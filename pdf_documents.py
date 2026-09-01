# -*- coding: utf-8 -*-
"""
IrwaneTraceForest (ITF) - Génération de documents PDF officiels
Lettre de Voiture Grumes, Lettre de Voiture Bois Débité, Carnet Entrée
Usine (CEU) et ticket DF10, chacun avec code-barres Code128 intégré
(via reportlab.graphics.barcode — aucune dépendance externe requise).
"""

import io
from reportlab.lib.pagesizes import A5, A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128

EMERAUDE = HexColor("#047857")
ARDOISE = HexColor("#0f172a")
GRIS = HexColor("#64748b")


def _entete(c: canvas.Canvas, largeur, hauteur, titre: str, tenant_nom: str):
    c.setFillColor(EMERAUDE)
    c.rect(0, hauteur - 22 * mm, largeur, 22 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 15)
    c.drawString(10 * mm, hauteur - 10 * mm, "IrwaneTraceForest — ITF")
    c.setFont("Helvetica", 9)
    c.drawString(10 * mm, hauteur - 16 * mm, titre)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(largeur - 10 * mm, hauteur - 10 * mm, tenant_nom or "")
    c.setFillColor(ARDOISE)


def _pied_de_page(c: canvas.Canvas, largeur, code_barre: str):
    c.setFillColor(GRIS)
    c.setFont("Helvetica", 7)
    c.drawString(10 * mm, 8 * mm,
                 "Document généré par IrwaneTraceForest (ITF) — MEA SARL / Éditeur Système ITT — "
                 "Concepteur exclusif : Gauthier MBILI")
    if code_barre:
        barcode = code128.Code128(code_barre, barHeight=12 * mm, barWidth=0.32)
        barcode.drawOn(c, 10 * mm, 12 * mm)


def _ligne_champ(c: canvas.Canvas, x, y, label, valeur):
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(GRIS)
    c.drawString(x, y, label)
    c.setFont("Helvetica", 10)
    c.setFillColor(ARDOISE)
    c.drawString(x, y - 5 * mm, str(valeur) if valeur not in (None, "") else "—")


def generer_pdf_df10(grume: dict, tenant_nom: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    largeur, hauteur = A5
    _entete(c, largeur, hauteur, "Fiche officielle DF10 — Registre d'abattage", tenant_nom)

    y = hauteur - 34 * mm
    champs = [
        ("N° DF10", grume.get("numero_df10")),
        ("N° Plaquette", grume.get("numero_plaquette")),
        ("UFA / AAC", f"{grume.get('ufa','')} / {grume.get('aac','')}"),
        ("Essence", grume.get("essence_nom")),
        ("Diamètre gros bout (cm)", grume.get("diametre_gros_bout_cm")),
        ("Diamètre petit bout (cm)", grume.get("diametre_petit_bout_cm")),
        ("Longueur (m)", grume.get("longueur_m")),
        ("Volume cubé (m³)", grume.get("volume_m3")),
        ("Statut", grume.get("statut")),
        ("Saisi par", grume.get("saisi_par")),
    ]
    for label, valeur in champs:
        _ligne_champ(c, 10 * mm, y, label, valeur)
        y -= 11 * mm

    _pied_de_page(c, largeur, grume.get("numero_df10", ""))
    c.showPage()
    c.save()
    return buf.getvalue()


def generer_pdf_lettre_voiture(lv: dict, tenant_nom: str, grumes: list, charge: dict = None) -> bytes:
    """type_lv attendu dans lv : 'GRUMES' ou 'BOIS_DEBITE' — adapte le titre
    et le tableau de détail (billes de grumes vs lots de bois débité)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    largeur, hauteur = A4
    type_lv = lv.get("type_lv", "GRUMES")
    titre = ("Lettre de Voiture — Bois Débité" if type_lv == "BOIS_DEBITE"
             else "Lettre de Voiture — Grumes")
    _entete(c, largeur, hauteur, titre, tenant_nom)

    y = hauteur - 34 * mm
    col1_x, col2_x = 10 * mm, 105 * mm
    gauche = [
        ("N° Lettre de Voiture", lv.get("numero_lv")),
        ("Tracteur", lv.get("tracteur")),
        ("Remorque", lv.get("remorque")),
        ("Chauffeur", lv.get("chauffeur")),
    ]
    droite = [
        ("Itinéraire", lv.get("itineraire")),
        ("Nombre de billes / colis", lv.get("nombre_billes")),
        ("Cubage total (m³)", lv.get("cubage_total_m3")),
        ("Statut", lv.get("statut")),
    ]
    y0 = y
    for label, valeur in gauche:
        _ligne_champ(c, col1_x, y, label, valeur)
        y -= 11 * mm
    y = y0
    for label, valeur in droite:
        _ligne_champ(c, col2_x, y, label, valeur)
        y -= 11 * mm

    y -= 8 * mm
    c.setFont("Helvetica-Bold", 10.5)
    c.setFillColor(EMERAUDE)
    c.drawString(col1_x, y, "Contrôle de charge à l'essieu")
    c.setFillColor(ARDOISE)
    y -= 7 * mm
    if charge:
        _ligne_champ(c, col1_x, y, "Poids total en charge (kg)", charge.get("poids_total_kg"))
        _ligne_champ(c, col2_x, y, "PMA réglementaire (kg)", charge.get("pma_reglementaire_kg"))
        y -= 11 * mm
        statut_charge = "CONFORME" if charge.get("conforme") else "NON CONFORME — DÉPASSEMENT"
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(EMERAUDE if charge.get("conforme") else HexColor("#dc2626"))
        c.drawString(col1_x, y, f"Statut : {statut_charge}")
        c.setFillColor(ARDOISE)
        y -= 11 * mm
    else:
        c.setFont("Helvetica", 9)
        c.setFillColor(GRIS)
        c.drawString(col1_x, y, "Aucun contrôle de charge enregistré pour cette lettre de voiture.")
        c.setFillColor(ARDOISE)
        y -= 11 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 10.5)
    c.setFillColor(EMERAUDE)
    label_detail = "Bois débité couverts" if type_lv == "BOIS_DEBITE" else "Grumes couvertes (DF10)"
    c.drawString(col1_x, y, label_detail)
    c.setFillColor(ARDOISE)
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(GRIS)
    if type_lv == "BOIS_DEBITE":
        c.drawString(col1_x, y, "N° LOT"); c.drawString(col1_x + 60*mm, y, "LIGNE"); c.drawString(col1_x + 120*mm, y, "VOLUME (m³)")
    else:
        c.drawString(col1_x, y, "N° DF10"); c.drawString(col1_x + 70*mm, y, "ESSENCE"); c.drawString(col1_x + 130*mm, y, "VOLUME (m³)")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColor(ARDOISE)
    for g in grumes[:22]:
        if type_lv == "BOIS_DEBITE":
            c.drawString(col1_x, y, str(g.get("numero_lot", "")))
            c.drawString(col1_x + 60*mm, y, str(g.get("ligne_sciage", "")))
            c.drawString(col1_x + 120*mm, y, str(g.get("volume_sciages_m3", "")))
        else:
            c.drawString(col1_x, y, str(g.get("numero_df10", "")))
            c.drawString(col1_x + 70*mm, y, str(g.get("essence_nom", "")))
            c.drawString(col1_x + 130*mm, y, str(g.get("volume_m3", "")))
        y -= 6 * mm
        if y < 30 * mm:
            break

    _pied_de_page(c, largeur, lv.get("numero_lv", ""))
    c.showPage()
    c.save()
    return buf.getvalue()


def generer_pdf_ceu(reception: dict, tenant_nom: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    largeur, hauteur = A5
    _entete(c, largeur, hauteur, "Carnet Entrée Usine (CEU)", tenant_nom)

    y = hauteur - 34 * mm
    champs = [
        ("N° CEU", reception.get("numero_ceu")),
        ("N° Lettre de Voiture liée", reception.get("numero_lv")),
        ("Fournisseur tiers", reception.get("fournisseur_tiers")),
        ("N° Agrément", reception.get("numero_agrement")),
        ("N° IFU", reception.get("ifu")),
        ("Volume reçu (m³)", reception.get("volume_recu_m3")),
        ("Conforme aux documents", "Oui" if reception.get("conforme") else "Non"),
        ("Saisi par", reception.get("saisi_par")),
    ]
    for label, valeur in champs:
        _ligne_champ(c, 10 * mm, y, label, valeur)
        y -= 11 * mm

    _pied_de_page(c, largeur, reception.get("numero_ceu") or reception.get("numero_lv", ""))
    c.showPage()
    c.save()
    return buf.getvalue()
