// The lesson catalogue (Phần Học). Lessons marked "soon" are listed but not yet written.

export type Lesson = {
  slug: string;
  vi: { title: string; summary: string };
  en: { title: string; summary: string };
  minutes: number;
  status: "ready" | "soon";
  tool: string; // where "apply it to you" leads
};

export const LESSONS: Lesson[] = [
  {
    slug: "lam-phat",
    vi: { title: "Lạm phát ăn ví", summary: "Vì sao tiền để yên vẫn mất, và gửi đúng chỗ giúp được bao nhiêu." },
    en: { title: "Inflation eats your wallet", summary: "Why idle money still shrinks, and how much the right deposit helps." },
    minutes: 3,
    status: "ready",
    tool: "/lai-suat-tiet-kiem",
  },
  {
    slug: "lai-thuc-nhan",
    vi: { title: "Lãi niêm yết ≠ lãi thực nhận", summary: "Rút trước hạn, lãi trả hàng tháng hay cuối kỳ: con số bạn thật sự nhận." },
    en: { title: "Advertised rate ≠ what you get", summary: "Early withdrawal, monthly or end-of-term interest: what you actually receive." },
    minutes: 4,
    status: "ready",
    tool: "/lai-suat-tiet-kiem",
  },
  {
    slug: "tra-toi-thieu",
    vi: { title: "Bẫy trả tối thiểu thẻ tín dụng", summary: "Trả tối thiểu mỗi tháng thì mất bao lâu và tốn bao nhiêu lãi." },
    en: { title: "The minimum-payment trap", summary: "How long the minimum payment takes, and what it costs in interest." },
    minutes: 3,
    status: "ready",
    tool: "/the-tin-dung",
  },
  {
    slug: "bien-dong",
    vi: { title: "Biến động là gì?", summary: "Một trăm tương lai có thể xảy ra, và vì sao chúng toả rộng." },
    en: { title: "What is volatility?", summary: "A hundred possible futures, and why they fan out." },
    minutes: 5,
    status: "soon",
    tool: "/muc-tieu",
  },
  {
    slug: "giu-hay-ban",
    vi: { title: "Trò chơi: giữ hay bán?", summary: "Thị trường giảm 20%. Bạn làm gì?" },
    en: { title: "Game: hold or sell?", summary: "The market falls 20%. What do you do?" },
    minutes: 5,
    status: "soon",
    tool: "/ho-so-rui-ro",
  },
  {
    slug: "da-dang-hoa",
    vi: { title: "Đa dạng hoá có miễn phí?", summary: "Trộn các lớp tài sản để giảm rủi ro mà không giảm nhiều lợi nhuận." },
    en: { title: "Is diversification free?", summary: "Mixing asset classes to cut risk without giving up much return." },
    minutes: 4,
    status: "soon",
    tool: "/danh-muc-mau",
  },
];

export const lessonBySlug = (slug: string) => LESSONS.find((l) => l.slug === slug && l.status === "ready");
