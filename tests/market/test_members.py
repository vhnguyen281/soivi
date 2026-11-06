"""Index aggregates from members (VNCMA Prompt 7), with a fake vnstock."""

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from pipeline.market import members
from pipeline.market.client import MarketDataError, Step
from pipeline.market.source import VnstockFetcher

TODAY = dt.date(2026, 11, 10)


class FakeVnstock:
    def __init__(self, summaries: dict[str, dict[str, float]], ratios: dict[str, Any]) -> None:
        self.summaries, self.ratios, self.calls = summaries, ratios, 0

    def __call__(self, chain: Sequence[Step]) -> Any:
        self.calls += 1
        head, last = chain[0][0], chain[-1][0]
        if last == "members":
            return pd.DataFrame({"symbol": sorted(self.summaries)})
        symbol = chain[1][1][0]  # type: ignore[index]
        if head == "Market":
            row = self.summaries[symbol]
            if not row:
                raise MarketDataError(f"summary {symbol} failed")
            return pd.DataFrame([row])
        return self.ratios[symbol]


def ratio_table(rows: dict[str, tuple[float, float]]) -> pd.DataFrame:
    out = []
    for period, (pe, cap) in rows.items():
        out.append({"period": period, "id": "RT_VALUE_PE", "value": pe})
        out.append({"period": period, "id": "RT_VALUE_MARKET_CAP", "value": cap})
        out.append({"period": period, "id": "RT_VALUE_PB", "value": 1.0})
    return pd.DataFrame(out)


SUMMARIES = {
    "AAA": {"market_cap": 300.0, "dividend_yield": 0.04, "pe": 10.0},
    "BBB": {"market_cap": 100.0, "dividend_yield": 0.0, "pe": -5.0},  # a loss-maker
    "CCC": {"market_cap": 100.0, "dividend_yield": None, "pe": 20.0},  # type: ignore[dict-item]
}


def test_summary_is_cap_weighted_and_losses_count() -> None:
    payload, points = members.summary(FakeVnstock(SUMMARIES, {}), "VNX", TODAY)
    (dp,) = points["dividend_yield"]
    assert dp.date == TODAY and dp.value == Decimal("2.4")  # 0.04*300/500 = 2.4%
    # earnings: 30 - 20 + 5 = 15; caps 500 -> P/E 33.33
    assert float(points["pe"][0].value) == pytest.approx(500 / 15)
    assert payload["members"] == ["AAA", "BBB", "CCC"] and payload["missing"] == {}


def test_too_few_members_with_data_raises() -> None:
    broken = {**SUMMARIES, "DDD": {}, "EEE": {}}
    with pytest.raises(MarketDataError, match="only 3 of 5"):
        members.summary(FakeVnstock(broken, {}), "VNX", TODAY)
    ok = {**SUMMARIES, "AAB": dict(SUMMARIES["AAA"]), "AAC": dict(SUMMARIES["AAA"]), "DDD": {}}
    payload, _ = members.summary(FakeVnstock(ok, {}), "VNX", TODAY)  # 5 of 6 is enough
    assert list(payload["missing"]) == ["DDD"]


def test_ratio_builds_closed_quarters_with_enough_members() -> None:
    ratios = {
        "AAA": ratio_table({"2017-Q4": (8.0, 50.0), "2026-Q2": (10.0, 300.0), "2026-Q3": (9, 1)}),
        "BBB": ratio_table({"2026-Q2": (20.0, 100.0), "2025": (5.0, 1.0)}),
        "CCC": ratio_table({"2026-Q2": (25.0, 100.0)}),
    }
    payload, points = members.ratio(FakeVnstock(SUMMARIES, ratios), "VNX", TODAY)
    # 2017-Q4 has 1 of 3 members (gap); 2026-Q3 closes 45 days after 30 Sep (mid-Nov).
    assert [p.date for p in points["pe"]] == [dt.date(2026, 6, 30)]
    assert float(points["pe"][0].value) == pytest.approx(500 / (30 + 5 + 4))
    assert payload["closed_through"] == "2026-06-30"
    assert "2026-Q3" not in payload["rows"]["AAA"] and "2025" not in payload["rows"]["BBB"]


def test_last_closed_quarter_waits_for_the_reporting_deadline() -> None:
    assert members.last_closed_quarter(dt.date(2026, 11, 14)) == dt.date(2026, 6, 30)
    assert members.last_closed_quarter(dt.date(2026, 11, 16)) == dt.date(2026, 9, 30)
    assert members.last_closed_quarter(dt.date(2026, 2, 20)) == dt.date(2025, 12, 31)
    assert members.quarter_end("2025-Q4") == dt.date(2025, 12, 31)
    assert members.quarter_end("2025") is None


class ClientAdapter:
    def __init__(self, fake: FakeVnstock) -> None:
        self.fake = fake

    def call(self, chain: Sequence[Step]) -> Any:
        return self.fake(chain)


def test_fetcher_skips_ratio_when_the_last_quarter_is_stored() -> None:
    fake = FakeVnstock(SUMMARIES, {})
    fetcher = VnstockFetcher(ClientAdapter(fake), sleep=lambda _: None)  # type: ignore[arg-type]
    request = {"members": "VNX", "report": "ratio"}
    fetched = fetcher.fetch(request, ["pe"], {dt.date(2026, 6, 30)}, TODAY)
    assert fetched.payload is None and fake.calls == 0
    summary = fetcher.fetch(
        {"members": "VNX", "report": "summary"}, ["dividend_yield"], set(), TODAY
    )
    assert summary.payload is not None and b'"report":"summary"' in summary.payload
    assert fake.calls == 4


def quant_table(rows: dict[str, dict[str, tuple[float, float]]]) -> pd.DataFrame:
    out = []
    for symbol, quarters in rows.items():
        for period, (pe, cap) in quarters.items():
            out.append({"symbol": symbol, "period": period, "id": "RT_VALUE_PE", "value": pe})
            out.append(
                {"symbol": symbol, "period": period, "id": "RT_VALUE_MARKET_CAP", "value": cap}
            )
    return pd.DataFrame(out)


def test_ratio_from_vnstock_quant_in_chunks_with_a_bad_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(members, "QUANT_CHUNK", 2)
    data = {
        "AAA": {"2026-Q2": (10.0, 300.0)},
        "BBB": {"2026-Q2": (20.0, 100.0)},
        "CCC": {"2026-Q2": (25.0, 100.0)},
        "EEE": {"2026-Q2": (10.0, 0.0)},  # no market cap: left out of the quarter
        "FFF": {"2026-Q2": (10.0, 0.0)},
    }
    calls: list[list[str]] = []

    def quant(symbols: Sequence[str]) -> pd.DataFrame:
        calls.append(list(symbols))
        if "DDD" in symbols:
            raise MarketDataError("load failed")  # the chunk is retried one by one
        return quant_table({s: data[s] for s in symbols})

    summaries = {**SUMMARIES, "DDD": {}, "EEE": {}, "FFF": {}}
    payload, points = members.ratio(FakeVnstock(summaries, {}), "VNX", TODAY, quant)
    assert float(points["pe"][0].value) == pytest.approx(500 / (30 + 5 + 4))
    assert payload["source"] == "vnstock_quant.fa.ratios"
    assert list(payload["missing"]) == ["DDD"]  # only the bad symbol is lost
    assert calls == [["AAA", "BBB"], ["CCC", "DDD"], ["CCC"], ["DDD"], ["EEE", "FFF"]]
