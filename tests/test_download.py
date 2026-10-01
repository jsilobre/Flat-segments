import hashlib
import http.client
import io
import urllib.error
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest

from flat_segments import download as dl
from flat_segments.elevation import RasterDem, raster_source


class FakeWeb:
    """Serves bytes (or raises) per URL and records the requests."""

    def __init__(self, routes: dict[str, bytes | Callable[[str], bytes]]) -> None:
        self.routes = routes
        self.requests: list[str] = []
        self.failures: dict[str, list[Exception]] = {}

    @contextmanager
    def __call__(self, url: str) -> Iterator[IO[bytes]]:
        self.requests.append(url)
        if self.failures.get(url):
            raise self.failures[url].pop(0)
        key = next((k for k in self.routes if url.startswith(k)), None)
        if key is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        route = self.routes[key]
        yield io.BytesIO(route(url) if callable(route) else route)


def no_sleep(_: float) -> None:
    pass


PBF = b"fake pbf content" * 1000
MD5 = hashlib.md5(PBF, usedforsecurity=False).hexdigest()
URL = "https://example.org/area-latest.osm.pbf"


def test_download_osm_checks_md5_and_skips_identical_copy(tmp_path: Path) -> None:
    web = FakeWeb({f"{URL}.md5": f"{MD5}  area-latest.osm.pbf\n".encode(), URL: PBF})
    path = dl.download_osm(tmp_path, URL, web)
    assert path == tmp_path / "area-latest.osm.pbf"
    assert path.read_bytes() == PBF
    assert web.requests == [f"{URL}.md5", URL]
    dl.download_osm(tmp_path, URL, web)
    assert web.requests[2:] == [f"{URL}.md5"]  # already there: only the checksum is fetched


def test_download_file_rejects_corrupted_content(tmp_path: Path) -> None:
    web = FakeWeb({URL: b"truncated"})
    with pytest.raises(dl.DownloadError, match="MD5 mismatch"):
        dl.download_file(URL, tmp_path / "x.pbf", web, expected_md5=MD5)
    assert list(tmp_path.iterdir()) == []


def test_fetch_bytes_retries_server_errors_but_not_client_errors() -> None:
    web = FakeWeb({URL: b"ok"})
    web.failures[URL] = [
        urllib.error.HTTPError(URL, 503, "busy", {}, None),  # type: ignore[arg-type]
        urllib.error.URLError("reset"),
    ]
    assert dl.fetch_bytes(URL, web, sleep=no_sleep) == b"ok"
    assert len(web.requests) == 3
    with pytest.raises(dl.DownloadError, match="HTTP 404"):
        dl.fetch_bytes("https://example.org/missing", web, sleep=no_sleep)


def test_fetch_bytes_retries_transient_client_errors() -> None:
    body = io.BytesIO(b"<ServiceException code='LayerNotDefined'/>")
    web = FakeWeb({URL: b"ok"})
    web.failures[URL] = [urllib.error.HTTPError(URL, 400, "Bad Request", {}, body)]  # type: ignore[arg-type]
    assert dl.fetch_bytes(URL, web, transient_codes={400}, sleep=no_sleep) == b"ok"
    web.failures[URL] = [urllib.error.HTTPError(URL, 400, "Bad Request", {}, body)]  # type: ignore[arg-type]
    with pytest.raises(dl.DownloadError, match="HTTP 400"):
        dl.fetch_bytes(URL, web, sleep=no_sleep)


def test_fetch_bytes_retries_dropped_connections() -> None:
    web = FakeWeb({URL: b"ok"})
    web.failures[URL] = [
        ConnectionResetError(104, "Connection reset by peer"),
        http.client.RemoteDisconnected("closed"),
        http.client.IncompleteRead(b"par"),
    ]
    assert dl.fetch_bytes(URL, web, retries=4, sleep=no_sleep) == b"ok"
    assert len(web.requests) == 4


def test_dem_tiles_cover_the_bounds() -> None:
    tiles = dl.dem_tiles((0, 0, 5000, 3000), 2000, 1.0)
    assert len(tiles) == 6
    assert (tiles[2].min_x, tiles[2].max_x, tiles[2].width) == (4000, 5000, 1000)
    assert (tiles[-1].max_y, tiles[-1].height) == (3000, 1000)
    assert tiles[0].name == "0_0.tif"
    with pytest.raises(ValueError, match="multiple"):
        dl.dem_tiles((0, 0, 10, 10), 2.5, 1.0)


def test_wms_url() -> None:
    [tile] = dl.dem_tiles((1000, 2000, 1400, 2300), 1000, 5.0)
    query = parse_qs(urlsplit(dl.wms_getmap_url(tile)).query)
    assert query["BBOX"] == ["1000,2000,1400,2300"]
    assert (query["WIDTH"], query["HEIGHT"]) == (["80"], ["60"])
    assert query["CRS"] == ["EPSG:2154"]
    assert query["FORMAT"] == [dl.WMS_FORMAT]


def test_decode_bil_reports_service_exceptions() -> None:
    values = np.arange(6, dtype="<f4").reshape(2, 3)
    np.testing.assert_array_equal(dl.decode_bil(values.tobytes(), 3, 2), values)
    with pytest.raises(dl.DownloadError, match="ServiceException"):
        dl.decode_bil(b"<?xml version='1.0'?><ServiceException>bad layer</ServiceException>", 3, 2)


def test_decode_bil_maps_service_nodata() -> None:
    # LiDAR HD answers -9999 outside its coverage, RGE ALTI -99999.
    raw = np.array([[152.5, -9999.0, -99999.0, np.nan, -5.0]], dtype="<f4")
    values = dl.decode_bil(raw.tobytes(), 5, 1)
    np.testing.assert_array_equal(values, [[152.5, *[dl.DEM_NODATA] * 3, -5.0]])


def test_known_layers_have_a_source_label() -> None:
    assert dl.WMS_LAYER == dl.WMS_LAYER_LIDAR_HD
    assert dl.source_for_layer(dl.WMS_LAYER_LIDAR_HD) == "lidar_hd"
    assert dl.source_for_layer(dl.WMS_LAYER_RGE_ALTI) == "rge_alti_wms"
    assert dl.source_for_layer("OTHER") == "unknown"


def plane(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 0.02 * x + 0.03 * y + 5.0


def fake_wms(url: str) -> bytes:
    """Answer a GetMap request with the plane z = 0.02 x + 0.03 y + 5."""
    query = parse_qs(urlsplit(url).query)
    min_x, min_y, max_x, max_y = (float(v) for v in query["BBOX"][0].split(","))
    width, height = int(query["WIDTH"][0]), int(query["HEIGHT"][0])
    res_x, res_y = (max_x - min_x) / width, (max_y - min_y) / height
    xs = min_x + res_x * (np.arange(width) + 0.5)
    ys = max_y - res_y * (np.arange(height) + 0.5)
    grid_x, grid_y = np.meshgrid(xs, ys)
    return plane(grid_x, grid_y).astype("<f4").tobytes()


def test_download_dem_builds_a_seamless_vrt_and_resumes(tmp_path: Path) -> None:
    web = FakeWeb({dl.WMS_URL: fake_wms})
    bounds = (1000.0, 2000.0, 1500.0, 2300.0)
    seen: list[int] = []
    vrt = dl.download_dem(
        bounds,
        tmp_path,
        web,
        tile_size_m=200,
        resolution_m=5,
        on_tile=lambda i, n, t: seen.append(i),
    )
    assert vrt == tmp_path / "pilot.vrt"
    assert seen == list(range(1, 7))  # 3 columns x 2 rows, last ones partial
    rng = np.random.default_rng(1)
    xy = np.column_stack((rng.uniform(1010, 1490, 200), rng.uniform(2010, 2290, 200)))
    with RasterDem(vrt) as dem:
        np.testing.assert_allclose(dem.sample(xy), plane(xy[:, 0], xy[:, 1]), rtol=1e-6)
    requests = len(web.requests)
    dl.download_dem(bounds, tmp_path, web, tile_size_m=200, resolution_m=5)
    assert len(web.requests) == requests  # tiles already on disk
    assert raster_source(vrt) == "lidar_hd"
    assert raster_source(tmp_path / "tiles" / "1000_2000.tif") == "lidar_hd"


def test_download_dem_replaces_tiles_from_another_layer(tmp_path: Path) -> None:
    web = FakeWeb({dl.WMS_URL: fake_wms})
    bounds = (1000.0, 2000.0, 1200.0, 2200.0)
    dl.download_dem(bounds, tmp_path, web, tile_size_m=200, resolution_m=5)
    vrt = dl.download_dem(
        bounds, tmp_path, web, tile_size_m=200, resolution_m=5, layer=dl.WMS_LAYER_RGE_ALTI
    )
    assert len(web.requests) == 2  # the LiDAR HD tile is not reused
    assert "LAYERS=ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES" in web.requests[1]
    assert raster_source(vrt) == "rge_alti_wms"


def test_download_dem_replaces_tiles_from_another_grid(tmp_path: Path) -> None:
    web = FakeWeb({dl.WMS_URL: fake_wms})
    bounds = (1000.0, 2000.0, 1400.0, 2400.0)
    dl.download_dem(bounds, tmp_path, web, tile_size_m=200, resolution_m=5)
    assert len(web.requests) == 4
    # Same south-west corner (same file name) for the first tile, other size.
    vrt = dl.download_dem(bounds, tmp_path, web, tile_size_m=400, resolution_m=10)
    assert len(web.requests) == 5
    with RasterDem(vrt) as dem:
        xy = np.array([[1350.0, 2350.0], [1010.0, 2010.0]])
        np.testing.assert_allclose(dem.sample(xy), plane(xy[:, 0], xy[:, 1]), rtol=1e-6)


def test_download_dem_only_fetches_tiles_touching_the_area(tmp_path: Path) -> None:
    from shapely.geometry import box

    web = FakeWeb({dl.WMS_URL: fake_wms})
    bounds = (1000.0, 2000.0, 1600.0, 2200.0)  # three 200 m tiles in a row
    area = box(1050.0, 2050.0, 1150.0, 2150.0).union(box(1450.0, 2050.0, 1550.0, 2150.0))
    vrt = dl.download_dem(bounds, tmp_path, web, tile_size_m=200, resolution_m=5, area=area)
    assert len(web.requests) == 2  # the middle tile is skipped
    with RasterDem(vrt) as dem:
        z = dem.sample(np.array([[1100.0, 2100.0], [1300.0, 2100.0], [1500.0, 2100.0]]))
    assert z[0] == pytest.approx(plane(np.array(1100.0), np.array(2100.0)))
    assert np.isnan(z[1])  # gap between the tiles: nodata
    assert z[2] == pytest.approx(plane(np.array(1500.0), np.array(2100.0)))


def test_download_dem_in_parallel_reports_every_tile_and_replaces_broken_ones(
    tmp_path: Path,
) -> None:
    web = FakeWeb({dl.WMS_URL: fake_wms})
    bounds = (1000.0, 2000.0, 1800.0, 2400.0)  # 4 x 2 tiles of 200 m
    seen: list[tuple[int, int]] = []
    dl.download_dem(
        bounds,
        tmp_path,
        web,
        tile_size_m=200,
        resolution_m=5,
        workers=3,
        on_tile=lambda i, n, t: seen.append((i, n)),
    )
    assert seen == [(i, 8) for i in range(1, 9)]
    assert len(web.requests) == 8
    assert not list((tmp_path / "tiles").glob("*.part"))
    (tmp_path / "tiles" / "1000_2000.tif").write_bytes(b"truncated")
    vrt = dl.download_dem(bounds, tmp_path, web, tile_size_m=200, resolution_m=5)
    assert len(web.requests) == 9  # only the broken tile
    with RasterDem(vrt) as dem:
        assert dem.sample(np.array([[1100.0, 2100.0]]))[0] == pytest.approx(
            plane(np.array(1100.0), np.array(2100.0))
        )


def test_download_dem_stops_at_the_first_failure(tmp_path: Path) -> None:
    web = FakeWeb({})  # every request fails with HTTP 404
    with pytest.raises(dl.DownloadError, match="404"):
        dl.download_dem(
            (0.0, 0.0, 800.0, 400.0), tmp_path, web, tile_size_m=200, resolution_m=5, workers=2
        )


def test_snap_bounds_to_the_tile_grid() -> None:
    assert dl.snap_bounds((576_100.0, 6_265_000.0, 603_900.0, 6_277_999.0), 4000) == (
        576_000.0,
        6_264_000.0,
        604_000.0,
        6_280_000.0,
    )


def test_default_grid_is_2_m_in_4_km_tiles() -> None:
    [tile, *_] = dl.dem_tiles((0, 0, 8000, 4000), dl.DEM_TILE_SIZE_M, dl.DEM_RESOLUTION_M)
    assert (tile.max_x - tile.min_x, tile.width, tile.height) == (4000, 2000, 2000)


def test_build_vrt_needs_tiles(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no tile"):
        dl.build_vrt([], tmp_path / "x.vrt")
