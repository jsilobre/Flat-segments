from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest
from shapely.geometry import LineString, box, mapping
from typer.testing import CliRunner

from flat_segments import batch, cli, download
from flat_segments.config import load_params
from flat_segments.departments import load_department
from flat_segments.detect import SegmentKind
from flat_segments.export import read_segments
from flat_segments.params import PipelineParams
from tests.test_departments import collection
from tests.test_download import FakeWeb

# A small "département" east of Labège, and three cycleways of 2 km:
# A inside it, B in the 2 km margin north of it, C far away.
OUTLINE = box(1.52, 43.52, 1.555, 43.54)
LATS = {1: 43.530, 2: 43.548, 3: 43.600}
LONS = np.linspace(1.525, 1.550, 11)


def osm_xml() -> str:
    nodes, ways = [], []
    for way_id, lat in LATS.items():
        refs = []
        for i, lon in enumerate(LONS):
            node_id = way_id * 100 + i
            nodes.append(f'<node id="{node_id}" lat="{lat}" lon="{lon:.5f}" version="1"/>')
            refs.append(f'<nd ref="{node_id}"/>')
        ways.append(
            f'<way id="{way_id}" version="1">{"".join(refs)}'
            '<tag k="highway" v="cycleway"/><tag k="surface" v="asphalt"/></way>'
        )
    return f'<?xml version="1.0"?><osm version="0.6">{"".join(nodes)}{"".join(ways)}</osm>'


def gentle_wms(url: str) -> bytes:
    """Answer a GetMap request with a 0.2 % slope (flat) towards the east."""
    query = parse_qs(urlsplit(url).query)
    min_x, _, max_x, _ = (float(v) for v in query["BBOX"][0].split(","))
    width, height = int(query["WIDTH"][0]), int(query["HEIGHT"][0])
    xs = min_x + (max_x - min_x) / width * (np.arange(width) + 0.5)
    grid = np.broadcast_to(150.0 + 0.002 * (xs - 580_000), (height, width))
    return grid.astype("<f4").tobytes()


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path]:
    pbf = tmp_path / "region.osm"
    pbf.write_text(osm_xml())
    outlines = tmp_path / "departements.geojson"
    outlines.write_bytes(collection(("31", "Test", mapping(OUTLINE))))
    return pbf, outlines


def run(
    inputs: tuple[Path, Path],
    root: Path,
    web: FakeWeb,
    params: PipelineParams | None = None,
    **kwargs: bool,
) -> dict[str, Any]:
    pbf, outlines = inputs
    return batch.run_department(
        "31",
        pbf,
        outlines,
        root,
        params or load_params(),
        opener=web,
        dem_resolution_m=20.0,
        log=lambda _: None,
        **kwargs,
    )


def test_department_keeps_the_segments_whose_midpoint_is_inside(
    inputs: tuple[Path, Path], tmp_path: Path
) -> None:
    web = FakeWeb({download.WMS_URL: gentle_wms})
    state = run(inputs, tmp_path / "out", web)
    paths = batch.department_paths(tmp_path / "out" / "31")
    assert list(state["steps"]) == list(batch.STEPS)
    assert state["steps"]["strokes"]["ways"] == 2  # C lies beyond the margin
    assert state["steps"]["segments"]["detected"] == 2  # flats on A and B
    [segment] = read_segments(paths.segments)
    assert segment.kind is SegmentKind.FLAT
    outline = load_department(inputs[1], "31").outline_l93()
    assert outline.contains(LineString(segment.coords))  # A, not B
    assert segment.elevation_source == "lidar_hd"
    assert not paths.dem_dir.exists()  # deleted once sampled
    assert paths.params.exists()
    assert len(web.requests) == state["steps"]["dem"]["tiles"] > 0


def test_department_resumes_and_refuses_other_parameters(
    inputs: tuple[Path, Path], tmp_path: Path
) -> None:
    web = FakeWeb({download.WMS_URL: gentle_wms})
    first = run(inputs, tmp_path, web, keep_dem=True)
    requests = len(web.requests)
    assert batch.department_paths(tmp_path / "31").dem.exists()
    again = run(inputs, tmp_path, web)
    assert again == first  # nothing recomputed
    assert len(web.requests) == requests
    other = load_params(None, ["flat.max_local_grade_pct=1.5"])
    with pytest.raises(batch.StateError, match="--force"):
        run(inputs, tmp_path, web, params=other)
    redone = run(inputs, tmp_path, web, params=other, force=True)
    assert redone["params"] != first["params"]
    assert len(web.requests) > requests  # the DEM was deleted by the second run


def test_departments_command_reports_failures_and_continues(
    inputs: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download, "urlopen", FakeWeb({download.WMS_URL: gentle_wms}))
    pbf, outlines = inputs
    args = ["--pbf", str(pbf), "--departments-file", str(outlines), "--root", str(tmp_path)]
    result = CliRunner().invoke(cli.app, ["departments", "99", "31", *args])
    assert result.exit_code == 1
    assert "| 99 | | | | | | | error: KeyError" in result.output
    assert "| 31 Test |" in result.output
    assert (tmp_path / "31" / "segments.parquet").exists()
