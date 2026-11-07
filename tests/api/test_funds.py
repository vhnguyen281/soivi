"""GET /funds/stats: approved group statistics only; per-fund rows never leave the review app."""

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.funds.release import FundStatsError, approve
from core.models import FundStatsRun

pytestmark = pytest.mark.db

PAYLOAD = {
    "as_of": "2026-10-31",
    "horizons": [1, 3, 5],
    "groups": {
        "equity_fund": {
            "count": 2,
            "benchmark": "eq_large",
            "horizons": {"3": {"stats": {"n": 2, "p50": 12.5}, "benchmark": 24.1, "beat": 0.0}},
            "volatility": None,
            "max_drawdown": None,
        }
    },
    "benchmarks": {"eq_large": {"1": 0.7, "3": 24.1, "5": 6.3}},
    "funds": [
        {
            "ticker": "AAA",
            "group": "equity_fund",
            "manager": "X",
            "first": "2016-01",
            "returns": {"1": 1.0, "3": 12.5, "5": None},
            "volatility": 15.0,
            "max_drawdown": -20.0,
        }
    ],
}


def run(db: Session) -> FundStatsRun:
    r = FundStatsRun(
        created_by="QA",
        as_of=dt.date(2026, 10, 31),
        code_version="test",
        inputs_sha256="0" * 64,
        inputs={},
        payload=PAYLOAD,
    )
    db.add(r)
    db.flush()
    return r


def test_drafts_never_show_and_releases_carry_derived_fund_rows(
    client: TestClient, db: Session
) -> None:
    draft = run(db)
    assert client.get("/funds/stats").status_code == 404
    with pytest.raises(FundStatsError):
        approve(db, draft.id, "  ")
    release = approve(db, draft.id, "Nguyễn Văn A")
    db.flush()
    body = client.get("/funds/stats").json()
    assert body["approved_by"] == "Nguyễn Văn A"
    assert body["payload_sha256"] == release.payload_sha256
    assert body["groups"]["equity_fund"]["count"] == 2
    assert body["funds"][0]["ticker"] == "AAA" and "nav" not in body["funds"][0]
    assert "vnstock" in body["source"]
    assert body["disclaimer"]["vi"] and body["method"]
    with pytest.raises(FundStatsError):
        approve(db, draft.id, "Nguyễn Văn A")


def test_runs_and_releases_are_append_only(db: Session) -> None:
    r = run(db)
    approve(db, r.id, "Nguyễn Văn A")
    db.flush()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE fund_stats_release SET approved_by = 'x'"))


def test_reuse_same_returns_the_latest_run_when_nothing_changed(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import pandas as pd

    import core.funds.release as rel

    idx = pd.date_range("2020-10-31", "2026-10-31", freq="ME")
    levels = {"fund_nav_aaa": pd.Series(range(100, 100 + len(idx)), index=idx, dtype=float)}
    monkeypatch.setattr(
        rel,
        "load_universe",
        lambda: [{"ticker": "AAA", "code": "fund_nav_aaa", "group": "equity_fund", "manager": "X"}],
    )
    monkeypatch.setattr(rel, "load_observations", lambda session, codes: levels)
    monkeypatch.setattr(rel, "benchmarks", lambda session: {})
    monkeypatch.setattr(
        rel, "input_manifest", lambda session, codes: {"fund_nav_aaa": {"sha256": "x"}}
    )
    first = rel.create_run(db, "QA", reuse_same=True)
    again = rel.create_run(db, "QA", reuse_same=True)
    assert again.id == first.id
    assert rel.create_run(db, "QA").id != first.id
