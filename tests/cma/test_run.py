"""`market compute`: a stored, append-only run whose inputs are hashed (VNCMA Prompt 7)."""

import copy
import datetime as dt
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.cma.config import parse_config
from core.cma.run import create_run, input_manifest
from core.models import CmaAdjustment, CmaRun, MarketObservation, MarketSeries, Snapshot, Source
from core.seed import load_market, parse_market
from tests.cma.test_blocks import AS_OF, DOC, observations

pytestmark = pytest.mark.db
SEEDS = Path(__file__).resolve().parents[2] / "data" / "seeds" / "market_series.yaml"


def store(db: Session, series: dict[str, pd.Series]) -> None:
    load_market(db, *parse_market(SEEDS))
    source = db.scalar(select(Source).where(Source.variant == "vnstock"))
    assert source is not None
    snap = Snapshot(
        source_id=source.id,
        url="vnstock:test",
        fetched_at=dt.datetime(2026, 11, 6, tzinfo=dt.UTC),
        content_type="application/json",
        sha256="0" * 64,
        storage_key="MARKET/test.json",
        size_bytes=1,
    )
    db.add(snap)
    db.flush()
    ids = {code: id_ for code, id_ in db.execute(select(MarketSeries.code, MarketSeries.id))}
    for code, s in series.items():
        for end, value in s.dropna().items():
            db.add(
                MarketObservation(
                    series_id=ids[code],
                    period_end=end.date(),
                    obs_date=end.date(),
                    value=Decimal(str(round(float(value), 6))),
                    snapshot_id=snap.id,
                )
            )
    db.flush()


def market_data() -> dict[str, pd.Series]:
    rng = np.random.default_rng(1)
    idx = pd.date_range(end=AS_OF, periods=150, freq="ME")
    walk = lambda: pd.Series(100 * np.exp(np.cumsum(rng.normal(0.005, 0.05, 150))), index=idx)  # noqa: E731
    return {
        **observations(),
        "vn30_close": walk(),
        "vnmid_close": walk(),
        "vnsml_close": walk(),
        "fund_nav_dcbf": walk(),
        "fund_nav_vff": walk(),
        "fed_rate": pd.Series(4.0, index=idx),
        "sp500_price": walk(),
        "sp500_dividend": walk() / 50,
        "hnx_par_10y": pd.Series(4.0 + rng.normal(0, 0.2, 150), index=idx),
    }


def test_compute_stores_a_traceable_append_only_run(db: Session) -> None:
    store(db, market_data())
    doc = copy.deepcopy(DOC)
    doc["adjustments"] = [
        {"asset_class": "eq_large", "delta_pp": -0.5, "reason": "AI test", "author": "QA"}
    ]
    run = create_run(db, parse_config(doc), "QA")
    db.flush()
    assert run.as_of == AS_OF.date() and run.created_by == "QA"
    assert run.output["classes"]["eq_large"]["adjustment"] == -0.5
    assert run.inputs["series"]["dp_vn30"]["count"] == 1
    assert len(run.inputs_sha256) == 64 and run.config_sha256 == parse_config(doc).sha256
    (adj,) = db.scalars(select(CmaAdjustment).where(CmaAdjustment.run_id == run.id))
    assert adj.delta_pp == Decimal("-0.50") and adj.reason == "AI test"
    assert input_manifest(db, ["dp_vn30"]) == {"dp_vn30": run.inputs["series"]["dp_vn30"]}

    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(text("UPDATE cma_run SET created_by = 'x' WHERE id = :id"), {"id": run.id})
    again = create_run(db, parse_config(doc), "QA")
    assert again.inputs_sha256 == run.inputs_sha256 and again.output == run.output
    assert db.scalar(select(CmaRun).where(CmaRun.id == again.id)) is not None
