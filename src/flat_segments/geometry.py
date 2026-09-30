"""Pure planar geometry on polylines in a metric CRS (Lambert-93).

A polyline is a ``(N, 2)`` float array of ``(x, y)`` coordinates in metres.
Distances "along" a polyline are measured from its first vertex.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from typing import Final

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
IntArray = NDArray[np.intp]

#: Coordinate transformation of ``(N, 2)`` arrays between two CRS.
Projector = Callable[[FloatArray], FloatArray]

_EPS: Final = 1e-9


def as_coords(points: ArrayLike) -> FloatArray:
    """Convert ``points`` to a ``(N, 2)`` float64 array and validate its shape.

    Raises:
        ValueError: If the array is not ``(N, 2)``.
    """
    coords = np.asarray(points, dtype=np.float64)
    if coords.ndim != 2 or coords.shape[1] != 2:
        raise ValueError(f"expected an (N, 2) array, got shape {coords.shape}")
    return coords


def dedupe_vertices(coords: FloatArray) -> FloatArray:
    """Remove consecutive duplicate vertices (zero-length pieces)."""
    if len(coords) < 2:
        return coords.copy()
    step = np.hypot(*np.diff(coords, axis=0).T)
    keep = np.concatenate(([True], step > _EPS))
    return coords[keep]


def cumulative_distances(coords: FloatArray) -> FloatArray:
    """Distance along the polyline at each vertex (starts at 0)."""
    if len(coords) == 0:
        return np.zeros(0)
    steps = np.hypot(*np.diff(coords, axis=0).T)
    return np.concatenate(([0.0], np.cumsum(steps)))


def polyline_length(coords: FloatArray) -> float:
    """Total length of the polyline."""
    return float(cumulative_distances(coords)[-1]) if len(coords) else 0.0


def uniform_grid(length: float, step: float) -> FloatArray:
    """Uniform distances from 0 to ``length`` with a step of at most ``step``.

    The grid has ``ceil(length / step)`` equal intervals, so both ends are
    included and the effective step is ``length / n``. The same inputs always
    produce the same grid, which lets separate pipeline stages agree on it.
    """
    if step <= 0:
        raise ValueError("step must be positive")
    if length <= _EPS:
        return np.zeros(1)
    n = max(1, math.ceil(length / step - _EPS))
    return np.linspace(0.0, length, n + 1)


def interpolate_at(coords: FloatArray, distances: ArrayLike) -> FloatArray:
    """Points located at the given distances along the polyline.

    Distances are clipped to ``[0, length]``.
    """
    coords = dedupe_vertices(coords)
    targets = np.atleast_1d(np.asarray(distances, dtype=np.float64))
    if len(coords) == 1:
        return np.repeat(coords, len(targets), axis=0)
    cum = cumulative_distances(coords)
    targets = np.clip(targets, 0.0, cum[-1])
    seg = np.clip(np.searchsorted(cum, targets, side="right") - 1, 0, len(coords) - 2)
    seg_len = cum[seg + 1] - cum[seg]
    frac = np.where(seg_len > 0, (targets - cum[seg]) / np.where(seg_len > 0, seg_len, 1.0), 0.0)
    result: FloatArray = coords[seg] + frac[:, None] * (coords[seg + 1] - coords[seg])
    return result


def resample(coords: FloatArray, step: float) -> tuple[FloatArray, FloatArray]:
    """Resample the polyline on a uniform grid (see :func:`uniform_grid`).

    Returns:
        ``(distances, points)``: distances along the original polyline and the
        corresponding ``(M, 2)`` points.
    """
    distances = uniform_grid(polyline_length(coords), step)
    return distances, interpolate_at(coords, distances)


def substring(coords: FloatArray, start: float, end: float) -> FloatArray:
    """Exact sub-polyline between two distances, keeping original vertices.

    Raises:
        ValueError: If ``end`` is not greater than ``start``.
    """
    if end <= start:
        raise ValueError("end must be greater than start")
    coords = dedupe_vertices(coords)
    cum = cumulative_distances(coords)
    start, end = max(start, 0.0), min(end, float(cum[-1]))
    inner = coords[(cum > start + _EPS) & (cum < end - _EPS)]
    ends = interpolate_at(coords, [start, end])
    return np.vstack((ends[:1], inner, ends[1:]))


def chord_length(coords: FloatArray) -> float:
    """Straight-line distance between the first and last vertices."""
    return float(np.hypot(*(coords[-1] - coords[0])))


def sinuosity(coords: FloatArray) -> float:
    """Length divided by chord (1 for a straight line, ``inf`` for a closed ring)."""
    chord = chord_length(coords)
    return polyline_length(coords) / chord if chord > _EPS else math.inf


def bearing_deg(origin: FloatArray, target: FloatArray) -> float:
    """Bearing from ``origin`` to ``target``, clockwise from north, in ``[0, 360)``."""
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    return math.degrees(math.atan2(dx, dy)) % 360.0


def deflection_deg(bearing_a: float, bearing_b: float) -> float:
    """Deviation from a straight line between two edges leaving the same node.

    Both bearings point *away* from the shared node. Two edges in exact
    prolongation (opposite bearings) have a deflection of 0; two edges leaving
    in the same direction have a deflection of 180.
    """
    angle = abs((bearing_a - bearing_b + 180.0) % 360.0 - 180.0)
    return 180.0 - angle


def point_polyline_distances(points: FloatArray, coords: FloatArray) -> FloatArray:
    """Shortest distance from each point to the polyline."""
    coords = dedupe_vertices(coords)
    if len(coords) == 1:
        single: FloatArray = np.hypot(*(points - coords[0]).T)
        return single
    a = coords[:-1][None, :, :]
    ab = (coords[1:] - coords[:-1])[None, :, :]
    ap = points[:, None, :] - a
    t = np.clip((ap * ab).sum(axis=2) / (ab * ab).sum(axis=2), 0.0, 1.0)
    closest = a + t[:, :, None] * ab
    dist: FloatArray = np.hypot(*(points[:, None, :] - closest).transpose(2, 0, 1)).min(axis=1)
    return dist


def unit_normals(points: FloatArray) -> FloatArray:
    """Left-hand unit normals of a polyline at each of its vertices."""
    if len(points) < 2:
        return np.zeros_like(points)
    tangent = np.gradient(points, axis=0)
    norm = np.hypot(*tangent.T)
    norm[norm == 0] = 1.0
    tangent /= norm[:, None]
    return np.column_stack((-tangent[:, 1], tangent[:, 0]))


def bbox(coords: FloatArray) -> tuple[float, float, float, float]:
    """Bounding box ``(min_x, min_y, max_x, max_y)``."""
    lo, hi = coords.min(axis=0), coords.max(axis=0)
    return float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])


def stable_id(kind: str, coords: FloatArray, grid_m: float = 10.0) -> str:
    """Direction-independent identifier ``"{kind}-{12 hex}"`` for a segment.

    Built from the kind, both endpoints snapped to a ``grid_m`` grid (sorted)
    and the length rounded to ``grid_m``. It survives small geometry changes,
    but an endpoint close to a grid line may flip (see docs/algorithm.md
    section 12).
    """
    ends = sorted(
        (round(float(p[0]) / grid_m), round(float(p[1]) / grid_m)) for p in (coords[0], coords[-1])
    )
    length = round(polyline_length(coords) / grid_m)
    key = f"{kind}|{ends[0][0]}|{ends[0][1]}|{ends[1][0]}|{ends[1][1]}|{length}"
    return f"{kind}-{hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12]}"


def make_projector(source_crs: str, target_crs: str) -> Projector:
    """Return a function transforming ``(N, 2)`` arrays from one CRS to another.

    Coordinates are always in ``(x, y)`` / ``(lon, lat)`` order.
    """
    from pyproj import Transformer

    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)

    def project(points: FloatArray) -> FloatArray:
        x, y = transformer.transform(points[:, 0], points[:, 1])
        return np.column_stack((x, y))

    return project
