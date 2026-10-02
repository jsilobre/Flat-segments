"""Segment ids kept from one published version to the next (ADR 0012).

A segment id is a hash of its rounded geometry (``geometry.stable_id``): a
small change (new DEM, edited OSM way, other parameters) gives a new id and
breaks the links already shared. Before publishing, the new segments are
therefore matched with the previously published ones:

* a new segment that covers the same ground as a previous one of the same
  kind (both covered at ``MATCH_MIN`` or more, within ``BUFFER_M``) takes
  its id; pairs are formed greedily, best match first, one to one;
* a previous id left without a match becomes an **alias** of the new segment
  that covers most of it (at least ``ALIAS_MIN`` of its length), e.g. a flat
  split in three; otherwise it is **retired** (segment gone);
* aliases and retired ids of the earlier versions are kept, their targets
  followed to the current version;
* a new segment whose own id is already taken (by a previous segment, alias
  or retired id) gets a ``-2``, ``-3``… suffix.

The previous version is read from what was published (``segments.pmtiles``
at its most detailed zoom, and ``ids/``): what the users saw is the
reference. The tile geometries are within a metre of the original ones.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from flat_segments.detect import Segment
from flat_segments.params import WEB_CRS, WORK_CRS

#: Distance under which two lines cover the same ground, in metres.
BUFFER_M: Final = 10.0
#: Share of both segments covered by the other for the id to be kept.
MATCH_MIN: Final = 0.8
#: Share of a vanished segment covered by a new one to redirect its id there.
ALIAS_MIN: Final = 0.3
#: A segment id: kind, 12 hexadecimal characters, optional ``-N`` suffix.
SEGMENT_ID: Final = re.compile(r"(flat|climb)-[0-9a-f]{12}(-[0-9]+)?")


def is_segment_id(value: object) -> bool:
    """Whether ``value`` is a segment id (a damaged tile may hold anything)."""
    return isinstance(value, str) and SEGMENT_ID.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class PreviousSegment:
    """A segment of the previous version (geometry in Lambert-93)."""

    id: str
    kind: str
    geometry: BaseGeometry


@dataclass(frozen=True, slots=True)
class Redirect:
    """An id that no longer names a segment.

    ``target`` is the id to open instead (``None``: the segment is gone) and
    ``position`` ``[lon, lat]`` is where to look: the target, else the old
    segment.
    """

    target: str | None
    position: tuple[float, float]


@dataclass(frozen=True, slots=True)
class PreviousVersion:
    """What was published before: segments and redirects."""

    segments: tuple[PreviousSegment, ...]
    redirects: Mapping[str, Redirect]


@dataclass(frozen=True, slots=True)
class Lineage:
    """Result of :func:`match`: segments with their final ids, and redirects."""

    segments: tuple[Segment, ...]
    redirects: Mapping[str, Redirect]
    kept: int  # segments that kept a previous id
    renamed: int  # new segments whose own id was taken
    aliased: int  # previous ids now redirected to another segment
    retired: int  # previous ids now naming nothing

    @property
    def summary(self) -> str:
        """One line for the logs."""
        new = len(self.segments) - self.kept
        return (
            f"{self.kept} ids kept, {new} new ({self.renamed} renamed), "
            f"{self.aliased} redirected, {self.retired} retired, "
            f"{len(self.redirects)} redirects in total"
        )


def read_previous(directory: Path, layer: str = "segments") -> PreviousVersion | None:
    """Read a published tileset (``segments.pmtiles``, ``ids/``), or None if absent.

    The pieces of a segment cut by tile borders are merged back. Features
    whose id is not a segment id are left out: tippecanoe before 2.55 could
    give a feature the value of another attribute as id (ADR 0009). The kind
    is taken from the id.
    """
    import geopandas as gpd

    pmtiles = directory / "segments.pmtiles"
    if not pmtiles.exists():
        return None
    frame = gpd.read_file(pmtiles, layer=layer, columns=["id"], engine="pyogrio")
    frame = frame[frame["id"].map(is_segment_id)]
    segments: tuple[PreviousSegment, ...] = ()
    if len(frame):
        merged = frame.to_crs(WORK_CRS).dissolve(by="id")
        segments = tuple(
            PreviousSegment(str(i), str(i).split("-")[0], shapely.line_merge(geometry))
            for i, geometry in zip(merged.index, merged.geometry, strict=True)
        )
    return PreviousVersion(segments, read_redirects(directory / "ids"))


def read_redirects(index_dir: Path) -> dict[str, Redirect]:
    """Redirects of a published id index (entries ``[lon, lat, target]``).

    Entries that are not segment ids, or whose target is not one, are left out.
    """
    redirects: dict[str, Redirect] = {}
    for path in sorted(index_dir.glob("*.json")):
        for segment_id, entry in json.loads(path.read_text(encoding="utf-8")).items():
            if len(entry) != 3 or not is_segment_id(segment_id):
                continue
            target = entry[2]
            if target is None or is_segment_id(target):
                redirects[segment_id] = Redirect(target, (float(entry[0]), float(entry[1])))
    return redirects


def _pairs(
    current: Sequence[BaseGeometry], previous: Sequence[BaseGeometry], buffer_m: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Candidate pairs (i current, j previous) and the share of each covered by the other."""
    empty = np.zeros(0, dtype=np.intp)
    if not current or not previous:
        return empty, empty, np.zeros(0), np.zeros(0)
    cur = np.asarray(current, dtype=object)
    prev = np.asarray(previous, dtype=object)
    cur_buffers = shapely.buffer(cur, buffer_m)
    prev_buffers = shapely.buffer(prev, buffer_m)
    i, j = shapely.STRtree(prev).query(cur_buffers, predicate="intersects")
    cur_covered = shapely.length(shapely.intersection(cur[i], prev_buffers[j]))
    prev_covered = shapely.length(shapely.intersection(prev[j], cur_buffers[i]))
    with np.errstate(divide="ignore", invalid="ignore"):
        cur_share = np.nan_to_num(cur_covered / shapely.length(cur[i]))
        prev_share = np.nan_to_num(prev_covered / shapely.length(prev[j]))
    return i, j, cur_share, prev_share


def _midpoint(geometry: BaseGeometry) -> tuple[float, float]:
    point = shapely.line_interpolate_point(geometry, 0.5, normalized=True)
    return float(point.x), float(point.y)


def _free_id(segment_id: str, taken: set[str]) -> str:
    """``segment_id``, or with the first free ``-N`` suffix."""
    candidate, n = segment_id, 1
    while candidate in taken:
        n += 1
        candidate = f"{segment_id}-{n}"
    return candidate


def match(
    current: Sequence[Segment],
    previous: PreviousVersion | None,
    *,
    buffer_m: float = BUFFER_M,
    match_min: float = MATCH_MIN,
    alias_min: float = ALIAS_MIN,
    to_wgs84: Any = None,
) -> Lineage:
    """Give the current segments their final ids, and list the redirects."""
    from flat_segments.geometry import make_projector

    if previous is None:
        return Lineage(tuple(current), {}, 0, 0, 0, 0)
    to_wgs84 = to_wgs84 or make_projector(WORK_CRS, WEB_CRS)
    geometries = [LineString(s.coords) for s in current]

    final: dict[int, str] = {}  # current index -> previous id kept
    best_alias: dict[int, tuple[float, int]] = {}  # previous index -> (share, current index)
    by_kind_prev: dict[str, list[int]] = defaultdict(list)
    for j, p in enumerate(previous.segments):
        by_kind_prev[p.kind].append(j)
    by_kind_cur: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(current):
        by_kind_cur[s.kind.value].append(i)

    for kind, cur_idx in by_kind_cur.items():
        prev_idx = by_kind_prev.get(kind, [])
        pair_cur, pair_prev, cur_share, prev_share = _pairs(
            [geometries[k] for k in cur_idx],
            [previous.segments[k].geometry for k in prev_idx],
            buffer_m,
        )
        score = np.minimum(cur_share, prev_share)
        used_cur: set[int] = set()
        used_prev: set[int] = set()
        for k in np.lexsort((-np.maximum(cur_share, prev_share), -score)):
            if score[k] < match_min:
                break
            ci, pj = cur_idx[pair_cur[k]], prev_idx[pair_prev[k]]
            if ci not in used_cur and pj not in used_prev:
                used_cur.add(ci)
                used_prev.add(pj)
                final[ci] = previous.segments[pj].id
        for k in range(len(pair_cur)):
            ci, pj = cur_idx[pair_cur[k]], prev_idx[pair_prev[k]]
            if pj in used_prev or prev_share[k] < alias_min:
                continue
            if pj not in best_alias or prev_share[k] > best_alias[pj][0]:
                best_alias[pj] = (float(prev_share[k]), ci)

    # Final ids: kept ones first, then the others, avoiding every known id.
    kept_ids = set(final.values())
    taken = kept_ids | {p.id for p in previous.segments} | set(previous.redirects)
    renamed = 0
    for i, segment in enumerate(current):
        if i in final:
            continue
        final[i] = _free_id(segment.id, taken)
        taken.add(final[i])
        renamed += final[i] != segment.id
    segments = tuple(
        s if final[i] == s.id else replace(s, id=final[i]) for i, s in enumerate(current)
    )
    index_of = {segment_id: i for i, segment_id in final.items()}

    def lonlat(geometry: BaseGeometry) -> tuple[float, float]:
        lon, lat = to_wgs84(np.array([_midpoint(geometry)]))[0]
        return round(float(lon), 5), round(float(lat), 5)

    def towards(target: str) -> Redirect:
        return Redirect(target, lonlat(geometries[index_of[target]]))

    redirects: dict[str, Redirect] = {}
    aliased = retired = 0
    for j, p in enumerate(previous.segments):
        if p.id in kept_ids:
            continue
        if j in best_alias:
            redirects[p.id] = towards(final[best_alias[j][1]])
            aliased += 1
        else:
            redirects[p.id] = Redirect(None, lonlat(p.geometry))
            retired += 1
    # Earlier redirects: follow their target (a previous segment) to this version.
    for old_id, redirect in previous.redirects.items():
        target = redirect.target
        if target is None:
            redirects[old_id] = redirect
        elif target in kept_ids:
            redirects[old_id] = towards(target)
        elif target in redirects:
            redirects[old_id] = redirects[target]
        else:  # not a previous segment: inconsistent index, keep the place only
            redirects[old_id] = Redirect(None, redirect.position)
    return Lineage(segments, redirects, len(kept_ids), renamed, aliased, retired)
