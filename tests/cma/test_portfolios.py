"""Model portfolios from a VNCMA release (Phase A): constraints, resampling, approval."""

import copy
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.cma.config import parse_config as parse_cma
from core.cma.portfolios import (
    PortfolioError,
    approve,
    build,
    optimise,
    parse_config,
    whole_percent,
)
from core.cma.release import approve as approve_release
from core.cma.run import create_run
from core.config import Settings
from pipeline.fetch.storage import MemoryStore
from review_app.app import create_app
from tests.cma.test_blocks import DOC
from tests.cma.test_run import market_data, store

CONFIG: dict[str, Any] = yaml.safe_load(Path("data/cma/portfolios.yaml").read_text("utf-8"))


def quick(draws: int = 20) -> Any:
    doc = copy.deepcopy(CONFIG)
    doc["resampling"]["draws"] = draws
    return parse_config(doc)


def release_doc() -> dict[str, Any]:
    """A small release payload with the 7 optimiser classes."""
    ids = ["cash_vnd", "gov_bond", "corp_bond", "eq_large", "eq_midsmall", "gold", "usd"]
    mu = [5.2, 4.6, 5.4, 12.3, 13.4, 6.2, 1.6]
    vol = [0.5, 7.3, 3.0, 20.6, 22.7, 19.0, 2.0]
    corr = np.eye(7)
    corr[3, 4] = corr[4, 3] = 0.63
    return {
        "version": "2027.1",
        "as_of": "2026-10-31",
        "methodology_version": "1.0.0",
        "classes": [
            {"id": i, "name": i, "arithmetic_return": f"{m:.2f}", "volatility": f"{v:.2f}"}
            for i, m, v in zip(ids, mu, vol, strict=True)
        ],
        "correlation": {"classes": ids, "matrix": corr.tolist()},
    }


def test_whole_percent_sums_to_100() -> None:
    assert sum(whole_percent(np.array([0.333, 0.333, 0.334]))) == 100
    assert whole_percent(np.array([0.125, 0.875])) in ([13, 87], [12, 88])


def test_optimiser_respects_bounds_and_target() -> None:
    mu = np.array([0.05, 0.12])
    cov = np.diag([0.005, 0.2]) ** 2
    w = optimise(mu, cov, [(0.05, 1.0), (0.0, 0.6)], 0.10)
    assert w.sum() == pytest.approx(1) and w[1] <= 0.6 + 1e-9 and w[0] >= 0.05 - 1e-9
    assert np.sqrt(w @ cov @ w) == pytest.approx(0.10, abs=1e-3)  # the risk budget binds
    low = optimise(mu, cov, [(0.05, 1.0), (0.0, 0.6)], 0.0001)  # below the minimum: min variance
    assert low[0] > 0.99


def test_build_is_deterministic_monotone_and_within_bounds() -> None:
    cfg = quick()
    a, b = build(release_doc(), cfg), build(release_doc(), cfg)
    assert a == b  # fixed seed
    risk = [float(p["volatility"]) for p in a["portfolios"]]
    ret = [float(p["expected_return_arithmetic"]) for p in a["portfolios"]]
    assert risk == sorted(risk) and ret == sorted(ret)
    for p in a["portfolios"]:
        assert sum(w["percent"] for w in p["weights"]) == 100
        for w in p["weights"]:
            lo, hi = cfg.bounds[w["asset_class"]]
            assert 100 * lo - 1 <= w["percent"] <= 100 * hi + 1  # rounding only
    assert "không phải lời khuyên đầu tư" in a["disclaimer"]["vi"]


def test_bad_bounds_are_refused() -> None:
    doc = copy.deepcopy(CONFIG)
    doc["bounds"]["gold"] = [0.5, 0.6]
    doc["bounds"]["cash_vnd"] = [0.6, 1.0]
    with pytest.raises(PortfolioError, match="minimums"):
        parse_config(doc)


@pytest.fixture
def released(db: Session) -> str:
    store(db, market_data())
    run = create_run(db, parse_cma(DOC), "QA")
    approve_release(db, run.id, "2027.1", "Nguyễn Văn A")
    db.flush()
    return "2027.1"


@pytest.fixture
def review(db: Session) -> Iterator[TestClient]:
    conn = db.connection()
    assert isinstance(conn, Connection)
    app = create_app(
        Settings(review_username="r", review_password="p", site_revalidate_url=""),
        session_factory=lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
        store=MemoryStore(),
    )
    with TestClient(app) as c:
        c.auth = ("r", "p")
        yield c


@pytest.mark.db
def test_review_app_approves_once_and_the_api_serves_it(
    db: Session, released: str, review: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.cma import portfolios

    monkeypatch.setattr(portfolios, "load_config", lambda: quick(5))
    page = review.get(f"/vncma/portfolios/{released}")
    assert page.status_code == 200 and "Bản nháp" in page.text and "Thận trọng" in page.text
    hx = {"HX-Request": "true"}
    url = f"/vncma/portfolios/{released}/approve"
    assert review.post(url, data={"reviewer_name": " "}, headers=hx).status_code == 409
    ok = review.post(url, data={"reviewer_name": "Nguyễn Văn A"}, headers=hx)
    assert ok.status_code == 204
    assert "Đã duyệt" in review.get(f"/vncma/portfolios/{released}").text
    assert review.post(url, data={"reviewer_name": "B"}, headers=hx).status_code == 409
    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(text("UPDATE cma_portfolio_set SET approved_by = 'x'"))

    from tests.api.conftest import Clock, make_client

    with make_client(db, MemoryStore(), Clock()) as api:
        body = api.get("/vncma/latest/portfolios").json()
        assert body["release"] == "2027.1" and body["approved_by"] == "Nguyễn Văn A"
        assert body["portfolios"][0]["weights"][0]["asset_class"] == "cash_vnd"
        assert api.get("/vncma/2026.1/portfolios").status_code == 404


@pytest.mark.db
def test_approve_needs_a_release(db: Session) -> None:
    with pytest.raises(PortfolioError, match="no VNCMA release"):
        approve(db, "2099.1", "A", quick(2))
