"""`python -m pipeline market probe`: try every vnstock call VNCMA needs (LIVE).

For each call it records whether it works, the error, columns, rows, first/last
date, frequency, units and a few sample rows; saves a small fixture per call
under tests/fixtures/vnstock/; and writes docs/vncma/probe-results.md. The
human summary lives in docs/vncma/probe-report.md.

Each call asks for the longest history it allows (start in 2000 or earlier,
limit=10000; domestic indices from source "vci", which goes back further than
the default "kbs").
Calls are spaced by `pause` seconds (Golden allows 0.1 s; we use 1 s).
"""

import datetime as dt
import importlib
import json
import re
import time
import warnings
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.market.client import MarketClient, MarketDataError, Step, describe

START = "2000-01-01"
# Without `limit`, ohlcv() stops at 1,000 rows whatever `start` says.
LIMIT = 10000
DATE_COLUMNS = (
    "time",
    "date",
    "trading_date",
    "tradingDate",
    "report_time",
    "reportDate",
    "report_date",
    "nav_date",
    "period",
)
UNIT_COLUMNS = ("unit", "units", "currency", "unit_vi", "unit_en")
TICKER_COLUMNS = ("ticker", "symbol", "fund_code", "short_name")
FIXTURE_ROWS = 5
SAMPLE_ROWS = 3


@dataclass(frozen=True)
class Spec:
    name: str  # also the fixture file name
    group: str
    need: str  # what VNCMA uses it for
    chain: Sequence[Step]


@dataclass
class Result:
    spec: Spec
    ok: bool
    error: str | None = None
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    date_column: str | None = None
    first: str | None = None
    last: str | None = None
    frequency: str | None = None
    units: list[str] = field(default_factory=list)
    samples: list[dict[str, str]] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0


def _s(cls: str, *steps: Step) -> list[Step]:
    return [(cls, (), {}), *steps]


def _c(name: str, *args: Any, **kwargs: Any) -> Step:
    return (name, args, kwargs)


def _a(name: str) -> Step:
    return (name, None, {})


def specs() -> list[Spec]:
    out: list[Spec] = []

    def add(name: str, group: str, need: str, chain: Sequence[Step]) -> None:
        out.append(Spec(name, group, need, chain))

    # Indices (price only) and membership
    for sym in ("VNINDEX", "VN30", "VN100", "VNMID", "VNSML", "HNXINDEX"):
        add(
            f"index_{sym.lower()}_daily",
            "index",
            "equity returns / volatility",
            _s(
                "Market",
                _c("index", sym),
                _c("ohlcv", start=START, interval="1D", limit=LIMIT, source="vci"),
            ),
        )
    add(
        "index_vnindex_daily_kbs",
        "index",
        "default source (kbs) for comparison",
        _s("Market", _c("index", "VNINDEX"), _c("ohlcv", start=START, interval="1D", limit=LIMIT)),
    )
    add(
        "index_vn30_monthly",
        "index",
        "check a native monthly interval",
        _s("Market", _c("index", "VN30"), _c("ohlcv", start=START, interval="1M", limit=LIMIT)),
    )
    add("index_list", "index", "VNMID/VNSML exist?", _s("Reference", _a("index"), _c("list")))
    add("index_groups", "index", "index groups", _s("Reference", _a("index"), _c("groups")))
    add(
        "index_members_vn30",
        "index",
        "D/P from members",
        _s("Reference", _a("index"), _c("members", "VN30")),
    )

    # Valuation
    for sym in ("VNINDEX", "VN30", "VNMID", "VNSML", "HNXINDEX"):
        add(
            f"valuation_pe_{sym.lower()}",
            "valuation",
            "PE_0 and PE history (Grinold-Kroner)",
            _s("Analytics", _c("valuation", sym), _c("pe", duration="20Y")),
        )
    add(
        "valuation_pb_vnindex",
        "valuation",
        "P/B history",
        _s("Analytics", _c("valuation", "VNINDEX"), _c("pb", duration="20Y")),
    )
    add(
        "valuation_evaluation_vnindex",
        "valuation",
        "combined valuation table",
        _s("Analytics", _c("valuation", "VNINDEX"), _c("evaluation", duration="20Y")),
    )

    # Stocks: dividend yield, fundamentals, dividend events
    add(
        "equity_summary_fpt",
        "equity",
        "dividend_yield, pe, market cap per member",
        _s("Market", _c("equity", "FPT"), _c("summary")),
    )
    add(
        "fundamental_ratio_fpt",
        "equity",
        "per-stock ratios history",
        _s("Fundamental", _c("equity", "FPT"), _c("ratio")),
    )
    add(
        "fundamental_income_fpt",
        "equity",
        "earnings history",
        _s("Fundamental", _c("equity", "FPT"), _c("income_statement")),
    )
    add(
        "events_dividends_2025",
        "equity",
        "dividend calendar",
        _s(
            "Reference",
            _a("events"),
            _c("calendar", start="2025-01-01", end="2025-12-31", event_type="dividend"),
        ),
    )

    # Macro: economy
    add("macro_gdp_quarter", "macro", "g", _s("Macro", _c("economy"), _c("gdp", start="1990")))
    add(
        "macro_gdp_year",
        "macro",
        "g (annual)",
        _s("Macro", _c("economy"), _c("gdp", start="1990", period="year")),
    )
    add("macro_cpi_month", "macro", "pi", _s("Macro", _c("economy"), _c("cpi", start="1990")))
    add(
        "macro_money_supply",
        "macro",
        "context",
        _s("Macro", _c("economy"), _c("money_supply", start="2000")),
    )
    add("macro_credit", "macro", "context", _s("Macro", _c("economy"), _c("credit", start="2000")))

    # Macro: currency and rates
    add(
        "fx_exchange_rate",
        "rates",
        "USD/VND (gold, usd, eq_global; d)",
        _s("Macro", _c("currency"), _c("exchange_rate", start="2000")),
    )
    add(
        "rates_policy",
        "rates",
        "r_star (policy rate)",
        _s("Macro", _c("currency"), _c("policy_rate", start="2000")),
    )
    for tenor in ("ON", "1W", "1M", "3M"):
        add(
            f"rates_interbank_{tenor.lower()}",
            "rates",
            "r_star (short rate)",
            _s("Macro", _c("currency"), _c("interbank_rate", period=tenor, start="2000")),
        )
    add(
        "rates_deposit_term",
        "rates",
        "cash cross-check",
        _s("Macro", _c("currency"), _c("deposit_rate", mode="term")),
    )
    add("rates_omo", "rates", "context", _s("Macro", _c("currency"), _c("omo", start="2000")))

    # Government bond yields (tenors 7Y and 15Y check the "unknown tenor" behaviour)
    for tenor in ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y"):
        add(
            f"bond_yield_vn_{tenor.lower()}",
            "bonds",
            "gov_bond TR index, tp",
            _s(
                "Macro",
                _a("global_macro"),
                _c("bond_yield", market="VN", tenor=tenor, start="2000", resolution="1M"),
            ),
        )
    add(
        "bond_yield_vn_10y_daily",
        "bonds",
        "daily resolution history length",
        _s(
            "Macro",
            _a("global_macro"),
            _c("bond_yield", market="VN", tenor="10Y", start="2000", resolution="1D"),
        ),
    )
    add(
        "bond_yield_us_10y",
        "bonds",
        "pi_us / context",
        _s(
            "Macro",
            _a("global_macro"),
            _c("bond_yield", market="US", tenor="10Y", start="2000", resolution="1M"),
        ),
    )
    add(
        "fed_rate",
        "bonds",
        "i_usd proxy",
        _s("Macro", _a("global_macro"), _c("fed_rate", start="2000", resolution="1M")),
    )

    # Gold
    add(
        "gold_xauusd_daily",
        "gold",
        "gold class (USD)",
        _s(
            "Market",
            _c("commodity", "XAUUSD"),
            _c("ohlcv", start=START, interval="1D", limit=LIMIT),
        ),
    )
    add(
        "gold_xauusd_monthly",
        "gold",
        "native monthly interval",
        _s(
            "Market",
            _c("commodity", "XAUUSD"),
            _c("ohlcv", start=START, interval="1M", limit=LIMIT),
        ),
    )
    add(
        "gold_xauusd_2025",
        "gold",
        "is history before the current year available?",
        _s(
            "Market",
            _c("commodity", "XAUUSD"),
            _c("ohlcv", start="2025-01-01", end="2025-12-31", interval="1D"),
        ),
    )
    add("gold_vn_macro", "gold", "SJC still there?", _s("Macro", _c("commodity")))
    add(
        "gold_search_sjc",
        "gold",
        "SJC symbol?",
        _s("Reference", _a("search"), _c("symbol", "SJC", limit=20)),
    )
    add(
        "gold_search_vang",
        "gold",
        "SJC symbol?",
        _s("Reference", _a("search"), _c("symbol", "vàng", limit=20)),
    )

    # Global equities: find the S&P 500
    for query in ("500", "S&P", "SPX"):
        add(
            f"global_search_{re.sub(r'[^a-z0-9]', '', query.lower())}",
            "global",
            "find the S&P 500 symbol",
            _s("Reference", _a("search"), _c("symbol", query, limit=20)),
        )
    for sym in ("USA500", "US500", "SPX", "USA30"):
        add(
            f"global_index_{sym.lower()}",
            "global",
            "eq_global (USD)",
            _s(
                "Market",
                _c("index", sym, scope="global"),
                _c("ohlcv", start=START, interval="1D", limit=LIMIT),
            ),
        )
    add(
        "global_index_usa500_2025",
        "global",
        "is history before the current year available?",
        _s(
            "Market",
            _c("index", "USA500", scope="global"),
            _c("ohlcv", start="2025-01-01", end="2025-12-31", interval="1D"),
        ),
    )
    add(
        "global_macro_index_dxy",
        "global",
        "context",
        _s("Macro", _a("global_macro"), _c("index", "DXY", start="2000", resolution="1M")),
    )

    # Funds
    add("fund_list_all", "funds", "fund universe", _s("Reference", _a("fund"), _c("list")))
    add(
        "fund_list_bond",
        "funds",
        "corp_bond proxy universe",
        _s("Reference", _a("fund"), _c("list", "bond_fund")),
    )
    add(
        "fund_performance_dcbf",
        "funds",
        "published fund returns",
        _s("Market", _c("fund", "DCBF"), _c("performance")),
    )
    add("fund_nav_dcbf", "funds", "nav() vs history()", _s("Market", _c("fund", "DCBF"), _c("nav")))
    return out


def fund_history_spec(ticker: str) -> Spec:
    return Spec(
        f"fund_history_{ticker.lower()}",
        "bond_fund_nav",
        "corp_bond NAV index",
        _s("Market", _c("fund", ticker), _c("history")),
    )


# --- summarising -------------------------------------------------------------


def _pandas() -> Any:
    return importlib.import_module("pandas")


def _cell(value: Any, limit: int = 60) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _frequency(dates: Any) -> str | None:
    if len(dates) < 3:
        return None
    gaps = dates.sort_values().diff().dropna().dt.days
    median = float(gaps.median())
    if median <= 1.5:
        return "daily"
    if median <= 4:
        return "daily (trading days)"
    if median <= 8:
        return "weekly"
    if median <= 35:
        return "monthly"
    if median <= 100:
        return "quarterly"
    if median <= 400:
        return "yearly"
    return f"~{median:.0f} days"


def summarise(spec: Spec, data: Any, seconds: float = 0.0) -> Result:
    """Turn what a call returned into a Result. An empty table counts as a failure."""
    result = Result(spec, ok=False, seconds=seconds)
    if data is None or not hasattr(data, "columns"):
        result.error = f"returned {type(data).__name__}, not a table"
        return result
    result.rows = len(data)
    result.columns = [str(c) for c in data.columns]
    result.attrs = {str(k): _cell(v, 200) for k, v in dict(getattr(data, "attrs", {})).items()}
    if result.rows == 0:
        result.error = "empty table (no error raised)"
        return result
    result.ok = True
    pd = _pandas()
    for col in [*DATE_COLUMNS, *result.columns]:
        if col not in result.columns:
            continue
        series = data[col]
        if col not in DATE_COLUMNS and not str(series.dtype).startswith("datetime"):
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Keep each value's own timezone so 2016-01-31 00:00+07 stays the 31st.
            parsed = pd.to_datetime(series, errors="coerce")
            if not str(parsed.dtype).startswith("datetime"):
                parsed = pd.to_datetime(series, errors="coerce", utc=True)
        parsed = parsed.dropna()
        if len(parsed) == 0:
            continue
        result.date_column = col
        result.first = parsed.min().date().isoformat()
        result.last = parsed.max().date().isoformat()
        result.frequency = _frequency(parsed)
        break
    for col in UNIT_COLUMNS:
        if col in result.columns:
            result.units = sorted({_cell(v) for v in data[col].dropna().unique()})[:5]
    head = data.head(SAMPLE_ROWS).to_dict(orient="records")
    result.samples = [{str(k): _cell(v) for k, v in row.items()} for row in head]
    return result


def fixture(spec: Spec, data: Any, captured_at: dt.datetime) -> dict[str, Any]:
    """A small, offline copy of one call's result: first rows, columns, dtypes, attrs."""
    if data is None or not hasattr(data, "columns"):
        return {"call": describe(spec.chain), "captured_at": captured_at.isoformat(), "rows": []}
    return {
        "call": describe(spec.chain),
        "captured_at": captured_at.isoformat(),
        "total_rows": len(data),
        "columns": [str(c) for c in data.columns],
        "dtypes": {str(c): str(t) for c, t in data.dtypes.items()},
        "attrs": {str(k): str(v) for k, v in dict(getattr(data, "attrs", {})).items()},
        "rows": json.loads(data.head(FIXTURE_ROWS).to_json(orient="records", date_format="iso")),
    }


# --- running -----------------------------------------------------------------


def run_probe(
    client: MarketClient,
    spec_list: Iterable[Spec],
    fixtures_dir: Path | None,
    pause: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    log: Callable[[str], None] = print,
) -> list[Result]:
    results: list[Result] = []
    queue = list(spec_list)
    first = True
    while queue:
        spec = queue.pop(0)
        if not first:
            sleep(pause)
        first = False
        started = time.monotonic()
        try:
            data = client.call(spec.chain)
        except MarketDataError as exc:
            result = Result(spec, ok=False, error=_cell(exc, 300))
            data = None
        else:
            result = summarise(spec, data, time.monotonic() - started)
        results.append(result)
        log(
            f"[{'ok' if result.ok else 'FAIL'}] {spec.name}: "
            + (
                f"{result.rows} rows {result.first}..{result.last}"
                if result.ok
                else (result.error or "")
            )
        )
        if data is not None and fixtures_dir is not None and hasattr(data, "columns"):
            fixtures_dir.mkdir(parents=True, exist_ok=True)
            path = fixtures_dir / f"{spec.name}.json"
            payload = fixture(spec, data, now())
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8")
        if spec.name == "fund_list_bond" and result.ok and data is not None:
            column = next((c for c in TICKER_COLUMNS if c in result.columns), None)
            if column:
                tickers = sorted({str(t) for t in data[column].dropna()})
                queue.extend(fund_history_spec(t) for t in tickers)
    return results


# --- report ------------------------------------------------------------------


def _md(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def render(results: Sequence[Result], header: Sequence[str]) -> str:
    ok = sum(r.ok for r in results)
    lines = [
        "# vnstock probe results (generated)",
        "",
        "Generated by `python -m pipeline market probe`; do not edit by hand. "
        "The summary is in [probe-report.md](probe-report.md).",
        "",
        *[f"- {h}" for h in header],
        f"- calls: {len(results)}, working: {ok}, failing or empty: {len(results) - ok}",
        "",
        "| # | group | name | call | ok | rows | first | last | freq | units / note |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        note = ", ".join(r.units) if r.ok else r.error
        lines.append(
            f"| {i} | {r.spec.group} | {r.spec.name} | `{_md(describe(r.spec.chain))}` | "
            f"{'yes' if r.ok else 'no'} | {r.rows} | {r.first or ''} | {r.last or ''} | "
            f"{r.frequency or ''} | {_md(_cell(note, 120))} |"
        )
    lines += ["", "## Details", ""]
    for r in results:
        lines += [f"### {r.spec.name}", "", f"- call: `{describe(r.spec.chain)}`"]
        lines.append(f"- used for: {r.spec.need}")
        if not r.ok:
            lines.append(f"- **error:** {_md(r.error)}")
        if r.columns:
            lines.append(f"- columns: {', '.join(f'`{c}`' for c in r.columns)}")
        if r.date_column:
            lines.append(f"- date column `{r.date_column}`: {r.first} → {r.last} ({r.frequency})")
        if r.attrs:
            keep = ("source", "route", "organization", "organisation", "terms_url", "robots_txt")
            shown = {k: v for k, v in r.attrs.items() if k in keep}
            if shown:
                lines.append(f"- provenance: {_md(json.dumps(shown, ensure_ascii=False))}")
        if r.samples:
            lines += ["", "```json"]
            lines += [json.dumps(s, ensure_ascii=False) for s in r.samples]
            lines += ["```"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
