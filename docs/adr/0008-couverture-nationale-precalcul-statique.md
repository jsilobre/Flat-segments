# 0008 — Couverture nationale par précalcul statique

- **Statut** : Acceptée
- **Date** : 2026-10-01
- **Complète** : [ADR 0005](0005-front-statique-maplibre.md) (rôle de l'API)

## Contexte

L'objectif est de couvrir **toute la France** avec une réponse
**instantanée** en tout point. L'hébergement doit rester celui d'un POC :
gratuit ou quasi gratuit, sans serveur à maintenir.

L'ADR 0005 et `architecture.md` prévoyaient, en phase 3, une API (FastAPI +
PostGIS) qui calculerait à la demande les zones non couvertes. Les mesures
de la zone pilote (28 × 13 km, 364 km², 30/09/2026) montrent que ce calcul
ne peut pas être instantané :

| Étape | Durée sur la zone pilote |
|---|---|
| Téléchargement du MNT (WMS, 98 dalles de 2 km) | ≈ 9 min |
| Pipeline complet (strokes, profils, détection, export) | ≈ 30 s |

Même pour un rayon de 5 km, la première requête sur une zone nouvelle
prendrait plusieurs minutes. Elle dépendrait en outre des limites d'usage
de la Géoplateforme et d'Overpass.

À l'inverse, le jeu de segments tient dans un fichier statique. La zone
pilote donne 3036 segments et 2,5 Mo de GeoJSON. Extrapolé grossièrement à la
métropole (544 000 km², environ 1500 fois la zone pilote), en tenant compte
d'une densité plus faible en zone rurale, on obtient de l'ordre de 2 à 4
millions de segments, soit **1 à 2 Go en PMTiles**. Ces ordres de grandeur
sont à confirmer à l'échelle régionale.

## Décision

1. **Tout est précalculé hors ligne**, département par département : 96
   tâches indépendantes, chacune avec son extrait OSM et son MNT (LiDAR HD là
   où il existe, RGE ALTI ailleurs). Le calcul à la demande sort du chemin
   principal.
2. **Les segments sont servis en PMTiles**, tuiles vectorielles dans un
   fichier unique lu par requêtes HTTP partielles. Il n'y a ni serveur ni
   base de données, et le navigateur ne charge que les tuiles autour de la
   position.
3. **Hébergement en deux temps.**
   - La région Midi-Pyrénées tient sur GitHub Pages : 1 Go de site au plus,
     100 Mo par fichier.
   - La France entière demande un stockage d'objets compatible avec les
     requêtes partielles, de type Cloudflare R2 (10 Go gratuits, trafic
     sortant gratuit). Ce changement sera fait au moment voulu.
4. **L'API de la phase 3 devient facultative.** Elle ne sert plus qu'à ce
   que le statique ne sait pas faire :
   - couvrir l'étranger (MNT à 30 m, côtes seulement) ;
   - suivre les mises à jour OSM au fil de l'eau ;
   - appliquer des critères personnalisés au-delà des filtres du front ;
   - recueillir les retours des utilisateurs.

## Conséquences

- Réponse instantanée partout en France, pour un coût d'hébergement nul ou
  quasi nul.
- Les données ont l'âge du dernier précalcul. Une régénération mensuelle
  ou trimestrielle suffit : le réseau de chemins évolue lentement.
- Le front change de modèle : il ne charge plus un GeoJSON global. La liste
  des résultats est construite à partir des segments des tuiles chargées
  autour de la position, qui doivent porter tous leurs attributs à partir
  d'un niveau de zoom donné (environ 12).
- Le téléchargement du MNT devient le poste le plus coûteux. Il faut
  paralléliser par département, en restant dans les limites d'usage de
  l'IGN.
  - Au pas de 1 m : de l'ordre de 9 jours en séquentiel pour la métropole.
  - Au pas de 2 m, adopté depuis (amendement de
    l'[ADR 0007](0007-altitude-lidar-hd.md)) : environ 2,7 jours, et 45 min
    par département.
- Une chaîne de production par lot est nécessaire : découpage par
  département, reprise après erreur, assemblage des PMTiles.

## Alternatives considérées

- **Calcul à la demande avec cache (API + worker)** : plusieurs minutes pour
  une zone nouvelle et un serveur permanent, ce qui est incompatible avec
  l'exigence d'instantanéité et l'hébergement de POC.
- **GeoJSON découpé en cellules** (un fichier par carré de 10 km, chargé selon
  la position) : plus simple côté front, mais plus volumineux que des tuiles
  vectorielles compressées (plusieurs Go pour la France).
- **PostGIS + tuiles vectorielles dynamiques** : réponse rapide, mais un
  serveur et une base à maintenir pour des données qui changent peu.
