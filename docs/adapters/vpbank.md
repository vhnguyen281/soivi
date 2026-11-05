# VPBank — savings rates (OCR)

| | |
|---|---|
| Adapter | `vpbank_savings` ([pipeline/adapters/vpbank.py](../../pipeline/adapters/vpbank.py)), OCR helpers in [pipeline/extract/ocr.py](../../pipeline/extract/ocr.py) |
| Source URL | `https://www.vpbank.com.vn/uiux-api/api/document?categoryPath=%2Ftai-lieu-bieu-mau%2Flai-suat-huy-dong%2Fkhach-hang-ca-nhan&pageIndex=1&pageSize=4&sort=publishTime%2CDESC&lang=vi` |
| Human page | https://www.vpbank.com.vn/tai-lieu-bieu-mau?category=%2Ftai-lieu-bieu-mau%2Flai-suat-huy-dong |
| Format | **Image-only PDF**: numbers are drawn as images; the grid is vector rectangles |
| Fetch method | `pdf` (listing via JSON API in `resolve_url()`) |
| Fixtures | `document_list_2026-10-26.json`, `savings_2026-10-26.pdf`, `savings_2026-10-26.ocr.json` (recorded OCR) |
| Checked | 2026-10-28 (PDF "Áp dụng từ ngày 24/10/2026") |

## How rates are published

The document library ("Tài liệu biểu mẫu → Lãi suất huy động → Khách hàng cá nhân") is filled from `/uiux-api/api/document`, sorted by `publishTime` (newest first). Using the parent category without the year (`…/khach-hang-ca-nhan`, not `…/2026`) returns the current sheet, so it doesn't break on 1 January. The newest item, "Biểu lãi suất huy động dành cho KHCN cập nhật từ ngày …", has one PDF in `itemList`, e.g. `/-/media/vpbank-latest/tai-lieu-bieu-mau/lai-suat-huy-dong/khcn/2026/2.-20261024-Phu-luc-BLS-niem-yet.pdf`.

The PDF (9 pages) has **no text layer**. Every word and number is a small image placed on the page, and the table borders are vector rectangles.

## How the OCR works, and why it's built this way

1. **Grid from vectors, not pixels.** `page.find_tables(lines)` finds the three ruled tables on page 1 from the vector rectangles, so cell positions are exact.
2. **Values from the images inside each cell.** Each image is assigned to a cell by its centre point, and we OCR **the image's own box (+2 pt)**, not the cell. The cell boundary can cut through a number: the 13T up-front cell crossed its column edge, and cropping by cell turned **5.99 into 5.95** with full OCR confidence. That's the bug this design prevents.
3. **Two reads must agree.** Every crop is rendered at 400 and 600 dpi, binarised (Otsu threshold, inverted for white-on-green headers), and read with Tesseract `--psm 7` and a whitelist (`0123456789.` for rates). If the two reads differ, the cell is treated as unreadable.
4. **Strict rules on the result** (`records_from_grids`, pure and tested on the recorded OCR):
   - every rate matches `d.dd` and lies in (0, 15);
   - every rate cell holds exactly one number image;
   - within each term column, rates never fall as the amount tier rises;
   - amount-tier labels must match their known OCR form exactly ("< 1 tỷ" → `<1` … "≥ 50 tỷ" → `250`: the "≥" reads as "2", identically every time);
   - term headers are a layout check: each must read as expected (`1T` … `36T`) or be unreadable, never a different term, and at least 15 of 17 must be confirmed. On 2026-10-24, "5T" is unreadable and "11T" reads as "T1T";
   - the effective date ("Áp dụng từ ngày dd/mm/yyyy") must be read identically twice.

   Any failure raises `AdapterBroken`, and every accepted change still goes through human review.

A full run takes about 1.5 minutes (≈ 450 crops × 2 reads). The test suite checks the rules against `savings_2026-10-26.ocr.json`. `make test-ocr` re-runs real OCR on the PDF and requires it to reproduce the recorded rates exactly; this passes on Tesseract 5.5.1 (macOS) and 5.3.0 (Docker).

## What is stored (page 1)

| Table | product_name | channel | payment | Amount tiers → `min_amount_vnd` |
|---|---|---|---|---|
| 1. Tại quầy | Tiết kiệm thường/Tiền gửi có kỳ hạn lĩnh lãi cuối kỳ | counter | `end` | <1 tỷ → 0; 1–<3 tỷ → 1 tỷ; 3–<10 tỷ → 3 tỷ; 10–<50 tỷ → 10 tỷ; ≥50 tỷ → 50 tỷ |
| 1. Kênh Online | same | online | `end` | same |
| 2. Trả lãi trước tại Quầy và Online | Tiết kiệm/Tiền gửi có kỳ hạn trả lãi trước | counter (the PDF uses one table for both channels) | `upfront` | <5 tỷ → 0; ≥5 tỷ → 5 tỷ |

Terms: 1T–13T, 15T, 18T, 24T, 36T. The **"1-3 tuần"** column is one merged cell for all tiers (0.40%), stored once at 7 days with tier 0 and "Áp dụng cho kỳ hạn 1-3 tuần". 206 records in total.

## Not parsed yet

Pages 2–9: other products (e.g. Thịnh Vượng Plus, CDs, foreign currency). Each needs its own grid spec. The same OCR pipeline applies.

## When it raises `AdapterBroken`

- listing: unexpected JSON, the newest document isn't a KHCN rate sheet, or it doesn't have exactly one PDF under the expected path;
- PDF: not a PDF or unreadable; no ruled tables; **real text inside a table** (the PDF was regenerated with a text layer, so it should be parsed as text instead);
- OCR rules: any check in the list above.

---

# Credit cards (`vpbank_card_tariff`)

| | |
|---|---|
| Adapter | `vpbank_card_tariff` ([pipeline/adapters/vpbank_cards.py](../../pipeline/adapters/vpbank_cards.py)) |
| Source URL | VPBank's document API, category `/tai-lieu-bieu-mau/bieu-phi/khach-hang-ca-nhan` (newest first) |
| Resolve | `resolve_url()` takes the newest document titled "Biểu phí thẻ tín dụng tại VPBank…" and its single PDF |
| Fixtures | `card_documents_2026-10-29.json` (listing), `card_tariff_2026-10-19.pdf` (6 pages), `card_tariff_llm_answers.json` |
| Checked | 2026-10-29, every value checked by hand against the PDF |

The old seed row pointed at an undated PDF from 2020. It was replaced by the document listing, so the adapter always reads the current schedule.

## Layout: cards are columns

Each page is a table whose columns are cards ("No.1", "MC2", "Lady, StepUp", …) under multi-line, letter-spaced headers. The PDF is read with **column labels** (`label_columns = True`): every cell is written as `[card names] value`, with the names read from the header above that column by position, e.g.

    2.2. Thẻ phụ | [No.1] Không thu phí | [MC2] 150.000 VND | [Lady] Không thu phí

The quote check then proves which card a value belongs to. Merged cells list every card they cover.

Reading notes for the model:
- "TT" means minimum and "TĐ" maximum.
- 2.1 is the primary annual fee, 2.2 the supplementary, and 2.1.2 the yearly spend that waives the next year's fee.
- VPBank Flex uses its credit column, not its debit one.
- Fees are before VAT.

## Cards

33 in the catalogue, **12 published**. A card is published only when VPBank writes its network, in the card's name or on its card page: MC2, Z (JCB), Platinum/Signature Travel Miles, YoJo, CommCredit, UnionPay FreeWays, GameON, MWG, S Rewards, Private Visa Infinite Privilege and Flex. The other 21 stay unpublished until their network is confirmed. They show up as `not_published` notes, not as errors.

## What the document doesn't give

- **Interest:** page 1 lists "3.99%" per card with no period, so `interest_rate_pct` is left empty.
- **Late fee:** it is 6% of the *minimum payment* (minimum 200,000). Techcombank and BIDV charge a percentage of the *overdue amount*, so the same field holds different bases; see DECISIONS.
- **Interest:** the card pages' FAQ settles it: "Lãi suất thẻ tín dụng VPBank Z là 3.99%/tháng", per month.
- Rewards and perks come from the card pages (below).

## Card pages (`vpbank_card_products`)

One source per card page (`variant` = page slug), 11 pages from the sitemap, mapped in `VPBANK_CARD_PAGES`. YoJo has no page.
- **The terms are page data:** the visible HTML has only headlines ("Hoàn tiền 15% cho mọi chi tiêu"). The tabs ("Tính năng nổi bật", "Lợi ích", FAQ) are shipped as Next.js data: `self.__next_f.push` chunks, with text blocks written as `<id>:T<hex length>,<html>`. The reader decodes them and appends them to the page text (`pipeline/cards/document.py`), so quotes from them are checked like any other.
- **Headlines aren't terms:** for Z the headline says 15% on all spending; the terms say 15% on dining, on entertainment/fitness and on ride-hailing/food delivery, each up to 500,000, and 1,000,000 per statement period in all.
- Fixture: `tests/fixtures/vpbank/card_page_z_2026-10-29.html`.

## When it raises `AdapterBroken`

- The listing isn't JSON with `data`.
- No document title starts with "Biểu phí thẻ tín dụng tại VPBank".
- The newest document doesn't have exactly one PDF under `/-/media/vpbank-latest/…`.
