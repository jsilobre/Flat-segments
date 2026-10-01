# 0010 — Recherche d'adresse avec le géocodeur de l'IGN

- **Statut** : Acceptée
- **Date** : 2026-10-01

## Contexte

Le coureur donnait sa position par géolocalisation, par un clic sur la carte
ou en saisissant une latitude et une longitude. On veut aussi qu'il puisse
taper une **adresse postale**. Le front reste statique, sans serveur
([ADR 0005](0005-front-statique-maplibre.md), [ADR 0008](0008-couverture-nationale-precalcul-statique.md)).
Le service de géocodage doit donc :

- répondre directement au navigateur, depuis GitHub Pages (CORS ouvert) ;
- être gratuit, sans clé à cacher ;
- couvrir **toute la France**, comme le précalcul ;
- répondre assez vite pour suggérer des adresses pendant la saisie.

## Décision

- Les adresses sont cherchées avec le **service de géocodage de la
  Géoplateforme IGN** (`https://data.geopf.fr/geocodage/search`), qui
  s'appuie sur la Base Adresse Nationale.
  - Vérifié le 01/10/2026 : gratuit, sans clé, CORS ouvert
    (`access-control-allow-origin: *`).
  - C'est le même fournisseur que le relief ([ADR 0007](0007-altitude-lidar-hd.md)).
- **Saisie** : un même champ accepte une adresse ou « latitude, longitude ».
  Un texte qui se lit comme des coordonnées n'est pas envoyé au géocodeur.
- **Suggestions** :
  - au plus 5, demandées 300 ms après la dernière frappe, à partir de
    3 caractères (`autocomplete=1`) ;
  - classées d'abord autour du centre de la carte (paramètres `lat`, `lon`).
- **Validation** : Entrée prend la suggestion surlignée, ou la première.
- Les fonctions pures (URL de recherche, lecture de la réponse) sont dans
  `web/geocode.js`, testées avec `node --test` sur une réponse réelle
  enregistrée.

## Conséquences

- Le texte tapé et le centre de la carte partent vers un service tiers.
  Le service est public et ne demande aucune identification.
- Si le service est indisponible, la page le dit, et la saisie de
  coordonnées et la géolocalisation restent utilisables.
- Le service géocode des **adresses** (voies, numéros, communes), pas des
  lieux : « mairie de Caraman » donne une « place de la Mairie »,
  éventuellement dans une autre commune.
- La recherche est limitée à la France, comme les données.

## Alternatives considérées

- **Nominatim** (OpenStreetMap) : il couvre le monde entier et trouve aussi
  des lieux. Mais sa politique d'usage limite le service public à une
  requête par seconde et interdit l'autocomplétion. Il faudrait l'héberger
  soi-même.
- **API Adresse de data.gouv.fr** (`api-adresse.data.gouv.fr`) : même base et
  même format, mais elle migre vers la Géoplateforme. On s'adresse donc
  directement à celle-ci.
- **Services commerciaux** (Google, Mapbox…) : une clé visible dans un site
  statique, et des quotas payants.
