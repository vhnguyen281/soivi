"""Statistics (VNCMA Prompt 6): property tests on random data, and known answers."""

import numpy as np
import pandas as pd
import pytest

from core.cma.stats import (
    StatsConfig,
    compute_stats,
    ewma_weights,
    geltner,
    is_valid_correlation,
    ledoit_wolf_shrinkage,
    nearest_correlation,
    validate,
)

CLASSES = ("a", "b", "c", "d", "e")


def random_returns(seed: int, months: int = 150, ragged: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(CLASSES)
    mix = rng.normal(size=(n, n))
    x = rng.normal(size=(months, n)) @ mix * 0.02
    frame = pd.DataFrame(
        x, columns=CLASSES, index=pd.date_range("2010-01-31", periods=months, freq="ME")
    )
    if ragged:  # unequal histories, like the real classes
        for i in range(1, len(CLASSES)):
            frame.iloc[: int(rng.integers(0, months - 60)) if i % 2 else 0, i] = np.nan
    return frame


def config(**kw: object) -> StatsConfig:
    base = {"classes": CLASSES, "desmooth": (), "vol_floors": {}}
    base.update(kw)
    return StatsConfig(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("seed", range(25))
def test_correlation_is_always_valid(seed: int) -> None:
    stats = compute_stats(random_returns(seed), config())
    c = stats.corr.to_numpy()
    assert np.allclose(c, c.T)
    assert np.allclose(np.diag(c), 1.0)
    assert np.all(np.abs(c) <= 1.0 + 1e-12)
    assert np.linalg.eigvalsh(c).min() > 0
    assert 0.0 <= stats.shrinkage <= 1.0
    assert all(v > 0 for v in stats.vol.values())


@pytest.mark.parametrize("seed", range(10))
def test_ledoit_wolf_intensity_is_in_0_1_and_falls_with_more_data(seed: int) -> None:
    rng = np.random.default_rng(seed)
    mix = rng.normal(size=(6, 6))  # a real correlation structure, so the target is wrong
    short, long = rng.normal(size=(40, 6)) @ mix, rng.normal(size=(4000, 6)) @ mix
    d_short, d_long = ledoit_wolf_shrinkage(short), ledoit_wolf_shrinkage(long)
    assert 0.0 <= d_long <= d_short <= 1.0
    assert d_long < 0.05
    iid = ledoit_wolf_shrinkage(rng.normal(size=(4000, 6)))  # true covariance is the target
    assert 0.0 <= iid <= 1.0


def test_higham_example_is_repaired() -> None:
    # Higham (2002), section 4: the nearest correlation matrix to this tridiagonal matrix.
    a = np.array([[2, -1, 0, 0], [-1, 2, -1, 0], [0, -1, 2, -1], [0, 0, -1, 2]], dtype=float)
    expected = np.array(
        [
            [1.0000, -0.8084, 0.1916, 0.1068],
            [-0.8084, 1.0000, -0.6562, 0.1916],
            [0.1916, -0.6562, 1.0000, -0.8084],
            [0.1068, 0.1916, -0.8084, 1.0000],
        ]
    )
    x = nearest_correlation(a, min_eigen=1e-10)
    assert np.allclose(x, expected, atol=2e-3)
    assert is_valid_correlation(x, 1e-12)


def test_a_broken_hand_edited_matrix_gets_repaired() -> None:
    broken = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])  # not PSD
    assert not is_valid_correlation(broken)
    fixed = validate(broken)
    assert is_valid_correlation(fixed)
    good = np.array([[1.0, 0.3], [0.3, 1.0]])
    assert validate(good) is not None and np.allclose(validate(good), good)  # left alone


def test_ewma_weights_sum_to_one_and_halve_every_half_life() -> None:
    w = ewma_weights(100, 36)
    assert w.sum() == pytest.approx(1.0)
    assert w[-37] / w[-1] == pytest.approx(0.5)


def test_geltner_recovers_an_unsmoothed_series() -> None:
    rng = np.random.default_rng(7)
    true = rng.normal(0.005, 0.03, size=3000)
    phi = 0.6
    observed = np.empty_like(true)
    observed[0] = true[0]
    for t in range(1, len(true)):  # appraisal smoothing: r_obs = phi r_obs_{t-1} + (1-phi) r_true
        observed[t] = phi * observed[t - 1] + (1 - phi) * true[t]
    out, est = geltner(pd.Series(observed), max_phi=0.9)
    assert est == pytest.approx(phi, abs=0.05)
    assert out.std() == pytest.approx(true.std(), rel=0.1)
    assert observed.std() < 0.6 * true.std()


def test_vol_floor_and_short_overlap() -> None:
    frame = random_returns(1, ragged=False)
    frame.iloc[:120, 1] = np.nan  # b shares only 30 months with the others
    stats = compute_stats(frame, config(vol_floors={"a": 0.9}, min_overlap=36))
    assert stats.vol["a"] == 0.9 and stats.vol_raw["a"] < 0.9
    assert stats.corr.loc["a", "b"] == 0.0
    assert any("a/b: 30 shared months" in n for n in stats.notes)


def test_equal_histories_use_plain_ledoit_wolf() -> None:
    frame = random_returns(3, ragged=False)
    raw = compute_stats(frame, config(ewma_weight=0.0))
    sample = frame.corr().to_numpy()
    expected = (1 - raw.shrinkage) * sample + raw.shrinkage * np.eye(len(CLASSES))
    assert np.allclose(raw.corr.to_numpy(), expected, atol=1e-10)
