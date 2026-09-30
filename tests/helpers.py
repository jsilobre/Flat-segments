"""Shared helpers to build synthetic networks."""

from __future__ import annotations

import itertools

import numpy as np

from flat_segments.network import RoadClass, Way

_node_ids: dict[tuple[float, float], int] = {}
_counter = itertools.count(1)


def node_id(point: tuple[float, float]) -> int:
    """Same coordinates -> same node id, so that ways sharing a point connect."""
    if point not in _node_ids:
        _node_ids[point] = next(_counter)
    return _node_ids[point]


def make_way(
    way_id: int,
    points: list[tuple[float, float]],
    road_class: RoadClass = RoadClass.PATH,
    highway: str = "footway",
    **attrs: str,
) -> Way:
    return Way(
        id=way_id,
        node_ids=tuple(node_id(p) for p in points),
        coords=np.array(points, dtype=np.float64),
        road_class=road_class,
        highway=highway,
        **attrs,
    )
