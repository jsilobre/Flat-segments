import json
from pathlib import Path

import pytest
from shapely.geometry import box, mapping
from typer.testing import CliRunner

from flat_segments import cli
from flat_segments import departments as dep
from flat_segments import osm_extracts as ox
from flat_segments.osm import read_ways
from flat_segments.params import WEB_CRS, WORK_CRS
from tests.test_departments import collection

needs_osmium = pytest.mark.skipif(not ox.osmium_available(), reason="osmium is not installed")

# Two "départements" around Labège, 10 km apart, and four cycleways:
# A inside the west one, B in its 2 km margin, C in the east one only,
# D starting in the west one and running 15 km east (kept whole).
WEST = box(1.52, 43.52, 1.555, 43.54)
EAST = box(1.70, 43.52, 1.74, 43.54)
WAYS = {
    1: [(1.525 + 0.0025 * i, 43.530) for i in range(11)],
    2: [(1.525 + 0.0025 * i, 43.548) for i in range(11)],
    3: [(1.705 + 0.0025 * i, 43.530) for i in range(11)],
    4: [(1.53, 43.525), (1.60, 43.525), (1.66, 43.525), (1.72, 43.525)],
}


def osm_xml() -> str:
    nodes, ways = [], []
    for way_id, points in WAYS.items():
        refs = []
        for i, (lon, lat) in enumerate(points):
            node_id = way_id * 100 + i
            nodes.append(f'<node id="{node_id}" lat="{lat}" lon="{lon}" version="1"/>')
            refs.append(f'<nd ref="{node_id}"/>')
        ways.append(
            f'<way id="{way_id}" version="1">{"".join(refs)}<tag k="highway" v="cycleway"/></way>'
        )
    return f'<?xml version="1.0"?><osm version="0.6">{"".join(nodes)}{"".join(ways)}</osm>'


@pytest.fixture
def outlines(tmp_path: Path) -> Path:
    path = tmp_path / "departements.geojson"
    path.write_bytes(
        collection(
            ("81", "Est", mapping(EAST)),
            ("31", "Ouest", mapping(WEST)),
            ("974", "La Réunion", mapping(box(55.2, -21.4, 55.8, -20.9))),
        )
    )
    return path


def test_department_codes_and_loading(outlines: Path) -> None:
    assert dep.department_codes(outlines) == ["31", "81"]
    assert dep.department_codes(outlines, overseas=True) == ["31", "81", "974"]
    loaded = dep.load_departments(outlines, ["81", "31"])
    assert [d.code for d in loaded] == ["81", "31"]
    with pytest.raises(KeyError, match="12"):
        dep.load_departments(outlines, ["31", "12"])


def test_batches() -> None:
    assert [list(b) for b in ox.batches([1, 2, 3, 4, 5], 2)] == [[1, 2], [3, 4], [5]]
    with pytest.raises(ValueError, match="batch size"):
        list(ox.batches([], 0))


def test_cut_area_holds_the_pipeline_area(outlines: Path) -> None:
    west = dep.load_department(outlines, "31")
    area = dep.transform_geometry(ox.extract_area(west), WEB_CRS, WORK_CRS)
    assert area.contains(west.work_area_l93())
    assert area.area < west.work_area_l93(dep.BORDER_MARGIN_M + 400).area


@needs_osmium
def test_extracts_keep_whole_ways_touching_the_grown_outline(
    tmp_path: Path, outlines: Path
) -> None:
    pbf = tmp_path / "france.osm"
    pbf.write_text(osm_xml())
    batches: list[list[Path]] = []
    files = ox.cut_extracts(
        pbf,
        dep.load_departments(outlines, ["31", "81"]),
        tmp_path / "osm",
        batch_size=1,
        on_batch=batches.append,
    )
    assert [[f.name for f in b] for b in batches] == [["31.osm.pbf"], ["81.osm.pbf"]]
    west = {way.id: way for way in read_ways(files[0])}
    east = {way.id: way for way in read_ways(files[1])}
    assert set(west) == {1, 2, 4}
    assert set(east) == {3, 4}
    assert len(west[4].coords) == len(east[4].coords) == len(WAYS[4])


@needs_osmium
def test_cut_osm_command(tmp_path: Path, outlines: Path) -> None:
    pbf = tmp_path / "france.osm"
    pbf.write_text(osm_xml())
    out = tmp_path / "osm"
    args = ["cut-osm", str(pbf), "--departments-file", str(outlines), "--out-dir", str(out)]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in out.iterdir()) == ["31.osm.pbf", "81.osm.pbf"]
    codes = CliRunner().invoke(cli.app, ["department-codes", "--departments-file", str(outlines)])
    assert codes.output.strip() == '["31", "81"]'
    bad = CliRunner().invoke(
        cli.app, ["department-codes", "12", "--departments-file", str(outlines)]
    )
    assert bad.exit_code != 0


def test_department_summary_command(tmp_path: Path) -> None:
    states = []
    for code, minutes in (("81", 2), ("31", 30)):
        path = tmp_path / code / "state.json"
        path.parent.mkdir()
        steps = {
            "dem": {"seconds": minutes * 60, "tiles": 5},
            "segments": {"flats": 3, "climbs": 4},
        }
        path.write_text(json.dumps({"code": code, "name": f"D{code}", "steps": steps}))
        states.append(str(path))
    result = CliRunner().invoke(cli.app, ["department-summary", *states])
    assert result.exit_code == 0, result.output
    rows = result.output.splitlines()[2:]
    assert rows[0].startswith("| 31 D31 |")
    assert "| 30.0 | ok |" in rows[0]
    assert rows[1].startswith("| 81 D81 |")


@needs_osmium
def test_renumbering_keeps_the_ways(tmp_path: Path, outlines: Path) -> None:
    pbf = tmp_path / "france.osm"
    pbf.write_text(osm_xml())
    renumbered = ox.renumber_nodes(pbf, tmp_path / "france-renumbered.osm.pbf")
    before = {way.id: way for way in read_ways(pbf)}
    after = {way.id: way for way in read_ways(renumbered)}
    assert set(before) == set(after) == set(WAYS)
    for way_id, way in before.items():
        assert (after[way_id].coords == way.coords).all()
    files = ox.cut_extracts(renumbered, dep.load_departments(outlines, ["31"]), tmp_path / "osm")
    assert {way.id for way in read_ways(files[0])} == {1, 2, 4}
    result = CliRunner().invoke(
        cli.app, ["renumber-osm", str(pbf), str(tmp_path / "again.osm.pbf")]
    )
    assert result.exit_code == 0, result.output
