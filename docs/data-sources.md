# Sources de données

Deux sources suffisent au prototype : **OpenStreetMap** pour le réseau et ses
attributs, et le **RGE ALTI® 1 m** de l'IGN pour l'altitude. Ce document
précise, pour chacune, les formats, le téléchargement, la projection, la
licence et les volumes.

> ⚠️ Les volumes marqués « ordre de grandeur » sont à confirmer au premier
> téléchargement, puis à mettre à jour ici.

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
« Midi-Pyrénées » :

```bash
mkdir -p data/raw
curl -L -o data/raw/midi-pyrenees-latest.osm.pbf \
  https://download.geofabrik.de/europe/france/midi-pyrenees-latest.osm.pbf
curl -L -o data/raw/midi-pyrenees-latest.osm.pbf.md5 \
  https://download.geofabrik.de/europe/france/midi-pyrenees-latest.osm.pbf.md5
(cd data/raw && md5sum -c midi-pyrenees-latest.osm.pbf.md5)
```

- **Format** : PBF (Protocol Buffers), nœuds, ways et relations.
- **Fraîcheur** : régénéré quotidiennement ; des diffs (`.osc.gz`) sont
  disponibles pour des mises à jour incrémentales (phase 3).
- **Découpe de la zone pilote** (optionnelle, mais elle accélère les
  itérations) avec [osmium-tool](https://osmcode.org/osmium-tool/) :

  ```bash
  osmium extract -b 1.48,43.48,1.80,43.59 \
    data/raw/midi-pyrenees-latest.osm.pbf -o data/raw/pilot.osm.pbf
  ```

  Sans osmium-tool, `flat-segments extract --bbox …` filtre lui-même les ways
  pendant la lecture.

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

## RGE ALTI® (IGN)

### Contenu

Modèle numérique de **terrain** (MNT) : altitude du sol nu, sans bâtiments ni
végétation.

- Pas de 1 m (il existe aussi une version à 5 m).
- Couvre la France métropolitaine et les DROM.
- Origine variable selon les zones : **LiDAR** aéroporté (précision de l'ordre
  de 20 cm), radar, ou **corrélation d'images** (précision métrique, voire
  pluri-métrique en relief marqué). Le produit fournit des couches annexes
  (masque de source, distance d'interpolation) qui permettent de savoir d'où
  vient chaque maille.

Pourquoi 1 m ([ADR 0003](adr/0003-altitude-rge-alti-1m.md)) : juger qu'un
tronçon de 200 m a moins de 2 % de pente locale demande de distinguer quelques
dizaines de centimètres de dénivelé. Un MNT à 30 m (SRTM, Copernicus GLO-30)
en est incapable : une seule maille couvre 15 % du segment.

### Formats et projection

- **Dalles** de 1 km × 1 km au format **ASCII Grid** (`.asc`), regroupées
  par **département** dans des archives `.7z`.
- Projection **Lambert-93 (EPSG:2154)** en métropole. Altitudes en **NGF-IGN69**
  (m), sans importance pour nous : seules les différences d'altitude comptent.
- Valeur *nodata* : `-99999`.

### Téléchargement

Page produit : <https://geoservices.ign.fr/rgealti>. Deux façons de faire :

1. **Référence : archive départementale** (Haute-Garonne, 31), à télécharger
   depuis la page produit, puis décompresser. On assemble ensuite un VRT GDAL
   limité aux dalles de la zone pilote :

   ```bash
   mkdir -p data/raw/rge_alti
   # après téléchargement de l'archive RGEALTI_..._D031_... dans data/raw/rge_alti
   7z x data/raw/rge_alti/RGEALTI_*D031*.7z -odata/raw/rge_alti/
   gdalbuildvrt -a_srs EPSG:2154 -te 576000 6265000 604000 6278000 \
     data/raw/rge_alti/pilot.vrt $(find data/raw/rge_alti -name '*.asc')
   ```

   L'emprise est en Lambert-93, arrondie au km, et couvre la zone pilote
   `1.48,43.48,1.80,43.59`. Elle sera recalculée par
   `elevation.bbox_to_lambert93` lors de l'implémentation.

2. **Prototype : extraction sur l'emprise** via les services de la
   [Géoplateforme](https://geoservices.ign.fr/services-geoplateforme-diffusion)
   (service raster WMS de la couche d'élévation haute résolution, en format
   brut 32 bits), en tuilant la zone par blocs de 2 km au plus.
   Nom exact de la couche et limites de requête : à confirmer lors de
   l'implémentation.

   Plus léger à télécharger, mais cela dépend d'un service en ligne et c'est
   moins reproductible.

Le pipeline ne dépend que d'un raster lisible par rasterio en Lambert-93
(`.vrt`, GeoTIFF ou COG), quelle que soit la façon dont on l'a obtenu.

### Licence

[Licence Ouverte / Open Licence 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/)
(Etalab). Réutilisation libre, y compris commerciale, sous réserve
d'attribution : « IGN – RGE ALTI® », avec la date de mise à jour de la donnée.

### Pièges

- **Ponts** : le MNT donne l'altitude du sol sous l'ouvrage.
- **Tunnels** : il donne celle du terrain au-dessus.
- **Talus** : un décalage latéral de la géométrie OSM fait lire le flanc.
- **Changements récents** (chantiers, nouvelles voies) : postérieurs au levé,
  donc absents du MNT.

Les parades sont décrites dans [`algorithm.md` § 3–5](algorithm.md#4-ponts-tunnels-et-trous).

### Alternative future : MNT LiDAR HD

L'IGN diffuse aussi, sous la même licence, un MNT dérivé du programme
**LiDAR HD** : pas de 50 cm, issu uniquement de levés LiDAR récents. S'il
couvre la zone pilote, c'est un candidat naturel pour améliorer la précision
sans changer le pipeline (même projection, même type de raster). Voir
[ADR 0003](adr/0003-altitude-rge-alti-1m.md).

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
| PBF Midi-Pyrénées | quelques centaines de Mo (ordre de grandeur) | `data/raw/` |
| PBF zone pilote (découpé) | quelques Mo | optionnel |
| RGE ALTI 1 m, département 31 | plusieurs Go compressés (ordre de grandeur) | `data/raw/rge_alti/` |
| MNT zone pilote | ≈ 28 km × 13 km ≈ 364 dalles ≈ 1,5 Go en float32 non compressé ; quelques centaines de Mo en GeoTIFF compressé | VRT : pas de copie |
| `strokes.parquet` / `profiles.parquet` (pilote) | quelques Mo à quelques dizaines de Mo | `data/interim/` |
| `segments.geojson` (pilote) | quelques Mo au plus | `web/data/` ; PMTiles au-delà de ~ 10 Mo |

Rien de tout cela n'est versionné (`/data/` est dans `.gitignore`). Seul le jeu
d'exemple fictif du front l'est.
