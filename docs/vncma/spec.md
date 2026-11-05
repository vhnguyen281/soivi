# VNCMA — engineering spec (v0.1, for the Soivi repo)

VNCMA (Vietnam Capital Market Assumptions) is a public, versioned set of 10-year expected returns, volatilities and
correlations for Vietnamese asset classes. It is the first piece of the "goals-based wealth planning" phase and lives
in this repo, on the same stack and principles as Phase 1.

Full methodology (Vietnamese, human-readable): export the Claude Docs document "VNCMA — Phương pháp luận Giả định
Thị trường Vốn Việt Nam" as Markdown to `docs/vncma/methodology.md`. If this spec and the methodology disagree, ask.

## 0. How VNCMA fits the existing principles (see docs/DECISIONS.md, 2026-11-05)
- Principle 1 (bank = only source of record) applies to bank product values. For VNCMA the sources of record are:
  approved Phase 1 savings rates (cash class), vnstock market/macro data, and official statistics. Publish only
  **derived statistics**, never raw vnstock series.
- Principles 2–5 apply unchanged: provenance on every input, append-only history, human approval before publishing,
  public versioned formula (`METHODOLOGY_VERSION` for VNCMA, separate from the ranking formula version).
- Storage: PostgreSQL + MinIO as in Phase 1 (no MongoDB; see DECISIONS 2026-10-25).

## 1. Output of one run
Per asset class: expected 10-yr **geometric** return (VND nominal, %/yr) as model value, adjustment and final value;
arithmetic = geometric + σ²/2; expected and historical volatility; adverse/base/favourable scenarios; 80% band
μ ± 1.28σ/√10; data-quality grade A/B/C; list of input series. Plus a validated (PSD) correlation matrix, macro
assumptions used, run metadata (code version, input hashes), and change log vs the previous release.

## 2. Macro block (config, each value with source + note; every override shown in the report)
| var | meaning | default derivation |
|---|---|---|
| `pi` | VN CPI inflation, 10-yr avg | 50% official target (config) + 50% trailing 10-yr CPI avg (vnstock) |
| `pi_us` | US inflation | config |
| `g` | real GDP growth | trailing 10-yr avg (vnstock), haircut in config |
| `r_star` | neutral real rate | trailing 10-yr avg of (short rate − CPI); short rate = interbank 3M or policy rate |
| `d` | expected VND depreciation vs USD | `pi - pi_us`, cross-checked with 10-yr trend of the central rate |
| `tp` | term premium | avg(VN 10Y − 1Y gov yield) over available history |

## 3. Asset classes and expected-return formulas (H = 10)
| id | class | proxy series | grade | default optimizer |
|---|---|---|---|---|
| `cash_vnd` | VND deposits | **Phase 1 approved savings rates** (12M, avg of big banks); history before Phase 1: policy/interbank proxy | B | yes |
| `gov_bond` | VN gov bonds | TR index built from 10Y (and 5Y) yields | B | yes |
| `corp_bond` | corporate bonds | equal-weight NAV index of open-end bond funds (≥36 months) | C | yes, weight cap |
| `eq_large` | VN large cap | VN30 + dividends | A | yes |
| `eq_midsmall` | VN mid/small | VNMID / VNSML (confirm in probe) | B | yes |
| `gold` | gold | XAUUSD × USD/VND; SJC premium tracked separately | B | yes |
| `usd` | USD | USD/VND + USD deposit rate | A | yes |
| `eq_global` | global equities (reference) | S&P 500 in VND | A | no |
| `real_estate` | residential RE | none — range from config | C | no |

- cash: `E = pi + r_star`; cross-check with current 12M rate from `savings_rate`.
- gov bond: `E ≈ y0 + D*(y0 - y_eq)/H`, `y_eq = pi + r_star + tp`, D = modified duration of a 10Y par bond at y0.
- corp bond: `E = E_gov + s - PD*LGD` (config); cross-check vs bond-fund index net return.
- equities (Grinold–Kroner): `E = D/P + (pi + g_eps) - dS + (1/H)*ln(PE_target/PE_0)`; D/P cap-weighted from VN30
  members; g_eps = g × haircut; dS default 1%; PE_0 from Analytics valuation; PE_target = blend of PE_0 and 10–15-yr median.
- gold: `E = pi_us + theta + d + (1/H)*ln((1+p_target)/(1+p_0))`.
- usd: `E = i_usd + d`.
- global equities: average of ≥2 published global CMAs (USD, entered with source) + d.
- real estate: `E = y_rent - c + (pi + g_income)*k`, published as a range.
- House-view adjustments: max ±1.0 pp per class, written reason required, stored separately from model values.

## 4. Volatility and correlation
1. Monthly total-return series in VND: equity = price + (D/P)/12; gov bond `R_t ≈ y_{t-1}/12 - D*Δy_t + 0.5*C*Δy_t^2`;
   gold/global equities converted with USD/VND.
2. All available history (≥10 yrs where possible); 50/50 blend of full-sample and EWMA (half-life 36 months).
3. Geltner de-smoothing for smoothed series: `r_true = (r_obs - φ r_obs_{t-1})/(1-φ)`.
4. Ledoit–Wolf shrinkage (numpy implementation).
5. Validate: |ρ| ≤ 1, unit diagonal, min eigenvalue > 0, else Higham nearest-PSD; vol floors per class. Re-validate
   after any manual change. Document the policy for unequal history lengths in DECISIONS.md.
New dependencies needed: `pandas`, `numpy`, `scipy`, `openpyxl`, `vnstock` (+ sponsor `vnstock_data`). Ask before adding others.

## 5. Storage (PostgreSQL + MinIO, via Alembic)
Proposed tables — refine in Prompt 0 and record the final design in DECISIONS.md:
- `market_series` — code, asset_class, provider (`vnstock` / `official` / `manual`), call + params (JSONB), frequency, unit, grade.
- `market_observation` — series_id, period_end, value NUMERIC, snapshot_id; append-only (revisions are new rows).
- raw payloads → MinIO + existing `snapshot` pattern (decide: reuse `snapshot` with a new source kind, or a parallel
  `market_snapshot` table).
- `macro_assumption` — versioned values with source and note.
- `cma_run` — model output (JSONB), input hashes, code version; append-only.
- `cma_adjustment` — run_id, asset_class, delta_pp, reason, author.
- `cma_release` + `cma_release_value` — immutable once approved; approval needs a named human reviewer (same rule
  as `core/versioning.py`); DB trigger blocks UPDATE/DELETE like the versioned tables.

## 6. Where it plugs in
- `pipeline/market/` — vnstock wrapper, ingest, daily collectors (deposit-rate snapshot, SJC gold).
- `core/cma/` — series builders, stats, building blocks, scenarios, report.
- `review_app` — a VNCMA tab: run summary, adjustments with reasons, approve release.
- `api` — `GET /v1/vncma/latest`, `GET /v1/vncma/{version}`.
- `web` — a VNCMA page (Vietnamese slug, e.g. `/gia-dinh-thi-truong`), plus download files.

## 7. Open questions for Prompt 0
- Run vnstock on the host (where `vnstock register` was done) or inside the pipeline container? The sponsor package
  is tied to a registered device; check how many devices the Golden plan allows before containerising.
- Reuse `snapshot`/`source` tables or add parallel market tables?
- METHODOLOGY_VERSION naming for VNCMA.
