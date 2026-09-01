# -*- coding: utf-8 -*-
"""
IrwaneTraceForest (ITF) - Couche base de données
Conçu pour Gauthier MBILI (myvongauthier@gmail.com) - MEA SARL / Éditeur Système ITT

Ce module crée et amorce la base SQLite locale (itf.db) avec :
- les sociétés (tenants) pré-configurées,
- le compte SUPER_ADMIN exclusif,
- le catalogue botanique officiel,
- les tables métiers de traçabilité (inventaire, DF10, LV, parc usine, scierie,
  contrats, licences/vouchers, journal d'audit).
"""

import sqlite3
import hashlib
import os
import sys
import datetime


def _dossier_donnees_persistant() -> str:
    """Retourne un dossier stable pour la base SQLite, y compris lorsque
    l'application tourne comme exécutable PyInstaller --onefile (où
    sys.executable/__file__ pointent vers un dossier temporaire volatile
    à chaque lancement). Sous Windows : %APPDATA%/IrwaneTraceForest."""
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        dossier = os.path.join(base, "IrwaneTraceForest")
    else:
        dossier = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(dossier, exist_ok=True)
    return dossier


DB_PATH = os.path.join(_dossier_donnees_persistant(), "itf.db")

# ------------------------------------------------------------------
# Essences tropicales officielles d'Afrique Centrale (extrait de base)
# masse volumique moyenne (kg/m3) et DME légal (cm) - valeurs indicatives
# à ajuster selon les arrêtés en vigueur dans chaque pays.
# ------------------------------------------------------------------
ESSENCES_DEFAUT = [
    ("Ayous", 370, 60),
    ("Sapelli", 640, 60),
    ("Azobé", 1000, 60),
    ("Tali", 950, 60),
    ("Padouk", 750, 60),
    ("Fraké", 560, 60),
    ("Kossipo", 560, 60),
    ("Moabi", 700, 100),
    ("Okan", 950, 60),
    ("Iroko", 630, 80),
    ("Bilinga", 750, 60),
    ("Dibétou", 560, 60),
]

TENANTS_DEFAUT = [
    ("SOFOCAM SARL", "SOFOCAM"),
    ("ALPICAM INDUSTRIES", "ALPICAM"),
    ("PALLISCO SARL", "PALLISCO"),
    ("SEFAC CAMEROUN SA", "SEFAC"),
]

ROLES = [
    "SUPER_ADMIN",
    "ADMIN",
    "PROSPECTEUR_FORESTIER",
    "CHEF_PARC_FORESTIER",
    "CHEF_PARC_USINE",
    "RESPONSABLE_SCIERIE",
    "AUDITEUR_CONTROLEUR",
]


def hash_password(password: str, salt: str = "itf-mea-sarl") -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def generer_mot_de_passe_temporaire() -> str:
    """Mot de passe temporaire lisible, à communiquer hors-bande (SMS/WhatsApp/
    e-mail) par la personne qui crée le compte. L'utilisateur devra le
    remplacer par un mot de passe personnel dès sa première connexion."""
    import secrets
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "Itf-" + "".join(secrets.choice(alphabet) for _ in range(8))


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _colonne_existe(conn, table: str, colonne: str) -> bool:
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return colonne in cols


def _migrer_colonnes_additionnelles(conn):
    """Ajoute les nouvelles colonnes V2 aux tables existantes sans jamais
    supprimer ni renommer une colonne déjà présente. Sûr à rejouer à
    chaque démarrage (idempotent) et sûr sur une base existante en
    production contenant déjà des données."""

    # lettres_voiture : type de document (Grumes / Bois débité) + rattachement
    # au contrôle de charge à l'essieu.
    if not _colonne_existe(conn, "lettres_voiture", "type_lv"):
        conn.execute("ALTER TABLE lettres_voiture ADD COLUMN type_lv TEXT DEFAULT 'GRUMES'")
    if not _colonne_existe(conn, "lettres_voiture", "poids_total_kg"):
        conn.execute("ALTER TABLE lettres_voiture ADD COLUMN poids_total_kg REAL")
    if not _colonne_existe(conn, "lettres_voiture", "charge_conforme"):
        conn.execute("ALTER TABLE lettres_voiture ADD COLUMN charge_conforme INTEGER")
    if not _colonne_existe(conn, "lettres_voiture", "scierie_lot_ids"):
        # équivalent de df10_ids mais pour couvrir des lots de bois débité
        conn.execute("ALTER TABLE lettres_voiture ADD COLUMN scierie_lot_ids TEXT")

    # parc_usine_receptions : numéro officiel de Carnet Entrée Usine (CEU)
    if not _colonne_existe(conn, "parc_usine_receptions", "numero_ceu"):
        conn.execute("ALTER TABLE parc_usine_receptions ADD COLUMN numero_ceu TEXT")

    # scierie_debits : rattachement optionnel à une étape de transformation
    # et à une réception, pour permettre la généalogie complète souche->client
    if not _colonne_existe(conn, "scierie_debits", "reception_id"):
        conn.execute("ALTER TABLE scierie_debits ADD COLUMN reception_id INTEGER")
    if not _colonne_existe(conn, "scierie_debits", "numero_lot"):
        conn.execute("ALTER TABLE scierie_debits ADD COLUMN numero_lot TEXT")

    # contrats_export : rattachement des lots livrés pour la généalogie
    if not _colonne_existe(conn, "contrats_export", "scierie_lot_ids"):
        conn.execute("ALTER TABLE contrats_export ADD COLUMN scierie_lot_ids TEXT")

    # tenants : horodatage de la dernière synchronisation réussie (mode hors-ligne)
    if not _colonne_existe(conn, "tenants", "dernier_sync_le"):
        conn.execute("ALTER TABLE tenants ADD COLUMN dernier_sync_le TEXT")

    # ---- V4 : gestion des utilisateurs par le Super-Admin / les Admins ----
    # doit_changer_mdp : force la définition d'un mot de passe personnel à la
    # première connexion pour tout compte créé par un tiers (Super-Admin ou Admin).
    if not _colonne_existe(conn, "users", "doit_changer_mdp"):
        conn.execute("ALTER TABLE users ADD COLUMN doit_changer_mdp INTEGER NOT NULL DEFAULT 0")
    # cree_par : traçabilité de qui a créé le compte (Super-Admin ou Admin de société).
    if not _colonne_existe(conn, "users", "cree_par"):
        conn.execute("ALTER TABLE users ADD COLUMN cree_par TEXT")

    # Garde-fou base de données : un seul compte SUPER_ADMIN peut exister,
    # quelle que soit la route applicative utilisée pour insérer un utilisateur.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_super_admin_unique "
        "ON users(role) WHERE role = 'SUPER_ADMIN'"
    )

    conn.commit()


def init_db(reset: bool = False):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = get_connection()
    c = conn.cursor()

    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            code TEXT NOT NULL UNIQUE,
            statut TEXT NOT NULL DEFAULT 'ACTIF',      -- ACTIF / SUSPENDU / EXPIRE
            licence_expire_le TEXT,                     -- ISO date
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom_complet TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            tenant_id INTEGER,                           -- NULL pour SUPER_ADMIN
            actif INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );

        CREATE TABLE IF NOT EXISTS essences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            masse_volumique_kg_m3 REAL NOT NULL,
            dme_cm REAL NOT NULL,
            tenant_id INTEGER,                           -- NULL = catalogue global
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );

        CREATE TABLE IF NOT EXISTS vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            tenant_id INTEGER NOT NULL,
            jours INTEGER NOT NULL,
            utilise INTEGER NOT NULL DEFAULT 0,
            genere_par TEXT NOT NULL,
            genere_le TEXT DEFAULT (datetime('now')),
            utilise_le TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );

        CREATE TABLE IF NOT EXISTS inventaire_arbres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            ufa TEXT, aac TEXT, bloc TEXT,
            essence_id INTEGER,
            diametre_cm REAL,
            hauteur_m REAL,
            facteur_forme REAL DEFAULT 0.7,
            latitude REAL, longitude REAL,
            volume_m3 REAL,
            conforme_dme INTEGER,
            saisi_par TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id),
            FOREIGN KEY (essence_id) REFERENCES essences(id)
        );

        CREATE TABLE IF NOT EXISTS df10_registre (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            numero_df10 TEXT NOT NULL UNIQUE,
            numero_plaquette TEXT,
            ufa TEXT, aac TEXT,
            essence_id INTEGER,
            diametre_gros_bout_cm REAL,
            diametre_petit_bout_cm REAL,
            longueur_m REAL,
            volume_m3 REAL,
            statut TEXT DEFAULT 'ABATTU',                -- ABATTU / TRANSPORTE / RECU_USINE / SCIE
            valide INTEGER DEFAULT 0,
            saisi_par TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id),
            FOREIGN KEY (essence_id) REFERENCES essences(id)
        );

        CREATE TABLE IF NOT EXISTS lettres_voiture (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            numero_lv TEXT NOT NULL UNIQUE,
            tracteur TEXT, remorque TEXT, chauffeur TEXT, itineraire TEXT,
            nombre_billes INTEGER,
            cubage_total_m3 REAL,
            df10_ids TEXT,                                -- liste JSON des grumes couvertes
            statut TEXT DEFAULT 'EN_ROUTE',                -- EN_ROUTE / RECEPTIONNE
            saisi_par TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );

        CREATE TABLE IF NOT EXISTS parc_usine_receptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            numero_lv TEXT,
            fournisseur_tiers TEXT,
            numero_agrement TEXT, ifu TEXT,
            volume_recu_m3 REAL,
            conforme INTEGER DEFAULT 1,
            saisi_par TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );

        CREATE TABLE IF NOT EXISTS scierie_debits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            ligne_sciage TEXT,
            volume_grume_entree_m3 REAL,
            volume_sciages_m3 REAL,
            rendement_pct REAL,
            saisi_par TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );

        CREATE TABLE IF NOT EXISTS contrats_export (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            client TEXT, destination TEXT, incoterm TEXT,
            volume_alloue_m3 REAL,
            volume_livre_m3 REAL DEFAULT 0,
            saisi_par TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,
            utilisateur TEXT,
            role TEXT,
            action TEXT,
            module TEXT,
            details TEXT,
            session_ip TEXT DEFAULT '127.0.0.1',
            horodatage TEXT DEFAULT (datetime('now'))
        );

        -- ============================================================
        -- ÉVOLUTION V2 : étapes de transformation, CEU, charge à l'essieu,
        -- suivi des exports Module 8, préférence de thème utilisateur.
        -- Toutes les tables ci-dessous sont additives : elles n'altèrent
        -- aucune table existante et ne cassent aucun flux déjà en place.
        -- ============================================================

        -- Étapes industrielles tracées séparément et facultativement.
        -- Elles se rattachent à une grume DF10 et/ou à une réception usine,
        -- mais aucune des deux n'est obligatoire : une étape peut être
        -- saisie même si la référence amont n'a pas encore été saisie
        -- (règle de souplesse terrain demandée).
        CREATE TABLE IF NOT EXISTS etapes_transformation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            type_etape TEXT NOT NULL,        -- ECORCAGE / TRONCONNAGE / SCIAGE_PRIMAIRE / SECHAGE / RABOTAGE
            df10_id INTEGER,                  -- rattachement optionnel à une grume
            reception_id INTEGER,             -- rattachement optionnel à une réception usine (CEU)
            reference_libre TEXT,             -- identifiant de lot libre si aucune référence amont saisie
            volume_entree_m3 REAL,
            volume_sortie_m3 REAL,
            taux_perte_pct REAL,
            notes TEXT,
            saisi_par TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id),
            FOREIGN KEY (df10_id) REFERENCES df10_registre(id),
            FOREIGN KEY (reception_id) REFERENCES parc_usine_receptions(id)
        );

        -- Contrôle de charge à l'essieu, rattaché à une lettre de voiture.
        CREATE TABLE IF NOT EXISTS controle_charge_essieu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            lv_id INTEGER NOT NULL,
            poids_a_vide_kg REAL,
            poids_charge_kg REAL,
            poids_total_kg REAL,
            pma_reglementaire_kg REAL,
            conforme INTEGER,
            ecart_kg REAL,
            saisi_par TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id),
            FOREIGN KEY (lv_id) REFERENCES lettres_voiture(id)
        );

        -- Journal spécifique des exports du Module 8 (suite Python autonome),
        -- distinct de l'audit_log général pour un contrôle Super-Admin dédié.
        CREATE TABLE IF NOT EXISTS exports_module8 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utilisateur TEXT NOT NULL,
            nom_fichier TEXT NOT NULL,
            session_ip TEXT DEFAULT '127.0.0.1',
            horodatage TEXT DEFAULT (datetime('now'))
        );

        -- ============================================================
        -- ÉVOLUTION V3 : mode hors-ligne avec synchronisation à la
        -- détection d'une connexion Internet. Additive : n'altère aucune
        -- table existante.
        -- ============================================================

        -- Paramètres globaux de synchronisation, définis exclusivement par
        -- le Super-Admin (une seule ligne, id=1).
        CREATE TABLE IF NOT EXISTS parametres_sync (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            url_serveur_central TEXT,
            auto_sync_actif INTEGER NOT NULL DEFAULT 0,
            modifie_par TEXT,
            modifie_le TEXT DEFAULT (datetime('now'))
        );

        -- Historique des tentatives de synchronisation, par société.
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,
            statut TEXT NOT NULL,          -- OK / ECHEC / HORS_LIGNE / NON_CONFIGURE
            details TEXT,
            nb_enregistrements INTEGER DEFAULT 0,
            declenche_par TEXT,
            horodatage TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );
        """
    )
    conn.commit()

    _migrer_colonnes_additionnelles(conn)

    # --- Amorçage : paramètres de synchronisation (désactivée par défaut) ---
    c.execute(
        "INSERT OR IGNORE INTO parametres_sync (id, url_serveur_central, auto_sync_actif) VALUES (1, NULL, 0)"
    )
    conn.commit()

    # --- Amorçage : sociétés ---
    for nom, code in TENANTS_DEFAUT:
        c.execute(
            "INSERT OR IGNORE INTO tenants (nom, code, statut, licence_expire_le) VALUES (?,?,?,?)",
            (nom, code, "ACTIF", (datetime.date.today() + datetime.timedelta(days=30)).isoformat()),
        )

    # --- Amorçage : essences globales ---
    for nom, masse, dme in ESSENCES_DEFAUT:
        c.execute(
            "INSERT OR IGNORE INTO essences (nom, masse_volumique_kg_m3, dme_cm, tenant_id) VALUES (?,?,?,NULL)",
            (nom, masse, dme),
        )

    # --- Amorçage : SUPER_ADMIN exclusif Gauthier MBILI ---
    c.execute(
        """INSERT OR IGNORE INTO users (nom_complet, email, password_hash, role, tenant_id, actif)
           VALUES (?,?,?,?,NULL,1)""",
        ("Gauthier MBILI", "myvongauthier@gmail.com", hash_password("ChangeMoiMaintenant2026!"), "SUPER_ADMIN"),
    )

    # --- Un ADMIN de démonstration par société (mot de passe à changer) ---
    conn.commit()
    c.execute("SELECT id, code FROM tenants")
    for row in c.fetchall():
        demo_email = f"admin@{row['code'].lower()}.itf"
        c.execute(
            """INSERT OR IGNORE INTO users (nom_complet, email, password_hash, role, tenant_id, actif)
               VALUES (?,?,?,?,?,1)""",
            (f"DG {row['code']}", demo_email, hash_password("Demo2026!"), "ADMIN", row["id"]),
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db(reset=True)
    print(f"Base initialisée : {DB_PATH}")
