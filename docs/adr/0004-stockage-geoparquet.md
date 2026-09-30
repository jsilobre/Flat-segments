# 0004 — Stockage prototype en GeoParquet, PostGIS plus tard

- **Statut** : Acceptée
- **Date** : 2026-09-30

## Contexte

Le pipeline produit des tables intermédiaires (strokes, profils) et une table
finale de segments, pour une seule région. Il n'y a ni accès concurrent ni
requête en ligne au stade prototype.

## Décision

- Tables géométriques (`strokes`, `segments`) en **GeoParquet** (Lambert-93),
  écrites et lues avec geopandas/pyarrow ; `profiles` en Parquet simple.
- Fichiers sous `data/` (non versionné) : `raw/`, `interim/`, `processed/`.
- Les structures imbriquées (`parts`, `events` des strokes) sont stockées en
  JSON texte, par simplicité et portabilité.
- **PostGIS** arrivera avec l'API (phase 3), avec le même schéma
  ([`data-model.md`](../data-model.md)).

## Conséquences

- Aucun serveur à installer ; les fichiers s'ouvrent dans QGIS, DuckDB
  (extension spatiale) ou geopandas pour inspection.
- Format colonnaire compressé, typé, et standard (spécification GeoParquet
  1.x).
- Pas de requête spatiale indexée ni de mise à jour partielle : acceptable
  pour une région recalculée d'un bloc.

## Alternatives considérées

- **GeoPackage** : bon format d'échange, mais plus lent et moins adapté à
  l'analytique colonnaire.
- **PostGIS dès maintenant** : utile pour l'API, prématuré pour le prototype.
- **GeoJSON partout** : verbeux et non typé. Réservé à l'export web.
