# 0001 — Pipeline hors ligne en Python, géré avec uv

- **Statut** : Acceptée
- **Date** : 2026-09-30

## Contexte

La détection croise un réseau de plusieurs milliers de kilomètres avec un MNT
au mètre. C'est trop lourd pour un navigateur, et inutile à refaire à chaque
visite : les données sources évoluent lentement (OSM au jour près, MNT sur
des années). L'écosystème géospatial le plus riche et le mieux outillé
(pyosmium, rasterio/GDAL, pyproj, geopandas, numpy) est en Python.

## Décision

- Un **pipeline hors ligne** en **Python ≥ 3.12** précalcule les segments.
  Il est organisé en commandes Typer (`extract`, `elevation`, `detect`,
  `export`) qui communiquent par fichiers.
- **uv** gère l'interpréteur, les dépendances (`pyproject.toml` + `uv.lock`
  versionné) et l'exécution (`uv run`).
- Outils de qualité : ruff (lint + format), mypy strict, pytest, pre-commit ;
  CI GitHub Actions.
- La logique de calcul est **pure** (numpy + dataclasses, sans E/S) pour être
  testée sur des données synthétiques.

## Conséquences

- Tests rapides et déterministes ; réglage des seuils sans relire les données
  brutes.
- Le même code servira l'API (phase 3) : seule la couche d'E/S changera.
- Les dépendances binaires (GDAL via rasterio, libosmium via pyosmium) sont
  distribuées en *wheels* pour Linux, macOS et Windows : pas de compilation.
- Les données ne sont pas « temps réel » : il faut relancer le pipeline pour
  intégrer les modifications d'OSM.

## Alternatives considérées

- **Tout dans PostGIS** (SQL + pgRouting) : puissant pour la phase 3, mais
  lourd à installer pour un prototype et moins pratique pour tester des
  algorithmes de profil.
- **Calcul dans le navigateur** : volumes de MNT prohibitifs.
- **pip/venv, Poetry** : uv est plus rapide, gère aussi l'interpréteur, et
  produit un lockfile multiplateforme.
