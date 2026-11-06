"""The Mac's monthly VNCMA job: deadlines, the message, and no duplicate runs."""

import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.cma.config import parse_config
from core.cma.run import create_run
from core.models import CmaRun
from pipeline.market.monthly import MonthlyReport, due_deadlines, message
from tests.cma.test_blocks import DOC
from tests.cma.test_run import market_data, store


def test_deadlines_show_up_75_days_ahead() -> None:
    assert due_deadlines(dt.date(2026, 11, 6)) == []
    (soon,) = due_deadlines(dt.date(2027, 5, 7))
    assert "in 70 days" in soon and "HNX" in soon
    late = due_deadlines(dt.date(2027, 11, 1))
    assert len(late) == 2 and "overdue" in late[1] and "vnstock-quant" in late[1]


def test_message_names_the_draft_failures_and_checks() -> None:
    report = MonthlyReport(
        groups=41,
        new=60,
        failed=["hnx_par_10y: <timeout>"],
        run_id=7,
        run_is_new=True,
        as_of="2026-11-30",
        headline={"eq_large": 10.12},
        failed_checks=["FAIL: gov_bond 4.35 > cash_vnd 5.23"],
        deadlines=["2027-01-15 (in 40 days): x"],
    )
    text = message(report, "http://127.0.0.1:8001")
    assert "41 groups, 60 new, 0 revised, 1 failed" in text
    assert "&lt;timeout&gt;" in text  # Telegram HTML is escaped
    assert "http://127.0.0.1:8001/vncma/runs/7" in text and "eq_large 10.12" in text
    assert "FAIL: gov_bond" in text and "2027-01-15" in text
    assert not report.ok
    same = MonthlyReport(run_id=7, as_of="2026-11-30")
    assert "no change since" in message(same, "u") and "/vncma/runs" not in message(same, "u")


@pytest.mark.db
def test_a_second_monthly_run_with_the_same_inputs_adds_nothing(db: Session) -> None:
    store(db, market_data())
    first = create_run(db, parse_config(DOC), "job", reuse_same=True)
    again = create_run(db, parse_config(DOC), "job", reuse_same=True)
    assert again.id == first.id
    assert db.scalar(select(func.count()).select_from(CmaRun)) == 1
    forced = create_run(db, parse_config(DOC), "job")  # `market compute` always stores
    assert forced.id != first.id
