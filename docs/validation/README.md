# Validation terrain

La phase 1 se termine par une vérification sur place d'un échantillon de
segments de la zone pilote. Le but est de savoir si les segments annoncés
plats le sont vraiment, si les côtes ont la pente annoncée, et si les
traversées, les accès et les revêtements sont justes.

## Déroulé

1. Après un passage du pipeline sur les vraies données, générer la fiche :

   ```bash
   uv run flat-segments validation-sheet --count 20   # → docs/validation/pilot.md
   ```

   L'échantillon est déterministe et représentatif. Plats et côtes s'y
   partagent les places à parts égales. Un partage proportionnel ne laissait
   que 5 plats sur 20 dans la zone pilote, où les côtes sont trois fois plus
   nombreuses. Il contient au moins un segment
   avec *flag* de qualité (pont, trou du MNT…) et un avec traversée, quand il
   y en a. Le reste est réparti sur toute la plage de scores, pour voir aussi
   les segments moyens et faibles.
2. Pour chaque ligne, ouvrir le lien **Carte** (lien direct vers le segment sur
   le site), aller sur place et remplir la colonne **Verdict** avec un code :

   | Code | Signification |
   |---|---|
   | `OK` | Conforme à la description |
   | `PENTE` | La pente ne correspond pas (pas plat, côte trop ou pas assez raide) |
   | `TRAVERSEE` | Traversée ou intersection non signalée, ou signalée à tort |
   | `ACCES` | Inaccessible : privé, fermé ou dangereux |
   | `SURFACE` | Revêtement ou éclairage faux |
   | `GEOMETRIE` | Tracé faux, ou segment coupé au mauvais endroit |
   | `DOUBLON` | Doublon d'un autre segment |
   | `AUTRE` | Autre problème (préciser en remarque) |

3. Commiter la fiche remplie. Les verdicts servent à ajuster les seuils
   (`flat-segments sweep`, `inspect`). Toute déviation de l'algorithme est
   reportée dans [`../algorithm.md`](../algorithm.md) et, si besoin, dans un ADR.

Critère de passage à la phase 2 (voir [`../architecture.md`](../architecture.md#5-phases)) :
précision jugée suffisante sur l'échantillon.

## Campagne 1 — zone pilote (octobre 2026)

Fiche : [`pilot.md`](pilot.md), 20 segments (10 plats, 10 côtes) tirés du jeu
publié le 30/09/2026.

| | Vérifiés | `OK` | Problèmes |
|---|---|---|---|
| Plats | 10 | 8 | 1 `ACCES`, 1 `DOUBLON` |
| Côtes | 8 | 7 | 1 `ACCES` |
| **Total** | **18** | **15 (83 %)** | 3 |

Deux côtes n'ont pas pu être vérifiées, car leur lien direct ne s'ouvrait
pas (« lien KO »). La cause était un bug du front, corrigé depuis : le lien
appliquait les filtres de la page, et ces côtes passaient juste en dessous
(pente moyenne de 2,97 % pour un minimum de 3 %, longueur de 98,9 m pour un
minimum de 100 m).

**Aucune erreur de pente ni de traversée** sur les 18 segments vérifiés : les
plats annoncés sont plats, les côtes ont la pente annoncée, et les traversées
sont correctement comptées. Le critère de passage à la phase 2 est rempli.

Analyse des problèmes :

- **`ACCES` + `DOUBLON` (plats 1 et 2), une seule cause.**
  - `flat-641dc017c07b` est une voie `highway=service` qui traverse le parking
    d'une zone commerciale. Elle n'a pas le tag `service=parking_aisle`, donc
    rien dans ses tags ne permet de l'exclure.
  - Le « doublon » est le cheminement piéton couvert qui la longe, à 28 m en
    médiane : au-delà des 20 m de la déduplication.
  - Correctif possible : exclure les voies `service` situées dans une zone
    `amenity=parking`. Il n'est pas retenu pour l'instant (limite connue,
    voir [`architecture.md` § 7](../architecture.md#7-pièges-connus)).
- **`ACCES` (côte 20, `climb-35ee7ffc67d8`)** : chemin en terre puis rue. OSM
  ne porte aucun tag d'accès sur ces voies, et le pipeline ne peut pas deviner
  la restriction. La bonne correction se fait dans OSM (`access=*`) : elle
  sera prise en compte au prochain passage du pipeline.
