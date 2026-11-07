// Plain-language definitions shown when a visitor taps an underlined term, and on /hoc#tu-dien.

export type Term = { id: string; lesson?: string; vi: { term: string; def: string }; en: { term: string; def: string } };

export const GLOSSARY: Term[] = [
  {
    id: "lam-phat",
    lesson: "lam-phat",
    vi: { term: "Lạm phát", def: "Mức tăng chung của giá cả. Lạm phát 4% nghĩa là sau một năm, 100đ chỉ mua được lượng hàng trước đây giá khoảng 96đ." },
    en: { term: "Inflation", def: "The general rise in prices. At 4% inflation, after a year 100 buys what about 96 bought before." },
  },
  {
    id: "lai-thuc",
    lesson: "lam-phat",
    vi: { term: "Lãi suất thực", def: "Lãi suất sau khi trừ lạm phát: phần sức mua bạn thật sự có thêm." },
    en: { term: "Real interest rate", def: "The interest rate after inflation: how much buying power you really gain." },
  },
  {
    id: "khong-ky-han",
    lesson: "lai-thuc-nhan",
    vi: { term: "Lãi không kỳ hạn", def: "Lãi của tiền gửi rút lúc nào cũng được. Thường rất thấp, và hay được áp dụng khi rút tiền gửi có kỳ hạn trước hạn." },
    en: { term: "Demand rate", def: "Interest on money you can withdraw any time. Usually very low, and often applied when a term deposit is withdrawn early." },
  },
  {
    id: "lai-quy-doi",
    lesson: "lai-thuc-nhan",
    vi: { term: "Lãi quy đổi", def: "Mức lãi tương đương nếu nhận cuối kỳ, để so công bằng các cách trả lãi khác nhau (hàng tháng, trả trước…)." },
    en: { term: "Equivalent rate", def: "The rate you would need if paid at the end of the term, so different payment styles compare fairly." },
  },
  {
    id: "bien-dong",
    lesson: "bien-dong",
    vi: { term: "Biến động", def: "Mức lợi nhuận thường lệch khỏi trung bình mỗi năm (độ lệch chuẩn). Biến động 20% nghĩa là khá nhiều năm lời hoặc lỗ hơn trung bình 20 điểm %." },
    en: { term: "Volatility", def: "How far returns usually swing from their average each year (standard deviation). 20% volatility means many years land 20 points above or below average." },
  },
  {
    id: "tuong-quan",
    lesson: "da-dang-hoa",
    vi: { term: "Tương quan", def: "Mức hai tài sản cùng lên cùng xuống, từ −1 (ngược chiều) đến 1 (cùng chiều). Tương quan càng thấp, trộn chúng càng giảm rủi ro." },
    en: { term: "Correlation", def: "How much two assets move together, from −1 (opposite) to 1 (in step). The lower it is, the more mixing them cuts risk." },
  },
  {
    id: "da-dang-hoa",
    lesson: "da-dang-hoa",
    vi: { term: "Đa dạng hoá", def: "Chia tiền vào nhiều loại tài sản không cùng lên xuống, để một loại giảm không kéo cả ví giảm theo." },
    en: { term: "Diversification", def: "Spreading money across assets that don't move together, so one falling doesn't drag down the whole wallet." },
  },
  {
    id: "danh-muc-mau",
    vi: { term: "Danh mục mẫu", def: "Năm cách chia tiền theo lớp tài sản, từ thận trọng đến tăng trưởng cao, tính từ giả định thị trường VNCMA. Không phải sản phẩm cụ thể." },
    en: { term: "Model portfolio", def: "Five asset-class mixes from cautious to high growth, built from the VNCMA assumptions. Not specific products." },
  },
  {
    id: "tai-can-bang",
    vi: { term: "Tái cân bằng", def: "Mua thêm phần đang thiếu và giảm phần đang thừa để tỷ trọng quay về kế hoạch." },
    en: { term: "Rebalancing", def: "Buying what has fallen short and trimming what has grown, to bring the mix back to plan." },
  },
  {
    id: "von-nhan-luc",
    vi: { term: "Vốn nhân lực", def: "Giá trị hôm nay của toàn bộ thu nhập bạn sẽ kiếm được đến khi nghỉ hưu. Với người trẻ, thường là tài sản lớn nhất." },
    en: { term: "Human capital", def: "Today's value of all the income you will earn until retirement. For young people it is often the largest asset." },
  },
];

export const termById = (id: string) => GLOSSARY.find((t) => t.id === id);
