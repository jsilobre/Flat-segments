import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString

from flat_segments import lineage
from flat_segments.detect import Segment, SegmentKind
from flat_segments.lineage import PreviousSegment, PreviousVersion, Redirect
from flat_segments.pipeline import run_publish
from flat_segments.tiles import index_prefix_length
from tests.test_tiles import labege_segments, needs_tippecanoe, write_run

# Lambert-93 origin near Labège; segments run east from it.
X0, Y0 = 581_000.0, 6_271_000.0
BASE = labege_segments()[0]


def seg(segment_id: str, x0: float, x1: float, y: float = 0.0, kind: str = "flat") -> Segment:
    xs = np.linspace(X0 + x0, X0 + x1, 20)
    coords = np.column_stack([xs, np.full_like(xs, Y0 + y)])
    return replace(BASE, id=segment_id, kind=SegmentKind(kind), coords=coords)


def prev(segment: Segment) -> PreviousSegment:
    return PreviousSegment(segment.id, segment.kind.value, LineString(segment.coords))


def version(*segments: Segment, redirects: dict[str, Redirect] | None = None) -> PreviousVersion:
    return PreviousVersion(tuple(prev(s) for s in segments), redirects or {})


def ids(result: lineage.Lineage) -> list[str]:
    return [s.id for s in result.segments]


def test_without_previous_version_nothing_changes() -> None:
    current = [seg("flat-aaaaaaaaaaaa", 0, 500)]
    result = lineage.match(current, None)
    assert ids(result) == ["flat-aaaaaaaaaaaa"]
    assert result.redirects == {}


def test_a_slightly_moved_segment_keeps_its_id() -> None:
    old = seg("flat-aaaaaaaaaaaa", 0, 500)
    moved = seg("flat-bbbbbbbbbbbb", 3, 490, y=2)  # new DEM: a bit shorter, 2 m aside
    result = lineage.match([moved], version(old))
    assert ids(result) == ["flat-aaaaaaaaaaaa"]
    assert (result.kept, result.redirects) == (1, {})
    assert result.segments[0].coords is moved.coords  # only the id changes


def test_a_split_segment_redirects_to_its_largest_piece() -> None:
    old = seg("flat-aaaaaaaaaaaa", 0, 1200)
    pieces = [
        seg("flat-111111111111", 0, 350),
        seg("flat-222222222222", 400, 850),
        seg("flat-333333333333", 900, 1200),
    ]
    result = lineage.match(pieces, version(old))
    assert ids(result) == [p.id for p in pieces]
    redirect = result.redirects["flat-aaaaaaaaaaaa"]
    assert redirect.target == "flat-222222222222"
    lon, lat = redirect.position  # the middle of the target
    assert lon == pytest.approx(1.532, abs=0.01)
    assert lat == pytest.approx(43.53, abs=0.02)
    assert (result.kept, result.aliased, result.retired) == (0, 1, 0)


def test_gone_and_other_kind_segments_are_retired() -> None:
    gone = seg("flat-aaaaaaaaaaaa", 0, 500, y=5000)
    became_climb = seg("flat-cccccccccccc", 0, 500)
    result = lineage.match(
        [seg("climb-dddddddddddd", 0, 500, kind="climb")], version(gone, became_climb)
    )
    assert ids(result) == ["climb-dddddddddddd"]
    assert result.redirects["flat-aaaaaaaaaaaa"].target is None
    assert result.redirects["flat-cccccccccccc"].target is None
    assert result.retired == 2


def test_pairs_are_one_to_one_best_first() -> None:
    old = seg("flat-aaaaaaaaaaaa", 0, 500)
    exact = seg("flat-111111111111", 0, 500)
    double = seg("flat-222222222222", 0, 480, y=6)  # also matches, less well
    result = lineage.match([double, exact], version(old))
    assert ids(result) == ["flat-222222222222", "flat-aaaaaaaaaaaa"]


def test_taken_ids_get_a_suffix() -> None:
    retired = seg("flat-aaaaaaaaaaaa", 0, 500, y=5000)
    redirected = Redirect(None, (1.5, 43.5))
    # A new segment elsewhere whose hash equals the retired id, another an old redirect.
    current = [seg("flat-aaaaaaaaaaaa", 0, 500), seg("flat-eeeeeeeeeeee", 0, 500, y=900)]
    result = lineage.match(current, version(retired, redirects={"flat-eeeeeeeeeeee": redirected}))
    assert ids(result) == ["flat-aaaaaaaaaaaa-2", "flat-eeeeeeeeeeee-2"]
    assert result.renamed == 2
    assert result.redirects["flat-aaaaaaaaaaaa"].target is None


def test_earlier_redirects_follow_their_target() -> None:
    kept = seg("flat-aaaaaaaaaaaa", 0, 500)
    split = seg("flat-bbbbbbbbbbbb", 0, 1200, y=900)
    current = [seg("flat-aaaaaaaaaaaa", 0, 500), seg("flat-111111111111", 0, 700, y=900)]
    earlier = {
        "flat-000000000001": Redirect("flat-aaaaaaaaaaaa", (0.0, 0.0)),  # to a kept id
        "flat-000000000002": Redirect("flat-bbbbbbbbbbbb", (0.0, 0.0)),  # to a now redirected id
        "flat-000000000003": Redirect(None, (1.5, 43.5)),  # retired stays retired
        "flat-000000000004": Redirect("flat-ffffffffffff", (1.6, 43.6)),  # unknown target
    }
    result = lineage.match(current, version(kept, split, redirects=earlier))
    r = result.redirects
    assert r["flat-000000000001"].target == "flat-aaaaaaaaaaaa"
    assert r["flat-000000000001"].position != (0.0, 0.0)
    assert r["flat-000000000002"] == r["flat-bbbbbbbbbbbb"]
    assert r["flat-bbbbbbbbbbbb"].target == "flat-111111111111"
    assert r["flat-000000000003"] == Redirect(None, (1.5, 43.5))
    assert r["flat-000000000004"] == Redirect(None, (1.6, 43.6))


def test_index_prefix_grows_with_the_number_of_ids() -> None:
    assert index_prefix_length(45_000) == 2
    assert index_prefix_length(600_000) == 3
    assert index_prefix_length(4_000_000) == 3
    assert index_prefix_length(9_000_000) == 4


@needs_tippecanoe
def test_republishing_keeps_ids_and_writes_redirects(tmp_path: Path) -> None:
    out = tmp_path / "web"
    v1 = write_run(
        tmp_path / "v1",
        [seg("flat-aaaaaaaaaaaa", 0, 1200), seg("flat-bbbbbbbbbbbb", 0, 500, y=900)],
    )
    run_publish([v1], out)
    pieces = [
        seg("flat-111111111111", 0, 350),
        seg("flat-222222222222", 400, 1200),
        seg("flat-cccccccccccc", 2, 500, y=901),
    ]
    v2 = write_run(tmp_path / "v2", pieces)
    count, files, result = run_publish([v2], out, previous=out)
    assert count == 3
    assert result is not None
    entries: dict[str, list[object]] = {}
    for path in files.index_dir.glob("*.json"):
        entries.update(json.loads(path.read_text()))
    assert set(entries) == {
        "flat-111111111111",
        "flat-222222222222",
        "flat-bbbbbbbbbbbb",  # kept by the moved segment
        "flat-aaaaaaaaaaaa",  # redirected
    }
    assert entries["flat-aaaaaaaaaaaa"][2] == "flat-222222222222"
    assert len(entries["flat-bbbbbbbbbbbb"]) == 2
    assert lineage.read_redirects(files.index_dir) == dict(result.redirects)
