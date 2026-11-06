# Báo cáo probe vnstock (VNCMA Prompt 2)

Chạy ngày 06/11/2026, vnstock 5.2.1, gói Golden, bằng lệnh `python -m pipeline market probe`.
Bảng đầy đủ từng lệnh (cột, số dòng, ngày đầu/cuối, mẫu dữ liệu, nguồn gốc):
[probe-results.md](probe-results.md). Mỗi lệnh có một fixture nhỏ (5 dòng đầu) trong `tests/fixtures/vnstock/`.

**Kết quả: 69/79 lệnh trả dữ liệu.** Đủ dữ liệu 10 năm theo tháng cho cổ phiếu, lãi suất liên ngân hàng,
CPI và quỹ trái phiếu. **Thiếu nặng:** vàng và S&P 500 (chỉ có năm hiện tại), tỷ giá (từ 2020),
lợi suất trái phiếu chính phủ (từ 08/2020).

## 1. Theo lớp tài sản

| Lớp | Chuỗi dùng được | Có từ | Đủ 10 năm? | Ghi chú |
|---|---|---|---|---|
| `eq_large` | VN30 ngày (nguồn `vci`) | 02/2012 | Có (14 năm) | VNINDEX có từ 01/2004. Chỉ là giá, chưa có cổ tức. |
| `eq_midsmall` | VNMID, VNSML ngày (`vci`) | 05/2015 | Có (11,5 năm) | Nguồn mặc định `kbs` trả bảng rỗng, phải dùng `vci`. |
| P/E (Grinold–Kroner) | P/E VNINDEX, VN30, HNX | 12/2017 | **Không** (9 năm) | `duration="20Y"` vẫn chỉ trả 9 năm. Không có P/E cho VNMID/VNSML. |
| Cổ tức | `Reference().events.calendar(event_type="dividend")` | — | — | Bộ lọc không lọc hết: 954 dòng cổ tức tiền mặt (`DIV`) lẫn 526 dòng phát hành cổ phiếu (`ISS`). Phải tự lọc `event_type == "DIV"`. `Market().equity(s).summary()` có `dividend_yield` hiện tại. |
| `gov_bond` | Lợi suất VN 1Y, 2Y, 3Y, 5Y, 10Y | 08/2020 | **Không** (6 năm) | 7Y và 15Y trả bảng rỗng, không báo lỗi. `resolution="1M"` bị bỏ qua: luôn trả dữ liệu ngày, có cả Chủ nhật. |
| `corp_bond` | NAV 15 quỹ trái phiếu (CafeF) | 2013 | Có | 12/15 quỹ có ≥ 36 tháng (xem mục 3). |
| `cash_vnd` | Liên ngân hàng ON/1W/1M/3M | 01/2016 | Có (10,8 năm) | Lãi suất điều hành chỉ từ 01/2021. `deposit_rate` chỉ là bảng hiện tại của 30 ngân hàng (kỳ hạn 1, 3, 6, 13, 36 tháng), ngày cập nhật từng ngân hàng từ 06/2025 đến 10/2026. Dùng lãi suất Phase 1 của mình là đúng. |
| Vĩ mô `pi` | CPI tháng (`cpi_total`, `cpi_core`, **% so với cùng kỳ**) | 01/2016 | Vừa đủ (10,8 năm) | Không phải chỉ số mức giá. |
| Vĩ mô `g` | GDP năm (% tăng) | 2015 | Vừa đủ (11 điểm) | GDP quý chỉ có số liệu từ Q3/2018 (các quý trước là trống). |
| `usd`, quy đổi | Tỷ giá trung tâm, thị trường | 01/2020 | **Không** (7 năm) | `Market().forex("USDVND")` lỗi HTTP 400. Fed rate theo tháng từ 2021. |
| `gold` | XAUUSD (Dukascopy) | **01/2026** | **Không** | Chỉ trả năm hiện tại. Hỏi năm 2025 trả bảng rỗng. Không còn giá vàng SJC (`Macro().commodity()` đã bỏ từ 5.0.0a2; tìm "SJC"/"vàng" không có mã). |
| `eq_global` | S&P 500 = mã **`USA500`** (cũng chạy với `SPX`) | **01/2026** | **Không** | Cùng nguồn Dukascopy, cùng giới hạn năm hiện tại. `US500` lỗi HTTP 400. |
| `real_estate` | — | — | — | Không có trong vnstock (như dự kiến). |

## 2. Những điều khác với ghi chép cũ
- `ohlcv()` **dừng ở 1.000 dòng** nếu không truyền `limit`, bất kể `start`. Probe dùng `limit=10000`.
- Chỉ số trong nước: nguồn `vci` có lịch sử dài hơn `kbs` (VNINDEX từ 2004 so với 06/2012; VNMID/VNSML chỉ có ở `vci`).
  Chỉ hai nguồn này phục vụ `market.index.ohlcv`.
- Hàm vĩ mô nằm ở `Macro().economy()` và `Macro().currency()`; lợi suất trái phiếu, Fed rate, DXY ở
  `Macro().global_macro`. Tham số `length` phải là số dòng, không nhận `"30Y"`.
- Nguồn vĩ mô (`asean`) có lịch sử ngắn bất kể `start`: không phải do cách gọi mà do nguồn.
- Bảng vĩ mô có thêm cột `vnindex`.
- Danh sách quỹ CafeF không có ngày thành lập (`inception_date` trống): lấy ngày NAV đầu tiên.
- Nhiều lệnh trả **bảng rỗng không báo lỗi** (kỳ hạn lạ, nguồn sai, năm cũ ở Dukascopy). Lớp bọc phải tự raise khi rỗng.

## 3. Quỹ trái phiếu có NAV
| Quỹ | NAV từ | Tần suất | ≥ 36 tháng |
|---|---|---|---|
| VFF | 04/2013 | ngày giao dịch | có |
| DCBF | 06/2013 | ngày | có |
| DCIP | 04/2019 | ngày | có |
| VNDBF | 07/2019 | ngày | có |
| VCBF-FIF | 08/2019 | tuần | có |
| PVBF | 02/2020 | ngày giao dịch | có |
| DFIX | 02/2021 | tuần | có |
| VLBF | 09/2021 | ngày | có |
| MAFF | 11/2021 | ngày | có |
| BVBF | 02/2022 | tuần | có |
| LHBF | 12/2022 | tuần | có |
| HDBOND | 01/2023 | ngày | có |
| ABBF | 01/2025 | ngày | không |
| LPBF | 07/2025 | ngày | không |
| SSIBF | 07/2025 | ngày | không |

`performance()` chỉ có YTD, 3 năm, 5 năm (ví dụ DCBF: 6,34% / 7,34%/năm / 6,99%/năm).

## 4. Quyết định (06/11/2026) và việc còn mở
1. **Vàng, S&P 500:** đồng ý. Vàng lấy từ World Bank Pink Sheet (tháng); S&P 500 lấy từ dữ liệu Shiller (Yale).
2. **Tỷ giá USD/VND:** lấy từ NHNN. Trang `sbv.gov.vn/tỷ-giá` hiện chỉ hiện tỷ giá trung tâm của ngày hôm nay
   (không có ô tra cứu theo ngày); NHNN đăng thêm tin "Diễn biến tỷ giá trung tâm" theo tuần.
   - Từ nay: bộ thu thập hằng tháng đọc tỷ giá trung tâm trên trang NHNN.
   - Lịch sử 01/2016–12/2019 (vnstock có từ 2020): **còn mở**. Cần tìm kho lưu trữ cũ của NHNN; nếu không có,
     dùng chuỗi tháng của IMF IFS (IMF lấy lại số của NHNN) và ghi rõ nguồn.
3. **Lợi suất TPCP:** chọn **HNX** làm nguồn chính (duyệt 06/11/2026); đang kiểm tra cách lấy, xem mục 5.
4. **P/E 9 năm:** đồng ý. `PE_target` dùng trung vị 9 năm (từ 12/2017).
5. **P/E cho VNMID/VNSML:** đồng ý cách tính từ dưới lên ở mục 6 (duyệt 06/11/2026).
6. **Giấy phép:** dự án cá nhân, chưa kinh doanh, nên chưa cần hỏi vnstocks. Xem lại khi bắt đầu kinh doanh
   hoặc công khai rộng.

## 5. Nguồn khác cho lợi suất TPCP (vnstock chỉ có từ 08/2020)
| Nguồn | Có gì | Ghi chú |
|---|---|---|
| **HNX** (Sở GDCK Hà Nội), đường cong lợi suất TPCP | Từ 2013, kỳ hạn đến 15 năm (phương pháp Svensson) | Nguồn chính thức, tốt nhất. Chưa kiểm tra được cách tra cứu theo ngày: chứng chỉ TLS của hnx.vn thiếu chứng chỉ trung gian, nên công cụ tải trang báo lỗi. Pipeline sẽ cần thêm chứng chỉ trung gian của HNX (không tắt kiểm tra TLS). |
| ADB AsianBondsOnline | Lợi suất 2, 5, 10 năm hằng ngày; có Data Portal | Chưa xác nhận lịch sử dài bao nhiêu; trang ghi "cấm sao chép khi chưa xin phép". |
| CEIC, Trading Economics | Chuỗi dài (10 năm từ 2013, có cả 2008) | Trả phí. |
| Investing.com | Lịch sử ngày/tuần/tháng | Điều khoản cấm thu thập tự động; chỉ có thể tải tay. |

Đề xuất: **HNX là nguồn chính** (đủ 10+ năm, chính thức), ADB để đối chiếu. Bước tiếp: kiểm tra trang HNX có tra cứu
theo ngày hay tải Excel không.

## 6. Đề xuất cách tính P/E cho VNMID/VNSML
vnstock không có P/E cho hai chỉ số này, nhưng `Fundamental().equity(s).ratio()` có **P/E và vốn hóa theo quý từ 2018-Q1**
cho từng cổ phiếu, và `Reference().index.members("VNMIDCAP"/"VNSMALLCAP")` cho danh sách thành phần (70 và 212 mã).

**Cách tính (từ dưới lên, theo vốn hóa):** mỗi quý, P/E nhóm = Σ vốn hóa ÷ Σ lợi nhuận, với lợi nhuận mỗi mã = vốn hóa ÷ P/E.
Mã lỗ được tính vào (lợi nhuận âm), đúng với lợi nhuận thật của cả giỏ. Bỏ quý có dưới 80% số mã có dữ liệu.

**Kiểm chứng trên VN30** (tính cùng cách, so với P/E VN30 của VNDIRECT, 35 quý): tương quan 0,75; lệch trung bình 11%;
có quý lệch tới 30% (2025-Q2). Nguyên nhân: dùng danh sách thành phần **hiện tại** cho cả quá khứ, và P/E quý của
từng mã chốt theo ngày báo cáo, không phải ngày cuối quý.

**Vì sao vẫn dùng được:** công thức chỉ cần tỷ số `ln(PE_target / PE_0)`. Nếu cả `PE_0` và `PE_target` đều tính
cùng một cách thì sai lệch về mức phần lớn triệt tiêu nhau. Vì vậy:
- `PE_0` = P/E từ dưới lên của quý gần nhất;
- `PE_target` = trung vị 9 năm của cùng chuỗi đó (rồi trộn với `PE_0` như spec).

**Kết quả thử (06/11/2026):**
| Nhóm | P/E hiện tại | Trung vị 9 năm | (1/10)·ln(trung vị/hiện tại) |
|---|---|---|---|
| VNMIDCAP | 10,8 | 13,8 | +2,5%/năm |
| VNSMALLCAP | 8,7 | 10,0 | +1,4%/năm |
| VN30 (VNDIRECT, để so) | 11,0 | 14,1 | +2,5%/năm |

**Hạn chế (ghi vào phương pháp, hạng dữ liệu B):** sai lệch do dùng danh sách hiện tại, dữ liệu theo quý, chỉ từ 2018.
Mỗi tháng cần khoảng 280 lần gọi (1 giây/lần), tức khoảng 5 phút.

**Phương án dự phòng, đơn giản hơn:** P/E nhóm = P/E VNINDEX × tỷ lệ (P/E nhóm từ dưới lên ÷ P/E VNINDEX từ dưới lên)
của quý gần nhất. Không cần lịch sử, nhưng giả định tỷ lệ này không đổi.
