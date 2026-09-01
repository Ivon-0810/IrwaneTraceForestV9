# IrwaneTraceForest (ITF)
ERP de traçabilité forestière & industrielle — Bassin du Congo (Cameroun, Gabon, Congo, RDC)

Conçu et propriété exclusive de **Gauthier MBILI** (myvongauthier@gmail.com)
Société mère éditrice : MEA SARL / Éditeur Système ITT

## En cas de mot de passe Super-Admin perdu

Si le compte Super-Admin est verrouillé (mot de passe oublié ou changé sans
avoir été noté), une procédure de récupération existe — elle nécessite un
accès physique à la machine où tourne l'application (ce n'est pas exploitable
à distance) :

1. Repérez le dossier contenant `itf.db` :
   - Version `.exe` : `%APPDATA%\IrwaneTraceForest\`
   - Version `python app.py` : le dossier du projet lui-même
2. Créez dedans un fichier texte **vide**, nommé exactement `RESET_SUPER_ADMIN.txt`
3. Pendant que l'application tourne, ouvrez un navigateur (Chrome, Edge...)
   à l'adresse : `http://127.0.0.1:5000/recuperation-urgence`
4. Un nouveau mot de passe temporaire s'affiche à l'écran — notez-le, le
   fichier déclencheur est automatiquement supprimé (récupération à usage
   unique) et un changement de mot de passe personnel sera exigé à la
   prochaine connexion.

Sans ce fichier créé à la main sur la machine, cette page renvoie une simple
erreur 404 — elle n'expose donc aucune faille utilisable à distance.

## Démarrage rapide (test local, tout OS)
```bash
pip install -r requirements.txt
python app.py
```
Puis ouvrez http://127.0.0.1:5000

Comptes de démonstration (**à changer avant toute mise en production**) :
- Super-Admin : `myvongauthier@gmail.com` / `ChangeMoiMaintenant2026!`
- Admin par société : `admin@sofocam.itf`, `admin@alpicam.itf`, `admin@pallisco.itf`,
  `admin@sefac.itf` — mot de passe `Demo2026!`

## Générer l'exécutable Windows (.exe)
Voir **DEPLOIEMENT_EXE.md** pour la procédure complète (compilation PyInstaller
+ protection du code source).

## Structure
- `app.py` — routes Flask, rôles, isolation multi-tenant
- `database.py` — schéma SQLite + amorçage + migrations additives idempotentes (`_migrer_colonnes_additionnelles`)
- `licensing.py` — licences, vouchers d'auto-réactivation
- `formulas.py` — formules officielles de cubage (arbre sur pied, grume)
- `charge_essieu.py` — contrôle de charge à l'essieu (PMA standard/renforcé)
- `pdf_documents.py` — génération PDF (DF10, LV Grumes/Bois débité, CEU) avec code-barres Code128
- `excel_io.py` — import/export Excel générique (inventaire, production, stock, audit)
- `core_export.py` — Module 8 : suite Python autonome, export réservé au Super-Admin
- `sync.py` — détection de connexion Internet + synchronisation un-clic vers le serveur central
- `sync_server.py` — serveur central de réception (à déployer séparément, côté Super-Admin)
- `desktop_launcher.py` — fenêtre native pour la version bureau
- `templates/`, `static/` — interface (thème Émeraude/Sombre commutable, logo IrwaneTraceForest)

## Chaque société a son interface exclusive
Un utilisateur d'une société (SOFOCAM, ALPICAM, PALLISCO, SEFAC, ou toute société créée
ensuite) ne voit jamais les données d'une autre société : chaque requête est filtrée par
`tenant_id` côté serveur, jamais côté affichage seul. La bannière « Interface exclusive —
[Nom de la société] » le rappelle visuellement dans la barre latérale. Seul le Super-Admin
(Gauthier MBILI) a une vue globale, via la console dédiée.

## Mode hors-ligne & synchronisation (V3)
L'application fonctionne **entièrement hors connexion** sur sa base SQLite locale — aucune
fonctionnalité n'est bloquée sans Internet. Dès qu'une connexion est détectée, la page
**Synchronisation** (menu latéral) active le bouton « Synchroniser maintenant » en un clic
(et le désactive automatiquement si la connexion est perdue). Le serveur central
(`sync_server.py`) est un script indépendant à déployer par le Super-Admin sur une machine
connectée en permanence ; chaque installation locale (par société) lui envoie ses données
une fois en ligne. Voir DEPLOIEMENT_EXE.md pour la mise en place.

## Évolution V2 (par rapport à la V1)
Ajouts additifs uniquement, sans rien casser de l'existant (voir DEPLOIEMENT_EXE.md
pour le détail des nouvelles routes) :
- Étapes de transformation facultatives et non bloquantes (Écorçage, Tronçonnage,
  Sciage primaire, Séchage, Rabotage) — module `/transformation`.
- Lettre de Voiture Grumes **et** Bois Débité, Carnet Entrée Usine (CEU), export PDF
  avec code-barres pour DF10, LV et CEU.
- Contrôle de charge à l'essieu intégré à l'émission de la Lettre de Voiture (facultatif,
  n'empêche jamais l'édition — signale simplement la non-conformité).
- Généalogie enrichie : souche → LV → réception (CEU) → étapes de transformation →
  lot de sciage → LV bois débité, avec liste des intervenants.
- Module 8 sécurisé : export de `irwanetrace_core.py`, strictement réservé au Super-Admin
  (vérifié côté serveur, page `/module8`).
- Import/Export Excel pour l'inventaire, le registre DF10, la production scierie,
  le stock usine et le journal d'audit.
- Commutateur de thème Émeraude / Sombre, mémorisé en session.
