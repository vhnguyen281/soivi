/**
 * Risk profile questionnaire (goals-based planning, Phase C). Runs in the browser; nothing is stored.
 *
 * Two scores, as in the CFA private-wealth workflow:
 * - ability to take risk (capacity): horizon, emergency fund, income stability, share of wealth, debt;
 * - willingness to take risk (tolerance): reaction to a fall, choice between return ranges, self-view.
 * Each answer scores 1..5. A dimension's level is the rounded mean of its answers. The suggested level is
 * the LOWER of the two: when they disagree, the client should not take more risk than they can carry,
 * nor more than they will sit through. Levels 1..5 map to the five model portfolios in order of risk.
 *
 * Behavioural notes are flagged from answer patterns (loss aversion, overconfidence, recency), to be shown
 * as reminders, never as a judgement.
 */

export type Dimension = "ability" | "willingness";

export type Question = {
  id: string;
  dimension: Dimension;
  vi: string;
  en: string;
  options: { vi: string; en: string }[]; // scored 1..5 in order
};

export const QUESTIONS: Question[] = [
  {
    id: "horizon",
    dimension: "ability",
    vi: "Khi nào bạn cần dùng phần lớn số tiền này?",
    en: "When will you need most of this money?",
    options: [
      { vi: "Dưới 2 năm", en: "Within 2 years" },
      { vi: "2–4 năm", en: "2–4 years" },
      { vi: "5–7 năm", en: "5–7 years" },
      { vi: "8–12 năm", en: "8–12 years" },
      { vi: "Trên 12 năm", en: "More than 12 years" },
    ],
  },
  {
    id: "emergency",
    dimension: "ability",
    vi: "Ngoài số tiền đầu tư, bạn có quỹ dự phòng đủ chi tiêu bao lâu?",
    en: "Apart from this money, how long would your emergency fund cover your spending?",
    options: [
      { vi: "Không có", en: "I have none" },
      { vi: "Dưới 3 tháng", en: "Under 3 months" },
      { vi: "3–6 tháng", en: "3–6 months" },
      { vi: "6–12 tháng", en: "6–12 months" },
      { vi: "Trên 12 tháng", en: "More than 12 months" },
    ],
  },
  {
    id: "income",
    dimension: "ability",
    vi: "Thu nhập của bạn trong vài năm tới ổn định đến đâu?",
    en: "How stable is your income over the next few years?",
    options: [
      { vi: "Không ổn định, có thể mất", en: "Unstable, could stop" },
      { vi: "Thay đổi nhiều theo tháng", en: "Varies a lot month to month" },
      { vi: "Khá ổn định", en: "Fairly stable" },
      { vi: "Ổn định", en: "Stable" },
      { vi: "Rất ổn định, có nhiều nguồn", en: "Very stable, several sources" },
    ],
  },
  {
    id: "share",
    dimension: "ability",
    vi: "Số tiền này chiếm bao nhiêu trong tổng tài sản của bạn (không tính nhà đang ở)?",
    en: "What share of your total wealth (excluding your home) is this money?",
    options: [
      { vi: "Trên 75%", en: "Over 75%" },
      { vi: "50–75%", en: "50–75%" },
      { vi: "25–50%", en: "25–50%" },
      { vi: "10–25%", en: "10–25%" },
      { vi: "Dưới 10%", en: "Under 10%" },
    ],
  },
  {
    id: "debt",
    dimension: "ability",
    vi: "Mỗi tháng bạn dành bao nhiêu thu nhập để trả nợ?",
    en: "How much of your monthly income goes to debt repayments?",
    options: [
      { vi: "Trên 50%", en: "Over 50%" },
      { vi: "30–50%", en: "30–50%" },
      { vi: "15–30%", en: "15–30%" },
      { vi: "Dưới 15%", en: "Under 15%" },
      { vi: "Không có nợ", en: "No debt" },
    ],
  },
  {
    id: "fall",
    dimension: "willingness",
    vi: "Nếu khoản đầu tư giảm 20% trong một năm, bạn sẽ làm gì?",
    en: "If your investment fell 20% in a year, what would you do?",
    options: [
      { vi: "Bán hết để tránh mất thêm", en: "Sell everything to stop the losses" },
      { vi: "Bán bớt một phần", en: "Sell some" },
      { vi: "Giữ nguyên và chờ", en: "Hold and wait" },
      { vi: "Mua thêm một ít", en: "Buy a little more" },
      { vi: "Mua thêm nhiều vì giá rẻ", en: "Buy a lot more while it is cheap" },
    ],
  },
  {
    id: "choice",
    dimension: "willingness",
    vi: "Với 100 triệu trong 1 năm, bạn chọn phương án nào?",
    en: "With 100 million VND for one year, which would you choose?",
    options: [
      { vi: "Chắc chắn còn 105 triệu", en: "105 million for sure" },
      { vi: "Thường 107 triệu, xấu nhất 100 triệu", en: "Usually 107 million, at worst 100 million" },
      { vi: "Thường 109 triệu, xấu nhất 92 triệu", en: "Usually 109 million, at worst 92 million" },
      { vi: "Thường 111 triệu, xấu nhất 85 triệu", en: "Usually 111 million, at worst 85 million" },
      { vi: "Thường 113 triệu, xấu nhất 75 triệu", en: "Usually 113 million, at worst 75 million" },
    ],
  },
  {
    id: "self",
    dimension: "willingness",
    vi: "Bạn tự thấy mình là nhà đầu tư thế nào?",
    en: "How would you describe yourself as an investor?",
    options: [
      { vi: "Rất thận trọng: không muốn mất đồng nào", en: "Very cautious: I do not want to lose anything" },
      { vi: "Thận trọng", en: "Cautious" },
      { vi: "Cân bằng", en: "Balanced" },
      { vi: "Chấp nhận rủi ro để có lợi nhuận cao hơn", en: "I accept risk for higher returns" },
      { vi: "Sẵn sàng chịu rủi ro cao", en: "Ready for high risk" },
    ],
  },
  {
    id: "experience",
    dimension: "willingness",
    vi: "Bạn đã từng đầu tư cổ phiếu hoặc quỹ cổ phiếu chưa?",
    en: "Have you invested in stocks or equity funds before?",
    options: [
      { vi: "Chưa bao giờ", en: "Never" },
      { vi: "Dưới 1 năm", en: "Under a year" },
      { vi: "1–3 năm", en: "1–3 years" },
      { vi: "3–7 năm, đã qua một lần thị trường giảm mạnh", en: "3–7 years, through one big fall" },
      { vi: "Trên 7 năm, qua nhiều chu kỳ", en: "Over 7 years, several cycles" },
    ],
  },
];

export type Answers = Record<string, number>; // question id -> 1..5

export type Note = "loss_aversion" | "overconfidence" | "capacity_limits" | "short_horizon";

export type Profile = {
  ability: number; // 1..5
  willingness: number; // 1..5
  level: number; // 1..5, the lower of the two
  notes: Note[];
};

function level(answers: Answers, dimension: Dimension): number {
  const scores = QUESTIONS.filter((q) => q.dimension === dimension).map((q) => answers[q.id]);
  if (scores.some((s) => !s || s < 1 || s > 5)) throw new Error(`unanswered ${dimension} question`);
  const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
  return Math.min(5, Math.max(1, Math.round(mean)));
}

export function complete(answers: Answers): boolean {
  return QUESTIONS.every((q) => answers[q.id] >= 1 && answers[q.id] <= 5);
}

export function profile(answers: Answers): Profile {
  const ability = level(answers, "ability");
  const willingness = level(answers, "willingness");
  // A short horizon caps the level: money needed within 2 years belongs in the most cautious mix.
  const cap = answers.horizon === 1 ? 1 : answers.horizon === 2 ? 2 : 5;
  const notes: Note[] = [];
  if (answers.fall <= 2 && answers.choice >= 4) notes.push("loss_aversion");
  if (answers.experience <= 2 && answers.self >= 4) notes.push("overconfidence");
  if (willingness > ability) notes.push("capacity_limits");
  if (cap < Math.min(ability, willingness)) notes.push("short_horizon");
  return { ability, willingness, level: Math.min(ability, willingness, cap), notes };
}
