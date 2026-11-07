# Deploying: site on Vercel, API on Fly.io

| Part | Where | Notes |
|---|---|---|
| Public site (`web/`) | Vercel | Calls the API at build time and on the hourly refresh |
| Public API (`api/`) | Fly.io, Singapore (`fly.toml`) | Slim image (`SLIM=1`), 512 MB, stops when idle |
| Database, snapshots | Neon, S3 (ap-southeast-1) | Unchanged |
| Pipeline, scheduler, monthly job, review app | The owner's Mac | vnstock key and launchd job live there |

## 1. API on Fly.io

```sh
brew install flyctl
fly auth login                       # or: fly auth signup (a card is required)
fly launch --no-deploy --copy-config --name <your-app-name> --region sin
```

Answer **No** to the offers of Postgres, Redis or Tigris: the API uses Neon and S3.

Set the secrets from `.env` and create the token that only the site will know:

```sh
scripts/fly-secrets.sh        # prints the new API_TOKEN once: save it, Vercel needs it
fly deploy
```

The script reads `.env` as text and pipes the values to `fly secrets import`. Do not `source .env`: `DATABASE_URL`
contains `&`, which the shell would treat as "run in the background". To keep an existing token, run
`API_TOKEN=<token> scripts/fly-secrets.sh`.

The API only reads from S3 (approved card pictures). A separate IAM key limited to `s3:GetObject` on the bucket is
safer than reusing the pipeline's key.

Check it:

```sh
curl https://<your-app-name>.fly.dev/health                                   # {"status":"ok"}
curl -o /dev/null -w "%{http_code}\n" https://<your-app-name>.fly.dev/vncma/latest   # 401 without the token
curl -H "X-Soivi-Token: <token>" https://<your-app-name>.fly.dev/vncma/latest | head -c 200
```

Logs: `fly logs`. Status: `fly status`. Fly has no hard spending cap; set a billing alert in the dashboard.

## 2. Site on Vercel

New project → import the repository, then:

- **Root Directory:** `web`, framework Next.js.
- **Include files outside the Root Directory:** on. The build copies `docs/methodology.md`.
- **Environment variables** (Production and Preview):

| Name | Value |
|---|---|
| `SOIVI_API_URL` | `https://<your-app-name>.fly.dev` |
| `SOIVI_API_TOKEN` | the same token as `API_TOKEN` on Fly |
| `SITE_URL` | the site's address, e.g. `https://soivi.vercel.app` or your domain |
| `REVALIDATE_SECRET` | another random string (`openssl rand -hex 32`) |

Optional build tuning, if the build times out against the API: `SOIVI_BUILD_CONCURRENCY` (default 4),
`SOIVI_BUILD_CPUS` (2) and `SOIVI_BUILD_RETRIES` (2).

## 3. Refresh after approvals

In the Mac's `.env`:

```
SITE_REVALIDATE_URL=https://<site address>/api/revalidate
SITE_REVALIDATE_SECRET=<the same value as REVALIDATE_SECRET on Vercel>
```

Then restart the review app (`make review`). Every approval now rebuilds the affected pages on Vercel. The hourly
refresh catches everything else.

## Updating

- API code: `fly deploy`.
- Site: push to the branch Vercel watches. Vercel builds it.
- Database migrations: still run from the Mac (`make migrate`, cloud mode) before deploying code that needs them.
