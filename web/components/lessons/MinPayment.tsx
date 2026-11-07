"use client";

import { useState } from "react";

import { pct, vnd, vndShort, type Lang } from "@/lib/format";
import { payoff } from "@/lib/lessons";

import { Quiz, Step } from "./Parts";

export type CardApr = { id: number; label: string; apr: number; freeDays: number | null; source: string | null };

const TEXT = {
  vi: {
    s1: "Nợ thẻ, trả tối thiểu mỗi tháng",
    p1: "Giả sử bạn không tiêu thêm và chỉ trả mức tối thiểu. Lãi suất là mức thật của thẻ bạn chọn. Mức trả tối thiểu là giả định: hãy xem đúng con số trên sao kê của bạn.",
    card: "Thẻ",
    balance: "Dư nợ",
    min: (p: number) => `Trả tối thiểu: ${p}% dư nợ mỗi tháng (ít nhất 100.000 ₫)`,
    fixed: "Hoặc trả cố định mỗi tháng",
    months: "Thời gian trả hết",
    interest: "Tổng tiền lãi",
    never: "Không bao giờ hết nợ: khoản trả không đủ bù tiền lãi.",
    m: (n: number) => (n >= 12 ? `${Math.floor(n / 12)} năm ${n % 12} tháng` : `${n} tháng`),
    minLabel: "Trả tối thiểu",
    fixedLabel: "Trả cố định",
    s2: "Bạn thật sự trả bao nhiêu?",
    principal: "Tiền gốc",
    int: "Tiền lãi",
    s3: "Thử một câu",
    q: "Bạn trả đủ toàn bộ dư nợ sao kê trước hạn thanh toán. Bạn trả bao nhiêu lãi cho các giao dịch mua sắm đó?",
    opts: ["0 đồng", "Bằng lãi suất năm của thẻ", "Một nửa", "Tuỳ số giao dịch"],
    why: "Trả đủ dư nợ sao kê đúng hạn thì không mất lãi mua sắm trong thời gian miễn lãi. Trả thiếu thì thường bị tính lãi từ ngày giao dịch: hãy đọc điều khoản của thẻ.",
    apr: (r: string, d: number | null) => `lãi suất ${r}/năm${d ? `, miễn lãi tối đa ${d} ngày` : ""}`,
    none: "Chưa có lãi suất thẻ đã kiểm tra.",
  },
  en: {
    s1: "Card debt, paying the minimum",
    p1: "Say you stop spending and pay only the minimum. The interest rate is the real rate of the card you pick. The minimum is an assumption: check the figure on your statement.",
    card: "Card",
    balance: "Balance",
    min: (p: number) => `Minimum: ${p}% of the balance a month (at least ₫100,000)`,
    fixed: "Or pay a fixed amount each month",
    months: "Time to clear it",
    interest: "Total interest",
    never: "Never paid off: the payment does not cover the interest.",
    m: (n: number) => (n >= 12 ? `${Math.floor(n / 12)} yr ${n % 12} mo` : `${n} months`),
    minLabel: "Minimum",
    fixedLabel: "Fixed",
    s2: "What do you really pay?",
    principal: "Principal",
    int: "Interest",
    s3: "Try one",
    q: "You pay the whole statement balance before the due date. How much interest do you pay on those purchases?",
    opts: ["Nothing", "The card's yearly rate", "Half of it", "Depends on the purchases"],
    why: "Paying the full statement balance on time means no purchase interest within the interest-free period. Paying less usually means interest from the purchase date: read your card's terms.",
    apr: (r: string, d: number | null) => `rate ${r} a year${d ? `, up to ${d} interest-free days` : ""}`,
    none: "No checked card interest rates yet.",
  },
};

export function MinPaymentLesson({ lang, cards }: { lang: Lang; cards: CardApr[] }) {
  const x = TEXT[lang];
  const [cardId, setCardId] = useState(cards[Math.floor(cards.length / 2)]?.id ?? 0);
  const [balance, setBalance] = useState(20);
  const [minPct, setMinPct] = useState(5);
  const [fixed, setFixed] = useState(2);
  if (!cards.length) return <p>{x.none}</p>;
  const card = cards.find((c) => c.id === cardId) ?? cards[0];
  const b = balance * 1e6;
  const min = payoff(b, card.apr, minPct, 100_000);
  const fix = payoff(b, card.apr, minPct, 100_000, fixed * 1e6);
  const rows: [string, typeof min][] = [
    [x.minLabel, min],
    [x.fixedLabel, fix],
  ];
  const most = Math.max(...rows.map(([, r]) => (r.never ? 0 : r.paid)), b);

  return (
    <div className="space-y-10">
      <Step n={1} title={x.s1}>
        <p>{x.p1}</p>
        <label className="map-hand block text-[20px]">
          {x.card}
          <select className="map-input" value={card.id} onChange={(e) => setCardId(+e.target.value)}>
            {cards.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} · {pct(c.apr, lang)}
              </option>
            ))}
          </select>
        </label>
        <p className="text-sm">
          {x.apr(pct(card.apr, lang), card.freeDays)}
          {card.source ? (
            <>
              {" · "}
              <a href={card.source} target="_blank" rel="noopener noreferrer">
                {lang === "vi" ? "nguồn" : "source"}
              </a>
            </>
          ) : null}
        </p>
        <label className="map-hand block text-[20px]">
          {x.balance}: <b>{vnd(b, lang)}</b>
          <input type="range" min={5} max={100} step={5} value={balance} onChange={(e) => setBalance(+e.target.value)} />
        </label>
        <label className="map-hand block text-[20px]">
          {x.min(minPct)}
          <input type="range" min={1} max={10} value={minPct} onChange={(e) => setMinPct(+e.target.value)} />
        </label>
        <label className="map-hand block text-[20px]">
          {x.fixed}: <b>{vnd(fixed * 1e6, lang)}</b>
          <input type="range" min={0.5} max={10} step={0.5} value={fixed} onChange={(e) => setFixed(+e.target.value)} />
        </label>
        <div className="grid gap-4 sm:grid-cols-2" aria-live="polite">
          {rows.map(([label, r], i) => (
            <div key={label} className="map-chest text-left">
              <p className="map-hand text-[20px]">{label}</p>
              {r.never ? (
                <p className="font-semibold text-[var(--map-terra)]">{x.never}</p>
              ) : (
                <>
                  <p className="text-sm">{x.months}</p>
                  <p className={`map-num text-[30px] ${i === 0 ? "map-num--warn" : ""}`}>{x.m(r.months)}</p>
                  <p className="text-sm">{x.interest}</p>
                  <p className={`map-num text-[30px] ${i === 0 ? "map-num--warn" : ""}`}>{vnd(Math.round(r.interest), lang)}</p>
                </>
              )}
            </div>
          ))}
        </div>
      </Step>

      <Step n={2} title={x.s2}>
        <ul className="flex flex-wrap gap-4 text-sm">
          <li>
            <span className="mp-swatch" style={{ background: "var(--series-1)" }} aria-hidden="true" /> {x.principal}
          </li>
          <li>
            <span className="mp-swatch" style={{ background: "var(--series-4)" }} aria-hidden="true" /> {x.int}
          </li>
        </ul>
        <div className="space-y-3">
          {rows.map(([label, r]) =>
            r.never ? null : (
              <div key={label} className="space-y-1">
                <p className="text-sm font-semibold">
                  {label}: {vndShort(Math.round(r.paid), lang)}
                </p>
                <div
                  className="mp-bar"
                  role="img"
                  aria-label={`${label}: ${x.principal} ${vnd(b, lang)}, ${x.int} ${vnd(Math.round(r.interest), lang)}`}
                >
                  <span style={{ width: `${(100 * b) / most}%`, background: "var(--series-1)" }} />
                  <span style={{ width: `${(100 * r.interest) / most}%`, background: "var(--series-4)" }} />
                </div>
              </div>
            ),
          )}
        </div>
      </Step>

      <Step n={3} title={x.s3}>
        <Quiz lang={lang} question={x.q} options={x.opts} answer={0} why={x.why} />
      </Step>
    </div>
  );
}
