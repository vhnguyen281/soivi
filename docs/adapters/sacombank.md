# Sacombank — savings rates

| | |
|---|---|
| Adapter | `sacombank_savings` ([pipeline/adapters/sacombank.py](../../pipeline/adapters/sacombank.py)) |
| Source URL | `https://www.sacombank.com.vn/content/dam/sacombank/files/cong-cu/lai-suat/tien-gui/khcn/SACOMBANK_LAISUATNIEMYETTAIQUAY_KHCN_VIE.pdf` |
| Human page | https://www.sacombank.com.vn/cong-cu/lai-suat.html |
| Format | PDF with a text layer and ruled tables |
| Fetch method | `pdf` |
| Fixture | `tests/fixtures/sacombank/savings_2026-10-26.pdf` |
| Checked | 2026-10-26 ("Hiệu lực từ 07h30 ngày 20.10.2026") |

Sacombank's legal name changed to Ngân hàng TMCP Sài Gòn Tài Lộc on 01/06/2026; the brand and short name stay "Sacombank".

## How the page publishes rates

`/cong-cu/lai-suat.html` (Adobe Experience Manager) has a small table: "Lãi suất huy động dành cho Khách hàng Cá nhân | Xem file | 20/10/2026". The "Xem file" link is a PDF whose **file name doesn't change** between versions (`SACOMBANK_LAISUATNIEMYETTAIQUAY_KHCN_VIE.pdf`), so we fetch it directly. Unchanged bytes are marked `unchanged` by the pipeline.

## PDF layout (4 pages)

Header: "LÃI SUẤT HUY ĐỘNG - KHÁCH HÀNG CÁ NHÂN", "**ÁP DỤNG CHO TẤT CẢ ĐỊA BÀN**", "Hiệu lực từ 07h30 ngày 20.10.2026".

- **A. ÁP DỤNG CHO TÀI KHOẢN MỞ TẠI QUẦY**
  - **I. Tiết kiệm có kỳ hạn truyền thống, VND** ← parsed (counter)
  - II. foreign currency, III. Phù Đổng, IV. Tích góp siêu linh hoạt, V. Phúc Lộc (bonus on top of I), VI–X products no longer sold
- **B. ÁP DỤNG CHO TÀI KHOẢN MỞ TRỰC TUYẾN**
  - **I. Tiền gửi có kỳ hạn trực tuyến, VND** ← parsed (online)
- Notes, payment accounts, KKH (0,1%)

The two parsed tables are ruled grids. We read them with pdfplumber's **line-based table extraction**, not text lines. Rows have 12 / 9 / 3 values depending on which payment options exist for that term, so text alone can't tell which column a value belongs to. The grid keeps empty cells in place.

| Table | Amount tiers → `min_amount_vnd` | Payment columns |
|---|---|---|
| Counter (A.I) | Dưới 500 triệu → 0; Từ 500 triệu đến dưới 2 tỷ → 500 000 000; Từ 2 tỷ → 2 000 000 000 | cuối kỳ (`end`), hàng quý (`quarterly`), hàng tháng (`monthly`), trả trước (`upfront`) |
| Online (B.I) | Dưới 50 triệu → 0; Từ 50 triệu đến dưới 500 triệu → 50 000 000; Từ 500 triệu → 500 000 000 | cuối kỳ, hàng quý, hàng tháng |

## Quirks

- **"Dưới 1 tháng"** (0,50%) is stored at 7 days with "Áp dụng cho kỳ hạn dưới 1 tháng". The notes say day-based terms start at 7 days.
- **Counter bands** "Từ 1 đến dưới 2 tháng" are one month wide, so they're stored as 1, 2, 3 months. A wider band would raise.
- **The effective date includes a time** ("07h30"), which the generic date finder doesn't expect, so the adapter has its own pattern.
- **Several notes and the second-page tables are typeset rotated or letter-spaced;** text extraction returns them as single letters. We don't parse them.
- **"ÁP DỤNG CHO TẤT CẢ ĐỊA BÀN"** means one national table, so `region = ''`. If that line disappears, the adapter raises, in case rates become regional.
- **Product names** follow the PDF headings: "Tiết kiệm có kỳ hạn truyền thống" and "Tiền gửi có kỳ hạn trực tuyến".

## When it raises `AdapterBroken`

- not a PDF, unreadable, or the title, the "tất cả địa bàn" line or the effective date is missing;
- a table isn't found exactly once (identified by its amount-tier header);
- the payment header changes, a row has the wrong number of cells, a term or rate can't be parsed, a band is wider than a month, or a term repeats;
- a core term (1, 3, 6, 12, 24, 36 months) is missing.
