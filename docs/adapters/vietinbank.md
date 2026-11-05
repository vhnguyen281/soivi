# VietinBank — savings rates

| | |
|---|---|
| Adapter | `vietinbank_savings` ([pipeline/adapters/vietinbank.py](../../pipeline/adapters/vietinbank.py)) |
| Source URL | https://www.vietinbank.vn/ca-nhan/cong-cu-tien-ich/lai-suat-khcn |
| Format | Static HTML table (Next.js server-rendered) |
| Fetch method | `http` |
| Fixture | `tests/fixtures/vietinbank/savings_2026-10-26.html` |
| Checked | 2026-10-26 |

## How the page publishes rates

The page is server-rendered by Next.js, so the rate table is in the HTML; no JavaScript or API is needed. The table follows the heading **"LÃI SUẤT HUY ĐỘNG ĐỐI VỚI CÁC KỲ HẠN"** and has the columns `Kỳ hạn | VND (%/năm) | USD (%/năm) | EUR (%/năm)`. A second table on the page ("Thông báo") lists announcements and is ignored.

## Quirks

- **Every row is rendered twice,** in groups: the rows for 1–2 months, then the same rows again, and so on. Probably a rendering bug. We keep one copy and **raise if two copies of a band disagree**.
- **Terms are bands, not single terms:** "Từ 1 tháng đến dưới 2 tháng", "Trên 12 tháng đến 13 tháng", "Trên 13 tháng đến dưới 18 tháng", "Từ 24 tháng đến dưới 36 tháng". Each band is stored as its **shortest whole-month term**, and multi-month bands keep the bank's wording in `conditions_text`:

  | Band on the page | Stored `term_months` | `conditions_text` |
  |---|---|---|
  | Từ 1 tháng đến dưới 2 tháng | 1 | — |
  | 12 tháng | 12 | — |
  | Trên 12 tháng đến 13 tháng | 13 | — |
  | Trên 13 tháng đến dưới 18 tháng | 14 | Áp dụng cho kỳ hạn: Trên 13 tháng đến dưới 18 tháng |
  | Từ 18 tháng đến dưới 24 tháng | 18 | Áp dụng cho kỳ hạn: … |
  | Từ 24 tháng đến dưới 36 tháng | 24 | Áp dụng cho kỳ hạn: … |

- **Two bands are skipped on purpose:** "Dưới 1 tháng" (0.2%) and "Trên 36 tháng" (5.5%). Neither has a single term to file the rate under. Revisit if the site needs "any term over 36 months".
- **Rates are written "5,4 %"** (comma decimal, space, separated by HTML comments `<!-- -->`).
- **The HTML mixes composed and decomposed Vietnamese accents** and uses non-breaking spaces inside labels. `clean()` normalises both, but tests that edit the raw HTML must normalise first.
- **No product name, channel or interest method is shown next to the table.** The calculator below it says "sản phẩm tiền gửi thông thường trả lãi sau", so: product "Tiền gửi thông thường", interest paid at the end (`end`), channel `counter` (the bank's listed rates; online rates aren't on this page).
- **The note says rates are indicative and may vary by area** ("có thể thay đổi tùy từng địa bàn"). No effective date is stated.

## When it raises `AdapterBroken`

- the heading or table is gone, or there is more than one;
- the header row changes, or a row doesn't have 4 cells;
- two copies of a band disagree;
- a band or rate can't be parsed, or a band is empty;
- a core term (KKH, 1, 3, 6, 12, 24 months) is missing, or two bands map to the same term.
