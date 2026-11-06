"""When each source should run.

Slots are wall-clock times in Asia/Ho_Chi_Minh (settings.timezone):

    savings_rate_page,
    card_tariff_pdf,
    card_product_page,
    official                   the 1st of every month at 07:00
    news feeds                 every hour 06:00-22:00 (pipeline/news, feeds.yaml)

Bank sources moved from daily/weekly to monthly on 2026-11-05 (DECISIONS.md):
the pipeline runs on the owner's Mac, not an always-on server. A source is due
when its most recent slot has passed and it hasn't been tried since, so a run
started after the 1st (Mac was off) still picks up that month's slot.

A failed attempt is retried every hour for up to 6 hours after the slot, then
waits for the next slot (the failures still count towards staleness). Re-run a
failed source by hand with --institution or --source.
"""

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from core.enums import SourceKind
from core.models import Source

RETRY_EVERY = dt.timedelta(hours=1)
RETRY_WINDOW = dt.timedelta(hours=6)
OK_STATUSES = {"parsed", "unchanged"}


@dataclass(frozen=True)
class Schedule:
    hours: tuple[int, ...]  # local hours, minute 0
    weekdays: frozenset[int] | None = None  # Monday = 0; None = every day
    monthdays: frozenset[int] | None = None  # None = every day of the month
    label: str = ""

    def matches(self, local: dt.datetime) -> bool:
        return (
            local.hour in self.hours
            and (self.weekdays is None or local.weekday() in self.weekdays)
            and (self.monthdays is None or local.day in self.monthdays)
        )


DAILY_TWICE = Schedule(hours=(7, 15), label="hằng ngày 07:00 và 15:00")
WEEKLY = Schedule(hours=(7,), weekdays=frozenset({0}), label="thứ Hai 07:00")
MONTHLY = Schedule(hours=(7,), monthdays=frozenset({1}), label="ngày 1 hằng tháng 07:00")
DAILY = Schedule(hours=(7,), label="hằng ngày 07:00")
# News feeds are config, not source rows: pipeline/news/service.py:news_due uses this.
NEWS = Schedule(hours=tuple(range(6, 23)), label="mỗi giờ 06:00–22:00")

SCHEDULES: dict[SourceKind, Schedule] = {
    SourceKind.SAVINGS_RATE_PAGE: MONTHLY,
    SourceKind.CARD_TARIFF_PDF: MONTHLY,
    SourceKind.CARD_PRODUCT_PAGE: MONTHLY,
    SourceKind.OFFICIAL: MONTHLY,
    SourceKind.NEWS_FEED: NEWS,
}


def last_slot(schedule: Schedule, now: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    """The most recent slot at or before `now` (searches back up to 32 days)."""
    local = now.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    for _ in range(32 * 24 + 1):
        if schedule.matches(local):
            return local.astimezone(dt.UTC)
        local -= dt.timedelta(hours=1)
    raise ValueError(f"schedule {schedule} has no slot in the last 32 days")


def next_slot(schedule: Schedule, now: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    local = now.astimezone(tz).replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    for _ in range(32 * 24 + 1):
        if schedule.matches(local):
            return local.astimezone(dt.UTC)
        local += dt.timedelta(hours=1)
    raise ValueError(f"schedule {schedule} has no slot in the next 32 days")


def is_due(source: Source, now: dt.datetime, tz: ZoneInfo) -> bool:
    schedule = SCHEDULES.get(source.kind)
    if schedule is None:
        return False
    slot = last_slot(schedule, now, tz)
    if source.last_attempt_at is None or source.last_attempt_at < slot:
        return True  # not tried since the slot
    if source.last_status in OK_STATUSES:
        return False  # done for this slot
    # Tried since the slot and failed: retry hourly within the window.
    return now - slot <= RETRY_WINDOW and now - source.last_attempt_at >= RETRY_EVERY
