from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from flat_segments import calibration as cal
from flat_segments.config import ConfigError
from flat_segments.detect import Segment, SegmentKind, detect_all
from flat_segments.geometry import FloatArray
from flat_segments.network import EventKind, Stroke, StrokeEvent
from flat_segments.params import PipelineParams
from flat_segments.profile import build_profile
from tests.helpers import piecewise, raw_profile, straight_stroke

PARAMS = PipelineParams()


def dataset() -> tuple[list[Segment], list[Stroke], dict[str, FloatArray]]:
    strokes = [
        straight_stroke(1000, stroke_id="flat"),
        straight_stroke(
            1000,
            stroke_id="crossed",
            offset_y=300,
            events=(StrokeEvent(500, EventKind.CROSSING, 1),),
        ),
        straight_stroke(900, stroke_id="hill", offset_y=600),
        straight_stroke(1000, stroke_id="gentle", offset_y=900),
    ]
    shapes = {
        "flat": piecewise((1000, 0)),
        "crossed": piecewise((1000, 0.3)),
        "hill": piecewise((300, 0), (300, 6), (300, 0)),
        "gentle": piecewise((1000, 0.8)),
    }
    z = {s.id: raw_profile(s, shapes[s.id]) for s in strokes}
    return detect_all(strokes, z, PARAMS, "synthetic"), strokes, z


def test_summarize_counts_by_kind() -> None:
    segments, _, _ = dataset()
    text = cal.summarize(segments)
    assert text.startswith("# Segments report")
    assert "| flat | 5 |" in text  # 3 flat strokes + the flat parts before and after the hill
    assert "| climb | 1 |" in text
    assert "| 1000 |" in text


def test_sweep_reruns_detection() -> None:
    _, strokes, z = dataset()
    rows = cal.sweep(strokes, z, PARAMS, "flat.max_mean_grade_pct", ["0.5", "1"])
    assert [r.value for r in rows] == ["0.5", "1"]
    assert rows[0].n_flat < rows[1].n_flat  # the 0.8 % stroke only passes with 1 %
    table = cal.format_sweep("flat.max_mean_grade_pct", rows)
    assert table.splitlines()[0].startswith("| flat.max_mean_grade_pct |")


@pytest.mark.parametrize("key", ["network.max_deflection_deg", "profile.step_m"])
def test_sweep_rejects_parameters_used_before_detection(key: str) -> None:
    _, strokes, z = dataset()
    with pytest.raises(ConfigError, match="extract"):
        cal.sweep(strokes, z, PARAMS, key, ["1", "2"])


def test_select_for_validation_is_representative_and_deterministic() -> None:
    segments, _, _ = dataset()
    assert len(cal.select_for_validation(segments, 10)) == len(segments)
    picked = cal.select_for_validation(segments, 3)
    assert len(picked) == 3
    assert any(s.kind is SegmentKind.CLIMB for s in picked)
    assert any(s.n_crossings > 0 for s in picked)
    assert [s.id for s in picked] == [s.id for s in cal.select_for_validation(segments, 3)]


def test_select_for_validation_balances_flats_and_climbs() -> None:
    segments, _, _ = dataset()
    flat = next(s for s in segments if s.kind is SegmentKind.FLAT)
    climb = next(s for s in segments if s.kind is SegmentKind.CLIMB)
    flats = [replace(flat, id=f"flat-{i}", score=float(i)) for i in range(3)]
    climbs = [replace(climb, id=f"climb-{i}", score=float(i)) for i in range(30)]
    picked = cal.select_for_validation(flats + climbs, 4)
    assert [s.kind for s in picked].count(SegmentKind.FLAT) == 2
    picked = cal.select_for_validation(flats + climbs, 10)  # only 3 flats
    assert [s.kind for s in picked].count(SegmentKind.FLAT) == 3
    assert len(picked) == 10
    assert len(cal.select_for_validation(climbs, 5)) == 5


def test_validation_sheet_is_a_fillable_table() -> None:
    segments, _, _ = dataset()
    sheet = cal.validation_sheet(segments, site_url="https://x.test/", today=date(2026, 10, 1))
    assert "Générée le 2026-10-01" in sheet
    assert "`TRAVERSEE`" in sheet
    rows = [line for line in sheet.splitlines() if line.startswith("| ") and "`flat-" in line]
    assert len(rows) == 5
    assert "[voir](https://x.test/?id=flat-" in rows[0]
    assert rows[0].endswith("|  |  |")
    assert "moy. 5," in sheet or "moy. 6," in sheet  # French decimal comma


@pytest.mark.parametrize("kind", [SegmentKind.FLAT, SegmentKind.CLIMB])
def test_plot_segment_writes_a_png(tmp_path: Path, kind: SegmentKind) -> None:
    segments, strokes, z = dataset()
    segment = next(s for s in segments if s.kind is kind)
    stroke = next(s for s in strokes if s.id == segment.stroke_id)
    profile = build_profile(stroke.coords, z[stroke.id], PARAMS.profile, stroke.structures())
    path = cal.plot_segment(segment, stroke, profile, PARAMS, tmp_path / "plot.png")
    assert path.read_bytes().startswith(b"\x89PNG")
