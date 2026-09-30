"""Pipeline steps as plain functions, shared by the CLI commands.

Each step reads and writes files (docs/architecture.md, section 3.1). The
parameters used by ``detect`` are saved next to its output
(``segments.params.toml``) and embedded in the GeoJSON metadata by
``export``, so that a published dataset always says how it was produced.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flat_segments.config import params_to_toml
from flat_segments.detect import Segment, detect_all
from flat_segments.params import PipelineParams


@dataclass(frozen=True, slots=True)
class DataPaths:
    """Default file locations (``data/`` is not versioned)."""

    pbf: Path = Path("data/raw/pilot.osm.pbf")
    dem: Path = Path("data/raw/dem/pilot.vrt")
    strokes: Path = Path("data/interim/strokes.parquet")
    profiles: Path = Path("data/interim/profiles.parquet")
    segments: Path = Path("data/processed/segments.parquet")
    geojson: Path = Path("web/data/segments.geojson")


def params_sidecar(segments_path: Path) -> Path:
    """Path of the parameters file written next to a segments file."""
    return segments_path.with_suffix(".params.toml")


def run_extract(
    pbf: Path,
    bbox: tuple[float, float, float, float] | None,
    out: Path,
    params: PipelineParams,
) -> tuple[int, int]:
    """Read OSM ways and chain them into strokes.

    Returns:
        ``(number of ways, number of strokes)``.
    """
    from flat_segments.export import write_strokes
    from flat_segments.network import build_strokes
    from flat_segments.osm import read_ways

    ways = read_ways(pbf, bbox)
    strokes = build_strokes(ways, params.network)
    write_strokes(strokes, out)
    return len(ways), len(strokes)


def run_elevation(
    dem: Path,
    strokes: Path,
    out: Path,
    params: PipelineParams,
    source: str | None = None,
) -> int:
    """Sample the DEM along every stroke.

    ``source`` defaults to the one recorded in the raster (``download-dem``
    tags its tiles and VRT), else ``rge_alti_1m``.

    Returns:
        Number of profiles written.
    """
    from flat_segments.elevation import DEFAULT_SOURCE, RasterDem, raster_source, sample_stroke
    from flat_segments.export import ProfileTable, read_strokes, write_profiles

    if source is None:
        source = raster_source(dem) or DEFAULT_SOURCE
    all_strokes = read_strokes(strokes)
    with RasterDem(dem) as sampler:
        z_raw = {s.id: sample_stroke(s.coords, sampler, params.profile) for s in all_strokes}
    write_profiles(ProfileTable(z_raw, params.profile.step_m, source), out)
    return len(z_raw)


def run_detect(strokes: Path, profiles: Path, out: Path, params: PipelineParams) -> list[Segment]:
    """Detect, score and deduplicate segments; save them and the parameters used.

    Raises:
        ValueError: If the profiles were sampled with another step.
    """
    from flat_segments.export import read_profiles, read_strokes, write_segments

    table = read_profiles(profiles)
    if table.z_raw and abs(table.step_m - params.profile.step_m) > 1e-9:
        raise ValueError(
            f"profiles sampled every {table.step_m} m, expected {params.profile.step_m} m: "
            "rerun `elevation` with the same profile.step_m"
        )
    segments = detect_all(read_strokes(strokes), table.z_raw, params, table.elevation_source)
    write_segments(segments, out)
    params_sidecar(out).write_text(params_to_toml(params), encoding="utf-8")
    return segments


def run_export(segments: Path, out: Path, *, sample: bool = False) -> int:
    """Export segments to GeoJSON, with the detection parameters in the metadata.

    Returns:
        Number of exported segments.
    """
    from flat_segments.export import read_segments, segments_to_geojson, write_geojson

    all_segments = read_segments(segments)
    params: dict[str, Any] | None = None
    sidecar = params_sidecar(segments)
    if sidecar.exists():
        params = tomllib.loads(sidecar.read_text(encoding="utf-8"))
    write_geojson(segments_to_geojson(all_segments, sample=sample, params=params), out)
    return len(all_segments)


def run_all(
    paths: DataPaths,
    bbox: tuple[float, float, float, float] | None,
    params: PipelineParams,
    *,
    source: str | None = None,
    sample: bool = False,
) -> list[Segment]:
    """Run the four steps in sequence."""
    run_extract(paths.pbf, bbox, paths.strokes, params)
    run_elevation(paths.dem, paths.strokes, paths.profiles, params, source)
    segments = run_detect(paths.strokes, paths.profiles, paths.segments, params)
    run_export(paths.segments, paths.geojson, sample=sample)
    return segments
