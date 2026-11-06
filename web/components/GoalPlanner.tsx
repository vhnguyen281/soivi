"use client";

import { useState } from "react";

import { vnd, type Lang } from "@/lib/format";
import { nominalGoal, plan, TARGET_PROBABILITY, type GoalInput, type PortfolioInput, type PortfolioResult } from "@/lib/goals";

const TEXT = {
  vi: {
    title: "Bạn có bao nhiêu khả năng đạt mục tiêu?",
    goal: "Số tiền mục tiêu",
    today: "Theo giá hôm nay (tự cộng lạm phát)",
    years: "Sau bao nhiêu năm",
    savings: "Số tiền đang có",
    monthly: "Góp thêm mỗi tháng",
    growth: "Tăng số góp mỗi năm (%)",
    run: "Tính khả năng",
    busy: "Đang tính…",
    goalAt: (v: string, y: number) => `Mục tiêu tính theo tiền của năm thứ ${y}: ${v}`,
    chance: "Khả năng đạt mục tiêu",
    portfolio: "Danh mục mẫu",
    base: "Cơ sở",
    adverse: "Xấu",
    favourable: "Tốt",
    median: "Giá trị giữa",
    p10: "Trường hợp xấu (10%)",
    needed: `Cần góp/tháng để có ${Math.round(TARGET_PROBABILITY * 100)}% khả năng`,
    none: "đã đủ",
    picked: "gợi ý cho bạn",
    note: "Kết quả mô phỏng 4.000 kịch bản thị trường cho mỗi danh mục, dựa trên giả định VNCMA, trước thuế và phí. Mọi tính toán chạy trên máy của bạn; SoiVí không lưu các con số bạn nhập.",
  },
  en: {
    title: "How likely are you to reach your goal?",
    goal: "Goal amount",
    today: "In today's money (inflation added)",
    years: "In how many years",
    savings: "Savings today",
    monthly: "Added each month",
    growth: "Raise the monthly amount each year (%)",
    run: "Calculate",
    busy: "Calculating…",
    goalAt: (v: string, y: number) => `Goal in year-${y} money: ${v}`,
    chance: "Chance of reaching the goal",
    portfolio: "Model portfolio",
    base: "Base",
    adverse: "Adverse",
    favourable: "Favourable",
    median: "Middle outcome",
    p10: "Bad case (10%)",
    needed: `Monthly amount for a ${Math.round(TARGET_PROBABILITY * 100)}% chance`,
    none: "already met",
    picked: "suggested for you",
    note: "4,000 simulated market paths per portfolio on the VNCMA assumptions, before tax and fees. Everything runs on your device; SoiVí stores nothing you type.",
  },
};

function digits(text: string, max = 15): string {
  return text.replace(/\D/g, "").slice(0, max);
}

function percent(x: number, lang: Lang): string {
  return new Intl.NumberFormat(lang === "vi" ? "vi-VN" : "en-US", { style: "percent", maximumFractionDigits: 0 }).format(x);
}

function MoneyField({ label, value, onChange, lang }: { label: string; value: string; onChange: (v: string) => void; lang: Lang }) {
  return (
    <label className="sv-field">
      {label}
      <input
        inputMode="numeric"
        value={Number(value || 0).toLocaleString(lang === "vi" ? "vi-VN" : "en-US")}
        onChange={(e) => onChange(digits(e.target.value))}
      />
    </label>
  );
}

export function GoalPlanner({ lang, portfolios, inflation }: { lang: Lang; portfolios: PortfolioInput[]; inflation: number }) {
  const x = TEXT[lang];
  const [goal, setGoal] = useState("1000000000");
  const [years, setYears] = useState("10");
  const [savings, setSavings] = useState("100000000");
  const [monthly, setMonthly] = useState("5000000");
  const [growth, setGrowth] = useState("0");
  const [today, setToday] = useState(true);
  const [results, setResults] = useState<PortfolioResult[] | null>(null);
  const [input, setInput] = useState<GoalInput | null>(null);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<string | null>(null); // ?p= from the risk questionnaire

  function run(event: React.FormEvent) {
    event.preventDefault();
    const next: GoalInput = {
      goal: Number(goal || 0),
      years: Math.min(40, Math.max(1, Number(years || 1))),
      savings: Number(savings || 0),
      monthly: Number(monthly || 0),
      contributionGrowth: Math.min(20, Math.max(0, Number(growth || 0))),
      inTodaysMoney: today,
      inflation,
    };
    setPicked(new URLSearchParams(window.location.search).get("p"));
    setBusy(true);
    // Let the button show "busy" before the simulation (up to about a second) blocks the page.
    setTimeout(() => {
      setInput(next);
      setResults(plan(next, portfolios));
      setBusy(false);
    }, 20);
  }

  return (
    <section aria-labelledby="goal-title" className="sv-panel space-y-6">
      <form onSubmit={run} className="grid gap-4 md:grid-cols-3">
        <h2 id="goal-title" className="t-h3 md:col-span-3">
          {x.title}
        </h2>
        <MoneyField label={x.goal} value={goal} onChange={setGoal} lang={lang} />
        <label className="sv-field">
          {x.years}
          <input inputMode="numeric" value={years} onChange={(e) => setYears(digits(e.target.value, 2))} />
        </label>
        <label className="flex items-center gap-2 self-end t-small">
          <input type="checkbox" checked={today} onChange={(e) => setToday(e.target.checked)} />
          {x.today}
        </label>
        <MoneyField label={x.savings} value={savings} onChange={setSavings} lang={lang} />
        <MoneyField label={x.monthly} value={monthly} onChange={setMonthly} lang={lang} />
        <label className="sv-field">
          {x.growth}
          <input inputMode="numeric" value={growth} onChange={(e) => setGrowth(digits(e.target.value, 2))} />
        </label>
        <button type="submit" disabled={busy} className="sv-btn sv-btn--primary md:col-span-3">
          {busy ? x.busy : x.run}
        </button>
      </form>

      {results && input ? (
        <div className="space-y-4" aria-live="polite">
          <p className="t-small text-muted">{x.goalAt(vnd(Math.round(nominalGoal(input)), lang), input.years)}</p>
          <h3 className="t-h3">{x.chance}</h3>
          <ul className="space-y-3">
            {results.map((r) => (
              <li key={r.id} className="grid grid-cols-[10rem_1fr_3.5rem] items-center gap-3 max-sm:grid-cols-[1fr_3.5rem]">
                <span className="t-small font-semibold max-sm:col-span-2">
                  {r.name}
                  {r.id === picked ? <span className="sv-badge sv-badge--jade ml-2">{x.picked}</span> : null}
                </span>
                <span className="goal-track" aria-hidden="true">
                  <span className="goal-fill" style={{ width: `${Math.round(r.base.probability * 100)}%` }} />
                </span>
                <span className="text-right font-semibold tabular-nums">{percent(r.base.probability, lang)}</span>
              </li>
            ))}
          </ul>
          <div className="sv-table-wrap" role="region" aria-label={x.chance} tabIndex={0}>
            <table className="sv-table min-w-[48rem]">
              <thead>
                <tr>
                  <th scope="col">{x.portfolio}</th>
                  <th scope="col" className="text-right">{x.adverse}</th>
                  <th scope="col" className="text-right">{x.base}</th>
                  <th scope="col" className="text-right">{x.favourable}</th>
                  <th scope="col" className="text-right">{x.median}</th>
                  <th scope="col" className="text-right">{x.p10}</th>
                  <th scope="col" className="text-right">{x.needed}</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.id}>
                    <th scope="row">
                      {r.name}
                      {r.id === picked ? <span className="sv-badge sv-badge--jade ml-2">{x.picked}</span> : null}
                    </th>
                    <td className="text-right tabular-nums">{percent(r.adverse.probability, lang)}</td>
                    <td className="text-right font-semibold tabular-nums">{percent(r.base.probability, lang)}</td>
                    <td className="text-right tabular-nums">{percent(r.favourable.probability, lang)}</td>
                    <td className="text-right tabular-nums">{vnd(Math.round(r.base.median), lang)}</td>
                    <td className="text-right tabular-nums">{vnd(Math.round(r.base.p10), lang)}</td>
                    <td className="text-right tabular-nums">
                      {r.base.monthlyFor80 <= 0 ? x.none : vnd(Math.ceil(r.base.monthlyFor80 / 100_000) * 100_000, lang)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="t-small text-muted">{x.note}</p>
        </div>
      ) : null}
    </section>
  );
}
