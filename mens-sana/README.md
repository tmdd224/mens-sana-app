# Mens Sana : application web

Application web de mise en relation entre patients et psychologues, avec rendez-vous au centre ou par appel, ateliers, programmes, abonnements, communauté et suivi par les proches.

## Lancer (2 minutes)
1. Installer Python 3.8 ou plus récent (python.org). Aucune autre installation n'est nécessaire.
2. Windows : double-cliquer sur `lancer.bat`. Autres systèmes : lancer `MENSSANA_DEMO=1 python3 server.py`.
3. Ouvrir http://127.0.0.1:8000. Le mode démo est local et le serveur écoute uniquement sur `127.0.0.1`.

Le lanceur Windows active explicitement le mode démo. Sans `MENSSANA_DEMO=1`, les comptes et données de démonstration ne sont pas créés et les comptes démo existants ne peuvent pas se connecter.
Le chemin de la base peut être déplacé avec `MENSSANA_DB_PATH` ; sinon, le fichier local est `mens_sana.db`.

**Données fictives uniquement.** Le mot de passe commun des comptes démo est `Demo2026!`. N’utilisez pas de vraies informations personnelles ou de santé dans cette version.

| Rôle | E-mail |
|---|---|
| Patient | awa@demo.sn (aussi moussa@, khady@, ibrahima@demo.sn) |
| Psychologue | dr.diagne@menssana.sn (aussi m.seck@, a.niang@menssana.sn) |
| Médecin | dr.gueye@menssana.sn |
| Parent | parent@demo.sn (enfant mineur : Ibrahima) |
| Parrain | parrain@demo.sn |
| Partenaire | partenaire@demo.sn |
| Administrateur | admin@menssana.sn |

Pour repartir de zéro : arrêter le serveur et supprimer `mens_sana.db`.

## Choix techniques
- Langage : Python (bibliothèque standard uniquement). Base : SQLite, 25 tables avec clés étrangères. Interface : HTML, CSS et JavaScript sans dépendance.
- API REST sous `/api`, droits vérifiés côté serveur pour chaque rôle.

## Tests
Depuis le dossier `mens-sana` : `python -B -m unittest discover -s tests -v`.

## Dépôt GitHub
Le dépôt GitHub exécute les tests automatiquement à chaque push. Le fichier `.gitignore` exclut la base locale, les environnements Python et les fichiers `.env`. Ne versionnez jamais de données réelles ni de secrets.

## Mettre en ligne une démo sur Render
Le dépôt contient un `render.yaml` qui prépare un service web Python gratuit. Pour le créer :
1. Connectez-vous à Render et choisissez **New > Blueprint**.
2. Reliez le dépôt GitHub `tmdd224/mens-sana-app` et sélectionnez la branche `main`.
3. Vérifiez le plan **Free**, puis appliquez le Blueprint. Render construit l’application et lance les tests.
4. Ouvrez l’adresse `https://mens-sana-demo.onrender.com` affichée dans le tableau de bord Render. Si ce nom est déjà pris, changez le nom du service ; Render fournit gratuitement son sous-domaine `onrender.com`.

Cette configuration active les comptes de démonstration et stocke la base SQLite sous `/tmp`. L’offre gratuite met le service en veille après 15 minutes sans trafic ; le premier accès après la veille peut prendre environ une minute. Le système de fichiers est temporaire : les changements de la démo peuvent disparaître au redémarrage ou au redéploiement. Les visiteurs peuvent modifier les données fictives avec les comptes démo.

**Démo uniquement :** n’entrez aucune vraie donnée personnelle ou de santé. Cette configuration gratuite n’est ni persistante ni adaptée à un service clinique. GitHub Pages ne peut pas exécuter l’API Python.

## Relations de la base (fichier server.py, SCHEMA)
Psychologue 1–N Patient (affectation avec historique) · Psychologue N–N Groupe · Psychologue N–N Atelier · Groupe N–N Atelier · Patient N–N Groupe · Patient N–N Atelier · Parent/Parrain/Partenaire N–N Patient (table `liens`, avec consentement) · Médecin 1–N Évaluation, Évaluation N–1 Programme, Programme N–N Psychologue · Rendez-vous N–1 Patient, Psychologue · Séance 1–1 Rendez-vous · Abonnement N–1 Patient · Paiement N–1 Abonnement (payeur : patient, parent, parrain ou partenaire) · Utilisateur N–N Communauté · Journal d'audit.

## Sécurité et limites
Cette maquette **n’est pas certifiée ISO/IEC 27001** et n’est pas prête pour des données réelles de santé. Elle contient des protections de base, mais ne fournit pas d’hébergement HTTPS, de chiffrement de la base, de sauvegardes chiffrées, de procédures de suppression ou de validation complète des habilitations cliniques.

## Avant une vraie mise en service
- Définir les règles de consentement et d’accès avec des professionnels du droit et de la santé.
- Déployer derrière une infrastructure HTTPS auditée, activer `MENSSANA_COOKIE_SECURE=1`, protéger les secrets, chiffrer et tester les sauvegardes.
- Paiement : le paiement est **simulé**, aucun argent n’est prélevé. L’intégration d’un agrégateur agréé au Sénégal nécessitera un compte et des identifiants prestataire.
- Téléconsultation : aucun appel ni lien vidéo n’est intégré ; les rendez-vous à distance doivent être organisés manuellement.
- Prix des formules : valeurs de démonstration.
- Faire valider par l'équipe Droit les obligations auprès de la Commission de protection des données personnelles, les CGU, la politique de confidentialité et les consentements.
- Non inclus : e-mails ou SMS de rappel, agenda de disponibilités des psychologues, appels vidéo réels, modération de la communauté.
