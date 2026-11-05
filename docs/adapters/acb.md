# ACB — savings rates

| | |
|---|---|
| Adapter | `acb_savings` ([pipeline/adapters/acb.py](../../pipeline/adapters/acb.py)) |
| Source URL | https://acb.com.vn/lai-suat-tien-gui |
| Format | Static HTML tables (Next.js, server-rendered) |
| Fetch method | `http` |
| Fixture | `tests/fixtures/acb/savings_2026-10-26.html` |
| Checked | 2026-10-26 |

## Tables on the page

| # | Heading | Used |
|---|---|---|
| I | Tiền gửi không kỳ hạn (VND/USD, AUD) | no (demand rate 0,01%; could be added) |
| II.1 | **Lãi suất tiền gửi**: counter, term deposits | yes |
| II.2 | Lãi suất thưởng bậc thang (amount bonus) | as a note, see below |
| II.3 | **Tiền gửi Online** (LCK), **Online kỳ hạn tùy chọn** (LCK), **Online lãi trả trước** | yes |

### II.1: counter table

Multi-row header with `rowspan`/`colspan`: columns are `Kỳ hạn | USD | VND × 8`. The VND part is split by product and payment:

| Product (page) | Payment columns | Stored product_name |
|---|---|---|
| TK Truyền Thống/ Tiền Gửi Có Kỳ Hạn | Lãi cuối kỳ, Lãi quý, Lãi tháng, Lãi trả trước | Tiết kiệm Truyền Thống/Tiền gửi có kỳ hạn |
| TK Phúc An Lộc | Lãi cuối kỳ, Lãi quý, Lãi tháng | Tiết kiệm Phúc An Lộc |
| Tích Lũy Tương Lai | (one column) | not stored (accumulation product) |

**Rate cells use `rowspan`:** e.g. the 4,00% end-of-term rate spans 1T–6T. The table extractor expands rowspans; without that, values shift into the wrong columns. This is why `extract_tables` now handles `rowspan` (and doesn't let it cross `<thead>`/`<tbody>`).

**Footnotes:** "4,90\*" and "4,75\*\*" (13 months) point to notes under the table: "(\*) Đối với mức gửi từ 200 tỷ (bậc 2): Lãi suất 6,50 %/năm (LCK)" and "(\*\*) … 6,25%/năm (LT)". These become **extra records with `min_amount_vnd` = 200 000 000 000**. If a marker's note can't be found, the adapter raises.

### II.2: amount bonus

"Lãi suất thưởng bậc thang" adds +0,10 (200 triệu–<1 tỷ), +0,15 (1–<5 tỷ), +0,20 (≥5 tỷ) to **1–12-month VND term deposits, except accumulation**. We don't compute base + bonus, since the bank doesn't print the result, and the page also says rates under 6 months must respect the 4,75% legal ceiling. Instead every counter record for 1–12 months carries the bonus rule in `conditions_text`. **Open question:** whether the bonus also applies to online deposits; the page doesn't say, so online records don't carry the note.

### II.3: online tables

Rows are **amount tiers** (in triệu VND) and columns are terms. They map to `min_amount_vnd`: `< 200` → 0, `200 – < 1.000` → 200 triệu, `1.000 - < 5.000` → 1 tỷ, `>= 5.000` → 5 tỷ.

- "Tiền gửi Online (LCK)": `end`. "Tiền gửi Online Lãi trả trước": `upfront`. Both are stored as product "Tiền gửi Online".
- "Tiền gửi Online kỳ hạn tùy chọn (LCK)" uses term **bands** ("3T – < 6T"). Each is stored at the lower bound, with the band in `conditions_text` when it covers more than one month. The **"Renew"** column (rollover rate 0,01%) is skipped.

## Other rules applied

- **"Mức gửi tối thiểu … kỳ hạn tuần/ tiết kiệm có kỳ hạn lãnh lãi trước là 10 triệu VND"**, so weekly and pay-up-front records get `min_amount_vnd` ≥ 10 000 000.
- **"1 - 3 tuần"** (one rate for 1–3 weeks) is stored at 7 days with a band note.
- **No effective date for deposit rates** is stated. The page's "Áp dụng từ ngày 01.10.2026" belongs to the lending base rate (LSCS), not deposits.
- **The HTML uses entities for some accents** (`Ph&uacute;c`). Parsing unescapes them; tests that edit raw HTML must use the entity form.
- **Channels:** II.1 → `counter`; II.3 → `online`.

## When it raises `AdapterBroken`

- the counter table (by its first header row) isn't found exactly once, or its product or payment header rows change;
- any of the three online tables isn't found exactly once, its shape changes, or an amount tier label is unknown;
- a counter row doesn't have 10 cells, or an online row has the wrong number of cells;
- a term, band or rate can't be parsed; a footnote marker has no matching note;
- core terms are missing (counter: 1, 3, 6, 12, 24, 36 months; online: 1, 6, 12);
- two cells map to the same product, term, tier and payment.
