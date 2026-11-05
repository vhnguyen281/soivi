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
