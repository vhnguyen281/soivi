# Thiết kế: dữ liệu thị trường cho VNCMA (Prompt 3, bản đề xuất)

Trạng thái: **đã duyệt** 06/11/2026 (duyệt ở bước phát hành; ingest chạy trên Mac; HNX và World Bank trong Prompt 3). Đã làm xong; xem `docs/DECISIONS.md` 2026-11-06.
Phạm vi: bảng lưu chuỗi thị trường và vĩ mô, lệnh `python -m pipeline market ingest`. Các bảng của mô hình
(`macro_assumption`, `cma_run`, `cma_adjustment`, `cma_release`, `cma_release_value`) để Prompt 6+, khi cần đến.

## 1. Dùng lại `source` và `snapshot` (không tạo bảng song song)
- Thêm `SourceKind.MARKET_DATA` và `FetchMethod.API`.
- **Một dòng `source` cho mỗi nhà cung cấp**: `vnstock`, `hnx`, `worldbank`, `shiller` (sau này `sbv`, `imf`,
  `manual`). `institution_id` để trống, `url` là trang chủ nhà cung cấp.
- **Mỗi lần lấy một chuỗi là một `snapshot`**:
  - `url`: URL thật đã gọi; với vnstock là lệnh gọi, ví dụ `vnstock:Market().index("VN30").ohlcv(...)`.
  - File gốc lưu lên S3 kèm SHA-256 theo khóa `MARKET/<provider>/<series_code>/<yyyy-mm-dd>/<sha256>.<ext>`.
  - Với vnstock, file gốc là JSON chứa toàn bộ bảng cùng `df.attrs` (nguồn, tổ chức, điều khoản, robots.txt).
    Mã hash bỏ qua trường thời gian gọi (`requested_at`), nên cùng một dữ liệu luôn cho cùng một hash.
- Bộ lập lịch hiện tại phải **bỏ qua** các nguồn `market_data` (sửa `runner.runnable()`), vì các nguồn này có đường
  chạy riêng.

## 2. Bảng mới
### `market_series`: cấu hình, giống `source` (metadata, không phải giá trị công bố)
| cột | ý nghĩa |
|---|---|
| `code` (unique) | ví dụ `vn30_close`, `cpi_yoy`, `hnx_par_10y`, `xauusd_close`, `fund_nav_dcbf` |
| `source_id` | nhà cung cấp |
| `asset_class` | `eq_large`, `gov_bond`, …; để trống cho chuỗi vĩ mô |
| `request` (JSONB) | lệnh gọi vnstock (chuỗi bước như trong probe) hoặc URL và tham số |
| `value_field` | cột lấy giá trị, ví dụ `close`, `nav`, `cpi_total`, `par_yield_10y` |
| `unit` | `index_points`, `pct_pa`, `pct_yoy`, `vnd_per_usd`, `usd_per_oz`, `nav_vnd`, `ratio` |
| `native_frequency` | `daily`, `weekly`, `monthly`, `quarterly`, `yearly` |
| `month_end_rule` | xem mục 3 |
| `grade` | A / B / C (theo spec §3) |
| `active`, `notes`, `last_checked_at`, `last_snapshot_id` | |

Danh sách chuỗi nằm ở `data/seeds/market_series.csv` và được nạp bằng `make seed`, giống `sources.csv`.

### `market_observation`: chỉ ghi thêm, không bao giờ sửa (trigger `soivi_guard_append_only`)
| cột | ý nghĩa |
|---|---|
| `series_id`, `period_end` (ngày cuối tháng/quý/năm) | khóa của một quan sát |
| `revision` | 1, 2, …; unique (`series_id`, `period_end`, `revision`) |
| `obs_date` | ngày thật của giá trị được dùng, ví dụ 28/12/2018 cho tháng 12/2018 |
| `value` NUMERIC(20, 8) | |
| `snapshot_id` | bản chụp chứa giá trị này |
| `ingested_at` | |

Giá trị hiện hành của một tháng là dòng có `revision` lớn nhất. Khi nhà cung cấp sửa số cũ, hệ thống ghi một dòng
mới với revision + 1 và báo trong kết quả chạy. Dòng cũ không bị sửa hay xóa.

## 3. Quy tắc cuối tháng
| Loại chuỗi | Quy tắc (`month_end_rule`) |
|---|---|
| Giá ngày (chỉ số, tỷ giá, lợi suất, vàng, P/E) | `last_on_or_before`: giá trị cuối cùng **trước hoặc đúng** ngày cuối tháng, cách tối đa **10 ngày** (Tết có thể nghỉ 9–10 ngày); không có thì tháng đó để trống và báo lỗ hổng |
| NAV quỹ (có quỹ báo theo tuần) | như trên, tối đa **14 ngày** |
| HNX (tra theo ngày) | hỏi ngày cuối tháng; nếu trống thì lùi từng ngày (bỏ thứ Bảy, Chủ nhật), tối đa 10 ngày |
| Theo tháng (CPI) | `period_value`: giá trị của chính tháng đó |
| Theo quý / năm (GDP) | `period_value`, `period_end` = cuối quý / cuối năm |
| Tháng chưa kết thúc | **không lưu**, chỉ lưu các tháng đã đóng, để tránh phải sửa lại |

## 4. Lệnh `python -m pipeline market ingest`
- Chạy toàn bộ chuỗi `active`, hoặc chỉ một số chuỗi với `--series vn30_close,cpi_yoy`.
- **Lớp bọc vnstock** (`pipeline/market/source.py`, vẫn là chỗ duy nhất import vnstock):
  - thử lại 3 lần với thời gian chờ tăng dần cho lỗi tạm thời (mạng, giới hạn tốc độ, lỗi nhà cung cấp); không thử lại
    lỗi tham số;
  - nghỉ ≥ 1 giây giữa các lần gọi;
  - **báo lỗi khi bảng rỗng hoặc thiếu cột**, thông báo lỗi luôn nêu rõ lệnh gọi.
- Nguồn web (HNX, World Bank, Shiller) đi qua `PoliteHttp` hiện có: robots.txt, 5 giây mỗi tên miền, User-Agent trung thực.
  HNX dùng certifi cộng chứng chỉ trung gian GlobalSign lưu trong repo.
- **Không bao giờ ghi một phần:** mỗi chuỗi chạy trong một transaction riêng. Chuỗi nào lỗi thì không ghi gì, các chuỗi
  khác vẫn chạy tiếp. Cuối lần chạy in tóm tắt (số tháng mới, số revision, lỗ hổng, lỗi); có lỗi thì mã thoát khác 0.
- **Chạy lại nhiều lần không sinh dữ liệu thừa:** nếu hash bằng bản chụp gần nhất của chuỗi thì không ghi bản chụp mới,
  chỉ cập nhật `last_checked_at`. Tháng nào giá trị không đổi thì không ghi thêm dòng.
  → **Hai lần ingest liên tiếp, lần thứ hai không thêm gì** (điều kiện hoàn thành của Prompt 3).
- Chạy trên Mac bằng `uv run python -m pipeline market ingest`, ghi vào Neon và S3 theo `.env`, vì vnstock đã
  đăng ký trên máy này. Đưa vào lịch tự động hằng tháng là việc của Prompt 4.

## 5. Chuỗi ban đầu
| Nhà cung cấp | Chuỗi | Ghi chú |
|---|---|---|
| vnstock (`vci`) | VNINDEX, VN30, VNMID, VNSML, HNXINDEX (giá đóng cửa) | |
| vnstock (`vnd`) | P/E VNINDEX, VN30, HNX | từ 12/2017 |
| vnstock (`asean`) | CPI (tổng, lõi), GDP năm, liên ngân hàng ON/1M/3M, lãi suất tái cấp vốn, tỷ giá trung tâm và thị trường, lợi suất VN 1Y/2Y/5Y/10Y, US 10Y, Fed | lợi suất 2020+ để đối chiếu với HNX |
| vnstock (`cafef`) | NAV 12 quỹ trái phiếu ≥ 36 tháng | |
| vnstock (`dukascopy`) | XAUUSD | chỉ năm hiện tại, để đối chiếu |
| HNX | par yield 1Y, 2Y, 5Y, 10Y cuối tháng từ 2013 | lần nạp đầu khoảng 155 yêu cầu, chừng 15 phút |
| World Bank Pink Sheet | giá vàng tháng (USD/oz) | một file Excel |
| Shiller (Yale) | S&P 500 giá và cổ tức theo tháng | một file `.xls`; cần thư viện `xlrd` (chờ duyệt), nên tạm tắt |

P/E từ dưới lên cho VNMID/VNSML (khoảng 280 mã) là chuỗi **suy ra**, thuộc Prompt 5. Prompt 3 chỉ nạp chuỗi gốc.
Tỷ giá NHNN (từ nay về sau) và SJC thuộc Prompt 4 (bộ thu thập hằng tháng).

## 6. Duyệt bởi con người (nguyên tắc 4)
Quan sát thị trường là **đầu vào** chứ không phải giá trị công bố, và có hàng nghìn dòng. Vì vậy không duyệt từng dòng.
Nguyên tắc 4 áp dụng ở bước **phát hành** (`cma_release`): một người có tên phải duyệt trước khi công bố, xem được
các input đã dùng (theo hash) và các revision. Lệnh ingest in danh sách thay đổi để người chạy xem ngay.

## 7. Test (không cần mạng)
- Lớp bọc: thử lại / không thử lại, báo lỗi khi bảng rỗng hoặc thiếu cột, lệnh gọi nêu trong lỗi, hash ổn định.
- Quy tắc cuối tháng: ngày nghỉ, tuần, giới hạn 7 và 14 ngày, tháng chưa đóng, quý và năm.
- Parser HNX, World Bank, Shiller dựa trên trang và file đã lưu trong `tests/fixtures/`.
- DB (`soivi_test`): trigger chặn UPDATE/DELETE trên `market_observation`; revision; hai lần ingest liên tiếp với client
  giả thì lần hai không thêm gì; chuỗi lỗi không ghi một phần.
- Fixture Prompt 2 dùng để kiểm tra cột và cách đọc dữ liệu.

## 8. Thứ tự làm
1. Migration + model + seed `market_series` + sửa `runner.runnable()`.
2. `source.py` (vnstock: thử lại, hash, S3) + quy tắc cuối tháng + `market ingest` cho các chuỗi vnstock.
3. Nhà cung cấp HNX, World Bank, Shiller (fixtures, chứng chỉ trung gian HNX).
4. Chạy thật vào Neon và S3, chạy lần hai để xác nhận không thêm gì, ghi DECISIONS.
