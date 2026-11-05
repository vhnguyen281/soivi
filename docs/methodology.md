# Phương pháp xếp hạng · Ranking methodology

**Phiên bản / Version: 1.2.0** (`METHODOLOGY_VERSION` in `core/scoring/__init__.py`). Mỗi phản hồi API đều ghi phiên bản này. / Every API response carries this version.

[Tiếng Việt](#tiếng-việt) · [English](#english)

---

## Tiếng Việt

### Nguyên tắc

- **Bảng xếp hạng chỉ dựa trên công thức công khai trong tài liệu này.** Không có vị trí trả tiền, không có tài trợ, không có ngoại lệ.
- **Chỉ dùng số liệu đã được người duyệt xác nhận**, lấy từ trang web hoặc biểu phí của chính ngân hàng. Số liệu đang chờ duyệt không bao giờ được xếp hạng.
- **Không đoán.** Nếu thiếu một con số mà công thức cần, sản phẩm được liệt kê riêng là "chưa xếp hạng", kèm lý do.
- **Mọi thay đổi** về công thức, giả định hay hồ sơ mẫu đều tăng số phiên bản và được ghi ở [Nhật ký thay đổi](#nhật-ký-thay-đổi--changelog).

### 1. Tiết kiệm

Bạn nhập số tiền gửi **P** (đồng), kỳ hạn **n** tháng, kênh gửi (tùy chọn) và vùng (tùy chọn). Chúng tôi xếp các mức lãi suất hiện hành theo **số tiền lãi bạn có được khi đáo hạn**, từ cao đến thấp.

#### 1.1. Lãi cơ bản

Lãi suất ngân hàng công bố là **% một năm, lãi đơn**. Với thời gian gửi t = n / 12 năm:

> **Lãi = P × r × t**

Ví dụ: gửi 100.000.000 đ, 12 tháng, lãi suất 6,00%/năm → 100.000.000 × 0,06 × 1 = **6.000.000 đ**.

Ngân hàng tính theo số ngày thực tế / 365, nên số liệu của ngân hàng có thể chênh vài đồng đến vài nghìn đồng.

#### 1.2. So sánh công bằng giữa các cách trả lãi

Cùng một lãi suất, nhận lãi sớm (hằng tháng, hằng quý, trả trước) có lợi hơn nhận lãi cuối kỳ, vì tiền lãi nhận sớm có thể gửi tiếp. Vì vậy ngân hàng thường áp lãi suất thấp hơn cho các cách trả lãi sớm.

Để so sánh công bằng, chúng tôi quy mọi cách trả lãi về **giá trị tương đương tại ngày đáo hạn**, với giả định: **mỗi khoản lãi nhận được đem gửi tiếp với chính lãi suất đó cho đến ngày đáo hạn.**

| Cách trả lãi | Công thức lãi tương đương khi đáo hạn | Giải thích |
|---|---|---|
| Cuối kỳ | P × r × t | Không có gì để quy đổi. |
| Hằng tháng | P × [(1 + r/12)ⁿ − 1] | Mỗi tháng nhận P × r/12, gửi tiếp hằng tháng (lãi nhập gốc). |
| Hằng quý | P × [((1 + r/4)ᵏ − 1) × (1 + r × m/12) + r × m/12] | k = số quý đủ, m = số tháng lẻ còn lại (lãi tháng lẻ trả khi đáo hạn). |
| Trả trước | P × r × t × (1 + r × t) | Nhận toàn bộ lãi ngay khi gửi, đem gửi tiếp hết kỳ. |

Ví dụ với 100.000.000 đ, 12 tháng:

| Ngân hàng | Lãi suất | Trả lãi | Lãi thực nhận | Tương đương khi đáo hạn | Thứ hạng |
|---|---|---|---|---|---|
| B | 5,80% | hằng tháng | 5.800.000 | **5.956.695** | 1 |
| A | 5,95% | cuối kỳ | 5.950.000 | **5.950.000** | 2 |
| C | 5,50% | trả trước | 5.500.000 | **5.802.500** | 3 |

Kết quả hiển thị cả **lãi thực nhận** (P × r × t, tổng tiền ngân hàng trả), **lãi tương đương khi đáo hạn** (dùng để xếp hạng) và **lãi suất tương đương** (lãi tương đương quy về %/năm cuối kỳ). Mọi số tiền làm tròn đến đồng (từ 0,5 làm tròn lên).

#### 1.3. Sản phẩm nào được tính

- **Kỳ hạn:** đúng kỳ hạn bạn chọn (tính theo tháng).
- **Số tiền tối thiểu:** sản phẩm có mức gửi tối thiểu lớn hơn số tiền của bạn bị loại. API cho biết đã loại bao nhiêu sản phẩm vì lý do này.
- **Bậc số tiền:** nếu một sản phẩm có nhiều bậc theo số tiền (ví dụ từ 0, từ 1 tỷ, từ 3 tỷ), chỉ dùng bậc áp dụng cho số tiền của bạn, tức bậc cao nhất không vượt quá số tiền. Mỗi sản phẩm chỉ xuất hiện một lần.
- **Kênh gửi:**
  - `any`: tất cả;
  - `counter`: tại quầy;
  - `online`: trực tuyến;
  - `app`: ứng dụng;
  - `digital`: trực tuyến và ứng dụng.
- **Vùng:** một số ngân hàng có lãi suất khác nhau theo vùng. Nếu bạn chọn vùng, chỉ tính lãi suất toàn quốc và lãi suất của vùng đó; nếu không chọn, tính tất cả và gắn cờ "theo vùng".
- **Hòa điểm:** nếu hai sản phẩm bằng nhau, sản phẩm có lãi suất công bố cao hơn đứng trước, sau đó xếp theo tên ngân hàng và tên sản phẩm.

#### 1.4. Cờ điều kiện

Cờ giúp bạn thấy điều kiện kèm theo. **Cờ không làm thay đổi thứ hạng.**

| Cờ | Ý nghĩa | Nguồn |
|---|---|---|
| `new_customer_only` | Chỉ dành cho khách hàng mới | Điều kiện ngân hàng ghi ("khách hàng mới", "lần đầu"…) |
| `app_only` | Chỉ gửi qua ứng dụng | Kênh = ứng dụng, hoặc điều kiện ghi "ứng dụng", "app" |
| `early_withdrawal_penalty` | Rút trước hạn bị mất phần lớn tiền lãi | Luôn bật với tiền gửi có kỳ hạn: theo quy định hiện hành, rút trước hạn thường chỉ được hưởng lãi suất không kỳ hạn |
| `early_withdrawal_terms_stated` | Ngân hàng ghi rõ điều kiện rút trước hạn | Điều kiện ngân hàng ghi |
| `rate_is_maximum` | Lãi suất là mức **tối đa**, không phải ai cũng được | Điều kiện ghi "tối đa" |
| `certificate_of_deposit` | Chứng chỉ tiền gửi | Dữ liệu sản phẩm |
| `deposit_insurance` | Tổ chức tham gia bảo hiểm tiền gửi (ngân hàng: có; công ty tài chính: không nhận tiền gửi) | Dữ liệu tổ chức |
| `regional` | Lãi suất chỉ áp dụng cho một vùng | Dữ liệu sản phẩm |
| `unverified` | Nguồn của ngân hàng chưa được kiểm tra lại gần đây, nên số liệu có thể đã cũ | Hệ thống theo dõi nguồn |

Cờ đọc từ điều kiện của ngân hàng dựa trên từ khóa. Luôn đọc nguyên văn điều kiện (`conditions_text`) trước khi gửi tiền.

#### 1.5. Giới hạn

- **Giả định gửi tiếp tiền lãi với cùng lãi suất** là chuẩn chung để so sánh. Thực tế bạn có thể gửi tiếp với lãi suất khác.
- **Lãi suất "tối đa"** có thể cao hơn mức bạn thực sự được hưởng.
- **Số ngày:** chúng tôi dùng tháng / 12, không dùng số ngày thực tế.

### 2. Thẻ tín dụng

Bạn mô tả cách chi tiêu (hoặc chọn một hồ sơ mẫu). Chúng tôi tính **giá trị ròng một năm** của từng thẻ, tính bằng đồng, và xếp từ cao đến thấp.

#### 2.1. Công thức

> **V = Σ_c min(r_c × S_c, cap_c) + P − F × (1 − w) − f_FX × S_nước_ngoài − i × B**

Mọi thành phần tính cho **một năm**.

| Ký hiệu | Ý nghĩa | Cách tính |
|---|---|---|
| r_c × S_c, cap_c | Hoàn tiền | Với mỗi ưu đãi hoàn tiền: tỷ lệ × chi tiêu hằng tháng thuộc ưu đãi đó, không vượt quá mức trần **hằng tháng**, rồi × 12. |
| P | Đặc quyền bạn quan tâm | Số lượt phòng chờ bạn dùng (không quá số lượt thẻ cho, trừ khi thẻ ghi không giới hạn) × giá trị bạn đặt cho mỗi lượt, cộng giá trị bảo hiểm du lịch nếu thẻ có. |
| F, w | Phí thường niên | w = 1 (được miễn phí) khi 12 × tổng chi tiêu hằng tháng ≥ mức chi tiêu miễn phí của thẻ. Nếu không biết điều kiện miễn phí, w = 0. |
| f_FX × S_nước_ngoài | Phí chuyển đổi ngoại tệ | Phí % × 12 × chi tiêu ngoại tệ hằng tháng. |
| i × B | Lãi khi không trả hết dư nợ | Lãi suất năm × dư nợ bạn duy trì cả năm. Lãi suất lấy từ trang sản phẩm của thẻ nếu trang ghi rõ theo năm, nếu không thì từ biểu phí. Lãi suất ghi theo tháng không được quy đổi, và một khoảng lãi suất ("15,5% - 16,5%/năm") không được dùng. |

**Chi tiêu được gán cho ưu đãi nào:** mỗi nhóm chi tiêu (ăn uống, mua sắm trực tuyến, du lịch, xăng dầu, siêu thị, nước ngoài, khác) dùng ưu đãi hoàn tiền dành riêng cho nhóm đó. Nếu thẻ không có ưu đãi riêng, nhóm đó dùng ưu đãi "mọi chi tiêu" của thẻ (nếu có). Chi tiêu ngoại tệ thuộc nhóm "nước ngoài". Mức trần của ưu đãi "mọi chi tiêu" áp dụng chung cho tổng phần chi tiêu dùng ưu đãi đó.

#### 2.2. Ví dụ

Thẻ X:
- phí thường niên 1.000.000 đ, miễn phí khi chi tiêu 200 triệu/năm;
- hoàn 10% ăn uống (tối đa 500.000 đ/tháng) và 0,5% mọi chi tiêu;
- phí ngoại tệ 2,5%, lãi suất 30%/năm;
- 4 lượt phòng chờ/năm, có bảo hiểm du lịch.

Người dùng:
- chi tiêu hằng tháng: ăn uống 6 triệu, siêu thị 4 triệu, khác 2 triệu, trực tuyến 1 triệu, ngoại tệ 2 triệu;
- dư nợ 10 triệu;
- muốn 6 lượt phòng chờ, mỗi lượt đáng 400.000 đ; bảo hiểm du lịch đáng 500.000 đ.

| Thành phần | Tính | Đồng/năm |
|---|---|---|
| Hoàn tiền | (min(600.000; 500.000) + 0,5% × 9 triệu) × 12 | +6.540.000 |
| Đặc quyền | min(6; 4) × 400.000 + 500.000 | +2.100.000 |
| Phí thường niên | 12 × 15 triệu = 180 triệu < 200 triệu: không được miễn | −1.000.000 |
| Phí ngoại tệ | 2,5% × 12 × 2 triệu | −600.000 |
| Lãi | 30% × 10 triệu | −3.000.000 |
| **V** | | **4.040.000** |

#### 2.3. Không đoán

Thẻ bị đưa vào danh sách **chưa xếp hạng**, kèm lý do, khi:

| Lý do | Khi nào |
|---|---|
| `annual_fee_unknown` | Chưa có phí thường niên đã duyệt |
| `rewards_unknown` | Bạn có chi tiêu nhưng chưa có dữ liệu ưu đãi (hoàn tiền, tích điểm) của thẻ đã duyệt. Chưa có dữ liệu không có nghĩa là thẻ không có ưu đãi, nên thẻ không được tính như ưu đãi bằng 0 |
| `fx_fee_unknown` | Bạn có chi tiêu ngoại tệ nhưng chưa có phí ngoại tệ |
| `interest_rate_unknown` | Bạn duy trì dư nợ nhưng chưa có lãi suất thẻ |
| `income_below_minimum` | Thu nhập của bạn thấp hơn mức tối thiểu ngân hàng yêu cầu |

Cờ (không làm thay đổi thứ hạng):
- `points_not_valued`: thẻ có tích điểm hoặc dặm bay. Chưa có cách quy đổi chung ra tiền, nên phần này tính bằng 0.
- `income_requirement_unknown`: ngân hàng không công bố thu nhập tối thiểu.
- `unverified`: số liệu có thể đã cũ.

#### 2.4. Hồ sơ mẫu

Các con số dưới đây là **giả định minh họa**, không phải số liệu thống kê. Đơn vị: đồng/tháng.

| Mã | Hồ sơ | Chi tiêu hằng tháng | Khác |
|---|---|---|---|
| `everyday` | Chi tiêu hằng ngày, trả hết dư nợ | siêu thị 4tr, ăn uống 2tr, trực tuyến 2tr, xăng 1tr, khác 3tr | — |
| `traveller` | Hay đi du lịch | du lịch 5tr, ăn uống 4tr, trực tuyến 2tr, khác 3tr, **ngoại tệ 8tr** | 6 lượt phòng chờ/năm × 500.000 đ; bảo hiểm du lịch 1.000.000 đ/năm |
| `first_card` | Thẻ đầu tiên, thu nhập khiêm tốn | siêu thị 2tr, trực tuyến 1tr, xăng 0,5tr, khác 1,5tr | **thu nhập 10tr/tháng**: loại thẻ đòi thu nhập cao hơn |
| `revolver` | Thường không trả hết dư nợ | siêu thị 3tr, ăn uống 1,5tr, trực tuyến 1,5tr, khác 2tr | **dư nợ 20tr** cả năm |

#### 2.5. Giới hạn

- **Tích điểm và dặm bay** chưa được quy ra tiền.
- **Mức trần dùng chung:** khi ngân hàng ghi một mức trần chung cho nhiều nhóm (ví dụ "tối đa 5 triệu/tháng" cho cả ăn uống và du lịch), dữ liệu hiện lưu mức trần đó cho từng nhóm. Với người chi tiêu rất nhiều ở cả hai nhóm, hoàn tiền có thể bị tính cao hơn thực tế.
- **Đơn giản hóa:** dư nợ được coi như duy trì đều cả năm, và không tính phí rút tiền mặt, ưu đãi năm đầu hay khuyến mãi có thời hạn.

---

## English

### Principles

- **Rankings come only from the public formulas in this document.** No paid placement, no sponsorship, no exceptions.
- **Only values a human reviewer approved are used,** taken from the bank's own website or fee schedule. Pending values are never ranked.
- **Nothing is guessed.** If a number the formula needs is missing, the product is listed separately as "not ranked", with the reason.
- **Every change** to a formula, an assumption or a preset bumps the version and is logged in the [changelog](#nhật-ký-thay-đổi--changelog).

### 1. Savings

You give an amount **P** (VND), a term of **n** months, an optional channel and an optional region. We rank current rates by **the interest you have at maturity**, highest first.

#### 1.1. Basic interest

Banks quote **percent per year, simple interest**. For t = n / 12 years:

> **Interest = P × r × t**

Example: 100,000,000 VND for 12 months at 6.00% a year → 100,000,000 × 0.06 × 1 = **6,000,000 VND**.

Banks count actual days / 365, so their figure can differ by a few đồng to a few thousand đồng.

#### 1.2. Comparing payment schedules fairly

At the same rate, interest paid early (monthly, quarterly, upfront) is worth more than interest paid at maturity, because it can be deposited again. That is why banks quote lower rates for early payment.

To compare fairly, we value every schedule **at maturity**, assuming that **each interest payment is deposited again at the same rate until maturity**.

| Payment | Equivalent interest at maturity | Explanation |
|---|---|---|
| At maturity | P × r × t | Nothing to convert. |
| Monthly | P × [(1 + r/12)ⁿ − 1] | P × r/12 each month, compounded monthly. |
| Quarterly | P × [((1 + r/4)ᵏ − 1) × (1 + r × m/12) + r × m/12] | k = full quarters, m = leftover months (their interest is paid at maturity). |
| Upfront | P × r × t × (1 + r × t) | All interest paid at the start and deposited for the whole term. |

Example with 100,000,000 VND for 12 months:

| Bank | Rate | Paid | Cash interest | Equivalent at maturity | Rank |
|---|---|---|---|---|---|
| B | 5.80% | monthly | 5,800,000 | **5,956,695** | 1 |
| A | 5.95% | at maturity | 5,950,000 | **5,950,000** | 2 |
| C | 5.50% | upfront | 5,500,000 | **5,802,500** | 3 |

Each result shows:
- the **cash interest** (P × r × t, what the bank pays in total);
- the **equivalent interest at maturity**, which is the ranking basis;
- the **equivalent rate** (the equivalent interest as a simple yearly rate).

Amounts are rounded to whole đồng, half up.

#### 1.3. Which offers count

- **Term:** exactly the term you chose, in months.
- **Minimum amount:** offers whose minimum is above your amount are excluded. The API says how many were excluded this way.
- **Amount tiers:** when a product has tiers by amount (e.g. from 0, from 1 billion, from 3 billion), only the tier for your amount is used: the highest tier not above it. Each product appears once.
- **Channel:**
  - `any`: everything;
  - `counter`: at a branch;
  - `online`;
  - `app`;
  - `digital`: online and app.
- **Region:** some banks set rates by region. With a region, we use nationwide rates plus that region's; without one, we use all of them and flag regional rates.
- **Ties:** the higher quoted rate first, then by bank and product name.

#### 1.4. Flags

Flags show conditions. **They never change the rank.**

| Flag | Meaning | Source |
|---|---|---|
| `new_customer_only` | New customers only | The bank's conditions ("khách hàng mới", "lần đầu", …) |
| `app_only` | App only | Channel = app, or the conditions say "ứng dụng"/"app" |
| `early_withdrawal_penalty` | Early withdrawal loses most of the interest | Always on for term deposits: under current rules, early withdrawal usually earns only the demand-deposit rate |
| `early_withdrawal_terms_stated` | The bank states its own early-withdrawal terms | The bank's conditions |
| `rate_is_maximum` | The rate is a **maximum**; not everyone gets it | Conditions say "tối đa" |
| `certificate_of_deposit` | Certificate of deposit | Product data |
| `deposit_insurance` | The institution is covered by deposit insurance (banks: yes; finance companies don't take deposits) | Institution data |
| `regional` | The rate applies in one region only | Product data |
| `unverified` | The bank's sources haven't been re-checked recently; values may be out of date | Source monitoring |

Flags read from the bank's conditions are keyword-based. Always read the conditions (`conditions_text`) before depositing.

#### 1.5. Limits

- **Reinvesting at the same rate** is a common yardstick for comparison. In practice you may reinvest at a different rate.
- **"Maximum" rates** may be higher than what you actually get.
- **Days:** we use months / 12, not actual days.

### 2. Credit cards

You describe how you spend (or pick a preset). We compute each card's **net value over one year**, in VND, and rank highest first.

#### 2.1. Formula

> **V = Σ_c min(r_c × S_c, cap_c) + P − F × (1 − w) − f_FX × S_foreign − i × B**

Every term is for **one year**.

| Term | Meaning | How |
|---|---|---|
| r_c × S_c, cap_c | Cashback | For each cashback reward: rate × the monthly spend it applies to, capped at its **monthly** cap, × 12. |
| P | Perks you value | Lounge visits you'd use (no more than the card gives, unless unlimited) × your value per visit, plus your value of travel insurance if the card includes it. |
| F, w | Annual fee | w = 1 (waived) when 12 × total monthly spend ≥ the card's waiver spend. If the waiver rule is unknown, w = 0. |
| f_FX × S_foreign | Foreign-currency fee | Fee % × 12 × monthly foreign spend. |
| i × B | Interest on a balance | Yearly rate × the balance you carry all year. The rate comes from the card's product page when it states it per year, otherwise from the fee schedule. Monthly rates are not converted, and a range ("15.5% – 16.5% a year") is not used. |

**Which reward each spend earns:** each spend category (dining, online, travel, fuel, grocery, overseas, other) uses the card's cashback reward for that category. Without one, it falls back to the card's "all spend" reward, if any. Foreign spend is the "overseas" category. An "all spend" cap applies to the total spend that falls back to it.

#### 2.2. Example

Card X:
- annual fee 1,000,000 VND, waived at 200 million a year;
- 10% cashback on dining (capped at 500,000/month) and 0.5% on everything;
- FX fee 2.5%, interest 30% a year;
- 4 lounge visits a year and travel insurance.

User:
- monthly spend: dining 6M, grocery 4M, other 2M, online 1M, foreign 2M;
- a 10M balance;
- wants 6 lounge visits at 400,000 each, and values travel insurance at 500,000.

| Term | Working | VND/year |
|---|---|---|
| Cashback | (min(600,000, 500,000) + 0.5% × 9M) × 12 | +6,540,000 |
| Perks | min(6, 4) × 400,000 + 500,000 | +2,100,000 |
| Annual fee | 12 × 15M = 180M < 200M: not waived | −1,000,000 |
| FX fee | 2.5% × 12 × 2M | −600,000 |
| Interest | 30% × 10M | −3,000,000 |
| **V** | | **4,040,000** |

#### 2.3. Nothing is guessed

A card goes on the **not ranked** list, with the reason, when:

| Reason | When |
|---|---|
| `annual_fee_unknown` | No approved annual fee |
| `rewards_unknown` | You spend, but there is no approved reward data (cashback, points) for the card yet. No data doesn't mean no rewards, so the card isn't scored as if it earned nothing |
| `fx_fee_unknown` | You spend in foreign currency, but the FX fee is unknown |
| `interest_rate_unknown` | You carry a balance, but the card's interest rate is unknown |
| `income_below_minimum` | Your income is below the bank's minimum |

Flags (no effect on rank):
- `points_not_valued`: the card earns points or miles. There's no agreed VND value for them yet, so they count 0.
- `income_requirement_unknown`: the bank doesn't publish a minimum income.
- `unverified`: values may be out of date.

#### 2.4. Presets

The numbers below are **illustrative assumptions**, not statistics. Amounts in VND per month.

| Key | Persona | Monthly spend | Other |
|---|---|---|---|
| `everyday` | Everyday spender who pays in full | grocery 4M, dining 2M, online 2M, fuel 1M, other 3M | — |
| `traveller` | Frequent traveller | travel 5M, dining 4M, online 2M, other 3M, **foreign 8M** | 6 lounge visits/year × 500,000; travel insurance 1,000,000/year |
| `first_card` | First card on a modest income | grocery 2M, online 1M, fuel 0.5M, other 1.5M | **income 10M/month**: cards requiring more are excluded |
| `revolver` | Carries a balance | grocery 3M, dining 1.5M, online 1.5M, other 2M | **20M balance** all year |

#### 2.5. Limits

- **Points and miles** have no VND value yet.
- **Shared caps:** when a bank states one cap for several categories (e.g. "up to 5M/month" for dining and travel together), the data currently stores that cap on each category. For someone spending heavily in both, cashback can be overstated.
- **Simplifications:** the balance is treated as constant all year, and cash-advance fees, first-year offers and time-limited promotions are not counted.

---

## Nhật ký thay đổi · Changelog

| Phiên bản / Version | Ngày / Date | Thay đổi / Change |
|---|---|---|
| 1.2.0 | 2026-10-30 | Lãi suất thẻ lấy từ trang sản phẩm khi trang ghi rõ theo năm; không quy đổi lãi suất tháng. / Card interest comes from the product page when it states a yearly rate; monthly rates are not converted. |
| 1.1.0 | 2026-10-29 | Thẻ chưa có dữ liệu ưu đãi được đưa vào danh sách chưa xếp hạng (`rewards_unknown`), thay vì tính ưu đãi bằng 0. / Cards with no reward data are not ranked (`rewards_unknown`) instead of being scored as earning nothing. |
| 1.0.0 | 2026-10-29 | Phiên bản đầu tiên: xếp hạng tiết kiệm theo lãi tương đương khi đáo hạn; giá trị ròng của thẻ; 4 hồ sơ mẫu. / First version: savings ranked by equivalent interest at maturity; card net value; 4 presets. |
