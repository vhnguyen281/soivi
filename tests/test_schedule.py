"""pipeline/schedule: slots in Asia/Ho_Chi_Minh and when a source is due. Offline."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from core.enums import SourceKind
from core.models import Source
from pipeline.schedule import DAILY_TWICE, MONTHLY, WEEKLY, is_due, last_slot, next_slot

VN = ZoneInfo("Asia/Ho_Chi_Minh")


def vn(y: int, m: int, d: int, h: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(y, m, d, h, minute, tzinfo=VN)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (vn(2026, 10, 28, 6, 59), vn(2026, 10, 27, 15)),  # before 07:00: yesterday 15:00
        (vn(2026, 10, 28, 7, 0), vn(2026, 10, 28, 7)),
        (vn(2026, 10, 28, 14, 30), vn(2026, 10, 28, 7)),
        (vn(2026, 10, 28, 15, 1), vn(2026, 10, 28, 15)),
        (vn(2026, 10, 28, 23, 0), vn(2026, 10, 28, 15)),
    ],
)
def test_savings_twice_a_day_vietnam_time(now: dt.datetime, expected: dt.datetime) -> None:
    assert last_slot(DAILY_TWICE, now, VN) == expected
    assert last_slot(DAILY_TWICE, now, VN).tzinfo == dt.UTC  # stored as UTC


def test_vietnam_slot_in_utc() -> None:
    # 07:00 in Vietnam (UTC+7, no DST) is 00:00 UTC.
    assert last_slot(DAILY_TWICE, vn(2026, 10, 28, 8), VN) == dt.datetime(
        2026, 10, 28, 0, tzinfo=dt.UTC
    )


def test_weekly_and_monthly() -> None:
    wednesday = vn(2026, 10, 28, 10)
    assert last_slot(WEEKLY, wednesday, VN) == vn(2026, 10, 26, 7)  # Monday
    assert next_slot(WEEKLY, wednesday, VN) == vn(2026, 11, 2, 7)
    assert last_slot(MONTHLY, wednesday, VN) == vn(2026, 10, 1, 7)
    assert next_slot(MONTHLY, wednesday, VN) == vn(2026, 11, 1, 7)
    assert next_slot(DAILY_TWICE, vn(2026, 10, 28, 15, 0), VN) == vn(2026, 10, 29, 7)


def src(kind: SourceKind = SourceKind.SAVINGS_RATE_PAGE, **kw: object) -> Source:
    return Source(kind=kind, cadence_hours=12, consecutive_failures=0, **kw)


NOW = vn(2026, 10, 28, 15, 5)  # bank sources are monthly: the latest slot was 1 Oct 07:00


@pytest.mark.parametrize(
    ("source", "due"),
    [
        (src(), True),  # never tried
        (src(last_attempt_at=vn(2026, 10, 1, 7, 1), last_status="parsed"), False),  # done
        (src(last_attempt_at=vn(2026, 10, 20, 9, 0), last_status="unchanged"), False),
        # Last run in September (Mac was off on 1 Oct): caught up on the next run.
        (src(last_attempt_at=vn(2026, 9, 15, 10, 0), last_status="parsed"), True),
        # Failed long after the slot: no automatic retry until next month.
        (src(last_attempt_at=vn(2026, 10, 28, 15, 1), last_status="fetch_failed"), False),
        (
            src(
                kind=SourceKind.CARD_TARIFF_PDF,
                last_attempt_at=vn(2026, 10, 26, 7, 2),
                last_status="parsed",
            ),
            False,
        ),
        (
            src(
                kind=SourceKind.CARD_PRODUCT_PAGE,
                last_attempt_at=vn(2026, 9, 21, 7, 2),
                last_status="parsed",
            ),
            True,
        ),
        (
            src(
                kind=SourceKind.OFFICIAL,
                last_attempt_at=vn(2026, 10, 1, 7, 3),
                last_status="parsed",
            ),
            False,
        ),
    ],
)
def test_is_due(source: Source, due: bool) -> None:
    assert is_due(source, NOW, VN) == due


def test_failed_run_is_retried_hourly_for_six_hours() -> None:
    failed = src(last_attempt_at=vn(2026, 11, 1, 7, 1), last_status="parse_failed")
    assert not is_due(failed, vn(2026, 11, 1, 7, 50), VN)
    assert is_due(failed, vn(2026, 11, 1, 8, 2), VN)
    late = src(last_attempt_at=vn(2026, 11, 1, 12, 0), last_status="fetch_failed")
    assert is_due(late, vn(2026, 11, 1, 13, 0), VN)  # 6 h after the 07:00 slot
    assert not is_due(late, vn(2026, 11, 1, 13, 30), VN)  # window over: next slot
    assert is_due(late, vn(2026, 12, 1, 7, 0), VN)
