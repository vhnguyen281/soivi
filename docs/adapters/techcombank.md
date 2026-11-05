# Techcombank — savings rates

| | |
|---|---|
| Adapter | `techcombank_savings` ([pipeline/adapters/techcombank.py](../../pipeline/adapters/techcombank.py)) |
| Source URL | `https://techcombank.com/graphql/execute.json/techcombank/viewDocumentList%3BcfPath%3D/content/dam/techcombank/master-data/vi/list-view-document/cong-cu-tien-ich/bieu-phi-lai-suat/khcn/` |
| Human page | https://techcombank.com/cong-cu-tien-ich/bieu-phi-lai-suat |
| Format | PDF, found through a JSON document listing (two steps) |
| Fetch method | `pdf` |
| Fixtures | `tests/fixtures/techcombank/document_list_2026-10-26.json`, `tests/fixtures/techcombank/savings_2026-10-26.pdf` |
| Checked | 2026-10-26 (PDF "Áp dụng từ ngày 24 tháng 10 năm 2026") |

## How the page publishes rates

The fee and rate page is Adobe Experience Manager. It lists documents by calling a persisted GraphQL query (`viewDocumentList`) for `khcn` (personal) and `khdn` (business). Each item has a `categoryTitle` and a `documentPath._publishUrl`. The savings rates are a **PDF whose file name contains the date** (`tcb-bieu-lai-suat-tien-gui-tiet-kiem-tien-gui-co-ky-han-20261024.pdf`), so the URL changes with every new rate sheet.

The adapter therefore works in two steps:

1. `resolve_url()` fetches the listing (politely, through the shared client) and takes the single item titled **"Lãi suất tiền gửi tiết kiệm/Tiền gửi có kỳ hạn"**.
2. `fetch()` downloads that PDF. The snapshot stores the PDF and its URL, which is the evidence.

There is a second savings document, "Lãi suất tiền gửi tiết kiệm Thường". We don't use it.

From this Mac, TLS connections to techcombank.com time out intermittently; from the Docker container they work. Run this adapter in Docker.

## PDF layout (3 pages)

Title "BIỂU LÃI SUẤT TIỀN GỬI DÀNH CHO KHÁCH HÀNG CÁ NHÂN", then "Áp dụng từ ngày 24 tháng 10 năm 2026", which becomes `effective_from`. Section **I** is VND, section **II** foreign currency.

Each VND table has 12 rate columns: **4 customer segments × 3 amount tiers**:

```
             PRIVATE          PRIORITY         INSPIRE          KH THƯỜNG / NORMAL CUSTOMER
           ≥3B 1-3B <1B     ≥3B 1-3B <1B     ≥3B 1-3B <1B     ≥3B   1-3B   <1B
12M        6.10 6.00 6.00   6.00 5.90 5.90   5.85 5.75 5.75   5.85  5.75   5.75
```

## What we store

- **Only the KH THƯỜNG (normal customer) columns.** Private, Priority and Inspire are wealth-client segments; our schema has no segment field, and a public comparison should show what an ordinary customer gets.
- **Amount tiers become `min_amount_vnd`:** `<1B` → 0, `1 - 3B` → 1 000 000 000, `≥3B` → 3 000 000 000. So there are 3 records per term.
- **Tables parsed:**

  | PDF heading | product_name | channel |
  |---|---|---|
  | TIẾT KIỆM PHÁT LỘC TẠI QUẦY | Tiết kiệm Phát Lộc | counter |
  | TIỀN GỬI PHÁT LỘC ONLINE | Tiền gửi Phát Lộc Online | online |
  | TIỀN GỬI RÚT GỐC LINH HOẠT TẠI QUẦY | Tiền gửi Rút gốc linh hoạt | counter |
  | TIỀN GỬI RÚT GỐC LINH HOẠT ONLINE | Tiền gửi Rút gốc linh hoạt Online | online |

- **`1-3W`** (one rate for 1–3 weeks) is stored at 7 days with `conditions_text` "Áp dụng cho kỳ hạn 1-3 tuần".
- **`KKH`** rows with no rate (in the flexible tables) are skipped.

## Not parsed yet (follow-ups)

- **CCTG Bảo Lộc** (certificate of deposit). Its rates depend on a holding period and "Series base / Volume base". It needs its own model; it's relevant to Phase 1 CDs.
- **TIỀN GỬI ONLINE** (Online Savings, KH THƯỜNG). Page 1 is two columns, and text extraction interleaves this table with the CD, Tài Tâm/Tài Hiền and Superkid tables. Parsing it needs cropping the page by coordinates.
- **Tài Tâm/Tài Hiền** (insurance-linked), **Superkid**, and **Như Ý** (listed vs adjusted rate depending on top-up timing): special products, skipped.
- **Foreign currency (section II)** is skipped; we store VND only.

## Quirks

- **Product headings repeat in section II** ("TIẾT KIỆM PHÁT LỘC TẠI QUẦY" for USD/EUR), so parsing is limited to the text between the section I and section II headings.
- **Rates are `6.10` (dot decimal) in a text layer.** pdfplumber's `extract_tables()` merges cells badly here, so we parse text lines with a strict regex instead.
- **The PDF note says** some customers may get different rates and the table is indicative. Interest payment method isn't stated per table; we record `end` (**assumption to confirm**).

## When it raises `AdapterBroken`

- listing: unexpected JSON shape, zero or several items with the savings title, or a URL that isn't a techcombank.com PDF;
- PDF: not a PDF or unreadable; title or effective date missing; section I/II headings missing;
- a product heading found 0 or 2+ times; the 4×3 tier header row changes; no rate rows; a term appears twice; a row without 12 rates;
- a core term (1M, 6M, 12M, 36M) is missing from any of the four tables.

---

# Credit cards (`techcombank_card_tariff`, `techcombank_card_products`)

Both are read with the LLM through the card pipeline (`pipeline/cards/`, see [docs/cards.md](../cards.md)). The card list is in `pipeline/adapters/techcombank_cards.py` (`TECHCOMBANK_CARDS`).

| Source | URL | Gives |
|---|---|---|
| `card_tariff_pdf` | `.../techcombank-bieu-phi-dich-vu-the-tin-dung-cho-khach-hang-thuong.pdf` (8 pages, text layer) | `card_terms`: annual fee, FX fee, cash advance (% and minimum), late fee (% and minimum), annual-fee waiver spend |
| `card_product_page` (12 sources, `techcombank_card_pages`) | each card's own page, e.g. `.../the-tin-dung/techcombank-visa-signature`; `variant` names the page (`TECHCOMBANK_CARD_PAGES`) | `card_reward`, `card_perk` |
| ~~card list~~ | `https://techcombank.com/khach-hang-ca-nhan/chi-tieu/the/the-tin-dung`: no longer monitored since 2026-10-30 | headlines only |

Fixtures saved on 2026-10-28: `tests/fixtures/techcombank/card_tariff_2026-10-28.pdf` and `card_products_2026-10-28.html`, plus mocked API answers (`card_*_llm_answers.json`) that quote them.

## Cards

- **Network:** all are Visa. Spark, Everyday and Style don't say "Visa" in their names. We confirmed it on their own pages (Everyday: "Thẻ Techcombank Visa Everyday"; Spark: images named `visa-spark`) and in the tariff (Style is grouped with "Thẻ tín dụng Visa khác").
- **DreamCard** is in the tariff, but neither the tariff nor the site states its network. It stays unpublished (`network=None`) until someone confirms it.
- **Priority Visa Signature, Visa Infinite and Techcom Wealth Visa Infinite Private** are on the product page only. Their fees are in other tariffs (Priority / private customers), which we don't read yet.
- **Techcombank Style** is marked "Ngưng phát hành" (no longer issued). It's still in the tariff, so existing cardholders' terms are kept.

## What the documents don't give

- **Interest rate and interest-free days** are in neither document's structured part. The product page says "Miễn lãi tới 45 ngày" for one card, but the product page doesn't write `card_terms`, to keep the two sources from overwriting each other's rows. These need the card terms and conditions as a third source.
- **Points rewards ("Tích điểm tới 8%")** are stated as a percentage of spend in points. `card_reward` stores points as points per spend unit, so these can't be stored. They are dropped, with a note on the review task.
- **Cashback on the product page is marketing wording** ("Hoàn tiền lên tới 5 triệu/tháng, tới 10%"). It's stored as 10% with a 5,000,000 VND monthly cap, and the full sentence goes in `conditions_text`.

## When it raises `AdapterBroken`

- The document names a credit card that isn't in `TECHCOMBANK_CARDS`. Add it to the catalogue, with its network.
- (Tariff) A card the catalogue expects in the tariff (`in_tariff`) has no verified annual fee.
- Nothing could be verified, or the document can't be read.

## Card pages (since 2026-10-30)

The list page gave only headlines ("Hoàn tiền lên tới 5 triệu/tháng, tới 10%"), which were stored as 10% on dining and travel capped at 5,000,000. Each card's page gives the real terms, for Visa Signature:
- 10% at partner restaurants (a merchant list: perks text);
- 5% at other restaurants and 3% on travel/hotels, up to 2 million cashback points a month ("điểm hoàn tiền", paid out as cash);
- U-Point bonuses from 50 or 100 million a month of spend (tiered: perks text).

The 5 million in the headline is the combined maximum including those tiers.

**Other cards:**
- Priority Visa Signature: the same shape with a 3,000,000 cap.
- Visa Infinite: 5% on dining, capped at 5,000,000. Its page title is "Techcombank Private Visa Infinite", the same card as the list's "Techcombank Visa Infinite".
- Spark, Everyday and Visa Classic: points per 1,000 VND.
- Vietnam Airlines cards: "25,000 VND = 1 dặm" miles rates, which the checker can't read yet. Miles count as 0 in the ranking anyway.
