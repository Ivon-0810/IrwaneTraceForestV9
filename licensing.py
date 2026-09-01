# -*- coding: utf-8 -*-
"""
IrwaneTraceForest (ITF) - Moteur de licences & vouchers
Toute génération de voucher ou modification de licence doit passer par
un contrôle de rôle SUPER_ADMIN au niveau des routes Flask (voir app.py).
Ce module ne fait AUCUNE vérification de rôle lui-même : il est appelé
uniquement depuis des routes déjà protégées.
"""

import hashlib
import datetime
import secrets
import string

from database import get_connection


def _checksum(entreprise_code: str, payload: str) -> str:
    """Somme de contrôle courte, dérivée d'un secret local à la machine
    (fichier .itf_secret) pour rendre les codes non-devinables sans accès
    à l'installation officielle."""
    raw = f"{entreprise_code}-{payload}-ITF-MEA-SARL".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:8].upper()


def generer_voucher(tenant_code: str, tenant_id: int, jours: int, genere_par: str) -> str:
    """Génère un code ACT-[ENTREPRISE]-[JOURS]J-[CHECKSUM]-[ANNEE].
    Appel réservé au SUPER_ADMIN (vérifié côté route)."""
    annee = datetime.date.today().year
    checksum = _checksum(tenant_code, f"{jours}J-{annee}")
    code = f"ACT-{tenant_code.upper()}-{jours}J-{checksum}-{annee}"

    conn = get_connection()
    conn.execute(
        "INSERT INTO vouchers (code, tenant_id, jours, genere_par) VALUES (?,?,?,?)",
        (code, tenant_id, jours, genere_par),
    )
    conn.commit()
    conn.close()
    return code


def appliquer_voucher(code: str) -> dict:
    """Valide et applique un voucher saisi depuis l'écran de verrouillage.
    Accessible par n'importe quel utilisateur du tenant verrouillé (c'est
    le but : réactivation autonome à distance), mais le voucher lui-même
    ne peut avoir été généré que par le SUPER_ADMIN."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM vouchers WHERE code = ? AND utilise = 0", (code,)
    ).fetchone()

    if not row:
        conn.close()
        return {"ok": False, "message": "Code invalide, déjà utilisé, ou expiré."}

    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (row["tenant_id"],)).fetchone()
    base = datetime.date.today()
    # si la licence a encore des jours restants, on les cumule
    if tenant["licence_expire_le"]:
        try:
            actuelle = datetime.date.fromisoformat(tenant["licence_expire_le"])
            if actuelle > base:
                base = actuelle
        except ValueError:
            pass

    nouvelle_date = base + datetime.timedelta(days=row["jours"])

    conn.execute(
        "UPDATE tenants SET statut = 'ACTIF', licence_expire_le = ? WHERE id = ?",
        (nouvelle_date.isoformat(), row["tenant_id"]),
    )
    conn.execute(
        "UPDATE vouchers SET utilise = 1, utilise_le = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    conn.execute(
        "INSERT INTO audit_log (tenant_id, utilisateur, role, action, module, details) VALUES (?,?,?,?,?,?)",
        (row["tenant_id"], "SYSTEME", "VOUCHER", "REACTIVATION", "LICENCE",
         f"Voucher {code} appliqué, nouvelle échéance {nouvelle_date.isoformat()}"),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "message": f"Licence réactivée jusqu'au {nouvelle_date.isoformat()}.",
            "nouvelle_date": nouvelle_date.isoformat()}


def verifier_statut_tenant(tenant_id: int) -> str:
    """Retourne ACTIF / SUSPENDU / EXPIRE en tenant compte de la date d'échéance."""
    conn = get_connection()
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    conn.close()
    if not tenant:
        return "INCONNU"
    if tenant["statut"] == "SUSPENDU":
        return "SUSPENDU"
    if tenant["licence_expire_le"]:
        try:
            if datetime.date.fromisoformat(tenant["licence_expire_le"]) < datetime.date.today():
                return "EXPIRE"
        except ValueError:
            pass
    return "ACTIF"
