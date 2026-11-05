# Soivi

A free, community-first comparison site for Vietnamese financial products (a NerdWallet for Vietnam). Phase 1 covers savings / term deposits, certificates of deposit and credit cards.

Project rules and conventions are in [CLAUDE.md](CLAUDE.md). Design decisions are in [docs/DECISIONS.md](docs/DECISIONS.md).

## Layout

```
pipeline/      adapters, fetch, extract, validate, diff
core/          config, db, models, scoring
migrations/    Alembic migrations (metadata comes from core/db.py)
review_app/    internal review UI (FastAPI + Jinja2 + HTMX)
api/           public API
web/           public site (Next.js), not scaffolded yet
data/seeds/    seed data
tests/         offline tests; saved bank pages in tests/fixtures/<bank>/
docs/          methodology, adapters, decision log
```

## Make targets

| Target | What it does |
|---|---|
| `make up` | Build and start Postgres, MinIO and the pipeline container |
| `make down` | Stop containers (data volumes are kept) |
| `make migrate` | `alembic upgrade head` inside the pipeline container |
| `make seed` | Load `data/seeds/` inside the pipeline container (safe to re-run) |
| `make pipeline ARGS="run --all-due"` | Fetch, store and parse sources (see below) |
| `make check-seeds` | Re-check seed URLs politely |
| `make review` | Start the review app on http://127.0.0.1:8001 (login from `.env`) |
| `make scheduler` | Start the scheduler (not started by `make up`) |
| `make scheduler-logs` | Follow the scheduler's output |
| `make test-ocr` | Slow OCR tests (needs Tesseract) |
| `make shell` | Bash shell in the pipeline container |
| `make test` | Offline test suite (runs on the host with uv) |
| `make lint` | `ruff check`, `ruff format --check` and `mypy --strict` |
| `make fmt` | Auto-fix lint issues and format |

## Local development (macOS / Linux)

```bash
# 1. Install uv: https://docs.astral.sh/uv/
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install Python 3.12 and all dependencies (uv downloads Python if needed)
uv sync

# 3. Git hooks
uv run pre-commit install

# 4. Config
cp .env.example .env        # then edit the change-me values

# 5. Services + database
make up
make migrate

# 6. Before calling anything done
make lint
make test
```

New migration after changing models in `core/`:

```bash
make shell
alembic revision --autogenerate -m "describe the change"
```

## Running the pipeline

```bash
make pipeline ARGS="adapters"                    # list registered adapters
make pipeline ARGS="run --source 12"             # one source by id
make pipeline ARGS="run --institution ACB"       # one institution's sources
make pipeline ARGS="run --all-due"               # everything past its cadence (for cron)
make pipeline ARGS="run --all-due --reparse"     # also re-parse unchanged pages
```

Each run fetches the page politely (robots.txt, at most 1 request per 5 s per host, retries), stores the raw bytes in MinIO under `{institution}/{source_kind}/{date}/{sha256}.{ext}`, and writes a `snapshot` row. A page whose bytes match the previous snapshot is marked `unchanged` and not parsed. `--all-due` and `--institution` skip sources that are inactive, flagged `needs_check`, or have no URL or adapter.

Writing an adapter: subclass `BaseAdapter` in `pipeline/adapters/`, decorate it with `@register`, set `adapter_name` on the matching `source` row, and add fixture tests in `tests/fixtures/<bank>/`. See the docstring in `pipeline/adapters/base.py`.

## Scheduling and alerts

`make scheduler` starts a service that checks every 5 minutes which sources are due and runs them:

| Source kind | Runs at (Asia/Ho_Chi_Minh) |
|---|---|
| savings_rate_page | every day at 07:00 and 15:00 |
| card_tariff_pdf, card_product_page | Mondays at 07:00 |
| official | the 1st of each month at 07:00 |

A failed run is retried hourly for up to 6 hours. Runs never overlap (file lock).

**Telegram.** Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`:

1. Create a bot with @BotFather.
2. Send it a message.
3. Read your chat id from `https://api.telegram.org/bot<TOKEN>/getUpdates`.

You then get an immediate alert when an adapter breaks (and when it recovers), plus a daily summary at `DAILY_SUMMARY_HOUR` (19:00). Without a token, messages are printed to the scheduler log.

```bash
make pipeline ARGS="summary"          # print today's summary
make pipeline ARGS="summary --send"   # send it now
```

**Health.** `GET /health` on the review app (same login) lists every source with its state, last status, the age of its last success and its next run. `?strict=1` answers 503 when something is stale or broken, for an uptime monitor.

## Reviewing changes

Every pipeline run that finds new, changed or removed values opens one review task per snapshot. Set `REVIEW_USERNAME` / `REVIEW_PASSWORD` in `.env` (the app won't start without a password), then:

```bash
make review                  # http://127.0.0.1:8001
```

- **Hàng chờ** (queue): open tasks, oldest first, with counts and warnings.
- **Task page**: old → new per field (rates first), rule warnings, and a link to the stored snapshot (HTML in a sandboxed frame, PDFs in the browser viewer). Buttons: **Duyệt tất cả** (approve all), **Từ chối** (reject), **Cần sửa** (needs fix, note required), and ✓/✗ per row.
- **Nhật ký** (audit log): every decision with reviewer, time and note. It's append-only in the database.

On a VPS the app listens on 127.0.0.1 only: `ssh -L 8001:localhost:8001 you@server`.

## Fresh Ubuntu VPS (22.04 / 24.04)

Run as a sudo user, not root. Plan for at least 2 GB RAM and 20 GB disk.

### 1. Base packages and firewall

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y git make curl ca-certificates ufw

sudo ufw allow OpenSSH
sudo ufw enable
```

Postgres (host port `POSTGRES_PORT`, default 5433) and MinIO (9000/9001) are bound to `127.0.0.1` in `docker-compose.yml`, so they are not reachable from the internet. Reach them over an SSH tunnel, for example `ssh -L 9001:localhost:9001 you@server` for the MinIO console.

### 2. Docker Engine + Compose plugin

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker "$USER"
newgrp docker          # or log out and back in
docker run --rm hello-world
```

### 3. uv (for `make test` / `make lint` on the host)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
```

### 4. Clone and configure

```bash
git clone <repo-url> soivi && cd soivi
cp .env.example .env
chmod 600 .env
```

Edit `.env`:

- Generate passwords with `openssl rand -base64 24` for `POSTGRES_PASSWORD` and `MINIO_ROOT_PASSWORD`.
- Put the same Postgres password in `DATABASE_URL`, and set `S3_ACCESS_KEY` / `S3_SECRET_KEY` to match the MinIO root user and password.
- Set `CRAWLER_USER_AGENT` to a real contact email.
- Set `ANTHROPIC_API_KEY`.
- Set `ENVIRONMENT=production`.

### 5. Start and migrate

```bash
make up
make migrate
make seed
docker compose ps        # postgres and minio "healthy", minio-init "exited (0)"
```

### 6. Check it works

```bash
uv sync
make lint
make test
```

### 7. Backups (do this before storing real data)

Snapshots and version history are the project's evidence, so back up both volumes:

```bash
# Postgres
docker compose exec -T postgres pg_dump -U soivi -Fc soivi > backup-$(date +%F).dump
# MinIO volume
docker run --rm -v soivi_miniodata:/data -v "$PWD":/backup alpine \
  tar czf /backup/minio-$(date +%F).tgz -C /data .
```

Copy these off the server, e.g. to a separate object store.

## Notes

- MinIO no longer publishes community images to Docker Hub, so `docker-compose.yml` uses `cgr.dev/chainguard/minio`.
- The pipeline image includes Tesseract with Vietnamese data and Playwright Chromium, so the first build is large (around 2 GB) and slow.
