"""Command-line interface of the offline pipeline.

``extract`` -> ``elevation`` -> ``detect`` -> ``export`` (or ``pipeline`` for
all four); each step reads and writes files under ``data/`` (see
docs/architecture.md, section 3.1). Parameters come from the defaults, an
optional ``--config`` TOML file and ``--set key=value`` overrides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from flat_segments import __version__
from flat_segments import pipeline as steps
from flat_segments.config import ConfigError, load_params, params_to_toml
from flat_segments.detect import Segment, SegmentKind
from flat_segments.params import PILOT_BBOX_WGS84, PipelineParams

PATHS = steps.DataPaths()
DEFAULT_BBOX = ",".join(str(v) for v in PILOT_BBOX_WGS84)


def _in(help_text: str) -> typer.models.OptionInfo:
    option: typer.models.OptionInfo = typer.Option(help=help_text, exists=True, dir_okay=False)
    return option


def _out(help_text: str) -> typer.models.OptionInfo:
    option: typer.models.OptionInfo = typer.Option(help=help_text, dir_okay=False)
    return option


PbfIn = Annotated[Path, _in("OSM extract (.osm.pbf or .osm).")]
DemIn = Annotated[Path, _in("DEM raster in Lambert-93 (GeoTIFF, VRT).")]
StrokesIn = Annotated[Path, _in("Strokes GeoParquet.")]
ProfilesIn = Annotated[Path, _in("Profiles Parquet.")]
SegmentsIn = Annotated[Path, _in("Segments GeoParquet.")]
StrokesOut = Annotated[Path, _out("Output strokes GeoParquet.")]
ProfilesOut = Annotated[Path, _out("Output profiles Parquet.")]
SegmentsOut = Annotated[Path, _out("Output segments GeoParquet.")]
GeojsonOut = Annotated[Path, _out("Output GeoJSON (WGS84).")]
BboxOpt = Annotated[str, typer.Option(help="WGS84 bbox: min_lon,min_lat,max_lon,max_lat.")]
SourceOpt = Annotated[str, typer.Option(help="Elevation source label.")]
SampleOpt = Annotated[bool, typer.Option(help="Flag the data as fictitious.")]
ConfigOpt = Annotated[
    Path | None,
    typer.Option("--config", help="TOML parameters file.", exists=True, dir_okay=False),
]
SetOpt = Annotated[
    list[str] | None,
    typer.Option("--set", help="Parameter override, e.g. flat.max_local_grade_pct=1.5."),
]

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


def get_params(config: Path | None, overrides: list[str] | None) -> PipelineParams:
    """Load parameters, reporting configuration errors as CLI errors.

    Raises:
        typer.BadParameter: On an invalid file or override.
    """
    try:
        return load_params(config, overrides or ())
    except ConfigError as error:
        raise typer.BadParameter(str(error)) from error


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
def config(config: ConfigOpt = None, overrides: SetOpt = None) -> None:
    """Print the effective parameters as TOML (defaults, --config, --set)."""
    typer.echo(params_to_toml(get_params(config, overrides)), nl=False)


@app.command()
def extract(
    pbf: PbfIn = PATHS.pbf,
    bbox: BboxOpt = DEFAULT_BBOX,
    out: StrokesOut = PATHS.strokes,
    config: ConfigOpt = None,
    overrides: SetOpt = None,
) -> None:
    """Read OSM ways and chain them into strokes."""
    params = get_params(config, overrides)
    n_ways, n_strokes = steps.run_extract(pbf, parse_bbox(bbox), out, params)
    typer.echo(f"{n_ways} ways -> {n_strokes} strokes -> {out}")


@app.command()
def elevation(
    dem: DemIn = PATHS.dem,
    strokes: StrokesIn = PATHS.strokes,
    out: ProfilesOut = PATHS.profiles,
    source: SourceOpt = "rge_alti_1m",
    config: ConfigOpt = None,
    overrides: SetOpt = None,
) -> None:
    """Sample the DEM along every stroke."""
    params = get_params(config, overrides)
    count = steps.run_elevation(dem, strokes, out, params, source)
    typer.echo(f"{count} profiles -> {out}")


def _report_detection(segments: list[Segment], out: Path) -> None:
    n_flat = sum(s.kind is SegmentKind.FLAT for s in segments)
    typer.echo(f"{n_flat} flat segments, {len(segments) - n_flat} climbs -> {out}")


@app.command()
def detect(
    strokes: StrokesIn = PATHS.strokes,
    profiles: ProfilesIn = PATHS.profiles,
    out: SegmentsOut = PATHS.segments,
    config: ConfigOpt = None,
    overrides: SetOpt = None,
) -> None:
    """Detect, score and deduplicate flat segments and climbs."""
    params = get_params(config, overrides)
    try:
        segments = steps.run_detect(strokes, profiles, out, params)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    _report_detection(segments, out)


@app.command()
def export(
    segments: SegmentsIn = PATHS.segments,
    out: GeojsonOut = PATHS.geojson,
    sample: SampleOpt = False,
) -> None:
    """Export segments to GeoJSON for the web page."""
    count = steps.run_export(segments, out, sample=sample)
    typer.echo(f"{count} segments -> {out}")


@app.command()
def pipeline(
    pbf: PbfIn = PATHS.pbf,
    dem: DemIn = PATHS.dem,
    bbox: BboxOpt = DEFAULT_BBOX,
    out: GeojsonOut = PATHS.geojson,
    source: SourceOpt = "rge_alti_1m",
    sample: SampleOpt = False,
    config: ConfigOpt = None,
    overrides: SetOpt = None,
) -> None:
    """Run extract, elevation, detect and export in sequence (default paths)."""
    params = get_params(config, overrides)
    paths = steps.DataPaths(pbf=pbf, dem=dem, geojson=out)
    try:
        segments = steps.run_all(paths, parse_bbox(bbox), params, source=source, sample=sample)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    _report_detection(segments, paths.segments)
    typer.echo(f"GeoJSON -> {out}")
