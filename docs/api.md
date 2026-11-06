# Public API

Run it with `make api` (Docker): http://127.0.0.1:8002, interactive docs at `/docs` and `/redoc`, schema at `/openapi.json`. Locally: `uv run python -m api`.

The API is read-only except `POST /reports`. It only serves values a person approved in the review app; pending, rejected and superseded values never appear.

| Endpoint | What it returns |
|---|---|
| `GET /institutions` | Banks and finance companies, with `verification` (`verified` / `unverified` / `no_sources`) |
| `GET /savings/rates?term=&channel=&amount=&institution=` | Current approved rates; `amount` keeps only rates whose minimum is ≤ amount |
| `GET /savings/rank?amount=&term=&channel=&region=` | Ranking by VND earned at maturity ([methodology](methodology.md) §1) |
| `GET /savings/history?institution=&term=` | Every approved value over time, one series per product / channel / region / tier / payment; a point is live while `valid_to` is null |
| `GET /cards`, `GET /cards/{id}` | Cards with approved terms, rewards and perks |
| `GET /cards/personas` | The preset spending profiles |
| `POST /cards/rank` | `{"persona": "everyday"}` or `{"profile": {...}}` → annual net value ([methodology](methodology.md) §2) |
| `GET /changes?since=YYYY-MM-DD&limit=` | Approved changes, newest first: old → new per field; `kind` is `new` or `changed` |
| `POST /reports` | A community report (multipart form; see below) |
| `GET /methodology` | The methodology version and the options its formulas accept |
| `GET /vncma/latest`, `GET /vncma/{version}` | An approved VNCMA release: 10-year expected returns, volatilities, correlations, scenarios, macro assumptions; `methodology_version` is the VNCMA method's (also in `X-VNCMA-Methodology-Version`) |
| `GET /vncma/releases` | Every approved VNCMA release, newest first |
| `GET /vncma/{version}/download/{xlsx,json,md}` | The release as a workbook, JSON or Vietnamese markdown |

## What every value carries

Each value has a `provenance` object:

- **`source_url`**: the bank's page or document it was read from.
- **`checked_at`**: the last time we read that source and found this value. This is the original fetch, or a later re-check that saw it unchanged.
- **`effective_from`**: the date the bank says the value applies from, if stated.
- **`methodology_version`**.
- **Also:** `approved_at`, `extraction_method`, the SHA-256 of the stored copy, and, for LLM-read values, `evidence` (page and exact quote per field).

Every response, errors included, also carries `methodology_version` in the body and the `X-Methodology-Version` header.

Formats:
- Amounts are integer VND.
- Rates are decimal strings (`"6.200"`), never floats.
- Times are UTC ISO 8601.

## Caching

- **Read responses** are cached in the API process for `API_CACHE_SECONDS` (default 60). They carry an `ETag` (`If-None-Match` → 304) and `Cache-Control: public, max-age=60`, so a CDN can cache them too. `X-Cache` says `HIT` or `MISS`.
- **`POST /cards/rank`** is cached by request body.
- **A newly approved value** shows within a minute.

## `POST /reports`

Multipart form fields:
- `message`: 10–2000 characters, required.
- `institution`: a `short_name`, optional.
- `product_ref`: optional.
- `contact`: optional. It is stored and never returned or published.
- `captcha_token`.
- `screenshot`: optional. PNG, JPEG or WebP, checked by content, not by the declared type; at most 5 MB. It is stored in MinIO under `reports/`.

Limits and checks:
- **Rate limit:** `REPORT_RATE_LIMIT_PER_HOUR` per client IP (default 5); over it the API answers 429 with `Retry-After`. Behind a reverse proxy, set `TRUST_PROXY_HEADERS=true` to use `X-Forwarded-For`. The limit lives in one process; run one API process, or move it to Redis before scaling out.
- **Captcha:** off until `CAPTCHA_PROVIDER=turnstile` (or `hcaptcha`) and `CAPTCHA_SECRET` are set. Then every report needs a valid `captcha_token`. If the provider can't be reached, the report is refused.

A report never changes a published value (CLAUDE.md principle 1). Reports are stored with status `new` for a person to triage. The triage screen isn't built yet.
