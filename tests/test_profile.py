import numpy as np
import pytest

from flat_segments import profile as p
from flat_segments.params import ProfileParams

STEP = 5.0


def grid(length: float) -> np.ndarray:
    return np.arange(0.0, length + STEP / 2, STEP)


def test_true_runs() -> None:
    mask = np.array([1, 1, 0, 0, 1, 0, 1, 1, 1], bool)
    assert p.true_runs(mask) == [(0, 2), (4, 5), (6, 9)]
    assert p.true_runs(np.zeros(3, bool)) == []


def test_smoothing_preserves_linear_profile_up_to_the_ends() -> None:
    d = grid(500)
    z = 100 + 0.04 * d
    smoothed = p.smooth(z, STEP, ProfileParams())
    np.testing.assert_allclose(smoothed, z, atol=1e-9)


def test_median_removes_isolated_spike() -> None:
    z = np.full(50, 150.0)
    z[20] = 153.0
    np.testing.assert_allclose(p.rolling_median(z, 3), 150.0)


def test_nan_stays_nan_and_is_ignored_by_neighbours() -> None:
    z = np.full(40, 10.0)
    z[15] = np.nan
    smoothed = p.gaussian_smooth(p.rolling_median(z, 3), 2.0)
    assert np.isnan(smoothed[15])
    np.testing.assert_allclose(np.delete(smoothed, 15), 10.0)


def test_local_grade_of_constant_slope() -> None:
    d = grid(300)
    grade = p.local_grade_pct(d, 50 + 0.06 * d, 20.0)
    np.testing.assert_allclose(grade, 6.0)


def test_smoothing_damps_dem_noise_below_flat_threshold() -> None:
    rng = np.random.default_rng(42)
    d = grid(1000)
    z = 150 + rng.normal(0.0, 0.1, len(d))
    params = ProfileParams()
    grade = p.local_grade_pct(d, p.smooth(z, STEP, params), params.grade_base_m)
    assert np.abs(grade).max() < 1.0


@pytest.mark.parametrize(
    ("z", "gain", "loss"),
    [
        ([0, 1, 2, 3, 4], 4, 0),
        ([4, 3, 2, 1, 0], 0, 4),
        ([0, 0.3, 0, 0.3, 0, 0.3, 0], 0, 0),  # noise below the hysteresis
        ([0, 2, 0, 2, 0], 4, 4),
        ([0, 0.2, 0.4, 0.6, 0.7], 0.7, 0),
    ],
)
def test_elevation_gain_loss(z: list[float], gain: float, loss: float) -> None:
    got_gain, got_loss = p.elevation_gain_loss(np.array(z, float), 0.5)
    assert got_gain == pytest.approx(gain)
    assert got_loss == pytest.approx(loss)


def test_gain_minus_loss_equals_net_change() -> None:
    rng = np.random.default_rng(0)
    z = np.cumsum(rng.normal(0, 0.4, 300))
    gain, loss = p.elevation_gain_loss(z, 0.5)
    assert gain - loss == pytest.approx(z[-1] - z[0])


def test_short_gap_is_filled_long_gap_is_not() -> None:
    d = grid(200)
    z = 100 + 0.01 * d
    z[10:13] = np.nan  # 3 samples: neighbours 20 m apart
    z[25:30] = np.nan  # 5 samples: neighbours 30 m apart
    filled, bridge, tunnel, gap = p.fill_profile(d, z, (), ProfileParams())
    np.testing.assert_allclose(filled[10:13], 100 + 0.01 * d[10:13])
    assert np.isnan(filled[25:30]).all()
    assert gap[10:13].all()
    assert not gap[25:30].any()
    assert not bridge.any()
    assert not tunnel.any()


def test_bridge_is_interpolated_between_abutments() -> None:
    d = grid(400)
    z = np.full(len(d), 150.0)
    valley = (d > 180) & (d < 220)
    z[valley] = 140.0  # DEM reads the river below the bridge
    filled, bridge, _, gap = p.fill_profile(d, z, [(175.0, 225.0, "bridge")], ProfileParams())
    np.testing.assert_allclose(filled, 150.0)
    assert bridge[valley].all()
    assert not gap.any()


def test_structure_touching_the_end_stays_nan() -> None:
    d = grid(100)
    z = np.full(len(d), 150.0)
    filled, _, tunnel, _ = p.fill_profile(d, z, [(80.0, 100.0, "tunnel")], ProfileParams())
    assert np.isnan(filled[-1])
    assert not tunnel.any()


def test_build_profile_checks_grid_size() -> None:
    coords = np.array([(0.0, 0.0), (100.0, 0.0)])
    profile = p.build_profile(coords, np.full(21, 10.0), ProfileParams())
    assert profile.step == pytest.approx(5.0)
    assert profile.length == pytest.approx(100.0)
    with pytest.raises(ValueError, match="expected 21"):
        p.build_profile(coords, np.full(20, 10.0), ProfileParams())
