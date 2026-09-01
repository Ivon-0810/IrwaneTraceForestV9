# Obtenir IrwaneTraceForest.exe SANS RIEN INSTALLER
## (uniquement avec votre navigateur — aucun droit administrateur nécessaire)

Ce guide utilise **GitHub Actions** : un service gratuit qui met à disposition
une vraie machine Windows dans le cloud pour compiler votre application. Vous
n'installez rien sur votre PC de bureau — tout se passe dans le navigateur.

---

## Étape 1 — Créer un compte GitHub (2 minutes)

1. Allez sur https://github.com/signup
2. Créez un compte gratuit avec votre e-mail (myvongauthier@gmail.com par exemple)
3. Confirmez votre e-mail

## Étape 2 — Créer un nouveau dépôt (« repository »)

1. Une fois connecté, cliquez sur le bouton **vert "New"** (ou allez sur
   https://github.com/new)
2. Nom du dépôt : `irwanetraceforest` (ou ce que vous voulez)
3. Laissez-le en **Public** (plus simple, gratuit et illimité pour ce type
   d'usage) ou **Private** si vous préférez — les deux fonctionnent
4. Cliquez sur **"Create repository"**

## Étape 3 — Envoyer les fichiers (glisser-déposer, comme un e-mail)

1. Sur la page de votre nouveau dépôt vide, cliquez sur le lien
   **"uploading an existing file"**
2. Sur votre PC, ouvrez le dossier `itf` que je vous ai donné (celui extrait
   du fichier .zip)
3. **Sélectionnez TOUT le contenu à l'intérieur du dossier `itf`** (app.py,
   database.py, templates, static, .github, etc. — pas le dossier `itf`
   lui-même, son **contenu**) et glissez-le dans la zone de dépôt du
   navigateur
4. Attendez que la barre de progression se termine (peut prendre 1-2 minutes
   selon votre connexion)
5. Tout en bas de la page, cliquez sur le bouton vert **"Commit changes"**

**Important :** vérifiez bien que vous envoyez le *contenu* du dossier `itf`
(vous devez voir `app.py` directement listé après l'envoi), pas un dossier
`itf` qui contiendrait lui-même ces fichiers.

## Étape 4 — La compilation démarre automatiquement

1. Cliquez sur l'onglet **"Actions"** en haut de la page de votre dépôt
2. Vous devez voir un traitement en cours, nommé **"Construire
   IrwaneTraceForest.exe"**, avec un petit rond orange qui tourne
3. Cliquez dessus pour voir la progression en direct
4. Patientez environ **2 à 4 minutes**

## Étape 5 — Télécharger votre .exe

1. Une fois le rond orange devenu une **coche verte** ✅, faites défiler la
   page vers le bas
2. Dans la section **"Artifacts"**, cliquez sur **"IrwaneTraceForest-exe"**
   pour le télécharger
3. Vous obtenez un fichier `.zip` — dézippez-le
4. À l'intérieur : **`IrwaneTraceForest.exe`**, prêt à double-cliquer !

---

## Si l'étape 4 ne démarre pas toute seule

Cliquez sur l'onglet **"Actions"**, puis dans le menu de gauche cliquez sur
**"Construire IrwaneTraceForest.exe"**, puis sur le bouton **"Run workflow"**
à droite (menu déroulant) → **"Run workflow"** à nouveau pour confirmer.

## Pour les mises à jour futures

Si je vous envoie une nouvelle version du code, répétez simplement l'étape 3
(envoyer les nouveaux fichiers, "Commit changes") — la compilation se relance
automatiquement et un nouveau `.exe` sera disponible dans "Actions" quelques
minutes après.

## Confidentialité

Si vous mettez le dépôt en **Public**, le code source sera visible par
n'importe qui sur Internet. Si c'est un problème pour vous (propriété
exclusive du système), choisissez **Private** à l'étape 2 — GitHub offre
suffisamment de minutes de compilation gratuites par mois pour un usage
comme celui-ci, même en privé.
