# 0009 — Tuiles vectorielles PMTiles produites avec tippecanoe

- **Statut** : Acceptée
- **Date** : 2026-10-01

## Contexte

L'[ADR 0008](0008-couverture-nationale-precalcul-statique.md) prévoit de servir
les segments en PMTiles. Il faut choisir l'outil qui produit les tuiles. Il
doit :

- garder **tous les segments et tous leurs attributs** aux zooms de travail du
  front, à partir de 12. La liste des résultats et les filtres en dépendent ;
- alléger les tuiles de faible zoom à l'échelle nationale (millions de
  segments), si l'on veut une vue d'ensemble ;
- fusionner des archives produites séparément, une par département ;
- s'installer simplement en local et sur les runners GitHub Actions.

Candidats essayés sur le jeu publié de la zone pilote (3036 segments, GeoJSON
de 2,45 Mo, 0,46 Mo en gzip), le 01/10/2026 :

| | GDAL 3.12 (pyogrio, déjà installé) | tippecanoe 2.49 (apt) |
|---|---|---|
| Taille, zooms 12–14 | 1,28 Mo | **1,14 Mo** |
| Taille, zooms 6–14 sans allègement | 2,70 Mo | 2,37 Mo |
| Durée | 1,3 s | **0,3 s** |
| Segments et attributs à z12–14 | tous (listes en chaînes JSON) | tous (listes en chaînes JSON) |
| Écart géométrique à z14 (Hausdorff, max) | 0,3 m | 0,7 m |
| Tuile z12 la plus lourde (gzip) | 86 Ko | 72 Ko |
| Allègement des faibles zooms | plafond de taille global (`MAX_SIZE`), appliqué à tous les zooms | options dédiées (`--drop-densest-as-needed`…) |
| Fusion d'archives | non | `tile-join` |

Un plafond de 40 Ko par tuile fait perdre des segments **aussi au zoom 12**,
avec les deux outils. Le détail doit donc être produit sans plafond, et la
vue d'ensemble à part.

Planetiler (Java) n'a pas été retenu. Il est conçu pour des fonds de carte
OSM complets, et il faudrait écrire un profil Java pour un simple jeu de
lignes.

## Décision

- Les PMTiles sont produits par **tippecanoe**, appelé par le pipeline comme
  outil externe. Il faut la version **2.55 ou plus**.
  - Le paquet Ubuntu (2.49) mélange les attributs de certains objets sur les
    gros jeux : collisions de hachage dans sa table de chaînes, corrigées en
    2.55. Constaté sur l'ex-Midi-Pyrénées (amendement du 02/10/2026, voir
    [étape 2.4](../phase-2/2.4-production.md)).
  - L'export refuse une version plus ancienne.
  - La CI et la production compilent tippecanoe 2.79.0 depuis les sources
    (action `.github/actions/tippecanoe`, mise en cache). En local :
    `brew install tippecanoe`, ou compilation depuis les sources.
- **Contrôle** : après l'écriture, l'export relit la couche `segments` au
  zoom 12 avec GDAL et la compare aux segments donnés (identifiants et toutes
  les propriétés). Il échoue au moindre écart, avant toute publication. Cela
  prend environ 30 s pour 350 000 segments.
- Couche `segments` :
  - zooms **12 à 14 sans perte** (`--no-feature-limit --no-tile-size-limit`) ;
  - au-delà de 14, MapLibre agrandit les tuiles de z14.
- Les listes (`highways`, `osm_way_ids`, `quality_flags`, `fits_targets_m`)
  deviennent des chaînes JSON, que le front décode.
- Les identifiants de segment restent dans la propriété `id`, car le MVT
  n'accepte que des identifiants numériques. Le front s'en sert via l'option
  `promoteId` de MapLibre.
- Une vue d'ensemble (couche `overview`, zooms 8 à 11, `id`, `kind` et
  `length_m` seulement, allégée par tippecanoe) est produite à part et
  fusionnée avec `tile-join` ([étape 2.2](../phase-2/2.2-tuiles.md)). Pour la
  Haute-Garonne, elle ajoute environ 5 Mo aux 16,8 Mo du détail.
- Les archives départementales sont fusionnées avec `tile-join`.
- **GDAL** (via pyogrio, sans dépendance de plus) reste un repli pour un
  export ponctuel, sans allègement ni fusion.

## Conséquences

- Les tuiles du zoom 12 sont complètes et légères. Une recherche dans un rayon
  de 5 km charge 4 à 9 tuiles, moins de 0,5 Mo dans la zone la plus dense du
  pilote.
- Une dépendance système (non Python) s'ajoute pour l'étape d'export en
  PMTiles. Le reste du pipeline et ses tests n'en dépendent pas : les tests de
  cette étape sont sautés si tippecanoe est absent, et la CI l'installe
  ([étape 2.2](../phase-2/2.2-tuiles.md)).
- **Ordre de grandeur des volumes**. L'estimation initiale, extrapolée de la
  zone pilote, était d'environ 150 Mo pour l'ex-Midi-Pyrénées et de 1 à
  2 Go pour la métropole. Elle a été recalée sur la Haute-Garonne complète
  ([étape 2.1](../phase-2/2.1-departement.md)), qui donne 16,8 Mo.
  - On attend 60 à 110 Mo pour l'ex-Midi-Pyrénées et au plus 1,4 Go pour la
    métropole.
  - C'est proche de la limite de 100 Mo par fichier de GitHub : il faudra
    peut-être un fichier par département, ou une publication hors du dépôt
    Git. C'est la seconde solution qui a été retenue
    ([ADR 0011](0011-production-github-actions.md)).
- **GitHub Pages** (vérifié au premier déploiement, [étape 2.2](../phase-2/2.2-tuiles.md)) :
  il compresse le `.pmtiles` si le client envoie `Accept-Encoding: gzip`,
  mais les navigateurs ne l'envoient pas sur les requêtes partielles. Le site
  fonctionne dans Chromium et Firefox. Le constat initial suit.
- **GitHub Pages** répond aux requêtes partielles (`206`, `Accept-Ranges`,
  CORS ouvert). Mais il compresse en gzip les types texte, et la plage porte
  alors sur les octets compressés, ce qui casserait la lecture.
  - Un `.pmtiles` est servi comme binaire et ne devrait pas être compressé.
  - C'est à confirmer au premier déploiement (étape 2.3).

## Alternatives considérées

- **GDAL seul** : aucune dépendance de plus, géométrie un peu plus fidèle,
  mais pas d'allègement par zoom ni de fusion d'archives. Indispensable à
  l'échelle nationale.
- **Planetiler** : voir plus haut.
- **GeoJSON découpé en cellules** : voir l'ADR 0008.
