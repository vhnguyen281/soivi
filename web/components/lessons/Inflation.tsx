"use client";

import { useState } from "react";

import { pct, vndShort, type Lang } from "@/lib/format";
import { doublingYears, realValue } from "@/lib/lessons";

import { Term } from "../Term";
import { Quiz, Step } from "./Parts";

type Rate = { bank: string; rate: number };

const TEXT = {
  vi: {
    s1: "100 triệu hôm nay, sau vài năm còn mua được bao nhiêu?",
    p1: (pi: string) =>
      `Kéo thanh để đi tới tương lai. Giả định lạm phát ${pi} mỗi năm (VNCMA). Ba đường là ba cách giữ tiền, tính theo sức mua của hôm nay.`,
    years: "Số năm",
    series: ["Để tiền mặt", "Gửi không kỳ hạn", "Gửi 12 tháng, tái tục"],
    after: (y: number) => `Sau ${y} năm`,
    rateOf: (b: string, r: string) => `${b} ${r}`,
    s2: "Giá cả gấp đôi sau bao lâu?",
    p2: "Kéo mức lạm phát. Mẹo nhẩm: lấy 72 chia cho lạm phát (%) là ra số năm để giá cả gấp đôi.",
    infl: "Lạm phát mỗi năm",
    doubles: (y: string) => `Giá cả gấp đôi sau khoảng ${y} năm`,
    rule: (y: string) => `Mẹo 72 cho: ${y} năm`,
    s3: "Thử một câu",
    q: "Gửi lãi 6%/năm khi lạm phát 3,9%/năm. Sức mua của bạn tăng khoảng bao nhiêu mỗi năm?",
    opts: ["6%", "Khoảng 2%", "3,9%", "Không tăng"],
    why: "Lãi thực ≈ lãi suất trừ lạm phát: (1,06 / 1,039) − 1 ≈ 2,0%. Đó mới là phần bạn thật sự giàu thêm.",
    source: "Lãi suất: mức cao nhất đã kiểm tra trên SoiVí, lấy từ trang của chính ngân hàng. Lạm phát: giả định VNCMA.",
  },
  en: {
    s1: "What will 100 million buy in a few years?",
    p1: (pi: string) =>
      `Drag to travel forward. Inflation is assumed at ${pi} a year (VNCMA). The three lines are three ways to hold money, in today's buying power.`,
    years: "Years",
    series: ["Cash", "Demand deposit", "12-month deposit, rolled over"],
    after: (y: number) => `After ${y} years`,
    rateOf: (b: string, r: string) => `${b} ${r}`,
    s2: "How long until prices double?",
    p2: "Drag the inflation rate. Shortcut: 72 divided by inflation (%) gives the years for prices to double.",
    infl: "Inflation a year",
    doubles: (y: string) => `Prices double in about ${y} years`,
    rule: (y: string) => `Rule of 72 says: ${y} years`,
    s3: "Try one",
    q: "You earn 6% a year while inflation is 3.9%. How much does your buying power grow each year?",
    opts: ["6%", "About 2%", "3.9%", "Not at all"],
    why: "Real return ≈ rate minus inflation: (1.06 / 1.039) − 1 ≈ 2.0%. That is how much richer you really get.",
    source: "Rates: the highest checked on SoiVí, from the banks' own pages. Inflation: VNCMA assumption.",
  },
};

const COLOURS = ["var(--series-2)", "var(--series-1)", "var(--series-3)"];

export function InflationLesson({ lang, inflation, demand, deposit }: { lang: Lang; inflation: number; demand: Rate; deposit: Rate }) {
  const x = TEXT[lang];
  const [years, setYears] = useState(10);
  const [pi, setPi] = useState(Math.round(inflation));
  const rates = [0, demand.rate, deposit.rate];
  const now = rates.map((r) => realValue(years, r, inflation) * 1e6);
  const nf = (v: number, d = 1) => v.toLocaleString(lang === "vi" ? "vi-VN" : "en-US", { maximumFractionDigits: d });

  return (
    <div className="space-y-10">
      <Step n={1} title={x.s1}>
        <p>{x.p1(pct(inflation, lang))}</p>
        <label className="map-hand block text-[20px]">
          {x.after(years)}
          <input type="range" min={1} max={30} value={years} onChange={(e) => setYears(+e.target.value)} />
        </label>
        <Lines rates={rates} inflation={inflation} years={years} labels={x.series} lang={lang} />
        <div className="sv-table-wrap" role="region" aria-label={x.after(years)} tabIndex={0}>
          <table className="sv-table">
            <tbody>
              {x.series.map((s, i) => (
                <tr key={s}>
                  <th scope="row">
                    <span className="mp-swatch" style={{ background: COLOURS[i] }} aria-hidden="true" /> {s}
                    {i > 0 ? (
                      <span className="sv-sub">{x.rateOf(i === 1 ? demand.bank : deposit.bank, pct(rates[i], lang))}</span>
                    ) : null}
                  </th>
                  <td className="text-right tabular-nums font-semibold">{vndShort(Math.round(now[i]), lang)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Step>

      <Step n={2} title={x.s2}>
        <p>{x.p2}</p>
        <label className="map-hand block text-[20px]">
          {x.infl}: <b>{pi}%</b>
          <input type="range" min={1} max={12} value={pi} onChange={(e) => setPi(+e.target.value)} />
        </label>
        <p className="map-num text-[40px]">{x.doubles(nf(doublingYears(pi)))}</p>
        <p className="text-sm">{x.rule(nf(72 / pi))}</p>
      </Step>

      <Step n={3} title={x.s3}>
        <Quiz lang={lang} question={x.q} options={x.opts} answer={1} why={x.why} />
        <p className="text-sm">
          <Term id="lai-thuc" lang={lang} /> · <Term id="lam-phat" lang={lang} />
        </p>
      </Step>
      <p className="text-xs text-[var(--map-muted)]">{x.source}</p>
    </div>
  );
}

/** Buying power of 100 million over 30 years, three series with direct labels and a marker at the chosen year. */
function Lines({ rates, inflation, years, labels, lang }: { rates: number[]; inflation: number; years: number; labels: string[]; lang: Lang }) {
  const W = 640;
  const H = 260;
  const pad = { l: 44, r: 150, t: 12, b: 28 };
  const series = rates.map((r) => Array.from({ length: 31 }, (_, y) => realValue(y, r, inflation)));
  const max = Math.max(120, ...series.flat());
  const x = (y: number) => pad.l + (y / 30) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - v / max) * (H - pad.t - pad.b);
  // Direct labels at the right end, pushed apart so close lines stay readable.
  const ends = series.map((s, i) => ({ i, y: y(s[30]) })).sort((a, b) => a.y - b.y);
  for (let k = 1; k < ends.length; k++) ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 15);
  const labelY = new Map(ends.map((e) => [e.i, e.y]));
  const ticks = [0, 50, 100, Math.round(max / 50) * 50].filter((v, i, a) => a.indexOf(v) === i && v <= max);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={labels.map((l, i) => `${l}: ${Math.round(series[i][years])}`).join(", ")}>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke="var(--map-line)" />
          <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--map-muted)">
            {v}
          </text>
        </g>
      ))}
      {[0, 10, 20, 30].map((t) => (
        <text key={t} x={x(t)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--map-muted)">
          {t}
          {t === 30 ? (lang === "vi" ? " năm" : " yrs") : ""}
        </text>
      ))}
      <line x1={x(years)} x2={x(years)} y1={pad.t} y2={H - pad.b} stroke="var(--map-ink)" strokeDasharray="3 3" />
      {series.map((s, i) => (
        <g key={labels[i]}>
          <path d={s.map((v, j) => `${j ? "L" : "M"}${x(j).toFixed(1)},${y(v).toFixed(1)}`).join("")} fill="none" stroke={COLOURS[i]} strokeWidth={2} />
          <circle cx={x(years)} cy={y(s[years])} r={5} fill={COLOURS[i]} stroke="var(--map-card)" strokeWidth={2} />
          <text x={W - pad.r + 8} y={(labelY.get(i) ?? 0) + 4} fontSize="12" fill="var(--map-ink)">
            {labels[i]}
          </text>
        </g>
      ))}
    </svg>
  );
}
