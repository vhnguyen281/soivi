# Agribank — savings rates

| | |
|---|---|
| Adapter | `agribank_savings` ([pipeline/adapters/agribank.py](../../pipeline/adapters/agribank.py)) |
| Source URL | `https://www.agribank.com.vn/wcm/connect/ttkhac/lai-suat/lai-suat-cn?source=library&srv=cmpnt&cmpntid=c1687c7c-142f-4616-a8b0-02f09a14f844` |
| Human page | https://www.agribank.com.vn/vn/lai-suat-tien-gui |
| Format | HTML fragment (two tables) |
| Fetch method | `http` |
| Fixture | `tests/fixtures/agribank/savings_2026-10-26.html` |
| Checked | 2026-10-26 |

## How the page publishes rates

`/vn/lai-suat-tien-gui` is an IBM WebSphere Portal page with no rate table in its HTML. In a browser it loads two **HTML fragments** from the WCM library: `…/lai-suat/lai-suat-cn` (cá nhân, personal) and `…/lai-suat/lai-suat-dn` (doanh nghiệp, business). We found these by loading the page once in headless Chromium and logging its XHR calls. We fetch the personal fragment directly with a plain GET.

The `cmpntid` parameter is the presentation component the page uses. If Agribank rebuilds the page it may change; the adapter would then raise (fragment empty or 404), and the new id can be found the same way.

## Tables in the fragment

1. **Counter rates** (no heading). Columns: `Kì hạn | VND | USD | EUR | JPY | Ngoại tệ khác`. Note the "Kì" spelling: the header check is exact on purpose. Rows: Không kỳ hạn, 1–13 tháng, 15, 18, 24 tháng, then **"Tiền gửi thanh toán"** (payment account). Rates look like `5.4%` (dot decimal).
2. **"LÃI SUẤT TIỀN GỬI TRỰC TUYẾN (VND)"**. Columns: `STT | Kỳ hạn | Mức lãi suất tối đa (%/năm)`. Rows are **bands** ("Từ 01 tháng đến dưới 03 tháng" … "Từ 24 tháng trở lên"), and rates look like `4,75` (comma decimal, no %).

## How rows are stored

| Row | product_name | channel | term | conditions_text |
|---|---|---|---|---|
| Không kỳ hạn, N Tháng | Tiền gửi tiết kiệm | counter | N months | — |
| Tiền gửi thanh toán | Tiền gửi thanh toán | counter | 0/0 | — |
| Online band "Từ A tháng đến dưới B tháng" | Tiền gửi trực tuyến | online | A months | "Mức lãi suất tối đa; áp dụng cho kỳ hạn: …" |
| Online "Từ 24 tháng trở lên" | Tiền gửi trực tuyến | online | 24 months | same |

## Quirks

- **Online rates are ceilings** ("mức lãi suất tối đa"), not a fixed rate. Every online record says so in `conditions_text`. The public site must show them as "up to", and the review UI should make this visible. **Worth a product decision.**
- **The open-ended online band "Từ 24 tháng trở lên"** is stored at 24 months, because its lower bound is stated and it's the only online figure for 24+ months. (VietinBank's "Trên 36 tháng" is skipped instead: it starts after a stated term and 36 months has its own row.)
- **"Không kỳ hạn" and "Tiền gửi thanh toán" are both demand rates** (0.2%). They're kept apart by product name, since they're different products.
- **No product names are shown** for the counter table. "Tiền gửi tiết kiệm" is our label.
- **Interest payment method is not stated;** we record `end` (**assumption to confirm**). No effective date is stated.
- **Formatting is Word-generated HTML** (inline `windowtext` styles, `<p><span>` in every cell), so expect noisy diffs in snapshots even when rates don't change.

## When it raises `AdapterBroken`

- the counter table (by exact header) or the online table (by heading) is missing, or there's more than one;
- the online header changes (e.g. "tối đa" disappears, which changes the meaning);
- a row has the wrong number of cells, or a term, band or rate can't be parsed;
- a core counter term (KKH, 1, 3, 6, 12, 24) is missing, or the online bands no longer start at 1, 3, 6, 12, 24;
- two rows map to the same product and term.
