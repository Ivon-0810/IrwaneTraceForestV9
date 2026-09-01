# -*- coding: utf-8 -*-
"""
IrwaneTraceForest (ITF) - Lanceur bureau
Encapsule le serveur Flask local dans une fenêtre native (pywebview) afin de
produire une véritable application de bureau (.exe) avec PyInstaller.

Propriétaire exclusif : Gauthier MBILI (myvongauthier@gmail.com)
NE PAS DISTRIBUER CE FICHIER SOURCE. Seul l'exécutable compilé (.exe) doit
être livré aux sociétés clientes (SOFOCAM, ALPICAM, PALLISCO, SEFAC, etc.).
"""

import threading
import time
import socket
import sys
import os

from database import init_db
from app import app

TITRE_FENETRE = "IrwaneTraceForest — ERP Traçabilité Forestière"


def port_libre(host="127.0.0.1", port=5000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) != 0


def lancer_serveur_flask():
    init_db(reset=False)
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


def chemin_ressource(relatif: str) -> str:
    """Résout un chemin de fichier embarqué, aussi bien en exécution normale
    qu'une fois empaqueté en .exe par PyInstaller (dossier temporaire _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relatif)


def forcer_icone_barre_des_taches(titre_fenetre: str, chemin_icone: str,
                                   tentatives: int = 60, delai: float = 0.25):
    """Sur Windows, pywebview (backend WebView2/WinForms) affiche parfois une
    icône générique dans la barre des tâches et le bandeau de fenêtre, même
    quand l'exécutable a bien sa propre icône. On corrige ça explicitement en
    envoyant un message WM_SETICON à la fenêtre une fois qu'elle existe.
    Sans effet et sans erreur sur toute autre plateforme (Linux/Mac) ou si
    pywin32 n'est pas disponible."""
    if sys.platform != "win32":
        return
    try:
        import win32gui
        import win32con
    except ImportError:
        return  # pywin32 absent : l'icône de l'exécutable (déjà définie) prévaut

    if not os.path.exists(chemin_icone):
        return

    hwnd = None
    for _ in range(tentatives):
        hwnd = win32gui.FindWindow(None, titre_fenetre)
        if hwnd:
            break
        time.sleep(delai)
    if not hwnd:
        return

    try:
        flags = win32con.LR_LOADFROMFILE
        icone_grande = win32gui.LoadImage(0, chemin_icone, win32con.IMAGE_ICON, 0, 0, flags)
        icone_petite = win32gui.LoadImage(0, chemin_icone, win32con.IMAGE_ICON, 16, 16, flags)
        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, icone_grande)
        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, icone_petite)
    except Exception:
        pass  # Ne doit jamais empêcher l'application de fonctionner


def main():
    thread_serveur = threading.Thread(target=lancer_serveur_flask, daemon=True)
    thread_serveur.start()

    # Laisse le temps au serveur Flask local de démarrer avant d'ouvrir la fenêtre
    for _ in range(50):
        if not port_libre():
            break
        time.sleep(0.1)

    try:
        import webview
        webview.create_window(
            TITRE_FENETRE,
            "http://127.0.0.1:5000",
            width=1440,
            height=900,
            min_size=(1100, 700),
        )

        chemin_icone = chemin_ressource(os.path.join("static", "img", "itf.ico"))
        threading.Thread(
            target=forcer_icone_barre_des_taches,
            args=(TITRE_FENETRE, chemin_icone),
            daemon=True,
        ).start()

        webview.start()
    except ImportError:
        # Repli si pywebview n'est pas installé : ouvre le navigateur par défaut.
        import webbrowser
        webbrowser.open("http://127.0.0.1:5000")
        print("pywebview n'est pas installé — ouverture dans le navigateur par défaut.")
        print("Fermez cette fenêtre de console pour arrêter le serveur ITF.")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
