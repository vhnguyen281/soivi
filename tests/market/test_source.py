"""Market fetchers, offline: vnstock (fake client), HNX and World Bank (saved pages)."""

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from pipeline.fetch.polite import FetchError
from pipeline.market.client import MarketDataError, Step, describe
from pipeline.market.source import (
    HNX_ENDPOINT,
    HnxFetcher,
    VnstockFetcher,
    WorldBankFetcher,
    find_link,
    parse_hnx,
    parse_pink_sheet,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
TODAY = dt.date(2026, 11, 6)
VN = "Asia/Ho_Chi_Minh"
REQUEST = {
    "call": [["Market", [], {}], ["index", ["VN30"], {}], ["ohlcv", [], {"limit": 10000}]],
    "date_field": "time",
}


def frame(days: Sequence[str], closes: Sequence[float], requested_at: str = "t1") -> pd.DataFrame:
    df = pd.DataFrame({"time": pd.to_datetime(list(days)).tz_localize(VN), "close": list(closes)})
    df.attrs.update(
        {"source": "vci", "requested_at": requested_at, "latency_ms": requested_at, "end": "x"}
    )
    return df


class ProviderError(Exception):
    """Named like vnstock's transient error."""


class InputError(Exception):
    """Named like vnstock's bad-parameter error."""


class FakeClient:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[str] = []

    def status(self) -> Any:
        raise NotImplementedError

    def latest_index_close(self, symbol: str) -> Any:
        raise NotImplementedError

    def call(self, chain: Sequence[Step]) -> Any:
        self.calls.append(describe(chain))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise MarketDataError(f"{describe(chain)} failed: {answer}") from answer
        return answer


def fetcher(client: FakeClient) -> VnstockFetcher:
    return VnstockFetcher(client, sleep=lambda _: None)


def test_vnstock_points_drop_the_open_month() -> None:
    df = frame(["2026-09-30", "2026-10-30", "2026-11-05"], [1800.5, 1865.23, 1842.19])
    got = fetcher(FakeClient(df)).fetch(REQUEST, ["close"], set(), TODAY)
    assert got.url.startswith('vnstock:Market().index("VN30")')
    assert [p.date for p in got.points["close"]] == [dt.date(2026, 9, 30), dt.date(2026, 10, 30)]
    assert got.points["close"][1].value == Decimal("1865.23")
    assert b"2026-11-05" not in (got.payload or b"")


def test_vnstock_payload_ignores_requested_at_and_open_month_rows() -> None:
    a = frame(["2026-10-30", "2026-11-05"], [1, 2], requested_at="t1")
    b = frame(["2026-10-30", "2026-11-06"], [1, 3], requested_at="t2")
    first = fetcher(FakeClient(a)).fetch(REQUEST, ["close"], set(), TODAY)
    second = fetcher(FakeClient(b)).fetch(REQUEST, ["close"], set(), TODAY)
    assert first.sha256 == second.sha256


def test_vnstock_retries_transient_errors_only() -> None:
    df = frame(["2026-10-30"], [1])
    client = FakeClient(ProviderError("HTTP 502"), df)
    waits: list[float] = []
    got = VnstockFetcher(client, sleep=waits.append).fetch(REQUEST, ["close"], set(), TODAY)
    assert len(client.calls) == 2 and got.points
    assert waits == [5.0, 1.0]  # backoff, then the pause before the next call
    with pytest.raises(MarketDataError, match=r"InputError|bad symbol"):
        fetcher(FakeClient(InputError("bad symbol"))).fetch(REQUEST, ["close"], set(), TODAY)


@pytest.mark.parametrize(
    ("df", "message"),
    [
        (frame([], []), "empty table"),
        (frame(["2026-10-30"], [1]).drop(columns="close"), r"no column\(s\) \['close'\]"),
        (frame(["2026-11-03"], [1]), "no rows before 2026-11-01"),
        (frame(["2026-10-30"], [float("nan")]), "has no numbers"),
    ],
)
def test_vnstock_raises_instead_of_returning_partial_data(df: pd.DataFrame, message: str) -> None:
    with pytest.raises(MarketDataError, match=message) as err:
        fetcher(FakeClient(df)).fetch(REQUEST, ["close"], set(), TODAY)
    assert "VN30" in str(err.value) or "empty" in str(err.value)


# --------------------------------------------------------------------------- HNX


def hnx_page(name: str) -> str:
    return (FIXTURES / "hnx" / f"yield-curve-{name}.html").read_text("utf-8")


def test_parse_hnx_par_yields() -> None:
    curve = parse_hnx(hnx_page("30-12-2013"))
    assert curve is not None
    assert curve["par_10y"] == Decimal("9.18691378121297")
    assert curve["par_1y"] == Decimal("6.28828933355732")
    assert "par_3m" not in curve  # no par yield under one year
    assert parse_hnx(hnx_page("05-11-2026"))["par_5y"] == Decimal("4.25596085999116")  # type: ignore[index]


def test_parse_hnx_holiday_is_none_and_new_layout_raises() -> None:
    assert parse_hnx(hnx_page("31-12-2018")) is None
    with pytest.raises(MarketDataError, match="unexpected table header"):
        parse_hnx("<table><tr><th>Tenor</th><th>Yield</th></tr></table>")


class Reply:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode()


class FakeHttp:
    def __init__(self, pages: dict[str, str], default: str | None = None) -> None:
        self.pages = pages
        self.default = default  # reply for any other date (e.g. the empty holiday table)
        self.requests: list[str] = []

    def get(self, url: str, method: str = "GET", data: dict[str, str] | None = None) -> Reply:
        key = data["pDate"] if data else url
        self.requests.append(key)
        if key not in self.pages and self.default is not None:
            return Reply(self.default)
        if key not in self.pages:
            raise FetchError(f"{url} returned HTTP 404")
        return Reply(self.pages[key])


def test_hnx_steps_back_over_holidays_and_weekends_and_skips_stored_months() -> None:
    holiday, curve = hnx_page("31-12-2018"), hnx_page("30-12-2013")
    http = FakeHttp({"31/12/2018": holiday, "28/12/2018": curve, "31/01/2019": curve})
    request = {"curve": "government_bond_yield_curve", "start": "2018-11"}
    got = HnxFetcher(http).fetch(
        request, ["par_10y"], {dt.date(2018, 11, 30)}, dt.date(2019, 2, 10)
    )
    # 30 and 29/12/2018 are a weekend: not asked.
    assert http.requests == ["31/12/2018", "28/12/2018", "31/01/2019"]
    assert [p.date for p in got.points["par_10y"]] == [dt.date(2018, 12, 28), dt.date(2019, 1, 31)]
    assert got.url == HNX_ENDPOINT and got.payload


def test_hnx_with_nothing_missing_fetches_nothing() -> None:
    http = FakeHttp({})
    have = {dt.date(2026, 9, 30), dt.date(2026, 10, 31)}
    got = HnxFetcher(http).fetch({"curve": "x", "start": "2026-09"}, ["par_10y"], have, TODAY)
    assert http.requests == [] and got.payload is None


def test_hnx_network_failure_names_the_day() -> None:
    with pytest.raises(MarketDataError, match="HNX yield curve 2026-10-30"):
        HnxFetcher(FakeHttp({})).fetch(
            {"curve": "x", "start": "2026-10"}, ["par_10y"], set(), TODAY
        )


# --------------------------------------------------------------------------- World Bank


def test_find_the_pink_sheet_link() -> None:
    page = (FIXTURES / "worldbank" / "commodity-markets.html").read_text("utf-8")
    link = find_link(page, "CMO-Historical-Data-Monthly.xlsx")
    assert link.startswith("https://thedocs.worldbank.org/") and link.endswith("Monthly.xlsx")
    with pytest.raises(MarketDataError, match="expected one link"):
        find_link(page, "no-such-file.xlsx")


def test_parse_pink_sheet_gold() -> None:
    data = (FIXTURES / "worldbank" / "cmo-monthly-sample.xlsx").read_bytes()
    gold = parse_pink_sheet(data, "Monthly Prices", ["Gold"])["Gold"]
    assert gold[0].date == dt.date(1960, 1, 31) and gold[0].value == Decimal("35")
    assert gold[-1].date == dt.date(2026, 10, 31) and gold[-1].value == Decimal("4105")
    with pytest.raises(MarketDataError, match=r"not found exactly once|no header row"):
        parse_pink_sheet(data, "Monthly Prices", ["Copper"])


def test_world_bank_fetcher_stores_the_workbook() -> None:
    page = (FIXTURES / "worldbank" / "commodity-markets.html").read_text("utf-8")
    link = find_link(page, "CMO-Historical-Data-Monthly.xlsx")
    data = (FIXTURES / "worldbank" / "cmo-monthly-sample.xlsx").read_bytes()

    class Http(FakeHttp):
        def get(self, url: str, method: str = "GET", data_: Any = None, **_: Any) -> Any:
            self.requests.append(url)
            reply = Reply(page)
            if url == link:
                reply.content = data
            return reply

    request = {
        "page": "https://www.worldbank.org/x",
        "link_contains": "Monthly.xlsx",
        "sheet": "Monthly Prices",
    }
    got = WorldBankFetcher(Http({})).fetch(request, ["Gold"], set(), TODAY)
    assert got.url == link and got.payload == data
    assert got.points["Gold"][-1].value == Decimal("4105")


def test_hnx_fetches_in_chunks_and_never_asks_a_month_twice() -> None:
    curve = hnx_page("30-12-2013")
    holiday = hnx_page("31-12-2018")
    http = FakeHttp({"31/10/2025": curve, "30/12/2025": curve}, holiday)  # no November curve
    fetcher = HnxFetcher(http, months_per_fetch=2)
    request = {"curve": "x", "start": "2025-10"}
    first = fetcher.fetch(request, ["par_10y"], set(), dt.date(2026, 1, 5))
    assert first.more and [p.date for p in first.points["par_10y"]] == [dt.date(2025, 10, 31)]
    asked = len(http.requests)
    second = fetcher.fetch(request, ["par_10y"], {dt.date(2025, 10, 31)}, dt.date(2026, 1, 5))
    assert not second.more and [p.date for p in second.points["par_10y"]] == [dt.date(2025, 12, 30)]
    assert all(r.endswith("/12/2025") for r in http.requests[asked:])  # November not asked again
