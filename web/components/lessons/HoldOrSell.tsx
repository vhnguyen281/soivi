"use client";

import { useState } from "react";

import { pct, type Lang } from "@/lib/format";
import { gameReturns, playGame } from "@/lib/lessons";

import { Step } from "./Parts";

const YEARS = 10;

const TEXT = {
  vi: {
    s1: "Luật chơi",
    p1: (a: string, r: string, v: string, d: string) =>
      `Bạn có 100 triệu trong ${a} (lợi nhuận kỳ vọng ${r}/năm, biến động ${v}, giả định VNCMA). Mỗi năm bạn chọn: giữ trong thị trường, hay chuyển sang tiền gửi lãi ${d}. Trong 10 năm sẽ có một năm giảm mạnh. Bạn không biết trước năm nào.`,
    s2: "Chơi",
    year: (y: number) => `Năm ${y}/${YEARS}`,
    value: "Tiền của bạn",
    last: (r: string) => `Năm vừa rồi thị trường: ${r}`,
    youWere: (inv: boolean) => (inv ? "bạn đang ở trong thị trường" : "bạn đang để ở tiền gửi"),
    hold: "Giữ trong thị trường",
    sell: "Chuyển sang tiền gửi",
    stayOut: "Tiếp tục để tiền gửi",
    buyBack: "Mua lại cổ phiếu",
    crash: "Ối! Thị trường vừa giảm mạnh. Bạn làm gì tiếp?",
    s3: "Kết quả",
    you: "Cách bạn chơi",
    holder: "Luôn giữ",
    saver: "Luôn gửi tiết kiệm",
    lessonGood: "Bạn đã giữ qua cú giảm. Phần lớn lợi nhuận dài hạn đến từ những năm ngay sau một đợt giảm.",
    lessonBad: "Bạn đã bán sau cú giảm và lỡ phần hồi phục. Đây là cách mất tiền phổ biến nhất: không phải vì thị trường, mà vì thời điểm bán.",
    lessonSaver: "Bạn chọn an toàn từ đầu. Không có gì sai, miễn là mức đó đủ cho mục tiêu của bạn.",
    again: "Chơi lại với kịch bản khác",
    note: "Mô phỏng từ giả định VNCMA, có cài sẵn một năm giảm 25%. Không phải dữ liệu lịch sử.",
    yearsAxis: "năm",
  },
  en: {
    s1: "How to play",
    p1: (a: string, r: string, v: string, d: string) =>
      `You have 100 million in ${a} (expected return ${r} a year, volatility ${v}, VNCMA assumptions). Each year you choose: stay in the market, or move to a deposit paying ${d}. One of the 10 years brings a big fall. You don't know which.`,
    s2: "Play",
    year: (y: number) => `Year ${y}/${YEARS}`,
    value: "Your money",
    last: (r: string) => `Last year the market: ${r}`,
    youWere: (inv: boolean) => (inv ? "you are in the market" : "you are in a deposit"),
    hold: "Stay in the market",
    sell: "Move to a deposit",
    stayOut: "Stay in the deposit",
    buyBack: "Buy back in",
    crash: "Ouch! The market just fell hard. What now?",
    s3: "Result",
    you: "Your way",
    holder: "Always hold",
    saver: "Always deposit",
    lessonGood: "You held through the fall. Much of the long-term return comes in the years right after a fall.",
    lessonBad: "You sold after the fall and missed the recovery. This is the most common way to lose money: not the market, but when you sell.",
    lessonSaver: "You played safe from the start. Nothing wrong with that, as long as it is enough for your goals.",
    again: "Play again with another scenario",
    note: "Simulated from VNCMA assumptions, with one 25% fall built in. Not historical data.",
    yearsAxis: "yrs",
  },
};

export function HoldOrSellLesson({ lang, asset, deposit }: { lang: Lang; asset: { name: string; ret: number; vol: number }; deposit: number }) {
  const x = TEXT[lang];
  const [round, setRound] = useState(0);
  const seed = 101 + round * 17;
  const crashYear = 1 + (round % 4);
  const returns = gameReturns(asset.ret, asset.vol, YEARS, seed, crashYear, 25);
  const [choices, setChoices] = useState<boolean[]>([]);
  const year = choices.length;
  const mine = playGame(returns.slice(0, year), choices, deposit);
  const done = year >= YEARS;
  const invested = choices.at(-1) ?? true;
  const lastReturn = year > 0 ? (choices[year - 1] ? returns[year - 1] : deposit) : null;
  const marketLast = year > 0 ? returns[year - 1] : null;
  const justCrashed = year - 1 === crashYear;
  const choose = (inMarket: boolean) => setChoices([...choices, inMarket]);
  const holder = playGame(returns, Array(YEARS).fill(true), deposit);
  const saver = playGame(returns, Array(YEARS).fill(false), deposit);
  const soldAfterCrash = choices.slice(crashYear + 1).some((c) => !c);
  const p = (v: number) => pct(Math.round(v * 10) / 10, lang);
  const m = (v: number) => `${Math.round(v)} ${lang === "vi" ? "triệu" : "million"}`;

  return (
    <div className="space-y-10">
      <Step n={1} title={x.s1}>
        <p>{x.p1(asset.name, p(asset.ret), p(asset.vol), p(deposit))}</p>
      </Step>

      <Step n={2} title={x.s2}>
        <div className="flex flex-wrap items-end justify-between gap-4" aria-live="polite">
          <div>
            <p className="map-hand text-[22px]">{x.year(Math.min(year + 1, YEARS))}</p>
            <p className="text-sm">{x.value}</p>
            <p className="map-num text-[48px]">{m(mine.at(-1) ?? 100)}</p>
          </div>
          {marketLast !== null ? (
            <div className="text-right text-sm">
              <p>{x.last(p(marketLast))}</p>
              <p>
                {x.youWere(choices[year - 1])}
                {lastReturn !== null ? ` (${p(lastReturn)})` : ""}
              </p>
            </div>
          ) : null}
        </div>
        {justCrashed && !done ? <p className="map-hand text-[24px] text-[var(--map-terra)]">{x.crash}</p> : null}
        {!done ? (
          <div className="flex flex-wrap gap-3">
            <button type="button" className="sv-btn sv-btn--primary" onClick={() => choose(true)}>
              {invested ? x.hold : x.buyBack}
            </button>
            <button type="button" className="sv-btn sv-btn--secondary" onClick={() => choose(false)}>
              {invested ? x.sell : x.stayOut}
            </button>
          </div>
        ) : null}
        <GameChart mine={mine} holder={done ? holder : holder.slice(0, year + 1)} saver={done ? saver : null} labels={[x.you, x.holder, x.saver]} axis={x.yearsAxis} />
      </Step>

      {done ? (
        <Step n={3} title={x.s3}>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              [x.you, mine[YEARS]],
              [x.holder, holder[YEARS]],
              [x.saver, saver[YEARS]],
            ].map(([l, v]) => (
              <div key={l as string} className="map-chest">
                <p className="map-hand text-[20px]">{l}</p>
                <p className="map-num text-[30px]">{m(v as number)}</p>
              </div>
            ))}
          </div>
          <p className="font-semibold">{choices.every((c) => !c) ? x.lessonSaver : soldAfterCrash ? x.lessonBad : x.lessonGood}</p>
          <button
            type="button"
            className="sv-btn sv-btn--secondary"
            onClick={() => {
              setRound(round + 1);
              setChoices([]);
            }}
          >
            {x.again}
          </button>
        </Step>
      ) : null}
      <p className="text-xs text-[var(--map-muted)]">{x.note}</p>
    </div>
  );
}

const COLOURS = ["var(--series-2)", "var(--series-1)", "var(--series-3)"];

/** Your path against "always hold" (and "always deposit" at the end): one axis, direct labels. */
function GameChart({ mine, holder, saver, labels, axis }: { mine: number[]; holder: number[]; saver: number[] | null; labels: string[]; axis: string }) {
  const W = 600;
  const H = 220;
  const pad = { l: 36, r: 110, t: 10, b: 24 };
  const all = [...mine, ...holder, ...(saver ?? [])];
  const max = Math.max(150, ...all) * 1.05;
  const min = Math.min(60, ...all) * 0.95;
  const x = (i: number) => pad.l + (i / YEARS) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - min) / (max - min)) * (H - pad.t - pad.b);
  const series = [mine, holder, saver].map((s, i) => ({ s, i })).filter((d): d is { s: number[]; i: number } => d.s !== null && d.s.length > 1);
  const ends = series.map(({ s, i }) => ({ i, y: y(s[s.length - 1]), x: x(s.length - 1) })).sort((a, b) => a.y - b.y);
  for (let k = 1; k < ends.length; k++) ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 14);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={series.map(({ s, i }) => `${labels[i]}: ${Math.round(s[s.length - 1])}`).join(", ")}>
      <line x1={pad.l} x2={W - pad.r} y1={y(100)} y2={y(100)} stroke="var(--map-ink)" strokeDasharray="4 4" strokeOpacity={0.5} />
      <text x={pad.l - 6} y={y(100) + 4} textAnchor="end" fontSize="11" fill="var(--map-muted)">
        100
      </text>
      {[0, 5, 10].map((t) => (
        <text key={t} x={x(t)} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--map-muted)">
          {t}
          {t === 10 ? ` ${axis}` : ""}
        </text>
      ))}
      {series.map(({ s, i }) => (
        <path key={i} d={s.map((v, j) => `${j ? "L" : "M"}${x(j).toFixed(1)},${y(v).toFixed(1)}`).join("")} fill="none" stroke={COLOURS[i]} strokeWidth={i === 0 ? 3 : 2} strokeDasharray={i === 0 ? undefined : "6 4"} />
      ))}
      {ends.map((e) => (
        <text key={e.i} x={e.x + 8} y={e.y + 4} fontSize="12" fill="var(--map-ink)">
          {labels[e.i]}
        </text>
      ))}
    </svg>
  );
}
