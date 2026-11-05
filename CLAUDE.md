# CLAUDE.md

Read this file at the start of every session. It defines what this project is and the rules that are not up for negotiation.

## Project

A free, community-first comparison site for Vietnam (a NerdWallet for Vietnam).

- **Phase 1:** savings / term deposits, certificates of deposit, and credit cards.
- **No monetisation yet.**
- **Later phases:** insurance → securities accounts → goals-based wealth planning.

## Non-negotiable principles

1. **The bank is the only source of record.** The bank's own web page or fee schedule (biểu phí / biểu lãi suất) is the only source a published value can come from. News and community reports only trigger a re-check. They never publish a value.
2. **Full provenance on every published value:** source URL, snapshot file + SHA-256 hash, `captured_at`, `effective_from`, extraction method, reviewer, and `approved_at`.
3. **Values are never overwritten.** Every change is a new version row.
4. **Human approval for every change.** Nothing extracted by a scraper or LLM goes live until a human approves the diff. Unchanged values pass automatically.
5. **Rankings come from a public, versioned formula.** No paid placement, ever.
6. **Polite crawling:** respect robots.txt, at most 1 request per 5 seconds per domain, an honest User-Agent with a contact email, and aggressive caching.
7. **Language:** Vietnamese is the primary UI language. Code, comments and identifiers are in English.

## Stack

| Area | Choice |
|---|---|
| Language / env | Python 3.12, managed with `uv` |
| Fetching | `httpx`; Playwright only when a page needs JS |
| PDF tables | `pdfplumber` + Camelot |
| OCR fallback | Tesseract (`vie`) |
| Structured extraction | Anthropic API |
| Database | PostgreSQL 16 + SQLAlchemy 2 + Alembic |
| Snapshot storage | MinIO (S3-compatible) |
| Scheduling | Built-in scheduler loop: `python -m pipeline schedule` (Prefect deferred; see DECISIONS.md) |
| Review app + public API | FastAPI + Jinja2 + HTMX |
| Public site | Next.js (App Router, TypeScript, static generation) |
| Runtime | Docker Compose for everything |
| Quality | pytest + ruff + mypy |

## Repo layout

```
pipeline/      adapters, fetch, extract, validate, diff
core/          models, db, scoring
review_app/    internal review UI (FastAPI + Jinja2 + HTMX)
api/           public API
web/           public site (Next.js)
data/seeds/    seed data
tests/         tests; saved pages in tests/fixtures/<bank>/
docs/          methodology, adapters, DECISIONS.md
```

## Conventions

- **Money:** integer VND.
- **Rates:** `Decimal` percent per year (e.g. `5.90`).
- **Terms:** `term_months`, or `term_days` for terms under a month ("1 tuần" = 7 days). Never both; `0`/`0` = demand deposit (không kỳ hạn).
- Write versioned tables (savings_rate, card_*) only through `core/versioning.py`; the database rejects edits and deletes of history.
- Every adapter has fixture-based tests that run offline.
- An adapter that cannot parse must **raise**, never return partial data.
- Run `make test` and `make lint` before saying a task is done.
- Record design decisions with dates in [docs/DECISIONS.md](docs/DECISIONS.md).

## VNCMA (goals-based planning, started 2026-11-05)

VNCMA = Vietnam Capital Market Assumptions: public, versioned 10-year expected returns, volatilities and correlations
for Vietnamese asset classes. Spec: [docs/vncma/spec.md](docs/vncma/spec.md). Work plan: [docs/vncma/prompts.md](docs/vncma/prompts.md).
vnstock calls and data gaps: [docs/vncma/vnstock-api-notes.md](docs/vncma/vnstock-api-notes.md).

- Principle 1 has a scoped exception for VNCMA (see DECISIONS 2026-11-05): market/macro data come from vnstock and
  official statistics; publish derived statistics only, never raw vnstock series.
- All other principles apply: provenance, append-only, named human approval before a release, public versioned method.
- All vnstock calls go through one wrapper (`pipeline/market/`); tests never hit the network (fixtures in
  `tests/fixtures/vnstock/`).
- Statistics are monthly; rates are Decimal percent in the DB, floats only inside the numeric computation in `core/cma/`.
- VNCMA is planning assumptions, not investment advice; every output carries the disclaimer.
