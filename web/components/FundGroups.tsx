"use client";

import { useState } from "react";

import type { Lang } from "@/lib/format";
import type { FundGroup, FundStats } from "@/lib/types";

type GroupId = keyof FundStats["groups"];
const one = (v: number, lang: Lang) =>
  `${v.toLocaleString(lang === "vi" ? "vi-VN" : "en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;

const ORDER: GroupId[] = ["equity_fund", "etf", "balanced_fund", "bond_fund"];

const TEXT = {
  vi: {
    groups: { equity_fund: "Quỹ mở cổ phiếu", etf: "ETF và quỹ niêm yết", balanced_fund: "Quỹ mở cân bằng", bond_fund: "Quỹ mở trái phiếu" },
    bench: { eq_large: "VN30 gồm cổ tức", cash_vnd: "Tiền gửi 12 tháng", balanced: "50% VN30, 50% tiền gửi" },
    horizon: (h: number) => `${h} năm`,
    pick: "Kỳ tính lợi nhuận",
    perYear: "lợi nhuận bình quân mỗi năm",
    legend: ["Khoảng 50% quỹ ở giữa", "Trung vị", "Thấp nhất – cao nhất", "Mốc so sánh"],
    beat: (p: string, b: string) => `${p} số quỹ thắng ${b}`,
    funds: (n: number, h: string) => `${n} quỹ đủ dữ liệu ${h} năm`,
    noData: "Chưa đủ dữ liệu",
    table: "Bảng số",
    group: "Nhóm",
    median: "Trung vị",
    range: "25% – 75%",
    benchmark: "Mốc",
    beatCol: "Thắng mốc",
    vol: "Biến động (trung vị)",
    mdd: "Sụt giảm lớn nhất 5 năm (trung vị)",
  },
  en: {
    groups: { equity_fund: "Open-end equity funds", etf: "ETFs and listed funds", balanced_fund: "Open-end balanced funds", bond_fund: "Open-end bond funds" },
    bench: { eq_large: "VN30 with dividends", cash_vnd: "12-month deposits", balanced: "50% VN30, 50% deposits" },
    horizon: (h: number) => `${h} yr`,
    pick: "Return period",
    perYear: "average return per year",
    legend: ["Middle 50% of funds", "Median", "Lowest – highest", "Benchmark"],
    beat: (p: string, b: string) => `${p} of funds beat ${b}`,
    funds: (n: number, h: string) => `${n} funds with ${h} years of data`,
    noData: "Not enough data yet",
    table: "The numbers",
    group: "Group",
    median: "Median",
    range: "25% – 75%",
    benchmark: "Benchmark",
    beatCol: "Beat it",
    vol: "Volatility (median)",
    mdd: "Worst 5-year drawdown (median)",
  },
};

export function FundGroups({ lang, stats }: { lang: Lang; stats: FundStats }) {
  const x = TEXT[lang];
  const [h, setH] = useState("3");
  const p = (v: number | null | undefined) => (v == null ? "–" : one(v, lang));
  const share = (v: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const rows = ORDER.map((id) => ({ id, g: stats.groups[id] as FundGroup })).filter((r) => r.g && r.g.count > 0);
  const all = rows.flatMap(({ g }) => {
    const s = g.horizons[h];
    return [s?.stats?.min, s?.stats?.max, s?.benchmark].filter((v): v is number => v != null);
  });
  const lo = Math.min(-5, ...all);
  const hi = Math.max(10, ...all);
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3" role="group" aria-label={x.pick}>
        <span className="t-small text-muted">{x.pick}</span>
        {stats.horizons.map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={h === String(n)}
            onClick={() => setH(String(n))}
            className={`rounded-full border px-4 py-1.5 t-small font-semibold ${h === String(n) ? "border-ink bg-ink text-surface" : "border-line bg-surface"}`}
          >
            {x.horizon(n)}
          </button>
        ))}
        <span className="t-small text-muted">· {x.perYear}</span>
      </div>

      <ul className="flex flex-wrap gap-x-5 gap-y-1 t-small">
        <li>
          <span className="inline-block h-3 w-5 rounded-sm align-middle" style={{ background: "color-mix(in srgb, var(--series-1) 45%, transparent)" }} aria-hidden="true" /> {x.legend[0]}
        </li>
        <li>
          <span className="inline-block h-3 w-1 bg-ink align-middle" aria-hidden="true" /> {x.legend[1]}
        </li>
        <li>
          <span className="inline-block w-5 border-t-2 border-line-strong align-middle" aria-hidden="true" /> {x.legend[2]}
        </li>
        <li>
          <span className="inline-block h-3 w-3 rotate-45 align-middle" style={{ background: "var(--series-2)" }} aria-hidden="true" /> {x.legend[3]}
        </li>
      </ul>

      <ul className="space-y-6">
        {rows.map(({ id, g }) => {
          const s = g.horizons[h];
          const st = s?.stats;
          const label = `${x.groups[id]}: ${st ? `${x.median} ${p(st.p50)}, ${x.range} ${p(st.p25)}–${p(st.p75)}` : x.noData}; ${x.bench[g.benchmark]} ${p(s?.benchmark)}`;
          return (
            <li key={id} className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-semibold">
                  {x.groups[id]} <span className="t-small font-normal text-muted">· {x.funds(st?.n ?? 0, h)}</span>
                </p>
                {s?.beat != null ? <p className="t-small">{x.beat(share(s.beat), x.bench[g.benchmark])}</p> : null}
              </div>
              <div className="relative h-12" role="img" aria-label={label}>
                <span className="absolute inset-y-0 w-px bg-line-strong" style={{ left: pos(0) }} />
                {st ? (
                  <>
                    <span className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-line-strong" style={{ left: pos(st.min), width: `calc(${pos(st.max)} - ${pos(st.min)})` }} />
                    <span
                      className="absolute top-1/2 h-6 -translate-y-1/2 rounded-md"
                      style={{ left: pos(st.p25), width: `calc(${pos(st.p75)} - ${pos(st.p25)})`, background: "color-mix(in srgb, var(--series-1) 45%, transparent)", border: "1.5px solid var(--series-1)" }}
                      title={`${x.range}: ${p(st.p25)} – ${p(st.p75)}`}
                    />
                    <span className="absolute top-1/2 h-8 w-1 -translate-x-1/2 -translate-y-1/2 rounded bg-ink" style={{ left: pos(st.p50) }} title={`${x.median}: ${p(st.p50)}`} />
                  </>
                ) : (
                  <span className="absolute inset-0 grid place-items-center t-small text-muted">{x.noData}</span>
                )}
                {s?.benchmark != null ? (
                  <span
                    className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rotate-45 border-2 border-surface"
                    style={{ left: pos(s.benchmark), background: "var(--series-2)" }}
                    title={`${x.bench[g.benchmark]}: ${p(s.benchmark)}`}
                  />
                ) : null}
              </div>
              <p className="flex flex-wrap gap-x-4 t-small text-muted tabular-nums">
                {st ? (
                  <span>
                    {x.median} <b className="text-ink">{p(st.p50)}</b> · {x.range} {p(st.p25)} – {p(st.p75)}
                  </span>
                ) : null}
                <span>
                  {x.bench[g.benchmark]} <b className="text-ink">{p(s?.benchmark)}</b>
                </span>
              </p>
            </li>
          );
        })}
      </ul>
      <div className="flex justify-between t-caption text-muted tabular-nums">
        <span>{p(lo)}</span>
        <span>{p(hi)}</span>
      </div>

      <div className="space-y-2">
        <h3 className="t-h3">{x.table}</h3>
        <div className="sv-table-wrap" role="region" aria-label={x.table} tabIndex={0}>
          <table className="sv-table min-w-[48rem]">
            <thead>
              <tr>
                <th scope="col">{x.group}</th>
                {stats.horizons.map((n) => (
                  <th key={n} scope="col" className="sv-num">
                    {x.median} {x.horizon(n)}
                  </th>
                ))}
                <th scope="col" className="sv-num">
                  {x.beatCol} ({x.horizon(Number(h))})
                </th>
                <th scope="col" className="sv-num">{x.vol}</th>
                <th scope="col" className="sv-num">{x.mdd}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ id, g }) => (
                <tr key={id}>
                  <th scope="row">
                    {x.groups[id]}
                    <span className="sv-sub">
                      {x.benchmark}: {x.bench[g.benchmark]}
                    </span>
                  </th>
                  {stats.horizons.map((n) => {
                    const s = g.horizons[String(n)];
                    return (
                      <td key={n} className="sv-num">
                        {p(s?.stats?.p50)}
                        <span className="sv-sub">
                          {x.benchmark} {p(s?.benchmark)}
                        </span>
                      </td>
                    );
                  })}
                  <td className="sv-num">{share(g.horizons[h]?.beat ?? null)}</td>
                  <td className="sv-num">{p(g.volatility?.p50)}</td>
                  <td className="sv-num">{p(g.max_drawdown?.p50)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
