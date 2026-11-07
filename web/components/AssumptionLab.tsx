"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { CLASS_NAMES } from "@/lib/classes";
import {
  bands,
  baseStockBond,
  chance,
  histogram,
  percentile,
  sensitivity,
  weightsFromAssets,
  hundred,
  LAB_CLASSES,
  NO_SHOCK,
  scenarioCorr,
  scenarioReturns,
  scenarioVols,
  simulate,
  type LabBase,
  type Sensitivity,
  type Shocks,
} from "@/lib/cmaLab";
import { pct, vnd, vndShort, type Lang } from "@/lib/format";

export type LabPortfolio = { id: string; name: string; weights: Record<string, number> };

const PATHS = 1500;
const SEED = 2027;

type Preset = { id: string; vi: string; en: string; shocks: Partial<Shocks> };
const PRESETS: Preset[] = [
  { id: "base", vi: "Gốc VNCMA", en: "VNCMA base", shocks: {} },
  { id: "infl", vi: "Lạm phát cao", en: "High inflation", shocks: { inflation: 3, real: -1 } },
  { id: "slow", vi: "Tăng trưởng chậm", en: "Slow growth", shocks: { growth: -2, pe: -0.15 } },
  { id: "pe", vi: "Định giá co lại", en: "Valuations shrink", shocks: { pe: -0.3 } },
  { id: "vol", vi: "Biến động mạnh", en: "Rough markets", shocks: { volScale: 1.5, stockBond: 0.5 } },
  { id: "crash", vi: "Sụp đổ năm đầu", en: "Early crash", shocks: { crash: true } },
  { id: "bad", vi: "Gần kịch bản xấu VNCMA", en: "Near VNCMA adverse", shocks: { growth: -1, pe: -0.07 } },
  { id: "good", vi: "Gần kịch bản tốt VNCMA", en: "Near VNCMA favourable", shocks: { growth: 1, pe: 0.1 } },
];

const TEXT = {
  vi: {
    you: "Kế hoạch thử",
    portfolio: "Danh mục mẫu",
    initial: "Số tiền ban đầu",
    monthly: "Góp mỗi tháng (giá hôm nay)",
    years: (n: number) => `Thời gian: ${n} năm`,
    goal: "Mục tiêu (giá hôm nay)",
    drivers: "Các giả định lớn",
    presets: "Kịch bản có sẵn",
    inflation: "Lạm phát",
    growth: "Tăng trưởng GDP thực",
    real: "Lãi suất thực",
    pe: "P/E cổ phiếu cuối kỳ so với dự kiến",
    vol: "Biến động cổ phiếu",
    sb: "Tương quan cổ phiếu – trái phiếu",
    sbBase: "theo VNCMA",
    crash: "Cổ phiếu giảm 40% trong năm đầu",
    shrunk: "Ma trận tương quan đã được điều chỉnh nhẹ để còn hợp lệ.",
    chance: "Khả năng đạt mục tiêu",
    base: "gốc",
    median: "Kết quả trung vị",
    bad: "Kịch bản xấu (1 trên 10)",
    fan: "Tài sản theo thời gian (giá hôm nay)",
    legendScen: ["Kịch bản: trung vị", "50% ở giữa", "80% ở giữa"],
    legendBase: ["Gốc VNCMA: trung vị", "Gốc: 80% ở giữa"],
    goalLine: "Mục tiêu",
    year: (y: number) => `Năm ${y}`,
    dots: "100 tương lai có thể xảy ra",
    dotsNote: (n: number, b: number) => `${n} trên 100 tương lai đạt mục tiêu (gốc VNCMA: ${b}). Mỗi chấm là một phần trăm khả năng.`,
    reach: "Đạt mục tiêu",
    miss: "Chưa đạt",
    table: "Lợi nhuận kỳ vọng mỗi lớp (%/năm)",
    cls: "Lớp tài sản",
    weight: "Tỷ trọng",
    baseCol: "Gốc VNCMA",
    scenCol: "Kịch bản",
    volCol: "Biến động",
    reset: "Về gốc",
    mine: "Danh mục của tôi (từ bảng cân đối)",
    custom: "Tự nhập tỷ trọng",
    mineNote: "Lấy từ tài sản dễ bán trong bảng cân đối đã lưu trên trình duyệt này. Trái phiếu tính là TPCP, cổ phiếu tính là VN30.",
    customSum: (n: number) => `Tổng ${n}%. Tỷ trọng được chia lại cho đủ 100%.`,
    tornado: "Giả định nào quan trọng nhất với kế hoạch này?",
    tornadoNote: (now: number) => `Mỗi thanh: khả năng đạt mục tiêu khi giả định dịch một bậc xuống (trái) hoặc lên (phải) từ kịch bản hiện tại (${now}%).`,
    computing: "Đang tính…",
    worse: "Thấp hơn",
    better: "Cao hơn",
    drivers2: {
      inflation: ["Lạm phát", "−1", "+1"],
      growth: ["Tăng trưởng GDP", "−1", "+1"],
      real: ["Lãi suất thực", "−0,5", "+0,5"],
      pe: ["P/E cuối kỳ", "−15%", "+15%"],
      vol: ["Biến động cổ phiếu", "×0,8", "×1,25"],
      stockBond: ["Tương quan CP–TP", "−0,3", "+0,3"],
      crash: ["Sụp đổ năm đầu", "", "có"],
    } as Record<string, [string, string, string]>,
    dist: "Lợi nhuận từng năm của danh mục",
    distNote: "Mỗi cột là tỷ lệ các năm mô phỏng có lợi nhuận trong khoảng đó (danh nghĩa).",
    lossYear: (s: number, b: number) => `Xác suất một năm bị lỗ: ${s}% (gốc ${b}%)`,
    badYear: (s: string, b: string) => `Năm xấu (1 trên 20): ${s} (gốc ${b})`,
    note: (v: string) =>
      `Gốc là bản VNCMA ${v} đã được duyệt. Kịch bản của bạn chỉ tính trên trình duyệt này, không được lưu hay công bố. Đây là thử nghiệm giả định, không phải dự báo hay lời khuyên đầu tư.`,
    method: `${PATHS.toLocaleString("vi-VN")} kịch bản theo tháng, lợi nhuận từng lớp tài sản có tương quan, tái cân bằng hằng tháng; gốc và kịch bản dùng chung một chuỗi số ngẫu nhiên nên khác biệt chỉ đến từ giả định.`,
  },
  en: {
    you: "Your test plan",
    portfolio: "Model portfolio",
    initial: "Starting amount",
    monthly: "Monthly saving (today's money)",
    years: (n: number) => `Horizon: ${n} years`,
    goal: "Goal (today's money)",
    drivers: "The big assumptions",
    presets: "Ready-made scenarios",
    inflation: "Inflation",
    growth: "Real GDP growth",
    real: "Real interest rate",
    pe: "Equity P/E at the end vs expected",
    vol: "Equity volatility",
    sb: "Stock–bond correlation",
    sbBase: "as VNCMA",
    crash: "Shares fall 40% in the first year",
    shrunk: "The correlation matrix was nudged to stay valid.",
    chance: "Chance of reaching the goal",
    base: "base",
    median: "Median outcome",
    bad: "Bad case (1 in 10)",
    fan: "Wealth over time (today's money)",
    legendScen: ["Scenario: median", "middle 50%", "middle 80%"],
    legendBase: ["VNCMA base: median", "Base: middle 80%"],
    goalLine: "Goal",
    year: (y: number) => `Year ${y}`,
    dots: "100 possible futures",
    dotsNote: (n: number, b: number) => `${n} in 100 futures reach the goal (VNCMA base: ${b}). Each dot is one percent of chance.`,
    reach: "Reaches the goal",
    miss: "Falls short",
    table: "Expected return by class (% a year)",
    cls: "Asset class",
    weight: "Weight",
    baseCol: "VNCMA base",
    scenCol: "Scenario",
    volCol: "Volatility",
    reset: "Back to base",
    mine: "My portfolio (from the balance sheet)",
    custom: "Enter my own weights",
    mineNote: "Taken from the liquid assets in the balance sheet saved in this browser. Bonds count as government bonds, shares as VN30.",
    customSum: (n: number) => `Total ${n}%. Weights are rescaled to 100%.`,
    tornado: "Which assumption matters most for this plan?",
    tornadoNote: (now: number) => `Each bar: the chance of the goal when the assumption moves one step down (left) or up (right) from the current scenario (${now}%).`,
    computing: "Working…",
    worse: "Lower",
    better: "Higher",
    drivers2: {
      inflation: ["Inflation", "−1", "+1"],
      growth: ["GDP growth", "−1", "+1"],
      real: ["Real rate", "−0.5", "+0.5"],
      pe: ["End P/E", "−15%", "+15%"],
      vol: ["Equity volatility", "×0.8", "×1.25"],
      stockBond: ["Stock–bond corr.", "−0.3", "+0.3"],
      crash: ["Early crash", "", "on"],
    } as Record<string, [string, string, string]>,
    dist: "The portfolio's yearly returns",
    distNote: "Each bar is the share of simulated years with a return in that range (nominal).",
    lossYear: (s: number, b: number) => `Chance of a losing year: ${s}% (base ${b}%)`,
    badYear: (s: string, b: string) => `Bad year (1 in 20): ${s} (base ${b})`,
    note: (v: string) =>
      `The base is the approved VNCMA ${v}. Your scenario is worked out in this browser only, never stored or published. This is an assumption test, not a forecast or investment advice.`,
    method: `${PATHS.toLocaleString("en-US")} monthly paths, correlated returns per asset class, rebalanced monthly; base and scenario share the same random draws, so differences come only from the assumptions.`,
  },
};

const digits = (s: string) => Number(s.replace(/\D/g, "").slice(0, 13)) || 0;

export function AssumptionLab({ lang, base, portfolios, release }: { lang: Lang; base: LabBase; portfolios: LabPortfolio[]; release: string }) {
  const x = TEXT[lang];
  const nf = (v: number) => v.toLocaleString(lang === "vi" ? "vi-VN" : "en-US");
  const [pid, setPid] = useState(portfolios[Math.min(2, portfolios.length - 1)]?.id ?? "");
  const [initial, setInitial] = useState(1_000_000_000);
  const [monthly, setMonthly] = useState(10_000_000);
  const [years, setYears] = useState(10);
  const [goal, setGoal] = useState(3_000_000_000);
  const [shocks, setShocks] = useState<Shocks>(NO_SHOCK);
  const set = (patch: Partial<Shocks>) => setShocks({ ...shocks, ...patch });

  const [mine, setMine] = useState<{ weights: Record<string, number>; initial: number; monthly: number } | null>(null);
  const [custom, setCustom] = useState<Record<string, number>>(() => ({ ...(portfolios[Math.min(2, portfolios.length - 1)]?.weights ?? {}) }));

  // The balance sheet, if the visitor chose to keep it in this browser (nothing is sent anywhere).
  useEffect(() => {
    try {
      const raw = JSON.parse(window.localStorage.getItem("soivi.balance.v1") ?? "null");
      if (!raw || !Array.isArray(raw.assets)) return;
      const assets = raw.assets.map((a: { kind?: unknown; value?: unknown }) => ({ kind: String(a.kind), value: Number(a.value) || 0 }));
      const w = weightsFromAssets(assets);
      if (!w) return;
      const liquid = assets.filter((a: { kind: string }) => ["deposit", "bond", "stock", "gold", "usd"].includes(a.kind)).reduce((t: number, a: { value: number }) => t + a.value, 0);
      const num = (k: string) => Number(raw[k]) || 0;
      const surplus = num("monthlyIncome") + num("annualBonus") / 12 - num("monthlySpending") - num("monthlyDebtPayment");
      setMine({ weights: w, initial: liquid, monthly: Math.max(0, Math.round(surplus)) }); // eslint-disable-line react-hooks/set-state-in-effect
    } catch {
      // nothing saved, or storage blocked
    }
  }, []);

  const portfolio = portfolios.find((p) => p.id === pid) ?? portfolios[0];
  const customTotal = LAB_CLASSES.reduce((t, c) => t + (custom[c] ?? 0), 0);
  const weights = useMemo(() => {
    const chosen = pid === "mine" && mine ? mine.weights : pid === "custom" ? custom : (portfolio?.weights ?? {});
    const raw = LAB_CLASSES.map((c) => Math.max(0, chosen[c] ?? 0));
    const total = raw.reduce((a, b) => a + b, 0) || 1;
    return raw.map((v) => v / total);
  }, [pid, mine, custom, portfolio]);
  const pick = (id: string) => {
    setPid(id);
    if (id === "mine" && mine) {
      setInitial(mine.initial);
      if (mine.monthly > 0) setMonthly(mine.monthly);
    }
  };
  const planNow = useMemo(() => ({ weights, initial, monthly, years, paths: PATHS, seed: SEED }), [weights, initial, monthly, years]);
  const plan = useDeferredValue(planNow);
  const deferred = useDeferredValue(shocks);

  const baseSim = useMemo(
    () => simulate(plan, scenarioReturns(base, NO_SHOCK), scenarioVols(base, NO_SHOCK), scenarioCorr(base, NO_SHOCK).chol, base.inflation, false),
    [base, plan],
  );
  const corr = useMemo(() => scenarioCorr(base, deferred), [base, deferred]);
  const rets = useMemo(() => scenarioReturns(base, deferred), [base, deferred]);
  const vols = useMemo(() => scenarioVols(base, deferred), [base, deferred]);
  const sim = useMemo(() => simulate(plan, rets, vols, corr.chol, base.inflation + deferred.inflation, deferred.crash), [plan, rets, vols, corr, base, deferred]);

  const bandS = useMemo(() => bands(sim, plan.years), [sim, plan.years]);
  const bandB = useMemo(() => bands(baseSim, plan.years), [baseSim, plan.years]);
  const pS = chance(sim.finals, goal);
  const pB = chance(baseSim.finals, goal);
  const dotsS = useMemo(() => hundred(sim.finals), [sim]);
  const baseRets = scenarioReturns(base, NO_SHOCK);

  // Sensitivity needs 13 runs, so it waits until the sliders rest, on fewer paths.
  const [sens, setSens] = useState<{ now: number; rows: Sensitivity[]; key: string } | null>(null);
  const sensKey = JSON.stringify([shocks, planNow, goal]);
  useEffect(() => {
    const id = window.setTimeout(() => {
      const r = sensitivity(base, shocks, { ...planNow, paths: 500 }, goal);
      setSens({ ...r, key: sensKey });
    }, 500);
    return () => window.clearTimeout(id);
  }, [base, shocks, planNow, goal, sensKey]);
  const stale = !sens || sens.key !== sensKey;

  const dist = useMemo(() => {
    const lo = -40;
    const hi = 50;
    const bins = 18;
    const norm = (h: number[], n: number) => h.map((c) => c / Math.max(1, n));
    const sorted = (a: Float64Array) => Array.from(a).sort((p, q) => p - q);
    const sS = sorted(sim.yearReturns);
    const sB = sorted(baseSim.yearReturns);
    return {
      lo,
      hi,
      scen: norm(histogram(sim.yearReturns, bins, lo, hi), sim.yearReturns.length),
      base: norm(histogram(baseSim.yearReturns, bins, lo, hi), baseSim.yearReturns.length),
      lossS: sS.filter((v) => v < 0).length / Math.max(1, sS.length),
      lossB: sB.filter((v) => v < 0).length / Math.max(1, sB.length),
      p5S: percentile(sS, 0.05),
      p5B: percentile(sB, 0.05),
    };
  }, [sim, baseSim]);
  const active = PRESETS.find((p) => JSON.stringify({ ...NO_SHOCK, ...p.shocks }) === JSON.stringify(shocks))?.id;
  const signed = (v: number, unit: string) => `${v > 0 ? "+" : ""}${nf(Math.round(v * 100) / 100)}${unit}`;
  const pp = lang === "vi" ? " điểm %" : " pp";

  return (
    <div className="grid gap-8 lg:grid-cols-[22rem_1fr] lg:items-start">
      <aside className="space-y-6">
        <section className="sv-panel space-y-4" aria-labelledby="lab-plan">
          <h2 id="lab-plan" className="t-h3">
            {x.you}
          </h2>
          <label className="sv-field">
            {x.portfolio}
            <select value={pid} onChange={(e) => pick(e.target.value)}>
              {portfolios.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
              {mine ? <option value="mine">{x.mine}</option> : null}
              <option value="custom">{x.custom}</option>
            </select>
          </label>
          {pid === "mine" ? <p className="t-caption text-muted">{x.mineNote}</p> : null}
          {pid === "custom" ? (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                {LAB_CLASSES.map((c) => (
                  <label key={c} className="sv-field !text-[13px]">
                    {CLASS_NAMES[c][lang]}
                    <input
                      inputMode="numeric"
                      value={String(custom[c] ?? 0)}
                      onChange={(e) => setCustom({ ...custom, [c]: Math.min(100, Number(e.target.value.replace(/\D/g, "")) || 0) })}
                    />
                  </label>
                ))}
              </div>
              {customTotal !== 100 ? <p className="t-caption text-muted">{x.customSum(customTotal)}</p> : null}
            </div>
          ) : null}
          <label className="sv-field">
            {x.initial}
            <input inputMode="numeric" value={nf(initial)} onChange={(e) => setInitial(digits(e.target.value))} />
          </label>
          <label className="sv-field">
            {x.monthly}
            <input inputMode="numeric" value={nf(monthly)} onChange={(e) => setMonthly(digits(e.target.value))} />
          </label>
          <label className="sv-field">
            {x.goal}
            <input inputMode="numeric" value={nf(goal)} onChange={(e) => setGoal(digits(e.target.value))} />
          </label>
          <label className="sv-field">
            {x.years(years)}
            <input type="range" min={3} max={30} value={years} onChange={(e) => setYears(+e.target.value)} className="accent-[var(--ink)]" />
          </label>
        </section>

        <section className="sv-panel space-y-4" aria-labelledby="lab-drivers">
          <div className="flex items-center justify-between gap-3">
            <h2 id="lab-drivers" className="t-h3">
              {x.drivers}
            </h2>
            <button type="button" className="sv-btn sv-btn--secondary !min-h-9 !px-4 t-small" onClick={() => setShocks(NO_SHOCK)}>
              {x.reset}
            </button>
          </div>
          <div>
            <p className="t-small text-muted">{x.presets}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  aria-pressed={active === p.id}
                  className={`rounded-full border px-3 py-1.5 t-small font-semibold ${active === p.id ? "border-ink bg-ink text-surface" : "border-line bg-surface"}`}
                  onClick={() => setShocks({ ...NO_SHOCK, ...p.shocks })}
                >
                  {p[lang]}
                </button>
              ))}
            </div>
          </div>
          <Slider label={x.inflation} value={shocks.inflation} min={-2} max={5} step={0.5} show={`${pct(base.inflation + shocks.inflation, lang)} (${signed(shocks.inflation, pp)})`} onChange={(v) => set({ inflation: v })} />
          <Slider label={x.growth} value={shocks.growth} min={-3} max={2} step={0.5} show={signed(shocks.growth, pp)} onChange={(v) => set({ growth: v })} />
          <Slider label={x.real} value={shocks.real} min={-2} max={2} step={0.25} show={signed(shocks.real, pp)} onChange={(v) => set({ real: v })} />
          <Slider label={x.pe} value={shocks.pe * 100} min={-40} max={40} step={5} show={signed(shocks.pe * 100, "%")} onChange={(v) => set({ pe: v / 100 })} />
          <Slider label={x.vol} value={shocks.volScale} min={0.6} max={1.8} step={0.1} show={`×${nf(shocks.volScale)}`} onChange={(v) => set({ volScale: v })} />
          <Slider
            label={x.sb}
            value={Math.round((shocks.stockBond ?? baseStockBond(base)) * 10) / 10}
            min={-0.5}
            max={0.8}
            step={0.1}
            show={shocks.stockBond === null ? x.sbBase : nf(shocks.stockBond)}
            onChange={(v) => set({ stockBond: v })}
          />
          <label className="flex items-center gap-2 t-small font-semibold">
            <input type="checkbox" checked={shocks.crash} onChange={(e) => set({ crash: e.target.checked })} className="h-5 w-5 accent-[var(--ink)]" />
            {x.crash}
          </label>
          {corr.shrunk > 0 ? <p className="t-caption text-muted">{x.shrunk}</p> : null}
        </section>
      </aside>

      <div className="min-w-0 space-y-8">
        <div className="grid gap-4 sm:grid-cols-3" aria-live="polite">
          <Stat label={x.chance} value={`${Math.round(pS * 100)}%`} base={`${x.base} ${Math.round(pB * 100)}%`} />
          <Stat label={x.median} value={vndShort(Math.round(bandS[plan.years].p50), lang)} base={`${x.base} ${vndShort(Math.round(bandB[plan.years].p50), lang)}`} />
          <Stat label={x.bad} value={vndShort(Math.round(bandS[plan.years].p10), lang)} base={`${x.base} ${vndShort(Math.round(bandB[plan.years].p10), lang)}`} />
        </div>

        <section className="sv-panel space-y-3" aria-labelledby="lab-fan">
          <h2 id="lab-fan" className="t-h3">
            {x.fan}
          </h2>
          <Legend x={x} />
          <Fan scen={bandS} base={bandB} goal={goal} lang={lang} x={x} />
        </section>

        <section className="sv-panel space-y-3" aria-labelledby="lab-dots">
          <h2 id="lab-dots" className="t-h3">
            {x.dots}
          </h2>
          <p className="t-small">{x.dotsNote(Math.round(pS * 100), Math.round(pB * 100))}</p>
          <Dots dots={dotsS} goal={goal} lang={lang} x={x} />
        </section>

        <section className="sv-panel space-y-3" aria-labelledby="lab-tornado">
          <h2 id="lab-tornado" className="t-h3">
            {x.tornado}
          </h2>
          {sens ? (
            <>
              <p className="t-small">{x.tornadoNote(Math.round(sens.now * 100))}</p>
              <Tornado sens={sens} labels={x.drivers2} x={x} stale={stale} />
            </>
          ) : (
            <p className="t-small text-muted">{x.computing}</p>
          )}
        </section>

        <section className="sv-panel space-y-3" aria-labelledby="lab-dist">
          <h2 id="lab-dist" className="t-h3">
            {x.dist}
          </h2>
          <p className="t-small">{x.distNote}</p>
          <Histo lo={dist.lo} hi={dist.hi} rows={[[x.scenCol, dist.scen, "var(--series-1)"], [x.baseCol, dist.base, "var(--line-strong)"]]} lang={lang} />
          <ul className="space-y-1 t-small">
            <li>{x.lossYear(Math.round(dist.lossS * 100), Math.round(dist.lossB * 100))}</li>
            <li>{x.badYear(pct(Math.round(dist.p5S * 10) / 10, lang), pct(Math.round(dist.p5B * 10) / 10, lang))}</li>
          </ul>
        </section>

        <section className="space-y-2" aria-labelledby="lab-table">
          <h2 id="lab-table" className="t-h3">
            {x.table}
          </h2>
          <div className="sv-table-wrap" role="region" aria-labelledby="lab-table" tabIndex={0}>
            <table className="sv-table min-w-[36rem]">
              <thead>
                <tr>
                  <th scope="col">{x.cls}</th>
                  <th scope="col" className="sv-num">{x.weight}</th>
                  <th scope="col" className="sv-num">{x.baseCol}</th>
                  <th scope="col" className="sv-num">{x.scenCol}</th>
                  <th scope="col" className="sv-num">{x.volCol}</th>
                </tr>
              </thead>
              <tbody>
                {LAB_CLASSES.map((c, i) => {
                  const moved = Math.abs(rets[i] - baseRets[i]) > 0.005;
                  return (
                    <tr key={c}>
                      <th scope="row">{CLASS_NAMES[c][lang]}</th>
                      <td className="sv-num">{Math.round(weights[i] * 100)}%</td>
                      <td className="sv-num">{pct(Math.round(baseRets[i] * 100) / 100, lang)}</td>
                      <td className={`sv-num ${moved ? "font-bold" : ""}`}>
                        {pct(Math.round(rets[i] * 100) / 100, lang)}
                        {moved ? <span className="t-caption text-muted"> ({signed(rets[i] - baseRets[i], "")})</span> : null}
                      </td>
                      <td className="sv-num">{pct(Math.round(vols[i] * 10) / 10, lang)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
        <div className="space-y-1 t-small text-muted">
          <p>{x.note(release)}</p>
          <p>{x.method}</p>
        </div>
      </div>
    </div>
  );
}

/** Tornado: one row per driver, bars from the current chance to the chance one step down (left) and up (right). */
function Tornado({ sens, labels, x, stale }: { sens: { now: number; rows: Sensitivity[] }; labels: Record<string, [string, string, string]>; x: (typeof TEXT)["vi"]; stale: boolean }) {
  const all = sens.rows.flatMap((r) => [r.low ?? sens.now, r.high, sens.now]);
  const lo = Math.max(0, Math.min(...all) - 0.05);
  const hi = Math.min(1, Math.max(...all) + 0.05);
  const pos = (v: number) => ((v - lo) / (hi - lo || 1)) * 100;
  const bar = (v: number | null) => {
    if (v === null) return null;
    const a = Math.min(v, sens.now);
    const b = Math.max(v, sens.now);
    return (
      <span
        className="absolute top-1/2 h-4 -translate-y-1/2 rounded"
        style={{ left: `${pos(a)}%`, width: `${Math.max(0.5, pos(b) - pos(a))}%`, background: v < sens.now ? "var(--series-2)" : "var(--series-1)" }}
      />
    );
  };
  return (
    <div className={`space-y-2 transition-opacity ${stale ? "opacity-50" : ""}`} aria-busy={stale}>
      <ul className="space-y-2">
        {sens.rows.map((r) => {
          const [name, down, up] = labels[r.id] ?? [r.id, "", ""];
          return (
            <li key={r.id} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[10rem_6.5rem_1fr_6.5rem]">
              <span className="t-small font-semibold sm:col-auto">{name}</span>
              <span className="t-caption tabular-nums text-right text-muted sm:order-none">
                {down ? `${down}: ${Math.round((r.low ?? sens.now) * 100)}%` : ""}
              </span>
              <span
                className="relative col-span-2 block h-7 sm:col-span-1"
                aria-label={`${name}: ${down ? `${down} → ${Math.round((r.low ?? sens.now) * 100)}%, ` : ""}${up} → ${Math.round(r.high * 100)}%`}
                role="img"
              >
                <span className="absolute inset-y-0 w-px bg-ink" style={{ left: `${pos(sens.now)}%` }} />
                {bar(r.low)}
                {bar(r.high)}
              </span>
              <span className="hidden t-caption tabular-nums text-muted sm:block">
                {up}: {Math.round(r.high * 100)}%
              </span>
              <span className="col-span-2 -mt-1 t-caption tabular-nums text-muted sm:hidden">
                {up}: {Math.round(r.high * 100)}%
              </span>
            </li>
          );
        })}
      </ul>
      <ul className="flex flex-wrap gap-x-5 t-small">
        <li>
          <span className="inline-block h-3 w-5 rounded-sm align-middle" style={{ background: "var(--series-2)" }} aria-hidden="true" /> {x.worse}
        </li>
        <li>
          <span className="inline-block h-3 w-5 rounded-sm align-middle" style={{ background: "var(--series-1)" }} aria-hidden="true" /> {x.better}
        </li>
      </ul>
    </div>
  );
}

/** Small multiples: one histogram row per series on the same bins and scale. */
function Histo({ lo, hi, rows, lang }: { lo: number; hi: number; rows: [string, number[], string][]; lang: Lang }) {
  const bins = rows[0][1].length;
  const max = Math.max(...rows.flatMap(([, h]) => h));
  const w = (hi - lo) / bins;
  return (
    <div className="space-y-3">
      {rows.map(([label, h, colour]) => (
        <div key={label}>
          <p className="t-small font-semibold">{label}</p>
          <div className="flex h-24 items-end gap-[2px]" role="img" aria-label={label}>
            {h.map((v, i) => (
              <span
                key={i}
                className="flex-1 rounded-t"
                style={{ height: `${(v / max) * 100}%`, background: colour, opacity: lo + i * w < 0 ? 0.65 : 1 }}
                title={`${pct(lo + i * w, lang)} … ${pct(lo + (i + 1) * w, lang)}: ${Math.round(v * 1000) / 10}%`}
              />
            ))}
          </div>
        </div>
      ))}
      <div className="relative h-4 t-caption text-muted">
        <span className="absolute left-0">≤ {lo}%</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${(-lo / (hi - lo)) * 100}%` }}>
          0%
        </span>
        <span className="absolute right-0">≥ {hi}%</span>
      </div>
    </div>
  );
}

function Slider({ label, value, min, max, step, show, onChange }: { label: string; value: number; min: number; max: number; step: number; show: string; onChange: (v: number) => void }) {
  return (
    <label className="block space-y-1">
      <span className="flex items-baseline justify-between gap-2 t-small font-semibold">
        <span>{label}</span>
        <span className="tabular-nums text-muted">{show}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} className="w-full accent-[var(--ink)]" />
    </label>
  );
}

function Stat({ label, value, base }: { label: string; value: string; base: string }) {
  return (
    <div className="sv-panel space-y-1">
      <p className="t-small text-muted">{label}</p>
      <p className="text-[40px] leading-none font-extrabold tracking-tight tabular-nums">{value}</p>
      <p className="t-small text-muted tabular-nums">{base}</p>
    </div>
  );
}

function Legend({ x }: { x: (typeof TEXT)["vi"] }) {
  const sw = (style: React.CSSProperties) => <span className="inline-block h-3 w-5 rounded-sm align-middle" style={style} aria-hidden="true" />;
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1 t-small">
      <li>{sw({ background: "var(--series-1)", height: 3 })} {x.legendScen[0]}</li>
      <li>{sw({ background: "color-mix(in srgb, var(--series-1) 35%, transparent)" })} {x.legendScen[1]}</li>
      <li>{sw({ background: "color-mix(in srgb, var(--series-1) 15%, transparent)" })} {x.legendScen[2]}</li>
      <li>{sw({ borderTop: "2px dashed var(--line-strong)", height: 0 })} {x.legendBase[0]}</li>
      <li>{sw({ borderTop: "2px dotted var(--line-strong)", height: 0 })} {x.legendBase[1]}</li>
      <li>{sw({ borderTop: "2px solid var(--series-2)", height: 0 })} {x.goalLine}</li>
    </ul>
  );
}

type Band = { p10: number; p25: number; p50: number; p75: number; p90: number };

/** Percentile fan of the scenario over the base (dashed), goal line, crosshair tooltip on hover/touch. */
function Fan({ scen, base, goal, lang, x }: { scen: Band[]; base: Band[]; goal: number; lang: Lang; x: (typeof TEXT)["vi"] }) {
  const W = 720;
  const H = 320;
  const pad = { l: 76, r: 16, t: 16, b: 30 };
  const years = scen.length - 1;
  const top = Math.max(goal, ...scen.map((b) => b.p90), ...base.map((b) => b.p90)) * 1.05;
  const step = niceStep(top / 4);
  const max = Math.ceil(top / step) * step;
  const px = (y: number) => pad.l + (y / years) * (W - pad.l - pad.r);
  const py = (v: number) => pad.t + (1 - v / max) * (H - pad.t - pad.b);
  const area = (lo: keyof Band, hi: keyof Band) =>
    `${scen.map((b, y) => `${y ? "L" : "M"}${px(y)},${py(b[hi])}`).join("")}${scen
      .map((_, k) => {
        const y = years - k;
        return `L${px(y)},${py(scen[y][lo])}`;
      })
      .join("")}Z`;
  const line = (data: Band[], key: keyof Band) => data.map((b, y) => `${y ? "L" : "M"}${px(y)},${py(b[key])}`).join("");
  const ticks = Array.from({ length: Math.round(max / step) + 1 }, (_, k) => k * step);
  const box = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const onMove = (e: React.PointerEvent) => {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    const sx = ((e.clientX - r.left) / r.width) * W;
    setHover(Math.max(0, Math.min(years, Math.round(((sx - pad.l) / (W - pad.l - pad.r)) * years))));
  };
  const h = hover === null ? null : { y: hover, s: scen[hover], b: base[hover] };
  return (
    <div className="relative">
      <svg
        ref={box}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full touch-none"
        role="img"
        aria-label={`${x.fan}: ${x.year(years)}, ${x.legendScen[0]} ${vnd(Math.round(scen[years].p50), lang)}, ${x.legendBase[0]} ${vnd(Math.round(base[years].p50), lang)}`}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={W - pad.r} y1={py(v)} y2={py(v)} stroke="var(--line)" />
            <text x={pad.l - 8} y={py(v) + 4} textAnchor="end" fontSize="11" fill="var(--ink-muted)">
              {vndShort(Math.round(v), lang)}
            </text>
          </g>
        ))}
        {Array.from({ length: years + 1 }, (_, y) => y)
          .filter((y) => y % Math.max(1, Math.round(years / 6)) === 0 || y === years)
          .map((y) => (
            <text key={y} x={px(y)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--ink-muted)">
              {y}
            </text>
          ))}
        <path d={area("p10", "p90")} fill="color-mix(in srgb, var(--series-1) 15%, transparent)" />
        <path d={area("p25", "p75")} fill="color-mix(in srgb, var(--series-1) 35%, transparent)" />
        <path d={line(base, "p10")} fill="none" stroke="var(--line-strong)" strokeWidth={1.5} strokeDasharray="2 4" />
        <path d={line(base, "p90")} fill="none" stroke="var(--line-strong)" strokeWidth={1.5} strokeDasharray="2 4" />
        <path d={line(base, "p50")} fill="none" stroke="var(--line-strong)" strokeWidth={2} strokeDasharray="6 4" />
        <path d={line(scen, "p50")} fill="none" stroke="var(--series-1)" strokeWidth={2.5} />
        <line x1={pad.l} x2={W - pad.r} y1={py(goal)} y2={py(goal)} stroke="var(--series-2)" strokeWidth={2} />
        <text x={W - pad.r} y={py(goal) - 6} textAnchor="end" fontSize="12" fontWeight={700} fill="var(--ink)">
          {x.goalLine} {vndShort(goal, lang)}
        </text>
        {h ? (
          <g pointerEvents="none">
            <line x1={px(h.y)} x2={px(h.y)} y1={pad.t} y2={H - pad.b} stroke="var(--ink)" strokeOpacity={0.4} />
            <circle cx={px(h.y)} cy={py(h.s.p50)} r={5} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
          </g>
        ) : null}
      </svg>
      {h ? (
        <div
          className="pointer-events-none absolute top-2 z-10 w-56 rounded-2xl bg-ink p-3 t-small text-surface shadow-lg"
          style={{ left: `clamp(0px, calc(${(px(h.y) / W) * 100}% - 7rem), calc(100% - 14rem))` }}
        >
          <p className="font-bold">{x.year(h.y)}</p>
          <p className="tabular-nums">
            {x.legendScen[0]}: {vndShort(Math.round(h.s.p50), lang)}
          </p>
          <p className="tabular-nums opacity-80">
            10–90%: {vndShort(Math.round(h.s.p10), lang)} – {vndShort(Math.round(h.s.p90), lang)}
          </p>
          <p className="tabular-nums opacity-80">
            {x.legendBase[0]}: {vndShort(Math.round(h.b.p50), lang)}
          </p>
        </div>
      ) : null}
    </div>
  );
}

/** 1, 2 or 5 times a power of ten, at least `raw`. */
function niceStep(raw: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  return [1, 2, 5, 10].map((m) => m * p).find((v) => v >= raw) ?? 10 * p;
}

/** Quantile dot plot: 100 dots binned by final value; filled = reaches the goal. */
function Dots({ dots, goal, lang, x }: { dots: number[]; goal: number; lang: Lang; x: (typeof TEXT)["vi"] }) {
  const W = 720;
  const bins = 24;
  const lo = Math.min(dots[0], goal);
  const hi = Math.max(dots[dots.length - 1], goal);
  const width = (hi - lo) / bins || 1;
  const stacks = new Map<number, number[]>();
  dots.forEach((v) => {
    const b = Math.min(bins - 1, Math.floor((v - lo) / width));
    stacks.set(b, [...(stacks.get(b) ?? []), v]);
  });
  const r = 9;
  const tallest = Math.max(...[...stacks.values()].map((s) => s.length));
  const H = Math.max(120, tallest * (2 * r + 3) + 40);
  const cx = (b: number) => 20 + (b + 0.5) * ((W - 40) / bins);
  const gx = 20 + ((goal - lo) / (hi - lo || 1)) * (W - 40);
  return (
    <div className="space-y-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={x.dots}>
        {[...stacks.entries()].map(([b, vals]) =>
          vals.map((v, k) => {
            const ok = v >= goal;
            return (
              <circle
                key={`${b}-${k}`}
                cx={cx(b)}
                cy={H - 28 - r - k * (2 * r + 3)}
                r={r}
                fill={ok ? "var(--series-1)" : "var(--surface)"}
                stroke={ok ? "var(--surface)" : "var(--line-strong)"}
                strokeWidth={ok ? 2 : 1.5}
              >
                <title>{vnd(Math.round(v), lang)}</title>
              </circle>
            );
          }),
        )}
        <line x1={gx} x2={gx} y1={8} y2={H - 22} stroke="var(--series-2)" strokeWidth={2} />
        <text x={gx + 6} y={18} fontSize="12" fontWeight={700} fill="var(--ink)">
          {x.goalLine}
        </text>
        <text x={20} y={H - 6} fontSize="11" fill="var(--ink-muted)">
          {vndShort(Math.round(lo), lang)}
        </text>
        <text x={W - 20} y={H - 6} textAnchor="end" fontSize="11" fill="var(--ink-muted)">
          {vndShort(Math.round(hi), lang)}
        </text>
      </svg>
      <ul className="flex flex-wrap gap-x-5 t-small">
        <li>
          <span className="inline-block h-3 w-3 rounded-full align-middle" style={{ background: "var(--series-1)" }} aria-hidden="true" /> {x.reach}
        </li>
        <li>
          <span className="inline-block h-3 w-3 rounded-full border-[1.5px] border-line-strong align-middle" aria-hidden="true" /> {x.miss}
        </li>
      </ul>
    </div>
  );
}
