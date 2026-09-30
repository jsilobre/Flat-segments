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

   L'échantillon est déterministe et représentatif. Les côtes y sont
   représentées (au moins 3 s'il y en a). Il contient au moins un segment
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
