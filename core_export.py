# -*- coding: utf-8 -*-
"""
IrwaneTraceForest (ITF) - Module 8 : Suite Python autonome (irwanetrace_core.py)
Ce module ne fait AUCUNE vérification de rôle lui-même : il doit être
appelé UNIQUEMENT depuis une route Flask déjà protégée par
@super_admin_requis (voir app.py, route /module8/export). Ce doublement
(contrôle applicatif + fonction séparée) limite le risque qu'un futur
appel ailleurs dans le code oublie la vérification de rôle : toute
nouvelle route qui appellerait ce module doit explicitement passer par
le même décorateur.
"""

import io
import zipfile
import datetime

from database import DB_PATH, get_connection

CORE_SCRIPT_TEMPLATE = '''# -*- coding: utf-8 -*-
"""
irwanetrace_core.py — Suite Python autonome IrwaneTraceForest (ITF)
Généré le {date_generation} par le compte Super-Admin exclusif
(Gauthier MBILI, myvongauthier@gmail.com).

Ce script est un export EXCLUSIF réservé à un usage local hors-ligne.
Il embarque : les formules de cubage vectorisées et un lecteur de la
base SQLite jointe (itf_export.db) pour consultation / calculs locaux.

NE PAS REDISTRIBUER : ce fichier peut contenir des données d'entreprise
extraites de la base ITF au moment de l'export.
"""

import sqlite3
import math
import os

DB_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "itf_export.db")


def volume_arbre_sur_pied(diametre_cm, hauteur_m, facteur_forme=0.7):
    d_m = diametre_cm / 100.0
    return round((math.pi * d_m ** 2 / 4.0) * hauteur_m * facteur_forme, 4)


def volume_grume(diametre_gros_bout_cm, diametre_petit_bout_cm, longueur_m):
    dm = (diametre_gros_bout_cm + diametre_petit_bout_cm) / 2.0
    return round((math.pi * dm ** 2 / 40000.0) * longueur_m, 4)


def rendement_matiere(volume_grume_m3, volume_sciages_m3):
    if not volume_grume_m3:
        return 0.0
    return round((volume_sciages_m3 / volume_grume_m3) * 100.0, 2)


def resume_base_locale():
    if not os.path.exists(DB_LOCAL):
        print("Aucune base jointe (itf_export.db introuvable à côté de ce script).")
        return
    conn = sqlite3.connect(DB_LOCAL)
    conn.row_factory = sqlite3.Row
    for table in ["tenants", "df10_registre", "lettres_voiture", "scierie_debits"]:
        try:
            n = conn.execute(f"SELECT COUNT(*) c FROM {{table}}").fetchone()["c"]
            print(f"{{table}} : {{n}} enregistrement(s)")
        except sqlite3.OperationalError:
            pass
    conn.close()


if __name__ == "__main__":
    print("IrwaneTraceForest — Suite Python autonome (Module 8)")
    print("Export réservé exclusivement à Gauthier MBILI (Super-Admin).")
    resume_base_locale()
'''


def generer_suite_autonome(inclure_base: bool = True) -> bytes:
    """Construit une archive ZIP contenant irwanetrace_core.py et,
    optionnellement, une copie de la base SQLite courante. Retourne les
    octets du ZIP prêts à être servis en téléchargement."""
    date_generation = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    script = CORE_SCRIPT_TEMPLATE.format(date_generation=date_generation)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("irwanetrace_core.py", script)
        if inclure_base:
            with open(DB_PATH, "rb") as f:
                z.writestr("itf_export.db", f.read())
        z.writestr(
            "LISEZ-MOI.txt",
            "Suite Python autonome IrwaneTraceForest (ITF)\n"
            "Export réservé exclusivement au Super-Admin (Gauthier MBILI).\n"
            f"Généré le {date_generation}.\n"
            "Ne pas redistribuer ce fichier : il peut contenir des données d'entreprise.\n",
        )
    return buf.getvalue()


def journaliser_export(utilisateur: str, nom_fichier: str, session_ip: str = "127.0.0.1"):
    conn = get_connection()
    conn.execute(
        "INSERT INTO exports_module8 (utilisateur, nom_fichier, session_ip) VALUES (?,?,?)",
        (utilisateur, nom_fichier, session_ip),
    )
    conn.commit()
    conn.close()


def lister_exports() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM exports_module8 ORDER BY id DESC LIMIT 100").fetchall()
    conn.close()
    return rows
