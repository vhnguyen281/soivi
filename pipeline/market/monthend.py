"""One stored value per period (docs/vncma/design-market-data.md §3).

- last_on_or_before: the last value on or before the period end, at most
  `max_gap_days` earlier; otherwise the period is a gap.
- period_value: the provider already gives one value per period; the last one in
  the period wins.

Only closed periods are kept: a period whose end is before `today`. Daily series
(a spot value read once, such as today's SBV central rate) keep every day up to and
including today, and have no gaps.
"""

import calendar
import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from core.enums import Frequency, MonthEndRule


@dataclass(frozen=True)
class Point:
    date: dt.date
    value: Decimal


@dataclass(frozen=True)
class PeriodValue:
    period_end: dt.date
    obs_date: dt.date
    value: Decimal


@dataclass
class Periods:
    values: dict[dt.date, PeriodValue] = field(default_factory=dict)
    gaps: list[dt.date] = field(default_factory=list)  # closed periods with no usable value


def period_end(day: dt.date, period: Frequency) -> dt.date:
    if period is Frequency.DAILY:
        return day
    if period is Frequency.MONTHLY:
        return day.replace(day=calendar.monthrange(day.year, day.month)[1])
    if period is Frequency.QUARTERLY:
        month = ((day.month - 1) // 3 + 1) * 3
        return dt.date(day.year, month, calendar.monthrange(day.year, month)[1])
    if period is Frequency.YEARLY:
        return dt.date(day.year, 12, 31)
    raise ValueError(f"cannot store {period} periods")


def next_period_end(end: dt.date, period: Frequency) -> dt.date:
    return period_end(end + dt.timedelta(days=1), period)


def month_ends(first: dt.date, last: dt.date) -> list[dt.date]:
    """Every month end from first's month to last's month, inclusive."""
    out: list[dt.date] = []
    end = period_end(first, Frequency.MONTHLY)
    while end <= period_end(last, Frequency.MONTHLY):
        out.append(end)
        end = next_period_end(end, Frequency.MONTHLY)
    return out


def to_periods(
    points: Iterable[Point],
    rule: MonthEndRule,
    period: Frequency,
    max_gap_days: int | None,
    today: dt.date,
) -> Periods:
    last: dict[dt.date, Point] = {}
    for p in sorted(points, key=lambda p: p.date):
        last[period_end(p.date, period)] = p  # later points overwrite earlier ones
    result = Periods()
    if period is Frequency.DAILY:
        for end, p in sorted(last.items()):
            if end <= today:
                result.values[end] = PeriodValue(end, p.date, p.value)
        return result
    closed = sorted(end for end in last if end < today)
    if not closed:
        return result
    end = closed[0]
    while end <= closed[-1]:
        found = last.get(end)
        usable = found is not None and (
            rule is MonthEndRule.PERIOD_VALUE
            or (max_gap_days is not None and (end - found.date).days <= max_gap_days)
        )
        if found is not None and usable:
            result.values[end] = PeriodValue(end, found.date, found.value)
        else:
            result.gaps.append(end)
        end = next_period_end(end, period)
    return result
