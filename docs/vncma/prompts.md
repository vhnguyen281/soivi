# Claude Code prompts — VNCMA in the Soivi repo

How to use
- Before Prompt 0: put the repo under git (`git init`, commit everything; `.env` is already gitignored).
- One prompt per conversation in the Claude Code panel. For [PLAN] prompts, type `/plan` first and review the plan.
- After each prompt: read the diff, `make test` and `make lint`, commit. Move on only when "Done when" is true.
- Never paste secrets into a prompt.

---

## Prompt 0 — Orientation [PLAN]
```
Read CLAUDE.md, docs/DECISIONS.md (especially 2026-11-05), docs/vncma/spec.md and docs/vncma/vnstock-api-notes.md,
then the existing code in core/ (models, versioning), pipeline/ (fetch/storage, runner, scheduler) and review_app/.
Propose how VNCMA fits this repo: tables and migrations, whether to reuse snapshot/source, module layout
(pipeline/market, core/cma), review-app and API integration, and the order of work. Answer the open questions in
spec §7 or ask me. List anything in the spec that conflicts with existing code or principles. No code yet.
```
Done when: I approve the plan; the final design is a new dated entry in docs/DECISIONS.md.

## Prompt 1 — Dependencies and vnstock access
```
Add pandas, numpy, scipy and openpyxl to pyproject (uv). Find out how vnstock and the sponsor package vnstock_data
are installed on this Mac (`vnstock` CLI, ~/.vnstock) and make them importable from the project's .venv without
breaking uv.lock (explain the approach; the sponsor package may come from vnstocks.com's own index). Add a tiny
`python -m pipeline market check` command that prints the vnstock version, tier (`vnstock policy`) and one VN30
close price. Keep mypy strict passing (stubs/ignores for vnstock only).
```
Done when: the check command works on the host and `make test`/`make lint` pass.

## Prompt 2 — Probe vnstock (LIVE)
```
Implement `python -m pipeline market probe`. For every call in docs/vncma/vnstock-api-notes.md, try the longest
history it allows and record: works yes/no, error, columns, rows, first/last date, frequency, units, 3 sample rows.
Also find the S&P 500 symbol, check VN30/VNMID/VNSML P/E, whether VN (SJC) gold still exists, bond_yield() params
and tenors, and which bond funds have NAV history (start dates). Write docs/vncma/probe-report.md (Vietnamese summary
+ table), save one small fixture per call under tests/fixtures/vnstock/, and update vnstock-api-notes.md.
Respect rate limits.
```
Done when: I have reviewed the probe report.

## Prompt 3 — Schema + ingest [PLAN]
```
Implement the market tables from the approved design (Alembic migration, append-only triggers like the versioned
tables, tests against the soivi_test DB). Build pipeline/market/source.py: one wrapper for all vnstock calls with
retries, provenance, raw payload to MinIO with SHA-256, clear errors naming the call, never partial data.
`python -m pipeline market ingest` fetches every configured series idempotently and stores monthly observations
(document the month-end rule per series). Offline tests with the Prompt 2 fixtures.
```
Done when: two ingests in a row; the second adds nothing.

## Prompt 4 — Monthly collectors (decided 2026-11-05: monthly, run on the Mac)
```
Add a monthly `python -m pipeline market collect` step, run together with ingest: (1) a snapshot of
Macro().currency().deposit_rate(mode="term") as a cross-check for our own savings_rate data; (2) one SJC gold
buy/sell point per month — via vnstock if the probe found it, otherwise an adapter for the official SJC page
following our polite-crawling rules (robots.txt, 5 s, honest User-Agent) with fixture tests and
raise-on-layout-change. Allow a manually entered monthly point with its source when the fetch fails.
```
Done when: one month of both is stored with provenance.

## Prompt 5 — Monthly total-return series
```
Implement core/cma/series.py per spec §4.1 for every class with data. The cash class uses approved savings_rate
history (12M, average of the 10 big banks) once it exists and a policy/interbank proxy before that — document the
splice. Output an aligned monthly log-return frame and a coverage table (start, months, grade). Unit tests on synthetic
data with known answers (constant yield → y/12, etc.).
```
Done when: the coverage table looks right to me.

## Prompt 6 — Statistics
```
Implement core/cma/stats.py: annualised vol, full-sample + EWMA blend, Geltner de-smoothing, Ledoit–Wolf shrinkage
(numpy, formula cited in the docstring), correlation validation + Higham nearest-PSD, vol floors. Record the
unequal-history policy in DECISIONS.md. Property tests: PSD, symmetric, unit diagonal, shrinkage in [0,1], and a broken
matrix that gets repaired.
```

## Prompt 7 — Macro block, building blocks, scenarios
```
Implement core/cma/blocks.py per spec §2–3: macro defaults derived from data (show the derivation), config overrides,
model expected returns, arithmetic returns, scenarios, 80% bands. Save as an append-only cma_run with input hashes and
code version. Adjustments: ±1pp cap, reason required, stored in cma_adjustment; refuse to run if a reason is missing.
```
Done when: `python -m pipeline market compute` creates a run where every number traces to inputs.

## Prompt 8 — Draft report + review-app tab
```
Generate the draft: xlsx (Summary, Macro, Building blocks, Correlation, Scenarios, Inputs, Changes), json (API shape)
and a Vietnamese markdown summary with disclaimer and grades. Add a VNCMA tab to review_app: run summary, adjustments
with reasons, and "approve release" with a named reviewer that writes an immutable cma_release. Then run end to end.
```
Done when: I can approve VNCMA 2027.1-draft in the review app.

## Prompt 9 — Sanity review (no code changes)
```
Review the latest draft as a sceptical CFA charterholder: compare with history, with the global EM CMAs I enter in
config, and with common sense (equity > gov bond > cash; gold vol vs equity vol). List the 10 weakest assumptions and
the sensitivity of each class to ±1pp in pi, g and PE_target. Write docs/vncma/review-notes.md.
```

## Prompt 10 — Publish
```
Add GET /v1/vncma/latest and /v1/vncma/{version} to the public API (methodology_version in every response), and a
Vietnamese VNCMA page on the site with the table, correlation heatmap, scenarios, methodology link, downloads and
disclaimer. Rebuild on release approval via the existing revalidate webhook.
```
