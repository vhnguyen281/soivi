"use client";

import { useEffect, useState } from "react";

import { allocate, CONFIDENCE, type Allocation, type Goal, type ModelMix } from "@/lib/buckets";
import { pct, vnd, type Lang } from "@/lib/format";
import type { SavingsRank } from "@/lib/types";

// Fixed colour per asset class, as on /danh-muc-mau.
const SERIES: Record<string, string> = {
  cash_vnd: "var(--series-1)",
  gov_bond: "var(--series-2)",
  corp_bond: "var(--series-3)",
  eq_large: "var(--series-4)",
  eq_midsmall: "var(--series-5)",
  gold: "var(--series-6)",
  usd: "var(--series-7)",
};
const SHORT: Record<string, { vi: string; en: string }> = {
  cash_vnd: { vi: "Tiền gửi", en: "Deposits" },
  gov_bond: { vi: "TPCP", en: "Gov bonds" },
  corp_bond: { vi: "TPDN", en: "Corp bonds" },
  eq_large: { vi: "VN30", en: "VN30" },
  eq_midsmall: { vi: "Vừa & nhỏ", en: "Mid/small" },
  gold: { vi: "Vàng", en: "Gold" },
  usd: { vi: "USD", en: "USD" },
};

const TEXT = {
  vi: {
    you: "Tình hình của bạn",
    total: "Tổng số tiền đầu tư được",
    spending: "Chi tiêu mỗi tháng",
    months: "Quỹ thanh khoản (số tháng chi tiêu)",
    risk: "Mức rủi ro của bạn",
    goals: "Mục tiêu (theo giá hôm nay)",
    goalName: "Tên mục tiêu",
    amount: "Số tiền",
    years: "Sau (năm)",
    essential: "Thiết yếu",
    add: "Thêm mục tiêu",
    remove: "Bỏ",
    run: "Chia tài sản",
    parts: ["Thanh khoản", "Mục tiêu", "Tăng trưởng"],
    partHints: [
      "Chi tiêu dự phòng, để ở tiền gửi.",
      "Đủ để đạt từng mục tiêu với độ chắc chắn yêu cầu.",
      "Phần còn lại, đầu tư dài hạn theo mức rủi ro của bạn.",
    ],
    goalTable: "Từng mục tiêu",
    priority: "Ưu tiên",
    aspirational: "Mong muốn",
    portfolio: "Danh mục",
    confidence: "Độ chắc chắn",
    needed: "Cần hôm nay",
    funded: "Đã dành",
    ok: "đủ",
    short: (v: string) => `thiếu ${v}`,
    liquidityShort: (v: string) => `Chưa đủ quỹ thanh khoản: thiếu ${v}. Hãy ưu tiên phần này trước khi đầu tư.`,
    mix: "Toàn bộ tài sản theo lớp",
    banks: "Gợi ý gửi quỹ thanh khoản (12 tháng, lãi cao nhất đã kiểm tra)",
    rules: `Mục tiêu thiết yếu cần ${CONFIDENCE.essential * 100}% chắc chắn, mục tiêu mong muốn ${CONFIDENCE.aspirational * 100}%. Mục tiêu gần và thiết yếu dùng danh mục thận trọng hơn, không bao giờ rủi ro hơn mức của bạn. Thiếu tiền thì mục tiêu mong muốn nhường trước.`,
    note: "Tính trên máy của bạn; SoiVí không lưu con số nào. Để tham khảo, không phải lời khuyên đầu tư cho cá nhân bạn.",
  },
  en: {
    you: "Your situation",
    total: "Total money to invest",
    spending: "Monthly spending",
    months: "Liquidity reserve (months of spending)",
    risk: "Your risk level",
    goals: "Goals (in today's money)",
    goalName: "Goal",
    amount: "Amount",
    years: "In (years)",
    essential: "Essential",
    add: "Add a goal",
    remove: "Remove",
    run: "Split my money",
    parts: ["Liquidity", "Goals", "Growth"],
    partHints: [
      "Spending reserve, in deposits.",
      "Enough to reach each goal with the required confidence.",
      "The rest, invested long term at your risk level.",
    ],
    goalTable: "Each goal",
    priority: "Priority",
    aspirational: "Aspirational",
    portfolio: "Portfolio",
    confidence: "Confidence",
    needed: "Needed today",
    funded: "Set aside",
    ok: "covered",
    short: (v: string) => `short by ${v}`,
    liquidityShort: (v: string) => `The liquidity reserve is short by ${v}. Build it before investing.`,
    mix: "All your money by asset class",
    banks: "Where to keep the reserve (12 months, highest checked rates)",
    rules: `Essential goals need ${CONFIDENCE.essential * 100}% confidence, aspirational ${CONFIDENCE.aspirational * 100}%. Near and essential goals use more cautious portfolios, never riskier than your level. When money is short, aspirational goals give way first.`,
    note: "Calculated on your device; SoiVí stores nothing. For reference, not personal investment advice.",
  },
};

const digits = (text: string, max = 15) => text.replace(/\D/g, "").slice(0, max);
const fmt = (v: string, lang: Lang) => Number(v || 0).toLocaleString(lang === "vi" ? "vi-VN" : "en-US");

type GoalRow = { name: string; amount: string; years: string; essential: boolean };

export function BucketPlanner({
  lang,
  mixes,
  inflation,
  initialLevel,
}: {
  lang: Lang;
  mixes: ModelMix[];
  inflation: number;
  initialLevel: number;
}) {
  const x = TEXT[lang];
  const [total, setTotal] = useState("2000000000");
  const [spending, setSpending] = useState("20000000");
  const [months, setMonths] = useState("12");
  const [level, setLevel] = useState(String(initialLevel));
  const [goals, setGoals] = useState<GoalRow[]>([
    { name: lang === "vi" ? "Học phí cho con" : "Child's tuition", amount: "500000000", years: "6", essential: true },
    { name: lang === "vi" ? "Mua xe" : "Buy a car", amount: "300000000", years: "3", essential: false },
  ]);
  const [result, setResult] = useState<Allocation | null>(null);
  const [banks, setBanks] = useState<SavingsRank | null>(null);

  // ?level=1..5 from the risk questionnaire preselects the visitor's level (read after hydration).
  useEffect(() => {
    const given = Number(new URLSearchParams(window.location.search).get("level"));
    if (given >= 1 && given <= mixes.length) setLevel(String(given)); // eslint-disable-line react-hooks/set-state-in-effect
  }, [mixes.length]);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    const parsed: Goal[] = goals.map((g) => ({
      name: g.name.trim() || "—",
      amount: Number(g.amount || 0),
      years: Math.min(40, Math.max(1, Number(g.years || 1))),
      essential: g.essential,
    }));
    const a = allocate(
      {
        total: Number(total || 0),
        monthlySpending: Number(spending || 0),
        liquidityMonths: Number(months),
        goals: parsed,
        riskLevel: Number(level),
        inflation,
      },
      mixes,
    );
    setResult(a);
    setBanks(null);
    if (a.liquidity > 0) {
      try {
        const res = await fetch(`/api/savings/rank?amount=${Math.round(a.liquidity)}&term=12&channel=any`);
        if (res.ok) setBanks((await res.json()) as SavingsRank);
      } catch {
        // the suggestion is optional; the split above stands without it
      }
    }
  }

  const setGoal = (i: number, patch: Partial<GoalRow>) => setGoals(goals.map((g, j) => (j === i ? { ...g, ...patch } : g)));
  const total0 = result ? Number(total || 0) : 0;
  const share = (v: number) => (total0 > 0 ? `${Math.round((100 * v) / total0)}%` : "—");
  const fundedGoals = result ? result.goals.reduce((s, g) => s + g.funded, 0) : 0;

  return (
    <div className="space-y-8">
      <form onSubmit={run} className="sv-panel space-y-6">
        <h2 className="t-h3">{x.you}</h2>
        <div className="grid gap-4 md:grid-cols-4">
          <label className="sv-field">
            {x.total}
            <input inputMode="numeric" value={fmt(total, lang)} onChange={(e) => setTotal(digits(e.target.value))} />
          </label>
          <label className="sv-field">
            {x.spending}
            <input inputMode="numeric" value={fmt(spending, lang)} onChange={(e) => setSpending(digits(e.target.value))} />
          </label>
          <label className="sv-field">
            {x.months}
            <select value={months} onChange={(e) => setMonths(e.target.value)}>
              {["6", "12", "18", "24"].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="sv-field">
            {x.risk}
            <select value={level} onChange={(e) => setLevel(e.target.value)}>
              {mixes.map((m, i) => (
                <option key={m.id} value={i + 1}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <fieldset className="space-y-3">
          <legend className="font-semibold">{x.goals}</legend>
          {goals.map((g, i) => (
            <div key={i} className="grid items-end gap-3 md:grid-cols-[2fr_1.5fr_0.7fr_auto_auto]">
              <label className="sv-field">
                {x.goalName}
                <input value={g.name} maxLength={40} onChange={(e) => setGoal(i, { name: e.target.value })} />
              </label>
              <label className="sv-field">
                {x.amount}
                <input inputMode="numeric" value={fmt(g.amount, lang)} onChange={(e) => setGoal(i, { amount: digits(e.target.value) })} />
              </label>
              <label className="sv-field">
                {x.years}
                <input inputMode="numeric" value={g.years} onChange={(e) => setGoal(i, { years: digits(e.target.value, 2) })} />
              </label>
              <label className="flex items-center gap-2 pb-2 t-small">
                <input type="checkbox" checked={g.essential} onChange={(e) => setGoal(i, { essential: e.target.checked })} />
                {x.essential}
              </label>
              <button type="button" className="sv-btn sv-btn--secondary" onClick={() => setGoals(goals.filter((_, j) => j !== i))}>
                {x.remove}
              </button>
            </div>
          ))}
          {goals.length < 5 ? (
            <button
              type="button"
              className="sv-btn sv-btn--secondary"
              onClick={() => setGoals([...goals, { name: "", amount: "0", years: "5", essential: false }])}
            >
              {x.add}
            </button>
          ) : null}
        </fieldset>
        <button type="submit" className="sv-btn sv-btn--primary sv-btn--block">
          {x.run}
        </button>
        <p className="t-small text-muted">{x.rules}</p>
      </form>

      {result ? (
        <section aria-live="polite" className="space-y-6">
          {result.liquidityShort > 0 ? (
            <p role="note" className="sv-note">
              {x.liquidityShort(vnd(Math.round(result.liquidityShort), lang))}
            </p>
          ) : null}
          <div className="grid gap-4 md:grid-cols-3">
            {[result.liquidity, fundedGoals, result.growth].map((v, i) => (
              <div key={x.parts[i]} className="sv-panel space-y-1">
                <p className="t-small text-muted">{x.parts[i]}</p>
                <p className="t-h3 tabular-nums">{vnd(Math.round(v), lang)}</p>
                <p className="t-small text-muted">
                  {share(v)} · {i === 2 ? result.growthPortfolio.name : x.partHints[i]}
                </p>
              </div>
            ))}
          </div>

          {result.goals.length ? (
            <div className="space-y-2">
              <h3 className="t-h3">{x.goalTable}</h3>
              <div className="sv-table-wrap" role="region" aria-label={x.goalTable} tabIndex={0}>
                <table className="sv-table min-w-[48rem]">
                  <thead>
                    <tr>
                      <th scope="col">{x.goalName}</th>
                      <th scope="col">{x.priority}</th>
                      <th scope="col" className="text-right">{x.years}</th>
                      <th scope="col">{x.portfolio}</th>
                      <th scope="col" className="text-right">{x.confidence}</th>
                      <th scope="col" className="text-right">{x.needed}</th>
                      <th scope="col" className="text-right">{x.funded}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.goals.map((g) => (
                      <tr key={`${g.goal.name}-${g.goal.years}`}>
                        <th scope="row">{g.goal.name}</th>
                        <td>{g.goal.essential ? x.essential : x.aspirational}</td>
                        <td className="text-right tabular-nums">{g.goal.years}</td>
                        <td>{g.portfolio.name}</td>
                        <td className="text-right tabular-nums">{Math.round(g.confidence * 100)}%</td>
                        <td className="text-right tabular-nums">{vnd(Math.round(g.needed), lang)}</td>
                        <td className="text-right tabular-nums">
                          {vnd(Math.round(g.funded), lang)}{" "}
                          <span className="t-small text-muted">
                            ({g.funded >= g.needed - 1 ? x.ok : x.short(vnd(Math.round(g.needed - g.funded), lang))})
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <div className="space-y-3">
            <h3 className="t-h3">{x.mix}</h3>
            <div
              className="mp-bar"
              role="img"
              aria-label={result.mix.map((m) => `${SHORT[m.asset_class]?.[lang] ?? m.asset_class} ${Math.round(m.percent)}%`).join(", ")}
            >
              {result.mix
                .filter((m) => m.percent >= 0.5)
                .map((m) => (
                  <span
                    key={m.asset_class}
                    style={{ width: `${m.percent}%`, background: SERIES[m.asset_class] }}
                    title={`${SHORT[m.asset_class]?.[lang] ?? m.asset_class}: ${Math.round(m.percent)}%`}
                  />
                ))}
            </div>
            <ul className="flex flex-wrap gap-x-4 gap-y-1 t-small">
              {result.mix.map((m) => (
                <li key={m.asset_class}>
                  <span className="mp-swatch" style={{ background: SERIES[m.asset_class] }} aria-hidden="true" />{" "}
                  {SHORT[m.asset_class]?.[lang] ?? m.asset_class}{" "}
                  <b className="tabular-nums">{Math.round(m.percent)}%</b>{" "}
                  <span className="text-muted tabular-nums">({vnd(Math.round(m.amount), lang)})</span>
                </li>
              ))}
            </ul>
          </div>

          {banks && banks.results.length ? (
            <div className="space-y-2">
              <h3 className="t-h3">{x.banks}</h3>
              <ul className="space-y-1 t-small">
                {banks.results.slice(0, 3).map((r) => (
                  <li key={r.rate.id}>
                    <b>{r.rate.institution.short_name}</b> · {pct(r.rate.rate_pct, lang)} · {r.rate.product_name}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <p className="t-small text-muted">{x.note}</p>
        </section>
      ) : null}
    </div>
  );
}
