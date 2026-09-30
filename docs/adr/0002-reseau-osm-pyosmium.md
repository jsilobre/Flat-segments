# 0002 — Réseau issu d'OpenStreetMap, lu avec pyosmium

- **Statut** : Acceptée
- **Date** : 2026-09-30

## Contexte

Il faut le réseau praticable à pied (voies piétonnes, cyclables, voies vertes,
chemins, petites routes) avec sa **topologie** : quelles voies se croisent et
où, pour chaîner les ways et compter les traversées de routes. Il faut aussi
des attributs (revêtement, éclairage, ponts, tunnels). Seul OSM offre tout
cela, librement, sur toute la France.

## Décision

- Source : **extrait Geofabrik** `europe/france/midi-pyrenees` (PBF), découpé
  sur l'emprise de la zone pilote. Le miroir d'OpenStreetMap France
  (`download.openstreetmap.fr`, même découpage, avec `.md5`) le remplace quand
  Geofabrik est inaccessible.
- Lecture avec **pyosmium** (`osmium` sur PyPI) : lecture en flux filtrée sur
  `highway`, coordonnées des nœuds résolues, **identifiants de nœuds
  conservés**. Reprojection immédiate en Lambert-93.
- Les voies sont classées en `PATH` / `MINOR` / `MAJOR` / exclues
  ([`algorithm.md` § 1](../algorithm.md#1-sélection-et-classement-des-voies)).
  Les routes `MAJOR` sont lues pour servir de barrières.
- Attribution ODbL sur le site ; les segments diffusés sont sous ODbL.

## Conséquences

- La topologie vient directement des nœuds partagés : pas de reconstruction
  géométrique approximative.
- Tout le chaînage (`network.py`) est écrit par nous. Il est pur et testé, ce
  qui donne un contrôle total sur la règle de continuité.
- La qualité dépend de la cartographie locale (tags manquants, trottoirs
  dédoublés) : valeurs `unknown` explicites et validation terrain.

## Alternatives considérées

- **pyrosm** (maintenu, *wheels* 3.12+) : produit directement des
  GeoDataFrames, ce qui est pratique pour explorer. Mais le graphe est reconstruit
  à sa façon, la topologie fine est moins accessible, et tout est chargé en
  mémoire. Il reste utile pour des analyses ponctuelles en notebook.
- **OSMnx / API Overpass** : dépend d'un service en ligne, moins reproductible,
  limites de requêtes.
- **Import PostGIS (osm2pgsql)** : pertinent en phase 3, surdimensionné pour
  le prototype.
