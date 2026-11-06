"""`market probe` pieces, offline: summarising, fixtures, pacing, report, saved fixtures."""

import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from pipeline.market import probe
from pipeline.market.client import MarketDataError, Step, describe

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "vnstock"
VN = "Asia/Ho_Chi_Minh"


def _monthly() -> pd.DataFrame:
    times = pd.to_datetime(["2016-01-31", "2016-02-29", "2016-03-31", "2016-04-30"]).tz_localize(VN)
    df = pd.DataFrame({"time": times, "cpi_total": [0.8, 1.27, 1.69, 1.89], "unit": "%"})
    df.attrs["source"] = "asean"
    return df


SPEC = probe.Spec("macro_cpi_month", "macro", "pi", [("Macro", (), {}), ("cpi", (), {})])


def test_describe_renders_a_call_chain() -> None:
    chain: list[Step] = [
        ("Reference", (), {}),
        ("fund", None, {}),
        ("list", ("bond_fund",), {}),
    ]
    assert describe(chain) == 'Reference().fund.list("bond_fund")'


def test_summarise_keeps_local_dates_and_finds_frequency() -> None:
    r = probe.summarise(SPEC, _monthly())
    assert r.ok and r.rows == 4
    assert (r.date_column, r.first, r.last) == ("time", "2016-01-31", "2016-04-30")
    assert r.frequency == "monthly"
    assert r.units == ["%"]
    assert r.attrs["source"] == "asean"
    assert len(r.samples) == probe.SAMPLE_ROWS


def test_empty_table_is_a_failure() -> None:
    r = probe.summarise(SPEC, _monthly().iloc[0:0])
    assert not r.ok
    assert r.error == "empty table (no error raised)"
    assert r.columns == ["time", "cpi_total", "unit"]


def test_non_table_is_a_failure() -> None:
    assert probe.summarise(SPEC, {"a": 1}).error == "returned dict, not a table"


class FakeClient:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def status(self) -> Any:
        raise NotImplementedError

    def latest_index_close(self, symbol: str) -> Any:
        raise NotImplementedError

    def call(self, chain: Sequence[Step]) -> Any:
        text = describe(chain)
        self.calls.append(text)
        answer = self.answers[text]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_run_probe_paces_calls_saves_fixtures_and_expands_bond_funds(tmp_path: Path) -> None:
    bond_list = pd.DataFrame({"ticker": ["DCBF", "VFF"], "fund_type": "bond_fund"})
    nav = pd.DataFrame({"time": pd.to_datetime(["2013-06-10", "2013-06-13"]), "nav": [1e4, 1e4]})
    specs = [
        SPEC,
        probe.Spec("broken", "x", "y", [("Macro", (), {}), ("commodity", (), {})]),
        probe.Spec(
            "fund_list_bond",
            "funds",
            "z",
            [("Reference", (), {}), ("fund", None, {}), ("list", ("bond_fund",), {})],
        ),
    ]
    client = FakeClient(
        {
            "Macro().cpi()": _monthly(),
            "Macro().commodity()": MarketDataError("Macro().commodity() failed: gone"),
            'Reference().fund.list("bond_fund")': bond_list,
            'Market().fund("DCBF").history()': nav,
            'Market().fund("VFF").history()': nav,
        }
    )
    pauses: list[float] = []
    results = probe.run_probe(
        client,
        specs,
        tmp_path,
        pause=1.0,
        sleep=pauses.append,
        now=lambda: dt.datetime(2026, 11, 6, tzinfo=dt.UTC),
        log=lambda _: None,
    )
    assert [r.spec.name for r in results] == [
        "macro_cpi_month",
        "broken",
        "fund_list_bond",
        "fund_history_dcbf",
        "fund_history_vff",
    ]
    assert pauses == [1.0] * 4  # between calls, not before the first
    assert not results[1].ok and "gone" in (results[1].error or "")
    saved = json.loads((tmp_path / "macro_cpi_month.json").read_text("utf-8"))
    assert saved["call"] == "Macro().cpi()"
    assert saved["total_rows"] == 4 and len(saved["rows"]) == 4
    assert saved["attrs"] == {"source": "asean"}
    assert not (tmp_path / "broken.json").exists()
    assert (tmp_path / "fund_history_vff.json").exists()


def test_render_has_one_row_per_call() -> None:
    results = [
        probe.summarise(SPEC, _monthly()),
        probe.Result(SPEC, ok=False, error="a | b"),
    ]
    text = probe.render(results, ["vnstock 5.2.1"])
    assert "| 1 | macro | macro_cpi_month | `Macro().cpi()` | yes | 4 | 2016-01-31 |" in text
    assert "a \\| b" in text
    assert "calls: 2, working: 1, failing or empty: 1" in text


def test_every_spec_name_is_unique() -> None:
    names = [s.name for s in probe.specs()]
    assert len(names) == len(set(names))


# Saved fixtures from the live probe: the columns VNCMA relies on must be there.
EXPECTED_COLUMNS = {
    "index_vnindex_daily": {"time", "close"},
    "index_vnmid_daily": {"time", "close"},
    "valuation_pe_vn30": {"report_date", "pe"},
    "equity_summary_fpt": {"dividend_yield", "pe", "market_cap"},
    "macro_cpi_month": {"time", "cpi_total", "cpi_core"},
    "macro_gdp_year": {"time", "gdp"},
    "fx_exchange_rate": {"time", "center_rate", "market_rate"},
    "rates_policy": {"time", "refinance", "discount"},
    "rates_interbank_3m": {"time", "interest"},
    "rates_deposit_term": {"bank_code", "interest_13m"},
    "bond_yield_vn_10y": {"time", "close"},
    "gold_xauusd_daily": {"time", "close"},
    "fund_list_bond": {"ticker", "fund_type", "nav"},
    "fund_history_dcbf": {"time", "nav"},
}


@pytest.mark.parametrize("name", sorted(EXPECTED_COLUMNS))
def test_saved_fixture_has_the_columns_vncma_uses(name: str) -> None:
    saved = json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))
    assert EXPECTED_COLUMNS[name] <= set(saved["columns"])
    assert saved["rows"], "fixture has no sample rows"
    assert saved["attrs"].get("source"), "provenance (df.attrs) missing"
    frame = pd.DataFrame(saved["rows"])
    assert EXPECTED_COLUMNS[name] <= set(frame.columns)
