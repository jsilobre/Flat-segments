# 0003 — Altitude : RGE ALTI® 1 m de l'IGN

- **Statut** : Acceptée
- **Date** : 2026-09-30

## Contexte

Juger qu'un tronçon de 200 m est « plat » (pente locale ≤ 2 %) demande de
distinguer des dénivelés de quelques dizaines de centimètres. Les MNT
mondiaux à 30 m (SRTM, Copernicus GLO-30) sont trop grossiers pour cela : une
maille couvre 15 % du segment. Ce sont en outre des modèles de surface
(arbres, bâtiments inclus).

## Décision

- Source d'altitude : **RGE ALTI® 1 m** de l'IGN (MNT, Lambert-93, Licence
  Ouverte 2.0), lu par rasterio à travers un VRT ou un GeoTIFF couvrant la zone.
- Échantillonnage **bilinéaire** tous les 5 m le long des strokes, puis lissage
  (médiane + gaussienne).
- Ponts et tunnels (tags OSM `bridge`, `tunnel`, `covered`) : altitude
  **interpolée** entre les extrémités de l'ouvrage.
- Hors de France (phase 3) : repli sur un MNT 30 m, limité aux côtes et
  signalé par le flag `dem_coarse`.

## Conséquences

- La précision est suffisante pour les plats là où le RGE ALTI vient du LiDAR ;
  elle est moindre dans les zones issues de corrélation d'images. Il faudra
  connaître la source par zone (masque de source) et la valider sur le
  terrain en phase 1.
- Volumes importants : plusieurs Go par département. On ne télécharge que ce
  qui est nécessaire et rien n'est versionné.
- Le pipeline n'accepte que des rasters en Lambert-93. Un autre MNT français
  s'y branche sans modification.

## Alternatives considérées

- **SRTM / Copernicus GLO-30** : couverture mondiale, mais trop grossiers.
  Gardés comme repli.
- **MNT LiDAR HD de l'IGN** (50 cm, même licence) : plus précis et homogène.
  Couverture de la zone pilote à vérifier. C'est l'évolution naturelle : même
  projection et même type de raster, donc un simple changement de source
  (`elevation_source = "lidar_hd"`).
- **Altitude des traces GPS (Strava…)** : non libre, biais barométriques.
