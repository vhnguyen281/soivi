# Design decisions

A dated log of design decisions. Newest entries go at the bottom. Don't edit past entries: if a decision changes, add a new entry that points back to the one it replaces.

---

## 2026-10-25 — Founding decisions

**Context.** Starting a free, community-first comparison site for Vietnamese financial products. Phase 1 covers savings / term deposits, certificates of deposit and credit cards. No monetisation yet. Planned later phases: insurance, securities accounts, then goals-based wealth planning.

**Decisions.**

1. **Source of record.** Only the bank's own web page or fee schedule (biểu phí / biểu lãi suất) can supply a published value. News and community reports only trigger a re-check.
   *Why:* trust depends on every number tracing back to the issuer.
2. **Provenance per value.** Store source URL, snapshot file + SHA-256 hash, `captured_at`, `effective_from`, extraction method, reviewer and `approved_at`.
   *Why:* any figure can be audited and reproduced from the stored snapshot.
3. **Append-only versioning.** Values are never overwritten; each change is a new version row.
   *Why:* full history, safe rollback, and rate-history features later.
4. **Human-in-the-loop publishing.** Scraper/LLM output goes live only after a human approves the diff. Unchanged values pass automatically.
   *Why:* extraction errors must not reach users; auto-passing unchanged values keeps review effort low.
5. **Transparent ranking.** Rankings come from a public, versioned formula. No paid placement, ever.
   *Why:* independence is the core value of the product.
6. **Polite crawling.** Respect robots.txt, at most 1 request / 5 s per domain, honest User-Agent with contact email, aggressive caching.
   *Why:* be a good citizen and avoid being blocked by banks.
7. **Language.** Vietnamese-first UI; English for code, comments and identifiers.
8. **Stack.** Python 3.12 + uv; httpx (Playwright only for JS pages); pdfplumber + Camelot for PDF tables; Tesseract (`vie`) OCR fallback; Anthropic API for structured extraction; PostgreSQL 16 + SQLAlchemy 2 + Alembic; MinIO for snapshots; Prefect (cron to start) for scheduling; FastAPI + Jinja2 + HTMX for the review app and public API; Next.js (App Router, TypeScript, static generation) for the public site; Docker Compose; pytest + ruff + mypy.
9. **Repo layout.** `pipeline/`, `core/`, `review_app/`, `api/`, `web/`, `data/seeds/`, `tests/` (fixtures in `tests/fixtures/<bank>/`), `docs/`.
10. **Data conventions.** Money as integer VND; rates as `Decimal` percent per year (e.g. `5.90`); terms in months (`0` = demand deposit).
    *Why:* avoids float rounding errors and keeps units the same everywhere.
11. **Adapter rules.** Each adapter has offline, fixture-based tests. An adapter that cannot parse raises instead of returning partial data.
    *Why:* a silent partial parse could publish wrong or incomplete rates.
12. **Definition of done.** `make test` and `make lint` pass before a task counts as done.

---

## 2026-10-25 — Repo scaffold

**Decisions.**

1. **Alembic lives in `migrations/` at the repo root.** `migrations/env.py` takes the DB URL from `core.config` (env vars) and metadata from `core.db.Base`; `alembic.ini` holds no credentials. Migration files are date-prefixed and auto-formatted with ruff.
   *Why:* one source of config; readable migration history.
2. **Config via `pydantic-settings` (`core/config.py`).** The crawler delay setting is validated to be ≥ 5 s.
   *Why:* principle 6 is enforced in code, not just by convention.
3. **Constraint naming convention on `Base.metadata`.**
   *Why:* Alembic autogenerate produces stable, reviewable constraint names.
4. **MinIO image: `cgr.dev/chainguard/minio`.** The official `minio/minio` and `minio/mc` Docker Hub images are no longer pullable. A one-off `minio-init` service creates the snapshot bucket with object versioning on.
   *Why:* versioning backs up principle 3 at the storage layer.
5. **Postgres and MinIO bind to `127.0.0.1` only.**
   *Why:* nothing but the app should reach them on a VPS.
6. **Where commands run.** `make test` / `make lint` run on the host via uv (same as CI); `migrate`, `seed`, `shell` run inside the pipeline container.
   *Why:* fast feedback loop and simple CI; DB tasks use the same network as production.
7. **mypy runs in strict mode** from day one.
   *Why:* far cheaper to start strict than to tighten later.
8. **Prefect is a dependency now, but scheduling starts with cron** as CLAUDE.md allows.
9. **`web/` is a placeholder.** Next.js gets scaffolded when public-site work starts.

---

## 2026-10-25 — Keep PostgreSQL (MongoDB considered)

**Decision.** Stay on PostgreSQL 16 as the primary store.

**Why:**
- The data is relational (bank → product → rate tier → version → snapshot → approval), and rankings need joins and filters across banks.
- Approving a diff must be atomic (close old version, insert new, record reviewer), which is native in Postgres.
- The database itself can enforce the core principles: constraints for one current version per rate, `NOT NULL` approval fields, and no UPDATE/DELETE grants on history tables.
- `NUMERIC` keeps rates exact.
- Flexible or raw data (e.g. LLM extraction output) can go in `JSONB` columns, so a document store isn't needed for that.

---

## 2026-10-26 — Database schema and versioning

The spec's table list is kept, with the changes below. Code: `core/models.py`, `core/versioning.py`, migration `40f22f9f58ba`.

**Decisions.**

1. **One shared base for versioned tables** (`Versioned`: `savings_rate`, `card_terms`, `card_reward`, `card_perk`). Each table declares a *version key*: the columns that identify one value series. Everything else (minus provenance and lifecycle columns) is a *value*, and comparing values decides "changed or not".
   - savings_rate: institution, product_name, channel, term_months, min_amount_vnd, interest_payment
   - card_terms / card_perk: card_product_id
   - card_reward: card_product_id, category, reward_type

   `is_cd` is a value, not part of the key.
   *Why:* one implementation of the rules instead of four, so they can't drift apart.
2. **Lifecycle:** `pending → approved | rejected | superseded`. An approved row is live while `valid_to IS NULL`. When a newer version is approved, the old row gets `valid_to` and stays `approved` as history. `valid_from` is the approval time (= `approved_at` in principle 2). `effective_from` is the date the bank states. `superseded` is new: it marks a pending proposal replaced by a newer fetch before anyone reviewed it.
   *Why:* separates "when the bank says it applies" from "when we published it", and keeps the review queue to one item per series.
3. **Extra provenance and audit columns** on every version: `extraction_method`, `proposed_at`, `reviewer`, `decided_at`, `review_task_id`, `last_seen_snapshot_id`, `last_seen_at`.
   *Why:* principle 2 needs the extraction method and reviewer on the value itself. `last_seen_*` records when a fetch last confirmed an unchanged value, so the site can say "checked on ..." without creating a new version.
4. **The database enforces principles 3 and 4 itself:**
   - Partial unique indexes: at most one live version and one pending version per key.
   - A CHECK constraint ties status to its fields (an approved row must have a reviewer, `decided_at` and `valid_from`).
   - A trigger rejects DELETE, any change to value or provenance columns, re-deciding a decided row, and changing `valid_to` once set.
   - `snapshot` and `change_event` are fully append-only (no UPDATE or DELETE).

   *Why:* a bug, a script or a manual SQL session can't quietly rewrite history. Triggers also bind the table owner, which a GRANT-based approach would not.
5. **Helpers are the only write path** (`core/versioning.py`): `get_current`, `get_pending`, `current_select`, `propose_version`, `approve_version`, `reject_version`.
   - Each runs inside a savepoint and locks the rows it touches.
   - `propose_version` requires every key and value field (None for "not stated") and rejects floats, so an adapter can't write partial or imprecise data.
   - Approval and rejection need a named human reviewer (`system` is refused).
   - Unchanged values create nothing.
6. **`change_event` rows are written by `propose_version`,** one per changed field, linked to the new pending version's id. Old and new values are JSONB, with decimals stored as strings so they stay exact.
7. **Enums are VARCHAR + CHECK, not native Postgres enums,** and store lowercase values (`visa`, `online`, ...).
   *Why:* adding a value later is a one-line migration; native enum changes are awkward and can't always run in a transaction.
8. **`snapshot.url`** stores the URL actually fetched.
   *Why:* `source.url` can change later; the evidence must not.
9. **`news_item.matched_institution_ids` is a join table** (`news_item_institution`), not an array.
   *Why:* foreign keys keep it valid, and "news for bank X" is a plain indexed join.
10. **Card field changes:**
    - `min_income_vnd` is renamed `min_monthly_income_vnd`, since Vietnamese banks state monthly income.
    - Card rewards store points/miles as the bank states them (`points_per_spend` per `spend_unit_vnd`); `rate_pct` is for cashback only. A CHECK requires the right fields for each reward type. Converting points to a VND value belongs to the published scoring formula, not the data.
    - `card_perk` adds `lounge_unlimited` and `travel_insurance_cover_vnd`.
11. **Number types:** percents are `NUMERIC(6,3)`, money is `BIGINT` VND, timestamps are `timestamptz`.
12. **DB tests run against a real Postgres** (`soivi_test`, rebuilt from the migrations each run, which also tests the downgrade). Locally they skip if `make up` isn't running; CI runs its own Postgres and fails if it is missing.
    *Why:* partial indexes, triggers and JSONB can't be tested faithfully on SQLite.

**Open follow-ups:**
- Retiring a series that disappears from a bank page (e.g. a dropped term). Not handled yet.
- Approving a whole review task (many versions from one snapshot) in one call. Belongs with the review app.
- USD deposits are out of scope; all amounts are VND.

---

## 2026-10-26 — Seed data for institutions and sources

Migration `0c4b0d367cb2`; details and citations in `data/seeds/README.md`.

**Decisions.**

1. **`needs_check` flag on `institution` and `source`; `source.url` is nullable,** with a CHECK that a source without a URL must be flagged.
   *Why:* the seed must record "we know this page should exist but haven't found it" without inventing a URL. The scheduler must skip flagged or URL-less sources.
2. **The CSV files are the source of truth for seeded rows.** `make seed` validates every row first and aborts with all errors (no partial load). It then inserts or updates, matching institutions on `short_name` and sources on (institution, kind). It never deletes rows.
3. **Scope of institutions:**
   - included: SBV's state-owned, joint-stock and 100% foreign-owned bank lists, plus finance companies that issue credit cards;
   - excluded: joint-venture banks, foreign bank branches, policy banks, and ANZ Vietnam (no retail business since 2017).

   Vietcombank, VietinBank and BIDV are typed `state_bank` although SBV lists them as joint-stock. The four one-member LLC banks from the 2024–2025 compulsory transfers are typed `joint_stock_bank`, as SBV lists them in that table.
4. **`deposit_insurance` is derived from type:** true for banks, false for finance companies, which may not take deposits from individuals.
5. **Prefer index pages over dated PDFs for sources.** A dated PDF URL is recorded only with `needs_check=true` and a note.
   *Why:* a crawler pointed at an old PDF would keep publishing outdated fees.
6. **`pipeline/fetch/url_check.py` (`make check-seeds`)** re-checks seed URLs politely: robots.txt, at least 5 s per host, and an honest User-Agent read from `.env`.

---

## 2026-10-26 — Fetch layer (`pipeline/fetch`, adapters, CLI)

Migration `932592c1815c` adds `snapshot.unchanged`.

**Decisions.**

1. **One polite HTTP client (`PoliteHttp`) for everything that touches a bank site,** including the browser fetcher and `url_check`.
   - robots.txt is cached per origin for 24 h.
   - Per-host minimum delay from settings (≥ 5 s), applied to robots.txt, retries and browser navigations alike.
   - 3 attempts with backoff of 5 s then 10 s; Retry-After is honoured up to 300 s.
   - Timeouts, connection errors, 429 and 5xx are retried; other 4xx are not.

   *Why:* principle 6 is enforced in one place that can't be bypassed by a new adapter.
2. **An unreadable robots.txt means don't crawl.** A 5xx or network failure on robots.txt blocks the host until it can be read; a 4xx means no rules.
   *Why:* the conservative reading of RFC 9309; we're a guest on these sites.
3. **The rate limit is in-process.** Only one pipeline process should run at a time (cron with `flock` when scheduling is added).
4. **Snapshots:**
   - Only 2xx responses are stored.
   - The key is `{institution}/{source_kind}/{UTC date}/{sha256}.{ext}`.
   - Every fetch writes a snapshot row, even when the bytes are unchanged; that row is the evidence the page was checked.
   - Bytes are uploaded unless the identical key already exists, which means same bytes on the same day. Same bytes on another day are stored again, as specified. This costs some space; the alternative is pointing `storage_key` at the earlier object.
5. **`unchanged` compares with the source's latest snapshot.** Parsing is skipped unless `--reparse` is given, e.g. after fixing an adapter.
6. **Adapters return typed pydantic records (`pipeline/records.py`)** that mirror the versioned tables. A test keeps record fields and DB columns in sync. Card records carry the card's name and network instead of `card_product_id`; matching them to `card_product` rows is the diff step's job.
7. **The runner stops at parse.** Proposing versions (`core/versioning.py`) is the next step.
   - A parse that raises or returns nothing is a `parse_failed` result; the snapshot is kept as evidence.
   - A failed fetch increments `source.consecutive_failures` and writes no snapshot.
8. **The adapter must match its source row** (institution, kind, fetch_method, URL present); a mismatch fails the run.
   *Why:* a seed row pointing at the wrong adapter must not silently produce data for the wrong bank.
9. **The CLI commits each source separately.** `--source` runs even a flagged source, for testing a new adapter; `--institution` and `--all-due` run only active, confirmed sources with a URL and an adapter.
10. **Tests use a local `ThreadingHTTPServer` and a fake clock.** The 5 s rule is asserted exactly without waiting. The Playwright test runs only when the matching Chromium build is installed (it is in the Docker image).

---

## 2026-10-28 — Savings-rate adapters for the 10 largest banks

Adapters for Vietcombank, BIDV, VietinBank, Agribank, Techcombank, VPBank, MB, ACB, Sacombank and HDBank, each with fixtures, exact-value tests, layout-change tests that raise `AdapterBroken`, and notes in `docs/adapters/<bank>.md`. Migrations `9ac938092409`, `59323fa81e8a`, `cb9399fba86b` and `11e8f69bc301`.

**Decisions.**

1. **`savings_rate.term_days`.** Terms under a month ("1 tuần", "7 ngày", "01 ngày") are stored in days, with `term_months = 0`; a CHECK forbids both being set. 0/0 is a demand deposit.
   *Why:* weekly terms are common and don't fit whole months. Recorded in CLAUDE.md conventions.
2. **`savings_rate.region`, part of the version key.** `''` means nationwide; otherwise a lowercase code for the bank's own split (`north` / `central_south` for MB; `hanoi` / `hcm` for BIDV when its two tables differ).
   *Why:* MB publishes different rates for Central/South branches. Chosen by the user over storing one region.
3. **`source.variant`, with the seed key (institution, kind, variant).** It allows several sources of one kind (BIDV counter and online). `source.url` is now unique per **(url, kind)**, not globally, because one page can hold several kinds (MB's `/fee`).
4. **Term bands.** "Từ 1 tháng đến dưới 2 tháng" style bands are stored at their **lowest whole-month term**, with the bank's wording in `conditions_text` when the band covers more than one month. Bands with no lower bound, or open-ended bands starting after a stated term, are skipped and documented per adapter.
5. **Amount tiers → `min_amount_vnd`.** Where a bank states a minimum for some terms (ACB weekly/up-front: 10 triệu), it raises the floor. Footnoted rates for very large amounts (ACB, HDBank ≥200/500 tỷ) become separate tiers.
6. **Only the normal-customer segment** (Techcombank "KH THƯỜNG", MB "Mass") is stored. There is no segment field, and wealth tiers shouldn't lead a public comparison.
7. **Bonuses are not computed into rates.** ACB's tiered bonus is kept as a rule in `conditions_text`.
   *Why:* we only publish numbers the bank prints.
8. **Interest payment is recorded as `end` where a bank doesn't state it.** It is flagged as an assumption in that bank's doc (Vietcombank, BIDV counter, Agribank, VietinBank says "trả lãi sau", Techcombank). Semiannual and annual payment columns (HDBank) are skipped until the enum gains those values.
9. **Prefer the data behind the page when it's public:** JSON endpoints (Vietcombank GET, BIDV form POST, added as `http_method`), HTML fragments (Agribank), document listings (Techcombank, VPBank) through a new **`resolve_url()`** hook, so the adapter always fetches the *current* dated PDF.
10. **No getting around protections.** MB's API needs an anti-forgery token and HDBank's API returns encrypted payloads; neither is worked around. Both are read by **rendering the public page in headless Chromium** (`fetch_method=browser`). XHR discovery used one ordinary page load per bank, after a robots.txt check.
11. **OCR for image-only PDFs (VPBank), with strict checks:**
    - cells come from the vector grid;
    - each number is OCR'd from its own image box, never the cell, because cropping by cell turned 5.99 into 5.95;
    - two resolutions must agree, every rate matches `d.dd`, there is one number per cell, and rates must not decrease with amount;
    - headers and tier labels are layout checks.

    Parsing is split from OCR so the rules are tested on recorded OCR output; `make test-ocr` (excluded from `make test`, about 75 s) proves real OCR reproduces the recording on Tesseract 5.5.1 and 5.3.0.
12. **The table extractor expands `rowspan`/`colspan`** (rowspans never cross `<thead>`/`<tbody>`). ACB's table placed values under the wrong columns without it.
13. **Fixture tests that edit raw HTML normalise to NFC first and use the page's own entity forms.** Several banks mix composed and decomposed accents and HTML entities; the adapters handle that through `clean()`.

**Open follow-ups:** extra products per bank (CDs: Techcombank Bảo Lộc; VPBank pages 2–9; Techcombank "Tiền gửi Online" needs page cropping); `semiannual`/`annual` payments; whether ACB's bonus applies online; confirming the assumed interest-payment methods and MB's "north" label with the banks.

---

## 2026-10-28 — Validation, diff and staleness

Code: `pipeline/validate/` (`rules.yaml`, `rules.py`), `pipeline/diff/`, `core/freshness.py`, and the `python -m pipeline status` command.

**Decisions.**

1. **Rules live in `pipeline/validate/rules.yaml`, loaded into a strict pydantic model.** Unknown keys, unknown `table.field` names or `min > max` fail at start-up.
   - Ranges: deposit rate 0–12%, card APR 10–50%, FX fee 0–5%, annual fees 0–20 000 000 VND.
   - Any `*_pct` field changing by **more than** 0.5 points is flagged.
   - Removed series are flagged.
   - `effective_from` more than 60 days ahead is flagged.
2. **Every rule result is a warning in the review task's payload; nothing is auto-rejected.** Ranges are checked only on new or changed values: unchanged ones were already approved by a person.
3. **The diff goes through `propose_version` only,** so the versioning rules and DB guards still apply.
   - Unchanged values just record "last seen".
   - New or changed values become pending, with change events.
   - Values already pending from an earlier snapshot count as `already_pending` and are not added to a new task.
4. **One `review_task` (kind `version_review`) per snapshot.** It is created first so versions and change events can reference it, then deleted if there's nothing to review. Re-diffing the same snapshot reuses it.
   - Payload: institution, snapshot URL, a summary of counts, `items` (change, table, version id, key, old, new, changed fields, effective_from), and `warnings`.
5. **"Removed" means a current approved series whose version came from a snapshot of *this* source** and is missing from the new parse. It's listed and flagged, but nothing is written to the series: our versioning has no way to retire a series yet (**follow-up**). Scoping by source keeps BIDV's counter and online sources from "removing" each other's rates.
6. **Unknown cards get a `card_product` row and a `new_card_product` warning,** so a reviewer checks the name.
7. **The diff runs in a savepoint;** a `DiffError` (e.g. two records for one series) leaves nothing behind and the run reports `diff_failed`.
8. **Each adapter declares `extraction_method`,** stored on every version it proposes: JSON and HTML sources → `html`, PDF text and grids → `pdf_table`, VPBank → `ocr`.
9. **Staleness is computed, not stored** (`core/freshness.py`). A monitored source (active, confirmed, with a URL and an adapter) is stale after ≥ 2 failures in a row, if it has never succeeded, or if its last success is older than 2 × its cadence. An institution is `unverified` if any monitored source is stale, `no_sources` if it has none, else `verified`. Thresholds come from `rules.yaml` → `staleness`.
10. **Browser sources can require content before capture** (`browser_wait_for`): the fetch waits for page load and then for that text, instead of for network silence.
    *Why:* MB's deposit section loads late and a capture without it is useless; HDBank's analytics keep the network busy indefinitely. Missing text is a fetch failure, which feeds staleness.

**Observed on the first live diff (2026-10-28):** 8 banks produced pending rates with no warnings, all "new" on a first run. MB and HDBank fetches failed after many development visits, which looks like rate-limiting; HDBank shows as unverified, as designed.

---

## 2026-10-28 — Review app

Code: `review_app/` (FastAPI + Jinja2 + HTMX, logic in `review_app/service.py`). Migration `a518a9104f2c` adds `review_action`.

**Decisions.**

1. **HTTP basic auth, one account from `.env`** (`REVIEW_USERNAME` / `REVIEW_PASSWORD`), checked with a constant-time compare. The app refuses to start with an empty password. The username is recorded as the reviewer on every version and audit row.
2. **Cross-site request protection:** every write is a POST that must carry HTMX's `HX-Request: true` header, otherwise 403. Browsers resend basic-auth credentials to any page, so without this a form on another site could approve rates; another origin can't add the header without a CORS preflight, which the app never allows.
3. **Audit log `review_action` is append-only** (same trigger as `snapshot` / `change_event`). It records action, reviewer, time, note and the version ids affected, in the same transaction as the decision.
4. **All decisions go through `core/versioning`.** Approving closes the old version (`valid_to` = the new `valid_from`). Rows that are no longer pending (superseded by a newer snapshot, or already decided) are skipped by "approve all" and refused one by one (409).
5. **Task outcomes:**
   - **Approve all** → task `approved`.
   - **Reject** → `rejected`.
   - **Needs fix** → `needs_fix`, a note is required, and the task's pending values are **rejected** so nothing mis-extracted can go live; a fixed adapter will propose them again.
   - **Per row:** the task closes when its last pending row is decided, as `approved` if any row was approved, else `rejected`.
6. **Snapshots:**
   - The raw response always sends `Content-Security-Policy: sandbox` and `nosniff`.
   - HTML is shown in `<iframe sandbox>` with no scripts. For display only, a `<base href>` to the bank URL is injected so CSS and images load; the unmodified bytes stay one click away.
   - JSON is pretty-printed.
   - PDFs open in the browser viewer at `#page=N`, using a new optional `source_page` on records, for LLM-extracted card fields.
7. **Task page shows rates first and hides empty fields on new rows;** changed rows show every changed field as old → new. Measured on the real queue: the 273-row Techcombank task renders in about 0.13 s.
8. **UI language is Vietnamese** (CLAUDE.md), with no build step and htmx 2.0.4 saved in `review_app/static/`.
9. **The app runs as the `review` service in Docker Compose,** bound to `127.0.0.1` like the other services.

---

## 2026-10-28 — Scheduling and monitoring

Code: `pipeline/schedule.py`, `pipeline/scheduler.py`, `pipeline/monitor.py`, `pipeline/notify.py`, `/health` in `review_app`. Migration `81b9f0cbf608` adds `pipeline_run`, `notification`, and `source.last_attempt_at` / `last_status` / `last_error`.

**Decisions.**

1. **A built-in scheduler loop instead of Prefect** (`python -m pipeline schedule --loop`, Compose service `scheduler`; `--once` for system cron).
   *Why:* Prefect 3 needs its own server and a worker, plus memory and upgrades. We need fixed wall-clock slots in one time zone and "never two runs at once", which take about a hundred lines and are easy to test. The `prefect` dependency was removed and CLAUDE.md updated. Revisit if we need distributed runs or a run UI.
2. **Schedules are fixed slots in `Asia/Ho_Chi_Minh`** (no DST):
   - savings: 07:00 and 15:00 daily;
   - cards: Monday 07:00;
   - official: the 1st at 07:00;
   - news: 07:00 daily (placeholder).

   A source is due when its latest slot has passed and it hasn't been tried since. A failure is retried hourly for 6 hours after the slot. `cadence_hours` remains the staleness reference (savings 12 h covers the 16 h overnight gap within the 2× limit). `tzdata` is a dependency so the slim Docker image has the zone.
3. **Only a fully successful run counts as success.** `last_success_at` moves (to the snapshot's capture time) only when the run is `parsed` or `unchanged`. `parse_failed` and `diff_failed` increment `consecutive_failures` like fetch failures.
   *Why:* a page we fetch but can't read isn't being kept up to date. This supersedes the 2026-10-26 fetch-layer behaviour.
4. **Every run is logged in `pipeline_run`** (status, error, snapshot, new/changed/removed, review task, trigger `schedule`/`manual`) for the summary and monitoring.
5. **Ticks never overlap:** `fcntl.flock` on `settings.pipeline_lock_file`; a second tick skips. This also keeps the in-process rate limit meaningful.
6. **Alerts are sent on change of state:** `adapter_broken` when a source goes into `parse_failed`/`diff_failed` (any exception, not only `AdapterBroken`, since a crash is worse), and `adapter_recovered` when it comes back. Fetch failures don't alert immediately; staleness and the daily summary cover them.
   *Why:* the same alert at every slot trains people to ignore it.
7. **The daily summary goes out once a day from 19:00 local time:** runs in the last 24 h by status, changes found, open review tasks (with the oldest's age), broken adapters with their errors, and unverified institutions. A failed send is retried after 30 minutes.
8. **Telegram via the Bot API (`sendMessage`, HTML, escaped):**
   - token and chat id come from `.env`;
   - errors never include the token;
   - every attempt is recorded in `notification`, which also prevents duplicate summaries;
   - sending never raises;
   - without a token, messages are printed.
9. **`/health` lives in the review app,** the running web server, behind its login. It returns JSON per source: `state` (`ok` / `stale` / `broken` / `not_monitored`), last status, last attempt, age of last success, failures, stale reasons, last error and next run. `?strict=1` → 503 when degraded.
10. **The scheduler service sits behind a Compose profile,** so `make up` doesn't start it; `make scheduler` does.
    *Why:* starting it fetches every due bank at once, which should be a deliberate step.

---

## 2026-10-28 — News feeds and news-triggered re-checks

Code: `pipeline/news/` (`feeds.yaml`, `feeds.py`, `institutions.py`, `classify.py`, `llm.py`, `service.py`), `data/seeds/institution_aliases.csv`, `python -m pipeline news`, the scheduler tick, the task page and the daily summary. Migration `bf450b7f0ccb` adds classification fields to `news_item` and the `news_fetch` log. Details: [news.md](news.md).

**Decisions.**

1. **News never writes a value** (principle 1). An item only does three things:
   - it creates a `news_item` row;
   - it triggers an immediate run of the bank's own sources (`pipeline_run.trigger = "news"`);
   - its URL is attached to the resulting review task as context (`payload_json["news"]`).

   The reviewer still approves values read from the bank's page.
2. **Feeds are config (`feeds.yaml`), not `source` rows.** Every feed was checked on 2026-10-28 through `PoliteHttp`:
   - CafeF, VnExpress Kinh doanh, Vietstock (Ngân hàng) and Thời báo Ngân hàng all have working RSS.
   - **Thị trường Tài chính Tiền tệ was dropped.** Its robots.txt allows crawling, but every page, `/rss` included, gets 403 "Access Denied" from its firewall. We don't work around blocks.
   - A section-page fallback (`kind: html` + `link_pattern`) exists and is tested on a saved Thời báo Ngân hàng page, but no feed needs it today.
3. **Thời báo Ngân hàng labels Vietnam time as "GMT"**, so its dates are read as local time (`pubdate_is_local`). Otherwise every item would sit 7 hours in the future.
4. **Deduplication:**
   - by URL, with fragments and `utm_*`/`fbclid` stripped, permanently;
   - by folded title within 7 days. On the first live run this dropped 6 press releases syndicated between CafeF, Vietstock and Thời báo Ngân hàng.
5. **Institution matching uses names and aliases, without accents or punctuation.**
   - Names come from `legal_name_vi` (also without a trailing "Việt Nam") and `short_name`, plus `institution_aliases.csv` (brands, tickers, former names).
   - Short all-caps aliases (VCB, TCB, MB) must match in capitals.
   - Longer names win over overlapping shorter ones ("VCB Neo" → VCBNEO).
   - Risky tickers are left out (ABB, EIB: the Swiss company, the European Investment Bank).
6. **Keywords first, the LLM only where it can change the outcome.**
   - No topic word (lãi suất, huy động, tiết kiệm, phí thẻ, thẻ tín dụng, biểu phí) → irrelevant.
   - A headline that plainly says "<bank> tăng/giảm/điều chỉnh <lãi suất huy động | phí thẻ …>" → decided by keywords.
   - On topic but naming no known institution → decided by keywords too: there's nothing to re-check, so a model call buys nothing.
   - Everything else goes to the LLM: lending rates, the SBV, questions, rate tables, other verbs.
   - Keywords are matched with accents: folding would make "giảm" equal "giám" (giám đốc) and "tăng" equal "tặng" (quà tặng).
   - Saved feeds (155 items): 1 bank rate change decided by keywords, 8 items for the LLM.
7. **LLM call (Anthropic API, `client.beta.messages.create`):**
   - Model: `claude-opus-5-5`, the current default. The config default changed from `claude-sonnet-5-5`, and an empty `ANTHROPIC_MODEL=` also means this default.
   - `effort: low`, because classification needs little reasoning.
   - Structured output with a JSON schema: `{about_rates, about_card_fees, institutions, direction}`. `institutions` is an enum of our own codes, so the model can't invent a bank.
   - `fallbacks: "default"`, so a safety decline is retried on another model.
   - The cached system prompt lists every institution with its names. The headline goes in as JSON, and the prompt says to treat it as data.
   - At most 30 calls per run.
   - Any API error, refusal or malformed answer leaves the item unclassified for the next run and stops LLM calls for the rest of that run. Nothing is guessed.
   - With no `ANTHROPIC_API_KEY`, the LLM is off and ambiguous items wait. That is the case today: 8 are waiting.
8. **Re-check rules:**
   - Rate news re-runs `savings_rate_page` sources; card news re-runs `card_tariff_pdf` and `card_product_page` sources.
   - Each source runs once per news run, however many items point at it.
   - Only items from the last 48 h trigger a re-check.
   - A source tried in the last 30 minutes is not fetched again. The news is attached to its newest open review task instead.
   - With no change found, the news goes on the newest open task for that source from the last 48 h, if there is one.
   - A bank with no automated source is recorded as `no_source` in `news_item.recheck_json`. On the first live run, SCB's move to near-0% savings rates was such a case.
   - Rate limits are those of the shared `PoliteHttp`, because news runs inside the scheduler tick with its fetchers.
9. **News runs every hour, 06:00–22:00**, as part of the scheduler tick. It is due when no feed has been read since the latest hourly slot.
   - `python -m pipeline news` runs it by hand under the same lock.
   - Broken adapters found by a news-triggered run alert like scheduled ones.
   - The daily summary adds a news line and lists feeds whose last read failed.
10. **`defusedxml` parses feeds.** A feed is third-party XML, so entity expansion is refused.

---

## 2026-10-29 — Card pipeline (LLM extraction with quoted evidence)

Code: `pipeline/cards/`, `pipeline/adapters/techcombank_cards.py`, the review page (quotes), and `pipeline/runner.py` (retry after a failed parse). Migration `18f7dfd3aea3` adds `source_evidence` to every versioned table. Details: [cards.md](cards.md).

**Decisions.**

1. **Every value needs an exact quote, its page, and the value as written.** A fact is kept only if:
   - the quote is on that page of the document text we sent;
   - the parsed value appears in the quote ("Miễn phí" = 0).

   Failed facts are dropped and listed as warnings on the review task. Two different values for one card field are both dropped.
   *Why:* principle 1. A real quote next to an invented number is the main LLM risk, and the second check catches it. It can't catch a quote from the wrong row; the reviewer does.
2. **Schema shape: arrays of `{field, value, page, quote}` facts, every property required, no nullable types.** Missing means not returned.
   *Why:* the structured-outputs docs (read 2026-10-28) cap a schema at 24 optional and 16 union-typed parameters. One nullable `{value, page, quote}` object per field would exceed that for `card_terms` alone. The shape also makes "not stated" the default instead of a null the model has to pick.
3. **Card identity is curated, not extracted.** Each issuer has a catalogue: codes, stored names, networks, and per-document spellings. The model may only answer with codes. An unknown card makes the adapter raise.
   *Why:* the tariff and the product page spell cards differently ("Visa Signature" / "Techcombank Visa Signature"), and both must map to one `card_product`. Networks are often not in the documents; a card whose network the issuer doesn't state (Techcombank DreamCard) is not published.
4. **The tariff writes `card_terms`; the product page writes `card_reward` and `card_perk`. Never both for one table.**
   *Why:* `card_terms` has one row per card. Two sources each proposing the full row would keep nulling each other's fields. Interest rate and interest-free days need a third source (the card T&C), which is not built yet.
5. **Evidence is stored with the version** (`source_evidence` JSONB, provenance, frozen by the existing trigger) as well as in the review payload, so an approved value keeps its quote.
6. **Model and effort come from config:** `ANTHROPIC_MODEL` (default `claude-opus-5-5`) and `CARD_EXTRACTION_EFFORT` (default `high`, because accuracy matters more than cost here).
   - The request is streamed, with `max_tokens` 32,000.
   - The system prompt is cached across pages.
   - It uses `fallbacks: "default"`.
   - A refusal, truncation, API error or non-JSON answer fails the whole parse. A partial document is never used.
7. **A failed parse is retried on unchanged bytes.** The runner used to skip parsing whenever the hash matched the last snapshot. After a failed parse (`parse_failed`/`diff_failed`) it now parses again, so an API outage doesn't leave a document unread until the bank changes it.
8. **Adapter notes reach the reviewer.** `BaseAdapter.notes` (set by `parse()`) is passed to `diff_snapshot(notes=...)` and shown with the rule warnings.
9. **Text fallbacks:** pdfplumber; then Camelot when a page has text but no table; then Tesseract `vie` when a page has under 40 characters of text. Values from OCR pages are flagged on the review page.
10. **Techcombank** has 13 catalogue cards. 9 are expected in the standard-customer tariff, 12 are published, and DreamCard is held back (network unknown). Points rewards stated as "% in points" don't fit `card_reward` and are dropped with a note; a model change for that is a separate decision.

---

## 2026-10-29 — Card pipeline: first live run (Techcombank)

Model: `claude-sonnet-5-5`, the operator's `ANTHROPIC_MODEL` in `.env`. The tariff took 8 API calls in about 80 s.

1. **First tariff run:** every value returned matched the PDF, and nothing failed a quote check. But two kinds of row were under-read:
   - Multi-column rows: Visa Signature's late fee got its rate but not the `Tối thiểu` minimum.
   - The exclusion-scoped row "Thẻ tín dụng Visa khác (không gồm Visa Infinite, Visa Signature, Techcombank Style)": it was applied to no card.

   The prompt now says how to read both (each value column is its own fact; an exclusion row covers every listed card on that network not excluded and without its own row), and the card list in the prompt shows each card's network. The re-run filled the late fee for all 9 cards; every value checked by hand against the PDF.
2. **Text fields add up instead of conflicting.** Several different quotes for `other_perks_text` / `fee_waiver_rule_text` / `conditions_text` are joined with "; ". Each quote is kept in the evidence (`also`). The first product-page run wrongly dropped Visa Infinite's and Private's perks as "conflicts".
3. **Because the PDF was unchanged, re-runs used `--reparse`.** Values that changed were proposed as new pending versions in a new review task, and the earlier pending versions were superseded. Review tasks 10–13 hold the current pending card values (10 and 12 partly superseded).

---

## 2026-10-29 — Scoring methodology 1.0.0 and the public API

Code: `core/scoring/` (`savings.py`, `cards.py`, `data.py`, `METHODOLOGY_VERSION`) and `api/` (FastAPI; `make api` → 127.0.0.1:8002). Explained in [methodology.md](methodology.md) (Vietnamese and English).

1. **Savings rank on interest valued at maturity.** Every payment is assumed to be reinvested at the offer's own rate until maturity.
   - Monthly: (1 + r/12)ⁿ − 1.
   - Quarterly: compounded per quarter, with leftover months simple.
   - Upfront: r·t·(1 + r·t).

   *Why:* it is the one assumption that treats all schedules alike, and it needs no outside rate. The cash interest the bank actually pays is shown next to it. Time is months / 12, not actual days.
2. **One listing per product.** For an amount, only the tier it falls in (highest floor ≤ amount) is used. Offers above the amount are excluded and counted.
3. **Flags never change the rank.**
   - Most flags are read from the bank's own conditions text with keywords. "tối đa" → `rate_is_maximum`, which is common in the live data.
   - `early_withdrawal_penalty` is on for every term deposit.
   - `deposit_insurance` comes from the institution row.
4. **Card value follows the brief's formula exactly, per year.**
   - Monthly caps × 12.
   - Categories without their own cashback reward fall back to the card's "all" reward, whose cap is shared.
   - Foreign spend counts as the "overseas" category.
   - w = 1 only when a waiver rule is known and 12 × monthly spend reaches it.
5. **Missing inputs are never guessed.** A card is "not ranked", with its reasons, when the formula needs a missing value: the annual fee always; the FX fee only with foreign spend; the interest rate only with a balance. The income filter works the same way.
   - Today all Techcombank cards are not ranked for the `revolver` preset, because neither of their documents states an interest rate.
6. **Points and miles count 0 (flagged)** until we decide how to value them. Shared caps stored per category can overstate cashback for heavy spenders in several categories. Both are documented as limits.
7. **Four presets** (`everyday`, `traveller`, `first_card`, `revolver`) with illustrative numbers, published in the methodology document.
8. **Every API response carries the version,** errors included: `methodology_version` in the body and `X-Methodology-Version` as a header. Decimals are strings, never floats.
   - Endpoints: `/v1/methodology`, `/v1/savings`, `/v1/cards/personas`, `/v1/cards?persona=`, and `POST /v1/cards/score`.
   - Rankings use approved, live versions only.
9. **Versioning rule:** any change to a formula, assumption or preset bumps `METHODOLOGY_VERSION` and adds a changelog row to methodology.md.

---

## 2026-10-29 — Public API v1 (read-only, cached)

Code: `api/` (`app.py`, `routes/`, `schemas.py`, `common.py`, `reports.py`). See [api.md](api.md). This replaces the `/v1/...` routes added earlier the same day; they had no users.

1. **Paths as specified, without a `/v1` prefix.** The methodology version in every response (body and `X-Methodology-Version` header) plays the role of a version marker. A breaking change to the API shape would add a prefix then.
2. **Provenance per value, not per response.**
   - `source_url` is the snapshot's URL, which is what was actually fetched.
   - `checked_at` is the later of the snapshot's fetch time and `last_seen_at` (set when a later fetch found the value unchanged).
   - `effective_from` comes from the version. Approval time, extraction method, snapshot hash and LLM evidence are included too.
   - Institutions (curated seed data) use their website and the last successful source read.
3. **Response models are Pydantic schemas,** so `/docs` shows real types. Handlers serialise themselves (to cache bytes and compute ETags), and the `response_model` declarations keep the OpenAPI schema accurate.
4. **Caching:**
   - an in-process TTL cache (60 s) keyed by method + URL (+ body for `POST /cards/rank`);
   - ETag/304;
   - `Cache-Control: public` for GETs.

   *Why:* values change a few times a day, after a human approves them, so a minute of staleness is harmless, and it keeps scoring off the database for repeat queries. If several API processes run, put a CDN in front, which can use these headers.
5. **`/changes`:**
   - **What counts:** an approved version is "changed" when an approved version of the same series was closed at the instant it went live (approval does both at once); otherwise it is "new".
   - **Field diffs:** they come from `change_event`, with decimals reformatted to the column's scale so old and new compare cleanly ("6.000" → "6.200").
6. **Reports:**
   - **What's stored:** the message, the optional contact (never returned) and an optional screenshot, validated by its first bytes (PNG/JPEG/WebP, ≤ 5 MB) and stored in MinIO by SHA-256.
   - **Rate limit:** per IP, in process. `X-Forwarded-For` is trusted only when configured.
   - **Captcha:** a `Captcha` interface. It is off by default. Turnstile and hCaptcha are implemented through their `siteverify` endpoints, and an unreachable provider means the report is refused.
   - Reports never publish anything.

---

## 2026-10-29 — Public site (web/)

Next.js 16.4 (App Router, TypeScript, Tailwind 4), Cache Components on. Details: [web/README.md](../web/README.md).

1. **Static pages rebuilt on approval, through tagged caches, not full rebuilds.** All API reads are `"use cache"` functions tagged `soivi`.
   - The review app calls `POST /api/revalidate`, authenticated with a shared secret (`SITE_REVALIDATE_SECRET`), after every approval, as a background task that never fails the approval.
   - The route expires the tag at once (`{ expire: 0 }`), so nobody is served the old number after the next visit.
   - An hourly refresh catches freshness changes.
   - The API now skips its own cache for requests with `Cache-Control: no-cache`, which the site sends.
   - Verified end to end: an approved rate appeared on the bank and rate-moves pages after the webhook, and not before.
2. **The container builds at start.** Next 16 prerenders every page from live data, so the build needs the API. `web/scripts/start.sh` waits for it, builds, then runs the standalone server.
3. **URLs:** Vietnamese at the root, English under `/en`, with the same Vietnamese slugs. `proxy.ts` maps both onto `app/[lang]`.
4. **One formula.** The calculator and custom card profiles call the API through route handlers; preset rankings are fetched at build time. There is no TypeScript copy of `core/scoring`.
5. **The methodology page is rendered from `docs/methodology.md`,** so the published method and the document can't drift.
6. **Performance choices** (all pages measured green on mobile Lighthouse):
   - no web fonts;
   - an SVG chart without a library;
   - the report dialog is rendered only when opened;
   - no `<Suspense>` around prerendered content (streaming caused CLS 0.27 on the bank page);
   - the weekly changes table is capped at the 40 largest moves per week, with a count of the rest.
7. **Reports go through the site** with the visitor's IP in `X-Forwarded-For`. The API trusts that header in Compose (`TRUST_PROXY_HEADERS=true`) because its port is bound to 127.0.0.1. In production, only the site (or the reverse proxy) may reach the API.
8. **A fictional demo database** (`scripts/demo_db.py`, `soivi_demo`, banks named "Ngân hàng Demo …" on example.com) is for UI work and measurement. Real values are never approved for testing.

---

## 2026-10-29 — Credit cards: BIDV and VPBank

Two more fee schedules on the card pipeline: `bidv_card_tariff` (18 cards published) and `vpbank_card_tariff` (12 published). Details: [docs/adapters/bidv.md](adapters/bidv.md), [docs/adapters/vpbank.md](adapters/vpbank.md).

1. **Cards-as-columns tables are read with column labels** (`label_columns`, `pipeline/cards/document.py`).
   - **The problem:** VPBank puts each card in a column. As plain rows, "359.000 VND" carries no card name, so a quote couldn't prove which card it belongs to.
   - **The fix:** the reader prefixes each cell with the header text above its column (`[MC2] 359.000 VND`), found by position. The usual quote check then proves the mapping.
   - **Reading the headers:**
     - letter-spaced header text is joined with `x_tolerance=5`;
     - bold text drawn twice is de-duplicated;
     - title rows (one cell) are skipped;
     - crops are clamped to the page.
   - **When it backs off:** if fewer than 60% of columns get a label, the table is left as it was. Techcombank's card-as-row tables are unchanged.
2. **`section` page filter.** BIDV's schedule is 24 pages; only the credit card section (pages 1–6) is sent to the model. The start marker must be found, or the run raises. Cost and noise both drop.
3. **Per-bank `reading_notes`** are appended to the system prompt. They say how *this* document is laid out:
   - which segment column to use;
   - what "TT"/"TĐ" mean;
   - which cash-advance row is general.

   They never contain values.
4. **Interest needs a stated period.** Both banks print card interest ("18%", "3.99%") without saying per year or per month. `interest_rate_pct` is now rejected unless its quote says "năm" / "per year" / "p.a.". A rate that might be monthly must never be shown as yearly. Those cards rank without interest until a bank page states the period.
5. **"Không thu phí" / "Không tính phí" read as 0,** like "Miễn phí". Before this, VPBank's free supplementary cards were dropped as unreadable.
6. **The VPBank source moved from a fixed PDF to the document listing.** The seeded PDF was an undated 2020 file. The adapter now takes the newest "Biểu phí thẻ tín dụng tại VPBank" document, as the savings adapter already does.
7. **BIDV's discontinued cards** (annex "thẻ ngừng phát hành") are published with their annual fees and the late fee from the "Thẻ khác" (other cards) row, which covers every card not named above it. No FX or cash-advance row reaches them, so those fields stay empty. Reading "Thẻ khác" as covering discontinued cards is an inference, so it is flagged to the reviewer.
8. **A card is published only with a network the bank writes.**
   - **VPBank:** 21 cards whose network isn't in the schedule or on their card page are held back as `not_published`.
   - **BIDV:** Private Banking is held back the same way.
9. **Known gap: late fee bases differ.**
   - VPBank: 6% of the *minimum payment*.
   - Techcombank and BIDV: a percentage of the *overdue amount*.

   `late_fee_pct` stores the number as written; the evidence quote shows the base. The scoring formula doesn't weight late fees today. Revisit the field if it does.

---

## 2026-10-29 — Rankings need reward data; card pages read one by one

1. **A card with no reward data is not ranked** when the profile spends anything (`rewards_unknown`, methodology 1.1.0).
   - **Why:** "no reward read yet" was scored as "earns nothing", so 40 of 42 cards ranked on fees alone with no warning. That broke the "nothing is guessed" rule in spirit.
   - **Known gap:** a card that truly earns nothing also stays unranked, until there's a way to record "the bank states no rewards".
2. **Product pages are read one card page at a time.**
   - **Why:** list pages carry only headlines; rates, categories and caps are on each card's page.
   - **How:** one source per page; `source.variant` names the page, and the adapter's `card_pages` maps it to catalogue codes.
   - **Other cards:** facts about other cards named on the page ("compare cards" blocks) are ignored with an `other_card_on_page` note, and unknown card names on such a page don't raise.
   - **Empty pages:** a card page may state nothing we store. That's allowed (`allows_empty`) and noted, while every other source still refuses an empty result.
3. **Headlines are not reward terms.**
   - **Prompt:** rewards are taken only from the passage that sets the rate, the spending and the cap.
   - **Categories:** spending outside the formula's categories (health, education, entertainment, one merchant such as Shopee or MWG) goes to `other_perks_text`, not into a category it doesn't match.
   - **Cap check in code:** a cashback reward with no cap is dropped (`dropped_no_cap`) unless the quote says "không giới hạn". Example: VPBank Z's "15% cho mọi chi tiêu" is really three categories capped at 500,000 each.
4. **VPBank's card details are decoded from page data** (Next.js `__next_f` text blocks), not fetched with a browser. It's the same bytes as the page, and no extra requests.
5. **VPBank's 3.99% is per month,** per its own FAQ. The 2026-10-29 rule that kept it out of `interest_rate_pct` was right.
6. **Not yet:** product pages state yearly interest (BIDV "20%/năm") and waiver rules, but they still don't write `card_terms`. That keeps two sources from overwriting each other's rows (Techcombank decision). It's the next step for interest rates.
7. **(2026-10-30) Three reading rules, after checking the first live run by hand:**
   - **Tiered rewards are text, not rates.**
     - Example: BIDV JCB Ultimate pays 10% on dining (cap 800,000) at 10 million a month or more, and 5% (cap 300,000) below that.
     - The formula has no spend tiers, and storing either tier misstates the other spender. These passages go to `other_perks_text` (prompt rule).
     - Supporting tiers (a minimum monthly spend per reward) is a follow-up.
   - **"Up to" rates are rejected in code.** A quote reading "lên đến 10%" / "tới 10%" / "up to 10%" is a ceiling, not the rate (`verify.py`).
     - This also drops Techcombank's list-page rewards ("Hoàn tiền lên tới 5 triệu/tháng, tới 10%"), which were stored as 10% capped at 5M.
     - The approved Techcombank rows stay live until a reviewer retires them. The next list-page run will show them as "removed".
   - **Travel insurance needs the word "du lịch".** "Bảo hiểm cho chủ thẻ" may be any cover.
8. **A task marked "needs fix" can be proposed again from the same snapshot.**
   - **Before:** a re-parse of a snapshot that already had a review task changed nothing, so a corrected parser couldn't re-propose values whose task was sent back.
   - **Now:** that holds for every other task status.
9. **(2026-10-30) Techcombank moves to card pages too.**
   - 12 sources (`techcombank_card_pages`) replace the list-page source, which is no longer monitored (its seed row has no adapter).
   - The list page only had headlines. Two sources writing perks for the same cards would keep replacing each other's rows.
   - The corrected Visa Signature reward is 5% on dining and 3% on travel, capped at 2M a month, replacing 10% capped at 5M. It goes through review as a "changed" value, flagged as a large change.

---

## 2026-10-30 — Card interest from product pages (`card_interest`)

1. **A separate versioned table, `card_interest`,** holds one row per card: the yearly rate and the interest-free days, read only from the card's product page.
   - **Why separate:** `card_terms` comes from the fee schedule; if both sources wrote it, each run would replace the other's row.
   - **Precedence:** scoring uses `card_interest` when present, else `card_terms.interest_rate_pct` (methodology 1.2.0). The API shows it as `interest` on a card.
   - **History is protected** by the same guard trigger as the other value tables.
2. **Only rates stated per year are stored.** VPBank states its rates per month ("3.99%/tháng") and they are not converted. ×12 would be our calculation, not the bank's value. Revisit if we decide to show monthly rates as such.
3. **A range is rejected** ("Lãi suất: 15,5% - 16,5%/năm"): which rate applies depends on the customer.
4. **Re-parsing a decided snapshot** (approved, rejected or needs fix) may now propose again. Only an open task blocks it.
   - **Why:** adding a field to a parser must be able to reach pages whose bytes haven't changed.
   - **No duplicates:** values already approved come out "unchanged", so the new task holds only what is new. An empty result opens no task.
   - The scheduler never re-parses unchanged bytes by itself; this takes an explicit `--reparse`.
5. **Approved text is kept while the page still says it** (`keep_approved_text`, `pipeline/cards/build.py`).
   - **The problem:** text fields (perks, conditions) are built from the quotes the model picks, so a fresh read of an unchanged page can reword them. The first interest re-run proposed "changed" perks for every card, and Visa Infinite's text lost a sentence.
   - **The rule:** when every quote behind the approved text is still on the page, the approved text and its evidence are kept, and the diff sees no change. A sentence the bank removed fails the check, so real changes still reach review.
6. **More fixes from the re-run:**
   - **Ranges written with words are rejected** ("17% đến 18%/năm").
   - **Numbers with a unit word are read** ("20 điểm", "1 dặm"), still checked against the quote. A value with two numbers is rejected.
   - **Approved rows the model leaves out are kept while their quotes are still on the page** (`_still_stated`). They come out unchanged instead of showing as false "removed" items.
   - **A minimum-spend condition is a tier** ("áp dụng cho KH có tổng doanh số từ 5 triệu/kỳ sao kê"): text, not a rate.
7. **Known gap: approved values can't be retired yet.** A "removed" item is information only; nothing closes the approved row. Example: VPBank MWG's approved 0.1% applies only from 5M a month in spend, which the new rule would keep out. It needs a "retire" action in the review app.
8. **(2026-10-30) Retiring a live value ("Gỡ").** The review app can take a live approved value down without a successor.
   - **Where:** on a task page, for "removed" items and for approved items that are still live.
   - **How:** a note is required. Only `valid_to` is set, so the row and its approval stay in history; the audit log records the action `retire`, who did it and why. The site is refreshed.
   - **Why:** "removed" items and values that no longer meet the reading rules (e.g. VPBank MWG's 0.1%, which needs 5M a month in spend) had no way down.

---

## 2026-10-30 — Website redesign on the SoiVí design system

The site follows the SoiVí design system (claude.ai artifact 8HDJ378MFAbBLaTZgLWvtG): its tokens, brand book and components.

1. **Tokens become CSS variables** (`web/app/globals.css`), light first and dark when the visitor's system asks. Tailwind maps them as `jade`, `gold-ink`, `surface-alt` and so on. Component classes (`sv-*`) follow the system's `bundle.css`, inside Tailwind's components layer so utilities can still adjust them.
2. **Font: Be Vietnam Pro** (`next/font/google`, weights 400–800). This replaces the 2026-10-29 choice of system fonts: the brand book picks it because it was drawn for Vietnamese diacritics.
   - Next downloads it at build time and serves it from our own domain, so visitors make no request to Google.
   - The build needs network access to Google Fonts.
3. **Components ported** to React (`web/components/ui.tsx`): Icon, Button, Badge, SourceStamp, TipBox, CategoryTile and CardArt.
   - Ranked cards use the ProductCard layout; rate tables use RateTable's highlight and "Cao nhất" badge; the savings calculator uses its result panel.
   - The calculator opens already answered (100M, 12 months), ranked at build time.
4. **Not used: RatingStars ("Điểm Soi").** The system says the score must come from the published methodology and never be set by hand, and our methodology ranks by net VND value, with no 0–5 score. Adding one would be a methodology change.
5. **Every number keeps its source stamp,** and unverified data is marked. Pros/cons and "So sánh" on product cards are left out: we have no sourced pros/cons, and no compare feature.
6. **Brand name shown as "SoiVí"** (code, URLs and the repository name stay as they are).
7. **Known issue: the site build can time out** when its 7 build workers hit the single-process API at once. One build failed with "use cache took too long" on /changes; the endpoint takes 0.3 s on its own. A retry passed. Fix later: more API workers, or fewer build workers.

---

## 2026-11-05 — VNCMA workstream added

**Context.** Start the goals-based wealth planning phase with VNCMA: a public, versioned set of 10-year capital market
assumptions for Vietnamese asset classes. Spec: `docs/vncma/spec.md`; prompts: `docs/vncma/prompts.md`.

**Decisions.**

1. **Same repo, same stack.** VNCMA lives in this repo on PostgreSQL + MinIO, consistent with "Keep PostgreSQL"
   (2026-10-25). An earlier draft plan to use MongoDB for VNCMA is dropped.
   *Why:* one source of truth, the same append-only and approval machinery, and the cash class reads Phase 1 savings rates directly.
2. **Scoped exception to principle 1.** "The bank is the only source of record" governs bank product values. For
   VNCMA the sources of record are approved Phase 1 savings rates, vnstock market/macro data (Golden tier, sponsor
   package `vnstock_data`) and official statistics. Only derived statistics are published, never raw vnstock series.
   *Why:* market and macro data have no bank-page equivalent; vendor licence terms forbid redistributing raw data.
3. **Principles 2–5 apply unchanged** to VNCMA: provenance on every input, append-only history, named human approval
   before a release is published, and a public versioned methodology.
4. **No paid data vendors for now** (WiFeed, FiinGroup considered on 2026-11-01). Gaps are covered by our own
   collectors (deposit rates, SJC gold) and manual, graded inputs.

**Open follow-ups:** where vnstock runs (host vs container, device limits of the plan); reuse of `snapshot`/`source`
vs parallel market tables; VNCMA methodology version naming; publishing brand and review committee.

---

## 2026-11-05 — Monthly updates and hosting without a VPS

**Context.** The owner judged a VPS too expensive for now. Savings rates and card terms change rarely, and VNCMA
statistics are monthly, so an always-on server is not needed yet.

**Decisions.**

1. **Every bank source runs monthly** (savings pages, card tariffs, card product pages, official: the 1st at 07:00
   Asia/Ho_Chi_Minh), replacing the daily/weekly slots of 2026-10-28. `cadence_hours` is 744 (31 days) for every
   seeded source, so data shows as unverified after 2 × 744 h ≈ 62 days without a successful fetch.
   - A run started after the 1st (machine was off) still picks up that month's slot.
   - A failed source is retried only within 6 h of the slot; after that, re-run it with `--institution` or `--source`.
   - News feeds stay as they are; they only run while the scheduler runs, and a news item can still trigger an
     early re-check of one bank.
   - The site keeps its freshness flag, so slower updates stay visible to readers.
2. **No VPS for now. Target hosting:**
   - public site (`web/`) on Vercel;
   - PostgreSQL 16 on Neon (managed, Singapore). Not MongoDB: versioning, append-only triggers and the VNCMA cash
     class all depend on PostgreSQL (see 2026-10-25 and the VNCMA entry above);
   - snapshots in the owner's AWS S3 bucket (ap-southeast-1, versioning on) instead of MinIO;
   - pipeline, review app and VNCMA jobs run on the owner's Mac when needed. vnstock is tied to that device anyway.
   - Open: where the public API runs so Vercel can reach it (candidate: the read-only API as a Vercel Python
     function reading Neon). To be checked before deploying.
3. **VNCMA collectors are monthly, not daily** (changes VNCMA Prompt 4). The cash class uses our own approved
   savings rates; SJC gold takes one monthly point. The vnstock deposit-rate snapshot becomes a monthly cross-check.

**Revisit** when updates need to be more frequent than monthly: a small VPS (about USD 5/month) or a scheduled CI job.

---

## 2026-11-05 — vnstock 5 in the project environment (VNCMA Prompt 1)

1. **`vnstock==5.2.1` from vnstocks.com's own index**, declared in `pyproject.toml` as an `explicit` uv index:
   only `vnstock` may come from it, everything else stays on PyPI (no dependency confusion). Pinned exactly;
   6.0 is only a release candidate (Linux only) as of today.
   - vnstock 5 merged the sponsor package: `vnstock_data`, `vnstock_installer`, `vnai` are no longer used.
   - The paid tier is unlocked by the API key stored on the machine (`vnstock register`, in `~/.vnstock`,
     or `VNSTOCK_API_KEY`). It is never committed. This Mac is registered (Golden, plan until 2027-04-09).
   - **Each vnstock release stops working after a date** (5.2.1: 2027-10-27). `market check` prints the days
     left; upgrade before then.
   - In a container, mount a volume at `VNSTOCK_HOME`, or every rebuild counts as a new device (limit 13).
2. **Added `pandas`, `numpy`, `scipy`, `openpyxl`** for `core/cma` and the xlsx report.
3. **One wrapper:** `pipeline/market/client.py` is the only module that imports vnstock (lazily). Calls that fail
   or return nothing raise `MarketDataError` naming the call. `python -m pipeline market check` prints the version,
   tier and the latest VN30 close.
4. vnstock attaches provenance to every result (`df.attrs`: source, route, organisation, terms URL, robots.txt
   note, requested_at). The ingest step (Prompt 3) stores it with each snapshot.
