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

🚧 **Phase 1 : prototype sur la zone pilote.**

Déjà en place :
- **Pipeline complet**, testé sur des données synthétiques puis lancé sur la
  zone pilote :
  - lecture OSM avec pyosmium et découpe de l'extrait ;
  - échantillonnage du MNT avec rasterio ;
  - détection, score et déduplication ;
  - export GeoParquet et GeoJSON.
- **Téléchargements automatisés** : extrait OSM (Geofabrik ou miroir) et dalles
  du MNT LiDAR HD via la Géoplateforme.
- **Outils de calibrage** : rapport, balayage de paramètres, profil d'un segment,
  fiche de validation terrain.
- **Front statique** :
  - liens directs vers un segment ;
  - déploiement GitHub Pages par workflow.
- **Segments réels de la zone pilote** (`web/data/segments.geojson`, 2,5 Mo) :
  - 767 plats (323 km) et 2269 côtes (497 km) ;
  - tirés de l'extrait OSM du 29/09/2026 et du MNT LiDAR HD de l'IGN ;
  - seuils calibrés sur ces données
    ([`algorithm.md` § 11](docs/algorithm.md#11-déduplication-inter-strokes)).

Reste à faire : la validation terrain, avec la fiche
[`docs/validation/pilot.md`](docs/validation/pilot.md) (20 segments).

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

### Pipeline

Les données brutes et intermédiaires vont dans `data/` (ignoré par Git). Voir
[`docs/data-sources.md`](docs/data-sources.md) pour le détail des sources.

```bash
uv run flat-segments download-osm   # extrait Geofabrik (MD5) + découpe → data/raw/pilot.osm.pbf
uv run flat-segments download-dem   # dalles MNT LiDAR HD de l'emprise → data/raw/dem/pilot.vrt
uv run flat-segments pipeline       # extract + elevation + detect + export → web/data/segments.geojson
```

Si Geofabrik est inaccessible, `download-osm --url` accepte le miroir
d'OpenStreetMap France (voir [`docs/data-sources.md`](docs/data-sources.md#téléchargement)).

Chaque étape existe aussi séparément : `extract`, `elevation`, `detect` et
`export`. Toutes acceptent un fichier de paramètres et des surcharges ponctuelles :

```bash
uv run flat-segments config > mes-parametres.toml          # paramètres effectifs (TOML)
uv run flat-segments detect --config mes-parametres.toml --set flat.max_local_grade_pct=1.5
```

Les valeurs par défaut sont dans [`configs/default.toml`](configs/default.toml).
Elles sont documentées dans [`docs/algorithm.md`](docs/algorithm.md#13-récapitulatif-des-paramètres).

### Calibrage

```bash
uv run flat-segments report                                   # résumé des segments détectés
uv run flat-segments sweep flat.max_local_grade_pct 1 1.5 2   # sensibilité à un paramètre
uv run flat-segments inspect flat-3fa2b1c9d0e4                # profil d'un segment (PNG, matplotlib)
uv run flat-segments validation-sheet --count 20              # fiche terrain → docs/validation/pilot.md
```

`inspect` utilise matplotlib : il est installé par `uv sync` (outils de
développement) ou avec l'extra `viz` (`uv sync --extra viz`).

### Front

Site statique, sans étape de build :

```bash
python -m http.server --directory web 8000
# puis ouvrir http://localhost:8000
```

La page charge `web/data/segments.geojson` s'il existe, sinon le jeu d'exemple
`web/data/sample-segments.geojson` (données fictives, signalées par un bandeau).

Liens directs : `?id=<segment>` ouvre un segment, `?lat=…&lon=…` fixe la
position et `?kind=climb` affiche les côtes. Le workflow *Pages* publie `web/` à
chaque modification sur `main`. Il faut d'abord activer GitHub Pages dans
*Settings → Pages → Source : GitHub Actions*.

Régénérer le jeu d'exemple : `uv run python scripts/make_sample_data.py`.

Tests du filtrage côté navigateur : `cd web && node --test`.

## Organisation du dépôt

```
docs/                 documentation (architecture, algorithme, données, ADR, validation)
configs/              paramètres par défaut (TOML)
src/flat_segments/    pipeline Python (package)
tests/                tests pytest (profils et réseaux synthétiques)
scripts/              scripts utilitaires (jeu d'exemple)
web/                  front statique MapLibre
data/                 données téléchargées et produites (non versionné)
```

## Documentation

- [Architecture](docs/architecture.md) : composants, flux de données, phases
- [Algorithme](docs/algorithm.md) : détection des plats et des côtes, paramètres
- [Sources de données](docs/data-sources.md) : OSM, MNT LiDAR HD et RGE ALTI, projections, licences
- [Modèle de données](docs/data-model.md) : schéma d'un segment
- [Décisions d'architecture (ADR)](docs/adr/README.md)

## Licences et attributions

- **Code** : licence MIT, voir [`LICENSE`](LICENSE).
- **Segments produits** : ils sont dérivés d'OpenStreetMap et constituent une
  base de données dérivée, diffusée sous
  [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
  © les contributeurs d'OpenStreetMap.
- **Altitudes** : IGN – MNT LiDAR HD (RGE ALTI® en repli), [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/).
- **Fond de carte** : [OpenFreeMap](https://openfreemap.org/), données © OpenStreetMap.

Ces mentions sont aussi affichées sur la carte du site.
