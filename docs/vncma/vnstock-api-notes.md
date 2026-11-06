# vnstock API notes for VNCMA (as of Nov 2026)

Sources: vnstocks.com docs (Macro, Market, Fund, Analytics, Data sources, Access levels pages) and the example
notebooks in github.com/thinh-vu/vnstock (`notebook/vnstock/01..05`). Function names below come from those; exact
parameters and column names MUST be confirmed by the probe step (`docs/vncma/prompts.md`, Prompt 2) because
the sponsor package `vnstock_data` is closed-source and changes between versions.

## Tier
Golden: all routes and sources, unlimited history and rows, 0.1 s pause between source queries.
Macro, Analytics, Fund functions need Bronze+ (Golden ok). Check with `vnstock policy` / `vnstock usage`.

## Calls used by VNCMA
| need | call (from notebooks/docs) | notes |
|---|---|---|
| index prices | `Market().index("VN30").ohlcv(start=, end=, interval="1D")` | cols: time, open, high, low, close, volume |
| index list | `Reference().index.list()`; members `Reference().index.members("VN30")` | VNMID, VNSML appear in list |
| index P/E, P/B | `Analytics().valuation("VNINDEX").pe(duration="5Y")`, `.pb()`, `.evaluation()` | source vnd; index = reportDate; test VN30 too and longer durations ("20Y") |
| stock summary | `Market().equity(s).summary()` | has dividend_yield, pe, pb, market_cap |
| financials | `Fundamental().equity(s).income_statement(limit=)`, `.ratio(limit=)` | |
| dividends | `Reference().events.calendar(start=, end=, event_type="dividend")` | |
| GDP | `Macro().economy().gdp(period="quarter", length=)` | long format: report_time, group_name, name, value, unit |
| CPI | `Macro().economy().cpi(period="month", length=)` | name "Chỉ số giá tiêu dùng" = headline |
| money, credit | `Macro().economy().money_supply()`, `.credit()` | |
| FX | `Macro().currency().exchange_rate(period="day", length=)` | names incl. "Tỷ giá trung tâm (từ 04/01/2016)" |
| policy / interbank | `Macro().currency().policy_rate()`, `.interbank_rate(...)` (tenor ON/1W/1M/3M) | older versions: `.interest_rate()` |
| deposit rates | `Macro().currency().deposit_rate(mode="term")` | current snapshot only — no history |
| gov bond yields | `Macro().global_macro.bond_yield(...)` (alias `Macro().world`) | VN 1Y–10Y, US; resolution 1D/1W/1M; params to confirm |
| Fed rate | `Macro().global_macro.fed_rate()` | |
| world gold | `Market().commodity("XAUUSD").ohlcv(...)` (dukascopy); older: `Macro().commodity().gold(market="GLOBAL")` | |
| VN gold (SJC) | older versions: `Macro().commodity().gold(market="VN")` returned buy/sell; docs say retail gold was removed in 5.0.0a3 | probe; if gone, scrape SJC daily ourselves |
| global indices | `Market().index("USA30", scope="global").ohlcv(interval="1d", length=)` | find S&P 500 symbol via `Reference().search.symbol("500")`; check values look sane (a notebook showed negative prices for USA30) |
| fund list / NAV | `Reference().fund.list()`; `Market().fund(s).history()` | types equity_fund / bond_fund / balanced_fund; sources cafef, digiinvest |

## Known gaps (fill outside vnstock)
- Deposit-rate history by bank → Phase 1 pipeline from now; older: NHNN averages / IMF IFS.
- SJC gold history → own daily scraper + monthly points collected manually.
- Index dividend yield history → compute from member data.
- Real-estate index, corporate-bond yields → none; grade C, manual inputs.

## Licensing
Read vnstocks.com/policies/license and /terms before publishing. Publish derived statistics only; never raw series.

## Confirmed from the vnstocks.com docs (read 2026-11-05; still to verify in the probe)
Pages: /docs/vnstock/quy-mo-fund, /vi-mo-macro, /dinh-gia-analytics, /thi-truong-market, /policies/license.

- **No ready-made asset-class returns or total-return indices.** Index `ohlcv()` is price only; we build TR ourselves.
- **Funds** (Bronze+; sources CafeF default, DigiInvest; Fmarket removed):
  - `Reference().fund.list("bond_fund")` → ticker, organ_short_name, fund_type, management_fee, inception_date, nav.
    CafeF: 43 funds (24 equity, 15 bond, 4 balanced).
  - `Market().fund(s).history()` → time, nav. No start/end. DCDS goes back to 2004–2005.
  - `Market().fund(s).performance()` (CafeF) → only ytd, 3y, 5y (annualised). Other periods: compute from NAV.
  - `holdings()`, `asset_allocation()`, `fee_structure()` (CafeF); `dividends()` (DigiInvest).
- **Macro** (Bronze+, source `asean`, `start`/`end` as "YYYY[-MM[-DD]]"; default window 3 years — pass `start`):
  - `eco.cpi(period="month")` → cpi_total, cpi_core as **% y/y, not an index level**.
  - `eco.gdp(period="quarter"|"year")` → gdp as % y/y.
  - `cur.policy_rate()` → refinance, discount; `cur.interbank_rate(period="ON"|"1W"|"1M"|"3M")` → interest.
  - `cur.deposit_rate(mode="term")` → current table only; tenors 1m, 3m, 6m, **13m**, 36m (no 12m).
  - `cur.exchange_rate()` → center_rate, vcb_rate, market_rate (daily).
  - `glb.bond_yield(market="VN", tenor="10Y", resolution="1M")` → VN 1Y/2Y/3Y/5Y/10Y; US 1Y/2Y/5Y/10Y/30Y.
    Unknown tenor returns an empty table without an error — the wrapper must raise.
  - `Macro().commodity()` removed. Gold: `Market().commodity("XAUUSD").ohlcv()` (dukascopy, UTC). No SJC.
- **Valuation:** `Analytics().valuation("VNINDEX").pe(duration="20Y")` (source vnd). Docs confirm only VNINDEX and
  HNXINDEX; VN30 is unconfirmed.
- **Indices:** VNINDEX, VN30, HNXINDEX, UPCOMINDEX named; VNMID/VNSML not mentioned — check `Reference().index.list()`.
  Global: `Market().index("USA30", scope="global")`; S&P 500 symbol not documented.
- **Licence** (effective 30/11/2026): one user per Bronze/Silver/Golden, **up to 13 registered devices** per package;
  no right to resell or distribute source data; users must check each source's terms (CafeF, DigiInvest, vnd,
  dukascopy, asean). Publishing derived statistics is not addressed directly — confirm before publishing.

## Confirmed by the probe (2026-11-06, vnstock 5.2.1, Golden) — supersedes the sections above
Full results: [probe-results.md](probe-results.md); summary and open decisions: [probe-report.md](probe-report.md).
Fixtures (first 5 rows of each call): `tests/fixtures/vnstock/<name>.json`.

| need | call that works | history | notes |
|---|---|---|---|
| index prices | `Market().index(s).ohlcv(start=, interval="1D", limit=10000, source="vci")` | VNINDEX 2004-01, HNXINDEX 2005-07, VN30 2012-02, VNMID/VNSML 2015-05, VN100 2022-06 | **`limit` is required**: without it ohlcv stops at 1,000 rows. Only `vci` and `kbs` serve indices; `kbs` starts 2012-06 and returns VNMID/VNSML empty. `interval="1M"` works. |
| index list / members | `Reference().index.list()`, `.groups()`, `.members("VN30")` | — | members: one column `symbol`. |
| P/E, P/B | `Analytics().valuation(i).pe(duration="20Y")`, `.pb()`, `.evaluation()` | 2017-12 (≈9 y) | columns `report_date`, `pe`. Valid indices: VNINDEX, VN30, HNX/HNXINDEX only. |
| stock summary | `Market().equity(s).summary()` | current | `dividend_yield` is a fraction (0.039), `pe`, `pb`, `market_cap` (VND). |
| ratios, income | `Fundamental().equity(s).ratio()`, `.income_statement()` | 2018 | long format with units. |
| dividends | `Reference().events.calendar(start=, end=, event_type="dividend")` | — | filter is loose: also returns share issues; keep `event_type == "DIV"`. |
| CPI | `Macro().economy().cpi(start=)` | 2016-01 | `cpi_total`, `cpi_core` in **% y/y**. |
| GDP | `Macro().economy().gdp(start=, period="year"\|"quarter")` | year 2015; quarter non-null from 2018-Q3 | % growth. |
| money, credit | `Macro().economy().money_supply()`, `.credit()` | 2014–2016, quarterly, to 2025-06 | context only. |
| FX | `Macro().currency().exchange_rate(start=)` | 2020-01 | `center_rate`, `vcb_rate`, `market_rate`. `Market().forex("USDVND")` fails (HTTP 400). |
| policy rate | `Macro().currency().policy_rate(start=)` | 2021-01 | `refinance`, `discount`. |
| interbank | `Macro().currency().interbank_rate(period="ON"\|"1W"\|"1M"\|"3M", start=)` | 2016-01 | column `interest`. |
| deposit rates | `Macro().currency().deposit_rate(mode="term")` | snapshot | 30 banks; `interest_1m/3m/6m/13m/36m`; per-bank dates vary. |
| gov bond yields | `Macro().global_macro.bond_yield(market="VN", tenor=, start=)` | 2020-08 | tenors 1Y, 2Y, 3Y, 5Y, 10Y; 7Y/15Y empty without error; `resolution` ignored (daily, incl. Sundays); OHLC columns, use `close`. |
| US 10Y, Fed, DXY | `Macro().global_macro.bond_yield(market="US", ...)`, `.fed_rate()`, `.index("DXY")` | 2020-08 / 2021-01 | |
| world gold | `Market().commodity("XAUUSD").ohlcv(...)` | **current calendar year only** | Dukascopy; earlier years return empty. SJC: gone (no symbol, `Macro().commodity()` raises). |
| S&P 500 | `Market().index("USA500", scope="global").ohlcv(...)` (`SPX` also works) | **current calendar year only** | Dukascopy; `US500` fails (HTTP 400). |
| funds | `Reference().fund.list("bond_fund")`, `Market().fund(s).history()`, `.nav()`, `.performance()` | NAV from 2013 (DCBF, VFF) | 15 bond funds, 12 with ≥36 months; `inception_date` empty; some NAVs weekly. |

General: macro data come from `asean` and are short whatever `start` says; `length` must be a row count; every
result carries `df.attrs` provenance (source, route, organisation, terms_url, robots_txt). Several calls return an
empty table instead of raising, so the wrapper must raise on empty results.
