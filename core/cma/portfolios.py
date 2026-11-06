"""Model portfolios from an approved VNCMA release (Phase A of goals-based planning).

For each target volatility: maximise the arithmetic expected return subject to
volatility <= target, weights summing to 1, no short sales, and per-class bounds
(data/cma/portfolios.yaml). Inputs are the release's arithmetic returns, volatilities
and correlation matrix, for the classes an optimiser may use (spec §3).

Resampling (Michaud 1998, "Efficient Asset Management"): draw `draws` histories of
`months` monthly returns from N(mu/12, Sigma/12) with a fixed seed, re-estimate mu
and Sigma on each, optimise, and average the weights per target. The average is
feasible (the constraints are convex) and moves far less between releases than a
single optimisation. Reported return and volatility use the release's own inputs.

Weights are published in whole percent (largest-remainder rounding, summing to 100).
Asset-class level only: never products or tickers. Floats only here (CLAUDE.md).
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy.optimize import minimize

DEFAULT_PATH = Path("data/cma/portfolios.yaml")
DISCLAIMER_VI = (
    "Danh mục mẫu ở cấp lớp tài sản, dựa trên giả định VNCMA, để tham khảo và học cách phân bổ. "
    "Đây không phải lời khuyên đầu tư cho cá nhân bạn; hãy cân nhắc mục tiêu, thời gian "
    "và khả năng chịu rủi ro của mình."
)
DISCLAIMER_EN = (
    "Asset-class model portfolios built on the VNCMA assumptions, for reference and learning. "
    "Not personal investment advice."
)


class PortfolioError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    id: str
    vol: float
    name_vi: str
    name_en: str


@dataclass(frozen=True)
class PortfolioConfig:
    methodology_version: str
    bounds: dict[str, tuple[float, float]]
    targets: list[Target]
    draws: int
    months: int
    seed: int
    raw: dict[str, Any]

    @property
    def classes(self) -> list[str]:
        return list(self.bounds)

    @property
    def sha256(self) -> str:
        text = json.dumps(self.raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()


def parse_config(doc: Mapping[str, Any]) -> PortfolioConfig:
    errors = []
    bounds: dict[str, tuple[float, float]] = {}
    for cls, pair in (doc.get("bounds") or {}).items():
        lo, hi = (float(x) for x in pair)
        if not 0 <= lo <= hi <= 1:
            errors.append(f"bounds {cls}: need 0 <= min <= max <= 1")
        bounds[str(cls)] = (lo, hi)
    if sum(lo for lo, _ in bounds.values()) > 1 or sum(hi for _, hi in bounds.values()) < 1:
        errors.append("bounds: the minimums must sum to <= 1 and the maximums to >= 1")
    targets = [
        Target(str(p["id"]), float(p["vol"]), str(p["name_vi"]), str(p["name_en"]))
        for p in doc.get("portfolios") or []
    ]
    if not targets:
        errors.append("portfolios: at least one target")
    r = doc.get("resampling") or {}
    if errors:
        raise PortfolioError("; ".join(errors))
    return PortfolioConfig(
        methodology_version=str(doc.get("methodology_version", "1.0.0")),
        bounds=bounds,
        targets=sorted(targets, key=lambda t: t.vol),
        draws=int(r.get("draws", 0)),
        months=int(r.get("months", 120)),
        seed=int(r.get("seed", 0)),
        raw=dict(doc),
    )


def load_config(path: Path = DEFAULT_PATH) -> PortfolioConfig:
    return parse_config(yaml.safe_load(path.read_text("utf-8")) or {})


# --------------------------------------------------------------------------- optimiser


def optimise(
    mu: np.ndarray, cov: np.ndarray, bounds: Sequence[tuple[float, float]], target_vol: float
) -> np.ndarray:
    """Max mu'w s.t. w'Cov w <= target^2, sum w = 1, bounds. If the target is below the
    lowest volatility the bounds allow, the minimum-variance portfolio."""
    n = len(mu)
    lo = np.array([b[0] for b in bounds])
    start = lo + (1 - lo.sum()) * np.ones(n) / n
    budget = {"type": "eq", "fun": lambda w: w.sum() - 1}
    minvar = minimize(
        lambda w: w @ cov @ w, start, bounds=bounds, constraints=[budget], method="SLSQP"
    )
    if not minvar.success:
        raise PortfolioError(f"minimum-variance portfolio failed: {minvar.message}")
    if np.sqrt(minvar.x @ cov @ minvar.x) >= target_vol:
        return np.asarray(minvar.x)
    risk = {"type": "ineq", "fun": lambda w: target_vol**2 - w @ cov @ w}
    best = minimize(
        lambda w: -(w @ mu), minvar.x, bounds=bounds, constraints=[budget, risk], method="SLSQP"
    )
    if not best.success:
        raise PortfolioError(f"optimisation at {target_vol:.0%} failed: {best.message}")
    return np.clip(np.asarray(best.x), 0, 1)


def resampled(mu: np.ndarray, cov: np.ndarray, cfg: PortfolioConfig) -> dict[str, np.ndarray]:
    """target id -> weights (plain optimisation when draws = 0)."""
    bounds = [cfg.bounds[c] for c in cfg.classes]
    if cfg.draws <= 0:
        return {t.id: optimise(mu, cov, bounds, t.vol) for t in cfg.targets}
    rng = np.random.default_rng(cfg.seed)
    sums = {t.id: np.zeros(len(mu)) for t in cfg.targets}
    for _ in range(cfg.draws):
        sample = rng.multivariate_normal(mu / 12, cov / 12, size=cfg.months)
        mu_s = sample.mean(axis=0) * 12
        cov_s = np.cov(sample, rowvar=False) * 12
        for t in cfg.targets:
            sums[t.id] += optimise(mu_s, cov_s, bounds, t.vol)
    return {k: v / cfg.draws for k, v in sums.items()}


def whole_percent(weights: np.ndarray) -> list[int]:
    """Largest-remainder rounding to whole percent that sums to exactly 100."""
    raw = np.asarray(weights) / np.sum(weights) * 100
    floor = np.floor(raw).astype(int)
    for i in np.argsort(-(raw - floor))[: 100 - int(floor.sum())]:
        floor[i] += 1
    return [int(x) for x in floor]


# --------------------------------------------------------------------------- from a release


def release_inputs(
    release: Mapping[str, Any], classes: Sequence[str]
) -> tuple[np.ndarray, np.ndarray]:
    """(arithmetic returns, covariance) as decimals, from a release payload."""
    by_id = {c["id"]: c for c in release["classes"]}
    missing = [c for c in classes if c not in by_id or by_id[c].get("arithmetic_return") is None]
    if missing:
        raise PortfolioError(f"the release has no arithmetic return or volatility for {missing}")
    mu = np.array([float(by_id[c]["arithmetic_return"]) / 100 for c in classes])
    vol = np.array([float(by_id[c]["volatility"]) / 100 for c in classes])
    order = release["correlation"]["classes"]
    idx = [order.index(c) for c in classes]
    corr = np.array(release["correlation"]["matrix"], dtype=float)[np.ix_(idx, idx)]
    return mu, np.outer(vol, vol) * corr


def build(release: Mapping[str, Any], cfg: PortfolioConfig) -> dict[str, Any]:
    """The model-portfolio payload for one release (JSON-ready, rates as decimal strings)."""
    classes = cfg.classes
    mu, cov = release_inputs(release, classes)
    names = {c["id"]: c["name"] for c in release["classes"]}
    out = []
    weights = resampled(mu, cov, cfg)
    for t in cfg.targets:
        pct = whole_percent(weights[t.id])
        w = np.array(pct) / 100
        arith = float(w @ mu)
        vol = float(np.sqrt(w @ cov @ w))
        out.append(
            {
                "id": t.id,
                "name": t.name_vi,
                "name_en": t.name_en,
                "target_volatility": f"{100 * t.vol:.2f}",
                "weights": [
                    {"asset_class": c, "name": names.get(c, c), "percent": p}
                    for c, p in zip(classes, pct, strict=True)
                ],
                "expected_return_arithmetic": f"{100 * arith:.2f}",
                "expected_return": f"{100 * (arith - vol**2 / 2):.2f}",
                "volatility": f"{100 * vol:.2f}",
            }
        )
    return {
        "release": release["version"],
        "as_of": release["as_of"],
        "methodology_version": cfg.methodology_version,
        "vncma_methodology_version": release["methodology_version"],
        "bounds": {c: [f"{lo:.2f}", f"{hi:.2f}"] for c, (lo, hi) in cfg.bounds.items()},
        "resampling": {"draws": cfg.draws, "months": cfg.months, "seed": cfg.seed},
        "config_sha256": cfg.sha256,
        "portfolios": out,
        "disclaimer": {"vi": DISCLAIMER_VI, "en": DISCLAIMER_EN},
    }


# --------------------------------------------------------------------------- approval


def approve(session: Any, version: str, reviewer: str, cfg: PortfolioConfig | None = None) -> Any:
    """Store the model portfolios of release `version`, approved by a named reviewer.
    The caller commits."""
    from sqlalchemy import select

    from core.cma.report import payload_sha256
    from core.cma.run import code_version
    from core.models import CmaPortfolioSet, CmaRelease

    reviewer = reviewer.strip()
    if not reviewer:
        raise PortfolioError("a named reviewer is required")
    release = session.scalar(select(CmaRelease).where(CmaRelease.version == version))
    if release is None:
        raise PortfolioError(f"no VNCMA release {version!r}")
    if session.scalar(select(CmaPortfolioSet).where(CmaPortfolioSet.release_id == release.id)):
        raise PortfolioError(f"the model portfolios of {version} are already approved")
    cfg = cfg or load_config()
    doc = build(release.payload, cfg)
    doc["approved_by"] = reviewer
    row = CmaPortfolioSet(
        release_id=release.id,
        methodology_version=cfg.methodology_version,
        config_sha256=cfg.sha256,
        code_version=code_version(),
        approved_by=reviewer,
        payload=doc,
        payload_sha256=payload_sha256(doc),
    )
    session.add(row)
    session.flush()
    return row
