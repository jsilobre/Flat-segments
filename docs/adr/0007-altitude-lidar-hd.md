# 0007 — Altitude : MNT LiDAR HD de l'IGN, RGE ALTI® en repli

- **Statut** : Acceptée
- **Date** : 2026-09-30
- **Remplace** : [ADR 0003](0003-altitude-rge-alti-1m.md)

## Contexte

L'[ADR 0003](0003-altitude-rge-alti-1m.md) retenait le RGE ALTI® 1 m, obtenu
par le service WMS raster de la Géoplateforme (couche
`ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES`). Au premier téléchargement réel
(30/09/2026), `GetCapabilities` et une dalle test de 200 m × 200 m à Labège
ont montré que cette couche ne fournit pas du 1 m :

- elle est stockée en coordonnées géographiques (`IGNF:WGS84G`), et le
  serveur la rééchantillonne quand on la demande en Lambert-93 ;
- 71 à 79 % des pixels voisins ont exactement la même valeur, même en
  demandant 0,5 m : la résolution effective est d'environ **3,5 m × 4,7 m**,
  en marches d'escalier ;
- par rapport au MNT LiDAR HD sur la même dalle, l'écart a un écart-type de
  0,79 m et atteint 2,5 m au 99ᵉ centile. C'est l'ordre de grandeur de ce
  qu'on mesure : 2 % de pente sur 20 m font 0,4 m.

Le même service propose la couche
`IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93` : le MNT issu du
programme LiDAR HD, stocké **nativement en Lambert-93** (pas de 50 cm), sous la
même Licence Ouverte 2.0. Elle couvre toute la zone pilote : 98 points de
sondage sur 98, un par dalle de 2 km.

## Décision

- Source d'altitude par défaut : **MNT LiDAR HD de l'IGN**, extrait par
  `download-dem` sur l'emprise, au pas de 2 m depuis le 01/10/2026 (voir
  l'amendement en fin de document ; 1 m auparavant), via la couche WMS
  `IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93`).
  Les segments portent `elevation_source = "lidar_hd"`.
- **Repli** : le RGE ALTI®, là où le LiDAR HD ne couvre pas encore le
  territoire.
  - Soit par le WMS (`--layer ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES`,
    `elevation_source = "rge_alti_wms"`), en sachant que sa résolution
    effective est d'environ 4 m.
  - Soit, de préférence, par l'archive départementale au pas de 1 m
    (`rge_alti_1m`).
- La source est inscrite dans les métadonnées des dalles et du VRT
  (`ELEVATION_SOURCE`). L'étape `elevation` la relit, et l'export en déduit
  l'attribution affichée.
- Le reste de l'ADR 0003 est inchangé : échantillonnage bilinéaire tous les
  5 m, lissage, interpolation sous les ponts et tunnels, et repli à 30 m hors
  de France.

## Conséquences

- **Effet mesuré sur la zone pilote** (paramètres par défaut, 30/09/2026). Le
  même réseau a été traité avec les deux MNT :

  | | Plats | Côtes |
  |---|---|---|
  | MNT LiDAR HD | 790 (331 km) | 2302 (504 km) |
  | RGE ALTI par WMS | 762 (321 km) | 2335 (506 km) |
  | km LiDAR HD retrouvés avec le RGE ALTI (à 10 m près) | 92 % | 97 % |

  Le lissage (σ = 10 m) et le pas de 5 m absorbent l'essentiel de la
  résolution grossière du RGE ALTI : l'écart porte sur 5 à 8 % des plats.
  Les 81 plats du LiDAR HD que le RGE ALTI manque en majorité sont plus courts
  (médiane 230 m contre 317 m) et plus proches des seuils : leur pente moyenne
  médiane, en valeur absolue, vaut 0,45 % contre 0,25 %.
- Profils plus précis et homogènes : la précision du LiDAR HD est décimétrique
  partout, alors que le RGE ALTI mêle LiDAR, radar et corrélation d'images.
- Même projection et même type de raster : aucun changement dans le pipeline
  en aval de `download-dem`.
- La couverture LiDAR HD de la France n'est pas encore complète. Pour une
  nouvelle zone, il faut la vérifier (valeur *nodata* `-9999` hors
  couverture) et passer au RGE ALTI si besoin.
  - Au 03/10/2026, le LiDAR HD manque sur 7,5 % de la métropole ; 23
    départements en ont plus de 1 % sans ([étape 2.5](../phase-2/2.5-france.md#couverture-du-mnt-lidar-hd)).
  - La production par département applique le repli depuis le 03/10/2026
    (amendement ci-dessous). Avant, ces zones n'avaient aucun segment.
- Une dépendance au service WMS demeure : on télécharge un extrait
  rééchantillonné au mètre, pas le produit d'origine à 50 cm.

## Alternatives considérées

- **RGE ALTI par WMS** (ADR 0003) : résolution effective d'environ 4 m,
  insuffisante pour les plats courts.
- **Archive RGE ALTI 1 m du département 31** (`data.geopf.fr/telechargement`,
  édition du 26/11/2024) : vrai pas de 1 m et reproductible, mais 6,8 Go en
  deux volumes `.7z` pour une zone pilote de 28 km × 13 km. Il faudrait aussi
  un outil de décompression. Cette solution reste le repli manuel documenté
  dans [`data-sources.md`](../data-sources.md).
- **Dalles LiDAR HD d'origine (50 cm)** : plus fines que nécessaire, avec un
  pas d'échantillonnage de 5 m et un lissage de 10 m. Volume quatre fois
  plus gros.

## Amendement du 01/10/2026 : extraction au pas de 2 m

Mesures de l'étape 2.0 de la phase 2 ([rapport](../phase-2/2.0-mesures.md)) :
au pas de 2 m, en dalles de 4 km (2000 × 2000 px, 16 Mo par requête),

- 98 % des km de plats et 99 % des km de côtes du 1 m sont retrouvés à 10 m
  près. Les segments perdus sont des cas limites, courts et proches des
  seuils ;
- les 20 segments de la fiche terrain sont tous retrouvés, et leur pente
  varie de 0,25 point au plus ;
- le téléchargement de la zone pilote passe de 9 min 03 s à 2 min 36 s, et
  son volume de 681 à 182 Mo.

`download-dem` extrait donc désormais le MNT au **pas de 2 m, en dalles de
4 km**. L'échantillonnage bilinéaire tous les 5 m et le lissage (σ = 10 m)
restent inchangés : ils lissent de toute façon sous l'échelle de 2 m.
L'option `--resolution-m 1 --tile-size-m 2000` redonne l'ancien réglage.

## Amendement du 03/10/2026 : repli automatique dans la production

La France publiée le 03/10/2026 n'avait aucun segment là où le LiDAR HD
manque : 7,5 % de la métropole, dont Lille
([étape 2.5](../phase-2/2.5-france.md#couverture-du-mnt-lidar-hd)). La
production par département applique désormais le repli de cet ADR.

- **Dalles** : celles du LiDAR HD qui ont des valeurs *nodata* sont aussi
  téléchargées en RGE ALTI par le WMS, dans un second VRT.
- **Strokes** : un stroke dont le profil garde des trous impossibles à
  combler (hors ponts et tunnels, plus longs que 20 m) est relu dans le
  RGE ALTI. Ce second profil remplace le premier en entier s'il en laisse
  moins.
  - Un segment n'a donc qu'une source, `lidar_hd` ou `rge_alti_wms`.
  - L'attribution du jeu publié cite les deux.
- **Qualité** : celle mesurée plus haut sur la zone pilote. Le RGE ALTI
  retrouve 92 % des km de plats et 97 % des km de côtes du LiDAR HD ; les
  plats manqués sont courts et proches des seuils. Le front ne distingue pas
  ces segments.
- **Évolution** : quand l'IGN publie le LiDAR HD d'une zone, la régénération
  suivante l'utilise. Le rapprochement à 10 m
  ([ADR 0012](0012-identifiants-stables.md)) garde alors les identifiants des
  segments peu déplacés.
