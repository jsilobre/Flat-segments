# Sources de données

Deux sources suffisent au prototype : **OpenStreetMap** pour le réseau et ses
attributs, et un **MNT de l'IGN** pour l'altitude : le **MNT LiDAR HD**, avec
le **RGE ALTI®** en repli ([ADR 0007](adr/0007-altitude-lidar-hd.md)). Ce document
précise, pour chacune, les formats, le téléchargement, la projection, la
licence et les volumes.

## OpenStreetMap

### Contenu utilisé

Toutes les ways `highway=*` de la zone, y compris les routes importantes, qui
servent de barrières (voir [`algorithm.md` § 1](algorithm.md#1-sélection-et-classement-des-voies)),
avec les coordonnées de leurs nœuds.

Tags lus : `highway`, `service`, `area`, `access`, `foot`, `oneway:foot`,
`surface`, `tracktype`, `lit`, `bridge`, `tunnel`, `covered`, `layer`, `name`.

### Téléchargement

Extrait régional [Geofabrik](https://download.geofabrik.de/europe/france.html).
Geofabrik découpe la France selon les régions d'avant 2016, d'où
« Midi-Pyrénées ». Une commande fait tout :

```bash
uv run flat-segments download-osm
```

1. Télécharge `midi-pyrenees-latest.osm.pbf` dans `data/raw/` et le vérifie
   avec son fichier `.md5`. Si une copie identique est déjà là, seul le
   `.md5` est retéléchargé.
2. Écrit `data/raw/pilot.osm.pbf` : les voies de l'emprise pilote et leurs
   nœuds (`osm.clip_osm`). C'est l'équivalent en Python pur de
   `osmium extract`, en deux passes, le filtrage par identifiant se faisant
   dans libosmium.

Options utiles : `--url` (autre extrait), `--bbox`, `--no-clip`, `--force`.

**Miroir.** Si Geofabrik est inaccessible, par exemple bloqué par un proxy,
OpenStreetMap France publie le même découpage régional, avec son `.md5`, mis à
jour chaque jour. C'est ce miroir qui a servi au premier passage sur la zone
pilote :

```bash
uv run flat-segments download-osm \
  --url https://download.openstreetmap.fr/extracts/europe/france/midi_pyrenees.osm.pbf
```

Attention au nom : `midi_pyrenees.osm.pbf` a un `.md5`, mais pas
`midi_pyrenees-latest.osm.pbf`.

- **Format** : PBF (Protocol Buffers), nœuds, ways et relations.
- **Fraîcheur** : régénéré quotidiennement ; des diffs (`.osc.gz`) sont
  disponibles pour des mises à jour incrémentales (phase 3).
- **Pourquoi découper** : l'extrait découpé ne pèse que quelques Mo et se relit
  en quelques secondes, ce qui accélère les itérations de calibrage.
  `flat-segments extract --bbox …` sait aussi filtrer l'extrait complet pendant
  la lecture.

### Lecture

Bibliothèque **pyosmium** ([ADR 0002](adr/0002-reseau-osm-pyosmium.md)) :
lecture en flux, filtrée sur `highway`, avec résolution des coordonnées des
nœuds. Les identifiants de nœuds sont conservés : c'est eux qui fournissent
la topologie (nœuds partagés = intersections).

### Licence

[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) :

- **Attribution** obligatoire : « © les contributeurs d'OpenStreetMap », avec un
  lien vers <https://www.openstreetmap.org/copyright>.
- **Partage à l'identique** : les segments produits sont une *base de données
  dérivée*. Diffusés publiquement (le GeoJSON du site), ils doivent l'être
  sous ODbL.
- La carte affichée est une *œuvre produite* : l'attribution suffit.

### Qualité

- Les tags `surface` et `lit` manquent souvent, d'où les valeurs `unknown`
  explicites.
- Les trottoirs sont parfois cartographiés séparément (`footway=sidewalk`),
  parfois seulement en tag sur la route (`sidewalk=both`).
- La géométrie est précise à quelques mètres près, selon les sources d'origine
  (imagerie, traces GPS).
- Tout ceci est à valider sur le terrain en phase 1.

## Altitude : MNT de l'IGN

### Contenu

Deux modèles numériques de **terrain** (MNT) : altitude du sol nu, sans
bâtiments ni végétation.

| | MNT LiDAR HD (**par défaut**) | RGE ALTI® (repli) |
|---|---|---|
| Origine | Programme LiDAR HD : levés LiDAR aéroportés récents | Mosaïque de sources : LiDAR, radar ou corrélation d'images |
| Pas d'origine | 50 cm | 1 m (et une version à 5 m) |
| Précision | décimétrique partout | de 20 cm (zones LiDAR) à métrique, voire plus en relief marqué (corrélation) |
| Couverture | France métropolitaine en cours d'achèvement ; **toute la zone pilote** est couverte | France métropolitaine et DROM |
| `elevation_source` | `lidar_hd` | `rge_alti_1m` (archive) ou `rge_alti_wms` (WMS) |

Pourquoi un MNT au mètre ([ADR 0003](adr/0003-altitude-rge-alti-1m.md),
[ADR 0007](adr/0007-altitude-lidar-hd.md)) : juger qu'un tronçon de 200 m a
moins de 2 % de pente locale demande de distinguer quelques dizaines de
centimètres de dénivelé. Un MNT à 30 m (SRTM, Copernicus GLO-30) en est
incapable : une seule maille couvre 15 % du segment.

### Formats et projection

- Projection **Lambert-93 (EPSG:2154)** en métropole. Altitudes en **NGF-IGN69**
  (m), sans importance pour nous : seules les différences d'altitude comptent.
- Dalles écrites par `download-dem` : GeoTIFF compressés, *nodata* `-99999`.
- Le service WMS marque les zones sans donnée par `-9999` (LiDAR HD) ou
  `-99999` (RGE ALTI). À la lecture, toute valeur inférieure à `-1000` devient
  *nodata*.
- Archive RGE ALTI : dalles de 1 km × 1 km (ASCII Grid `.asc` ou GeoTIFF),
  regroupées par **département** dans des archives `.7z`.

### Téléchargement

1. **Automatique : extraction sur l'emprise par WMS**, méthode retenue pour le
   prototype :

   ```bash
   uv run flat-segments download-dem
   ```

   La commande découpe l'emprise (convertie en Lambert-93, arrondie au km) en
   dalles de 2 km au plus. Pour chacune, elle demande l'image d'altitude au
   service WMS raster de la
   [Géoplateforme](https://geoservices.ign.fr/services-geoplateforme-diffusion).
   Réglages vérifiés avec `GetCapabilities` le 30/09/2026 :

   | Réglage | Valeur |
   |---|---|
   | Point d'accès | `https://data.geopf.fr/wms-r/wms` |
   | Couche (défaut) | `IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93`, stockée en Lambert-93 |
   | Format | `image/x-bil;bits=32` : flottants 32 bits bruts, **petit-boutiste** (*little-endian*) |
   | Version | WMS 1.3.0, `CRS=EPSG:2154`, `STYLES` vide (style `normal` : valeurs brutes) |
   | Taille max d'une image | 5010 × 5010 pixels (`MaxWidth`, `MaxHeight`) |
   | Taille d'une dalle | 2000 × 2000 pixels au pas de 1 m, soit 16 Mo par requête |

   Chaque dalle est enregistrée en GeoTIFF compressé dans
   `data/raw/dem/tiles/`. Les dalles sont ensuite assemblées dans la mosaïque
   virtuelle `data/raw/dem/pilot.vrt`, dont les chemins sont relatifs.

   - **Reprise** : on peut relancer la commande après une interruption. Les
     dalles déjà présentes sont gardées si elles viennent de la même couche,
     sinon elles sont retéléchargées.
   - **Source** : les dalles et le VRT portent la métadonnée
     `ELEVATION_SOURCE` (`lidar_hd`, `rge_alti_wms`). L'étape `elevation` la
     relit, et `--source` permet de la forcer.
   - **Fiabilité** : le service coupe parfois la connexion ou répond
     `400 LayerNotDefined` pour une couche qui existe. Chaque dalle est
     retentée jusqu'à six fois.
   - **Autre couche** : `--layer`, `--wms-url`, `--tile-size-m` et
     `--resolution-m`.

   > ⚠️ La couche RGE ALTI du même service
   > (`--layer ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES`) est stockée en
   > coordonnées géographiques et rééchantillonnée par le serveur. Sa résolution
   > effective en Lambert-93 n'est que d'environ **3,5 m × 4,7 m**, en marches
   > d'escalier. Voir [ADR 0007](adr/0007-altitude-lidar-hd.md).

   C'est léger à télécharger, mais cela dépend d'un service en ligne et c'est
   moins reproductible qu'une archive.

2. **Repli manuel : archive RGE ALTI 1 m départementale**, là où le LiDAR HD
   manque. Pour la Haute-Garonne (31), l'édition du 26/11/2024 est listée sur
   `https://data.geopf.fr/telechargement/resource/RGEALTI?zone=D031`. Elle pèse
   6,8 Go en deux volumes `.7z` (GeoTIFF). On la décompresse, puis on assemble
   un VRT GDAL limité aux dalles de la zone pilote :

   ```bash
   mkdir -p data/raw/dem
   # après téléchargement de l'archive RGEALTI_..._D031_... dans data/raw/dem
   7z x data/raw/dem/RGEALTI_*D031*.7z.001 -odata/raw/dem/
   gdalbuildvrt -a_srs EPSG:2154 -te 576000 6265000 604000 6278000 \
     data/raw/dem/pilot.vrt $(find data/raw/dem -name '*.asc' -o -name '*.tif')
   ```

   L'emprise est en Lambert-93, arrondie au km, et couvre la zone pilote
   `1.48,43.48,1.80,43.59`. C'est ce que calcule `elevation.bbox_to_lambert93`.
   Un VRT sans métadonnée `ELEVATION_SOURCE` est considéré comme
   `rge_alti_1m`.

Le pipeline ne dépend que d'un raster lisible par rasterio en Lambert-93
(`.vrt`, GeoTIFF ou COG), quelle que soit la façon dont on l'a obtenu.

### Licence

[Licence Ouverte / Open Licence 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/)
(Etalab), pour les deux produits. Réutilisation libre, y compris commerciale,
sous réserve d'attribution : « IGN – MNT LiDAR HD » ou « IGN – RGE ALTI® ».
L'export GeoJSON choisit la mention selon la source réellement utilisée.

### Pièges

- **Ponts** : le MNT donne l'altitude du sol sous l'ouvrage.
- **Tunnels** : il donne celle du terrain au-dessus.
- **Talus** : un décalage latéral de la géométrie OSM fait lire le flanc.
- **Changements récents** (chantiers, nouvelles voies) : postérieurs au levé,
  donc absents du MNT.

Les parades sont décrites dans [`algorithm.md` § 3–5](algorithm.md#4-ponts-tunnels-et-trous).

## Repli hors de France : MNT 30 m

Hors de France (phase 3), on peut se replier sur **Copernicus GLO-30** ou
**SRTM** (30 m). Ces deux produits sont des modèles de **surface** (MNS),
qui incluent arbres et bâtiments.

- Ils suffisent à repérer des **côtes** de plusieurs centaines de mètres.
- Ils sont **inutilisables pour les plats courts**.
- Les segments issus d'un tel MNT porteraient `elevation_source = "copernicus_glo30"`
  et un flag `dem_coarse`.

## Projections

| Système | Code | Unités | Utilisation |
|---|---|---|---|
| WGS84 | EPSG:4326 | degrés (lon, lat) | OSM, GeoJSON (imposé par la RFC 7946), front |
| Lambert-93 (RGF93) | EPSG:2154 | mètres | RGE ALTI, **tous les calculs du pipeline**, GeoParquet interne |
| UTM (zone locale) | ex. EPSG:32631 | mètres | calculs hors de France (phase 3) |

- Le pipeline reprojette les nœuds OSM en Lambert-93 dès la lecture
  (`pyproj`, `always_xy=True` : ordre lon, lat). Longueurs, pentes, distances
  et tampons sont ainsi en mètres, sans calcul géodésique.
- L'altération linéaire du Lambert-93 est de l'ordre du millimètre par mètre en
  métropole, négligeable pour des tronçons de quelques centaines de mètres.
- L'export GeoJSON repasse en WGS84, avec des coordonnées arrondies à 6
  décimales (environ 10 cm).
- Le front calcule les distances à l'utilisateur par la formule de haversine,
  directement en WGS84.

## Volumes

| Donnée | Volume | Remarque |
|---|---|---|
| PBF Midi-Pyrénées | 412 Mo (extrait du 29/09/2026) ; environ 10 min de téléchargement | `data/raw/` |
| PBF zone pilote (découpé) | 1,5 Mo : 13 934 voies `highway=*`, 93 764 nœuds | `data/raw/pilot.osm.pbf` |
| Archive RGE ALTI 1 m, département 31 | 6,8 Go (GeoTIFF, deux volumes `.7z`) | repli manuel, `data/raw/dem/` |
| MNT LiDAR HD zone pilote | 28 km × 13 km : 98 dalles WMS de 2 km, 1,5 Go transférés (float32), **681 Mo** en GeoTIFF compressé ; environ 9 min de téléchargement | `data/raw/dem/` ; le VRT ne recopie rien |
| RGE ALTI par WMS, zone pilote | 109 Mo en GeoTIFF compressé (valeurs en marches d'escalier, très compressibles) | comparaison seulement |
| `strokes.parquet` / `profiles.parquet` (pilote) | 2,5 Mo / 3,1 Mo : 9145 strokes, 1616 km de voies | `data/interim/` |
| `segments.geojson` (pilote) | 2,5 Mo pour environ 3000 segments | `web/data/` ; PMTiles au-delà de ~ 10 Mo |

Rien de tout cela n'est versionné (`/data/` est dans `.gitignore`). Seul le jeu
d'exemple fictif du front l'est.
