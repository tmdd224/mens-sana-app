# Mens Sana

Application web de mise en relation entre patients et professionnels de santé, avec rendez-vous, ateliers, programmes de suivi, abonnements et espaces communautaires.

## Lancer en local

1. Installer Python 3.8 ou une version plus récente. Aucune dépendance externe n'est requise.
2. Sous Windows, double-cliquer sur `lancer.bat`. Sinon, depuis ce dossier, exécuter `python server.py`.
3. Ouvrir http://127.0.0.1:8000.

La base SQLite est créée à côté de `server.py`. Son emplacement peut être défini avec `MENSSANA_DB_PATH`. Le serveur local n'écoute que sur `127.0.0.1` par défaut.

## Comptes et rôles

Les patients, parents ou tuteurs, parrains, partenaires, psychologues et médecins peuvent créer leur compte depuis la page de connexion. Les comptes professionnels sont activés immédiatement. Ils ne voient aucun dossier patient avant qu'un administrateur leur attribue des patients.

L'administrateur crée son compte au premier démarrage avec les variables `MENSSANA_ADMIN_EMAIL`, `MENSSANA_ADMIN_NAME` et `MENSSANA_ADMIN_PASSWORD` ; choisissez un mot de passe d'au moins 14 caractères. Ce rôle n'est pas disponible dans l'inscription publique. L'administrateur attribue aussi les patients et vérifie les liens de suivi des proches.

## Fonctionnalités

- Dossiers et rendez-vous soumis aux permissions du rôle et aux affectations.
- Évaluations psychologiques rattachées aux séances et évaluations médicales séparées.
- Historique des appels : les rapports brefs sont réservés aux professionnels de santé concernés.
- Communautés créées et gérées par un administrateur ou le psychologue créateur.
- Annuaire public des partenaires, géré par l'administrateur. Il démarre sans partenaire prérempli ; n'ajoutez que des organisations autorisées à être affichées.
- Reçus imprimables et choix de moyens de paiement.

Les paiements ne sont pas reliés aux prestataires Wave, Orange Money, Free Money ou bancaires : l'application enregistre les informations et ouvre l'abonnement, mais aucun débit n'est effectué. Les rendez-vous à distance ne lancent pas d'appel et ne créent pas de lien vidéo ; ils doivent être organisés par l'équipe.

## Tests

Depuis ce dossier :

```powershell
python -B -m unittest discover -s tests -v
```

Le dépôt GitHub exécute aussi ces tests à chaque push.

## Déploiement sur Render

Le fichier `render.yaml` configure le service web Python et demande à Render d'attendre la réussite des contrôles GitHub Actions avant chaque déploiement sur `main`.

1. Relier une seule fois le dépôt GitHub `tmdd224/mens-sana-app` à Render (ou synchroniser le Blueprint existant). Choisir la branche `main`.
2. Renseigner les variables `MENSSANA_ADMIN_EMAIL`, `MENSSANA_ADMIN_NAME` et `MENSSANA_ADMIN_PASSWORD`, puis examiner et appliquer la configuration.
3. Dans les paramètres du service Render, vérifier que le déploiement automatique est réglé sur **After CI Checks Pass**.
4. À chaque `git push` sur `main`, GitHub Actions exécute les tests Python 3.8 et 3.12. Render déploie ensuite le commit si les contrôles sont réussis.
5. Utiliser l'adresse fournie par Render.

Le plan gratuit peut mettre le service en veille et son stockage de fichiers est temporaire ; les données SQLite peuvent disparaître lors d'un redémarrage ou d'un redéploiement. Ce déploiement ne convient pas à la conservation de données personnelles ou de santé.

## Avant toute mise en service clinique

Cette application n'est ni certifiée ISO/IEC 27001 ni prête pour des données réelles de santé. Elle ne fournit pas encore de chiffrement de base de données ou de sauvegardes chiffrées. Avant son utilisation clinique, faire auditer les habilitations, mettre en place un hébergement sécurisé et des sauvegardes vérifiées, intégrer les prestataires requis, puis faire valider les consentements et obligations juridiques au Sénégal.
