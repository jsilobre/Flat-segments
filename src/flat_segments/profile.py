"""Elevation profiles along strokes: gap filling, smoothing, grade, gain/loss.

All functions are pure and operate on numpy arrays sampled on a uniform grid
(see :func:`flat_segments.geometry.uniform_grid`). ``NaN`` marks missing
elevation. See docs/algorithm.md sections 4 to 6.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from flat_segments.geometry import BoolArray, FloatArray, resample
from flat_segments.params import ProfileParams

#: A bridge or tunnel along a stroke: ``(start_m, end_m, kind)``.
Structure = tuple[float, float, str]


def true_runs(mask: BoolArray) -> list[tuple[int, int]]:
    """Runs of consecutive ``True`` values as ``(start, end)`` with ``end`` exclusive."""
    padded = np.concatenate(([0], mask.astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(padded))
    return [(int(s), int(e)) for s, e in zip(edges[::2], edges[1::2], strict=True)]


def _odd_reflect_pad(values: FloatArray, width: int) -> FloatArray:
    """Pad by point reflection around each end, which preserves linear trends."""
    if width <= 0 or len(values) < 2:
        return np.pad(values, width, mode="edge") if width > 0 else values.copy()
    return np.pad(values, width, mode="reflect", reflect_type="odd")


def rolling_median(z: FloatArray, window: int) -> FloatArray:
    """NaN-aware rolling median over ``window`` samples (forced to be odd).

    ``NaN`` inputs stay ``NaN``; other ``NaN`` values in a window are ignored.
    """
    window = max(1, window) | 1
    if window == 1 or len(z) < 2:
        return z.copy()
    half = window // 2
    windows = sliding_window_view(_odd_reflect_pad(z, half), window)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result: FloatArray = np.nanmedian(windows, axis=1)
    result[np.isnan(z)] = np.nan
    return result


def gaussian_smooth(z: FloatArray, sigma: float) -> FloatArray:
    """NaN-aware Gaussian smoothing with ``sigma`` expressed in samples.

    The kernel is truncated at 3 sigma and renormalised over valid samples.
    Ends are padded by odd reflection so that a linear profile is unchanged.
    """
    if sigma <= 0 or len(z) < 2:
        return z.copy()
    radius = max(1, math.ceil(3.0 * sigma))
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / sigma) ** 2)
    padded = _odd_reflect_pad(z, radius)
    valid = ~np.isnan(padded)
    num = np.convolve(np.where(valid, padded, 0.0), kernel, mode="valid")
    den = np.convolve(valid.astype(np.float64), kernel, mode="valid")
    result: FloatArray = np.full_like(z, np.nan)
    np.divide(num, den, out=result, where=den > 0)
    result[np.isnan(z)] = np.nan
    return result


def smooth(z: FloatArray, step: float, params: ProfileParams) -> FloatArray:
    """Rolling median followed by Gaussian smoothing (docs/algorithm.md section 5)."""
    median_window = round(params.median_window_m / step)
    return gaussian_smooth(rolling_median(z, median_window), params.gaussian_sigma_m / step)


def local_grade_pct(distances: FloatArray, z: FloatArray, base_m: float) -> FloatArray:
    """Local grade in percent: centred difference over ``base_m``.

    Indices are clipped at the ends, where the difference becomes one-sided.
    """
    n = len(z)
    if n < 2:
        return np.zeros(n)
    step = float(distances[1] - distances[0])
    half = max(1, round(base_m / 2.0 / step))
    idx = np.arange(n)
    lo = np.clip(idx - half, 0, n - 1)
    hi = np.clip(idx + half, 0, n - 1)
    grade: FloatArray = 100.0 * (z[hi] - z[lo]) / (distances[hi] - distances[lo])
    return grade


def elevation_gain_loss(z: FloatArray, hysteresis: float) -> tuple[float, float]:
    """Cumulative gain and loss (both positive) with a hysteresis threshold.

    A change is only counted once it exceeds ``hysteresis`` from the last
    reference point; the remainder at the end is always counted, so that
    ``gain - loss == z[-1] - z[0]`` (ignoring ``NaN``).
    """
    values = z[~np.isnan(z)]
    if len(values) < 2:
        return 0.0, 0.0
    gain = loss = 0.0
    ref = float(values[0])
    for value in values[1:]:
        diff = float(value) - ref
        if diff >= hysteresis:
            gain += diff
            ref = float(value)
        elif diff <= -hysteresis:
            loss -= diff
            ref = float(value)
    rest = float(values[-1]) - ref
    if rest > 0:
        gain += rest
    else:
        loss -= rest
    return gain, loss


def _interpolate_run(distances: FloatArray, z: FloatArray, start: int, end: int) -> bool:
    """Linearly interpolate ``z[start:end]`` between its neighbours, in place.

    Returns:
        ``False`` (and leaves ``z`` untouched) when the run touches an end.
    """
    if start == 0 or end == len(z):
        return False
    left, right = start - 1, end
    z[start:end] = np.interp(distances[start:end], distances[[left, right]], z[[left, right]])
    return True


@dataclass(frozen=True, slots=True, eq=False)
class Profile:
    """Elevation profile of a stroke on a uniform grid.

    Attributes:
        distances: Distance along the stroke of each sample.
        xy: Sample coordinates, ``(N, 2)``.
        z_raw: Elevation read from the DEM (``NaN`` = nodata).
        z: Elevation after structure / gap interpolation and smoothing.
        grade_pct: Local grade of ``z`` in percent.
        bridge_mask: Samples interpolated across a bridge.
        tunnel_mask: Samples interpolated through a tunnel.
        gap_mask: DEM nodata samples filled by interpolation.
    """

    distances: FloatArray
    xy: FloatArray
    z_raw: FloatArray
    z: FloatArray
    grade_pct: FloatArray
    bridge_mask: BoolArray
    tunnel_mask: BoolArray
    gap_mask: BoolArray

    @property
    def step(self) -> float:
        """Effective sampling step in metres."""
        return float(self.distances[1] - self.distances[0]) if len(self.distances) > 1 else 0.0

    @property
    def length(self) -> float:
        """Profile length in metres."""
        return float(self.distances[-1])


def fill_profile(
    distances: FloatArray,
    z_raw: FloatArray,
    structures: Sequence[Structure],
    params: ProfileParams,
) -> tuple[FloatArray, BoolArray, BoolArray, BoolArray]:
    """Interpolate elevation across bridges, tunnels and short nodata gaps.

    Returns:
        ``(z, bridge_mask, tunnel_mask, gap_mask)``. Samples that could not be
        interpolated (structure or long gap touching an end, long gap) stay
        ``NaN``.
    """
    z = z_raw.astype(np.float64, copy=True)
    masks = {"bridge": np.zeros(len(z), bool), "tunnel": np.zeros(len(z), bool)}
    for start, end, kind in structures:
        inside = (distances >= start - params.structure_margin_m) & (
            distances <= end + params.structure_margin_m
        )
        masks[kind] |= inside
        z[inside] = np.nan
    on_structure = masks["bridge"] | masks["tunnel"]
    filled = np.zeros(len(z), bool)
    for start, end in true_runs(np.isnan(z)):
        crosses_structure = bool(on_structure[start:end].any())
        left = distances[max(start - 1, 0)]
        right = distances[min(end, len(z) - 1)]
        if (crosses_structure or right - left <= params.max_gap_fill_m) and _interpolate_run(
            distances, z, start, end
        ):
            filled[start:end] = True
    bridge_mask = masks["bridge"] & filled
    tunnel_mask = masks["tunnel"] & filled
    gap_mask = filled & ~on_structure
    return z, bridge_mask, tunnel_mask, gap_mask


def build_profile(
    coords: FloatArray,
    z_raw: FloatArray,
    params: ProfileParams,
    structures: Sequence[Structure] = (),
) -> Profile:
    """Build the smoothed profile of a stroke from its raw DEM samples.

    Args:
        coords: Stroke polyline (Lambert-93).
        z_raw: Raw elevations on the grid ``resample(coords, params.step_m)``.
        params: Profile parameters.
        structures: Bridges and tunnels along the stroke.

    Raises:
        ValueError: If ``z_raw`` does not match the resampling grid.
    """
    distances, xy = resample(coords, params.step_m)
    if len(z_raw) != len(distances):
        raise ValueError(f"z_raw has {len(z_raw)} samples, expected {len(distances)}")
    z_filled, bridge_mask, tunnel_mask, gap_mask = fill_profile(
        distances, np.asarray(z_raw, dtype=np.float64), structures, params
    )
    step = float(distances[1] - distances[0]) if len(distances) > 1 else params.step_m
    z = smooth(z_filled, step, params)
    grade = local_grade_pct(distances, z, params.grade_base_m)
    return Profile(
        distances=distances,
        xy=xy,
        z_raw=np.asarray(z_raw, dtype=np.float64),
        z=z,
        grade_pct=grade,
        bridge_mask=bridge_mask,
        tunnel_mask=tunnel_mask,
        gap_mask=gap_mask,
    )
