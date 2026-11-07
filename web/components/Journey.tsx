"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { pct, vnd, vndShort, type Lang } from "@/lib/format";
import { href } from "@/lib/i18n";
import { fanPaths, fanSummary, monthlyFor, realValue } from "@/lib/lessons";

import { LessonScraps } from "./LessonScraps";

export type JourneyBank = { name: string; rate: number; product: string };
export type JourneyPortfolio = { name: string; expectedReturn: number; volatility: number };
export type JourneyLesson = { slug: string; title: string; minutes: number; ready: boolean };

const TEXT = {
  vi: {
    title: ["Kho báu nằm", "ngay trong ví bạn."],
    hand: "…chỉ cần đúng bản đồ",
    amount: "Bạn đang gửi bao nhiêu?",
    bank: "Ở ngân hàng nào?",
    pick: "Chọn ngân hàng",
    lost: "Kho báu bị bỏ quên mỗi năm",
    vs: (b: string, r: string) => `so với ${b} (${r}), nơi trả cao nhất đã kiểm tra`,
    top: "Bạn đang ở nơi trả cao nhất đã kiểm tra. Tuyệt!",
    spread: (v: string) => `Chọn ngân hàng của bạn. Chênh lệch giữa nơi trả cao nhất và thấp nhất cho số tiền này: ${v} mỗi năm.`,
    basis: "Lãi suất 12 tháng tốt nhất của mỗi ngân hàng cho khoản 100 triệu, mọi kênh, lấy từ trang của chính ngân hàng.",
    compare: "So sánh mọi kỳ hạn",
    scroll: "↓ Cuộn để đồng xu lên đường. Mỗi trạm có một thứ để bạn thử.",
    stations: ["Làng Lạm Phát", "Đèo Rủi Ro", "Đỉnh Mục Tiêu", "Cảng Kế Hoạch"],
    s1: {
      h: "Đồng xu teo lại",
      p: (pi: string) => `Mỗi năm giá cả tăng khoảng ${pi} (giả định VNCMA). Kéo để đi tiếp bao nhiêu năm:`,
      years: "Số năm",
      r: (y: number) => `Sau ${y} năm, 100đ để yên chỉ còn mua được`,
      r2: "còn gửi ở nơi lãi cao nhất thì thành",
      r3: "(theo sức mua).",
      more: "Bài học: Lạm phát ăn ví",
    },
    s2: {
      h: "Đường càng dốc, càng nhiều lối",
      p: "Chọn một danh mục mẫu. Mỗi nét là một hành trình 10 năm có thể xảy ra của 100đ.",
      r: (lo: string, hi: string, loss: string) => `Sau 10 năm, 8 trên 10 lối dẫn tới khoảng ${lo}–${hi}; ${loss} lối kết thúc dưới 100đ.`,
      none: "Chưa có danh mục mẫu được duyệt.",
      more: "Xem các danh mục mẫu",
    },
    s3: {
      h: "Leo bao nhiêu mỗi tháng?",
      goal: "Mục tiêu",
      years: "Sau (năm)",
      safe: "Chỉ gửi tiết kiệm",
      bal: (n: string) => `Danh mục ${n}`,
      perMonth: "/tháng",
      note: "Theo lợi nhuận kỳ vọng, chưa tính rủi ro. Khả năng đạt thật sự: xem công cụ mục tiêu.",
      more: "Tính khả năng đạt mục tiêu",
    },
    s4: {
      h: "Ba rương cho ba việc",
      p: "Ví dụ 2 tỷ, chi tiêu 20 triệu mỗi tháng. Kéo số tháng dự phòng:",
      months: "Số tháng dự phòng",
      chests: ["Dự phòng", "Mục tiêu", "Tăng trưởng"],
      more: "Vẽ bản đồ của riêng bạn",
      hub: "Hành trình lập kế hoạch 5 bước",
    },
    learn: "Mảnh bản đồ",
    learnIntro: "Các bài học tương tác, mỗi bài vài phút. Tiến độ chỉ lưu trên trình duyệt này.",
    all: "Xem tất cả bài học",
  },
  en: {
    title: ["The treasure is", "already in your wallet."],
    hand: "…you just need the right map",
    amount: "How much do you have on deposit?",
    bank: "With which bank?",
    pick: "Choose a bank",
    lost: "Treasure left behind each year",
    vs: (b: string, r: string) => `compared with ${b} (${r}), the highest checked rate`,
    top: "You are already at the highest checked rate. Nice!",
    spread: (v: string) => `Choose your bank. The gap between the highest and lowest rate for this amount: ${v} a year.`,
    basis: "Each bank's best 12-month rate for 100 million, any channel, from the bank's own pages.",
    compare: "Compare every term",
    scroll: "↓ Scroll to send the coin on its way. Every stop has something to try.",
    stations: ["Inflation Village", "Risk Pass", "Goal Peak", "Plan Harbour"],
    s1: {
      h: "The shrinking coin",
      p: (pi: string) => `Prices rise about ${pi} a year (VNCMA assumption). Drag to travel the years:`,
      years: "Years",
      r: (y: number) => `After ${y} years, 100 left idle buys only`,
      r2: "while the best deposit grows it to",
      r3: "(in buying power).",
      more: "Lesson: Inflation eats your wallet",
    },
    s2: {
      h: "The steeper the road, the more paths",
      p: "Pick a model portfolio. Each line is one possible 10-year journey of 100.",
      r: (lo: string, hi: string, loss: string) => `After 10 years, 8 in 10 paths land between ${lo} and ${hi}; ${loss} end below 100.`,
      none: "No model portfolios are approved yet.",
      more: "See the model portfolios",
    },
    s3: {
      h: "How much to climb each month?",
      goal: "Goal",
      years: "In (years)",
      safe: "Deposits only",
      bal: (n: string) => `${n} portfolio`,
      perMonth: "/month",
      note: "At expected returns, before risk. For the real chance, use the goal tool.",
      more: "Check your chance of reaching it",
    },
    s4: {
      h: "Three chests for three jobs",
      p: "Say 2 billion, spending 20 million a month. Drag the months of reserve:",
      months: "Months of reserve",
      chests: ["Reserve", "Goals", "Growth"],
      more: "Draw your own map",
      hub: "The 5-step planning journey",
    },
    learn: "Map pieces",
    learnIntro: "Interactive lessons, a few minutes each. Progress stays in this browser.",
    all: "See all lessons",
  },
};

const digits = (s: string) => Number(s.replace(/\D/g, "").slice(0, 13)) || 0;

export function Journey({
  lang,
  banks,
  inflation,
  portfolios,
  lessons,
}: {
  lang: Lang;
  banks: JourneyBank[];
  inflation: number;
  portfolios: JourneyPortfolio[];
  lessons: JourneyLesson[];
}) {
  const x = TEXT[lang];
  const nf = (v: number) => v.toLocaleString(lang === "vi" ? "vi-VN" : "en-US");
  const best = banks[0];
  const [amount, setAmount] = useState(100_000_000);
  const [bank, setBank] = useState("");
  const [years, setYears] = useState(10);
  const [level, setLevel] = useState(Math.min(3, portfolios.length));
  const [goal, setGoal] = useState(1000);
  const [goalYears, setGoalYears] = useState(8);
  const [reserve, setReserve] = useState(12);

  const mine = banks.find((b) => b.name === bank);
  const missed = mine && best ? (amount * (best.rate - mine.rate)) / 100 : 0;
  const spread = banks.length ? (amount * (best.rate - banks[banks.length - 1].rate)) / 100 : 0;
  const portfolio = portfolios[level - 1];
  const paths = portfolio ? fanPaths(portfolio.expectedReturn, portfolio.volatility, 10, 36, 2027) : [];
  const fan = paths.length ? fanSummary(paths) : null;
  const balanced = portfolios[Math.min(2, portfolios.length - 1)];
  const res = Math.min(2000, reserve * 20);
  const goalsChest = Math.min(2000 - res, 780);
  const chests = [res, goalsChest, 2000 - res - goalsChest];

  return (
    <div className="map">
      <section className="sv-container grid gap-10 py-14 lg:grid-cols-[1.2fr_1fr] lg:items-center">
        <h1 className="map-title text-[clamp(44px,6vw,92px)]">
          {x.title[0]}
          <br />
          {x.title[1]}
          <span className="map-hand mt-3 block -rotate-2 text-[0.5em] text-[var(--map-terra)]">{x.hand}</span>
        </h1>
        <form className="map-card map-card--pinned rotate-1 space-y-3" onSubmit={(e) => e.preventDefault()}>
          <label className="map-hand block text-[22px]">
            {x.amount}
            <input className="map-input" inputMode="numeric" value={nf(amount)} onChange={(e) => setAmount(digits(e.target.value))} />
          </label>
          <label className="map-hand block text-[22px]">
            {x.bank}
            <select className="map-input" value={bank} onChange={(e) => setBank(e.target.value)}>
              <option value="">{x.pick}</option>
              {banks.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name} · {pct(b.rate, lang)}
                </option>
              ))}
            </select>
          </label>
          <div aria-live="polite" className="pt-2">
            {mine && best ? (
              missed > 0 ? (
                <>
                  <p className="map-hand text-[22px]">{x.lost}</p>
                  <p className="map-num map-num--warn text-[48px]">{vnd(Math.round(missed), lang)}</p>
                  <p className="text-sm">{x.vs(best.name, pct(best.rate, lang))}</p>
                </>
              ) : (
                <p className="map-hand text-[24px]">{x.top}</p>
              )
            ) : (
              <p className="text-sm">{x.spread(vnd(Math.round(spread), lang))}</p>
            )}
          </div>
          <p className="text-xs text-[var(--map-muted)]">{x.basis}</p>
          <Link href={href(lang, "/lai-suat-tiet-kiem")} className="map-hand text-[20px]">
            {x.compare} →
          </Link>
        </form>
      </section>

      <p className="sv-container map-hand text-[22px]">{x.scroll}</p>

      <Trail labels={x.stations}>
        <Station side="left" tag={`1 · ${x.stations[0]}`} title={x.s1.h}>
          <p>{x.s1.p(pct(inflation, lang))}</p>
          <input type="range" min={1} max={30} value={years} onChange={(e) => setYears(+e.target.value)} aria-label={x.s1.years} />
          <p>
            {x.s1.r(years)} <span className="map-num map-num--warn text-[40px]">{Math.round(realValue(years, 0, inflation))}đ</span>,{" "}
            {x.s1.r2} <span className="map-num text-[40px]">{best ? Math.round(realValue(years, best.rate, inflation)) : "—"}đ</span> {x.s1.r3}
          </p>
          <Link href={href(lang, "/hoc/lam-phat")}>{x.s1.more} →</Link>
        </Station>

        <Station side="right" tag={`2 · ${x.stations[1]}`} title={x.s2.h}>
          {portfolio && fan ? (
            <>
              <p>{x.s2.p}</p>
              <label className="map-hand block text-[20px]">
                {portfolio.name}
                <input type="range" min={1} max={portfolios.length} value={level} onChange={(e) => setLevel(+e.target.value)} />
              </label>
              <Fan paths={paths} label={x.s2.h} />
              <p>{x.s2.r(Math.round(fan.low) + "đ", Math.round(fan.high) + "đ", `${Math.round(fan.loss * 100)}%`)}</p>
              <Link href={href(lang, "/danh-muc-mau")}>{x.s2.more} →</Link>
            </>
          ) : (
            <p>{x.s2.none}</p>
          )}
        </Station>

        <Station side="left" tag={`3 · ${x.stations[2]}`} title={x.s3.h}>
          <label className="map-hand block text-[20px]">
            {x.s3.goal}: <b>{vndShort(goal * 1e6, lang)}</b>
            <input type="range" min={100} max={5000} step={100} value={goal} onChange={(e) => setGoal(+e.target.value)} />
          </label>
          <label className="map-hand block text-[20px]">
            {x.s3.years}: <b>{goalYears}</b>
            <input type="range" min={1} max={30} value={goalYears} onChange={(e) => setGoalYears(+e.target.value)} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-sm">{x.s3.safe}</p>
              <p className="map-num map-num--warn text-[30px]">{best ? vndShort(monthlyFor(goal * 1e6, goalYears, best.rate), lang) : "—"}</p>
              <p className="text-xs">{x.s3.perMonth}</p>
            </div>
            {balanced ? (
              <div>
                <p className="text-sm">{x.s3.bal(balanced.name)}</p>
                <p className="map-num text-[30px]">{vndShort(monthlyFor(goal * 1e6, goalYears, balanced.expectedReturn), lang)}</p>
                <p className="text-xs">{x.s3.perMonth}</p>
              </div>
            ) : null}
          </div>
          <p className="text-xs text-[var(--map-muted)]">{x.s3.note}</p>
          <Link href={href(lang, "/muc-tieu")}>{x.s3.more} →</Link>
        </Station>

        <Station side="right" tag={`4 · ${x.stations[3]}`} title={x.s4.h}>
          <p>{x.s4.p}</p>
          <input type="range" min={3} max={24} value={reserve} onChange={(e) => setReserve(+e.target.value)} aria-label={x.s4.months} />
          <div className="grid grid-cols-3 gap-2">
            {chests.map((v, i) => (
              <div key={x.s4.chests[i]} className="map-chest">
                <span className="map-hand text-[18px]">{x.s4.chests[i]}</span>
                <b className="map-num block text-[22px]">{vndShort(v * 1e6, lang)}</b>
              </div>
            ))}
          </div>
          <p className="flex flex-wrap gap-x-4">
            <Link href={href(lang, "/bang-can-doi")}>{x.s4.more} →</Link>
            <Link href={href(lang, "/lap-ke-hoach")}>{x.s4.hub} →</Link>
          </p>
        </Station>
      </Trail>

      <section className="sv-container space-y-6 py-14" aria-labelledby="map-learn">
        <h2 id="map-learn" className="map-title text-[clamp(36px,4vw,56px)]">
          {x.learn}
        </h2>
        <p>{x.learnIntro}</p>
        <LessonScraps lang={lang} lessons={lessons} showCount />
        <Link href={href(lang, "/hoc")} className="map-hand text-[22px]">
          {x.all} →
        </Link>
      </section>
    </div>
  );
}

function Station({ side, tag, title, children }: { side: "left" | "right"; tag: string; title: string; children: React.ReactNode }) {
  return (
    <div className={`relative z-10 md:w-[46%] ${side === "right" ? "md:ml-auto" : ""}`}>
      <div className="map-card space-y-3">
        <p className="map-hand text-[20px] text-[var(--map-teal)]">{tag}</p>
        <h3 className="map-title text-[30px]">{title}</h3>
        {children}
      </div>
    </div>
  );
}

/** Stations on a dotted trail; a coin in a conical hat walks it as you scroll (wide screens). */
function Trail({ labels, children }: { labels: string[]; children: React.ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const path = useRef<SVGPathElement>(null);
  const coin = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const walk = () => {
      const b = box.current;
      const p = path.current;
      const c = coin.current;
      if (!b || !p || !c) return;
      const r = b.getBoundingClientRect();
      const k = Math.min(1, Math.max(0, (innerHeight * 0.55 - r.top) / r.height));
      const L = p.getTotalLength();
      const at = p.getPointAtLength(k * L);
      const next = p.getPointAtLength(Math.min(L, k * L + 4));
      c.style.left = `${(at.x / 1000) * r.width}px`;
      c.style.top = `${(at.y / 1000) * r.height}px`;
      c.style.transform = `scaleX(${next.x < at.x ? -1 : 1})`;
    };
    walk();
    addEventListener("scroll", walk, { passive: true });
    addEventListener("resize", walk);
    return () => {
      removeEventListener("scroll", walk);
      removeEventListener("resize", walk);
    };
  }, []);

  const spots = [
    { left: "62%", top: "14%" },
    { left: "18%", top: "38%" },
    { left: "64%", top: "62%" },
    { left: "16%", top: "86%" },
  ];
  const icons = ["🏘️", "⛰️", "🏔️", "⚓"];
  return (
    <div ref={box} className="sv-container relative space-y-16 py-10">
      <svg className="pointer-events-none absolute inset-0 hidden h-full w-full md:block" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">
        <path
          ref={path}
          d="M500 0 C 900 80, 900 200, 640 260 S 100 360, 220 500 S 900 620, 780 760 S 120 860, 300 1000"
          fill="none"
          className="map-trail"
          strokeWidth="4"
          strokeDasharray="2 14"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {spots.map((s, i) => (
        <span key={labels[i]} className="pointer-events-none absolute hidden text-center md:block" style={{ left: s.left, top: s.top }} aria-hidden="true">
          <span className="block text-[64px] leading-none">{icons[i]}</span>
          <span className="map-label">{labels[i]}</span>
        </span>
      ))}
      <svg ref={coin} viewBox="0 0 80 80" className="pointer-events-none absolute z-20 hidden h-16 w-16 md:block" style={{ marginLeft: -32, marginTop: -32 }} aria-hidden="true">
        <path d="M8 34 L40 6 L72 34 Z" fill="#c9a24a" stroke="#3b2617" strokeWidth="3" />
        <circle cx="40" cy="48" r="26" fill="#f2c14e" stroke="#3b2617" strokeWidth="3" />
        <circle cx="40" cy="48" r="17" fill="none" stroke="#3b2617" strokeWidth="2" strokeDasharray="3 3" />
        <text x="40" y="55" textAnchor="middle" fontWeight="900" fontSize="20" fill="#3b2617">
          đ
        </text>
      </svg>
      {children}
    </div>
  );
}

/** Ten-year paths of 100 VND: one series, thin lines, dashed start line. */
function Fan({ paths, label }: { paths: number[][]; label: string }) {
  const W = 600;
  const H = 200;
  const max = 400;
  const x = (i: number) => 10 + (i / 10) * (W - 20);
  const y = (v: number) => H - 10 - (Math.min(v, max) / max) * (H - 20);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-44 w-full" role="img" aria-label={label}>
      <line x1={10} x2={W - 10} y1={y(100)} y2={y(100)} stroke="var(--map-ink)" strokeDasharray="4 4" strokeOpacity={0.6} />
      {paths.map((p, i) => (
        <path
          key={i}
          d={p.map((v, j) => `${j ? "L" : "M"}${x(j).toFixed(1)},${y(v).toFixed(1)}`).join("")}
          fill="none"
          stroke="var(--map-teal)"
          strokeOpacity={0.4}
          strokeWidth={1.5}
        />
      ))}
    </svg>
  );
}
