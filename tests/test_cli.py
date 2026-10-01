import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import typer
from typer.testing import CliRunner

from flat_segments import cli, download
from flat_segments.elevation import bbox_to_lambert93
from flat_segments.osm import read_ways
from tests.test_download import FakeWeb, fake_wms
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
    pbf, dem = make_inputs(tmp_path)
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


def test_elevation_source_is_read_from_the_dem(tmp_path: Path) -> None:
    import rasterio

    from flat_segments.elevation import SOURCE_TAG
    from flat_segments.export import read_profiles

    pbf, dem = make_inputs(tmp_path)
    with rasterio.open(dem, "r+") as ds:
        ds.update_tags(**{SOURCE_TAG: "lidar_hd"})
    strokes, profiles = tmp_path / "strokes.parquet", tmp_path / "profiles.parquet"
    runner.invoke(cli.app, ["extract", "--pbf", str(pbf), "--bbox", BBOX, "--out", str(strokes)])
    args = ["elevation", "--dem", str(dem), "--strokes", str(strokes), "--out", str(profiles)]
    assert runner.invoke(cli.app, args).exit_code == 0
    assert read_profiles(profiles).elevation_source == "lidar_hd"
    assert runner.invoke(cli.app, [*args, "--source", "other"]).exit_code == 0
    assert read_profiles(profiles).elevation_source == "other"


def test_missing_input_is_reported(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["extract", "--pbf", str(tmp_path / "missing.pbf")])
    assert result.exit_code != 0


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"


def make_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """The synthetic OSM file and a gentle-slope GeoTIFF covering it."""
    pbf = tmp_path / "area.osm"
    pbf.write_text(OSM)
    min_x, min_y, max_x, max_y = bbox_to_lambert93(cli.parse_bbox(BBOX), round_to_m=100)
    cols, rows = int((max_x - min_x) / 5), int((max_y - min_y) / 5)
    x = min_x + 5 * (np.arange(cols) + 0.5)
    values = np.tile(150 + 0.004 * (x - min_x), (rows, 1))
    dem = tmp_path / "dem.tif"
    write_geotiff(dem, values, (5.0, 0.0, min_x, 0.0, -5.0, max_y), "EPSG:2154")
    return pbf, dem


def test_pipeline_command_with_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pbf, dem = make_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)  # default intermediate paths live under ./data
    out = tmp_path / "site" / "segments.geojson"
    args = ["pipeline", "--pbf", str(pbf), "--dem", str(dem), "--bbox", BBOX, "--out", str(out)]
    result = runner.invoke(cli.app, [*args, "--set", "flat.target_lengths_m=[250, 1500]"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data" / "processed" / "segments.params.toml").exists()
    collection = json.loads(out.read_text())
    [feature] = collection["features"]
    assert feature["properties"]["fits_targets_m"] == [250]
    recorded = collection["metadata"]["params"]["detection"]["flat"]["target_lengths_m"]
    assert recorded == [250.0, 1500.0]


def test_config_command_prints_effective_parameters(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["config"])
    assert result.exit_code == 0
    default = Path(__file__).resolve().parents[1] / "configs" / "default.toml"
    assert result.output == default.read_text()
    custom = tmp_path / "custom.toml"
    custom.write_text("[detection.flat]\nmax_local_grade_pct = 1.5\n")
    result = runner.invoke(
        cli.app, ["config", "--config", str(custom), "--set", "dedup.buffer_m=12"]
    )
    assert "max_local_grade_pct = 1.5" in result.output
    assert "buffer_m = 12.0" in result.output


def test_invalid_override_is_a_usage_error() -> None:
    result = runner.invoke(cli.app, ["config", "--set", "flat.nope=1"])
    assert result.exit_code == 2
    assert "unknown parameter" in result.output


def test_download_osm_command_downloads_and_clips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = OSM.encode()
    url = "https://example.org/area.osm"
    md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
    web = FakeWeb({f"{url}.md5": md5.encode(), url: content})
    monkeypatch.setattr(download, "urlopen", web)
    clipped = tmp_path / "pilot.osm.pbf"
    args = ["--url", url, "--out-dir", str(tmp_path), "--bbox", BBOX, "--clipped", str(clipped)]
    result = runner.invoke(cli.app, ["download-osm", *args])
    assert result.exit_code == 0, result.output
    assert "2 ways" in result.output
    assert [w.id for w in read_ways(clipped)] == [1, 2]


def test_download_dem_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download, "urlopen", FakeWeb({download.WMS_URL: fake_wms}))
    args = ["--bbox", "1.530,43.529,1.535,43.531", "--out-dir", str(tmp_path)]
    result = runner.invoke(
        cli.app, ["download-dem", *args, "--tile-size-m", "500", "--resolution-m", "10"]
    )
    assert result.exit_code == 0, result.output
    assert "tile 1/" in result.output
    assert (tmp_path / "pilot.vrt").exists()


def test_download_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download, "urlopen", FakeWeb({}))
    result = runner.invoke(cli.app, ["download-osm", "--out-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "HTTP 404" in result.output


def test_calibration_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pbf, dem = make_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    pipeline_args = ["pipeline", "--pbf", str(pbf), "--dem", str(dem), "--bbox", BBOX]
    assert runner.invoke(cli.app, [*pipeline_args, "--out", "site.geojson"]).exit_code == 0

    result = runner.invoke(cli.app, ["report"])
    assert result.exit_code == 0, result.output
    assert "| flat | 1 |" in result.output

    result = runner.invoke(cli.app, ["sweep", "flat.max_mean_grade_pct", "0.2", "1"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[2].startswith("| 0.2 | 0 |")  # the 0.4 % slope is too steep for 0.2 %
    assert lines[3].startswith("| 1 | 1 |")

    segment_id = json.loads(Path("site.geojson").read_text())["features"][0]["id"]
    result = runner.invoke(cli.app, ["inspect", segment_id])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data" / "processed" / "inspect" / f"{segment_id}.png").exists()
    assert runner.invoke(cli.app, ["inspect", "flat-unknown"]).exit_code == 2

    result = runner.invoke(cli.app, ["validation-sheet", "--count", "5"])
    assert result.exit_code == 0, result.output
    sheet = (tmp_path / "docs" / "validation" / "pilot.md").read_text()
    assert f"?id={segment_id}" in sheet
