import math

import numpy as np
import pytest

from flat_segments import geometry as g


def square_path() -> g.FloatArray:
    return g.as_coords([(0, 0), (100, 0), (100, 100)])


def test_as_coords_rejects_bad_shape() -> None:
    with pytest.raises(ValueError, match=r"\(N, 2\)"):
        g.as_coords([1.0, 2.0, 3.0])


def test_length_and_cumulative_distances() -> None:
    coords = square_path()
    np.testing.assert_allclose(g.cumulative_distances(coords), [0, 100, 200])
    assert g.polyline_length(coords) == pytest.approx(200)


def test_uniform_grid_covers_both_ends_with_step_at_most_requested() -> None:
    grid = g.uniform_grid(203.0, 5.0)
    assert grid[0] == 0
    assert grid[-1] == pytest.approx(203.0)
    assert len(grid) == 42  # ceil(203 / 5) = 41 intervals
    assert np.diff(grid).max() <= 5.0


def test_uniform_grid_exact_multiple() -> None:
    np.testing.assert_allclose(g.uniform_grid(20.0, 5.0), [0, 5, 10, 15, 20])


def test_interpolate_at_and_clipping() -> None:
    pts = g.interpolate_at(square_path(), [-10, 50, 150, 500])
    np.testing.assert_allclose(pts, [(0, 0), (50, 0), (100, 50), (100, 100)])


def test_interpolate_ignores_duplicate_vertices() -> None:
    coords = g.as_coords([(0, 0), (0, 0), (10, 0), (10, 0)])
    np.testing.assert_allclose(g.interpolate_at(coords, [5]), [(5, 0)])


def test_resample_keeps_original_distances() -> None:
    distances, points = g.resample(square_path(), 30.0)
    assert len(distances) == len(points) == 8  # 7 intervals of 28.57 m
    np.testing.assert_allclose(points[-1], (100, 100))


def test_substring_keeps_inner_vertices() -> None:
    sub = g.substring(square_path(), 50, 150)
    np.testing.assert_allclose(sub, [(50, 0), (100, 0), (100, 50)])
    assert g.polyline_length(sub) == pytest.approx(100)


def test_substring_rejects_empty_interval() -> None:
    with pytest.raises(ValueError, match="greater"):
        g.substring(square_path(), 10, 10)


def test_sinuosity() -> None:
    assert g.sinuosity(g.as_coords([(0, 0), (500, 0)])) == pytest.approx(1.0)
    assert g.sinuosity(square_path()) == pytest.approx(200 / math.hypot(100, 100))
    angles = np.linspace(0, math.pi, 200)
    half_circle = np.column_stack((np.cos(angles), np.sin(angles))) * 100
    assert g.sinuosity(half_circle) == pytest.approx(math.pi / 2, rel=1e-3)
    ring = g.as_coords([(0, 0), (10, 0), (10, 10), (0, 0)])
    assert math.isinf(g.sinuosity(ring))


@pytest.mark.parametrize(
    ("target", "expected"),
    [((0, 10), 0.0), ((10, 0), 90.0), ((0, -10), 180.0), ((-10, 0), 270.0)],
)
def test_bearing(target: tuple[float, float], expected: float) -> None:
    assert g.bearing_deg(np.zeros(2), np.array(target, float)) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(0, 180, 0), (90, 270, 0), (0, 90, 90), (10, 170, 20), (350, 190, 20), (45, 45, 180)],
)
def test_deflection(a: float, b: float, expected: float) -> None:
    assert g.deflection_deg(a, b) == pytest.approx(expected)


def test_point_polyline_distances() -> None:
    points = g.as_coords([(50, 10), (110, 50), (-3, -4), (100, 100)])
    np.testing.assert_allclose(g.point_polyline_distances(points, square_path()), [10, 10, 5, 0])


def test_unit_normals_point_left() -> None:
    normals = g.unit_normals(g.as_coords([(0, 0), (10, 0), (20, 0)]))
    np.testing.assert_allclose(normals, [(0, 1)] * 3)


def test_stable_id_is_deterministic_and_direction_independent() -> None:
    coords = g.as_coords([(581_000.0, 6_271_000.0), (581_400.0, 6_271_010.0)])
    ident = g.stable_id("flat", coords)
    assert ident.startswith("flat-")
    assert len(ident) == len("flat-") + 12
    assert g.stable_id("flat", coords[::-1]) == ident
    assert g.stable_id("flat", coords + 1.0) == ident  # sub-grid jitter
    assert g.stable_id("climb", coords) != ident
    assert g.stable_id("flat", coords + 100.0) != ident
