from pathlib import Path

import numpy as np
import pytest

from flat_segments import elevation as el
from flat_segments.params import PILOT_BBOX_WGS84, ProfileParams

# 10 x 8 grid of 5 m pixels, top-left corner at (1000, 2040): z = 2x + 3y + 5.
TRANSFORM: el.Transform = (5.0, 0.0, 1000.0, 0.0, -5.0, 2040.0)


def plane_grid() -> np.ndarray:
    cols, rows = np.meshgrid(np.arange(10), np.arange(8))
    x = 1000 + 5 * (cols + 0.5)
    y = 2040 - 5 * (rows + 0.5)
    return 2 * x + 3 * y + 5


def write_geotiff(path: Path, values: np.ndarray, transform: el.Transform, crs: str) -> None:
    import rasterio
    from rasterio.transform import Affine

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs=crs,
        transform=Affine(*transform),
        nodata=-99999.0,
    ) as dst:
        dst.write(values.astype(np.float32), 1)


def test_bilinear_is_exact_on_a_plane() -> None:
    xy = np.array([(1012.3, 2021.7), (1003.0, 2037.0), (1047.4, 2003.1)])
    z = el.bilinear_sample(plane_grid(), TRANSFORM, xy)
    np.testing.assert_allclose(z, 2 * xy[:, 0] + 3 * xy[:, 1] + 5)


def test_outside_and_nodata_give_nan() -> None:
    grid = plane_grid()
    grid[3, 3] = -99999.0
    xy = np.array([(900.0, 2000.0), (1017.5, 2022.5), (1040.0, 2010.0)])
    z = el.bilinear_sample(grid, TRANSFORM, xy, nodata=-99999.0)
    assert np.isnan(z[0])
    assert np.isnan(z[1])
    assert np.isfinite(z[2])


def test_rotated_transform_is_rejected() -> None:
    with pytest.raises(ValueError, match="rotated"):
        el.bilinear_sample(plane_grid(), (5.0, 1.0, 0.0, 0.0, -5.0, 0.0), np.zeros((1, 2)))


def test_sample_stroke_on_grid() -> None:
    dem = el.FunctionDem(lambda x, y: 100 + 0.01 * x)
    coords = np.array([(0.0, 0.0), (100.0, 0.0)])
    z = el.sample_stroke(coords, dem, ProfileParams(step_m=5))
    np.testing.assert_allclose(z, 100 + 0.01 * np.arange(0, 101, 5))


def test_lateral_median_ignores_a_narrow_embankment() -> None:
    def ridge(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return 150 + 3.0 * (np.abs(y) < 1.0)

    coords = np.array([(0.0, 0.0), (100.0, 0.0)])
    dem = el.FunctionDem(ridge)
    np.testing.assert_allclose(el.sample_stroke(coords, dem, ProfileParams()), 153)
    np.testing.assert_allclose(
        el.sample_stroke(coords, dem, ProfileParams(lateral_offset_m=2.0)), 150
    )


def test_raster_dem_reads_windows(tmp_path: Path) -> None:
    path = tmp_path / "dem.tif"
    write_geotiff(path, plane_grid(), TRANSFORM, "EPSG:2154")
    xy = np.array([(1012.3, 2021.7), (1047.4, 2003.1), (500.0, 500.0)])
    with el.RasterDem(path) as dem:
        z = dem.sample(xy)
    np.testing.assert_allclose(z[:2], 2 * xy[:2, 0] + 3 * xy[:2, 1] + 5, rtol=1e-6)
    assert np.isnan(z[2])


def test_raster_dem_requires_lambert93(tmp_path: Path) -> None:
    path = tmp_path / "dem.tif"
    write_geotiff(path, plane_grid(), TRANSFORM, "EPSG:4326")
    with pytest.raises(ValueError, match="EPSG:2154"):
        el.RasterDem(path)


def test_bbox_to_lambert93_covers_the_pilot_area() -> None:
    assert el.bbox_to_lambert93(PILOT_BBOX_WGS84) == (576000, 6265000, 604000, 6278000)
