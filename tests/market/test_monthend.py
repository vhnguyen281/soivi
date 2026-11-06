"""Month-end rules (docs/vncma/design-market-data.md §3)."""

import datetime as dt
from decimal import Decimal

from core.enums import Frequency, MonthEndRule
from pipeline.market.monthend import Point, month_ends, period_end, to_periods

D = dt.date
L, P = MonthEndRule.LAST_ON_OR_BEFORE, MonthEndRule.PERIOD_VALUE
M, Q, Y = Frequency.MONTHLY, Frequency.QUARTERLY, Frequency.YEARLY
TODAY = D(2026, 11, 6)


def pts(*pairs: tuple[dt.date, str]) -> list[Point]:
    return [Point(d, Decimal(v)) for d, v in pairs]


def test_period_end() -> None:
    assert period_end(D(2024, 2, 10), M) == D(2024, 2, 29)
    assert period_end(D(2026, 5, 1), Q) == D(2026, 6, 30)
    assert period_end(D(2026, 1, 1), Y) == D(2026, 12, 31)


def test_month_ends_inclusive() -> None:
    assert month_ends(D(2025, 11, 15), D(2026, 1, 3)) == [
        D(2025, 11, 30),
        D(2025, 12, 31),
        D(2026, 1, 31),
    ]


def test_last_on_or_before_takes_the_last_trading_day() -> None:
    # 31/12/2018 was a holiday: the value of 28/12 is the December value.
    points = pts((D(2018, 12, 27), "5.1"), (D(2018, 12, 28), "5.2"), (D(2019, 1, 31), "5.3"))
    result = to_periods(points, L, M, 7, TODAY)
    assert result.values[D(2018, 12, 31)].obs_date == D(2018, 12, 28)
    assert result.values[D(2018, 12, 31)].value == Decimal("5.2")
    assert result.gaps == []


def test_value_older_than_the_gap_limit_is_a_gap() -> None:
    points = pts((D(2026, 1, 20), "1"), (D(2026, 2, 27), "2"))
    result = to_periods(points, L, M, 7, TODAY)
    assert result.gaps == [D(2026, 1, 31)]
    assert list(result.values) == [D(2026, 2, 28)]


def test_weekly_nav_needs_the_wider_limit() -> None:
    points = pts((D(2026, 3, 20), "10500"))  # last NAV 11 days before the month end
    assert to_periods(points, L, M, 7, TODAY).gaps == [D(2026, 3, 31)]
    assert D(2026, 3, 31) in to_periods(points, L, M, 14, TODAY).values


def test_months_without_any_point_are_gaps() -> None:
    points = pts((D(2026, 1, 30), "1"), (D(2026, 4, 30), "4"))
    assert to_periods(points, L, M, 7, TODAY).gaps == [D(2026, 2, 28), D(2026, 3, 31)]


def test_open_month_is_never_stored() -> None:
    points = pts((D(2026, 10, 31), "1"), (D(2026, 11, 5), "2"))
    result = to_periods(points, L, M, 7, TODAY)
    assert list(result.values) == [D(2026, 10, 31)]


def test_period_value_for_monthly_and_yearly() -> None:
    fed = pts((D(2026, 8, 1), "4.33"), (D(2026, 9, 1), "4.1"))  # dated the 1st
    result = to_periods(fed, P, M, None, TODAY)
    assert result.values[D(2026, 8, 31)].value == Decimal("4.33")
    assert result.values[D(2026, 8, 31)].obs_date == D(2026, 8, 1)
    gdp = pts((D(2024, 12, 31), "7.09"), (D(2025, 12, 31), "8.02"))
    assert list(to_periods(gdp, P, Y, None, TODAY).values) == [D(2024, 12, 31), D(2025, 12, 31)]


def test_daily_spot_values_keep_today_and_have_no_gaps() -> None:
    points = pts((D(2026, 11, 2), "25600"), (D(2026, 11, 6), "25615"), (D(2026, 11, 7), "1"))
    result = to_periods(points, P, Frequency.DAILY, None, TODAY)
    assert list(result.values) == [D(2026, 11, 2), D(2026, 11, 6)]
    assert result.gaps == []
