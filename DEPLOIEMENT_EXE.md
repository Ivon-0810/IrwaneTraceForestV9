# IrwaneTraceForest (ITF) — Guide de déploiement en exécutable Windows (.exe)

Propriétaire exclusif : **Gauthier MBILI** (myvongauthier@gmail.com)
Société éditrice : MEA SARL / Éditeur Système ITT

---

## ⚡ Important — pourquoi le .exe n'est pas déjà dans cette archive

Je construis et teste cette application dans un environnement Linux, sans accès
Internet. Or un fichier `.exe` Windows ne peut être compilé que **depuis un
Windows** (PyInstaller ne fait pas de compilation croisée Linux → Windows).
Je ne peux donc pas vous livrer un `.exe` généré par mes soins.

**Ce que je vous donne à la place :**
1. **`construire_exe.bat`** — un script à double-cliquer sur votre PC Windows,
   qui installe automatiquement tout ce qu'il faut et produit
   `dist\IrwaneTraceForest.exe` en une seule fois (1-2 minutes, connexion
   Internet nécessaire uniquement pour cette étape d'installation).
2. **Vous pouvez essayer l'application tout de suite, sans exe**, sur n'importe
   quel poste (Windows/Mac/Linux) avec Python installé :
   ```bat
   pip install -r requirements.txt
   python app.py
   ```
   puis ouvrez http://127.0.0.1:5000 — c'est exactement la même application,
   juste sans la fenêtre native ni l'icône de bureau.

## 0. Ce que vous avez reçu

```
itf/
├── construire_exe.bat      # Double-cliquez ici sur Windows pour tout compiler
├── app.py                 # Application Flask (routes, rôles, modules)
├── database.py             # Schéma SQLite + amorçage (tenants, essences, super-admin)
├── licensing.py             # Génération / validation des vouchers de licence
├── formulas.py              # Formules officielles de cubage
├── desktop_launcher.py      # Lanceur bureau (fenêtre native pywebview)
├── itf.spec                 # Fichier de build PyInstaller
├── requirements.txt
├── templates/                # Interfaces HTML (thème émeraude/ardoise)
└── static/css/style.css
```

Ce socle couvre : authentification par rôle, isolation multi-tenant (SOFOCAM,
ALPICAM, PALLISCO, SEFAC + création libre de nouvelles sociétés), écran de
verrouillage avec vouchers `ACT-[ENTREPRISE]-[JOURS]J-[CHECKSUM]-[ANNEE]`,
inventaire forestier, registre DF10, lettres de voiture, parc à grumes usine,
scierie/rendements, contrats d'export, journal d'audit et généalogie du bois.
**C'est une base fonctionnelle et testée, pas la totalité de chaque écran
possible** — voyez la section « Prochaines itérations » en bas de ce document.

---

## 1. Étapes de déploiement en exécutable (.exe)

Deux options : le script automatique (recommandé) ou les étapes manuelles
détaillées ci-dessous si vous préférez garder le contrôle de chaque étape.

**Option rapide :** installez Python (étape 1 ci-dessous), copiez le dossier
`itf` sur votre PC Windows, puis double-cliquez sur `construire_exe.bat`.
Tout le reste (étapes 2 à 5) est fait automatiquement.

Ces étapes se font **sur un poste Windows** (PyInstaller doit compiler sur le
système cible ; on ne peut pas fabriquer un .exe Windows depuis Linux/Mac).

### Étape 1 — Installer Python
Installez Python 3.11 ou 3.12 depuis python.org, en cochant **"Add Python to PATH"**.

### Étape 2 — Copier le projet et installer les dépendances
```bat
cd C:\ITF
pip install -r requirements.txt
```
Le fichier `requirements.txt` inclut désormais `reportlab` (PDF + code-barres)
et `openpyxl` (import/export Excel), en plus de Flask et pywebview.

### Étape 3 — Vérifier que l'application tourne normalement
```bat
python desktop_launcher.py
```
Une fenêtre native doit s'ouvrir avec l'écran de connexion ITF.
Testez la connexion Super-Admin puis fermez la fenêtre.

### Étape 4 — (Optionnel) Ajouter une icône
Placez un fichier `static/img/itf.ico` (format .ico, 256×256 recommandé).
Si vous n'avez pas d'icône, supprimez la ligne `icon=...` dans `itf.spec`.

### Étape 5 — Compiler l'exécutable
```bat
pyinstaller itf.spec
```
`itf.spec` déclare explicitement les imports « cachés » de `reportlab`
(génération PDF/code-barres) et `openpyxl` (Excel), que PyInstaller ne
détecte pas toujours automatiquement — ne les retirez pas du fichier spec.
L'exécutable final apparaît dans :
```
dist\IrwaneTraceForest.exe
```
C'est un **fichier unique (onefile)**, sans console visible, prêt à distribuer.

### Étape 6 — Tester l'exécutable
Double-cliquez sur `dist\IrwaneTraceForest.exe`. La base de données SQLite se
crée automatiquement dans :
```
%APPDATA%\IrwaneTraceForest\itf.db
```
(ce dossier persiste entre les lancements, contrairement au dossier temporaire
d'extraction de l'exécutable).

### Étape 7 — Distribuer aux sociétés clientes
Livrez **uniquement** `IrwaneTraceForest.exe` (+ éventuellement un raccourci
bureau). N'envoyez jamais les fichiers `.py` sources — voir section 2.

### Étape 8 — Premier lancement chez le client
1. Le client double-clique sur l'exécutable.
2. Il se connecte avec le compte ADMIN que vous lui aurez communiqué.
3. Changez immédiatement tous les mots de passe de démonstration
   (`Demo2026!`, `ChangeMoiMaintenant2026!`) — voir section 3.

---

## 2. Rendre le script Python visible uniquement de votre profil

Un exécutable PyInstaller `--onefile` **n'expose pas** le code source en clair
à l'utilisateur final : celui-ci ne voit que le binaire compilé. Cependant
PyInstaller n'est **pas un chiffrement fort** — un attaquant motivé avec des
outils comme `pyinstxtractor` peut extraire le bytecode `.pyc` et le
décompiler partiellement. Voici les couches de protection concrètes :

### a) Ne jamais distribuer les fichiers .py
Seul `dist\IrwaneTraceForest.exe` doit quitter votre machine. Gardez le
dossier source (`app.py`, `database.py`, `licensing.py`, etc.) uniquement en
local ou dans un dépôt privé (GitHub/GitLab privé) auquel vous seul avez accès.

### b) Restreindre l'accès au dossier source sur votre propre PC Windows
Pour que même un autre utilisateur Windows du même ordinateur ne puisse pas
lire vos fichiers sources, restreignez les permissions NTFS au dossier projet
à votre seul compte utilisateur (à exécuter dans une invite **Administrateur**) :

```bat
icacls "C:\ITF" /inheritance:r
icacls "C:\ITF" /grant:r "%USERNAME%":(OI)(CI)F
icacls "C:\ITF" /remove "Users" "Authenticated Users" "Everyone"
```
Cela retire l'accès à tout autre compte du poste et ne laisse que le vôtre
en contrôle total.

### c) Renforcer la protection du bytecode (optionnel, recommandé si le code
   circule sur plusieurs machines ou si des clients avancés pourraient tenter
   une rétro-ingénierie)
Utilisez **PyArmor** avant la compilation PyInstaller pour obfusquer le
bytecode Python :
```bat
pip install pyarmor
pyarmor gen -O dist_obf app.py database.py licensing.py formulas.py desktop_launcher.py
```
puis pointez `itf.spec` vers les fichiers obfusqués générés dans `dist_obf/`.

### d) Verrouillage applicatif (déjà en place)
Le module `licensing.py` garde la génération de vouchers strictement
réservée aux routes protégées par le décorateur `@super_admin_requis` dans
`app.py` : même en lisant le code, un tiers ne peut pas générer de voucher
valide sans passer par une session authentifiée en SUPER_ADMIN sur votre
propre installation (le calcul de somme de contrôle dépend de votre base).

> En résumé : la vraie barrière n'est pas « personne ne peut techniquement
> lire un .exe » (aucun exécutable n'est totalement inviolable), mais **le
> fait de ne jamais faire circuler le fichier .py**, de protéger le dossier
> source par les permissions NTFS de votre session Windows, et d'ajouter une
> obfuscation (PyArmor) si le niveau de risque le justifie.

---

## 3. Sécurité à traiter avant mise en production réelle

- Changez `app.secret_key` dans `app.py` (actuellement une valeur de démo).
- Changez tous les mots de passe de démonstration dès le premier lancement
  (super-admin et comptes ADMIN par société).
- Le hachage de mot de passe actuel (SHA-256 + sel fixe) est fonctionnel pour
  un MVP ; pour une mise en production, migrez vers `werkzeug.security`
  (`generate_password_hash` / `check_password_hash`, qui utilise bcrypt/scrypt
  avec sel aléatoire par utilisateur).
- Envisagez HTTPS si l'ERP est un jour exposé au-delà du poste local
  (actuellement conçu pour tourner en local via `127.0.0.1`).

---

## 4. Prochaines itérations possibles

Ce socle livre l'architecture complète (multi-tenant, rôles, licences,
formules de cubage officielles, audit) et une implémentation fonctionnelle
des 7 modules métiers. Peuvent être approfondis ensuite, module par module :
- Impression PDF de la Lettre de Voiture et des DF10 (code-barres inclus).
- Contrôle de charge à l'essieu (PMA 44t/50t) avec alertes.
- Tableaux de rapprochement fournisseurs tiers plus détaillés (parc usine).
- Écorçage / tronçonnage / séchage / rabotage en tant qu'étapes distinctes
  tracées dans la généalogie (actuellement la généalogie relie grume → LV ;
  l'extension vers sciages → colis → export peut être ajoutée).
- Export Excel/PDF des rapports d'audit FLEGT.
- Suite Python autonome packagée séparément (`irwanetrace_core.py`) si vous
  souhaitez aussi un outil hors-ligne indépendant du serveur Flask.

Dites-moi lesquels traiter en priorité et je les construis avec vous.

## 5. Déployer le serveur central de synchronisation (`sync_server.py`)

Ce script est **indépendant** de l'ERP local : il tourne sur une machine à vous
(VPS, serveur MEA SARL, etc.) disposant d'un accès Internet permanent, et reçoit
les données que chaque installation ITF lui envoie une fois connectée.

```bat
pip install Flask
python sync_server.py
```
Il écoute par défaut sur le port 6000 (`http://0.0.0.0:6000`). Depuis chaque
poste avec ITF installé, connectez-vous en Super-Admin, ouvrez **Synchronisation**
dans le menu, et renseignez l'URL publique de ce serveur (ex :
`https://sync.itf-mea.com` si vous le mettez derrière un nom de domaine et HTTPS
— fortement recommandé pour un usage réel, via un reverse proxy comme Nginx ou
Caddy). Un tableau de bord de suivi est disponible à la racine du serveur central
(`/`), listant chaque réception par société.

> Le récepteur central actuel journalise les paquets reçus (aucune fusion
> automatique dans une base consolidée) — une étape naturelle de suite serait
> d'ajouter la re-création d'une base agrégée consultable, si vous en avez besoin.

## 6. Icônes et branding

Le logo fourni a été décliné automatiquement en :
- `static/img/favicon.png` — favicon affiché dans l'onglet du navigateur
- `static/img/logo_badge.png` — icône affichée dans la barre latérale et sur
  l'écran de connexion
- `static/img/itf.ico` — icône Windows multi-résolution (16 à 256px), déjà
  référencée dans `itf.spec` pour l'exécutable `.exe`

Pour changer de logo plus tard, remplacez ces trois fichiers en conservant les
mêmes noms et dimensions (carré, fond inclus).
