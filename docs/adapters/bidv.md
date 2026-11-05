# BIDV — savings rates

| | Counter | Online |
|---|---|---|
| Adapter | `bidv_savings_counter` | `bidv_savings_online` |
| Source URL | `https://bidv.com.vn/ServicesBIDV/InterestDetailServlet` | `https://bidv.com.vn/ServicesLaiSuatOnline/InterestDetailOnlineServlet` |
| Source variant | (empty) | `online` |
| Human page | https://bidv.com.vn/vn/tra-cuu-lai-suat | https://bidv.com.vn/vn/tra-cuu-lai-suat-online |
| Fixture | `tests/fixtures/bidv/savings_2026-10-26.json` | `tests/fixtures/bidv/savings_online_2026-10-26.json` |

Code: [pipeline/adapters/bidv.py](../../pipeline/adapters/bidv.py). Checked 2026-10-26.

## How the pages publish rates

Both pages are IBM WebSphere Portal pages with an AngularJS controller (`BidvJSApp`). On load the controller sends an **empty form POST** (`Content-Type: application/x-www-form-urlencoded`) to a servlet and renders the JSON it gets back. A GET doesn't work, so both adapters set `http_method = "POST"`. No browser is needed. robots.txt allows both servlet paths.

The online page is a separate source of the same kind. That's why `source.variant` exists: a bank can have several savings sources, e.g. `''` for counter and `online`.

## Response shape

```json
{"status": 1,
 "hanoi": {"visible": [{"currency": "VND", "enable": "0"}, ...], "day_vi": "21/10/2026", "hour": "00:00",
           "data": [{"title_vi": "1 Tháng", "title_en": "1 month", "VND": "2.1", "USD": "", ...}]},
 "hcm":   {...same shape...},
 "note_vi": "L%E3i%20su%u1EA5t...", "note_en": "..."}
```

## Quirks

- **Two regions.** The page has a "Chọn khu vực" picker (Hà Nội / Hồ Chí Minh), and the note says rates "có thể thay đổi tùy từng địa bàn". When the two tables are identical (as on 2026-10-26) they are stored once with `region = ''` (nationwide); when they differ, each is stored with `region = hanoi` or `hcm`.
- **Rates are percent strings** (`"2.1"`, `"4.75"`), not fractions. An empty string means the term isn't offered in that currency.
- **`visible[].enable == "0"` means the currency column is shown** (inverted). We require VND to be shown.
- **The notes are JavaScript `escape()`-encoded** (`%u1EA5`); `js_unescape()` decodes them.
- **The online note** says rates are "áp dụng cho tiền gửi trả lãi cuối kỳ", with up-front and periodic payment converted from that. So `interest_payment = end` is stated for online. The counter note doesn't say; we assume the same convention (**to confirm**).
- **Online rows have `TG<currency>` columns,** shown as "+/- Ưu đãi lãi suất". They're empty today. If one is filled we can't tell whether `VND` already includes it, so the adapter raises.
- **`day_vi` / `hour` (e.g. 21/10/2026 11:30) are in the JSON but never shown on the page,** and might be edit times. They're not used as `effective_from`. A "hiệu lực từ ngày …" date in the note would be used.
- **Weekly terms** ("1 Tuần" … "3 Tuần") appear only online and map to `term_days` 7/14/21.
- **Product names** are ours ("Tiền gửi tại quầy", "Tiền gửi Online"), based on the page headings "Lãi suất tiền gửi (Online) dành cho khách hàng cá nhân". BIDV doesn't name a product.
- **Online rates are much higher** than counter rates (12 months: 6.8% vs 5.4% on 2026-10-26).

## When it raises `AdapterBroken`

- the body is not JSON, or `status` ≠ 1;
- a region block or its `data` / `visible` list is missing, or the VND column is hidden;

- a row lacks `title_vi` / `VND`, a term or rate can't be parsed, or `TGVND` is set;
- a core term is missing (counter: KKH, 1, 3, 6, 12, 24 months; online: 1, 3, 6, 12, 24 months).

---

# Credit cards (`bidv_card_tariff`)

| | |
|---|---|
| Adapter | `bidv_card_tariff` ([pipeline/adapters/bidv_cards.py](../../pipeline/adapters/bidv_cards.py)) |
| Source | BIDV's card fee schedule PDF (24 pages, "áp dụng từ 20/08/2026"); URL in `data/seeds/sources.csv` |
| Read | Section 1 only, "1. BIỂU PHÍ DỊCH VỤ THẺ TÍN DỤNG" up to "2. BIỂU PHÍ DỊCH VỤ THẺ GHI NỢ" (pages 1–6) |
| Fixtures | `tests/fixtures/bidv/card_tariff_2026-10-29.pdf`, `card_tariff_llm_answers.json` (real model answers) |
| Checked | 2026-10-29, every value checked by hand against the PDF |

## Layout

Cards are rows. The value columns are customer segments: "KHCN thông thường", "KH Premier/Premier Elite" and "KH Private". We publish only **KHCN thông thường** (a standard customer). The adapter's reading notes tell the model:
- "Thẻ chính X" rows give the primary card's annual fee, "Thẻ phụ X" the supplementary card's, and "Thẻ chính/phụ X" both. "Combo thẻ …" rows are not cards.
- Fee rows that name no card (e.g. "Phí chuyển đổi ngoại tệ", 1%) apply to every card listed above them.
- Cash advance uses the general row "Các trường hợp còn lại" (3.64%, min 50,000). The Visa Easy rate "tại POS/MGDTD BIDV" applies at BIDV's own machines only.
- "Thẻ khác" rows apply to every card not named above them.
- Fees are before VAT and are stored as written.

## Cards

19 in the catalogue, 18 published:
- **Current cards** get annual fees, late fee, cash advance and FX.
- **Visa Infinite** comes in three privilege packages (30, 15 and 5 million đồng), stored as three cards.
- **No longer issued:** six cards (Visa Premier, Mastercard Inspire, Visa Precious, Mastercard Vietravel Platinum/Standard, Visa Credit TPV). They appear only in the annex of discontinued cards. They get annual fees from the annex and the late fee from the "Thẻ khác" row; FX and cash advance stay empty.
- **Visa Platinum** is named in group rows but has no annual fee row.
- **Private Banking** is not published: the schedule doesn't write its network.

## What the document doesn't give

- **Interest:** the rates (12% / 18% / 20% / 22%) are printed without a period (per year? per month?), so `interest_rate_pct` is left empty. See DECISIONS 2026-10-29 "Credit cards: BIDV and VPBank".
- Rewards and perks come from the card pages (below).

## Card pages (`bidv_card_products`)

One source per card page (`card_product_page`, `variant` = page slug), 13 pages mapped to cards in `BIDV_CARD_PAGES`. The Visa Infinite page covers all three packages.
- **Promotions cut off:** each page ends with a list of the bank's card promotions; the text is cut at "Dịch vụ hỗ trợ 1900" (`html_until`). If the marker disappears the run raises.
- **Points, not cashback:** BIDV's "Chương trình tích lũy điểm thưởng" gives points as a percentage of spend ("Tích điểm lên tới 10% … tại siêu thị"). These can't be stored as points per spend unit, so they are left out, and those cards stay "not ranked: no reward data".
- **Interest:** the pages state it per year ("Lãi suất: 20%/năm, miễn lãi tối đa 45 ngày"). Product pages don't write `card_terms` yet; see DECISIONS.
- Fixture: `tests/fixtures/bidv/card_page_visa-cashback-360_2026-10-29.html`.
