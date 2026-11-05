# web/ — the public site

Next.js 16 (App Router, TypeScript, Tailwind 4). Vietnamese at the root, English under `/en`. Every page is prerendered from the Soivi API and rebuilt when a reviewer approves a change.

> Next.js 16 differs from older versions; this project follows the docs bundled in `node_modules/next/dist/docs/`. Read them before changing caching or routing.

## Run

```bash
make web                     # Docker: waits for the API, builds every page, serves on :3000
cd web && npm run dev        # local dev; SOIVI_API_URL defaults to http://127.0.0.1:8002
make web-test                # unit tests (node --test), types, lint
```

For UI work with data, use the fictional demo database (no real bank appears in it):

```bash
PYTHONPATH=. uv run python scripts/demo_db.py
DATABASE_URL=…/soivi_demo API_PORT=8012 uv run python -m api
cd web && SOIVI_API_URL=http://127.0.0.1:8012 npm run build && npm start
```

## How pages stay current

- Every API read in `lib/api.ts` is a `"use cache"` function tagged `soivi`, with a custom `cacheLife` profile (`next.config.ts`): refreshed hourly, last good copy kept for 30 days if the API is down.
- After an approval, the review app calls `POST /api/revalidate` with `X-Soivi-Secret` (`review_app/webhook.py`). That expires the tag (`revalidateTag("soivi", { expire: 0 })`), so each page is rebuilt with the new values on its next visit.
- The site sends `Cache-Control: no-cache` to the API, so it skips the API's own one-minute cache.
- The hourly refresh catches changes that aren't approvals, such as a bank's source going stale, which shows the "Chưa xác minh" badge.

## Routing

`proxy.ts` rewrites `/x` to `app/[lang=vi]/x` and leaves `/en/x` as is. `/vi/x` redirects to `/x`, so each page has one URL. The language toggle is a plain link, because the two languages are separate root layouts.

| Path | Page |
|---|---|
| `/` | Best rates by term (ranked on 100 million VND), latest rate moves, card finder entry |
| `/lai-suat-tiet-kiem` | Sortable, filterable table of every approved rate, with the calculator |
| `/lai-suat-tiet-kiem/[bank]` | Rate history chart (SVG step line, with a data table) and the bank's rates |
| `/the-tin-dung` | Card finder: presets ranked at build time, custom profile through `/api/cards/rank` |
| `/the-tin-dung/[card]` | Every fee with its exact quote and a link to the PDF page |
| `/bien-dong-lai-suat` | Approved changes by ISO week (Vietnam time), with a summary line per week |
| `/phuong-phap` | Rendered from `docs/methodology.md` (copied to `content/` at build) |
| `/doc-lap` | Editorial independence: who pays us (nobody) |

Calculations stay in the API (`core/scoring`): the calculator and the custom card profile call it through same-origin route handlers, so the formula lives in one place. `/api/reports` forwards reports with the visitor's IP for the rate limit.

## Quality bar (measured 2026-10-29 with Lighthouse 12.6, mobile, on the demo data)

Every page: performance 98–99, accessibility 100, SEO 100, best practices 100; LCP 2.1 s, CLS 0, TBT ≤ 100 ms. What keeps it there:

- **No web fonts:** system fonts render Vietnamese. The one TTF in `assets/fonts` (Be Vietnam Pro, OFL) is used only for Open Graph images.
- **Little JavaScript:** server-rendered tables and charts, and client code only for sorting and filters, the calculator, the finder and the report dialog. The report form is added to the page only when opened.
- **Pages render in one pass:** content isn't wrapped in `<Suspense>`. Streaming moved it after the footer and caused layout shift.
- **Accessible tables:** `<caption>`, `scope`, `aria-sort` on sortable headers, and scrollable regions with labels. Links are underlined; focus is visible.

## SEO

Each page has a canonical URL, hreflang vi/en/x-default, Open Graph and Twitter tags, and JSON-LD:
- WebSite and Organization on the home page;
- BreadcrumbList on every page;
- DepositAccount items, BankOrCreditUnion, CreditCard, Dataset and TechArticle on their pages.

`sitemap.xml` lists every page in both languages, and `robots.txt` blocks `/api/`. Not-found pages carry `noindex`. Unknown bank and card URLs answer 200 with the not-found page, because Next serves params that weren't prerendered that way.
