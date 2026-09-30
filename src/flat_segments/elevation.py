"""Elevation sampling along strokes (docs/algorithm.md section 3).

A DEM is anything implementing :class:`DemSampler`: it returns an elevation
(or ``NaN``) for ``(N, 2)`` Lambert-93 points. Three implementations:

* :class:`ArrayDem`: an in-memory north-up grid, bilinear interpolation (pure);
* :class:`FunctionDem`: an analytic function, for tests and sample data;
* :class:`RasterDem`: a GeoTIFF / VRT read on demand with rasterio.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self

import numpy as np

from flat_segments.geometry import FloatArray, resample, unit_normals
from flat_segments.params import WORK_CRS, ProfileParams

#: Affine transform ``(a, b, c, d, e, f)``: ``x = a*col + b*row + c``,
#: ``y = d*col + e*row + f`` (same order as ``affine.Affine`` / rasterio).
Transform = tuple[float, float, float, float, float, float]


class DemSampler(Protocol):
    """Anything that returns elevations for Lambert-93 points."""

    def sample(self, xy: FloatArray) -> FloatArray:
        """Elevation at each ``(x, y)`` point, ``NaN`` where unknown."""
        ...


def bilinear_sample(
    values: FloatArray, transform: Transform, xy: FloatArray, nodata: float | None = None
) -> FloatArray:
    """Bilinear interpolation of a north-up grid at arbitrary points.

    Pixel values are taken at pixel centres. Points outside the grid, or whose
    interpolation involves a nodata pixel, get ``NaN``.

    Raises:
        ValueError: If the transform is rotated.
    """
    a, b, c, d, e, f = transform
    if b != 0 or d != 0:
        raise ValueError("rotated rasters are not supported")
    grid = values.astype(np.float64)
    if nodata is not None:
        grid = np.where(grid == nodata, np.nan, grid)
    rows, cols = grid.shape
    col_f = (xy[:, 0] - c) / a
    row_f = (xy[:, 1] - f) / e
    inside = (col_f >= 0) & (col_f <= cols) & (row_f >= 0) & (row_f <= rows)
    # Pixel-centre coordinates, clamped so that the outer half pixels are usable.
    col_c = np.clip(col_f - 0.5, 0, cols - 1)
    row_c = np.clip(row_f - 0.5, 0, rows - 1)
    c0 = np.clip(np.floor(col_c).astype(np.intp), 0, max(cols - 2, 0))
    r0 = np.clip(np.floor(row_c).astype(np.intp), 0, max(rows - 2, 0))
    c1, r1 = np.minimum(c0 + 1, cols - 1), np.minimum(r0 + 1, rows - 1)
    fx, fy = col_c - c0, row_c - r0
    top = grid[r0, c0] * (1 - fx) + grid[r0, c1] * fx
    bottom = grid[r1, c0] * (1 - fx) + grid[r1, c1] * fx
    result: FloatArray = np.where(inside, top * (1 - fy) + bottom * fy, np.nan)
    return result


@dataclass(frozen=True, slots=True, eq=False)
class ArrayDem:
    """An in-memory north-up DEM grid."""

    values: FloatArray
    transform: Transform
    nodata: float | None = None

    def sample(self, xy: FloatArray) -> FloatArray:
        """Bilinear elevation at each point."""
        return bilinear_sample(self.values, self.transform, xy, self.nodata)


@dataclass(frozen=True, slots=True)
class FunctionDem:
    """A DEM defined by a function ``z = f(x, y)`` (synthetic data)."""

    function: Callable[[FloatArray, FloatArray], FloatArray]

    def sample(self, xy: FloatArray) -> FloatArray:
        """Evaluate the function at each point."""
        return np.asarray(self.function(xy[:, 0], xy[:, 1]), dtype=np.float64)


class RasterDem:
    """A DEM raster (GeoTIFF, VRT, COG) in Lambert-93, read window by window.

    Use as a context manager. Each :meth:`sample` call reads only the window
    covering the requested points (plus a one-pixel margin).
    """

    def __init__(self, path: Path) -> None:
        import rasterio

        self._dataset: Any = rasterio.open(path)
        crs = self._dataset.crs
        if crs is None or crs.to_epsg() != int(WORK_CRS.split(":")[1]):
            self._dataset.close()
            raise ValueError(f"{path}: expected a {WORK_CRS} raster, got {crs}")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying dataset."""
        self._dataset.close()

    def sample(self, xy: FloatArray) -> FloatArray:
        """Bilinear elevation at each point (``NaN`` outside the raster)."""
        from rasterio.windows import Window

        ds = self._dataset
        t = ds.transform
        if t.b != 0 or t.d != 0:
            raise ValueError("rotated rasters are not supported")
        cols, rows = (xy[:, 0] - t.c) / t.a, (xy[:, 1] - t.f) / t.e
        col_lo = max(math.floor(float(np.min(cols))) - 1, 0)
        row_lo = max(math.floor(float(np.min(rows))) - 1, 0)
        col_hi = min(math.ceil(float(np.max(cols))) + 1, ds.width)
        row_hi = min(math.ceil(float(np.max(rows))) + 1, ds.height)
        if col_hi <= col_lo or row_hi <= row_lo:
            return np.full(len(xy), np.nan)
        window = Window(col_lo, row_lo, col_hi - col_lo, row_hi - row_lo)
        values = ds.read(1, window=window, masked=False).astype(np.float64)
        origin = (t.c + col_lo * t.a, t.f + row_lo * t.e)
        window_transform = (t.a, 0.0, origin[0], 0.0, t.e, origin[1])
        result = bilinear_sample(values, window_transform, xy, ds.nodata)
        # Points outside the whole raster must stay NaN even if the window clamps.
        outside = (cols < 0) | (cols > ds.width) | (rows < 0) | (rows > ds.height)
        result[outside] = np.nan
        return result


def sample_stroke(coords: FloatArray, dem: DemSampler, params: ProfileParams) -> FloatArray:
    """Raw elevations of a stroke on its uniform grid.

    With ``params.lateral_offset_m > 0``, the median of the centre sample and
    the two samples offset across the line is kept.
    """
    _, points = resample(coords, params.step_m)
    z = dem.sample(points)
    if params.lateral_offset_m > 0 and len(points) > 1:
        offset = unit_normals(points) * params.lateral_offset_m
        stacked = np.vstack((z, dem.sample(points + offset), dem.sample(points - offset)))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN columns stay NaN
            z = np.nanmedian(stacked, axis=0)
    return z


def bbox_to_lambert93(
    bbox: tuple[float, float, float, float], round_to_m: float = 1000.0
) -> tuple[float, float, float, float]:
    """Project a WGS84 bbox to Lambert-93, rounded outwards (km by default)."""
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", WORK_CRS, always_xy=True)
    min_x, min_y, max_x, max_y = transformer.transform_bounds(*bbox, densify_pts=21)
    r = round_to_m
    return (
        math.floor(min_x / r) * r,
        math.floor(min_y / r) * r,
        math.ceil(max_x / r) * r,
        math.ceil(max_y / r) * r,
    )
