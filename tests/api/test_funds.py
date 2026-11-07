"""GET /funds/stats: approved group statistics only; per-fund rows never leave the review app."""

import datetime as dt

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
