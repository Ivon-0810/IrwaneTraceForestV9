# -*- coding: utf-8 -*-
"""
IrwaneTraceForest (ITF) - Contrôle de charge à l'essieu
Vérifie la conformité du poids total en charge d'un ensemble routier
(tracteur + remorque) par rapport aux seuils réglementaires du Bassin du
Congo avant l'édition définitive de la Lettre de Voiture.

Seuils par défaut (indicatifs, à ajuster selon la réglementation en vigueur
dans le pays d'exploitation — ces valeurs sont exposées en constantes pour
rester facilement modifiables) :
- Grumier standard (5-6 essieux) : PMA 44 tonnes
- Grumier renforcé / long (7+ essieux) : PMA 50 tonnes
"""

PMA_STANDARD_KG = 44000
PMA_RENFORCE_KG = 50000

SEUILS_PMA = {
    "STANDARD": PMA_STANDARD_KG,
    "RENFORCE": PMA_RENFORCE_KG,
}


def verifier_charge(poids_a_vide_kg: float, poids_charge_kg: float, categorie: str = "STANDARD") -> dict:
    """Calcule le poids total en charge et vérifie la conformité au PMA.
    Retourne un dictionnaire prêt à être stocké / affiché."""
    pma = SEUILS_PMA.get(categorie, PMA_STANDARD_KG)
    poids_total = round((poids_a_vide_kg or 0) + (poids_charge_kg or 0), 1)
    ecart = round(poids_total - pma, 1)
    conforme = poids_total <= pma
    return {
        "poids_a_vide_kg": poids_a_vide_kg,
        "poids_charge_kg": poids_charge_kg,
        "poids_total_kg": poids_total,
        "pma_reglementaire_kg": pma,
        "conforme": conforme,
        "ecart_kg": ecart,  # positif = dépassement, négatif = marge restante
    }
