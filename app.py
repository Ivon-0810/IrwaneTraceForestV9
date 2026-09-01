# -*- coding: utf-8 -*-
"""
IrwaneTraceForest (ITF) - ERP Traçabilité Forestière & Industrielle
Conçu et propriété exclusive de Gauthier MBILI (myvongauthier@gmail.com)
Société mère éditrice : MEA SARL / Éditeur Système ITT

Lancement local : python app.py  -> http://127.0.0.1:5000
"""

import io
import os
import json
import functools
import datetime

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash,
    jsonify, send_file, abort,
)

from database import init_db, get_connection, ROLES, hash_password, generer_mot_de_passe_temporaire, DB_PATH
from licensing import generer_voucher, appliquer_voucher, verifier_statut_tenant
from formulas import volume_arbre_sur_pied, volume_grume, rendement_matiere
from charge_essieu import verifier_charge, SEUILS_PMA
from pdf_documents import generer_pdf_df10, generer_pdf_lettre_voiture, generer_pdf_ceu
from excel_io import exporter_xlsx, importer_xlsx
from core_export import generer_suite_autonome, journaliser_export, lister_exports
from sync import (
    verifier_connexion_internet, obtenir_parametres_sync, definir_parametres_sync,
    synchroniser, historique_sync,
)

app = Flask(__name__)
app.secret_key = "itf-mea-sarl-changez-cette-cle-en-production"

THEMES_DISPONIBLES = ["emeraude", "sombre"]


@app.context_processor
def injecter_theme():
    tenant_nom = None
    if session.get("tenant_id"):
        conn = get_connection()
        row = conn.execute("SELECT nom FROM tenants WHERE id = ?", (session["tenant_id"],)).fetchone()
        conn.close()
        tenant_nom = row["nom"] if row else None
    return {"theme_actif": session.get("theme", "emeraude"), "tenant_courant_nom": tenant_nom}

# ------------------------------------------------------------------
# Utilitaires auth / rôles / audit
# ------------------------------------------------------------------

def log_audit(action, module, details=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO audit_log (tenant_id, utilisateur, role, action, module, details, session_ip) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            session.get("tenant_id"),
            session.get("email", "anonyme"),
            session.get("role", "?"),
            action,
            module,
            details,
            request.remote_addr,
        ),
    )
    conn.commit()
    conn.close()


def login_requis(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        # Changement de mot de passe obligatoire avant tout autre accès,
        # pour tout compte créé par un tiers (Super-Admin ou Admin).
        if session.get("doit_changer_mdp") and view.__name__ not in ("changer_mot_de_passe", "logout"):
            return redirect(url_for("changer_mot_de_passe"))
        # Le SUPER_ADMIN n'est jamais soumis au verrouillage de licence
        if session.get("role") != "SUPER_ADMIN":
            statut = verifier_statut_tenant(session.get("tenant_id"))
            if statut in ("SUSPENDU", "EXPIRE"):
                return redirect(url_for("lock_screen"))
        return view(*args, **kwargs)
    return wrapped


def roles_requis(*roles_autorises):
    def decorateur(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles_autorises:
                flash("Accès refusé : privilège insuffisant pour ce module.", "danger")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorateur


def super_admin_requis(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "SUPER_ADMIN":
            flash("Cette action est réservée exclusivement à Gauthier MBILI (SUPER_ADMIN).", "danger")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


ROLES_OPERATIONNELS = [
    "PROSPECTEUR_FORESTIER", "CHEF_PARC_FORESTIER", "CHEF_PARC_USINE",
    "RESPONSABLE_SCIERIE", "AUDITEUR_CONTROLEUR",
]


# ------------------------------------------------------------------
# Authentification
# ------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        from database import hash_password
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ? AND actif = 1", (email,)).fetchone()
        conn.close()
        if user and user["password_hash"] == hash_password(password):
            session["user_id"] = user["id"]
            session["nom_complet"] = user["nom_complet"]
            session["email"] = user["email"]
            session["role"] = user["role"]
            session["tenant_id"] = user["tenant_id"]
            session["doit_changer_mdp"] = bool(user["doit_changer_mdp"])
            log_audit("CONNEXION", "AUTH", f"Connexion de {user['email']}")
            if session["doit_changer_mdp"]:
                return redirect(url_for("changer_mot_de_passe"))
            if user["role"] != "SUPER_ADMIN":
                statut = verifier_statut_tenant(user["tenant_id"])
                if statut in ("SUSPENDU", "EXPIRE"):
                    return redirect(url_for("lock_screen"))
            return redirect(url_for("dashboard"))
        flash("Identifiants invalides.", "danger")
    return render_template("login.html")


@app.route("/recuperation-urgence")
def recuperation_urgence():
    """Récupération d'accès Super-Admin en cas de mot de passe perdu.

    Ne fonctionne QUE si un fichier nommé exactement RESET_SUPER_ADMIN.txt
    est présent, à la main, dans le même dossier que la base de données
    (preuve d'un accès physique à la machine — pas une faille distante).
    Le fichier est supprimé automatiquement après usage (à usage unique).
    """
    chemin_declencheur = os.path.join(os.path.dirname(DB_PATH), "RESET_SUPER_ADMIN.txt")
    if not os.path.exists(chemin_declencheur):
        abort(404)

    conn = get_connection()
    superadmin = conn.execute("SELECT * FROM users WHERE role = 'SUPER_ADMIN'").fetchone()
    if not superadmin:
        conn.close()
        abort(404)

    nouveau_mdp = generer_mot_de_passe_temporaire()
    conn.execute("UPDATE users SET password_hash = ?, doit_changer_mdp = 1 WHERE id = ?",
                 (hash_password(nouveau_mdp), superadmin["id"]))
    conn.execute(
        "INSERT INTO audit_log (tenant_id, utilisateur, role, action, module, details, session_ip) "
        "VALUES (NULL,?,?,?,?,?,?)",
        ("RECUPERATION_LOCALE", "SYSTEME", "REINITIALISATION_MDP", "AUTH",
         "Mot de passe Super-Admin réinitialisé via fichier de récupération local", request.remote_addr),
    )
    conn.commit()
    conn.close()

    try:
        os.remove(chemin_declencheur)
    except OSError:
        pass

    return render_template("recuperation_urgence.html", email=superadmin["email"], mot_de_passe=nouveau_mdp)


@app.route("/mon-compte", methods=["GET", "POST"])
@login_requis
def mon_compte():
    """Page « Mon compte », accessible à tout utilisateur connecté (y compris
    le Super-Admin) : consulter ses informations et changer soi-même son mot
    de passe, à tout moment — contrairement à /changer-mot-de-passe qui ne
    sert qu'au changement obligatoire imposé lors de la création du compte."""
    conn = get_connection()
    utilisateur = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (session.get("tenant_id"),)).fetchone() \
        if session.get("tenant_id") else None

    if request.method == "POST":
        actuel = request.form.get("mot_de_passe_actuel", "")
        nouveau = request.form.get("nouveau_mdp", "")
        confirmation = request.form.get("confirmation_mdp", "")
        if utilisateur["password_hash"] != hash_password(actuel):
            flash("Mot de passe actuel incorrect.", "danger")
        elif len(nouveau) < 8:
            flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "danger")
        elif nouveau != confirmation:
            flash("Les deux mots de passe ne correspondent pas.", "danger")
        else:
            conn.execute("UPDATE users SET password_hash = ?, doit_changer_mdp = 0 WHERE id = ?",
                         (hash_password(nouveau), session["user_id"]))
            conn.commit()
            session["doit_changer_mdp"] = False
            log_audit("CHANGEMENT_MDP", "AUTH", "Mot de passe changé depuis Mon compte")
            flash("Mot de passe mis à jour avec succès.", "success")

    conn.close()
    return render_template("mon_compte.html", utilisateur=utilisateur, tenant=tenant)


@app.route("/parametres")
@login_requis
@super_admin_requis
def parametres():
    """Console « Paramètres » du Super-Admin : point d'entrée unique vers
    tous les réglages globaux (mot de passe, licences, utilisateurs, sync)."""
    params_sync = obtenir_parametres_sync()
    conn = get_connection()
    nb_tenants = conn.execute("SELECT COUNT(*) c FROM tenants").fetchone()["c"]
    nb_utilisateurs = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    conn.close()
    return render_template("parametres.html", params_sync=params_sync,
                            nb_tenants=nb_tenants, nb_utilisateurs=nb_utilisateurs)


@app.route("/changer-mot-de-passe", methods=["GET", "POST"])
def changer_mot_de_passe():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        nouveau = request.form.get("nouveau_mdp", "")
        confirmation = request.form.get("confirmation_mdp", "")
        if len(nouveau) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères.", "danger")
        elif nouveau != confirmation:
            flash("Les deux mots de passe ne correspondent pas.", "danger")
        else:
            conn = get_connection()
            conn.execute("UPDATE users SET password_hash = ?, doit_changer_mdp = 0 WHERE id = ?",
                         (hash_password(nouveau), session["user_id"]))
            conn.commit()
            conn.close()
            session["doit_changer_mdp"] = False
            log_audit("CHANGEMENT_MDP", "AUTH", "Mot de passe personnel défini")
            flash("Mot de passe personnel défini avec succès.", "success")
            return redirect(url_for("dashboard"))
    return render_template("changer_mot_de_passe.html")


@app.route("/logout")
def logout():
    log_audit("DECONNEXION", "AUTH", "")
    session.clear()
    return redirect(url_for("login"))


@app.route("/lock")
def lock_screen():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_connection()
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (session.get("tenant_id"),)).fetchone()
    conn.close()
    return render_template("lock.html", tenant=tenant)


@app.route("/lock/activer", methods=["POST"])
def lock_activer():
    code = request.form.get("code", "").strip().upper()
    resultat = appliquer_voucher(code)
    if resultat["ok"]:
        flash(resultat["message"], "success")
        return redirect(url_for("dashboard"))
    flash(resultat["message"], "danger")
    return redirect(url_for("lock_screen"))


# ------------------------------------------------------------------
# Tableau de bord
# ------------------------------------------------------------------

@app.route("/dashboard")
@login_requis
def dashboard():
    conn = get_connection()
    tenant = None
    stats = {}
    if session["role"] == "SUPER_ADMIN":
        tenants = conn.execute("SELECT * FROM tenants ORDER BY nom").fetchall()
        stats["nb_tenants"] = len(tenants)
        stats["nb_utilisateurs"] = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        stats["evenements_audit"] = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        conn.close()
        return render_template("dashboard_super_admin.html", tenants=tenants, stats=stats,
                                today=datetime.date.today().isoformat())

    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (session["tenant_id"],)).fetchone()
    stats["nb_arbres"] = conn.execute(
        "SELECT COUNT(*) c FROM inventaire_arbres WHERE tenant_id = ?", (session["tenant_id"],)
    ).fetchone()["c"]
    stats["nb_df10"] = conn.execute(
        "SELECT COUNT(*) c FROM df10_registre WHERE tenant_id = ?", (session["tenant_id"],)
    ).fetchone()["c"]
    stats["volume_df10_m3"] = conn.execute(
        "SELECT COALESCE(SUM(volume_m3),0) v FROM df10_registre WHERE tenant_id = ?", (session["tenant_id"],)
    ).fetchone()["v"]
    stats["nb_lv"] = conn.execute(
        "SELECT COUNT(*) c FROM lettres_voiture WHERE tenant_id = ?", (session["tenant_id"],)
    ).fetchone()["c"]
    stats["rendement_moyen"] = conn.execute(
        "SELECT COALESCE(AVG(rendement_pct),0) r FROM scierie_debits WHERE tenant_id = ?", (session["tenant_id"],)
    ).fetchone()["r"]
    conn.close()
    return render_template("dashboard.html", tenant=tenant, stats=stats)


# ------------------------------------------------------------------
# SUPER_ADMIN : gestion exclusive des licences / vouchers / tenants
# ------------------------------------------------------------------

@app.route("/super-admin/tenants/<int:tenant_id>/suspendre", methods=["POST"])
@login_requis
@super_admin_requis
def suspendre_tenant(tenant_id):
    conn = get_connection()
    conn.execute("UPDATE tenants SET statut = 'SUSPENDU' WHERE id = ?", (tenant_id,))
    conn.commit()
    conn.close()
    log_audit("SUSPENSION_LICENCE", "LICENCE", f"tenant_id={tenant_id}")
    flash("Société suspendue.", "warning")
    return redirect(url_for("dashboard"))


@app.route("/super-admin/tenants/<int:tenant_id>/reactiver", methods=["POST"])
@login_requis
@super_admin_requis
def reactiver_tenant(tenant_id):
    jours = int(request.form.get("jours", 30))
    nouvelle_date = (datetime.date.today() + datetime.timedelta(days=jours)).isoformat()
    conn = get_connection()
    conn.execute(
        "UPDATE tenants SET statut = 'ACTIF', licence_expire_le = ? WHERE id = ?",
        (nouvelle_date, tenant_id),
    )
    conn.commit()
    conn.close()
    log_audit("RENOUVELLEMENT_DIRECT", "LICENCE", f"tenant_id={tenant_id} jusqu_au={nouvelle_date}")
    flash(f"Licence renouvelée jusqu'au {nouvelle_date}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/super-admin/tenants/<int:tenant_id>/voucher", methods=["POST"])
@login_requis
@super_admin_requis
def generer_voucher_route(tenant_id):
    jours = int(request.form.get("jours", 30))
    conn = get_connection()
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    conn.close()
    code = generer_voucher(tenant["code"], tenant_id, jours, session["email"])
    log_audit("GENERATION_VOUCHER", "LICENCE", f"{code} pour tenant_id={tenant_id}")
    flash(f"Voucher généré : {code}", "success")
    return redirect(url_for("dashboard"))


@app.route("/super-admin/tenants/creer", methods=["POST"])
@login_requis
@super_admin_requis
def creer_tenant():
    nom = request.form.get("nom", "").strip()
    code = request.form.get("code", "").strip().upper()
    conn = get_connection()
    conn.execute(
        "INSERT INTO tenants (nom, code, statut, licence_expire_le) VALUES (?,?,?,?)",
        (nom, code, "ACTIF", (datetime.date.today() + datetime.timedelta(days=30)).isoformat()),
    )
    conn.commit()
    conn.close()
    log_audit("CREATION_TENANT", "LICENCE", f"{nom} ({code})")
    flash(f"Société {nom} créée.", "success")
    return redirect(url_for("dashboard"))


# ------------------------------------------------------------------
# Module 1 : Inventaires forestiers
# ------------------------------------------------------------------

@app.route("/inventaire", methods=["GET", "POST"])
@login_requis
@roles_requis("PROSPECTEUR_FORESTIER", "ADMIN", "SUPER_ADMIN", "AUDITEUR_CONTROLEUR")
def inventaire():
    conn = get_connection()
    if request.method == "POST" and session["role"] != "AUDITEUR_CONTROLEUR":
        essence_id = int(request.form["essence_id"])
        diametre = float(request.form["diametre_cm"])
        hauteur = float(request.form["hauteur_m"])
        facteur = float(request.form.get("facteur_forme", 0.7))
        essence = conn.execute("SELECT * FROM essences WHERE id = ?", (essence_id,)).fetchone()
        volume = volume_arbre_sur_pied(diametre, hauteur, facteur)
        conforme = 1 if diametre >= essence["dme_cm"] else 0
        conn.execute(
            """INSERT INTO inventaire_arbres
               (tenant_id, ufa, aac, bloc, essence_id, diametre_cm, hauteur_m, facteur_forme,
                latitude, longitude, volume_m3, conforme_dme, saisi_par)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session["tenant_id"], request.form.get("ufa"), request.form.get("aac"), request.form.get("bloc"),
             essence_id, diametre, hauteur, facteur,
             request.form.get("latitude") or None, request.form.get("longitude") or None,
             volume, conforme, session["email"]),
        )
        conn.commit()
        log_audit("CREATION", "INVENTAIRE", f"{diametre}cm / {essence['nom']} / {volume}m3")
        flash(f"Arbre enregistré — volume estimé {volume} m³ "
              f"({'conforme' if conforme else 'NON conforme DME'}).",
              "success" if conforme else "warning")

    essences = conn.execute("SELECT * FROM essences ORDER BY nom").fetchall()
    arbres = conn.execute(
        "SELECT ia.*, e.nom AS essence_nom FROM inventaire_arbres ia "
        "JOIN essences e ON e.id = ia.essence_id WHERE ia.tenant_id = ? "
        "ORDER BY ia.id DESC LIMIT 100",
        (session["tenant_id"],),
    ).fetchall()
    conn.close()
    return render_template("inventaire.html", essences=essences, arbres=arbres)


# ------------------------------------------------------------------
# Module 2 : Registre DF10 (abattage)
# ------------------------------------------------------------------

@app.route("/df10", methods=["GET", "POST"])
@login_requis
@roles_requis("CHEF_PARC_FORESTIER", "ADMIN", "SUPER_ADMIN", "AUDITEUR_CONTROLEUR")
def df10():
    conn = get_connection()
    if request.method == "POST" and session["role"] != "AUDITEUR_CONTROLEUR":
        ufa = request.form.get("ufa", "")
        aac = request.form.get("aac", "")
        seq = conn.execute(
            "SELECT COUNT(*) c FROM df10_registre WHERE tenant_id = ?", (session["tenant_id"],)
        ).fetchone()["c"] + 1
        numero_df10 = f"DF10-{ufa}-{aac}-{seq:05d}"
        d1 = float(request.form["diametre_gros_bout_cm"])
        d2 = float(request.form["diametre_petit_bout_cm"])
        longueur = float(request.form["longueur_m"])
        volume = volume_grume(d1, d2, longueur)
        conn.execute(
            """INSERT INTO df10_registre
               (tenant_id, numero_df10, numero_plaquette, ufa, aac, essence_id,
                diametre_gros_bout_cm, diametre_petit_bout_cm, longueur_m, volume_m3, saisi_par)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (session["tenant_id"], numero_df10, request.form.get("numero_plaquette"), ufa, aac,
             int(request.form["essence_id"]), d1, d2, longueur, volume, session["email"]),
        )
        conn.commit()
        log_audit("CREATION", "DF10", f"{numero_df10} / {volume}m3")
        flash(f"Grume enregistrée sous {numero_df10} — {volume} m³.", "success")

    essences = conn.execute("SELECT * FROM essences ORDER BY nom").fetchall()
    grumes = conn.execute(
        "SELECT g.*, e.nom AS essence_nom FROM df10_registre g "
        "JOIN essences e ON e.id = g.essence_id WHERE g.tenant_id = ? "
        "ORDER BY g.id DESC LIMIT 100",
        (session["tenant_id"],),
    ).fetchall()
    conn.close()
    return render_template("df10.html", essences=essences, grumes=grumes)


@app.route("/df10/<int:grume_id>/pdf")
@login_requis
def df10_pdf(grume_id):
    conn = get_connection()
    grume = conn.execute(
        "SELECT g.*, e.nom AS essence_nom FROM df10_registre g JOIN essences e ON e.id=g.essence_id "
        "WHERE g.id = ? AND g.tenant_id = ?", (grume_id, session["tenant_id"])).fetchone()
    if not grume:
        conn.close()
        abort(404)
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (session["tenant_id"],)).fetchone()
    conn.close()
    pdf_bytes = generer_pdf_df10(dict(grume), tenant["nom"] if tenant else "")
    log_audit("EXPORT_PDF", "DF10", grume["numero_df10"])
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
                      download_name=f"{grume['numero_df10']}.pdf")


# ------------------------------------------------------------------
# Module 3 : Transport / Lettres de voiture
# ------------------------------------------------------------------

@app.route("/transport", methods=["GET", "POST"])
@login_requis
@roles_requis("CHEF_PARC_FORESTIER", "ADMIN", "SUPER_ADMIN", "AUDITEUR_CONTROLEUR")
def transport():
    conn = get_connection()
    if request.method == "POST" and session["role"] != "AUDITEUR_CONTROLEUR":
        type_lv = request.form.get("type_lv", "GRUMES")
        cubage_total = 0.0
        references_ids = []

        if type_lv == "BOIS_DEBITE":
            lot_ids = request.form.getlist("scierie_lot_ids")
            for lid in lot_ids:
                row = conn.execute("SELECT volume_sciages_m3 FROM scierie_debits WHERE id = ?", (lid,)).fetchone()
                if row:
                    cubage_total += row["volume_sciages_m3"] or 0
            references_ids = lot_ids
        else:
            df10_ids = request.form.getlist("df10_ids")
            for did in df10_ids:
                row = conn.execute("SELECT volume_m3 FROM df10_registre WHERE id = ?", (did,)).fetchone()
                if row:
                    cubage_total += row["volume_m3"] or 0
            references_ids = df10_ids

        seq = conn.execute(
            "SELECT COUNT(*) c FROM lettres_voiture WHERE tenant_id = ?", (session["tenant_id"],)
        ).fetchone()["c"] + 1
        numero_lv = f"LV-{session['tenant_id']}-{seq:05d}"

        # Contrôle de charge à l'essieu (facultatif : si les poids ne sont pas
        # saisis, la lettre de voiture est tout de même émise sans blocage).
        poids_a_vide = request.form.get("poids_a_vide_kg")
        poids_charge = request.form.get("poids_charge_kg")
        categorie_pma = request.form.get("categorie_pma", "STANDARD")
        resultat_charge = None
        if poids_a_vide and poids_charge:
            resultat_charge = verifier_charge(float(poids_a_vide), float(poids_charge), categorie_pma)

        conn.execute(
            """INSERT INTO lettres_voiture
               (tenant_id, numero_lv, tracteur, remorque, chauffeur, itineraire,
                nombre_billes, cubage_total_m3, df10_ids, scierie_lot_ids, type_lv,
                poids_total_kg, charge_conforme, saisi_par)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session["tenant_id"], numero_lv, request.form.get("tracteur"), request.form.get("remorque"),
             request.form.get("chauffeur"), request.form.get("itineraire"),
             len(references_ids), round(cubage_total, 4),
             json.dumps(references_ids) if type_lv != "BOIS_DEBITE" else None,
             json.dumps(references_ids) if type_lv == "BOIS_DEBITE" else None,
             type_lv,
             resultat_charge["poids_total_kg"] if resultat_charge else None,
             (1 if resultat_charge["conforme"] else 0) if resultat_charge else None,
             session["email"]),
        )
        lv_id = conn.execute("SELECT id FROM lettres_voiture WHERE numero_lv = ?", (numero_lv,)).fetchone()["id"]

        if resultat_charge:
            conn.execute(
                """INSERT INTO controle_charge_essieu
                   (tenant_id, lv_id, poids_a_vide_kg, poids_charge_kg, poids_total_kg,
                    pma_reglementaire_kg, conforme, ecart_kg, saisi_par)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (session["tenant_id"], lv_id, resultat_charge["poids_a_vide_kg"], resultat_charge["poids_charge_kg"],
                 resultat_charge["poids_total_kg"], resultat_charge["pma_reglementaire_kg"],
                 1 if resultat_charge["conforme"] else 0, resultat_charge["ecart_kg"], session["email"]),
            )

        if type_lv != "BOIS_DEBITE":
            for did in references_ids:
                conn.execute("UPDATE df10_registre SET statut = 'TRANSPORTE' WHERE id = ?", (did,))

        conn.commit()
        detail_charge = ""
        if resultat_charge:
            detail_charge = f" / charge {resultat_charge['poids_total_kg']}kg " \
                             f"({'conforme' if resultat_charge['conforme'] else 'NON CONFORME'})"
        log_audit("CREATION", "TRANSPORT", f"{numero_lv} / {cubage_total}m3 / {len(references_ids)} unités{detail_charge}")

        if resultat_charge and not resultat_charge["conforme"]:
            flash(f"⚠️ Lettre de voiture {numero_lv} émise mais SURCHARGE détectée : "
                  f"{resultat_charge['poids_total_kg']}kg pour un PMA de {resultat_charge['pma_reglementaire_kg']}kg.",
                  "danger")
        else:
            flash(f"Lettre de voiture {numero_lv} émise — {len(references_ids)} unités, {round(cubage_total,2)} m³.",
                  "success")

    grumes_dispo = conn.execute(
        "SELECT * FROM df10_registre WHERE tenant_id = ? AND statut = 'ABATTU' ORDER BY id DESC",
        (session["tenant_id"],),
    ).fetchall()
    lots_dispo = conn.execute(
        "SELECT * FROM scierie_debits WHERE tenant_id = ? ORDER BY id DESC LIMIT 100",
        (session["tenant_id"],),
    ).fetchall()
    lvs = conn.execute(
        "SELECT * FROM lettres_voiture WHERE tenant_id = ? ORDER BY id DESC LIMIT 50",
        (session["tenant_id"],),
    ).fetchall()
    conn.close()
    return render_template("transport.html", grumes_dispo=grumes_dispo, lots_dispo=lots_dispo,
                            lvs=lvs, seuils_pma=SEUILS_PMA)


@app.route("/transport/<int:lv_id>/pdf")
@login_requis
def transport_pdf(lv_id):
    conn = get_connection()
    lv = conn.execute("SELECT * FROM lettres_voiture WHERE id = ? AND tenant_id = ?",
                       (lv_id, session["tenant_id"])).fetchone()
    if not lv:
        conn.close()
        abort(404)
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (session["tenant_id"],)).fetchone()
    charge = conn.execute("SELECT * FROM controle_charge_essieu WHERE lv_id = ? ORDER BY id DESC LIMIT 1",
                           (lv_id,)).fetchone()

    if lv["type_lv"] == "BOIS_DEBITE":
        ids = json.loads(lv["scierie_lot_ids"] or "[]")
        detail = []
        for lid in ids:
            row = conn.execute("SELECT * FROM scierie_debits WHERE id = ?", (lid,)).fetchone()
            if row:
                d = dict(row)
                d["numero_lot"] = row["numero_lot"] or f"LOT-{row['id']}"
                detail.append(d)
    else:
        ids = json.loads(lv["df10_ids"] or "[]")
        detail = []
        for did in ids:
            row = conn.execute(
                "SELECT g.*, e.nom AS essence_nom FROM df10_registre g JOIN essences e ON e.id=g.essence_id "
                "WHERE g.id = ?", (did,)).fetchone()
            if row:
                detail.append(dict(row))
    conn.close()

    pdf_bytes = generer_pdf_lettre_voiture(dict(lv), tenant["nom"] if tenant else "", detail,
                                            dict(charge) if charge else None)
    log_audit("EXPORT_PDF", "TRANSPORT", lv["numero_lv"])
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                      as_attachment=True, download_name=f"{lv['numero_lv']}.pdf")


# ------------------------------------------------------------------
# Module 4bis : Étapes de transformation (Écorçage, Tronçonnage, Sciage
# primaire, Séchage, Rabotage/Finition) - tracées séparément, facultatives,
# non bloquantes : aucune référence amont (DF10 / réception) n'est obligatoire.
# ------------------------------------------------------------------

TYPES_ETAPE = ["ECORCAGE", "TRONCONNAGE", "SCIAGE_PRIMAIRE", "SECHAGE", "RABOTAGE"]


@app.route("/transformation", methods=["GET", "POST"])
@login_requis
@roles_requis("CHEF_PARC_USINE", "RESPONSABLE_SCIERIE", "ADMIN", "SUPER_ADMIN", "AUDITEUR_CONTROLEUR")
def transformation():
    conn = get_connection()
    if request.method == "POST" and session["role"] != "AUDITEUR_CONTROLEUR":
        v_entree = request.form.get("volume_entree_m3") or None
        v_sortie = request.form.get("volume_sortie_m3") or None
        taux_perte = None
        if v_entree and v_sortie:
            v_entree_f, v_sortie_f = float(v_entree), float(v_sortie)
            if v_entree_f:
                taux_perte = round((1 - v_sortie_f / v_entree_f) * 100, 2)
        conn.execute(
            """INSERT INTO etapes_transformation
               (tenant_id, type_etape, df10_id, reception_id, reference_libre,
                volume_entree_m3, volume_sortie_m3, taux_perte_pct, notes, saisi_par)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (session["tenant_id"], request.form["type_etape"],
             request.form.get("df10_id") or None, request.form.get("reception_id") or None,
             request.form.get("reference_libre") or None,
             float(v_entree) if v_entree else None, float(v_sortie) if v_sortie else None,
             taux_perte, request.form.get("notes"), session["email"]),
        )
        conn.commit()
        log_audit("CREATION", "TRANSFORMATION", f"{request.form['type_etape']}")
        flash("Étape de transformation enregistrée.", "success")

    grumes = conn.execute(
        "SELECT id, numero_df10 FROM df10_registre WHERE tenant_id = ? ORDER BY id DESC LIMIT 200",
        (session["tenant_id"],),
    ).fetchall()
    receptions = conn.execute(
        "SELECT id, numero_ceu, numero_lv FROM parc_usine_receptions WHERE tenant_id = ? ORDER BY id DESC LIMIT 200",
        (session["tenant_id"],),
    ).fetchall()
    etapes = conn.execute(
        """SELECT e.*, g.numero_df10, r.numero_ceu FROM etapes_transformation e
           LEFT JOIN df10_registre g ON g.id = e.df10_id
           LEFT JOIN parc_usine_receptions r ON r.id = e.reception_id
           WHERE e.tenant_id = ? ORDER BY e.id DESC LIMIT 100""",
        (session["tenant_id"],),
    ).fetchall()
    conn.close()
    return render_template("transformation.html", grumes=grumes, receptions=receptions,
                            etapes=etapes, types_etape=TYPES_ETAPE)


# ------------------------------------------------------------------
# Module 4 : Parc à grumes usine & achats tiers
# ------------------------------------------------------------------

@app.route("/parc-usine", methods=["GET", "POST"])
@login_requis
@roles_requis("CHEF_PARC_USINE", "ADMIN", "SUPER_ADMIN", "AUDITEUR_CONTROLEUR")
def parc_usine():
    conn = get_connection()
    if request.method == "POST" and session["role"] != "AUDITEUR_CONTROLEUR":
        numero_lv = request.form.get("numero_lv", "")
        volume = float(request.form.get("volume_recu_m3", 0))
        seq = conn.execute(
            "SELECT COUNT(*) c FROM parc_usine_receptions WHERE tenant_id = ?", (session["tenant_id"],)
        ).fetchone()["c"] + 1
        numero_ceu = f"CEU-{session['tenant_id']}-{seq:05d}"
        conn.execute(
            """INSERT INTO parc_usine_receptions
               (tenant_id, numero_ceu, numero_lv, fournisseur_tiers, numero_agrement, ifu,
                volume_recu_m3, conforme, saisi_par)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (session["tenant_id"], numero_ceu, numero_lv, request.form.get("fournisseur_tiers"),
             request.form.get("numero_agrement"), request.form.get("ifu"), volume,
             1 if request.form.get("conforme") == "on" else 0, session["email"]),
        )
        if numero_lv:
            conn.execute("UPDATE lettres_voiture SET statut = 'RECEPTIONNE' WHERE numero_lv = ? AND tenant_id = ?",
                         (numero_lv, session["tenant_id"]))
        conn.commit()
        log_audit("RECEPTION", "PARC_USINE", f"{numero_ceu} / {numero_lv} / {volume}m3")
        flash(f"Réception enregistrée sous {numero_ceu} — {volume} m³.", "success")

    lvs_en_route = conn.execute(
        "SELECT * FROM lettres_voiture WHERE tenant_id = ? AND statut = 'EN_ROUTE' ORDER BY id DESC",
        (session["tenant_id"],),
    ).fetchall()
    receptions = conn.execute(
        "SELECT * FROM parc_usine_receptions WHERE tenant_id = ? ORDER BY id DESC LIMIT 50",
        (session["tenant_id"],),
    ).fetchall()
    conn.close()
    return render_template("parc_usine.html", lvs_en_route=lvs_en_route, receptions=receptions)


@app.route("/parc-usine/<int:reception_id>/pdf")
@login_requis
def parc_usine_pdf(reception_id):
    conn = get_connection()
    reception = conn.execute("SELECT * FROM parc_usine_receptions WHERE id = ? AND tenant_id = ?",
                              (reception_id, session["tenant_id"])).fetchone()
    if not reception:
        conn.close()
        abort(404)
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (session["tenant_id"],)).fetchone()
    conn.close()
    pdf_bytes = generer_pdf_ceu(dict(reception), tenant["nom"] if tenant else "")
    log_audit("EXPORT_PDF", "PARC_USINE", reception["numero_ceu"] or "")
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
                      download_name=f"{reception['numero_ceu'] or 'CEU'}.pdf")


# ------------------------------------------------------------------
# Module 5 : Scierie & rendements matière
# ------------------------------------------------------------------

@app.route("/scierie", methods=["GET", "POST"])
@login_requis
@roles_requis("RESPONSABLE_SCIERIE", "ADMIN", "SUPER_ADMIN", "AUDITEUR_CONTROLEUR")
def scierie():
    conn = get_connection()
    if request.method == "POST" and session["role"] != "AUDITEUR_CONTROLEUR":
        v_grume = float(request.form["volume_grume_entree_m3"])
        v_sciages = float(request.form["volume_sciages_m3"])
        rendement = rendement_matiere(v_grume, v_sciages)
        seq = conn.execute(
            "SELECT COUNT(*) c FROM scierie_debits WHERE tenant_id = ?", (session["tenant_id"],)
        ).fetchone()["c"] + 1
        numero_lot = f"LOT-{session['tenant_id']}-{seq:05d}"
        conn.execute(
            """INSERT INTO scierie_debits
               (tenant_id, ligne_sciage, volume_grume_entree_m3, volume_sciages_m3, rendement_pct,
                reception_id, numero_lot, saisi_par)
               VALUES (?,?,?,?,?,?,?,?)""",
            (session["tenant_id"], request.form.get("ligne_sciage"), v_grume, v_sciages, rendement,
             request.form.get("reception_id") or None, numero_lot, session["email"]),
        )
        conn.commit()
        log_audit("CREATION", "SCIERIE", f"{numero_lot} / rendement={rendement}%")
        alerte = "warning" if rendement < 40 else "success"
        flash(f"Débit {numero_lot} enregistré — rendement matière {rendement}%.", alerte)

    receptions = conn.execute(
        "SELECT id, numero_ceu, fournisseur_tiers FROM parc_usine_receptions WHERE tenant_id = ? "
        "ORDER BY id DESC LIMIT 200",
        (session["tenant_id"],),
    ).fetchall()
    debits = conn.execute(
        "SELECT * FROM scierie_debits WHERE tenant_id = ? ORDER BY id DESC LIMIT 50",
        (session["tenant_id"],),
    ).fetchall()
    conn.close()
    return render_template("scierie.html", debits=debits, receptions=receptions)


# ------------------------------------------------------------------
# Module 6 : Contrats commerciaux & exports
# ------------------------------------------------------------------

@app.route("/contrats", methods=["GET", "POST"])
@login_requis
@roles_requis("ADMIN", "SUPER_ADMIN", "AUDITEUR_CONTROLEUR")
def contrats():
    conn = get_connection()
    if request.method == "POST" and session["role"] != "AUDITEUR_CONTROLEUR":
        conn.execute(
            """INSERT INTO contrats_export
               (tenant_id, client, destination, incoterm, volume_alloue_m3, saisi_par)
               VALUES (?,?,?,?,?,?)""",
            (session["tenant_id"], request.form.get("client"), request.form.get("destination"),
             request.form.get("incoterm"), float(request.form.get("volume_alloue_m3", 0)), session["email"]),
        )
        conn.commit()
        log_audit("CREATION", "CONTRAT", request.form.get("client", ""))
        flash("Contrat enregistré.", "success")

    liste = conn.execute(
        "SELECT * FROM contrats_export WHERE tenant_id = ? ORDER BY id DESC LIMIT 50",
        (session["tenant_id"],),
    ).fetchall()
    conn.close()
    return render_template("contrats.html", liste=liste)


# ------------------------------------------------------------------
# Module 7 : Journal d'audit / généalogie
# ------------------------------------------------------------------

@app.route("/audit")
@login_requis
@roles_requis("AUDITEUR_CONTROLEUR", "ADMIN", "SUPER_ADMIN")
def audit():
    conn = get_connection()
    if session["role"] == "SUPER_ADMIN":
        logs = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 300").fetchall()
    else:
        logs = conn.execute(
            "SELECT * FROM audit_log WHERE tenant_id = ? ORDER BY id DESC LIMIT 300",
            (session["tenant_id"],),
        ).fetchall()
    conn.close()
    return render_template("audit.html", logs=logs)


@app.route("/genealogie/<numero_df10>")
@login_requis
def genealogie(numero_df10):
    """Remonte la souche à la destination finale : DF10 -> Lettre de voiture
    -> réception usine (CEU) -> étapes de transformation (facultatives) ->
    lot scierie -> lettre de voiture bois débité -> contrat d'export, avec
    la liste des intervenants (saisi_par) rencontrés à chaque étape."""
    conn = get_connection()
    grume = conn.execute(
        "SELECT g.*, e.nom AS essence_nom FROM df10_registre g JOIN essences e ON e.id=g.essence_id "
        "WHERE g.numero_df10 = ? AND g.tenant_id = ?",
        (numero_df10, session["tenant_id"]),
    ).fetchone()
    if not grume:
        conn.close()
        flash("Numéro DF10 introuvable.", "danger")
        return redirect(url_for("audit"))

    intervenants = [grume["saisi_par"]]

    lvs_grumes = conn.execute(
        "SELECT * FROM lettres_voiture WHERE tenant_id = ? AND (type_lv IS NULL OR type_lv = 'GRUMES')",
        (session["tenant_id"],),
    ).fetchall()
    lv_associee = None
    for lv in lvs_grumes:
        ids = json.loads(lv["df10_ids"] or "[]")
        if numero_df10 in ids or str(grume["id"]) in ids:
            lv_associee = lv
            intervenants.append(lv["saisi_par"])
            break

    reception = None
    if lv_associee:
        reception = conn.execute(
            "SELECT * FROM parc_usine_receptions WHERE numero_lv = ? AND tenant_id = ?",
            (lv_associee["numero_lv"], session["tenant_id"]),
        ).fetchone()
        if reception:
            intervenants.append(reception["saisi_par"])

    etapes = conn.execute(
        "SELECT * FROM etapes_transformation WHERE tenant_id = ? AND (df10_id = ? OR (reception_id = ? AND ? IS NOT NULL)) "
        "ORDER BY id ASC",
        (session["tenant_id"], grume["id"], reception["id"] if reception else -1, reception["id"] if reception else None),
    ).fetchall()
    for e in etapes:
        intervenants.append(e["saisi_par"])

    lots = []
    if reception:
        lots = conn.execute(
            "SELECT * FROM scierie_debits WHERE tenant_id = ? AND reception_id = ? ORDER BY id ASC",
            (session["tenant_id"], reception["id"]),
        ).fetchall()
        for lot in lots:
            intervenants.append(lot["saisi_par"])

    lv_bois_debite = []
    contrats_lies = []
    if lots:
        lot_ids_str = [str(l["id"]) for l in lots]
        toutes_lv_bd = conn.execute(
            "SELECT * FROM lettres_voiture WHERE tenant_id = ? AND type_lv = 'BOIS_DEBITE'",
            (session["tenant_id"],),
        ).fetchall()
        for lv in toutes_lv_bd:
            ids = json.loads(lv["scierie_lot_ids"] or "[]")
            if any(i in ids for i in lot_ids_str):
                lv_bois_debite.append(lv)
                intervenants.append(lv["saisi_par"])

    conn.close()
    intervenants_uniques = sorted(set(i for i in intervenants if i))
    return render_template("genealogie.html", grume=grume, lv=lv_associee, reception=reception,
                            etapes=etapes, lots=lots, lv_bois_debite=lv_bois_debite,
                            intervenants=intervenants_uniques)


@app.route("/genealogie")
@login_requis
def genealogie_recherche():
    conn = get_connection()
    grumes = conn.execute(
        "SELECT numero_df10 FROM df10_registre WHERE tenant_id = ? ORDER BY id DESC LIMIT 200",
        (session["tenant_id"],),
    ).fetchall()
    conn.close()
    return render_template("genealogie_recherche.html", grumes=grumes)


# ------------------------------------------------------------------
# Module 8 : Suite Python autonome (irwanetrace_core.py) — export
# strictement et exclusivement réservé au compte Super-Admin, avec
# vérification des droits côté serveur (décorateur super_admin_requis,
# jamais contournable depuis un template ou une requête directe).
# ------------------------------------------------------------------

@app.route("/module8")
@login_requis
@super_admin_requis
def module8():
    exports = lister_exports()
    return render_template("module8.html", exports=exports)


@app.route("/module8/export", methods=["POST"])
@login_requis
@super_admin_requis
def module8_export():
    inclure_base = request.form.get("inclure_base") == "on"
    archive = generer_suite_autonome(inclure_base=inclure_base)
    nom_fichier = f"irwanetrace_core_{datetime.date.today().isoformat()}.zip"
    journaliser_export(session["email"], nom_fichier, request.remote_addr)
    log_audit("EXPORT_MODULE8", "MODULE8", nom_fichier)
    return send_file(io.BytesIO(archive), mimetype="application/zip", as_attachment=True,
                      download_name=nom_fichier)


# ------------------------------------------------------------------
# Thème visuel : commutateur Émeraude / Sombre, mémorisé en session.
# ------------------------------------------------------------------

@app.route("/theme/<nom_theme>", methods=["POST"])
@login_requis
def changer_theme(nom_theme):
    if nom_theme in THEMES_DISPONIBLES:
        session["theme"] = nom_theme
    return redirect(request.referrer or url_for("dashboard"))


# ------------------------------------------------------------------
# Import / Export Excel — rapports d'inventaire, production, stock, audit.
# ------------------------------------------------------------------

RAPPORTS_EXCEL = {
    "df10": {
        "titre": "Registre DF10",
        "entetes": ["N° DF10", "N° Plaquette", "UFA", "AAC", "Essence", "Gros bout (cm)", "Petit bout (cm)", "Longueur (m)", "Volume (m³)", "Statut", "Saisi par"],
        "requete": """SELECT g.numero_df10, g.numero_plaquette, g.ufa, g.aac, e.nom, g.diametre_gros_bout_cm,
                             g.diametre_petit_bout_cm, g.longueur_m, g.volume_m3, g.statut, g.saisi_par
                      FROM df10_registre g JOIN essences e ON e.id = g.essence_id
                      WHERE g.tenant_id = ? ORDER BY g.id DESC""",
    },
    "inventaire": {
        "titre": "Inventaire forestier",
        "entetes": ["UFA", "AAC", "Bloc", "Essence", "Diamètre (cm)", "Hauteur (m)", "Volume (m³)", "Conforme DME", "Saisi par"],
        "requete": """SELECT ia.ufa, ia.aac, ia.bloc, e.nom, ia.diametre_cm, ia.hauteur_m, ia.volume_m3,
                             CASE WHEN ia.conforme_dme=1 THEN 'Oui' ELSE 'Non' END, ia.saisi_par
                      FROM inventaire_arbres ia JOIN essences e ON e.id = ia.essence_id
                      WHERE ia.tenant_id = ? ORDER BY ia.id DESC""",
    },
    "transport": {
        "titre": "Transport - Lettres de voiture",
        "entetes": ["N° LV", "Type", "Tracteur", "Remorque", "Chauffeur", "Itinéraire", "Nb unités",
                    "Cubage (m³)", "Poids total (kg)", "Charge conforme", "Statut", "Saisi par"],
        "requete": """SELECT numero_lv, type_lv, tracteur, remorque, chauffeur, itineraire, nombre_billes,
                             cubage_total_m3, poids_total_kg,
                             CASE WHEN charge_conforme=1 THEN 'Oui' WHEN charge_conforme=0 THEN 'Non' ELSE '—' END,
                             statut, saisi_par
                      FROM lettres_voiture WHERE tenant_id = ? ORDER BY id DESC""",
    },
    "transformation": {
        "titre": "Étapes de transformation",
        "entetes": ["Type d'étape", "N° DF10 lié", "N° CEU lié", "Référence libre", "Volume entrée (m³)",
                    "Volume sortie (m³)", "Taux de perte (%)", "Notes", "Saisi par"],
        "requete": """SELECT e.type_etape, g.numero_df10, r.numero_ceu, e.reference_libre, e.volume_entree_m3,
                             e.volume_sortie_m3, e.taux_perte_pct, e.notes, e.saisi_par
                      FROM etapes_transformation e
                      LEFT JOIN df10_registre g ON g.id = e.df10_id
                      LEFT JOIN parc_usine_receptions r ON r.id = e.reception_id
                      WHERE e.tenant_id = ? ORDER BY e.id DESC""",
    },
    "production": {
        "titre": "Production scierie",
        "entetes": ["N° Lot", "Ligne", "Volume grume (m³)", "Volume sciages (m³)", "Rendement (%)", "Saisi par"],
        "requete": """SELECT numero_lot, ligne_sciage, volume_grume_entree_m3, volume_sciages_m3,
                             rendement_pct, saisi_par
                      FROM scierie_debits WHERE tenant_id = ? ORDER BY id DESC""",
    },
    "stock": {
        "titre": "Réceptions parc usine",
        "entetes": ["N° CEU", "N° LV", "Fournisseur tiers", "N° Agrément", "IFU", "Volume reçu (m³)", "Conforme"],
        "requete": """SELECT numero_ceu, numero_lv, fournisseur_tiers, numero_agrement, ifu, volume_recu_m3,
                             CASE WHEN conforme=1 THEN 'Oui' ELSE 'Non' END
                      FROM parc_usine_receptions WHERE tenant_id = ? ORDER BY id DESC""",
    },
    "contrats": {
        "titre": "Contrats & exports",
        "entetes": ["Client", "Destination", "Incoterm", "Volume alloué (m³)", "Volume livré (m³)", "Saisi par"],
        "requete": """SELECT client, destination, incoterm, volume_alloue_m3, volume_livre_m3, saisi_par
                      FROM contrats_export WHERE tenant_id = ? ORDER BY id DESC""",
    },
    "audit": {
        "titre": "Journal d'audit",
        "entetes": ["Horodatage", "Utilisateur", "Rôle", "Action", "Module", "Détails", "IP"],
        "requete": """SELECT horodatage, utilisateur, role, action, module, details, session_ip
                      FROM audit_log WHERE tenant_id = ? ORDER BY id DESC""",
    },
}

# Colonnes attendues pour chaque modèle d'import Excel — un modèle vierge
# téléchargeable est généré à partir de cette même liste (voir /rapports/<nom>/modele-excel).
IMPORT_MODELES = {
    "df10": ["ufa", "aac", "numero_plaquette", "essence_nom", "diametre_gros_bout_cm",
             "diametre_petit_bout_cm", "longueur_m"],
    "inventaire": ["ufa", "aac", "bloc", "essence_nom", "diametre_cm", "hauteur_m",
                   "facteur_forme", "latitude", "longitude"],
    "transport": ["type_lv (GRUMES ou BOIS_DEBITE)", "tracteur", "remorque", "chauffeur", "itineraire",
                  "numero_df10_liste (séparés par ;)", "numero_lot_liste (séparés par ;)",
                  "poids_a_vide_kg", "poids_charge_kg", "categorie_pma"],
    "transformation": ["type_etape", "numero_df10", "numero_ceu", "reference_libre",
                        "volume_entree_m3", "volume_sortie_m3", "notes"],
    "production": ["ligne_sciage", "numero_ceu", "volume_grume_entree_m3", "volume_sciages_m3"],
    "stock": ["numero_lv", "fournisseur_tiers", "numero_agrement", "ifu", "volume_recu_m3", "conforme (oui/non)"],
    "contrats": ["client", "destination", "incoterm", "volume_alloue_m3"],
}


@app.route("/rapports/<nom_rapport>/export-excel")
@login_requis
def export_excel(nom_rapport):
    if nom_rapport not in RAPPORTS_EXCEL:
        abort(404)
    rapport = RAPPORTS_EXCEL[nom_rapport]
    conn = get_connection()
    if session["role"] == "SUPER_ADMIN" and nom_rapport == "audit":
        lignes = conn.execute(rapport["requete"].replace("WHERE tenant_id = ? ", ""), ()).fetchall()
    else:
        lignes = conn.execute(rapport["requete"], (session["tenant_id"],)).fetchall()
    conn.close()
    xlsx_bytes = exporter_xlsx(rapport["titre"], rapport["entetes"], [tuple(r) for r in lignes])
    log_audit("EXPORT_EXCEL", nom_rapport.upper(), f"{len(lignes)} lignes")
    return send_file(io.BytesIO(xlsx_bytes), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      as_attachment=True, download_name=f"itf_{nom_rapport}_{datetime.date.today().isoformat()}.xlsx")


@app.route("/rapports/<nom_rapport>/modele-excel")
@login_requis
def modele_excel(nom_rapport):
    """Modèle Excel vierge (en-têtes uniquement) pour préparer un import."""
    if nom_rapport not in IMPORT_MODELES:
        abort(404)
    entetes = IMPORT_MODELES[nom_rapport]
    xlsx_bytes = exporter_xlsx(f"Modèle {nom_rapport}", entetes, [])
    return send_file(io.BytesIO(xlsx_bytes), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      as_attachment=True, download_name=f"itf_modele_{nom_rapport}.xlsx")


@app.route("/inventaire/import-excel", methods=["POST"])
@login_requis
@roles_requis("PROSPECTEUR_FORESTIER", "ADMIN", "SUPER_ADMIN")
def import_excel_inventaire():
    fichier = request.files.get("fichier")
    if not fichier:
        flash("Aucun fichier sélectionné.", "danger")
        return redirect(url_for("inventaire"))
    colonnes = ["ufa", "aac", "bloc", "essence_nom", "diametre_cm", "hauteur_m", "facteur_forme", "latitude", "longitude"]
    try:
        lignes = importer_xlsx(fichier.read(), colonnes)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("inventaire"))

    conn = get_connection()
    essences_par_nom = {row["nom"].strip().lower(): row["id"] for row in
                         conn.execute("SELECT id, nom FROM essences").fetchall()}
    nb_ok, nb_erreurs = 0, 0
    for ligne in lignes:
        try:
            essence_id = essences_par_nom.get(str(ligne.get("essence_nom", "")).strip().lower())
            if not essence_id or not ligne.get("diametre_cm") or not ligne.get("hauteur_m"):
                nb_erreurs += 1
                continue
            diametre = float(ligne["diametre_cm"])
            hauteur = float(ligne["hauteur_m"])
            facteur = float(ligne.get("facteur_forme") or 0.7)
            essence = conn.execute("SELECT * FROM essences WHERE id = ?", (essence_id,)).fetchone()
            volume = volume_arbre_sur_pied(diametre, hauteur, facteur)
            conforme = 1 if diametre >= essence["dme_cm"] else 0
            conn.execute(
                """INSERT INTO inventaire_arbres
                   (tenant_id, ufa, aac, bloc, essence_id, diametre_cm, hauteur_m, facteur_forme,
                    latitude, longitude, volume_m3, conforme_dme, saisi_par)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session["tenant_id"], ligne.get("ufa"), ligne.get("aac"), ligne.get("bloc"),
                 essence_id, diametre, hauteur, facteur, ligne.get("latitude"), ligne.get("longitude"),
                 volume, conforme, session["email"]),
            )
            nb_ok += 1
        except (ValueError, TypeError):
            nb_erreurs += 1
    conn.commit()
    conn.close()
    log_audit("IMPORT_EXCEL", "INVENTAIRE", f"{nb_ok} lignes importées, {nb_erreurs} erreurs")
    flash(f"{nb_ok} arbre(s) importé(s), {nb_erreurs} ligne(s) ignorée(s) (voir modèle attendu).",
          "success" if nb_erreurs == 0 else "warning")
    return redirect(url_for("inventaire"))


@app.route("/df10/import-excel", methods=["POST"])
@login_requis
@roles_requis("CHEF_PARC_FORESTIER", "ADMIN", "SUPER_ADMIN")
def import_excel_df10():
    fichier = request.files.get("fichier")
    if not fichier:
        flash("Aucun fichier sélectionné.", "danger")
        return redirect(url_for("df10"))
    colonnes = ["ufa", "aac", "numero_plaquette", "essence_nom",
                "diametre_gros_bout_cm", "diametre_petit_bout_cm", "longueur_m"]
    try:
        lignes = importer_xlsx(fichier.read(), colonnes)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("df10"))

    conn = get_connection()
    essences_par_nom = {row["nom"].strip().lower(): row["id"] for row in
                         conn.execute("SELECT id, nom FROM essences").fetchall()}
    nb_ok, nb_erreurs = 0, 0
    for ligne in lignes:
        try:
            essence_id = essences_par_nom.get(str(ligne.get("essence_nom", "")).strip().lower())
            d1, d2, longueur = ligne.get("diametre_gros_bout_cm"), ligne.get("diametre_petit_bout_cm"), ligne.get("longueur_m")
            if not essence_id or not d1 or not d2 or not longueur:
                nb_erreurs += 1
                continue
            d1, d2, longueur = float(d1), float(d2), float(longueur)
            volume = volume_grume(d1, d2, longueur)
            ufa, aac = ligne.get("ufa") or "", ligne.get("aac") or ""
            seq = conn.execute("SELECT COUNT(*) c FROM df10_registre WHERE tenant_id = ?",
                                (session["tenant_id"],)).fetchone()["c"] + 1
            numero_df10 = f"DF10-{ufa}-{aac}-{seq:05d}"
            conn.execute(
                """INSERT INTO df10_registre
                   (tenant_id, numero_df10, numero_plaquette, ufa, aac, essence_id,
                    diametre_gros_bout_cm, diametre_petit_bout_cm, longueur_m, volume_m3, saisi_par)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (session["tenant_id"], numero_df10, ligne.get("numero_plaquette"), ufa, aac,
                 essence_id, d1, d2, longueur, volume, session["email"]),
            )
            nb_ok += 1
        except (ValueError, TypeError):
            nb_erreurs += 1
    conn.commit()
    conn.close()
    log_audit("IMPORT_EXCEL", "DF10", f"{nb_ok} lignes importées, {nb_erreurs} erreurs")
    flash(f"{nb_ok} grume(s) importée(s), {nb_erreurs} ligne(s) ignorée(s) (voir modèle attendu).",
          "success" if nb_erreurs == 0 else "warning")
    return redirect(url_for("df10"))


@app.route("/parc-usine/import-excel", methods=["POST"])
@login_requis
@roles_requis("CHEF_PARC_USINE", "ADMIN", "SUPER_ADMIN")
def import_excel_parc_usine():
    fichier = request.files.get("fichier")
    if not fichier:
        flash("Aucun fichier sélectionné.", "danger")
        return redirect(url_for("parc_usine"))
    colonnes = ["numero_lv", "fournisseur_tiers", "numero_agrement", "ifu", "volume_recu_m3", "conforme"]
    try:
        lignes = importer_xlsx(fichier.read(), colonnes)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("parc_usine"))

    conn = get_connection()
    nb_ok, nb_erreurs = 0, 0
    for ligne in lignes:
        try:
            volume = ligne.get("volume_recu_m3")
            if not volume:
                nb_erreurs += 1
                continue
            volume = float(volume)
            numero_lv = str(ligne.get("numero_lv") or "").strip()
            conforme_val = str(ligne.get("conforme") or "oui").strip().lower()
            conforme = 1 if conforme_val in ("oui", "yes", "1", "true") else 0
            seq = conn.execute("SELECT COUNT(*) c FROM parc_usine_receptions WHERE tenant_id = ?",
                                (session["tenant_id"],)).fetchone()["c"] + 1
            numero_ceu = f"CEU-{session['tenant_id']}-{seq:05d}"
            conn.execute(
                """INSERT INTO parc_usine_receptions
                   (tenant_id, numero_ceu, numero_lv, fournisseur_tiers, numero_agrement, ifu,
                    volume_recu_m3, conforme, saisi_par)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (session["tenant_id"], numero_ceu, numero_lv or None, ligne.get("fournisseur_tiers"),
                 ligne.get("numero_agrement"), ligne.get("ifu"), volume, conforme, session["email"]),
            )
            if numero_lv:
                conn.execute("UPDATE lettres_voiture SET statut = 'RECEPTIONNE' WHERE numero_lv = ? AND tenant_id = ?",
                             (numero_lv, session["tenant_id"]))
            nb_ok += 1
        except (ValueError, TypeError):
            nb_erreurs += 1
    conn.commit()
    conn.close()
    log_audit("IMPORT_EXCEL", "PARC_USINE", f"{nb_ok} lignes importées, {nb_erreurs} erreurs")
    flash(f"{nb_ok} réception(s) importée(s), {nb_erreurs} ligne(s) ignorée(s) (voir modèle attendu).",
          "success" if nb_erreurs == 0 else "warning")
    return redirect(url_for("parc_usine"))


@app.route("/scierie/import-excel", methods=["POST"])
@login_requis
@roles_requis("RESPONSABLE_SCIERIE", "ADMIN", "SUPER_ADMIN")
def import_excel_scierie():
    fichier = request.files.get("fichier")
    if not fichier:
        flash("Aucun fichier sélectionné.", "danger")
        return redirect(url_for("scierie"))
    colonnes = ["ligne_sciage", "numero_ceu", "volume_grume_entree_m3", "volume_sciages_m3"]
    try:
        lignes = importer_xlsx(fichier.read(), colonnes)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("scierie"))

    conn = get_connection()
    nb_ok, nb_erreurs = 0, 0
    for ligne in lignes:
        try:
            v_grume, v_sciages = ligne.get("volume_grume_entree_m3"), ligne.get("volume_sciages_m3")
            if not v_grume or not v_sciages:
                nb_erreurs += 1
                continue
            v_grume, v_sciages = float(v_grume), float(v_sciages)
            rendement = rendement_matiere(v_grume, v_sciages)
            reception_id = None
            numero_ceu = str(ligne.get("numero_ceu") or "").strip()
            if numero_ceu:
                r = conn.execute("SELECT id FROM parc_usine_receptions WHERE numero_ceu = ? AND tenant_id = ?",
                                  (numero_ceu, session["tenant_id"])).fetchone()
                reception_id = r["id"] if r else None
            seq = conn.execute("SELECT COUNT(*) c FROM scierie_debits WHERE tenant_id = ?",
                                (session["tenant_id"],)).fetchone()["c"] + 1
            numero_lot = f"LOT-{session['tenant_id']}-{seq:05d}"
            conn.execute(
                """INSERT INTO scierie_debits
                   (tenant_id, ligne_sciage, volume_grume_entree_m3, volume_sciages_m3, rendement_pct,
                    reception_id, numero_lot, saisi_par)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (session["tenant_id"], ligne.get("ligne_sciage"), v_grume, v_sciages, rendement,
                 reception_id, numero_lot, session["email"]),
            )
            nb_ok += 1
        except (ValueError, TypeError):
            nb_erreurs += 1
    conn.commit()
    conn.close()
    log_audit("IMPORT_EXCEL", "SCIERIE", f"{nb_ok} lignes importées, {nb_erreurs} erreurs")
    flash(f"{nb_ok} débit(s) importé(s), {nb_erreurs} ligne(s) ignorée(s) (voir modèle attendu).",
          "success" if nb_erreurs == 0 else "warning")
    return redirect(url_for("scierie"))


@app.route("/transformation/import-excel", methods=["POST"])
@login_requis
@roles_requis("CHEF_PARC_USINE", "RESPONSABLE_SCIERIE", "ADMIN", "SUPER_ADMIN")
def import_excel_transformation():
    fichier = request.files.get("fichier")
    if not fichier:
        flash("Aucun fichier sélectionné.", "danger")
        return redirect(url_for("transformation"))
    colonnes = ["type_etape", "numero_df10", "numero_ceu", "reference_libre",
                "volume_entree_m3", "volume_sortie_m3", "notes"]
    try:
        lignes = importer_xlsx(fichier.read(), colonnes)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("transformation"))

    conn = get_connection()
    nb_ok, nb_erreurs = 0, 0
    for ligne in lignes:
        try:
            type_etape = str(ligne.get("type_etape") or "").strip().upper()
            if type_etape not in TYPES_ETAPE:
                nb_erreurs += 1
                continue
            df10_id = None
            numero_df10 = str(ligne.get("numero_df10") or "").strip()
            if numero_df10:
                r = conn.execute("SELECT id FROM df10_registre WHERE numero_df10 = ? AND tenant_id = ?",
                                  (numero_df10, session["tenant_id"])).fetchone()
                df10_id = r["id"] if r else None
            reception_id = None
            numero_ceu = str(ligne.get("numero_ceu") or "").strip()
            if numero_ceu:
                r = conn.execute("SELECT id FROM parc_usine_receptions WHERE numero_ceu = ? AND tenant_id = ?",
                                  (numero_ceu, session["tenant_id"])).fetchone()
                reception_id = r["id"] if r else None
            v_entree = ligne.get("volume_entree_m3")
            v_sortie = ligne.get("volume_sortie_m3")
            taux_perte = None
            if v_entree and v_sortie:
                v_entree_f, v_sortie_f = float(v_entree), float(v_sortie)
                if v_entree_f:
                    taux_perte = round((1 - v_sortie_f / v_entree_f) * 100, 2)
            conn.execute(
                """INSERT INTO etapes_transformation
                   (tenant_id, type_etape, df10_id, reception_id, reference_libre,
                    volume_entree_m3, volume_sortie_m3, taux_perte_pct, notes, saisi_par)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (session["tenant_id"], type_etape, df10_id, reception_id,
                 ligne.get("reference_libre") or None,
                 float(v_entree) if v_entree else None, float(v_sortie) if v_sortie else None,
                 taux_perte, ligne.get("notes"), session["email"]),
            )
            nb_ok += 1
        except (ValueError, TypeError):
            nb_erreurs += 1
    conn.commit()
    conn.close()
    log_audit("IMPORT_EXCEL", "TRANSFORMATION", f"{nb_ok} lignes importées, {nb_erreurs} erreurs")
    flash(f"{nb_ok} étape(s) importée(s), {nb_erreurs} ligne(s) ignorée(s) (voir modèle attendu).",
          "success" if nb_erreurs == 0 else "warning")
    return redirect(url_for("transformation"))


@app.route("/contrats/import-excel", methods=["POST"])
@login_requis
@roles_requis("ADMIN", "SUPER_ADMIN")
def import_excel_contrats():
    fichier = request.files.get("fichier")
    if not fichier:
        flash("Aucun fichier sélectionné.", "danger")
        return redirect(url_for("contrats"))
    colonnes = ["client", "destination", "incoterm", "volume_alloue_m3"]
    try:
        lignes = importer_xlsx(fichier.read(), colonnes)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("contrats"))

    conn = get_connection()
    nb_ok, nb_erreurs = 0, 0
    for ligne in lignes:
        try:
            client, volume = ligne.get("client"), ligne.get("volume_alloue_m3")
            if not client or not volume:
                nb_erreurs += 1
                continue
            conn.execute(
                """INSERT INTO contrats_export (tenant_id, client, destination, incoterm, volume_alloue_m3, saisi_par)
                   VALUES (?,?,?,?,?,?)""",
                (session["tenant_id"], client, ligne.get("destination"), ligne.get("incoterm"),
                 float(volume), session["email"]),
            )
            nb_ok += 1
        except (ValueError, TypeError):
            nb_erreurs += 1
    conn.commit()
    conn.close()
    log_audit("IMPORT_EXCEL", "CONTRAT", f"{nb_ok} lignes importées, {nb_erreurs} erreurs")
    flash(f"{nb_ok} contrat(s) importé(s), {nb_erreurs} ligne(s) ignorée(s) (voir modèle attendu).",
          "success" if nb_erreurs == 0 else "warning")
    return redirect(url_for("contrats"))


@app.route("/transport/import-excel", methods=["POST"])
@login_requis
@roles_requis("CHEF_PARC_FORESTIER", "ADMIN", "SUPER_ADMIN")
def import_excel_transport():
    fichier = request.files.get("fichier")
    if not fichier:
        flash("Aucun fichier sélectionné.", "danger")
        return redirect(url_for("transport"))
    colonnes = ["type_lv", "tracteur", "remorque", "chauffeur", "itineraire",
                "numero_df10_liste", "numero_lot_liste", "poids_a_vide_kg", "poids_charge_kg", "categorie_pma"]
    try:
        lignes = importer_xlsx(fichier.read(), colonnes)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("transport"))

    conn = get_connection()
    nb_ok, nb_erreurs = 0, 0
    for ligne in lignes:
        try:
            type_lv = str(ligne.get("type_lv") or "GRUMES").strip().upper()
            if type_lv not in ("GRUMES", "BOIS_DEBITE"):
                type_lv = "GRUMES"
            references_ids, cubage_total = [], 0.0

            if type_lv == "BOIS_DEBITE":
                noms = [n.strip() for n in str(ligne.get("numero_lot_liste") or "").split(";") if n.strip()]
                for nom in noms:
                    r = conn.execute("SELECT id, volume_sciages_m3 FROM scierie_debits WHERE numero_lot = ? AND tenant_id = ?",
                                      (nom, session["tenant_id"])).fetchone()
                    if r:
                        references_ids.append(str(r["id"]))
                        cubage_total += r["volume_sciages_m3"] or 0
            else:
                noms = [n.strip() for n in str(ligne.get("numero_df10_liste") or "").split(";") if n.strip()]
                for nom in noms:
                    r = conn.execute("SELECT id, volume_m3 FROM df10_registre WHERE numero_df10 = ? AND tenant_id = ? AND statut = 'ABATTU'",
                                      (nom, session["tenant_id"])).fetchone()
                    if r:
                        references_ids.append(str(r["id"]))
                        cubage_total += r["volume_m3"] or 0

            if not references_ids:
                nb_erreurs += 1
                continue

            poids_a_vide, poids_charge = ligne.get("poids_a_vide_kg"), ligne.get("poids_charge_kg")
            categorie_pma = str(ligne.get("categorie_pma") or "STANDARD").strip().upper()
            if categorie_pma not in SEUILS_PMA:
                categorie_pma = "STANDARD"
            resultat_charge = None
            if poids_a_vide and poids_charge:
                resultat_charge = verifier_charge(float(poids_a_vide), float(poids_charge), categorie_pma)

            seq = conn.execute("SELECT COUNT(*) c FROM lettres_voiture WHERE tenant_id = ?",
                                (session["tenant_id"],)).fetchone()["c"] + 1
            numero_lv = f"LV-{session['tenant_id']}-{seq:05d}"

            conn.execute(
                """INSERT INTO lettres_voiture
                   (tenant_id, numero_lv, tracteur, remorque, chauffeur, itineraire,
                    nombre_billes, cubage_total_m3, df10_ids, scierie_lot_ids, type_lv,
                    poids_total_kg, charge_conforme, saisi_par)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session["tenant_id"], numero_lv, ligne.get("tracteur"), ligne.get("remorque"),
                 ligne.get("chauffeur"), ligne.get("itineraire"),
                 len(references_ids), round(cubage_total, 4),
                 json.dumps(references_ids) if type_lv != "BOIS_DEBITE" else None,
                 json.dumps(references_ids) if type_lv == "BOIS_DEBITE" else None,
                 type_lv,
                 resultat_charge["poids_total_kg"] if resultat_charge else None,
                 (1 if resultat_charge["conforme"] else 0) if resultat_charge else None,
                 session["email"]),
            )
            if type_lv != "BOIS_DEBITE":
                for did in references_ids:
                    conn.execute("UPDATE df10_registre SET statut = 'TRANSPORTE' WHERE id = ?", (did,))
            nb_ok += 1
        except (ValueError, TypeError):
            nb_erreurs += 1
    conn.commit()
    conn.close()
    log_audit("IMPORT_EXCEL", "TRANSPORT", f"{nb_ok} lignes importées, {nb_erreurs} erreurs")
    flash(f"{nb_ok} lettre(s) de voiture importée(s), {nb_erreurs} ligne(s) ignorée(s) "
          f"(vérifiez que les N° DF10/Lot existent et sont disponibles).",
          "success" if nb_erreurs == 0 else "warning")
    return redirect(url_for("transport"))


# ------------------------------------------------------------------
# Gestion des utilisateurs — un seul compte SUPER_ADMIN (Gauthier MBILI,
# créé à l'amorçage, jamais recréable via ces routes). Chaque ADMIN de
# société est nommé exclusivement par le Super-Admin. Chaque ADMIN gère
# ensuite ses propres collaborateurs opérationnels au sein de sa seule
# société — aucune interaction possible entre sociétés.
# ------------------------------------------------------------------

@app.route("/super-admin/utilisateurs")
@login_requis
@super_admin_requis
def super_admin_utilisateurs():
    conn = get_connection()
    tenants = conn.execute("SELECT * FROM tenants ORDER BY nom").fetchall()
    utilisateurs = conn.execute(
        "SELECT u.*, t.nom AS tenant_nom FROM users u LEFT JOIN tenants t ON t.id = u.tenant_id "
        "ORDER BY t.nom, u.role, u.nom_complet"
    ).fetchall()
    conn.close()
    return render_template("utilisateurs_super_admin.html", tenants=tenants, utilisateurs=utilisateurs)


@app.route("/super-admin/utilisateurs/creer", methods=["POST"])
@login_requis
@super_admin_requis
def super_admin_creer_utilisateur():
    role = request.form.get("role", "")
    tenant_id = request.form.get("tenant_id", "")
    nom = request.form.get("nom_complet", "").strip()
    email = request.form.get("email", "").strip().lower()

    if role == "SUPER_ADMIN":
        flash("Un seul compte Super-Admin existe dans IrwaneTraceForest — il ne peut pas être recréé.", "danger")
        return redirect(url_for("super_admin_utilisateurs"))
    if role not in ["ADMIN"] + ROLES_OPERATIONNELS:
        flash("Rôle invalide.", "danger")
        return redirect(url_for("super_admin_utilisateurs"))
    if not nom or not email or not tenant_id:
        flash("Nom, e-mail et société sont obligatoires.", "danger")
        return redirect(url_for("super_admin_utilisateurs"))

    from database import hash_password
    mot_de_passe = generer_mot_de_passe_temporaire()
    conn = get_connection()
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    try:
        conn.execute(
            "INSERT INTO users (nom_complet, email, password_hash, role, tenant_id, actif, doit_changer_mdp, cree_par) "
            "VALUES (?,?,?,?,?,1,1,?)",
            (nom, email, hash_password(mot_de_passe), role, tenant_id, session["email"]),
        )
        conn.commit()
        log_audit("CREATION_UTILISATEUR", "UTILISATEURS", f"{email} ({role}) pour {tenant['nom'] if tenant else tenant_id}")
        flash(f"Compte {role} créé pour {nom} ({email}) — société {tenant['nom'] if tenant else ''}. "
              f"Mot de passe temporaire à transmettre en sécurité : {mot_de_passe} "
              f"(changement obligatoire à la première connexion).", "success")
    except Exception:
        flash("Impossible de créer ce compte — cet e-mail est peut-être déjà utilisé.", "danger")
    finally:
        conn.close()
    return redirect(url_for("super_admin_utilisateurs"))


@app.route("/super-admin/utilisateurs/<int:user_id>/toggle", methods=["POST"])
@login_requis
@super_admin_requis
def super_admin_toggle_utilisateur(user_id):
    conn = get_connection()
    cible = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not cible or cible["role"] == "SUPER_ADMIN":
        conn.close()
        flash("Action impossible sur ce compte.", "danger")
        return redirect(url_for("super_admin_utilisateurs"))
    nouveau_statut = 0 if cible["actif"] else 1
    conn.execute("UPDATE users SET actif = ? WHERE id = ?", (nouveau_statut, user_id))
    conn.commit()
    conn.close()
    log_audit("ACTIVATION_UTILISATEUR" if nouveau_statut else "DESACTIVATION_UTILISATEUR",
               "UTILISATEURS", cible["email"])
    flash(f"Compte {cible['email']} {'réactivé' if nouveau_statut else 'désactivé'}.", "success")
    return redirect(url_for("super_admin_utilisateurs"))


@app.route("/super-admin/utilisateurs/<int:user_id>/reinitialiser", methods=["POST"])
@login_requis
@super_admin_requis
def super_admin_reinitialiser_mdp(user_id):
    from database import hash_password
    conn = get_connection()
    cible = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not cible or cible["role"] == "SUPER_ADMIN":
        conn.close()
        flash("Action impossible sur ce compte.", "danger")
        return redirect(url_for("super_admin_utilisateurs"))
    mot_de_passe = generer_mot_de_passe_temporaire()
    conn.execute("UPDATE users SET password_hash = ?, doit_changer_mdp = 1 WHERE id = ?",
                 (hash_password(mot_de_passe), user_id))
    conn.commit()
    conn.close()
    log_audit("REINITIALISATION_MDP", "UTILISATEURS", cible["email"])
    flash(f"Nouveau mot de passe temporaire pour {cible['email']} : {mot_de_passe} "
          f"(changement obligatoire à la prochaine connexion).", "success")
    return redirect(url_for("super_admin_utilisateurs"))


@app.route("/utilisateurs")
@login_requis
@roles_requis("ADMIN")
def utilisateurs_societe():
    conn = get_connection()
    utilisateurs = conn.execute(
        "SELECT * FROM users WHERE tenant_id = ? ORDER BY role, nom_complet", (session["tenant_id"],)
    ).fetchall()
    conn.close()
    return render_template("utilisateurs.html", utilisateurs=utilisateurs, roles=ROLES_OPERATIONNELS)


@app.route("/utilisateurs/creer", methods=["POST"])
@login_requis
@roles_requis("ADMIN")
def creer_utilisateur_societe():
    role = request.form.get("role", "")
    nom = request.form.get("nom_complet", "").strip()
    email = request.form.get("email", "").strip().lower()

    if role not in ROLES_OPERATIONNELS:
        flash("Un Admin ne peut créer que des comptes opérationnels de sa propre société "
              "(pas de compte Admin ou Super-Admin).", "danger")
        return redirect(url_for("utilisateurs_societe"))
    if not nom or not email:
        flash("Nom et e-mail sont obligatoires.", "danger")
        return redirect(url_for("utilisateurs_societe"))

    from database import hash_password
    mot_de_passe = generer_mot_de_passe_temporaire()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (nom_complet, email, password_hash, role, tenant_id, actif, doit_changer_mdp, cree_par) "
            "VALUES (?,?,?,?,?,1,1,?)",
            (nom, email, hash_password(mot_de_passe), role, session["tenant_id"], session["email"]),
        )
        conn.commit()
        log_audit("CREATION_UTILISATEUR", "UTILISATEURS", f"{email} ({role})")
        flash(f"Compte {role} créé pour {nom} ({email}). "
              f"Mot de passe temporaire à transmettre en sécurité : {mot_de_passe} "
              f"(changement obligatoire à la première connexion).", "success")
    except Exception:
        flash("Impossible de créer ce compte — cet e-mail est peut-être déjà utilisé.", "danger")
    finally:
        conn.close()
    return redirect(url_for("utilisateurs_societe"))


@app.route("/utilisateurs/<int:user_id>/toggle", methods=["POST"])
@login_requis
@roles_requis("ADMIN")
def toggle_utilisateur_societe(user_id):
    conn = get_connection()
    cible = conn.execute("SELECT * FROM users WHERE id = ? AND tenant_id = ?",
                          (user_id, session["tenant_id"])).fetchone()
    if not cible or cible["role"] in ("ADMIN", "SUPER_ADMIN"):
        conn.close()
        flash("Action impossible sur ce compte.", "danger")
        return redirect(url_for("utilisateurs_societe"))
    nouveau_statut = 0 if cible["actif"] else 1
    conn.execute("UPDATE users SET actif = ? WHERE id = ?", (nouveau_statut, user_id))
    conn.commit()
    conn.close()
    log_audit("ACTIVATION_UTILISATEUR" if nouveau_statut else "DESACTIVATION_UTILISATEUR",
               "UTILISATEURS", cible["email"])
    flash(f"Compte {cible['email']} {'réactivé' if nouveau_statut else 'désactivé'}.", "success")
    return redirect(url_for("utilisateurs_societe"))


# ------------------------------------------------------------------
# Mode hors-ligne & synchronisation — bouton un-clic, activable dès
# qu'une connexion Internet est détectée. Fonctionne pour tous les
# utilisateurs connectés (données de leur société), et de façon globale
# pour le Super-Admin (toutes les sociétés en un seul export).
# ------------------------------------------------------------------

@app.route("/sync")
@login_requis
def sync_page():
    params = obtenir_parametres_sync()
    en_ligne = verifier_connexion_internet()
    conn = get_connection()
    tenant = None
    if session.get("tenant_id"):
        tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (session["tenant_id"],)).fetchone()
    conn.close()
    historique = historique_sync(session.get("tenant_id"))
    return render_template("sync.html", params=params, en_ligne=en_ligne, tenant=tenant, historique=historique)


@app.route("/sync/verifier-connexion")
@login_requis
def sync_verifier_connexion():
    """Endpoint léger interrogé en arrière-plan (JS) pour activer/désactiver
    automatiquement le bouton Synchroniser dès qu'Internet est détecté."""
    return jsonify({"en_ligne": verifier_connexion_internet()})


@app.route("/sync/executer", methods=["POST"])
@login_requis
def sync_executer():
    tenant_id = None if session["role"] == "SUPER_ADMIN" else session.get("tenant_id")
    resultat = synchroniser(tenant_id, session["email"])
    log_audit("SYNCHRONISATION", "SYNC", f"{resultat['statut']} — {resultat['message']}")
    flash(resultat["message"], "success" if resultat["ok"] else
          ("warning" if resultat["statut"] == "HORS_LIGNE" else "danger"))
    return redirect(url_for("sync_page"))


@app.route("/super-admin/sync-config", methods=["POST"])
@login_requis
@super_admin_requis
def sync_config():
    url = request.form.get("url_serveur_central", "").strip()
    auto = request.form.get("auto_sync_actif") == "on"
    definir_parametres_sync(url, auto, session["email"])
    log_audit("CONFIGURATION_SYNC", "SYNC", f"url={url or '—'} / auto={auto}")
    flash("Paramètres de synchronisation mis à jour.", "success")
    return redirect(url_for("sync_page"))


if __name__ == "__main__":
    init_db(reset=False)
    app.run(host="127.0.0.1", port=5000, debug=False)
