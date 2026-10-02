# 0012 — Identifiants conservés d'une version publiée à l'autre

- **Statut** : Acceptée
- **Date** : 2026-10-02

## Contexte

L'identifiant d'un segment est une empreinte de sa géométrie arrondie à 10 m
([`algorithm.md` § 12](../algorithm.md#12-identifiant-stable)). Une petite
modification change l'empreinte, et casse les liens déjà partagés (`?id=`) :

- un MNT plus fin ou d'autres paramètres ;
- une voie OSM retouchée.

Avec la production régulière ([ADR 0011](0011-production-github-actions.md)),
ce sera le cas à chaque régénération. Le passage au MNT à 2 m l'a montré :
5 liens sur 20 de la fiche terrain ne marchaient plus, dont
`flat-7784bbe8c297`, devenu trois segments.

## Décision

Avant de publier, on rapproche les nouveaux segments de ceux de la version
publiée (module `lineage.py`, option `export-pmtiles --previous`).

- **Version de référence** : ce qui a été publié, relu dans
  `segments.pmtiles` au zoom 14. Les géométries y sont à moins d'un mètre
  des originales : sur la Haute-Garonne, la longueur relue diffère de moins
  de 0,4 % pour 98 % des segments, et de 1,1 % au plus. On relit aussi l'index `ids/`.
- **Conservation** : un nouveau segment garde l'identifiant d'un ancien quand
  - ils sont du même type ;
  - chacun est couvert à **80 %** au moins par l'autre, à **10 m** près.
  
  Les paires se forment une à une, la meilleure d'abord.
- **Redirection** : un ancien identifiant resté sans paire renvoie au nouveau
  segment qui en couvre la plus grande part, s'il en couvre au moins
  **30 %**. C'est le cas d'un plat coupé en trois, par exemple. Sinon,
  l'identifiant est **retiré**.
- **Mémoire** : les redirections des versions précédentes sont gardées, et
  leur cible est suivie jusqu'à la version courante (un seul saut pour le
  front).
- **Pas de réemploi** : un nouveau segment dont l'empreinte est déjà prise
  (segment, redirection ou identifiant retiré) reçoit un suffixe `-2`, `-3`…
  Un identifiant ne désigne donc jamais deux segments différents au fil des
  versions.
- **Index** : `ids/XX.json` contient `[lon, lat]` pour un segment, et
  `[lon, lat, cible]` pour une redirection (`cible` à `null` si le segment
  n'existe plus). La longueur du préfixe des fichiers grandit avec le jeu
  (2 caractères, soit 256 fichiers, jusqu'à 512 000 identifiants).
- **Front** :
  - un identifiant redirigé ouvre sa cible, et l'adresse prend le nouvel
    identifiant ;
  - un identifiant retiré montre l'endroit où était le segment ;
  - dans les deux cas, la page le signale.

## Conséquences

- **Mesures sur la Haute-Garonne** :
  - comparée à sa propre version publiée : 45 341 identifiants sur 45 341
    gardés, en 30 s ;
  - comparée au pilote de la phase 1 (MNT à 1 m) : 2 913 identifiants sur
    3 036 gardés, 78 redirigés, 45 retirés ;
  - les 20 liens de la fiche terrain fonctionnent à nouveau, y compris
    `flat-7784bbe8c297`.
- **L'identifiant n'est plus une simple empreinte** : il dépend de
  l'historique des publications. Le GeoParquet d'un département garde
  l'empreinte, et seul le jeu publié porte l'identifiant définitif.
- **Coût** : la relecture et le rapprochement prennent environ 30 s par
  département de la taille de la Haute-Garonne. Pour la France, c'est
  quelques minutes à l'assemblage.
- **Un jeu publié remplace le précédent en entier** : un segment absent de la
  nouvelle publication est retiré ou redirigé. Publier moins de départements
  qu'avant retire donc les identifiants des autres.

## Alternatives considérées

- **Repli par position** : les liens portent aussi la position, et un
  identifiant inconnu ouvre le segment le plus proche de même type. C'est
  simple, mais approximatif, et les liens existants n'ont pas de position.
- **Identifiant tiré des voies OSM** (`osm_way_ids` et abscisses) : il change
  aussi quand une voie est découpée ou fusionnée dans OSM, ce qui est
  fréquent.
- **Fichier de filiation à part** (GeoParquet des identifiants et
  géométries) : il est exact, mais c'est un fichier de plus à publier et à
  garder cohérent. Relire le jeu publié suffit.
