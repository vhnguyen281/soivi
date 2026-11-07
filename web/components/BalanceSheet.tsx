"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  ASSET_KINDS,
  CONFIDENCE,
  economicBalanceSheet,
  goalPlan,
  JOBS,
  type AssetKind,
  type BalanceSheet as Sheet,
  type GoalPlan,
  type Job,
  type Profile,
  type Rates,
} from "@/lib/balanceSheet";
import type { ModelMix } from "@/lib/buckets";
import { vnd, type Lang } from "@/lib/format";
import { href } from "@/lib/i18n";
import { parseHistory, type Snapshot } from "@/lib/monitor";

import { Monitor } from "./Monitor";

const STORE = "soivi.balance.v1";

// Seven parts, seven categorical slots in fixed order (validated palette, see globals.css).
const ASSET_PARTS = ["financial", "humanCapital", "pension"] as const;
const LIABILITY_PARTS = ["debts", "spendingToRetirement", "spendingInRetirement", "goals"] as const;
type Part = (typeof ASSET_PARTS)[number] | (typeof LIABILITY_PARTS)[number];
const COLOUR: Record<Part, string> = {
  financial: "var(--series-1)",
  humanCapital: "var(--series-2)",
  pension: "var(--series-3)",
  debts: "var(--series-4)",
  spendingToRetirement: "var(--series-5)",
  spendingInRetirement: "var(--series-6)",
  goals: "var(--series-7)",
};

const TEXT = {
  vi: {
    general: "Thông tin chung",
    age: "Tuổi hiện nay",
    retire: "Tuổi nghỉ hưu dự kiến",
    life: "Lập kế hoạch đến tuổi",
    lifeHint: "Nên chọn cao hơn tuổi thọ trung bình để không hết tiền sớm.",
    job: "Thu nhập của bạn",
    jobs: {
      stable: "Ổn định (công chức, giáo viên, hợp đồng dài hạn)",
      average: "Trung bình (nhân viên doanh nghiệp)",
      volatile: "Biến động (kinh doanh, hoa hồng, ngành chứng khoán)",
    } satisfies Record<Job, string>,
    cash: "Thu nhập và chi tiêu (cả hộ gia đình)",
    income: "Thu nhập ròng mỗi tháng",
    incomeHint: "Sau thuế và BHXH.",
    bonus: "Thưởng, lương tháng 13 mỗi năm",
    growth: "Thu nhập tăng thêm mỗi năm (trên lạm phát, %)",
    spending: "Chi tiêu mỗi tháng",
    retSpending: "Chi tiêu mỗi tháng khi nghỉ hưu",
    retSpendingHint: "Theo giá hôm nay; thường bằng 70–80% hiện nay.",
    pension: "Lương hưu dự kiến mỗi tháng",
    pensionHint: "Theo giá hôm nay. Xem trên ứng dụng VssID hoặc để 0 nếu không có.",
    debtPayment: "Trả nợ mỗi tháng (gốc và lãi)",
    assets: "Tài sản",
    kinds: {
      deposit: "Tiền gửi, tiền mặt",
      bond: "Trái phiếu, chứng chỉ quỹ trái phiếu",
      stock: "Cổ phiếu, chứng chỉ quỹ cổ phiếu",
      gold: "Vàng",
      usd: "Ngoại tệ",
      home: "Nhà đang ở",
      property: "Bất động sản đầu tư",
      business: "Phần vốn kinh doanh",
      other: "Khác",
    } satisfies Record<AssetKind, string>,
    kind: "Loại",
    name: "Ghi chú",
    value: "Giá trị hiện nay",
    debts: "Khoản nợ",
    balance: "Dư nợ còn lại",
    goals: "Mục tiêu trung và dài hạn (theo giá hôm nay)",
    goalHint: "Không cần nhập nghỉ hưu: phần này tự tính từ chi tiêu khi nghỉ hưu và lương hưu.",
    goalName: "Mục tiêu",
    amount: "Số tiền",
    years: "Sau (năm)",
    essential: "Thiết yếu",
    add: "Thêm",
    remove: "Bỏ",
    planning: "Kế hoạch",
    risk: "Mức rủi ro của bạn",
    months: "Quỹ thanh khoản (số tháng chi tiêu)",
    run: "Lập bảng cân đối",
    privacy:
      "Mọi con số chỉ được tính trên trình duyệt này. SoiVí không gửi, không lưu và không công bố dữ liệu của bạn.",
    remember: "Lưu trên trình duyệt này để lần sau mở lại",
    download: "Tải file dữ liệu",
    open: "Mở file dữ liệu",
    clear: "Xoá dữ liệu",
    badFile: "File không đúng định dạng.",
    print: "In hoặc lưu PDF",
    // results
    sheet: "Bảng cân đối kinh tế",
    sheetHint:
      "Ngoài tài sản và nợ thông thường, bảng này tính cả giá trị hôm nay của thu nhập tương lai (vốn nhân lực), lương hưu, chi tiêu cả đời và các mục tiêu.",
    netWorth: "Giá trị ròng kinh tế",
    surplus: "Kế hoạch hiện tại đủ cho chi tiêu và mục tiêu, còn dư.",
    deficit: "Kế hoạch hiện tại chưa đủ cho chi tiêu và mục tiêu.",
    illiquidNote: (v: string) =>
      `Phần dư này chủ yếu nằm ở nhà đất và vốn kinh doanh (${v}), chỉ dùng được khi bán hoặc đổi sang nhà nhỏ hơn. Phần kế hoạch bên dưới chỉ dùng tài sản dễ bán và số tiền để dành hằng tháng.`,
    sideAssets: "Tài sản",
    sideLiabilities: "Nghĩa vụ",
    parts: {
      financial: "Tài sản tài chính và nhà đất",
      humanCapital: "Vốn nhân lực (thu nhập đến khi nghỉ hưu)",
      pension: "Lương hưu",
      debts: "Các khoản nợ",
      spendingToRetirement: "Chi tiêu đến khi nghỉ hưu",
      spendingInRetirement: "Chi tiêu khi nghỉ hưu",
      goals: "Các mục tiêu",
    } satisfies Record<Part, string>,
    total: "Tổng",
    share: "Tỷ trọng",
    ratios: "Chỉ số sức khoẻ tài chính",
    liquidity: "Quỹ dự phòng (tiền gửi)",
    liquidityOk: (m: string) => `${m} tháng chi tiêu`,
    liquidityRule: "Nên có ít nhất 6 tháng.",
    debtRatio: "Nợ trên tài sản",
    debtRatioRule: "Nên dưới 50%.",
    dsti: "Trả nợ trên thu nhập",
    dstiRule: "Nên dưới 40%.",
    savings: "Tỷ lệ để dành",
    savingsRule: "Nên từ 20% trở lên.",
    good: "Đạt",
    watch: "Cần chú ý",
    fixes: "Cách thu hẹp phần thiếu",
    fixMonthly: (v: string) => `Để dành thêm hoặc giảm chi khoảng ${v} mỗi tháng (theo giá hôm nay) đến khi nghỉ hưu.`,
    fixYears: (n: number) => `Hoặc làm việc thêm ${n} năm.`,
    fixNoYears: "Làm thêm đến 15 năm vẫn chưa đủ: hãy xem lại chi tiêu và mục tiêu.",
    fixInvest:
      "Bảng cân đối tính theo lãi suất phi rủi ro. Đầu tư phần tài sản tài chính với lợi nhuận cao hơn cũng giúp thu hẹp khoảng thiếu; phần kế hoạch bên dưới đo điều đó.",
    hc: {
      stable:
        "Thu nhập của bạn ổn định, giống một khoản trái phiếu. Phần tài sản tài chính có thể nghiêng về cổ phiếu hơn, trong giới hạn mức rủi ro bạn chọn.",
      average: "Thu nhập của bạn có rủi ro ở mức trung bình. Danh mục theo đúng mức rủi ro bạn chọn là phù hợp.",
      volatile:
        "Thu nhập của bạn biến động, giống cổ phiếu. Phần tài sản tài chính nên thận trọng hơn và quỹ dự phòng nên dày hơn, vì thu nhập và thị trường có thể cùng xấu một lúc.",
    } satisfies Record<Job, string>,
    hcShare: (p: string) => `Vốn nhân lực chiếm ${p} tổng tài sản kinh tế.`,
    plan: "Kế hoạch cho các mục tiêu",
    planHint: (v: string) =>
      `Tài sản dễ bán (${v}) được dùng trước cho quỹ thanh khoản, rồi cho từng mục tiêu. Nhà đang ở, bất động sản và vốn kinh doanh không được tính vào phần này.`,
    retirementGoal: "Nghỉ hưu",
    needed: "Cần hôm nay",
    funded: "Đã có",
    monthly: "Cần góp thêm mỗi tháng",
    priority: "Ưu tiên",
    aspirational: "Mong muốn",
    portfolio: "Danh mục",
    confidence: "Độ chắc chắn",
    none: "—",
    liquidityShort: (v: string) => `Quỹ thanh khoản còn thiếu ${v}: nên bù phần này trước.`,
    growthLeft: (v: string, name: string) => `Còn ${v} cho phần tăng trưởng dài hạn (${name}).`,
    compare: "Mỗi tháng",
    surplusMonthly: "Bạn để dành được",
    neededMonthly: "Các mục tiêu cần thêm",
    enough: "Số tiền để dành hiện nay đủ cho các mục tiêu.",
    notEnough: (v: string) =>
      `Còn thiếu ${v} mỗi tháng. Có thể giảm hoặc lùi mục tiêu mong muốn, tăng để dành, hoặc nghỉ hưu muộn hơn.`,
    noModels: "Chưa có danh mục mẫu được duyệt, nên chưa lập được kế hoạch cho các mục tiêu.",
    split: "Xem chi tiết phân bổ theo mục tiêu",
    quiz: "Chưa biết mức rủi ro? Làm bảng hỏi hồ sơ rủi ro",
    assumptions: (r: string, pi: string, v: string) =>
      `Giả định: lãi suất thực phi rủi ro ${r}/năm (lợi nhuận TPCP trừ lạm phát ${pi}, VNCMA ${v}). Không tính xác suất sống, thuế khi bán tài sản và chi phí giao dịch.`,
    prepared: (d: string) => `Lập ngày ${d} trên SoiVí. Chỉ để tham khảo, không phải lời khuyên đầu tư cho cá nhân bạn.`,
  },
  en: {
    general: "About you",
    age: "Age today",
    retire: "Planned retirement age",
    life: "Plan to age",
    lifeHint: "Choose above average life expectancy so the money does not run out early.",
    job: "Your income",
    jobs: {
      stable: "Stable (civil service, teaching, long-term contract)",
      average: "Average (company employee)",
      volatile: "Volatile (own business, commission, securities industry)",
    } satisfies Record<Job, string>,
    cash: "Income and spending (whole household)",
    income: "Net income a month",
    incomeHint: "After tax and social insurance.",
    bonus: "Bonus and 13th-month pay a year",
    growth: "Income growth above inflation (% a year)",
    spending: "Spending a month",
    retSpending: "Spending a month in retirement",
    retSpendingHint: "In today's money; often 70–80% of today.",
    pension: "Expected state pension a month",
    pensionHint: "In today's money. See the VssID app, or 0 if none.",
    debtPayment: "Debt payments a month (principal and interest)",
    assets: "Assets",
    kinds: {
      deposit: "Deposits, cash",
      bond: "Bonds, bond funds",
      stock: "Shares, equity funds",
      gold: "Gold",
      usd: "Foreign currency",
      home: "Home you live in",
      property: "Investment property",
      business: "Business stake",
      other: "Other",
    } satisfies Record<AssetKind, string>,
    kind: "Kind",
    name: "Note",
    value: "Value today",
    debts: "Debts",
    balance: "Balance owed",
    goals: "Medium and long-term goals (in today's money)",
    goalHint: "Leave out retirement: it is worked out from retirement spending and the pension.",
    goalName: "Goal",
    amount: "Amount",
    years: "In (years)",
    essential: "Essential",
    add: "Add",
    remove: "Remove",
    planning: "Plan",
    risk: "Your risk level",
    months: "Liquidity reserve (months of spending)",
    run: "Build my balance sheet",
    privacy: "Every number is worked out in this browser. SoiVí does not send, store or publish your data.",
    remember: "Keep it in this browser for next time",
    download: "Download data file",
    open: "Open data file",
    clear: "Clear data",
    badFile: "That file is not in the right format.",
    print: "Print or save as PDF",
    sheet: "Economic balance sheet",
    sheetHint:
      "Besides ordinary assets and debts, it counts today's value of future income (human capital), the pension, lifetime spending and your goals.",
    netWorth: "Economic net worth",
    surplus: "Your current plan covers your spending and goals, with room to spare.",
    deficit: "Your current plan does not yet cover your spending and goals.",
    illiquidNote: (v: string) =>
      `Most of this surplus is in property and business stakes (${v}), usable only by selling or moving somewhere smaller. The plan below uses only assets you can sell quickly and what you save each month.`,
    sideAssets: "Assets",
    sideLiabilities: "Obligations",
    parts: {
      financial: "Financial assets and property",
      humanCapital: "Human capital (income to retirement)",
      pension: "Pension",
      debts: "Debts",
      spendingToRetirement: "Spending to retirement",
      spendingInRetirement: "Spending in retirement",
      goals: "Goals",
    } satisfies Record<Part, string>,
    total: "Total",
    share: "Share",
    ratios: "Financial health",
    liquidity: "Emergency fund (deposits)",
    liquidityOk: (m: string) => `${m} months of spending`,
    liquidityRule: "Aim for at least 6 months.",
    debtRatio: "Debt to assets",
    debtRatioRule: "Aim below 50%.",
    dsti: "Debt payments to income",
    dstiRule: "Aim below 40%.",
    savings: "Savings rate",
    savingsRule: "Aim for 20% or more.",
    good: "On track",
    watch: "Watch",
    fixes: "Ways to close the gap",
    fixMonthly: (v: string) => `Save more or spend less by about ${v} a month (today's money) until retirement.`,
    fixYears: (n: number) => `Or work ${n} more years.`,
    fixNoYears: "Even 15 more years of work is not enough: review spending and goals.",
    fixInvest:
      "The balance sheet uses the risk-free rate. Investing financial assets for a higher return also narrows the gap; the plan below measures that.",
    hc: {
      stable:
        "Your income is steady, like a bond. Your financial assets can lean more towards shares, within the risk level you chose.",
      average: "Your income carries average risk. A portfolio at your chosen risk level fits.",
      volatile:
        "Your income swings, like shares. Keep your financial assets more cautious and the emergency fund larger, since income and markets can fall together.",
    } satisfies Record<Job, string>,
    hcShare: (p: string) => `Human capital is ${p} of your total economic assets.`,
    plan: "Plan for your goals",
    planHint: (v: string) =>
      `Assets you can sell quickly (${v}) go first to the liquidity reserve, then to each goal. Your home, property and business stake are not used here.`,
    retirementGoal: "Retirement",
    needed: "Needed today",
    funded: "Already have",
    monthly: "Extra needed a month",
    priority: "Priority",
    aspirational: "Aspirational",
    portfolio: "Portfolio",
    confidence: "Confidence",
    none: "—",
    liquidityShort: (v: string) => `The liquidity reserve is short by ${v}: fill it first.`,
    growthLeft: (v: string, name: string) => `${v} is left for long-term growth (${name}).`,
    compare: "Each month",
    surplusMonthly: "You save",
    neededMonthly: "Your goals need",
    enough: "What you save now is enough for your goals.",
    notEnough: (v: string) =>
      `${v} a month short. Trim or delay aspirational goals, save more, or retire later.`,
    noModels: "No model portfolios have been approved yet, so the goal plan cannot be built.",
    split: "See the full split by goal",
    quiz: "Not sure of your risk level? Take the risk questionnaire",
    assumptions: (r: string, pi: string, v: string) =>
      `Assumptions: real risk-free rate ${r} a year (government bond return less inflation ${pi}, VNCMA ${v}). Survival probabilities, tax on sales and trading costs are left out.`,
    prepared: (d: string) => `Prepared on ${d} with SoiVí. For reference only, not personal investment advice.`,
  },
};

const digits = (text: string, max = 15) => text.replace(/\D/g, "").slice(0, max);
const decimal = (text: string) => text.replace(/[^\d.,-]/g, "").replace(",", ".").slice(0, 5);
const fmt = (v: string, lang: Lang) => Number(v || 0).toLocaleString(lang === "vi" ? "vi-VN" : "en-US");
const percent = (v: number, lang: Lang, digitsAfter = 0) =>
  Number.isFinite(v)
    ? `${(100 * v).toLocaleString(lang === "vi" ? "vi-VN" : "en-US", { maximumFractionDigits: digitsAfter })}%`
    : "—";

type AssetRow = { kind: AssetKind; name: string; value: string };
type DebtRow = { name: string; balance: string };
type GoalRow = { name: string; amount: string; years: string; essential: boolean };
type Form = {
  age: string;
  retirementAge: string;
  lifeExpectancy: string;
  job: Job;
  monthlyIncome: string;
  annualBonus: string;
  incomeGrowth: string;
  monthlySpending: string;
  retirementSpending: string;
  monthlyPension: string;
  monthlyDebtPayment: string;
  assets: AssetRow[];
  debts: DebtRow[];
  goals: GoalRow[];
  level: string;
  months: string;
  history: Snapshot[]; // reviews kept for monitoring (step 8)
};

function example(lang: Lang): Form {
  const vi = lang === "vi";
  return {
    age: "38",
    retirementAge: "60",
    lifeExpectancy: "85",
    job: "average",
    monthlyIncome: "45000000",
    annualBonus: "60000000",
    incomeGrowth: "1",
    monthlySpending: "25000000",
    retirementSpending: "18000000",
    monthlyPension: "7000000",
    monthlyDebtPayment: "8000000",
    assets: [
      { kind: "deposit", name: vi ? "Tiết kiệm" : "Savings", value: "400000000" },
      { kind: "stock", name: vi ? "Quỹ cổ phiếu" : "Equity fund", value: "300000000" },
      { kind: "gold", name: "SJC", value: "150000000" },
      { kind: "home", name: vi ? "Căn hộ" : "Flat", value: "3500000000" },
    ],
    debts: [{ name: vi ? "Vay mua nhà" : "Mortgage", balance: "900000000" }],
    goals: [
      { name: vi ? "Học đại học cho con" : "Child's university", amount: "800000000", years: "10", essential: true },
      { name: vi ? "Đổi xe" : "New car", amount: "600000000", years: "5", essential: false },
    ],
    level: "3",
    months: "6",
    history: [],
  };
}

const num = (v: string, lo: number, hi: number, fallback = lo) => {
  const n = Number(v);
  return Number.isFinite(n) && v !== "" ? Math.min(hi, Math.max(lo, n)) : fallback;
};

function toProfile(f: Form): Profile {
  const age = num(f.age, 18, 90, 35);
  const retirementAge = num(f.retirementAge, age, 90, 60);
  return {
    age,
    retirementAge,
    lifeExpectancy: num(f.lifeExpectancy, retirementAge, 110, 85),
    monthlyIncome: num(f.monthlyIncome, 0, 1e13),
    annualBonus: num(f.annualBonus, 0, 1e14),
    incomeGrowth: num(f.incomeGrowth, -5, 10, 0),
    job: f.job,
    monthlySpending: num(f.monthlySpending, 0, 1e13),
    retirementSpending: num(f.retirementSpending, 0, 1e13),
    monthlyPension: num(f.monthlyPension, 0, 1e12),
    monthlyDebtPayment: num(f.monthlyDebtPayment, 0, 1e13),
    assets: f.assets.map((a) => ({ kind: a.kind, name: a.name, value: num(a.value, 0, 1e15) })),
    debts: f.debts.map((d) => ({ name: d.name, balance: num(d.balance, 0, 1e15) })),
    goals: f.goals
      .map((g) => ({ name: g.name.trim() || "—", amount: num(g.amount, 0, 1e15), years: num(g.years, 1, 50, 5), essential: g.essential }))
      .filter((g) => g.amount > 0),
  };
}

/** Accepts only the shape this page writes, so a stray or edited file cannot break it. */
function parseForm(raw: unknown): Form | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const s = (v: unknown) => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");
  const list = <T,>(v: unknown, f: (x: Record<string, unknown>) => T | null, max: number) =>
    Array.isArray(v) ? v.slice(0, max).map((x) => (x && typeof x === "object" ? f(x as Record<string, unknown>) : null)).filter((x): x is T => x !== null) : [];
  const job = JOBS.includes(o.job as Job) ? (o.job as Job) : "average";
  return {
    age: digits(s(o.age), 3),
    retirementAge: digits(s(o.retirementAge), 3),
    lifeExpectancy: digits(s(o.lifeExpectancy), 3),
    job,
    monthlyIncome: digits(s(o.monthlyIncome)),
    annualBonus: digits(s(o.annualBonus)),
    incomeGrowth: decimal(s(o.incomeGrowth)),
    monthlySpending: digits(s(o.monthlySpending)),
    retirementSpending: digits(s(o.retirementSpending)),
    monthlyPension: digits(s(o.monthlyPension)),
    monthlyDebtPayment: digits(s(o.monthlyDebtPayment)),
    assets: list(
      o.assets,
      (a) => (ASSET_KINDS.includes(a.kind as AssetKind) ? { kind: a.kind as AssetKind, name: s(a.name).slice(0, 40), value: digits(s(a.value)) } : null),
      20,
    ),
    debts: list(o.debts, (d) => ({ name: s(d.name).slice(0, 40), balance: digits(s(d.balance)) }), 10),
    goals: list(o.goals, (g) => ({ name: s(g.name).slice(0, 40), amount: digits(s(g.amount)), years: digits(s(g.years), 2), essential: g.essential === true }), 8),
    level: digits(s(o.level), 1) || "3",
    months: ["3", "6", "12", "18", "24"].includes(s(o.months)) ? s(o.months) : "6",
    history: parseHistory(o.history),
  };
}

type Result = { sheet: Sheet; plan: GoalPlan | null; date: string; profile: Profile; level: number };

export function BalanceSheet({
  lang,
  mixes,
  rates,
  release,
}: {
  lang: Lang;
  mixes: ModelMix[];
  rates: Rates;
  release: string;
}) {
  const x = TEXT[lang];
  const [form, setForm] = useState<Form>(() => example(lang));
  const [remember, setRemember] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [fileError, setFileError] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // Read a saved copy (only ever written when the visitor ticks "keep it"), and ?level= from the quiz.
  useEffect(() => {
    let saved: Form | null = null;
    try {
      const raw = window.localStorage.getItem(STORE);
      saved = raw ? parseForm(JSON.parse(raw)) : null;
    } catch {
      saved = null;
    }
    const given = Number(new URLSearchParams(window.location.search).get("level"));
    /* eslint-disable react-hooks/set-state-in-effect */
    if (saved) {
      setForm(given >= 1 && given <= 5 ? { ...saved, level: String(given) } : saved);
      setRemember(true);
    } else if (given >= 1 && given <= 5) {
      setForm((f) => ({ ...f, level: String(given) }));
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });
  const setRow = <K extends "assets" | "debts" | "goals">(key: K, i: number, patch: Partial<Form[K][number]>) =>
    set({ [key]: form[key].map((r, j) => (j === i ? { ...r, ...patch } : r)) } as Partial<Form>);
  const dropRow = (key: "assets" | "debts" | "goals", i: number) =>
    set({ [key]: (form[key] as unknown[]).filter((_, j) => j !== i) } as Partial<Form>);

  function save(next: Form, keep: boolean) {
    try {
      if (keep) window.localStorage.setItem(STORE, JSON.stringify(next));
      else window.localStorage.removeItem(STORE);
    } catch {
      // storage can be blocked (private window); the page works without it
    }
  }

  function run(event: React.FormEvent) {
    event.preventDefault();
    const profile = toProfile(form);
    const level = Math.min(Math.max(1, Number(form.level) || 3), Math.max(1, mixes.length));
    setResult({
      sheet: economicBalanceSheet(profile, rates),
      plan: mixes.length ? goalPlan(profile, rates, mixes, level, Number(form.months), x.retirementGoal) : null,
      date: new Date().toLocaleDateString(lang === "vi" ? "vi-VN" : "en-GB"),
      profile,
      level,
    });
    save(form, remember);
  }

  function download() {
    const blob = new Blob([JSON.stringify(form, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "soivi-bang-can-doi.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function openFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || file.size > 100_000) {
      setFileError(Boolean(file));
      return;
    }
    try {
      const parsed = parseForm(JSON.parse(await file.text()));
      setFileError(!parsed);
      if (parsed) {
        setForm(parsed);
        setResult(null);
      }
    } catch {
      setFileError(true);
    }
  }

  function clearAll() {
    save(form, false);
    setRemember(false);
    setForm({ ...example(lang), assets: [], debts: [], goals: [], history: [], monthlyIncome: "", annualBonus: "", monthlySpending: "", retirementSpending: "", monthlyPension: "", monthlyDebtPayment: "" });
    setResult(null);
  }

  const money = (key: keyof Form, label: string, hint?: string) => (
    <label className="sv-field">
      {label}
      <input inputMode="numeric" value={fmt(form[key] as string, lang)} onChange={(e) => set({ [key]: digits(e.target.value) } as Partial<Form>)} />
      {hint ? <span className="sv-field__hint">{hint}</span> : null}
    </label>
  );
  const small = (key: "age" | "retirementAge" | "lifeExpectancy", label: string, hint?: string) => (
    <label className="sv-field">
      {label}
      <input inputMode="numeric" value={form[key]} onChange={(e) => set({ [key]: digits(e.target.value, 3) })} />
      {hint ? <span className="sv-field__hint">{hint}</span> : null}
    </label>
  );

  return (
    <div className="space-y-8">
      <form onSubmit={run} className="no-print space-y-6">
        <p role="note" className="sv-note">
          <span>{x.privacy}</span>
        </p>

        <section className="sv-panel space-y-4">
          <h2 className="t-h3">{x.general}</h2>
          <div className="grid gap-4 md:grid-cols-4">
            {small("age", x.age)}
            {small("retirementAge", x.retire)}
            {small("lifeExpectancy", x.life, x.lifeHint)}
            <label className="sv-field">
              {x.job}
              <select value={form.job} onChange={(e) => set({ job: e.target.value as Job })}>
                {JOBS.map((j) => (
                  <option key={j} value={j}>
                    {x.jobs[j]}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <section className="sv-panel space-y-4">
          <h2 className="t-h3">{x.cash}</h2>
          <div className="grid gap-4 md:grid-cols-3">
            {money("monthlyIncome", x.income, x.incomeHint)}
            {money("annualBonus", x.bonus)}
            <label className="sv-field">
              {x.growth}
              <input inputMode="decimal" value={form.incomeGrowth} onChange={(e) => set({ incomeGrowth: decimal(e.target.value) })} />
            </label>
            {money("monthlySpending", x.spending)}
            {money("retirementSpending", x.retSpending, x.retSpendingHint)}
            {money("monthlyPension", x.pension, x.pensionHint)}
            {money("monthlyDebtPayment", x.debtPayment)}
          </div>
        </section>

        <section className="sv-panel space-y-3">
          <h2 className="t-h3">{x.assets}</h2>
          {form.assets.map((a, i) => (
            <div key={i} className="grid items-end gap-3 md:grid-cols-[1.6fr_1.4fr_1.4fr_auto]">
              <label className="sv-field">
                {x.kind}
                <select value={a.kind} onChange={(e) => setRow("assets", i, { kind: e.target.value as AssetKind })}>
                  {ASSET_KINDS.map((k) => (
                    <option key={k} value={k}>
                      {x.kinds[k]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="sv-field">
                {x.name}
                <input value={a.name} maxLength={40} onChange={(e) => setRow("assets", i, { name: e.target.value })} />
              </label>
              <label className="sv-field">
                {x.value}
                <input inputMode="numeric" value={fmt(a.value, lang)} onChange={(e) => setRow("assets", i, { value: digits(e.target.value) })} />
              </label>
              <button type="button" className="sv-btn sv-btn--secondary" onClick={() => dropRow("assets", i)}>
                {x.remove}
              </button>
            </div>
          ))}
          {form.assets.length < 20 ? (
            <button type="button" className="sv-btn sv-btn--secondary" onClick={() => set({ assets: [...form.assets, { kind: "deposit", name: "", value: "" }] })}>
              {x.add}
            </button>
          ) : null}
        </section>

        <section className="sv-panel space-y-3">
          <h2 className="t-h3">{x.debts}</h2>
          {form.debts.map((d, i) => (
            <div key={i} className="grid items-end gap-3 md:grid-cols-[3fr_1.4fr_auto]">
              <label className="sv-field">
                {x.name}
                <input value={d.name} maxLength={40} onChange={(e) => setRow("debts", i, { name: e.target.value })} />
              </label>
              <label className="sv-field">
                {x.balance}
                <input inputMode="numeric" value={fmt(d.balance, lang)} onChange={(e) => setRow("debts", i, { balance: digits(e.target.value) })} />
              </label>
              <button type="button" className="sv-btn sv-btn--secondary" onClick={() => dropRow("debts", i)}>
                {x.remove}
              </button>
            </div>
          ))}
          {form.debts.length < 10 ? (
            <button type="button" className="sv-btn sv-btn--secondary" onClick={() => set({ debts: [...form.debts, { name: "", balance: "" }] })}>
              {x.add}
            </button>
          ) : null}
        </section>

        <section className="sv-panel space-y-3">
          <h2 className="t-h3">{x.goals}</h2>
          <p className="t-small text-muted">{x.goalHint}</p>
          {form.goals.map((g, i) => (
            <div key={i} className="grid items-end gap-3 md:grid-cols-[2fr_1.5fr_0.7fr_auto_auto]">
              <label className="sv-field">
                {x.goalName}
                <input value={g.name} maxLength={40} onChange={(e) => setRow("goals", i, { name: e.target.value })} />
              </label>
              <label className="sv-field">
                {x.amount}
                <input inputMode="numeric" value={fmt(g.amount, lang)} onChange={(e) => setRow("goals", i, { amount: digits(e.target.value) })} />
              </label>
              <label className="sv-field">
                {x.years}
                <input inputMode="numeric" value={g.years} onChange={(e) => setRow("goals", i, { years: digits(e.target.value, 2) })} />
              </label>
              <label className="flex items-center gap-2 pb-2 t-small">
                <input type="checkbox" checked={g.essential} onChange={(e) => setRow("goals", i, { essential: e.target.checked })} />
                {x.essential}
              </label>
              <button type="button" className="sv-btn sv-btn--secondary" onClick={() => dropRow("goals", i)}>
                {x.remove}
              </button>
            </div>
          ))}
          {form.goals.length < 8 ? (
            <button
              type="button"
              className="sv-btn sv-btn--secondary"
              onClick={() => set({ goals: [...form.goals, { name: "", amount: "", years: "5", essential: false }] })}
            >
              {x.add}
            </button>
          ) : null}
        </section>

        {mixes.length ? (
          <section className="sv-panel space-y-4">
            <h2 className="t-h3">{x.planning}</h2>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="sv-field">
                {x.risk}
                <select value={form.level} onChange={(e) => set({ level: e.target.value })}>
                  {mixes.map((m, i) => (
                    <option key={m.id} value={i + 1}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="sv-field">
                {x.months}
                <select value={form.months} onChange={(e) => set({ months: e.target.value })}>
                  {["3", "6", "12", "18", "24"].map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <Link href={href(lang, "/ho-so-rui-ro")} className="t-small">
              {x.quiz}
            </Link>
          </section>
        ) : null}

        <div className="space-y-3">
          <button type="submit" className="sv-btn sv-btn--primary sv-btn--block">
            {x.run}
          </button>
          <label className="flex items-center gap-2 t-small">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => {
                setRemember(e.target.checked);
                save(form, e.target.checked);
              }}
            />
            {x.remember}
          </label>
          <div className="flex flex-wrap gap-3">
            <button type="button" className="sv-btn sv-btn--secondary" onClick={download}>
              {x.download}
            </button>
            <button type="button" className="sv-btn sv-btn--secondary" onClick={() => fileInput.current?.click()}>
              {x.open}
            </button>
            <input ref={fileInput} type="file" accept="application/json,.json" className="hidden" onChange={openFile} />
            <button type="button" className="sv-btn sv-btn--secondary" onClick={clearAll}>
              {x.clear}
            </button>
          </div>
          {fileError ? <p className="t-small text-danger">{x.badFile}</p> : null}
        </div>
      </form>

      {result ? <Report lang={lang} result={result} job={form.job} rates={rates} release={release} /> : null}
      {result ? (
        <Monitor
          lang={lang}
          release={release}
          profile={result.profile}
          sheet={result.sheet}
          plan={result.plan}
          level={result.level}
          history={form.history}
          kept={remember}
          onChange={(history) => {
            const next = { ...form, history };
            setForm(next);
            save(next, remember);
          }}
        />
      ) : null}
    </div>
  );
}

function Report({ lang, result, job, rates, release }: { lang: Lang; result: Result; job: Job; rates: Rates; release: string }) {
  const x = TEXT[lang];
  const { sheet: s, plan } = result;
  const money = (v: number) => vnd(Math.round(v), lang);
  const scale = Math.max(s.totalAssets, s.totalLiabilities) || 1;
  const value: Record<Part, number> = {
    financial: s.financial,
    humanCapital: s.humanCapital,
    pension: s.pension,
    debts: s.debts,
    spendingToRetirement: s.spendingToRetirement,
    spendingInRetirement: s.spendingInRetirement,
    goals: s.goals,
  };
  const bar = (label: string, parts: readonly Part[]) => (
    <div className="space-y-1">
      <p className="t-small font-semibold">{label}</p>
      <div
        className="mp-bar"
        role="img"
        aria-label={`${label}: ${parts.map((p) => `${x.parts[p]} ${money(value[p])}`).join(", ")}`}
      >
        {parts
          .filter((p) => value[p] > 0)
          .map((p) => (
            <span key={p} style={{ width: `${(100 * value[p]) / scale}%`, background: COLOUR[p] }} title={`${x.parts[p]}: ${money(value[p])}`} />
          ))}
      </div>
    </div>
  );
  const ratio = (label: string, shown: string, ok: boolean, rule: string) => (
    <div className="sv-panel space-y-1">
      <p className="t-small text-muted">{label}</p>
      <p className="t-h3 tabular-nums">{shown}</p>
      <p className="t-small">
        <b>{ok ? x.good : x.watch}</b> · <span className="text-muted">{rule}</span>
      </p>
    </div>
  );
  const months = s.ratios.liquidityMonths;
  const table = (side: string, parts: readonly Part[], total: number) => (
    <table className="sv-table">
      <thead>
        <tr>
          <th scope="col">{side}</th>
          <th scope="col" className="text-right">
            {x.value}
          </th>
          <th scope="col" className="text-right">
            {x.share}
          </th>
        </tr>
      </thead>
      <tbody>
        {parts.map((p) => (
          <tr key={p}>
            <th scope="row">
              <span className="mp-swatch" style={{ background: COLOUR[p] }} aria-hidden="true" /> {x.parts[p]}
            </th>
            <td className="text-right tabular-nums">{money(value[p])}</td>
            <td className="text-right tabular-nums">{percent(total > 0 ? value[p] / total : 0, lang)}</td>
          </tr>
        ))}
        <tr>
          <th scope="row">{x.total}</th>
          <td className="text-right tabular-nums font-semibold">{money(total)}</td>
          <td />
        </tr>
      </tbody>
    </table>
  );

  return (
    <section aria-live="polite" aria-labelledby="bs-title" className="space-y-8">
      <div className="space-y-2">
        <h2 id="bs-title" className="t-h2">
          {x.sheet}
        </h2>
        <p className="t-small text-muted">{x.sheetHint}</p>
      </div>

      <div className="sv-panel space-y-1">
        <p className="t-small text-muted">{x.netWorth}</p>
        <p className="t-h2 tabular-nums">{money(s.netWorth)}</p>
        <p>{s.netWorth >= 0 ? x.surplus : x.deficit}</p>
        {s.netWorth > 0 && s.illiquid > s.netWorth / 2 ? <p className="t-small text-muted">{x.illiquidNote(money(s.illiquid))}</p> : null}
      </div>

      <div className="space-y-3">
        {bar(x.sideAssets, ASSET_PARTS)}
        {bar(x.sideLiabilities, LIABILITY_PARTS)}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="sv-table-wrap" role="region" aria-label={x.sideAssets} tabIndex={0}>
          {table(x.sideAssets, ASSET_PARTS, s.totalAssets)}
        </div>
        <div className="sv-table-wrap" role="region" aria-label={x.sideLiabilities} tabIndex={0}>
          {table(x.sideLiabilities, LIABILITY_PARTS, s.totalLiabilities)}
        </div>
      </div>

      {s.netWorth < 0 ? (
        <div className="space-y-2">
          <h3 className="t-h3">{x.fixes}</h3>
          <ul className="list-disc space-y-1 pl-5">
            {Number.isFinite(s.fix.monthly) ? <li>{x.fixMonthly(money(s.fix.monthly))}</li> : null}
            <li>{s.fix.extraYears ? x.fixYears(s.fix.extraYears) : x.fixNoYears}</li>
            <li>{x.fixInvest}</li>
          </ul>
        </div>
      ) : null}

      <div className="space-y-2">
        <p>
          {x.hcShare(percent(s.totalAssets > 0 ? s.humanCapital / s.totalAssets : 0, lang))} {x.hc[job]}
        </p>
      </div>

      <div className="space-y-3">
        <h3 className="t-h3">{x.ratios}</h3>
        <div className="grid gap-4 md:grid-cols-4">
          {ratio(x.liquidity, Number.isFinite(months) ? x.liquidityOk(months.toLocaleString(lang === "vi" ? "vi-VN" : "en-US", { maximumFractionDigits: 1 })) : "—", months >= 6, x.liquidityRule)}
          {ratio(x.debtRatio, percent(s.ratios.debtToAssets, lang), s.ratios.debtToAssets < 0.5, x.debtRatioRule)}
          {ratio(x.dsti, percent(s.ratios.debtService, lang), s.ratios.debtService < 0.4, x.dstiRule)}
          {ratio(x.savings, percent(s.ratios.savingsRate, lang), s.ratios.savingsRate >= 0.2, x.savingsRule)}
        </div>
      </div>

      {plan ? <PlanView lang={lang} plan={plan} liquid={s.liquid} /> : <p className="sv-note">{x.noModels}</p>}

      <div className="space-y-1 border-t border-line pt-4 t-small text-muted">
        <p>{x.assumptions(percent(s.realRate / 100, lang, 2), percent(rates.inflation / 100, lang, 2), release)}</p>
        <p>{x.prepared(result.date)}</p>
      </div>
      <div className="no-print flex flex-wrap gap-4">
        <button type="button" className="sv-btn sv-btn--secondary" onClick={() => window.print()}>
          {x.print}
        </button>
        <Link href={href(lang, "/phan-bo-theo-muc-tieu")}>{x.split}</Link>
      </div>
    </section>
  );
}

function PlanView({ lang, plan, liquid }: { lang: Lang; plan: GoalPlan; liquid: number }) {
  const x = TEXT[lang];
  const money = (v: number) => vnd(Math.round(v), lang);
  const a = plan.allocation;
  const monthlyOf = new Map(plan.monthly.map((m) => [m.name, m.amount]));
  const gap = plan.monthlyTotal - plan.monthlySurplus;
  return (
    <div className="space-y-4">
      <h3 className="t-h3">{x.plan}</h3>
      <p className="t-small text-muted">{x.planHint(money(liquid))}</p>
      {a.liquidityShort > 0 ? (
        <p role="note" className="sv-note">
          {x.liquidityShort(money(a.liquidityShort))}
        </p>
      ) : null}
      <div className="sv-table-wrap" role="region" aria-label={x.plan} tabIndex={0}>
        <table className="sv-table min-w-[48rem]">
          <thead>
            <tr>
              <th scope="col">{x.goalName}</th>
              <th scope="col">{x.priority}</th>
              <th scope="col" className="text-right">
                {x.years}
              </th>
              <th scope="col">{x.portfolio}</th>
              <th scope="col" className="text-right">
                {x.confidence}
              </th>
              <th scope="col" className="text-right">
                {x.needed}
              </th>
              <th scope="col" className="text-right">
                {x.funded}
              </th>
              <th scope="col" className="text-right">
                {x.monthly}
              </th>
            </tr>
          </thead>
          <tbody>
            {a.goals.map((g) => (
              <tr key={`${g.goal.name}-${g.goal.years}`}>
                <th scope="row">{g.goal.name}</th>
                <td>{g.goal.essential ? x.essential : x.aspirational}</td>
                <td className="text-right tabular-nums">{g.goal.years}</td>
                <td>{g.portfolio.name}</td>
                <td className="text-right tabular-nums">{Math.round(g.confidence * 100)}%</td>
                <td className="text-right tabular-nums">{money(g.needed)}</td>
                <td className="text-right tabular-nums">{money(g.funded)}</td>
                <td className="text-right tabular-nums">{monthlyOf.has(g.goal.name) ? money(monthlyOf.get(g.goal.name) ?? 0) : x.none}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {a.growth > 0 ? <p>{x.growthLeft(money(a.growth), a.growthPortfolio.name)}</p> : null}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="sv-panel space-y-1">
          <p className="t-small text-muted">
            {x.compare} · {x.surplusMonthly}
          </p>
          <p className="t-h3 tabular-nums">{money(plan.monthlySurplus)}</p>
        </div>
        <div className="sv-panel space-y-1">
          <p className="t-small text-muted">
            {x.compare} · {x.neededMonthly}
          </p>
          <p className="t-h3 tabular-nums">{money(plan.monthlyTotal)}</p>
        </div>
      </div>
      <p className="font-semibold">{gap <= 0 ? x.enough : x.notEnough(money(gap))}</p>
      <p className="t-small text-muted">
        {CONFIDENCE.essential * 100}% / {CONFIDENCE.aspirational * 100}% ·{" "}
        {lang === "vi" ? "độ chắc chắn cho mục tiêu thiết yếu / mong muốn." : "confidence for essential / aspirational goals."}
      </p>
    </div>
  );
}
