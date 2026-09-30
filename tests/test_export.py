import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from flat_segments import export as ex
from flat_segments.detect import Segment, detect_all
from flat_segments.geometry import FloatArray
from flat_segments.network import EventKind, StrokeEvent, build_strokes
from tests.helpers import make_way, piecewise, raw_profile, straight_stroke


def identity(points: FloatArray) -> FloatArray:
    return points


def sample_segments() -> list[Segment]:
    stroke = straight_stroke(1000, events=(StrokeEvent(500.0, EventKind.CROSSING, 7),))
    z = raw_profile(stroke, piecewise((1000, 0.5)))
    return detect_all([stroke], {stroke.id: z}, elevation_source="synthetic")


def test_geojson_structure_and_rounding() -> None:
    [segment] = sample_segments()
    collection = ex.segments_to_geojson(
        [segment], identity, sample=True, generated_at=datetime(2026, 9, 30, tzinfo=UTC)
    )
    assert collection["metadata"]["sample"] is True
    assert collection["metadata"]["generated_at"] == "2026-09-30T00:00:00Z"
    assert collection["metadata"]["schema_version"] == ex.SCHEMA_VERSION
    [feature] = collection["features"]
    assert feature["id"] == segment.id
    assert feature["geometry"]["type"] == "LineString"
    props = feature["properties"]
    assert list(props) == list(ex.PUBLIC_FIELDS)
    assert props["kind"] == "flat"
    assert props["n_crossings"] == 1
    assert props["fits_targets_m"] == [200, 400, 1000]
    assert props["grade_mean_pct"] == pytest.approx(0.5, abs=0.01)
    assert props["length_m"] == round(segment.length_m, 1)
    assert "stroke_id" not in props


def test_geojson_default_projection_is_wgs84(tmp_path: Path) -> None:
    [segment] = sample_segments()
    moved = replace(segment, coords=segment.coords + np.array([581_000.0, 6_271_000.0]))
    collection = ex.segments_to_geojson([moved])
    lon, lat = collection["features"][0]["geometry"]["coordinates"][0]
    assert lon == pytest.approx(1.53, abs=0.02)
    assert lat == pytest.approx(43.53, abs=0.02)
    path = tmp_path / "web" / "segments.geojson"
    ex.write_geojson(collection, path)
    assert json.loads(path.read_text())["type"] == "FeatureCollection"


def test_segments_round_trip(tmp_path: Path) -> None:
    segments = sample_segments()
    path = tmp_path / "segments.parquet"
    ex.write_segments(segments, path)
    [back] = ex.read_segments(path)
    [orig] = segments
    for name in Segment.__dataclass_fields__:
        if name == "coords":
            np.testing.assert_allclose(back.coords, orig.coords)
        else:
            assert getattr(back, name) == getattr(orig, name), name


def test_strokes_round_trip(tmp_path: Path) -> None:
    strokes = build_strokes(
        [
            make_way(1, [(0, 0), (100, 0), (200, 0)], surface="asphalt", structure="bridge"),
            make_way(2, [(100, -50), (100, 0), (100, 50)]),
        ]
    )
    path = tmp_path / "strokes.parquet"
    ex.write_strokes(strokes, path)
    back = ex.read_strokes(path)
    assert [s.id for s in back] == [s.id for s in strokes]
    for a, b in zip(strokes, back, strict=True):
        np.testing.assert_allclose(a.coords, b.coords)
        assert a.parts == b.parts
        assert a.events == b.events
        assert a.is_ring == b.is_ring


def test_profiles_round_trip_keeps_nan(tmp_path: Path) -> None:
    table = ex.ProfileTable({"s1": np.array([1.0, np.nan, 3.0]), "s2": np.array([4.0])}, 5.0, "x")
    path = tmp_path / "profiles.parquet"
    ex.write_profiles(table, path)
    back = ex.read_profiles(path)
    assert (back.step_m, back.elevation_source) == (5.0, "x")
    np.testing.assert_array_equal(back.z_raw["s1"], table.z_raw["s1"])
    np.testing.assert_array_equal(back.z_raw["s2"], [4.0])
