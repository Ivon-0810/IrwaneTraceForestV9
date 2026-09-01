# -*- coding: utf-8 -*-
"""Formules métier de cubage - IrwaneTraceForest"""

import math


def volume_arbre_sur_pied(diametre_cm: float, hauteur_m: float, facteur_forme: float = 0.7) -> float:
    """V = (pi * D^2 / 4) * H * Fforme, D en mètres."""
    d_m = diametre_cm / 100.0
    return round((math.pi * d_m ** 2 / 4.0) * hauteur_m * facteur_forme, 4)


def volume_grume(diametre_gros_bout_cm: float, diametre_petit_bout_cm: float, longueur_m: float) -> float:
    """Cubage officiel au diamètre moyen (méthode Bassin du Congo) :
    Dm = (D1 + D2) / 2 ; V = pi * Dm^2 / 40000 * L"""
    dm = (diametre_gros_bout_cm + diametre_petit_bout_cm) / 2.0
    return round((math.pi * dm ** 2 / 40000.0) * longueur_m, 4)


def rendement_matiere(volume_grume_m3: float, volume_sciages_m3: float) -> float:
    if not volume_grume_m3:
        return 0.0
    return round((volume_sciages_m3 / volume_grume_m3) * 100.0, 2)
