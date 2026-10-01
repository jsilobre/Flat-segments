"""Export of the segments as vector tiles in a PMTiles archive (ADR 0009).

The web page reads three things next to each other (``web/data/``):

* ``segments.pmtiles``: two layers.
  * ``segments``: every segment with all its public properties, zooms 12 to
    14. The page builds its result list from the zoom 12 tiles, so nothing
    may be dropped there.
  * ``overview``: a lighter view for zooms 8 to 11, with only ``id``,
    ``kind`` and ``length_m``, thinned out by tippecanoe where too dense.
* ``segments.json``: what the GeoJSON ``metadata`` member used to hold
  (attribution, date, parameters), plus the bounds and counts of the set.
* ``ids/XX.json``: where each segment is, for links holding only an ``id``.
  The ids are spread over 256 small files by the first two hexadecimal
  characters of their hash part.

Vector tiles have no list nor null values: lists (``highways``…) are written
as JSON strings, and null properties (``name``…) are left out.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np

from flat_segments.detect import Segment, SegmentKind
from flat_segments.export import (
    COORD_DECIMALS,
    SCHEMA_VERSION,
    attribution_for,
    segment_properties,
)
from flat_segments.geometry import Projector, make_projector
from flat_segments.params import WEB_CRS, WORK_CRS

DETAIL_LAYER: Final = "segments"
OVERVIEW_LAYER: Final = "overview"
DETAIL_ZOOMS: Final = (12, 14)
OVERVIEW_ZOOMS: Final = (8, 11)
OVERVIEW_FIELDS: Final = ("id", "kind", "length_m")
#: Number of hexadecimal characters of the id hash naming its index file.
INDEX_PREFIX_LENGTH: Final = 2


class TippecanoeError(RuntimeError):
    """tippecanoe is missing or failed."""


@dataclass(frozen=True)
class TilesetFiles:
    """Files written by :func:`write_tileset`."""

    pmtiles: Path
    metadata: Path
    index_dir: Path


def tippecanoe_available() -> bool:
    """Whether ``tippecanoe`` and ``tile-join`` are on the PATH."""
    return shutil.which("tippecanoe") is not None and shutil.which("tile-join") is not None


def tile_properties(segment: Segment) -> dict[str, Any]:
    """Public properties for a vector tile: lists as JSON, no nulls."""
    props = {}
    for name, value in segment_properties(segment).items():
        if value is None:
            continue
        props[name] = json.dumps(value, separators=(",", ":")) if isinstance(value, list) else value
    return props


def index_key(segment_id: str) -> str:
    """Name (without extension) of the index file holding ``segment_id``."""
    return segment_id.split("-")[1][:INDEX_PREFIX_LENGTH]


def _write_features(
    segments: Sequence[Segment], path: Path, to_wgs84: Projector, fields: Sequence[str] | None
) -> None:
    """Newline-delimited GeoJSON features (tippecanoe reads them in parallel)."""
    with path.open("w", encoding="utf-8") as handle:
        for segment in segments:
            props = tile_properties(segment)
            if fields is not None:
                props = {k: v for k, v in props.items() if k in fields}
            coords = np.round(to_wgs84(segment.coords), COORD_DECIMALS).tolist()
            feature = {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": props,
            }
            handle.write(json.dumps(feature, ensure_ascii=False, separators=(",", ":")) + "\n")


def _run(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise TippecanoeError(f"{args[0]} not found: install tippecanoe (ADR 0009)") from error
    except subprocess.CalledProcessError as error:
        raise TippecanoeError(f"{args[0]} failed: {error.stderr.strip()[-500:]}") from error


def write_pmtiles(
    segments: Sequence[Segment],
    path: Path,
    attribution: Sequence[str],
    to_wgs84: Projector | None = None,
) -> Path:
    """Write the two-layer PMTiles archive with tippecanoe and tile-join.

    Raises:
        TippecanoeError: If the tools are missing or fail.
    """
    to_wgs84 = to_wgs84 or make_projector(WORK_CRS, WEB_CRS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="flat-segments-tiles-") as tmp:
        work = Path(tmp)
        detail_in, overview_in = work / "detail.geojsonl", work / "overview.geojsonl"
        _write_features(segments, detail_in, to_wgs84, None)
        _write_features(segments, overview_in, to_wgs84, OVERVIEW_FIELDS)
        detail, overview = work / "detail.pmtiles", work / "overview.pmtiles"
        common = ["tippecanoe", "--quiet", "--force", "--read-parallel"]
        _run(
            [
                *common,
                f"--output={detail}",
                f"--layer={DETAIL_LAYER}",
                f"--minimum-zoom={DETAIL_ZOOMS[0]}",
                f"--maximum-zoom={DETAIL_ZOOMS[1]}",
                "--no-feature-limit",
                "--no-tile-size-limit",
                str(detail_in),
            ]
        )
        _run(
            [
                *common,
                f"--output={overview}",
                f"--layer={OVERVIEW_LAYER}",
                f"--minimum-zoom={OVERVIEW_ZOOMS[0]}",
                f"--maximum-zoom={OVERVIEW_ZOOMS[1]}",
                "--drop-densest-as-needed",
                str(overview_in),
            ]
        )
        _run(
            [
                "tile-join",
                "--quiet",
                "--force",
                "--no-tile-size-limit",
                f"--output={path}",
                "--name=flat-segments",
                f"--attribution={' ; '.join(attribution)}",
                str(detail),
                str(overview),
            ]
        )
    return path


def write_id_index(
    segments: Sequence[Segment], directory: Path, to_wgs84: Projector | None = None
) -> int:
    """Write ``directory/XX.json``: id -> ``[lon, lat]`` of the segment midpoint.

    Older files are removed first. Returns the number of files written.
    """
    to_wgs84 = to_wgs84 or make_projector(WORK_CRS, WEB_CRS)
    shards: dict[str, dict[str, list[float]]] = defaultdict(dict)
    for segment in segments:
        mid = to_wgs84(segment.coords[len(segment.coords) // 2][None, :])[0]
        shards[index_key(segment.id)][segment.id] = [round(float(v), 5) for v in mid]
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    for key, entries in shards.items():
        text = json.dumps(dict(sorted(entries.items())), separators=(",", ":"))
        (directory / f"{key}.json").write_text(text + "\n", encoding="utf-8")
    return len(shards)


def tileset_metadata(
    segments: Sequence[Segment],
    *,
    sample: bool = False,
    generated_at: datetime | None = None,
    attribution: Sequence[str] | None = None,
    params: Mapping[str, Any] | None = None,
    to_wgs84: Projector | None = None,
) -> dict[str, Any]:
    """Content of ``segments.json`` (see docs/data-model.md)."""
    to_wgs84 = to_wgs84 or make_projector(WORK_CRS, WEB_CRS)
    bounds = None
    if segments:
        lonlat = to_wgs84(np.vstack([s.coords for s in segments]))
        bounds = [round(float(v), 5) for v in (*lonlat.min(axis=0), *lonlat.max(axis=0))]
    generated_at = generated_at or datetime.now(UTC)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample": sample,
        "attribution": list(attribution if attribution is not None else attribution_for(segments)),
        "bounds": bounds,
        "counts": {kind.value: sum(s.kind is kind for s in segments) for kind in SegmentKind},
        "tiles": {
            "url": "segments.pmtiles",
            "layer": DETAIL_LAYER,
            "minzoom": DETAIL_ZOOMS[0],
            "maxzoom": DETAIL_ZOOMS[1],
            "overview_layer": OVERVIEW_LAYER,
            "overview_minzoom": OVERVIEW_ZOOMS[0],
            "index": "ids",
            "index_prefix_length": INDEX_PREFIX_LENGTH,
        },
        **({"params": dict(params)} if params is not None else {}),
    }


def write_tileset(
    segments: Sequence[Segment],
    directory: Path,
    *,
    sample: bool = False,
    generated_at: datetime | None = None,
    attribution: Sequence[str] | None = None,
    params: Mapping[str, Any] | None = None,
) -> TilesetFiles:
    """Write ``segments.pmtiles``, ``segments.json`` and ``ids/`` in ``directory``.

    Raises:
        TippecanoeError: If the tools are missing or fail.
    """
    to_wgs84 = make_projector(WORK_CRS, WEB_CRS)
    metadata = tileset_metadata(
        segments,
        sample=sample,
        generated_at=generated_at,
        attribution=attribution,
        params=params,
        to_wgs84=to_wgs84,
    )
    files = TilesetFiles(
        directory / "segments.pmtiles", directory / "segments.json", directory / "ids"
    )
    write_pmtiles(segments, files.pmtiles, metadata["attribution"], to_wgs84)
    write_id_index(segments, files.index_dir, to_wgs84)
    files.metadata.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return files
