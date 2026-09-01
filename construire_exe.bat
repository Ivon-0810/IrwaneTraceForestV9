@echo off
REM ============================================================
REM IrwaneTraceForest (ITF) - Construction automatique du .exe
REM Double-cliquez sur ce fichier depuis un Windows avec Python installé.
REM Propriétaire exclusif : Gauthier MBILI (myvongauthier@gmail.com)
REM ============================================================

echo.
echo ===============================================
echo   IrwaneTraceForest - Construction de l'exe
echo ===============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Installez Python 3.11 ou 3.12 depuis https://www.python.org/downloads/
    echo puis cochez "Add Python to PATH" lors de l'installation.
    pause
    exit /b 1
)

echo [1/4] Installation des dependances (Flask, pywebview, reportlab, openpyxl, PyInstaller)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] Echec de l'installation des dependances.
    pause
    exit /b 1
)

echo.
echo [2/4] Initialisation de la base de donnees locale...
python database.py

echo.
echo [3/4] Compilation de l'executable avec PyInstaller...
python -m PyInstaller itf.spec --noconfirm
if errorlevel 1 (
    echo [ERREUR] Echec de la compilation. Verifiez les messages ci-dessus.
    pause
    exit /b 1
)

echo.
echo [4/4] Termine !
echo.
echo   Votre executable se trouve dans : dist\IrwaneTraceForest.exe
echo   Vous pouvez le deplacer et le distribuer tel quel.
echo.
pause
