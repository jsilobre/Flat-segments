"""Download of the source data (docs/data-sources.md).

* OSM: the Geofabrik regional extract, checked against its ``.md5`` file.
* DEM: elevation tiles extracted over a bbox from the Géoplateforme WMS
  (raw 32-bit BIL), saved as GeoTIFF tiles and assembled into a GDAL VRT.
  The default layer is the LiDAR HD terrain model (docs/adr/0007).

Network access goes through an injectable ``opener`` so that everything can
be tested offline.
"""

from __future__ import annotations

import hashlib
import http.client
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Collection
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Final, cast
from urllib.parse import urlencode
from xml.sax.saxutils import escape

import numpy as np

from flat_segments import __version__
from flat_segments.elevation import SOURCE_TAG, raster_source
from flat_segments.geometry import FloatArray
from flat_segments.params import WORK_CRS

USER_AGENT: Final = f"flat-segments/{__version__} (+https://github.com/jsilobre/Flat-segments)"
GEOFABRIK_URL: Final = "https://download.geofabrik.de/europe/france/midi-pyrenees-latest.osm.pbf"

# Géoplateforme WMS raster service, checked against GetCapabilities
# (2026-09-30): MaxWidth = MaxHeight = 5010 px, BIL payloads are little-endian.
WMS_URL: Final = "https://data.geopf.fr/wms-r/wms"
# LiDAR HD terrain model, stored natively in Lambert-93 (0.5 m).
WMS_LAYER_LIDAR_HD: Final = "IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93"
# RGE ALTI, stored in geographic coordinates and resampled by the server:
# its effective resolution in Lambert-93 is about 3.5 m x 4.7 m, not 1 m.
WMS_LAYER_RGE_ALTI: Final = "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES"
WMS_LAYER: Final = WMS_LAYER_LIDAR_HD
WMS_FORMAT: Final = "image/x-bil;bits=32"
# Value of ``elevation_source`` for each known layer (docs/data-model.md).
LAYER_SOURCES: Final = {WMS_LAYER_LIDAR_HD: "lidar_hd", WMS_LAYER_RGE_ALTI: "rge_alti_wms"}
DEM_NODATA: Final = -99999.0
# Some Géoplateforme backends intermittently answer "400 LayerNotDefined" for
# a layer that exists; the same request succeeds when retried.
WMS_TRANSIENT_CODES: Final = frozenset({400})
# The service marks nodata with -9999 (LiDAR HD) or -99999 (RGE ALTI): any
# value below this threshold is nodata.
WMS_NODATA_BELOW: Final = -1000.0

CHUNK_SIZE: Final = 1 << 20

Opener = Callable[[str], AbstractContextManager[IO[bytes]]]


class DownloadError(RuntimeError):
    """A download failed or returned unexpected content."""


def urlopen(url: str) -> AbstractContextManager[IO[bytes]]:
    """Open a URL with the project's User-Agent (default opener)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return cast(AbstractContextManager[IO[bytes]], urllib.request.urlopen(request, timeout=120))


def fetch_bytes(
    url: str,
    opener: Opener = urlopen,
    *,
    retries: int = 3,
    transient_codes: Collection[int] = (),
    sleep: Callable[[float], Any] = time.sleep,
) -> bytes:
    """Read a whole (small) resource, retrying transient network errors.

    HTTP 5xx and ``transient_codes`` are retried, other HTTP errors are not.

    Raises:
        DownloadError: After ``retries`` failed attempts, or on another HTTP error.
    """
    for attempt in range(1, retries + 1):
        try:
            with opener(url) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            transient = error.code >= 500 or error.code in transient_codes
            if not transient or attempt == retries:
                raise DownloadError(f"{url}: HTTP {error.code} {_error_body(error)}") from error
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            TimeoutError,
            ConnectionError,
        ) as error:
            if attempt == retries:
                raise DownloadError(f"{url}: {error}") from error
        sleep(2.0**attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def _error_body(error: urllib.error.HTTPError) -> str:
    """Start of an HTTP error body (a WMS ServiceException, typically)."""
    try:
        return error.read(300).decode("utf-8", errors="replace")
    except Exception:  # diagnostic only: never mask the HTTP error
        return ""


def md5_of(path: Path) -> str:
    """MD5 hex digest of a file."""
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(
    url: str, dest: Path, opener: Opener = urlopen, *, expected_md5: str | None = None
) -> Path:
    """Stream ``url`` to ``dest`` through a ``.part`` file, checking the MD5.

    Raises:
        DownloadError: If the checksum does not match (the partial file is removed).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.md5(usedforsecurity=False)
    with opener(url) as response, part.open("wb") as handle:
        while chunk := response.read(CHUNK_SIZE):
            handle.write(chunk)
            digest.update(chunk)
    if expected_md5 is not None and digest.hexdigest() != expected_md5:
        part.unlink()
        raise DownloadError(f"{url}: MD5 mismatch ({digest.hexdigest()} != {expected_md5})")
    part.replace(dest)
    return dest


def download_osm(
    out_dir: Path, url: str = GEOFABRIK_URL, opener: Opener = urlopen, *, force: bool = False
) -> Path:
    """Download a Geofabrik extract unless an identical copy is already there.

    Returns:
        Path of the ``.osm.pbf`` file.
    """
    checksum = fetch_bytes(f"{url}.md5", opener).decode("ascii").split()[0].lower()
    dest = out_dir / url.rsplit("/", 1)[-1]
    if dest.exists() and not force and md5_of(dest) == checksum:
        return dest
    return download_file(url, dest, opener, expected_md5=checksum)


# --- DEM --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DemTile:
    """One WMS request: a Lambert-93 box and its size in pixels."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float
    width: int
    height: int

    @property
    def name(self) -> str:
        """File name of the tile (south-west corner in metres)."""
        return f"{self.min_x:.0f}_{self.min_y:.0f}.tif"


def dem_tiles(
    bounds: tuple[float, float, float, float], tile_size_m: float, resolution_m: float
) -> list[DemTile]:
    """Split Lambert-93 ``bounds`` into tiles of at most ``tile_size_m``.

    Raises:
        ValueError: If sizes are not positive or not multiples of the resolution.
    """
    if tile_size_m <= 0 or resolution_m <= 0:
        raise ValueError("tile size and resolution must be positive")
    if not math.isclose(tile_size_m / resolution_m, round(tile_size_m / resolution_m)):
        raise ValueError("tile size must be a multiple of the resolution")
    min_x, min_y, max_x, max_y = bounds
    tiles = []
    y = min_y
    while y < max_y - 1e-6:
        top = min(y + tile_size_m, max_y)
        x = min_x
        while x < max_x - 1e-6:
            right = min(x + tile_size_m, max_x)
            width = round((right - x) / resolution_m)
            height = round((top - y) / resolution_m)
            tiles.append(DemTile(x, y, right, top, width, height))
            x = right
        y = top
    return tiles


def wms_getmap_url(
    tile: DemTile, *, base_url: str = WMS_URL, layer: str = WMS_LAYER, fmt: str = WMS_FORMAT
) -> str:
    """WMS 1.3.0 GetMap URL for a Lambert-93 tile (x, y axis order)."""
    query = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "CRS": WORK_CRS,
        "BBOX": f"{tile.min_x},{tile.min_y},{tile.max_x},{tile.max_y}",
        "WIDTH": tile.width,
        "HEIGHT": tile.height,
        "FORMAT": fmt,
    }
    return f"{base_url}?{urlencode(query)}"


def source_for_layer(layer: str) -> str:
    """``elevation_source`` label of a WMS layer (``"unknown"`` if not known)."""
    return LAYER_SOURCES.get(layer, "unknown")


def decode_bil(data: bytes, width: int, height: int, byteorder: str = "<") -> FloatArray:
    """Decode a raw 32-bit float BIL image (row-major, north up).

    The service's nodata values (and non-finite values) become ``DEM_NODATA``.

    Raises:
        DownloadError: If the payload is not an image of the expected size
            (typically an XML service exception).
    """
    expected = width * height * 4
    if len(data) != expected:
        head = data[:300].decode("utf-8", errors="replace")
        raise DownloadError(f"expected {expected} bytes of BIL, got {len(data)}: {head!r}")
    values = np.frombuffer(data, dtype=np.dtype(f"{byteorder}f4")).reshape(height, width)
    values = values.astype(np.float64)
    values[~np.isfinite(values) | (values < WMS_NODATA_BELOW)] = DEM_NODATA
    return values


def write_tile(
    path: Path,
    values: FloatArray,
    tile: DemTile,
    nodata: float = DEM_NODATA,
    source: str | None = None,
) -> None:
    """Write a tile as a compressed Lambert-93 GeoTIFF, tagged with its source."""
    import rasterio
    from rasterio.transform import from_bounds

    path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_bounds(tile.min_x, tile.min_y, tile.max_x, tile.max_y, tile.width, tile.height)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=tile.width,
        height=tile.height,
        count=1,
        dtype="float32",
        crs=WORK_CRS,
        transform=transform,
        nodata=nodata,
        compress="deflate",
        predictor=3,
        tiled=True,
    ) as dst:
        dst.write(values.astype(np.float32), 1)
        if source is not None:
            dst.update_tags(**{SOURCE_TAG: source})


def build_vrt(tiles: list[Path], vrt_path: Path, source: str | None = None) -> Path:
    """Assemble same-resolution Lambert-93 GeoTIFF tiles into a GDAL VRT.

    Source paths are written relative to the VRT, so the folder can be moved.
    ``source`` is recorded as the ``ELEVATION_SOURCE`` metadata item.

    Raises:
        ValueError: If there is no tile or tiles do not share resolution / CRS.
    """
    import rasterio

    if not tiles:
        raise ValueError("no tile to assemble")
    infos = []
    for path in tiles:
        with rasterio.open(path) as ds:
            infos.append((path, ds.bounds, ds.res, ds.width, ds.height, ds.crs, ds.nodata))
    res_x, res_y = infos[0][2]
    crs = infos[0][5]
    if any(not np.allclose(info[2], (res_x, res_y)) or info[5] != crs for info in infos):
        raise ValueError("tiles must share the same resolution and CRS")
    min_x = min(info[1].left for info in infos)
    max_x = max(info[1].right for info in infos)
    min_y = min(info[1].bottom for info in infos)
    max_y = max(info[1].top for info in infos)
    width, height = round((max_x - min_x) / res_x), round((max_y - min_y) / res_y)
    nodata = infos[0][6]
    sources = []
    for path, bounds, _, w, h, _, _ in infos:
        x_off = round((bounds.left - min_x) / res_x)
        y_off = round((max_y - bounds.top) / res_y)
        relative = path.resolve().relative_to(vrt_path.parent.resolve()).as_posix()
        sources.append(
            "    <SimpleSource>\n"
            f'      <SourceFilename relativeToVRT="1">{escape(relative)}</SourceFilename>\n'
            "      <SourceBand>1</SourceBand>\n"
            f'      <SrcRect xOff="0" yOff="0" xSize="{w}" ySize="{h}"/>\n'
            f'      <DstRect xOff="{x_off}" yOff="{y_off}" xSize="{w}" ySize="{h}"/>\n'
            "    </SimpleSource>\n"
        )
    nodata_xml = f"    <NoDataValue>{nodata}</NoDataValue>\n" if nodata is not None else ""
    metadata_xml = (
        f'  <Metadata>\n    <MDI key="{SOURCE_TAG}">{escape(source)}</MDI>\n  </Metadata>\n'
        if source is not None
        else ""
    )
    vrt = (
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">\n'
        f"  <SRS>{escape(crs.to_wkt())}</SRS>\n"
        f"{metadata_xml}"
        f"  <GeoTransform>{min_x}, {res_x}, 0, {max_y}, 0, {-res_y}</GeoTransform>\n"
        '  <VRTRasterBand dataType="Float32" band="1">\n'
        f"{nodata_xml}{''.join(sources)}"
        "  </VRTRasterBand>\n"
        "</VRTDataset>\n"
    )
    vrt_path.parent.mkdir(parents=True, exist_ok=True)
    vrt_path.write_text(vrt, encoding="utf-8")
    return vrt_path


def download_dem(
    bounds: tuple[float, float, float, float],
    out_dir: Path,
    opener: Opener = urlopen,
    *,
    tile_size_m: float = 2000.0,
    resolution_m: float = 1.0,
    base_url: str = WMS_URL,
    layer: str = WMS_LAYER,
    vrt_name: str = "pilot.vrt",
    force: bool = False,
    retries: int = 6,
    on_tile: Callable[[int, int, DemTile], None] | None = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> Path:
    """Download DEM tiles over Lambert-93 ``bounds`` and assemble them in a VRT.

    Tiles already on disk from the same layer are kept (the download can be
    resumed) unless ``force`` is set. Tiles and VRT are tagged with the
    layer's ``elevation_source``.

    Returns:
        Path of the VRT (``out_dir / vrt_name``), tiles being in ``out_dir/tiles``.
    """
    source = source_for_layer(layer)
    tiles = dem_tiles(bounds, tile_size_m, resolution_m)
    paths = []
    for index, tile in enumerate(tiles, start=1):
        path = out_dir / "tiles" / tile.name
        if force or not path.exists() or raster_source(path) != source:
            url = wms_getmap_url(tile, base_url=base_url, layer=layer)
            data = fetch_bytes(
                url, opener, retries=retries, transient_codes=WMS_TRANSIENT_CODES, sleep=sleep
            )
            write_tile(path, decode_bil(data, tile.width, tile.height), tile, source=source)
        paths.append(path)
        if on_tile is not None:
            on_tile(index, len(tiles), tile)
    return build_vrt(paths, out_dir / vrt_name, source)
