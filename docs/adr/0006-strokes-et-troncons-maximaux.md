# 0006 — Chaînage par continuité (*strokes*) et tronçons maximaux

- **Statut** : Acceptée
- **Date** : 2026-09-30

## Contexte

Deux choix d'algorithme conditionnent la forme des résultats :

1. **Où couper le réseau ?** Couper à chaque intersection empêche de trouver
   des segments longs sur les voies souvent croisées par de petits chemins (voies
   vertes, rues).
2. **Que produire ?** Soit une fenêtre de longueur fixe par longueur cible
   (200 m, 400 m…), soit le tronçon plat (ou la montée) le plus long possible.

## Décision

1. Les ways sont chaînées en **strokes** par *continuité naturelle* : à chaque
   carrefour, on prolonge par l'arête la plus droite (déflexion ≤ 35°). Un
   stroke n'est coupé qu'en cul-de-sac, en l'absence de prolongement droit, ou
   au contact d'une route `MAJOR`. Les carrefours restent des **événements**
   (`crossing`, `junction`) le long du stroke.
2. La fenêtre glissante (à la plus courte longueur cible) sert de **primitive
   de détection**. Les fenêtres valides qui se chevauchent sont **fusionnées
   en tronçons maximaux**, avec l'attribut `fits_targets_m` qui indique les
   longueurs cibles réalisables dans le tronçon. Les côtes sont rognées aux
   extrémités et orientées vers le haut.

Détails : [`algorithm.md` § 2, 7 et 8](../algorithm.md#2-construction-du-graphe-et-chaînage-en-strokes).

## Conséquences

- Moins de doublons (un plat = un segment), et un filtrage simple côté front
  (« longueur ≥ X »).
- Les statistiques d'un tronçon fusionné (pente moyenne, sinuosité) peuvent
  dépasser les seuils de fenêtre. Elles sont publiées telles quelles et le
  front filtre dessus.
- La règle de continuité (angle, sonde de cap) devra être validée sur des cas
  réels en phase 1.

## Alternatives considérées

- **Découpage à chaque intersection** : simple, mais segments trop courts.
- **Fenêtres de longueur fixe par cible, avec suppression des non-maxima** :
  plus de segments quasi identiques, et un segment de 400 m réapparaît en
  plusieurs fenêtres de 200 m.
