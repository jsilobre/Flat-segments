# 0013 — Données publiées sur Cloudflare R2

- **Statut** : Acceptée
- **Date** : 2026-10-02

## Contexte

Le jeu publié est déployé avec le site sur GitHub Pages, depuis la release
`data-latest` ([ADR 0011](0011-production-github-actions.md)). Pour la
France métropolitaine (étape 2.5), cela ne suffit plus :

- l'ex-Midi-Pyrénées fait 155 Mo de PMTiles, ce qui laisse attendre 1,5 à
  2 Go pour la métropole ;
- un site Pages est limité à 1 Go, et une release à 2 Go par fichier ;
- le navigateur ne peut pas lire une release directement (pas de CORS).

Il faut un stockage d'objets qui accepte les requêtes partielles et le CORS,
sans frais de trafic.

## Décision

- **Stockage** : les tuiles et l'index des identifiants sont publiés sur
  **Cloudflare R2**.
  - C'est le stockage recommandé pour PMTiles par Protomaps.
  - Gratuit jusqu'à 10 Go stockés et 10 millions de lectures par mois, sans
    frais de trafic sortant.
- **Accès public** : par l'adresse de développement `r2.dev` pendant le POC.
  - Elle est limitée en débit, sans cache Cloudflare.
  - On passera à un domaine à soi, géré par Cloudflare, à l'ouverture
    publique. L'adresse est une variable du dépôt (`R2_PUBLIC_URL`), et un
    changement ne demande qu'une republication.
- **Une version, des noms à elle** : `tiles/segments-<version>.pmtiles` et
  `ids/<version>/`, la version étant la date de l'assemblage.
  - Un navigateur ne peut pas mélanger des morceaux de deux versions.
  - Ces fichiers ne changent jamais : on les sert avec un cache d'un an.
  - Les deux dernières versions sont gardées, pour les pages restées ouvertes
    et pour revenir en arrière.
- **`segments.json`** :
  - il est publié à la racine du bucket, sans cache, et déployé avec le site
    sur Pages ;
  - il donne les adresses absolues des tuiles et de l'index
    (`tiles.url`, `tiles.index`), que la page lit telles quelles. Des
    adresses relatives restent possibles, par exemple en local ou pour le jeu
    d'exemple.
- **Contrôle préalable** : le workflow Production commence par vérifier le
  bucket, avant tout calcul :
  - écriture ;
  - lecture publique par morceaux (`206`) ;
  - en-tête CORS pour le site.
- **Rapprochement des identifiants** : la version précédente est relue sur R2
  ([ADR 0012](0012-identifiants-stables.md)).
- **Identifiants d'accès** : les clés R2 sont des *secrets* du dépôt
  (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`). Le nom du
  bucket et l'adresse publique sont des *variables* (`R2_BUCKET`,
  `R2_PUBLIC_URL`).
- **Repli** : sans ces réglages, le workflow publie dans la release
  `data-latest`, comme avant.

## Conséquences

- **Taille** : plus de limite pratique de taille pour la France. Le site
  Pages ne contient plus que le code et `segments.json`.
- **Coût** : une recherche coûte 15 à 45 lectures. Les 10 millions de
  lectures gratuites couvrent donc plus de 200 000 recherches par mois.
- **Volume** de la France : 1,68 Go de PMTiles, plus l'index des
  identifiants ([étape 2.5](../phase-2/2.5-france.md)).
- **Latence** : sans cache, R2 peut mettre plusieurs centaines de
  millisecondes par requête. Mesure de l'étape 2.5 par `r2.dev` : 1,2 à
  2,5 s par requête (médiane par recherche), 3 à 7 s pour afficher les
  résultats. Le domaine à soi, avec le cache Cloudflare, l'améliorera.
- **Dépendance** : un compte Cloudflare devient nécessaire au projet.

## Alternatives considérées

- **Backblaze B2** : 10 Go gratuits, mais trafic sortant gratuit seulement
  jusqu'à 3 fois le volume stocké.
- **Source Cooperative** : gratuit pour les données géographiques ouvertes,
  mais il dépend de l'accord et du financement de l'association.
- **Worker Cloudflare devant un bucket privé** : c'est la méthode de
  Protomaps. Mais c'est un composant de plus, et son cache n'a d'effet que
  sur un domaine à soi. À reconsidérer avec ce domaine.
- **Découper le jeu par région sur Pages** : la limite de 1 Go s'applique au
  site entier.
