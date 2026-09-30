import json
from pathlib import Path

import numpy as np
import pytest
import typer
from typer.testing import CliRunner

from flat_segments import cli
from flat_segments.elevation import bbox_to_lambert93
from tests.test_elevation import write_geotiff

runner = CliRunner()

# A 1.2 km cycleway at Labège, crossed at its west end by a tertiary road.
LONS = np.linspace(1.530, 1.545, 13)
NODES = "\n".join(
    f'<node id="{i + 1}" lat="43.5300" lon="{lon:.5f}" version="1"/>' for i, lon in enumerate(LONS)
)
OSM = f"""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
{NODES}
  <node id="100" lat="43.5290" lon="1.53000" version="1"/>
  <node id="101" lat="43.5310" lon="1.53000" version="1"/>
  <way id="1" version="1">
    {"".join(f'<nd ref="{i + 1}"/>' for i in range(len(LONS)))}
    <tag k="highway" v="cycleway"/><tag k="surface" v="asphalt"/><tag k="name" v="Voie verte"/>
  </way>
  <way id="2" version="1">
    <nd ref="100"/><nd ref="1"/><nd ref="101"/><tag k="highway" v="tertiary"/>
  </way>
</osm>
"""
BBOX = "1.52,43.52,1.55,43.54"


def test_parse_bbox() -> None:
    assert cli.parse_bbox("1,2,3,4") == (1, 2, 3, 4)
    with pytest.raises(typer.BadParameter):
        cli.parse_bbox("1,2,3")
    with pytest.raises(typer.BadParameter):
        cli.parse_bbox("3,2,1,4")


def test_full_pipeline_on_synthetic_files(tmp_path: Path) -> None:
    pbf = tmp_path / "area.osm"
    pbf.write_text(OSM)
    min_x, min_y, max_x, max_y = bbox_to_lambert93(cli.parse_bbox(BBOX), round_to_m=100)
    cols, rows = int((max_x - min_x) / 5), int((max_y - min_y) / 5)
    x = min_x + 5 * (np.arange(cols) + 0.5)
    values = np.tile(150 + 0.004 * (x - min_x), (rows, 1))  # gentle 0.4 % slope
    dem = tmp_path / "dem.tif"
    write_geotiff(dem, values, (5.0, 0.0, min_x, 0.0, -5.0, max_y), "EPSG:2154")
    strokes, profiles = tmp_path / "strokes.parquet", tmp_path / "profiles.parquet"
    segments, geojson = tmp_path / "segments.parquet", tmp_path / "segments.geojson"

    steps = [
        ["extract", "--pbf", str(pbf), "--bbox", BBOX, "--out", str(strokes)],
        ["elevation", "--dem", str(dem), "--strokes", str(strokes), "--out", str(profiles)],
        ["detect", "--strokes", str(strokes), "--profiles", str(profiles), "--out", str(segments)],
        ["export", "--segments", str(segments), "--out", str(geojson), "--sample"],
    ]
    for args in steps:
        result = runner.invoke(cli.app, args)
        assert result.exit_code == 0, result.output

    collection = json.loads(geojson.read_text())
    assert collection["metadata"]["sample"] is True
    [feature] = collection["features"]
    props = feature["properties"]
    assert props["kind"] == "flat"
    assert props["length_m"] == pytest.approx(1210, rel=0.02)
    assert props["grade_mean_pct"] == pytest.approx(0.4, abs=0.05)
    assert props["name"] == "Voie verte"
    assert props["surface"] == "paved"
    assert props["fits_targets_m"] == [200, 400, 1000]
    assert props["elevation_source"] == "rge_alti_1m"


def test_missing_input_is_reported(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["extract", "--pbf", str(tmp_path / "missing.pbf")])
    assert result.exit_code != 0


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"
