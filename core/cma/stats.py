"""Volatilities and correlations from monthly log returns (docs/vncma/spec.md §4, Prompt 6).

Steps, per run:

1. Geltner de-smoothing for smoothed series (NAV-based and monthly-average classes):
   r_true_t = (r_obs_t - phi * r_obs_{t-1}) / (1 - phi), phi = the lag-1 autocorrelation of
   r_obs, clipped to [0, `max_phi`] (Geltner 1993, "Estimating market values from appraised
   values without assuming an efficient market", J. Real Estate Research 8(3)).
2. Volatility per class on its **own full history**: annualised sqrt(12 * var), with
   var = 0.5 * full-sample variance + 0.5 * EWMA variance (half-life 36 months).
3. Correlation per **pair, on the months both have** (at least `min_overlap`), blended the same
   way (0.5 full sample + 0.5 EWMA). Pairs with too little overlap get 0.
4. Ledoit–Wolf shrinkage toward the identity (Ledoit & Wolf 2004, "A well-conditioned estimator
   for large-dimensional covariance matrices", J. Multivariate Analysis 88(2), 365-411):
   on standardised returns X (T x N) over the months **all** classes share,
       S = X'X / T,  m = tr(S) / N,  d2 = ||S - m I||_F^2 / N,
       b2_bar = (1 / T^2) * sum_t ||x_t x_t' - S||_F^2 / N,  b2 = min(b2_bar, d2),
       delta = b2 / d2  (in [0, 1]),
   and, per pair, R_ij = (1 - delta_ij) * R_pairwise_ij with delta_ij = delta * T_common / T_ij.
   Estimation noise falls with sample size (~1/T), so a pair with a longer shared history than
   the common window is shrunk less (VNCMA choice, DECISIONS 2026-11-06; plain LW when all
   histories are equal).
5. Validation: symmetric, unit diagonal, |rho| <= 1, min eigenvalue > `min_eigen`; otherwise the
   nearest correlation matrix by Higham's alternating projections (Higham 2002, "Computing the
   nearest correlation matrix - a problem from finance", IMA J. Numerical Analysis 22(3)).
6. Volatility floors per class (config).

Floats only here (CLAUDE.md, VNCMA).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_CLASSES = (
    "cash_vnd",
    "gov_bond",
    "corp_bond",
    "eq_large",
    "eq_midsmall",
    "gold",
    "usd",
    "eq_global",
)
# Smoothed series: bond-fund NAVs, and monthly averages (World Bank gold, Shiller S&P).
DEFAULT_DESMOOTH = ("corp_bond", "gold", "eq_global")
# Proposed annual volatility floors (decimals); reviewed with the owner before a release.
DEFAULT_VOL_FLOORS = {
    "cash_vnd": 0.005,
    "gov_bond": 0.03,
    "corp_bond": 0.03,
    "eq_large": 0.18,
    "eq_midsmall": 0.20,
    "gold": 0.12,
    "usd": 0.02,
    "eq_global": 0.14,
}


@dataclass(frozen=True)
class StatsConfig:
    classes: tuple[str, ...] = DEFAULT_CLASSES
    desmooth: tuple[str, ...] = DEFAULT_DESMOOTH
    half_life_months: float = 36.0
    ewma_weight: float = 0.5
    min_overlap: int = 36
    max_phi: float = 0.9
    min_eigen: float = 1e-8
    vol_floors: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_VOL_FLOORS))


@dataclass
class Stats:
    vol: dict[str, float]  # annual, after floors
    vol_raw: dict[str, float]  # annual, before floors
    corr: pd.DataFrame
    phi: dict[str, float]  # Geltner phi used (0 = not de-smoothed)
    shrinkage: float
    common_months: int
    overlap: pd.DataFrame  # months each pair shares
    repaired: bool  # Higham was needed
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- pieces


def ewma_weights(n: int, half_life: float) -> np.ndarray:
    """Weights for n observations, oldest first, summing to 1 (newest weighs most)."""
    lam = 0.5 ** (1.0 / half_life)
    w: np.ndarray = lam ** np.arange(n - 1, -1, -1, dtype=float)
    out: np.ndarray = w / w.sum()
    return out


def weighted_cov(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    mx, my = float(np.sum(w * x)), float(np.sum(w * y))
    return float(np.sum(w * (x - mx) * (y - my)))


def blended_cov(x: np.ndarray, y: np.ndarray, half_life: float, ewma_weight: float) -> float:
    full = float(np.cov(x, y, ddof=1)[0, 1])
    ewma = weighted_cov(x, y, ewma_weights(len(x), half_life))
    return (1 - ewma_weight) * full + ewma_weight * ewma


def geltner(returns: pd.Series, max_phi: float) -> tuple[pd.Series, float]:
    """(de-smoothed returns, phi). phi = lag-1 autocorrelation clipped to [0, max_phi]."""
    r = returns.dropna()
    if len(r) < 3:
        return r, 0.0
    lagged = returns.shift(1)
    pair = pd.concat([returns, lagged], axis=1).dropna()
    phi = float(np.corrcoef(pair.iloc[:, 0], pair.iloc[:, 1])[0, 1]) if len(pair) > 2 else 0.0
    phi = min(max(phi, 0.0), max_phi)
    if phi == 0.0:
        return r, 0.0
    out = ((returns - phi * lagged) / (1 - phi)).dropna()
    return out, phi


def ledoit_wolf_shrinkage(x: np.ndarray) -> float:
    """Ledoit-Wolf (2004) intensity toward m*I for the sample covariance of x (T x N),
    columns demeaned here. Returns delta in [0, 1]."""
    t, n = x.shape
    if t < 2 or n < 2:
        return 1.0
    x = x - x.mean(axis=0)
    s = x.T @ x / t
    m = np.trace(s) / n
    d2 = float(np.sum((s - m * np.eye(n)) ** 2) / n)
    if d2 <= 0:
        return 1.0
    b2_bar = sum(float(np.sum((np.outer(row, row) - s) ** 2)) for row in x) / (t * t) / n
    b2 = min(b2_bar, d2)
    return float(b2 / d2)


def is_valid_correlation(c: np.ndarray, min_eigen: float = 1e-8, tol: float = 1e-10) -> bool:
    return bool(
        np.allclose(c, c.T, atol=tol)
        and np.allclose(np.diag(c), 1.0, atol=tol)
        and np.all(np.abs(c) <= 1.0 + tol)
        and np.linalg.eigvalsh((c + c.T) / 2).min() > min_eigen
    )


def nearest_correlation(
    a: np.ndarray, min_eigen: float = 1e-8, max_iter: int = 1000, tol: float = 1e-12
) -> np.ndarray:
    """Higham (2002) alternating projections with Dykstra's correction: the nearest (in
    Frobenius norm) symmetric matrix with unit diagonal and eigenvalues >= min_eigen."""
    y = (a + a.T) / 2
    correction = np.zeros_like(y)
    x = y.copy()
    for _ in range(max_iter):
        r = y - correction
        vals, vecs = np.linalg.eigh((r + r.T) / 2)
        x = (vecs * np.maximum(vals, min_eigen)) @ vecs.T  # projection onto PSD (with floor)
        correction = x - r
        y_new = x.copy()
        np.fill_diagonal(y_new, 1.0)  # projection onto unit diagonal
        if np.linalg.norm(y_new - y, "fro") < tol:
            y = y_new
            break
        y = y_new
    # The unit-diagonal step can leave tiny negative eigenvalues: rescale a final PSD
    # projection back to unit diagonal.
    vals, vecs = np.linalg.eigh((y + y.T) / 2)
    z = (vecs * np.maximum(vals, min_eigen * 10)) @ vecs.T
    d = np.sqrt(np.diag(z))
    out: np.ndarray = z / np.outer(d, d)
    return out


# --------------------------------------------------------------------------- the run


def compute_stats(returns: pd.DataFrame, config: StatsConfig | None = None) -> Stats:
    config = config or StatsConfig()
    names = [c for c in config.classes if c in returns.columns and returns[c].notna().sum() > 2]
    notes: list[str] = []
    missing = [c for c in config.classes if c not in names]
    if missing:
        notes.append(f"no returns for {missing}: left out")

    series: dict[str, pd.Series] = {}
    phi: dict[str, float] = {}
    for c in names:
        r = returns[c]
        if c in config.desmooth:
            r_out, phi[c] = geltner(r, config.max_phi)
            series[c] = r_out
        else:
            series[c], phi[c] = r.dropna(), 0.0

    vol_raw, vol = {}, {}
    for c in names:
        x = series[c].to_numpy(dtype=float)
        var = blended_cov(x, x, config.half_life_months, config.ewma_weight)
        vol_raw[c] = float(np.sqrt(max(var, 0.0) * 12))
        floor = float(config.vol_floors.get(c, 0.0))
        vol[c] = max(vol_raw[c], floor)
        if vol[c] > vol_raw[c]:
            notes.append(f"{c}: volatility floor {floor:.1%} applied (estimate {vol_raw[c]:.1%})")

    n = len(names)
    corr = np.eye(n)
    overlap = np.zeros((n, n), dtype=int)
    for i in range(n):
        overlap[i, i] = len(series[names[i]])
        for j in range(i + 1, n):
            pair = pd.concat([series[names[i]], series[names[j]]], axis=1, join="inner").dropna()
            overlap[i, j] = overlap[j, i] = len(pair)
            if len(pair) < config.min_overlap:
                notes.append(
                    f"{names[i]}/{names[j]}: {len(pair)} shared months < {config.min_overlap}: "
                    "correlation set to 0"
                )
                continue
            a, b = pair.iloc[:, 0].to_numpy(), pair.iloc[:, 1].to_numpy()
            cov = blended_cov(a, b, config.half_life_months, config.ewma_weight)
            va = blended_cov(a, a, config.half_life_months, config.ewma_weight)
            vb = blended_cov(b, b, config.half_life_months, config.ewma_weight)
            corr[i, j] = corr[j, i] = float(np.clip(cov / np.sqrt(va * vb), -1.0, 1.0))

    common = pd.concat([series[c] for c in names], axis=1, join="inner").dropna()
    if len(common) >= 2:
        z = (common - common.mean()) / common.std(ddof=0)
        delta = ledoit_wolf_shrinkage(z.to_numpy(dtype=float))
    else:
        delta = 1.0
        notes.append("no months shared by all classes: full shrinkage to the identity")
    pair_delta = np.ones((n, n))
    for i in range(n):
        for j in range(n):
            if i != j and overlap[i, j] > 0:
                pair_delta[i, j] = min(1.0, delta * max(len(common), 1) / overlap[i, j])
    corr = (1 - pair_delta) * corr + pair_delta * np.eye(n)
    np.fill_diagonal(corr, 1.0)

    repaired = not is_valid_correlation(corr, config.min_eigen)
    if repaired:
        corr = nearest_correlation(corr, config.min_eigen)
        notes.append("correlation matrix repaired (Higham nearest correlation)")
    if not is_valid_correlation(corr, config.min_eigen * 0.1):
        raise ValueError("correlation matrix still invalid after repair")

    return Stats(
        vol=vol,
        vol_raw=vol_raw,
        corr=pd.DataFrame(corr, index=names, columns=names),
        phi=phi,
        shrinkage=delta,
        common_months=len(common),
        overlap=pd.DataFrame(overlap, index=names, columns=names),
        repaired=repaired,
        notes=notes,
    )


def validate(corr: Any, min_eigen: float = 1e-8) -> np.ndarray:
    """Re-validate a matrix after any manual change; repair it if needed (spec §4.5)."""
    c = np.asarray(corr, dtype=float)
    return c if is_valid_correlation(c, min_eigen) else nearest_correlation(c, min_eigen)


def summary_rows(stats: Stats) -> Sequence[dict[str, Any]]:
    return [
        {
            "class": c,
            "vol": stats.vol[c],
            "vol_raw": stats.vol_raw[c],
            "phi": stats.phi[c],
            "months": int(stats.overlap.loc[c, c]),
        }
        for c in stats.corr.index
    ]
