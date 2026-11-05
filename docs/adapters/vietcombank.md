# Vietcombank — savings rates

| | |
|---|---|
| Adapter | `vietcombank_savings` ([pipeline/adapters/vietcombank.py](../../pipeline/adapters/vietcombank.py)) |
| Source URL | `https://www.vietcombank.com.vn/vi-VN/api/interestrates?accountType=Personal` |
| Human page | https://www.vietcombank.com.vn/vi-VN/KHCN/Cong-cu-Tien-ich/KHCN---Lai-suat |
| Format | JSON (the endpoint the page's own JavaScript calls) |
| Fetch method | `http` (no browser needed) |
| Fixture | `tests/fixtures/vietcombank/savings_2026-10-26.json` |
| Checked | 2026-10-26 |

## How the page publishes rates

The rate page is a Sitecore page whose table is filled in by JavaScript (`pre-optimized-min.js`). The table element has `data-properties='{"endpoint":"vi-VN/api/interestrates","accountType":"Personal"}'`, and the script:

1. reads JSON from a hidden `<input id="currentDataInterestRate">` embedded in the HTML; or, if that's empty,
2. calls `/vi-VN/api/interestrates?accountType=Personal`.

We fetch the endpoint directly: about 9.5 KB instead of about 290 KB of HTML, and the same data. robots.txt allows it. The date picker on the page calls the same endpoint with a date argument for past tables; we don't use that.

## Response shape

```json
{"Count": 90, "UpdatedDate": "2026-10-26T10:01:01+07:00", "AccountType": "Personal",
 "Data": [{"tenorType": "Savings", "tenor": "12-months", "currencyCode": "VND",
           "tenorDisplay": "12 tháng", "rates": 0.054}, ...]}
```

| `tenorType` | Tab on the page | Our `product_name` | `channel` |
|---|---|---|---|
| `Savings` | Tiết kiệm tại quầy | Tiết kiệm tại quầy | counter |
| `FixedDeposit` | Tiền gửi có kỳ hạn tại quầy | Tiền gửi có kỳ hạn tại quầy | counter |
| `Online` | Tiền gửi trực tuyến | Tiền gửi trực tuyến | online |

## Quirks

- **Rates are fractions, sent as JSON floats** (`0.054` = 5.4%/năm). Parsed with `parse_float=Decimal`, then × 100, so there's no float rounding.
- **Weekly terms are given in days** ("7 ngày", "14 ngày", tenor keys `7-days`, `14-days`). They map to `term_days`.
- **Demand deposit:** `tenor: "Demand"`, label "Không kỳ hạn", stored as 0/0. It appears only under `Savings`.
- **The tenor key and the Vietnamese label are both given.** We parse the label and require it to agree with the key; a mismatch raises.
- **USD and EUR rows are present but skipped** (all USD rates are 0 at the time of writing).
- **`UpdatedDate` moves forward every day** (same time, new date) even when no rate changes, so the snapshot bytes differ daily and the page is re-parsed each time. The diff then finds nothing new; that's expected, not a change.
- **`UpdatedDate` is when VCB last edited the table, not an effective date.** The page states no effective date, so `effective_from` is left empty. The snapshot's `fetched_at` is the capture time.
- **Interest payment method is not stated.** The listed rates are VCB's standard end-of-term (trả lãi cuối kỳ) rates, so we record `end`. **Assumption: confirm with VCB's product terms** before showing it as a fact.
- **No amount tiers:** one rate per term, so `min_amount_vnd` = 0.
- **The page footnote says** rates are indicative ("chỉ mang tính tham khảo") and that unlisted terms and currencies are available at branches. Not stored per row.

## When it raises `AdapterBroken`

- the body is not JSON, or has no `Data` list;
- `AccountType` is not `Personal`, or `Count` ≠ number of rows;
- a row is missing a key, or has an unknown `tenorType` (a new product needs a human decision);
- a rate is not a number between 0 and 0.2 (e.g. sent as a percent or a string);
- a term label can't be parsed, or disagrees with the tenor key;
- any of the three products, or its 1/3/6/12-month VND rate, is missing.
