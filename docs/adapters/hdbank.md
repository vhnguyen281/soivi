# HDBank — savings rates

| | |
|---|---|
| Adapter | `hdbank_savings` ([pipeline/adapters/hdbank.py](../../pipeline/adapters/hdbank.py)) |
| Source URL | https://hdbank.com.vn/vi/personal/cong-cu/interest-rate |
| Format | PDF (text layer), found on a JavaScript-rendered listing |
| Fetch method | `pdf` (the listing is rendered with the browser fetcher in `resolve_url()`) |
| Fixtures | `tests/fixtures/hdbank/savings_2026-10-26.html` (rendered listing), `tests/fixtures/hdbank/savings_2026-10-26.pdf` |
| Checked | 2026-10-26 (listing label "BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN 19-10-2026") |

## How the page publishes rates

The rate page is a Next.js app. Its data endpoints (`/api/vi/personal/interest-rates`, …) return **encrypted** payloads that the page's JavaScript decrypts. We **don't decrypt them**: pulling a key out of the bank's code would be getting around a deliberate protection. Instead `resolve_url()` renders the public page in headless Chromium, as a visitor's browser does. That gives a list of document links:

```
BIỂU LÃI SUẤT CƠ SỞ CHO VAY KHCN 14-10-2026
LÃI SUẤT CHO VAY BÌNH QUÂN KHÁCH HÀNG 01-07-2026
BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN 10-04-2026
BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN 19-10-2026   ← newest, used
```

The adapter takes the "BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN dd-mm-yyyy" link with the **latest date in its label**, and requires it to be a PDF on `cdn.hdbank.com.vn`. File names can't be trusted for dates: the 19-10-2026 file is named `20261910…` (day and month swapped).

## PDF layout (6 pages, text layer, "-" for "not offered")

"BIỂU LÃI SUẤT HUY ĐỘNG VỐN DÀNH CHO KHÁCH HÀNG CÁ NHÂN" / "Biểu lãi suất áp dụng trên toàn hệ thống (%/năm)", so `region = ''`.

Every row writes `-` in columns that don't apply, so values keep their positions and text lines are safe to parse. The adapter requires each row to have exactly the expected number of values.

| Section | Stored as | Columns (in order) |
|---|---|---|
| 1a Tiết kiệm có kỳ hạn thông thường | product "Tiết kiệm có kỳ hạn thông thường", counter | cuối kỳ, trả lãi trước, hàng tháng, hàng quý, *hàng 06 tháng*, *hàng năm*, *USD*, *EUR*, *AUD*, *GBP* |
| 2c Tiết kiệm Online VNĐ | "Tiết kiệm Online", online | cuối kỳ, trả lãi trước, hàng tháng, hàng quý |
| 3 Tiền gửi có kỳ hạn | "Tiền gửi có kỳ hạn", counter | cuối kỳ, hàng tháng, hàng quý, *hàng 06 tháng* |
| 4 Lãi suất chứng chỉ tiền gửi | "Chứng chỉ tiền gửi", counter, **`is_cd = true`** | one rate (stored as `end`, an **assumption**: the PDF gives no payment method for CDs) |

*Italic* columns are read but not stored: our `interest_payment` has no semiannual or annual value yet (**follow-up: add `semiannual` / `annual`**), and we store VND only.

## Quirks

- **12 and 13 months have two rows:** "LS12 loại 1 7,20" and "loại 2 5,20 …". The footnotes say *loại 1* is for "khoản tiết kiệm tối thiểu từ 500 tỷ đồng trở lên", end-of-term only. Loại 1 is stored with `min_amount_vnd` = 500 000 000 000 and the rule in `conditions_text`; loại 2 is the standard tier (0). If the footnotes change, the adapter raises.
- **Terms include "01 ngày"** (`term_days` = 1), "01–03 tuần" (7/14/21) and "TK KKH" (demand, section 3).
- **No effective date in the PDF.** Only the listing label carries "19-10-2026", so `effective_from` stays empty.
- **Skipped sections:** không kỳ hạn (1b), Bảo ngân tương lai (1c/2a), Gửi góp linh hoạt (1d/2b), Tiết kiệm Linh hoạt (1e), **Online Vikki (2d)** (Vikki Bank is a separate institution in our data), payment accounts (5).

## When it raises `AdapterBroken`

- listing: no matching link, two links with the same newest date, or a link that isn't an HDBank CDN PDF;
- PDF: not a PDF or unreadable; title or "áp dụng trên toàn hệ thống" missing; a section heading missing or out of order;
- a row with the wrong number of values; a term repeated; a "loại 1" row without its footnote; LS12/LS13 footnotes changed;
- a core term (1, 3, 6, 12, 24, 36 months) missing from any section.
