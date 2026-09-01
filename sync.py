# -*- coding: utf-8 -*-
"""
IrwaneTraceForest (ITF) - Mode hors-ligne & synchronisation
Chaque installation (par société ou console Super-Admin) fonctionne
entièrement hors ligne sur sa base SQLite locale. Quand une connexion
Internet est détectée, l'utilisateur peut déclencher une synchronisation
en un clic vers le serveur central défini par le Super-Admin
(paramètres_sync.url_serveur_central) — ou laisser l'auto-détection le
proposer automatiquement.

Aucune donnée n'est envoyée sans connexion effective : verifier_connexion_internet()
est toujours appelé en premier et la synchronisation s'arrête net si elle échoue.
"""

import json
import socket
import urllib.request
import urllib.error
import datetime

from database import get_connection

TIMEOUT_SECONDES = 3

# Cibles de test de connectivité : DNS publics fiables, testés par simple
# connexion TCP (rapide, ne télécharge aucune donnée).
CIBLES_TEST = [
    ("8.8.8.8", 53),
    ("1.1.1.1", 53),
]


def verifier_connexion_internet() -> bool:
    """Vérifie une connectivité Internet réelle (pas seulement le réseau
    local). Ne lève jamais d'exception : retourne False au moindre doute."""
    for host, port in CIBLES_TEST:
        try:
            socket.setdefaulttimeout(TIMEOUT_SECONDES)
            s = socket.create_connection((host, port), timeout=TIMEOUT_SECONDES)
            s.close()
            return True
        except OSError:
            continue
    return False


def obtenir_parametres_sync() -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM parametres_sync WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else {"url_serveur_central": None, "auto_sync_actif": 0}


def definir_parametres_sync(url_serveur_central: str, auto_sync_actif: bool, modifie_par: str):
    """Réservé au Super-Admin (vérifié côté route, voir app.py)."""
    conn = get_connection()
    conn.execute(
        "UPDATE parametres_sync SET url_serveur_central = ?, auto_sync_actif = ?, "
        "modifie_par = ?, modifie_le = datetime('now') WHERE id = 1",
        (url_serveur_central or None, 1 if auto_sync_actif else 0, modifie_par),
    )
    conn.commit()
    conn.close()


TABLES_SYNCHRONISABLES = [
    "inventaire_arbres", "df10_registre", "lettres_voiture", "parc_usine_receptions",
    "etapes_transformation", "controle_charge_essieu", "scierie_debits",
    "contrats_export", "audit_log",
]


def _collecter_donnees_tenant(conn, tenant_id: int) -> dict:
    paquet = {}
    for table in TABLES_SYNCHRONISABLES:
        try:
            lignes = conn.execute(f"SELECT * FROM {table} WHERE tenant_id = ?", (tenant_id,)).fetchall()
            paquet[table] = [dict(r) for r in lignes]
        except Exception:
            paquet[table] = []
    return paquet


def synchroniser(tenant_id, declenche_par: str) -> dict:
    """Point d'entrée unique du bouton « Synchroniser ». Toujours sûr :
    - pas de connexion -> statut HORS_LIGNE, aucune donnée envoyée ;
    - pas de serveur configuré -> statut NON_CONFIGURE ;
    - erreur réseau/serveur -> statut ECHEC, message clair, rien n'est perdu
      localement (les données restent dans la base locale, à retenter plus tard).
    """
    params = obtenir_parametres_sync()
    url = params.get("url_serveur_central")

    if not verifier_connexion_internet():
        _journaliser(tenant_id, "HORS_LIGNE", "Aucune connexion Internet détectée.", 0, declenche_par)
        return {"ok": False, "statut": "HORS_LIGNE",
                "message": "Aucune connexion Internet détectée. Réessayez une fois connecté."}

    if not url:
        _journaliser(tenant_id, "NON_CONFIGURE", "Aucun serveur central défini par le Super-Admin.", 0, declenche_par)
        return {"ok": False, "statut": "NON_CONFIGURE",
                "message": "Aucun serveur central n'a encore été configuré (réservé au Super-Admin)."}

    conn = get_connection()
    try:
        if tenant_id:
            tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
            paquet = {
                "tenant_code": tenant["code"] if tenant else None,
                "tenant_id": tenant_id,
                "donnees": _collecter_donnees_tenant(conn, tenant_id),
                "envoye_le": datetime.datetime.now().isoformat(),
            }
            nb = sum(len(v) for v in paquet["donnees"].values())
        else:
            # Synchronisation globale déclenchée par le Super-Admin : un paquet par société.
            tenants = conn.execute("SELECT * FROM tenants").fetchall()
            paquet = {
                "tenant_code": "GLOBAL_SUPER_ADMIN",
                "tenant_id": None,
                "donnees": {t["code"]: _collecter_donnees_tenant(conn, t["id"]) for t in tenants},
                "envoye_le": datetime.datetime.now().isoformat(),
            }
            nb = sum(len(v2) for v1 in paquet["donnees"].values() for v2 in v1.values())

        corps = json.dumps(paquet, default=str).encode("utf-8")
        requete = urllib.request.Request(
            url.rstrip("/") + "/api/sync/push",
            data=corps,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(requete, timeout=10) as reponse:
            code = reponse.getcode()

        if 200 <= code < 300:
            if tenant_id:
                conn.execute("UPDATE tenants SET dernier_sync_le = datetime('now') WHERE id = ?", (tenant_id,))
            else:
                conn.execute("UPDATE tenants SET dernier_sync_le = datetime('now')")
            conn.commit()
            _journaliser(tenant_id, "OK", f"{nb} enregistrement(s) envoyés au serveur central.", nb, declenche_par)
            return {"ok": True, "statut": "OK",
                    "message": f"Synchronisation réussie — {nb} enregistrement(s) envoyés."}
        else:
            _journaliser(tenant_id, "ECHEC", f"Le serveur central a répondu avec le code {code}.", 0, declenche_par)
            return {"ok": False, "statut": "ECHEC", "message": f"Le serveur central a répondu avec le code {code}."}

    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _journaliser(tenant_id, "ECHEC", f"Serveur central injoignable : {exc}", 0, declenche_par)
        return {"ok": False, "statut": "ECHEC",
                "message": "Le serveur central n'a pas répondu. Vos données restent en sécurité "
                            "dans la base locale — réessayez plus tard."}
    finally:
        conn.close()


def _journaliser(tenant_id, statut, details, nb, declenche_par):
    conn = get_connection()
    conn.execute(
        "INSERT INTO sync_log (tenant_id, statut, details, nb_enregistrements, declenche_par) "
        "VALUES (?,?,?,?,?)",
        (tenant_id, statut, details, nb, declenche_par),
    )
    conn.commit()
    conn.close()


def historique_sync(tenant_id=None, limite=50) -> list:
    conn = get_connection()
    if tenant_id:
        rows = conn.execute(
            "SELECT * FROM sync_log WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
            (tenant_id, limite),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    conn.close()
    return rows
