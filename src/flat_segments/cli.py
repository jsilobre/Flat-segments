"""Command-line interface of the offline pipeline.

``extract`` -> ``elevation`` -> ``detect`` -> ``export``; each step reads and
writes files under ``data/`` (see docs/architecture.md, section 3.1).
Parameters currently use the defaults of :mod:`flat_segments.params`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from flat_segments import __version__
from flat_segments.params import PILOT_BBOX_WGS84, PipelineParams

DEFAULT_PBF = Path("data/raw/midi-pyrenees-latest.osm.pbf")
DEFAULT_DEM = Path("data/raw/rge_alti/pilot.vrt")
DEFAULT_STROKES = Path("data/interim/strokes.parquet")
DEFAULT_PROFILES = Path("data/interim/profiles.parquet")
DEFAULT_SEGMENTS = Path("data/processed/segments.parquet")
DEFAULT_GEOJSON = Path("web/data/segments.geojson")
DEFAULT_BBOX = ",".join(str(v) for v in PILOT_BBOX_WGS84)

PbfIn = Annotated[
    Path, typer.Option(help="OSM extract (.osm.pbf or .osm).", exists=True, dir_okay=False)
]
DemIn = Annotated[
    Path, typer.Option(help="DEM raster in Lambert-93 (GeoTIFF, VRT).", exists=True, dir_okay=False)
]
StrokesIn = Annotated[Path, typer.Option(help="Strokes GeoParquet.", exists=True, dir_okay=False)]
ProfilesIn = Annotated[Path, typer.Option(help="Profiles Parquet.", exists=True, dir_okay=False)]
SegmentsIn = Annotated[Path, typer.Option(help="Segments GeoParquet.", exists=True, dir_okay=False)]
BboxOpt = Annotated[str, typer.Option(help="WGS84 bbox: min_lon,min_lat,max_lon,max_lat.")]
StrokesOut = Annotated[Path, typer.Option(help="Output strokes GeoParquet.", dir_okay=False)]
ProfilesOut = Annotated[Path, typer.Option(help="Output profiles Parquet.", dir_okay=False)]
SegmentsOut = Annotated[Path, typer.Option(help="Output segments GeoParquet.", dir_okay=False)]
GeojsonOut = Annotated[Path, typer.Option(help="Output GeoJSON (WGS84).", dir_okay=False)]

app = typer.Typer(
    help="Offline pipeline: OSM network + DEM -> flat segments and climbs for runners.",
    no_args_is_help=True,
    add_completion=False,
)


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    """Parse ``"min_lon,min_lat,max_lon,max_lat"``.

    Raises:
        typer.BadParameter: If the value is malformed or inverted.
    """
    try:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in value.split(","))
    except ValueError as error:
        raise typer.BadParameter("expected min_lon,min_lat,max_lon,max_lat") from error
    if min_lon >= max_lon or min_lat >= max_lat:
        raise typer.BadParameter("min values must be lower than max values")
    return min_lon, min_lat, max_lon, max_lat


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    """Offline pipeline: OSM network + DEM -> segments."""


@app.command()
def extract(
    pbf: PbfIn = DEFAULT_PBF,
    bbox: BboxOpt = DEFAULT_BBOX,
    out: StrokesOut = DEFAULT_STROKES,
) -> None:
    """Read OSM ways and chain them into strokes."""
    from flat_segments.export import write_strokes
    from flat_segments.network import build_strokes
    from flat_segments.osm import read_ways

    ways = read_ways(pbf, parse_bbox(bbox))
    strokes = build_strokes(ways, PipelineParams().network)
    write_strokes(strokes, out)
    typer.echo(f"{len(ways)} ways -> {len(strokes)} strokes -> {out}")


@app.command()
def elevation(
    dem: DemIn = DEFAULT_DEM,
    strokes: StrokesIn = DEFAULT_STROKES,
    out: ProfilesOut = DEFAULT_PROFILES,
    source: Annotated[str, typer.Option(help="Elevation source label.")] = "rge_alti_1m",
) -> None:
    """Sample the DEM along every stroke."""
    from flat_segments.elevation import RasterDem, sample_stroke
    from flat_segments.export import ProfileTable, read_strokes, write_profiles

    params = PipelineParams().profile
    all_strokes = read_strokes(strokes)
    with RasterDem(dem) as sampler:
        z_raw = {s.id: sample_stroke(s.coords, sampler, params) for s in all_strokes}
    write_profiles(ProfileTable(z_raw, params.step_m, source), out)
    typer.echo(f"{len(z_raw)} profiles -> {out}")


@app.command()
def detect(
    strokes: StrokesIn = DEFAULT_STROKES,
    profiles: ProfilesIn = DEFAULT_PROFILES,
    out: SegmentsOut = DEFAULT_SEGMENTS,
) -> None:
    """Detect, score and deduplicate flat segments and climbs."""
    from flat_segments.detect import SegmentKind, detect_all
    from flat_segments.export import read_profiles, read_strokes, write_segments

    params = PipelineParams()
    table = read_profiles(profiles)
    if table.z_raw and abs(table.step_m - params.profile.step_m) > 1e-9:
        raise typer.BadParameter(
            f"profiles sampled every {table.step_m} m, expected {params.profile.step_m} m"
        )
    segments = detect_all(read_strokes(strokes), table.z_raw, params, table.elevation_source)
    write_segments(segments, out)
    n_flat = sum(s.kind is SegmentKind.FLAT for s in segments)
    typer.echo(f"{n_flat} flat segments, {len(segments) - n_flat} climbs -> {out}")


@app.command()
def export(
    segments: SegmentsIn = DEFAULT_SEGMENTS,
    out: GeojsonOut = DEFAULT_GEOJSON,
    sample: Annotated[bool, typer.Option(help="Flag the data as fictitious.")] = False,
) -> None:
    """Export segments to GeoJSON for the web page."""
    from flat_segments.export import read_segments, segments_to_geojson, write_geojson

    all_segments = read_segments(segments)
    write_geojson(segments_to_geojson(all_segments, sample=sample), out)
    typer.echo(f"{len(all_segments)} segments -> {out}")
