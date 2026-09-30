# flat-segments

**Trouver, près de chez soi, les bouts de chemin parfaits pour une séance de course.**

`flat-segments` repère des tronçons courts exploitables pour l'entraînement
autour d'une position GPS (saisie à la main ou fournie par l'appareil) :

1. **Segments plats et courts** pour le fractionné et le travail d'allure :
   longueurs cibles 200 m, 400 m et 1 km (paramétrables), pente maximale faible.
2. **Côtes** pour le travail en montée : longueur et pente moyenne cibles.

Contrairement à Strava ou Komoot, on ne cherche ni parcours ni boucles, mais des
**tronçons** : une ligne droite plate de 400 m sans traversée de route, ou une
montée régulière à 6 % sur 200 m.

## Ce qui fait un bon segment

| Critère | Plat | Côte |
|---|---|---|
| Longueur | ≥ longueur cible (200 / 400 / 1000 m) | ≥ longueur cible (100 à 800 m) |
| Pente | pente locale max faible (2 %), pente moyenne ≤ 1 % | pente moyenne dans une plage (3 à 15 %), sans replat |
| Traversées | aucune route importante, peu de routes secondaires | idem |
| Tracé | droit ou peu sinueux | sinuosité tolérée plus forte (lacets) |
| Revêtement / éclairage | asphalte, stabilisé, terre… ; éclairage si connu | idem |
| Accès | praticable en aller-retour (pas d'accès privé, pas de sens unique piéton) | idem |
| Proximité | distance à la position de l'utilisateur | idem |

Le détail des calculs est dans [`docs/algorithm.md`](docs/algorithm.md).

## Statut

🚧 **Phase 0 : documents d'architecture et squelette de code.**

- La logique pure (géométrie, chaînage du réseau, profils d'altitude, fenêtre
  glissante, déduplication, score) est implémentée et testée sur des données
  synthétiques.
- Les entrées/sorties (lecture OSM avec pyosmium, lecture raster avec rasterio,
  GeoParquet, GeoJSON) sont implémentées. Elles sont testées sur de petits
  fichiers synthétiques, mais pas encore sur les vraies données.
- Le téléchargement des données n'est pas automatisé : c'est un *stub*
  documenté (voir [`docs/data-sources.md`](docs/data-sources.md)).
- Le front `web/` fonctionne sur un jeu de segments **fictifs**, produit par le
  vrai pipeline à partir d'un réseau synthétique autour de Labège.

Zone pilote : **Labège / Caraman** (sud-est de Toulouse, Haute-Garonne),
emprise `1.48,43.48,1.80,43.59` (lon/lat WGS84).

## Démarrage rapide

Prérequis : [uv](https://docs.astral.sh/uv/) (installe Python ≥ 3.12 si besoin)
et, pour les tests du front, Node.js ≥ 20.

```bash
# Environnement et outils de développement
uv sync
uv run pre-commit install

# Qualité
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest

# CLI du pipeline
uv run flat-segments --help
```

### Pipeline (cible)

Les données brutes vont dans `data/` (ignoré par Git).
Voir [`docs/data-sources.md`](docs/data-sources.md) pour les téléchargements.

```bash
uv run flat-segments extract   --pbf data/raw/midi-pyrenees-latest.osm.pbf  # → data/interim/strokes.parquet
uv run flat-segments elevation --dem data/raw/rge_alti/pilot.vrt             # → data/interim/profiles.parquet
uv run flat-segments detect                                                  # → data/processed/segments.parquet
uv run flat-segments export                                                  # → web/data/segments.geojson
```

### Front

Site statique, sans étape de build :

```bash
python -m http.server --directory web 8000
# puis ouvrir http://localhost:8000
```

La page charge `web/data/segments.geojson` s'il existe, sinon le jeu d'exemple
`web/data/sample-segments.geojson` (données fictives, signalées par un bandeau).

Régénérer le jeu d'exemple : `uv run python scripts/make_sample_data.py`.

Tests du filtrage côté navigateur : `cd web && node --test`.

## Organisation du dépôt

```
docs/                 documentation (architecture, algorithme, données, ADR)
src/flat_segments/    pipeline Python (package)
tests/                tests pytest (profils et réseaux synthétiques)
scripts/              scripts utilitaires (jeu d'exemple)
web/                  front statique MapLibre
data/                 données téléchargées et produites (non versionné)
```

## Documentation

- [Architecture](docs/architecture.md) : composants, flux de données, phases
- [Algorithme](docs/algorithm.md) : détection des plats et des côtes, paramètres
- [Sources de données](docs/data-sources.md) : OSM, RGE ALTI, projections, licences
- [Modèle de données](docs/data-model.md) : schéma d'un segment
- [Décisions d'architecture (ADR)](docs/adr/README.md)

## Licences et attributions

- **Code** : licence MIT, voir [`LICENSE`](LICENSE).
- **Segments produits** : ils sont dérivés d'OpenStreetMap et constituent une
  base de données dérivée, diffusée sous
  [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
  © les contributeurs d'OpenStreetMap.
- **Altitudes** : IGN – RGE ALTI®, [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/).
- **Fond de carte** : [OpenFreeMap](https://openfreemap.org/), données © OpenStreetMap.

Ces mentions sont aussi affichées sur la carte du site.
