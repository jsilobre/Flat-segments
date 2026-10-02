# 0011 — Production sur GitHub Actions, données publiées hors de Git

- **Statut** : Acceptée
- **Date** : 2026-10-02

## Contexte

Le pipeline traite un département à la fois ([étape 2.1](../phase-2/2.1-departement.md)).
La Haute-Garonne (6 365 km²) prend 31 min 31 s, dont 24 min 38 s de
téléchargement du MNT. Extrapolé à la métropole (environ 86 fois plus
grand), cela donne :

- environ 45 h de calcul en séquentiel ;
- environ 400 Go de MNT transférés, supprimés au fur et à mesure ;
- 1 à 1,4 Go de PMTiles publiés.

Ce calcul ne peut pas se faire à la main, ni dans un environnement de travail
temporaire. Par ailleurs, le jeu publié était jusqu'ici versionné dans Git
(`web/data/`) :

- chaque régénération ajouterait plus de 20 Mo à l'historique, sans retour en
  arrière possible ;
- GitHub refuse les fichiers de plus de 100 Mo.

Le dépôt est public : les *runners* GitHub Actions sont gratuits. Chaque
tâche dispose d'environ 16 Go de mémoire et dure au plus 6 h. Jusqu'à 20
tâches peuvent tourner en parallèle.

## Décision

- **Production** : un workflow lancé à la main (`.github/workflows/produce.yml`),
  avec en paramètres la liste des départements (ou `all` pour la métropole),
  la publication ou non, et le parallélisme.
  1. **Préparation** :
     - téléchargement de l'extrait OSM France, depuis Geofabrik, ou le miroir
       d'OpenStreetMap France en secours ;
     - découpe par département avec osmium (commande `cut-osm`), en lots de 12
       départements par passage ;
     - dépôt des extraits dans la release `osm-extracts` (fichiers
       intermédiaires, remplacés à chaque lancement).
  2. **Une tâche par département** :
     - commande `department` sur son extrait ;
     - un échec n'arrête pas les autres départements, et on ne relance que les
       tâches en échec ;
     - parallélisme réglable, 4 départements à la fois par défaut, soit 16
       requêtes simultanées au service de l'IGN.
  3. **Assemblage** :
     - `export-pmtiles` sur tous les départements, en gardant les identifiants
       déjà publiés ([ADR 0012](0012-identifiants-stables.md)) ;
     - dépôt dans la release `data-latest` (`segments.pmtiles`,
       `segments.json`, `ids.tar.gz`) ;
     - lancement du workflow Pages ;
     - un département en échec bloque l'assemblage, pour ne pas publier un jeu
       incomplet.
- **Publication** :
  - le workflow Pages déploie le contenu de `data-latest` avec le site ;
  - les données publiées **sortent de Git** : seul le jeu d'exemple fictif
    reste dans `web/data/sample/` ;
  - tant que `data-latest` n'existe pas, Pages garde les fichiers de
    `web/data/`.
- **Régénération** : à la main pour l'instant, pas de lancement périodique.
- **Source OSM** : retour à Geofabrik ([ADR 0002](0002-reseau-osm-pyosmium.md)),
  accessible depuis les *runners*. Le miroir n'était qu'un contournement
  local.

## Conséquences

- **Calcul** : la métropole devient calculable en quelques heures, sans
  machine à soi. Le rythme réel dépendra de ce que le service de l'IGN
  accepte en parallèle : à mesurer avant de monter au-delà de 4 départements
  à la fois.
- **Historique Git** : il ne grossit plus avec les données. Une release ne
  garde que la dernière version : pour revenir en arrière, on relance la
  production.
- **Taille** : une release accepte des fichiers jusqu'à 2 Go, mais un site
  Pages est limité à 1 Go. Pour l'ex-Midi-Pyrénées, cela suffit. Pour la
  France (étape 2.5), les données iront sur un stockage d'objets (Cloudflare
  R2 pressenti). Seule la destination de l'assemblage changera.
- **Lecture directe impossible** : un fichier de release ne peut pas être lu
  directement par le navigateur. Sa redirection n'autorise pas les autres
  sites (pas de CORS), d'où son passage par le déploiement Pages.
- **Mise en service** : un workflow lancé à la main doit être sur `main` pour
  être lancé. On le fusionne d'abord, puis on l'essaie sur un petit
  département sans publier.

## Alternatives considérées

- **Calcul sur une machine louée** : il faut l'administrer et la payer, pour
  un calcul ponctuel.
- **Données dans Git** (sur `main` ou sur une branche réécrite à chaque fois)
  : l'historique grossit, ou il faut réécrire une branche. La limite de
  100 Mo par fichier reste.
- **Extrait régional par tâche** (sans découpe préalable) : un département au
  bord d'une région a besoin de l'extrait voisin pour sa marge. Une découpe
  unique de la France est plus simple. Elle donne exactement les mêmes voies
  que l'extrait régional : 186 363 sur 186 363 pour la Haute-Garonne.
