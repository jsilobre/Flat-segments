# 0005 — Front statique MapLibre d'abord, API ensuite

- **Statut** : Acceptée ; rôle de l'API revu par l'[ADR 0008](0008-couverture-nationale-precalcul-statique.md)
- **Date** : 2026-09-30

## Contexte

Pour une zone pilote, le nombre de segments reste modeste (quelques milliers,
quelques Mo de GeoJSON). Tous les filtres (longueur, pente, distance,
traversées) peuvent s'appliquer côté navigateur. Le projet est personnel :
pas de serveur à maintenir si on peut l'éviter.

## Décision

- **Site statique** dans `web/`, **sans étape de build** : HTML + modules ES,
  hébergeable sur GitHub Pages.
- Carte **MapLibre GL JS** (version figée, chargée depuis un CDN). Elle est
  vectorielle, performante, et lit nativement les PMTiles via le protocole
  `pmtiles://` : c'est l'évolution prévue si le volume grossit. Depuis la
  version 6, MapLibre n'est distribué qu'en modules ES : on le charge par une
  *import map* avec empreintes SRI. MapLibre crée lui-même son *worker* à
  partir du CDN.
- Fond de carte **OpenFreeMap** (tuiles vectorielles OSM, sans clé). En cas
  d'indisponibilité du fond, la page reste utilisable (segments sur fond neutre).
- Données : `web/data/segments.geojson` précalculé, filtré dans le navigateur.
  Position par géolocalisation, point placé sur la carte (bouton, puis clic ;
  déplaçable), saisie lat, lon ou adresse ([ADR 0010](0010-geocodage-ign.md)).
- Logique de filtrage isolée dans un module pur (`filters.js`), testé avec
  `node --test`.
- Attributions OSM, IGN et OpenFreeMap affichées sur la carte.

## Conséquences

- Coût d'hébergement nul, déploiement trivial, fonctionnement hors serveur.
- Tout le jeu de données est téléchargé : on passe aux **PMTiles** au-delà
  d'environ 10 Mo de GeoJSON (phase 2).
- Pas de calcul à la demande : une zone non précalculée est vide. C'est ce que
  résoudra l'**API FastAPI + PostGIS** (phase 3).

## Alternatives considérées

- **Leaflet** : plus simple, mais raster et sans PMTiles vectoriel natif.
- **Framework (React, Svelte…) + bundler** : superflu pour une page.
- **Plan IGN vectoriel** comme fond : excellent en France, mais pas au-delà.
  Pourra être proposé comme fond alternatif.
- **Tuiles raster tile.openstreetmap.org** : politique d'usage restrictive pour
  un site public.
