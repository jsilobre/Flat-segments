# Modèle de données

Ce document décrit le schéma des tables produites par le pipeline. La table
centrale est **`segments`** : c'est elle que consomme le front, et elle
deviendra une table PostGIS en phase 3. Les tables intermédiaires (`strokes`,
`profiles`) sont décrites en fin de document.

Version du schéma : **0.1**. Elle figure dans les métadonnées de l'export et
évolue à chaque changement incompatible.

## Conventions

- **Unités** : mètres (`_m`), pourcentages (`_pct`), degrés (`_deg`).
- **Pentes signées** dans le sens de la géométrie : positif = montée. Les côtes
  sont orientées vers le haut, leur `grade_mean_pct` est donc toujours > 0.
- **Géométrie** : `LineString`, en Lambert-93 (EPSG:2154) dans le GeoParquet
  et en WGS84 (EPSG:4326) dans le GeoJSON.
- **Valeurs inconnues** : `"unknown"` pour les catégories, `null` pour les
  nombres absents. Jamais de chaîne vide.
- **Listes** : tableaux JSON dans le GeoJSON, colonnes `list<…>` dans le
  GeoParquet.

## Table `segments`

Fichiers : `data/processed/segments.parquet` (GeoParquet) et
`web/data/segments.geojson` (export). En Python : dataclass
`flat_segments.detect.Segment`.

| Champ | Type | Unité | Description |
|---|---|---|---|
| `id` | `str` | — | Identifiant stable `"{kind}-{12 hex}"`, voir [`algorithm.md` § 12](algorithm.md#12-identifiant-stable) |
| `kind` | `"flat"` \| `"climb"` | — | Type de segment |
| `geometry` | `LineString` | — | Sous-polyligne exacte du réseau OSM ; côtes orientées vers le haut |
| `length_m` | `float` | m | Longueur le long de la géométrie |
| `elev_start_m` | `float` | m | Altitude (lissée) au début |
| `elev_end_m` | `float` | m | Altitude (lissée) à la fin |
| `elev_gain_m` | `float` | m | Dénivelé positif cumulé (D+), hystérésis 0,5 m |
| `elev_loss_m` | `float` | m | Dénivelé négatif cumulé (D-), valeur positive |
| `grade_mean_pct` | `float` | % | Pente moyenne `(elev_end − elev_start) / length`, signée |
| `grade_max_pct` | `float` | % | Pente locale maximale en valeur absolue (base 20 m) |
| `sinuosity` | `float` | — | Longueur / distance à vol d'oiseau entre extrémités (≥ 1) |
| `n_crossings` | `int` | — | Intersections avec une route circulée (`MINOR`) à l'intérieur du segment |
| `n_junctions` | `int` | — | Carrefours avec d'autres chemins à l'intérieur du segment |
| `surface` | `str` | — | Revêtement majoritaire : `paved`, `compacted`, `gravel`, `cobbles`, `unpaved`, `unknown` |
| `lit` | `str` | — | Éclairage : `yes`, `partial`, `no`, `unknown` |
| `name` | `str` \| `null` | — | Nom OSM majoritaire (tag `name`) |
| `highways` | `list[str]` | — | Valeurs `highway` rencontrées, par longueur décroissante |
| `osm_way_ids` | `list[int]` | — | Ways OSM traversées, dans l'ordre |
| `on_structure` | `bool` | — | Passe sur un pont ou dans un tunnel |
| `quality_flags` | `list[str]` | — | Voir ci-dessous |
| `fits_targets_m` | `list[int]` | m | Longueurs cibles réalisables dans le segment (§ 8 de l'algorithme) |
| `score` | `float` | 0–100 | Qualité globale, voir [`algorithm.md` § 10](algorithm.md#10-score) |
| `elevation_source` | `str` | — | Source d'altitude : `rge_alti_1m` (ou `lidar_hd`, `copernicus_glo30`, `synthetic`) |

Champs **internes**, présents seulement dans le GeoParquet :

| Champ | Type | Description |
|---|---|---|
| `stroke_id` | `str` | Stroke d'origine |
| `stroke_start_m` | `float` | Abscisse de début sur le stroke (sens du stroke) |
| `stroke_end_m` | `float` | Abscisse de fin sur le stroke |

### `quality_flags`

| Flag | Signification |
|---|---|
| `bridge_interpolated` | Altitude interpolée sur un pont |
| `tunnel_interpolated` | Altitude interpolée dans un tunnel ou un passage couvert |
| `gap_filled` | Trou *nodata* du MNT comblé par interpolation |
| `dem_coarse` | MNT de repli à 30 m : plats peu fiables (phase 3) |

### Ce qui n'est **pas** dans la table

- **Distance à l'utilisateur** : elle dépend de la position, le front la
  calcule.
- **Rang** : il dépend des filtres choisis ; le front trie.

## Export GeoJSON

`FeatureCollection` conforme à la RFC 7946 : WGS84, coordonnées `[lon, lat]`
arrondies à 6 décimales. Les champs internes sont retirés. Un membre
`metadata` (membre étranger, toléré par la RFC) décrit l'export.

```json
{
  "type": "FeatureCollection",
  "metadata": {
    "schema_version": "0.1",
    "generated_at": "2026-09-30T12:00:00Z",
    "sample": false,
    "attribution": [
      "© les contributeurs d'OpenStreetMap (ODbL)",
      "IGN – RGE ALTI® (Licence Ouverte 2.0)"
    ]
  },
  "features": [
    {
      "type": "Feature",
      "id": "flat-3fa2b1c9d0e4",
      "geometry": {
        "type": "LineString",
        "coordinates": [[1.534021, 43.531870], [1.538412, 43.532005]]
      },
      "properties": {
        "id": "flat-3fa2b1c9d0e4",
        "kind": "flat",
        "length_m": 412.5,
        "elev_start_m": 151.2,
        "elev_end_m": 151.9,
        "elev_gain_m": 0.7,
        "elev_loss_m": 0.0,
        "grade_mean_pct": 0.17,
        "grade_max_pct": 0.9,
        "sinuosity": 1.02,
        "n_crossings": 0,
        "n_junctions": 2,
        "surface": "paved",
        "lit": "unknown",
        "name": "Voie verte",
        "highways": ["cycleway"],
        "osm_way_ids": [123456789],
        "on_structure": false,
        "quality_flags": [],
        "fits_targets_m": [200, 400],
        "score": 86.4,
        "elevation_source": "rge_alti_1m"
      }
    }
  ]
}
```

Précision des valeurs numériques à l'export : longueurs et altitudes à 0,1 m,
pentes à 0,01 %, sinuosité à 0,01, score à 0,1. Si `metadata.sample` vaut
`true`, les données sont **fictives** et le front affiche un bandeau.

## Tables intermédiaires

### `strokes` (`data/interim/strokes.parquet`)

Produite par `extract`. GeoParquet en Lambert-93, une ligne par stroke.
En Python : `flat_segments.network.Stroke`.

| Champ | Type | Description |
|---|---|---|
| `stroke_id` | `str` | `"s000001"`… (numérotation propre à un run) |
| `geometry` | `LineString` | Polyligne complète |
| `length_m` | `float` | Longueur |
| `is_ring` | `bool` | Stroke fermé (anneau) |
| `parts` | `str` (JSON) | Liste de `StrokePart` : `way_id`, `start_m`, `end_m`, `highway`, `road_class`, `surface`, `tracktype`, `lit`, `structure`, `name` |
| `events` | `str` (JSON) | Liste de `StrokeEvent` : `offset_m`, `kind` (`crossing` \| `junction`), `node_id` |

### `profiles` (`data/interim/profiles.parquet`)

Produite par `elevation`. Parquet simple (sans géométrie), une ligne par
stroke. La grille des abscisses se recalcule à partir de la longueur du stroke
et du pas.

| Champ | Type | Description |
|---|---|---|
| `stroke_id` | `str` | Clé vers `strokes` |
| `step_m` | `float` | Pas demandé (`profile.step_m`) ; le pas effectif est `length_m / ceil(length_m / step_m)` |
| `z_raw` | `list<float64>` | Altitudes brutes aux points de la grille, `NaN` = *nodata* |
| `elevation_source` | `str` | Source d'altitude |

## Évolution vers PostGIS (phase 3)

- `segments` devient une table avec `geometry(LineString, 2154)`, un index GiST,
  et `id` en clé primaire. `highways`, `osm_way_ids`, `quality_flags` et
  `fits_targets_m` deviennent des tableaux PostgreSQL.
- On ajoute une colonne `region` et une date de calcul, pour les mises à jour
  incrémentales.
- L'API sert le même schéma en JSON, ou en tuiles vectorielles (MVT).
