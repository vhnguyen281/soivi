"use client";

import { useState } from "react";

import { pct, vnd, type Lang } from "@/lib/format";
import { earlyWithdrawal } from "@/lib/lessons";

import { Quiz, Step } from "./Parts";

export type Offer = { bank: string; product: string; channel: string; payment: string; rate: number; equivalent: number; source: string | null };
export type Demand = { bank: string; rate: number };

const TEXT = {
  vi: {
    bank: "Chọn một ngân hàng",
    s1: "Cùng ngân hàng, cùng 12 tháng, nhiều mức lãi",
    p1: "Lãi suất thay đổi theo kênh gửi (tại quầy hay online) và cách trả lãi (cuối kỳ, hàng tháng, trả trước). Cột “quy đổi” là mức tương đương lãi cuối kỳ, để so sánh công bằng.",
    product: "Sản phẩm",
    channel: "Kênh",
    payment: "Trả lãi",
    rate: "Niêm yết",
    eq: "Quy đổi",
    src: "Nguồn",
    s2: "Rút trước hạn thì còn bao nhiêu?",
    p2: "Nhiều ngân hàng chỉ trả lãi không kỳ hạn cho khoản rút trước hạn. Điều khoản cụ thể khác nhau: hãy đọc kỹ hợp đồng của ngân hàng bạn.",
    amount: "Số tiền gửi",
    held: (m: number) => `Rút sau ${m} tháng (kỳ hạn 12 tháng)`,
    keep: "Nếu giữ đủ 12 tháng",
    early: "Nếu rút lúc này",
    lost: "Phần lãi mất đi so với lãi suất kỳ hạn",
    demandOf: (b: string, r: string) => `lãi không kỳ hạn ${b}: ${r}`,
    demandFallback: (b: string, r: string) => `ngân hàng này chưa có số liệu lãi không kỳ hạn đã kiểm tra; dùng mức cao nhất đã kiểm tra (${b} ${r})`,
    s3: "Thử một câu",
    q: "Hai mức lãi 12 tháng: 6,0% trả cuối kỳ và 5,85% trả hàng tháng. Nhận lãi hàng tháng có thiệt không?",
    opts: ["Thiệt nhiều", "Gần như ngang nhau, vì lãi về sớm có thể gửi tiếp", "Luôn lợi hơn", "Không so được"],
    why: "Lãi trả hàng tháng thấp hơn trên giấy, nhưng tiền về sớm có thể sinh lãi tiếp. Vì vậy SoiVí quy đổi mọi cách trả lãi về một mức tương đương để so.",
    none: "Chưa có lãi suất 12 tháng đã kiểm tra.",
  },
  en: {
    bank: "Pick a bank",
    s1: "Same bank, same 12 months, several rates",
    p1: "Rates change with the channel (branch or online) and how interest is paid (at the end, monthly, upfront). The “equivalent” column converts each to end-of-term interest so they compare fairly.",
    product: "Product",
    channel: "Channel",
    payment: "Interest",
    rate: "Advertised",
    eq: "Equivalent",
    src: "Source",
    s2: "What if you withdraw early?",
    p2: "Many banks pay only the demand rate on early withdrawals. Terms differ: read your bank's contract.",
    amount: "Amount on deposit",
    held: (m: number) => `Withdraw after ${m} months (12-month term)`,
    keep: "Kept the full 12 months",
    early: "Withdrawn now",
    lost: "Interest lost against the term rate",
    demandOf: (b: string, r: string) => `${b} demand rate: ${r}`,
    demandFallback: (b: string, r: string) => `no checked demand rate for this bank; using the highest checked (${b} ${r})`,
    s3: "Try one",
    q: "Two 12-month rates: 6.0% paid at the end and 5.85% paid monthly. Do you lose by taking it monthly?",
    opts: ["A lot", "About the same, since early interest can earn more", "Always better", "Can't compare"],
    why: "Monthly interest looks lower on paper, but money paid earlier can earn more. That is why SoiVí converts every payment style to one equivalent rate.",
    none: "No checked 12-month rates yet.",
  },
};

export function RealRateLesson({
  lang,
  offers,
  demand,
  channels,
  payments,
}: {
  lang: Lang;
  offers: Offer[];
  demand: Demand[];
  channels: Record<string, string>;
  payments: Record<string, string>;
}) {
  const x = TEXT[lang];
  const banks = [...new Set(offers.map((o) => o.bank))].sort();
  const withChoice = banks.find((b) => new Set(offers.filter((o) => o.bank === b).map((o) => o.payment)).size > 1) ?? banks[0];
  const [bank, setBank] = useState(withChoice ?? "");
  const [amount, setAmount] = useState(100_000_000);
  const [months, setMonths] = useState(6);
  if (!banks.length) return <p>{x.none}</p>;

  const mine = offers.filter((o) => o.bank === bank).sort((a, b) => b.equivalent - a.equivalent);
  const endRate = Math.max(...mine.filter((o) => o.payment === "end").map((o) => o.rate), ...(mine.some((o) => o.payment === "end") ? [] : mine.map((o) => o.rate)));
  const own = demand.find((d) => d.bank === bank);
  const fallback = [...demand].sort((a, b) => b.rate - a.rate)[0];
  const dem = own ?? fallback;
  const r = earlyWithdrawal(amount, endRate, 12, dem?.rate ?? 0, months);
  const nf = (v: number) => v.toLocaleString(lang === "vi" ? "vi-VN" : "en-US");

  return (
    <div className="space-y-10">
      <label className="map-hand block max-w-sm text-[22px]">
        {x.bank}
        <select className="map-input" value={bank} onChange={(e) => setBank(e.target.value)}>
          {banks.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>
      </label>

      <Step n={1} title={x.s1}>
        <p>{x.p1}</p>
        <div className="sv-table-wrap" role="region" aria-label={x.s1} tabIndex={0}>
          <table className="sv-table min-w-[40rem]">
            <thead>
              <tr>
                <th scope="col">{x.product}</th>
                <th scope="col">{x.channel}</th>
                <th scope="col">{x.payment}</th>
                <th scope="col" className="text-right">{x.rate}</th>
                <th scope="col" className="text-right">{x.eq}</th>
                <th scope="col">{x.src}</th>
              </tr>
            </thead>
            <tbody>
              {mine.map((o, i) => (
                <tr key={`${o.product}-${o.channel}-${o.payment}-${i}`}>
                  <th scope="row">{o.product}</th>
                  <td>{channels[o.channel] ?? o.channel}</td>
                  <td>{payments[o.payment] ?? o.payment}</td>
                  <td className="text-right tabular-nums">{pct(o.rate, lang)}</td>
                  <td className="text-right tabular-nums font-semibold">{pct(o.equivalent, lang)}</td>
                  <td>{o.source ? <a href={o.source} rel="noopener noreferrer" target="_blank">{bank}</a> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Step>

      <Step n={2} title={x.s2}>
        <p>{x.p2}</p>
        <label className="map-hand block text-[20px]">
          {x.amount}
          <input className="map-input" inputMode="numeric" value={nf(amount)} onChange={(e) => setAmount(Number(e.target.value.replace(/\D/g, "").slice(0, 13)) || 0)} />
        </label>
        <label className="map-hand block text-[20px]">
          {x.held(months)}
          <input type="range" min={1} max={11} value={months} onChange={(e) => setMonths(+e.target.value)} />
        </label>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-sm">{x.keep} ({pct(endRate, lang)})</p>
            <p className="map-num text-[30px]">{vnd(Math.round(r.atMaturity), lang)}</p>
          </div>
          <div>
            <p className="text-sm">{x.early}</p>
            <p className="map-num map-num--warn text-[30px]">{vnd(Math.round(r.early), lang)}</p>
          </div>
          <div>
            <p className="text-sm">{x.lost}</p>
            <p className="map-num map-num--warn text-[30px]">{vnd(Math.round(r.lost), lang)}</p>
          </div>
        </div>
        {dem ? (
          <p className="text-xs text-[var(--map-muted)]">
            {own ? x.demandOf(own.bank, pct(own.rate, lang)) : x.demandFallback(dem.bank, pct(dem.rate, lang))}
          </p>
        ) : null}
      </Step>

      <Step n={3} title={x.s3}>
        <Quiz lang={lang} question={x.q} options={x.opts} answer={1} why={x.why} />
      </Step>
    </div>
  );
}
