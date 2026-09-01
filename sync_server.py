# -*- coding: utf-8 -*-
"""
IrwaneTraceForest (ITF) - Serveur central de synchronisation
À déployer séparément, sur une machine avec accès Internet permanent,
par Gauthier MBILI (Super-Admin). Chaque installation ITF (par société ou
console Super-Admin), une fois une connexion détectée, pousse ses données
locales vers ce serveur via POST /api/sync/push.

Lancement : python sync_server.py   -> http://0.0.0.0:6000
Ce script est indépendant de app.py : il peut tourner sur un serveur
distinct de celui utilisé pour les installations locales des sociétés.
"""

import json
import os
import sqlite3
import datetime

from flask import Flask, request, jsonify, render_template_string

DB_CENTRAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync_central.db")

app = Flask(__name__)


def get_connection():
    conn = sqlite3.connect(DB_CENTRAL)
    conn.row_factory = sqlite3.Row
    return conn


def init_central_db():
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS receptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_code TEXT NOT NULL,
            tenant_id INTEGER,
            nb_enregistrements INTEGER DEFAULT 0,
            paquet_json TEXT NOT NULL,
            adresse_ip TEXT,
            recu_le TEXT DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()


@app.route("/api/sync/push", methods=["POST"])
def sync_push():
    """Reçoit un paquet JSON {tenant_code, tenant_id, donnees, envoye_le}
    envoyé par sync.synchroniser() depuis une installation locale ITF."""
    try:
        paquet = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "message": "JSON invalide."}), 400

    if not paquet or "donnees" not in paquet:
        return jsonify({"ok": False, "message": "Paquet incomplet."}), 400

    tenant_code = paquet.get("tenant_code") or "INCONNU"
    tenant_id = paquet.get("tenant_id")
    donnees = paquet["donnees"]

    if tenant_code == "GLOBAL_SUPER_ADMIN":
        nb = sum(len(v2) for v1 in donnees.values() for v2 in v1.values())
    else:
        nb = sum(len(v) for v in donnees.values())

    conn = get_connection()
    conn.execute(
        "INSERT INTO receptions (tenant_code, tenant_id, nb_enregistrements, paquet_json, adresse_ip) "
        "VALUES (?,?,?,?,?)",
        (tenant_code, tenant_id, nb, json.dumps(donnees, default=str), request.remote_addr),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": f"{nb} enregistrement(s) reçus.", "recu_le": datetime.datetime.now().isoformat()})


@app.route("/api/sync/health")
def sync_health():
    return jsonify({"ok": True, "service": "IrwaneTraceForest - Serveur central de synchronisation"})


@app.route("/")
def tableau_bord_central():
    conn = get_connection()
    receptions = conn.execute(
        "SELECT id, tenant_code, nb_enregistrements, adresse_ip, recu_le FROM receptions "
        "ORDER BY id DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return render_template_string(
        """
        <!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
        <title>ITF — Serveur central de synchronisation</title>
        <style>
          body { font-family: Segoe UI, sans-serif; background:#0f172a; color:#e2e8f0; padding:30px; }
          h1 { color:#34d399; }
          table { width:100%; border-collapse: collapse; margin-top:20px; }
          th, td { padding:8px 12px; border-bottom:1px solid #334155; text-align:left; font-size:13px; }
          th { color:#94a3b8; text-transform:uppercase; font-size:11px; }
        </style></head><body>
        <h1>IrwaneTraceForest — Serveur central de synchronisation</h1>
        <p style="color:#94a3b8">Réceptions envoyées par les installations locales, une fois connectées à Internet.</p>
        <table>
          <tr><th>#</th><th>Société</th><th>Enregistrements</th><th>IP</th><th>Reçu le</th></tr>
          {% for r in receptions %}
          <tr><td>{{ r.id }}</td><td>{{ r.tenant_code }}</td><td>{{ r.nb_enregistrements }}</td>
              <td>{{ r.adresse_ip }}</td><td>{{ r.recu_le }}</td></tr>
          {% endfor %}
        </table>
        </body></html>
        """,
        receptions=receptions,
    )


if __name__ == "__main__":
    init_central_db()
    app.run(host="0.0.0.0", port=6000, debug=False)
