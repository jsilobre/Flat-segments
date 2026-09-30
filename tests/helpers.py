"""Shared helpers to build synthetic networks."""

from __future__ import annotations

import itertools
from collections.abc import Callable

import numpy as np

from flat_segments.geometry import resample
from flat_segments.network import RoadClass, Stroke, StrokeEvent, StrokePart, Way

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


def straight_stroke(
    length: float,
    *,
    stroke_id: str = "s000001",
    parts: tuple[StrokePart, ...] | None = None,
    events: tuple[StrokeEvent, ...] = (),
    offset_y: float = 0.0,
    surface: str | None = "asphalt",
) -> Stroke:
    """A west-east stroke along ``y = offset_y`` made of one PATH way."""
    if parts is None:
        parts = (StrokePart(1, 0.0, length, "cycleway", RoadClass.PATH, surface=surface),)
    coords = np.array([(0.0, offset_y), (length, offset_y)])
    return Stroke(stroke_id, coords, parts, events)


def raw_profile(
    stroke: Stroke, z_of_d: Callable[[np.ndarray], np.ndarray], step: float = 5.0
) -> np.ndarray:
    """Raw elevations on the stroke grid from a function of the distance along it."""
    distances, _ = resample(stroke.coords, step)
    return np.asarray(z_of_d(distances), dtype=np.float64)


def piecewise(*pieces: tuple[float, float]) -> Callable[[np.ndarray], np.ndarray]:
    """Profile made of ``(length_m, grade_pct)`` pieces, starting at 150 m."""
    breaks = np.cumsum([0.0] + [length for length, _ in pieces])
    heights = np.cumsum([150.0] + [length * grade / 100 for length, grade in pieces])
    return lambda d: np.interp(d, breaks, heights)
