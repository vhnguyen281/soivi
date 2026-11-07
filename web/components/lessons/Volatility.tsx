"use client";

import { useState } from "react";

import type { ClassStat } from "@/lib/classes";
import { pct, type Lang } from "@/lib/format";
import { band80, fanPaths, fanSummary } from "@/lib/lessons";

import { Term } from "../Term";
import { Quiz, Step } from "./Parts";

const TEXT = {
  vi: {
    s1: "Một năm của mỗi lớp tài sản",
    p1: "Mỗi thanh là khoảng mà lợi nhuận một năm rơi vào 8 trên 10 lần, chấm là mức kỳ vọng (giả định VNCMA). Chọn một lớp để xem kỹ.",
    pick: "Lớp tài sản",
    range: (lo: string, hi: string) => `Trong một năm, 8 trên 10 lần lợi nhuận nằm trong khoảng ${lo} đến ${hi}.`,
    s2: "Một trăm tương lai",
    p2: "Mỗi nét là một hành trình 10 năm có thể xảy ra của 100đ với lớp tài sản đã chọn.",
    fan: (lo: string, hi: string, loss: string) => `Sau 10 năm, 8 trên 10 lối dẫn tới ${lo}–${hi}; ${loss} lối kết thúc dưới 100đ.`,
    s3: "Thời gian làm dịu biến động",
    p3: "Lợi nhuận bình quân mỗi năm dao động hẹp dần khi bạn giữ lâu hơn (nhưng tổng số tiền vẫn có thể chênh nhiều).",
    years: (n: number) => `Giữ ${n} năm`,
    avg: (lo: string, hi: string) => `Lợi nhuận bình quân mỗi năm: 8 trên 10 lần nằm trong ${lo} đến ${hi}.`,
    s4: "Thử một câu",
    q: "Biến động cao nghĩa là gì?",
    opts: ["Chắc chắn lỗ", "Kết quả mỗi năm dao động rộng quanh mức trung bình", "Lợi nhuận chắc chắn cao hơn", "Tốn phí nhiều hơn"],
    why: "Biến động đo độ rộng của các kết quả có thể xảy ra, không nói trước lời hay lỗ. Tài sản biến động cao thường cần giữ lâu hơn.",
    source: "Lợi nhuận kỳ vọng và biến động: giả định VNCMA. Mô phỏng, không phải lịch sử.",
  },
  en: {
    s1: "One year of each asset class",
    p1: "Each bar is where one year's return lands 8 times in 10; the dot is the expected return (VNCMA). Pick a class to look closer.",
    pick: "Asset class",
    range: (lo: string, hi: string) => `In one year, 8 times in 10 the return lands between ${lo} and ${hi}.`,
    s2: "A hundred futures",
    p2: "Each line is one possible 10-year journey of 100 in the chosen class.",
    fan: (lo: string, hi: string, loss: string) => `After 10 years, 8 in 10 paths land at ${lo}–${hi}; ${loss} end below 100.`,
    s3: "Time calms the swings",
    p3: "The average yearly return narrows the longer you hold (though the total can still differ a lot).",
    years: (n: number) => `Hold ${n} years`,
    avg: (lo: string, hi: string) => `Average yearly return: 8 times in 10 between ${lo} and ${hi}.`,
    s4: "Try one",
    q: "What does high volatility mean?",
    opts: ["A sure loss", "Yearly results swing widely around the average", "A sure higher return", "Higher fees"],
    why: "Volatility measures how wide the possible results are; it does not say gain or loss in advance. Volatile assets usually need longer holding.",
    source: "Expected returns and volatility: VNCMA assumptions. A simulation, not history.",
  },
};

export function VolatilityLesson({ lang, classes }: { lang: Lang; classes: ClassStat[] }) {
  const x = TEXT[lang];
  const [id, setId] = useState(classes.find((c) => c.id === "eq_large")?.id ?? classes[0]?.id);
  const [years, setYears] = useState(5);
  const c = classes.find((k) => k.id === id) ?? classes[0];
  if (!c) return null;
  const [lo1, hi1] = band80(c.ret, c.vol, 1);
  const [loN, hiN] = band80(c.ret, c.vol, years);
  const paths = fanPaths(c.ret, c.vol, 10, 40, 11);
  const fan = fanSummary(paths);
  const p = (v: number) => pct(Math.round(v * 10) / 10, lang);

  return (
    <div className="space-y-10">
      <Step n={1} title={x.s1}>
        <p>
          {x.p1} <Term id="bien-dong" lang={lang}>{lang === "vi" ? "Biến động là gì?" : "What is volatility?"}</Term>
        </p>
        <Ranges classes={classes} selected={c.id} onPick={setId} lang={lang} />
        <label className="map-hand block max-w-sm text-[20px]">
          {x.pick}
          <select className="map-input" value={c.id} onChange={(e) => setId(e.target.value)}>
            {classes.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
        </label>
        <p className="font-semibold">{x.range(p(lo1), p(hi1))}</p>
      </Step>

      <Step n={2} title={x.s2}>
        <p>{x.p2}</p>
        <Paths paths={paths} label={x.s2} />
        <p>{x.fan(`${Math.round(fan.low)}đ`, `${Math.round(fan.high)}đ`, `${Math.round(fan.loss * 100)}%`)}</p>
      </Step>

      <Step n={3} title={x.s3}>
        <p>{x.p3}</p>
        <label className="map-hand block text-[20px]">
          {x.years(years)}
          <input type="range" min={1} max={20} value={years} onChange={(e) => setYears(+e.target.value)} />
        </label>
        <Band lo={loN} hi={hiN} wide={[lo1, hi1]} mid={c.ret} lang={lang} />
        <p className="font-semibold">{x.avg(p(loN), p(hiN))}</p>
      </Step>

      <Step n={4} title={x.s4}>
        <Quiz lang={lang} question={x.q} options={x.opts} answer={1} why={x.why} />
      </Step>
      <p className="text-xs text-[var(--map-muted)]">{x.source}</p>
    </div>
  );
}

/** One horizontal range per class (80% of one-year returns), dot at the expected return; tap a row to pick it. */
function Ranges({ classes, selected, onPick, lang }: { classes: ClassStat[]; selected: string; onPick: (id: string) => void; lang: Lang }) {
  const bands = classes.map((c) => band80(c.ret, c.vol, 1));
  const lo = Math.min(-10, ...bands.map((b) => b[0]));
  const hi = Math.max(20, ...bands.map((b) => b[1]));
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="space-y-1">
      {classes.map((c, i) => {
        const [a, b] = bands[i];
        const on = c.id === selected;
        return (
          <button
            key={c.id}
            type="button"
            onClick={() => onPick(c.id)}
            aria-pressed={on}
            className={`grid w-full grid-cols-[9rem_1fr] items-center gap-3 rounded px-1 py-1 text-left text-sm sm:grid-cols-[12rem_1fr] ${on ? "font-semibold" : ""}`}
            aria-label={`${c.name}: ${pct(Math.round(a * 10) / 10, lang)} – ${pct(Math.round(b * 10) / 10, lang)}`}
          >
            <span>{c.name}</span>
            <span className="relative block h-6">
              <span className="absolute top-1/2 h-px w-full bg-[var(--map-line)]" />
              <span className="absolute top-0 h-full w-px bg-[var(--map-ink)] opacity-50" style={{ left: x(0) }} />
              <span
                className="absolute top-1/2 h-2.5 -translate-y-1/2 rounded"
                style={{ left: x(a), width: `calc(${x(b)} - ${x(a)})`, background: on ? "var(--map-terra-bright)" : "var(--map-teal)", opacity: on ? 1 : 0.55 }}
              />
              <span
                className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--map-card)] bg-[var(--map-ink)]"
                style={{ left: x(c.ret) }}
              />
            </span>
          </button>
        );
      })}
      <p className="grid grid-cols-[9rem_1fr] text-xs text-[var(--map-muted)] sm:grid-cols-[12rem_1fr]">
        <span />
        <span className="flex justify-between">
          <span>{pct(Math.round(lo), lang)}</span>
          <span>0%</span>
          <span>{pct(Math.round(hi), lang)}</span>
        </span>
      </p>
    </div>
  );
}

function Band({ lo, hi, wide, mid, lang }: { lo: number; hi: number; wide: [number, number]; mid: number; lang: Lang }) {
  const min = Math.min(-5, wide[0]);
  const max = Math.max(15, wide[1]);
  const x = (v: number) => `${((v - min) / (max - min)) * 100}%`;
  return (
    <div className="relative h-14" aria-hidden="true">
      <span className="absolute top-2 h-3 rounded opacity-30" style={{ left: x(wide[0]), width: `calc(${x(wide[1])} - ${x(wide[0])})`, background: "var(--map-teal)" }} />
      <span className="absolute top-2 h-3 rounded transition-all" style={{ left: x(lo), width: `calc(${x(hi)} - ${x(lo)})`, background: "var(--map-terra-bright)" }} />
      <span className="absolute top-0 h-7 w-0.5 bg-[var(--map-ink)]" style={{ left: x(mid) }} />
      <span className="absolute top-8 text-xs" style={{ left: x(0) }}>
        0%
      </span>
      <span className="absolute top-8 -translate-x-1/2 text-xs font-semibold" style={{ left: x(mid) }}>
        {pct(Math.round(mid * 10) / 10, lang)}
      </span>
    </div>
  );
}

function Paths({ paths, label }: { paths: number[][]; label: string }) {
  const W = 600;
  const H = 220;
  const max = 450;
  const px = (i: number) => 10 + (i / 10) * (W - 20);
  const py = (v: number) => H - 10 - (Math.min(v, max) / max) * (H - 20);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-52 w-full" role="img" aria-label={label}>
      <line x1={10} x2={W - 10} y1={py(100)} y2={py(100)} stroke="var(--map-ink)" strokeDasharray="4 4" strokeOpacity={0.6} />
      {paths.map((p, i) => (
        <path key={i} d={p.map((v, j) => `${j ? "L" : "M"}${px(j).toFixed(1)},${py(v).toFixed(1)}`).join("")} fill="none" stroke="var(--map-teal)" strokeOpacity={0.4} strokeWidth={1.5} />
      ))}
    </svg>
  );
}
