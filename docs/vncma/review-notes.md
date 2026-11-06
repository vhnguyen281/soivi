# VNCMA 2027.1-draft: ghi chú rà soát (Prompt 9)

Người rà soát: Claude, đóng vai một CFA charterholder hoài nghi. Ngày 06/11/2026.
Bản được rà soát: run 2 (dữ liệu đến 31/10/2026, phương pháp 1.0.0, code `41b0cbf`). Không sửa code trong bước này.
Kết luận ngắn: **có thể phát hành dưới dạng bản đầu tiên có ghi chú**. Không có lỗi tính toán, nhưng có 3 giả định cần
chủ dự án quyết định rõ trước khi duyệt (mục 3, điểm 1–3).

## 1. So với lịch sử

Lịch sử = lợi nhuận bình quân nhân theo năm của chuỗi tháng mà mô hình dùng để tính biến động (DECISIONS, Prompt 5).

| Lớp | Kỳ vọng 10 năm | Lịch sử | Giai đoạn | Nhận xét |
|---|---:|---:|---|---|
| Tiền gửi VND | 5,23 | 4,65 | 2016-02 → 2026-10 | Hợp lý. Lãi 12 tháng hiện tại của các ngân hàng lớn là 5,79. |
| TPCP 10 năm | 4,35 | 7,88 | 2013-04 → 2026-10 | Lịch sử cao nhờ lợi suất 10 năm giảm từ 10,3% (03/2013) xuống thấp nhất 1,86% (lãi vốn). Không lặp lại được, nên mức thấp hơn là đúng hướng. |
| Trái phiếu DN | 5,35 | 7,67 | 2013-07 → 2026-10 | Lịch sử là NAV quỹ, đã trừ phí và đi qua giai đoạn lợi suất giảm. Có thể hơi thấp. |
| VN30 | 10,12 | 12,15 | 2012-03 → 2026-10 | Lịch sử gồm D/P cố định 2,34. Mức kỳ vọng thấp hơn lịch sử 2 điểm % là thận trọng nhưng hợp lý. |
| VNMID/VNSML | 10,80 | 10,74 | 2015-06 → 2026-10 | Ngang lịch sử. Cao hơn VN30 0,7 điểm % trong khi biến động cao hơn 2 điểm %: chấp nhận được. |
| Vàng (VND) | 4,40 | 17,12 | 2020-02 → 2026-10 | Lịch sử chỉ 6,7 năm và trùng với đợt tăng giá kỷ lục. Không nên dùng làm mốc. |
| USD | 1,60 | 5,27 | 2021-02 → 2026-09 | Lịch sử cộng lãi Fed, nhưng người gửi USD ở Việt Nam chỉ được trần 0%. Kỳ vọng dùng 0% là đúng. |
| Cổ phiếu toàn cầu | 7,80 | 16,91 | 2020-02 → 2026-10 | Lịch sử ngắn và rơi vào giai đoạn rất tốt của Mỹ. Kỳ vọng dựa trên CMA đã công bố là đúng cách. |
| Bất động sản | 7,42 (4,95–9,90) | — | — | Không có dữ liệu, hạng C. |

## 2. Kiểm tra theo lẽ thường

- Cổ phiếu > TPCP: **đạt** (10,12 so với 4,35).
- TPCP > tiền gửi: **không đạt** (4,35 so với 5,23). Xem mục 3, điểm 1.
- Cổ phiếu > tiền gửi: **đạt**. Phần bù rủi ro cổ phiếu so với tiền gửi là 4,9 điểm %; trên mỗi đơn vị biến động là 0,24.
  Mức này hợp lý cho thị trường mới nổi.
- Biến động vàng < biến động cổ phiếu: **đạt nhưng sát** (19,0% so với 20,6%). Vàng VND được đo bằng giá trung bình
  tháng, đã hiệu chỉnh Geltner. Trong 6,7 năm qua biến động vàng cao bất thường, nên con số này có thể đang phóng đại.
- So với CMA thị trường mới nổi của các tổ chức toàn cầu: **chưa làm được**. Config chưa có giá trị nào (Prompt 9 yêu cầu
  chủ dự án tự nhập). Đề xuất nhập ít nhất J.P. Morgan LTCMA 2027 và Vanguard cho cổ phiếu EM, quy sang VND bằng `d`,
  rồi so với VN30.

## 3. Mười giả định yếu nhất (xếp từ quan trọng nhất)

1. **TPCP thấp hơn tiền gửi.** `r_star_gov` (−0,80) là bình quân 10 năm, trong đó có 2020–2022 khi lợi suất 1 năm
   bình quân chỉ 1,4% (thấp nhất 0,43%). Nếu chỉ lấy 5 năm gần nhất hoặc dùng lãi suất điều hành thay cho lợi suất 1 năm, `y_eq` tăng và kỳ vọng
   TPCP còn thấp hơn nữa. Việc TPCP thấp hơn tiền gửi là đặc thù có thật của Việt Nam. Người dùng cá nhân không mua được
   TPCP ở mức lợi suất HNX, nên thứ tự này không gây hại cho kế hoạch. Nhưng báo cáo phải ghi rõ, và bộ tối ưu không
   được hiểu TPCP là "tài sản an toàn có lợi suất cao hơn".
2. **P/E hiện tại của VN30 phụ thuộc nguồn.** Chỉ số của VNDIRECT là 11,36. Tính cộng dồn từ các mã đang trong rổ ra
   8,82. Mô hình dùng số của VNDIRECT cho cả `PE_0` lẫn trung vị, nên chênh lệch mức độ triệt tiêu trong
   ln(PE_target/PE_0). Tuy vậy, chênh 2,5 lần P/E cho thấy hai cách tính khác nhau đáng kể. Có thể do trọng số free-float, cách xử lý
   doanh nghiệp lỗ, hoặc kỳ lợi nhuận; VNDIRECT không công bố công thức. Cần ghi chú
   và theo dõi qua các lần chạy.
3. **Phần định giá +1,24 điểm %/năm (VN30) dựa trên trung vị chỉ 9 năm (2017-12 → 2026-10).** Giai đoạn này gồm đỉnh
   24,0 (03/2018) và đáy 10,6 (10/2022). Nếu trung vị thật chỉ là 12,5 thay vì 14,4, phần định giá còn khoảng +0,5. Với VNMID, `PE_0`
   10,15 là mức thấp nhất từ 2018, nên phần định giá +1,9 điểm % là lớn nhất trong các lớp.
4. **`g_eps = 0,6 × g`.** Đây là phán đoán, chưa có dữ liệu Việt Nam để kiểm chứng. Mỗi 0,1 trong hệ số làm cổ phiếu đổi
   0,61 điểm %. Tăng trưởng EPS thực của VN30 trong 2018–2026 có thể tính được từ dữ liệu `ratio()`, nên kiểm chứng ở
   bản sau.
5. **Lạm phát `pi` = 3,90 neo vào mục tiêu một năm (4,5% cho 2026).** Mục tiêu hằng năm của Quốc hội thường là 4%, còn
   thực tế 10 năm là 3,29. Neo vào mục tiêu làm tăng mọi lớp danh nghĩa khoảng 0,6 điểm %, trừ TPCP (bị giảm). Xem độ
   nhạy ở mục 4.
6. **D/P lấy theo vốn hoá toàn bộ và chỉ tính cổ tức tiền mặt trượt 12 tháng.** VNSML có D/P 3,92, cao bất thường so với
   VNMID 1,88, có thể vì vài mã trả cổ tức lớn chiếm tỷ trọng cao (chưa kiểm tra từng mã). Cổ tức bằng cổ phiếu (rất phổ biến
   ở Việt Nam) không được tính, trong khi phần pha loãng đã có `dS` 1%. Cần xem danh sách mã trong snapshot trước khi duyệt.
7. **Vàng: `theta` 0,5% và không hồi quy về giá trị trung bình** dù giá đang ở đỉnh lịch sử (4.105 USD/oz trung bình
   tháng 10/2026). Kịch bản xấu lại cho vàng tốt hơn (5,40), vì VND mất giá. Điều này đúng logic, nhưng người dùng có thể
   hiểu nhầm. Chênh giá SJC hiện là 6%, trung vị từ 2020 là 12,6%: người mua vàng miếng chịu thêm rủi ro này.
8. **Cổ phiếu toàn cầu lấy từ hai CMA lệch nhau 2,6 điểm %** (J.P. Morgan 7,5, Vanguard 4,9) và khác ngày (09/2026 so với
   12/2025). Hai bộ chỉ cho cổ phiếu Mỹ, không phải toàn cầu. Nên thêm CMA thứ ba (MSCI ACWI) và cùng kỳ.
9. **Trái phiếu doanh nghiệp: chênh lệch 2,0 và tổn thất 1,0 là cấu hình, hạng C.** Biến động lịch sử 2,2% đã bị nâng lên
   mức sàn 3%, vì NAV quỹ được làm mượt. Sau 2022–2023, tổn thất thật có thể lớn hơn 1 điểm %/năm trong một chu kỳ xấu.
10. **Tương quan dựa trên 66 tháng chung** (từ 2021, vì USD/VND chỉ có từ 2020). Mức co Ledoit–Wolf là 0,35. Cặp có lịch
    sử dài được co ít hơn (DECISIONS Prompt 6). Tương quan của vàng, USD và cổ phiếu toàn cầu chỉ phản ánh giai đoạn
    2020–2026.

Các điểm nhỏ khác:
- Biến động tiền gửi 0,5% là biến động của lãi suất, không phải rủi ro mất vốn.
- `g` bình quân 10 năm gồm cả hai năm COVID (2020: 2,9%; 2021: 2,6%).
- Kịch bản không sốc lạm phát, nên tiền gửi và TPCP giống nhau trong cả ba kịch bản.

## 4. Độ nhạy (thay đổi kỳ vọng, điểm %/năm)

`pi` ±1 điểm % (kéo theo `d`, vì `d = pi − pi_us`); `g` ±1 điểm %; `PE_target` ±1 lần P/E.

| Lớp | pi +1 | pi −1 | g +1 | g −1 | PE_target +1 | PE_target −1 |
|---|---:|---:|---:|---:|---:|---:|
| Tiền gửi VND | +1,00 | −1,00 | 0 | 0 | 0 | 0 |
| TPCP | −0,79 | +0,79 | 0 | 0 | 0 | 0 |
| Trái phiếu DN | −0,79 | +0,79 | 0 | 0 | 0 | 0 |
| VN30 | +1,00 | −1,00 | +0,60 | −0,60 | +0,75 | −0,81 |
| VNMID/VNSML | +1,00 | −1,00 | +0,60 | −0,60 | +0,88 | −0,96 |
| Vàng | +1,00 | −1,00 | 0 | 0 | 0 | 0 |
| USD | +1,00 | −1,00 | 0 | 0 | 0 | 0 |
| Cổ phiếu toàn cầu | +1,00 | −1,00 | 0 | 0 | 0 | 0 |
| Bất động sản (điểm giữa) | +0,75 | −0,75 | 0 | 0 | 0 | 0 |

Đọc bảng:
- **`pi` là biến quan trọng nhất.** Nó dịch gần như mọi lớp 1:1. Riêng TPCP đi ngược chiều, vì `y_eq` tăng thì giá
  trái phiếu giảm.
- **`g` chỉ tác động lên cổ phiếu**, qua hệ số 0,6.
- **Một lần P/E** tương đương khoảng 0,8–1,0 điểm %/năm cho cổ phiếu. Đây là nguồn bất định lớn nhất của nhóm cổ phiếu.

## 5. Đề xuất trước khi duyệt 2027.1

1. Duyệt như hiện tại, kèm ghi chú trên trang công khai về hai điểm:
   - thứ tự TPCP < tiền gửi;
   - P/E VN30 của VNDIRECT khác P/E tính cộng dồn từ các mã.
2. Nhập ít nhất một CMA cổ phiếu thị trường mới nổi vào config để so sánh (không đổi công thức).
3. Bản sau:
   - kiểm chứng `g_eps` bằng EPS thực của VN30;
   - thêm CMA thứ ba cho cổ phiếu toàn cầu;
   - cân nhắc thêm kịch bản sốc lạm phát.
