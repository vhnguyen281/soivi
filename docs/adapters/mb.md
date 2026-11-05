# MB (Military Bank) — savings rates

| | |
|---|---|
| Adapter | `mb_savings` ([pipeline/adapters/mb.py](../../pipeline/adapters/mb.py)) |
| Source URL | https://www.mbbank.com.vn/fee |
| Format | HTML, rendered by JavaScript |
| Fetch method | `browser` (headless Chromium) |
| Fixture | `tests/fixtures/mb/savings_2026-10-26.html` (rendered DOM) |
| Checked | 2026-10-26 (rates "có hiệu lực từ ngày 21-10-2026") |

## How the page publishes rates

`/fee` is a single-page app. After loading it calls `/forgery/UpdateAntiForgeryToken/…` to get a `__RequestVerificationToken`, then `/api/GetlistFee`. That returns JSON whose item "Lãi suất huy động MB" holds the rate tables as an HTML string (`fulltext`). A direct GET of `/api/GetlistFee` returns **403** without the token and cookie.

We **don't work around the token.** Scripting the token handshake would mean getting past a protection the bank put there. Instead the adapter renders the public page in headless Chromium, the way a visitor's browser would, and parses the resulting HTML. robots.txt allows `/fee`. One render loads the page's normal sub-requests; the per-host rate limit counts the navigation. (During seeding the site also returned 403 to plain requests from this Mac; renders from Docker work.)

## Tables used (out of ~42 on the page)

| Section | Caption | region | product_name | channel |
|---|---|---|---|---|
| I.1 | "Lãi suất tiết kiệm khách hàng cá nhân bằng đồng Việt Nam tại MB" (no region label) | `north` | Tiết kiệm khách hàng cá nhân | counter |
| II.1 | same, under "(áp dụng: các chi nhánh thuộc miền Trung và miền Nam)" | `central_south` | Tiết kiệm khách hàng cá nhân | counter |
| IV.1 | "Lãi suất sản phẩm Tiền gửi số truyền thống (áp dụng: Khách hàng Mass)" | `''` | Tiền gửi số truyền thống | app |

**Regions.** Section II applies to Central and South branches; section I carries no label, so it covers the rest, i.e. the North. We label it `north`. **This is an inference from the page structure; confirm with MB.** The two differ by 0.10%/năm on short terms (2026-10-21 sheet) and are equal from 12 months.

Each table has 6 rate columns: **amount tier × interest payment**:

| | Số tiền dưới 1 tỷ VND | | | Số tiền từ trên 1 tỷ VND | | |
|---|---|---|---|---|---|---|
| | Lãi trả sau | Lãi trả trước | Lãi trả hàng tháng | Lãi trả sau | Lãi trả trước | Lãi trả hàng tháng |
| stored as | `end`, 0 | `upfront`, 0 | `monthly`, 0 | `end`, 1 tỷ | `upfront`, 1 tỷ | `monthly`, 1 tỷ |

"Từ trên 1 tỷ" means *more than* 1 tỷ. We store `min_amount_vnd = 1 000 000 000` and keep "Số tiền trên 1 tỷ VND" in `conditions_text`. Empty cells (KKH and weekly terms have no up-front or monthly option; 1–2 months have no monthly option) are skipped. MB is the first bank where the interest payment method is stated, not assumed.

## Skipped (for now)

Foreign-currency tables, corporate deposits (III), Priority/Private digital deposits (IV.2), "Tiết kiệm đặc quyền" (V), "Tích lũy thông minh" (VI), "Tiền gửi số tích lũy" (VII), "Tiết kiệm cho con" (VIII), and the loan reference rates further down the page.

## Quirks

- **The HTML mixes composed and decomposed Vietnamese accents** and splits header text across `<strong>`/`<br>`. `clean()` handles it; tests normalise to NFC before editing raw HTML.
- **Terms are written "01 tuần", "01 tháng"** (zero-padded). KKH = demand.
- **Rates are written "5.70%"** (dot decimal).
- **The effective date is in the sentence before section I:** "Biểu lãi suất huy động vốn có hiệu lực từ ngày 21-10-2026".

## When it raises `AdapterBroken`

- not exactly one North savings table, one Central/South table and one Mass digital table (e.g. the region label or caption wording changes, or the page is blocked);
- the effective-date sentence is missing;
- the amount or payment header rows change;
- a row doesn't have 7 cells, a term or rate can't be parsed, or a term repeats;
- a core term (1, 3, 6, 12, 24 months) is missing from any table.
