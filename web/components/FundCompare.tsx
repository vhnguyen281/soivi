"use client";

import { useMemo, useState } from "react";

import type { Lang } from "@/lib/format";
import type { FundRow, FundStats } from "@/lib/types";

type Group = FundRow["group"];
const GROUPS: Group[] = ["equity_fund", "etf", "balanced_fund", "bond_fund"];
const BENCH: Record<Group, "eq_large" | "cash_vnd" | "balanced"> = {
  equity_fund: "eq_large",
  etf: "eq_large",
  balanced_fund: "balanced",
  bond_fund: "cash_vnd",
};

const TEXT = {
  vi: {
    title: "So sánh từng quỹ",
    groups: { equity_fund: "Quỹ cổ phiếu", etf: "ETF & quỹ niêm yết", balanced_fund: "Quỹ cân bằng", bond_fund: "Quỹ trái phiếu" } as Record<Group, string>,
    all: "Tất cả",
    search: "Tìm mã quỹ hoặc công ty",
    scatter: "Rủi ro và lợi nhuận 3 năm",
    scatterNote: "Mỗi chấm là một quỹ. Càng lên cao lợi nhuận càng lớn; càng sang phải dao động càng mạnh.",
    axisX: "Biến động mỗi năm (36 tháng) →",
    vn30: "VN30 gồm cổ tức",
    deposit: "Tiền gửi 12 tháng",
    noPoint: (n: number) => `${n} quỹ chưa đủ 3 năm dữ liệu nên không có trên biểu đồ.`,
    legendMine: "Quỹ trong nhóm",
    legendOthers: "Quỹ nhóm khác",
    cols: { ticker: "Quỹ", group: "Nhóm", r1: "1 năm", r3: "3 năm", r5: "5 năm", vol: "Biến động", mdd: "Sụt giảm lớn nhất", beat: "So với mốc (3 năm)" },
    beat: "Thắng mốc",
    lag: "Thua mốc",
    since: (d: string) => `từ ${d}`,
    shown: (n: number, all: number) => `${n} / ${all} quỹ`,
    sortHint: "Bấm tiêu đề cột để sắp xếp",
    flagged: (m: string, v: string) => `Dữ liệu nguồn bất thường (tháng ${m}: ${v}), chưa hiển thị số`,
    source: "Nguồn NAV: CafeF qua vnstock, chưa đối chiếu với từng công ty quản lý quỹ. Chỉ công bố số liệu tính ra; ETF tính theo giá giao dịch.",
  },
  en: {
    title: "Fund by fund",
    groups: { equity_fund: "Equity funds", etf: "ETFs & listed funds", balanced_fund: "Balanced funds", bond_fund: "Bond funds" } as Record<Group, string>,
    all: "All",
    search: "Search a fund code or manager",
    scatter: "Risk and 3-year return",
    scatterNote: "Each dot is a fund. Higher means more return; further right means bigger swings.",
    axisX: "Volatility a year (36 months) →",
    vn30: "VN30 with dividends",
    deposit: "12-month deposits",
    noPoint: (n: number) => `${n} funds have less than 3 years of data and are not plotted.`,
    legendMine: "Funds in the group",
    legendOthers: "Other funds",
    cols: { ticker: "Fund", group: "Group", r1: "1 yr", r3: "3 yr", r5: "5 yr", vol: "Volatility", mdd: "Worst drawdown", beat: "Vs benchmark (3 yr)" },
    beat: "Beat",
    lag: "Lagged",
    since: (d: string) => `since ${d}`,
    shown: (n: number, all: number) => `${n} / ${all} funds`,
    sortHint: "Tap a column header to sort",
    flagged: (m: string, v: string) => `Implausible source data (${m}: ${v}); figures withheld`,
    source: "NAV source: CafeF via vnstock, not checked with each fund manager. Only derived figures are published; ETFs use trading prices.",
  },
};

type SortKey = "ticker" | "r1" | "r3" | "r5" | "vol" | "mdd";

export function FundCompare({ lang, stats }: { lang: Lang; stats: FundStats }) {
  const x = TEXT[lang];
  const one = (v: number | null | undefined) =>
    v == null ? "–" : `${v.toLocaleString(lang === "vi" ? "vi-VN" : "en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
  const [group, setGroup] = useState<Group | "all">("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "r3", desc: true });
  const bench = (g: Group) => stats.benchmarks[BENCH[g]]?.["3"] ?? null;

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const value = (f: FundRow): number | string | null =>
      sort.key === "ticker" ? f.ticker : sort.key === "vol" ? f.volatility : sort.key === "mdd" ? f.max_drawdown : f.returns[sort.key.slice(1)];
    return stats.funds
      .filter((f) => (group === "all" || f.group === group) && (!q || f.ticker.toLowerCase().includes(q) || f.manager.toLowerCase().includes(q)))
      .sort((a, b) => {
        const va = value(a);
        const vb = value(b);
        if (va == null) return 1;
        if (vb == null) return -1;
        const c = typeof va === "string" ? va.localeCompare(String(vb)) : va - (vb as number);
        return sort.desc ? -c : c;
      });
  }, [stats.funds, group, query, sort]);

  const header = (key: SortKey, label: string, num = true) => (
    <th scope="col" className={num ? "sv-num" : ""} aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}>
      <button type="button" className="font-semibold" onClick={() => setSort({ key, desc: sort.key === key ? !sort.desc : key !== "ticker" })}>
        {label}
        {sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}
      </button>
    </th>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        {(["all", ...GROUPS] as const).map((g) => (
          <button
            key={g}
            type="button"
            aria-pressed={group === g}
            onClick={() => setGroup(g)}
            className={`rounded-full border px-4 py-1.5 t-small font-semibold ${group === g ? "border-ink bg-ink text-surface" : "border-line bg-surface"}`}
          >
            {g === "all" ? x.all : x.groups[g]}
          </button>
        ))}
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={x.search}
          aria-label={x.search}
          className="sv-input ml-auto !min-h-10 max-w-64"
        />
      </div>

      <Scatter funds={rows} stats={stats} x={x} one={one} />

      <div className="space-y-2">
        <p className="t-small text-muted">
          {x.shown(rows.length, stats.funds.length)} · {x.sortHint}
        </p>
        <div className="sv-table-wrap" role="region" aria-label={x.title} tabIndex={0}>
          <table className="sv-table min-w-[52rem]">
            <thead>
              <tr>
                {header("ticker", x.cols.ticker, false)}
                <th scope="col">{x.cols.group}</th>
                {header("r1", x.cols.r1)}
                {header("r3", x.cols.r3)}
                {header("r5", x.cols.r5)}
                {header("vol", x.cols.vol)}
                {header("mdd", x.cols.mdd)}
                <th scope="col">{x.cols.beat}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => {
                const r3 = f.returns["3"];
                const b = bench(f.group);
                const won = r3 != null && b != null ? r3 > b : null;
                return (
                  <tr key={f.ticker}>
                    <th scope="row">
                      {f.ticker}
                      <span className="sv-sub">
                        {f.manager || "—"} · {x.since(f.first)}
                      </span>
                    </th>
                    <td className="t-small">{x.groups[f.group]}</td>
                    {f.flag ? (
                      <td colSpan={6} className="t-small text-muted">
                        ⚠ {x.flagged(f.flag.month, `${f.flag.move > 0 ? "+" : ""}${one(f.flag.move)}`)}
                      </td>
                    ) : (
                      <>
                    <td className="sv-num">{one(f.returns["1"])}</td>
                    <td className="sv-num font-semibold">{one(r3)}</td>
                    <td className="sv-num">{one(f.returns["5"])}</td>
                    <td className="sv-num">{one(f.volatility)}</td>
                    <td className="sv-num">{one(f.max_drawdown)}</td>
                    <td className="t-small">
                      {won == null ? "–" : (
                        <span className={`rounded-full px-2 py-0.5 font-semibold ${won ? "bg-ink text-surface" : "border border-line-strong"}`}>
                          {won ? `✓ ${x.beat}` : x.lag} {one(b)}
                        </span>
                      )}
                    </td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <p className="t-small text-muted">{x.source}</p>
    </div>
  );
}

/**
 * Volatility (x) against 3-year return (y) as small multiples: one panel per group on shared axes, the
 * group's funds in slot 1 over the other funds in faint grey, benchmark lines, hover tooltip. (Four group
 * colours cannot all be told apart pairwise, so groups are faceted instead of coloured.)
 */
function Scatter({ funds, stats, x, one }: { funds: FundRow[]; stats: FundStats; x: (typeof TEXT)["vi"]; one: (v: number | null) => string }) {
  const pts = funds.filter((f) => f.returns["3"] != null && f.volatility != null);
  const vn30 = stats.benchmarks.eq_large?.["3"] ?? null;
  const dep = stats.benchmarks.cash_vnd?.["3"] ?? null;
  const ys = [...pts.map((f) => f.returns["3"] as number), ...[vn30, dep].filter((v): v is number => v != null)];
  const scale = {
    yLo: Math.floor(Math.min(0, ...ys) / 5) * 5,
    yHi: Math.ceil(Math.max(10, ...ys) / 5) * 5,
    xHi: Math.ceil(Math.max(10, ...pts.map((f) => f.volatility as number)) / 5) * 5,
  };
  const shown = GROUPS.filter((g) => pts.some((f) => f.group === g));
  const missing = funds.length - pts.length;
  return (
    <figure className="space-y-2">
      <figcaption>
        <span className="t-h3">{x.scatter}</span>
        <span className="block t-small text-muted">{x.scatterNote}</span>
      </figcaption>
      <div className={`grid gap-4 ${shown.length > 1 ? "md:grid-cols-2" : ""}`}>
        {shown.map((g) => (
          <Panel key={g} title={x.groups[g]} mine={pts.filter((f) => f.group === g)} others={pts.filter((f) => f.group !== g)} scale={scale} lines={[[vn30, x.vn30], [dep, x.deposit]]} x={x} one={one} big={shown.length === 1} />
        ))}
      </div>
      <p className="t-caption text-muted">
        <span className="inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: "var(--series-1)" }} aria-hidden="true" />{" "}
        {x.legendMine} ·{" "}
        <span className="inline-block h-2.5 w-2.5 rounded-full bg-line-strong align-middle opacity-40" aria-hidden="true" /> {x.legendOthers}
        {missing > 0 ? ` · ${x.noPoint(missing)}` : ""}
      </p>
    </figure>
  );
}

function Panel({
  title,
  mine,
  others,
  scale,
  lines,
  x,
  one,
  big,
}: {
  title: string;
  mine: FundRow[];
  others: FundRow[];
  scale: { yLo: number; yHi: number; xHi: number };
  lines: [number | null, string][];
  x: (typeof TEXT)["vi"];
  one: (v: number | null) => string;
  big: boolean;
}) {
  const W = big ? 720 : 400;
  const H = big ? 340 : 260;
  const pad = { l: 44, r: 12, t: 14, b: 34 };
  const { yLo, yHi, xHi } = scale;
  const px = (v: number) => pad.l + (v / xHi) * (W - pad.l - pad.r);
  const py = (v: number) => pad.t + (1 - (v - yLo) / (yHi - yLo)) * (H - pad.t - pad.b);
  const step = yHi - yLo > 40 ? 10 : 5;
  const yTicks = Array.from({ length: Math.floor((yHi - yLo) / step) + 1 }, (_, i) => yLo + i * step);
  const xTicks = Array.from({ length: Math.floor(xHi / 10) + 1 }, (_, i) => i * 10);
  const [hover, setHover] = useState<FundRow | null>(null);
  return (
    <div className="space-y-1">
      <p className="t-small font-semibold">
        {title} <span className="font-normal text-muted">· {mine.length}</span>
      </p>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${title}: ${mine.map((f) => `${f.ticker} ${one(f.returns["3"])}`).join(", ")}`}>
          {yTicks.map((v) => (
            <g key={v}>
              <line x1={pad.l} x2={W - pad.r} y1={py(v)} y2={py(v)} stroke="var(--line)" />
              <text x={pad.l - 6} y={py(v) + 4} textAnchor="end" fontSize="11" fill="var(--ink-muted)">
                {v}%
              </text>
            </g>
          ))}
          {xTicks.map((v) => (
            <text key={v} x={px(v)} y={H - 16} textAnchor="middle" fontSize="11" fill="var(--ink-muted)">
              {v}%
            </text>
          ))}
          <text x={W - pad.r} y={H - 2} textAnchor="end" fontSize="10" fill="var(--ink-muted)">
            {x.axisX}
          </text>
          {lines.map(([v, label]) =>
            v == null ? null : (
              <g key={label}>
                <line x1={pad.l} x2={W - pad.r} y1={py(v)} y2={py(v)} stroke="var(--series-2)" strokeWidth={1.5} strokeDasharray="5 4" />
                <text x={W - pad.r} y={py(v) - 4} textAnchor="end" fontSize="10" fontWeight={700} fill="var(--ink)">
                  {label} {one(v)}
                </text>
              </g>
            ),
          )}
          {others.map((f) => (
            <circle key={f.ticker} cx={px(f.volatility as number)} cy={py(f.returns["3"] as number)} r={4} fill="var(--line-strong)" opacity={0.3} />
          ))}
          {mine.map((f) => (
            <g key={f.ticker} onPointerEnter={() => setHover(f)} onPointerLeave={() => setHover(null)} onPointerDown={() => setHover(f)}>
              <circle cx={px(f.volatility as number)} cy={py(f.returns["3"] as number)} r={14} fill="transparent" />
              <circle
                cx={px(f.volatility as number)}
                cy={py(f.returns["3"] as number)}
                r={hover?.ticker === f.ticker ? 8 : 6}
                fill="var(--series-1)"
                stroke="var(--surface)"
                strokeWidth={2}
                pointerEvents="none"
              >
                <title>{`${f.ticker}: ${one(f.returns["3"])}, ${one(f.volatility)}`}</title>
              </circle>
            </g>
          ))}
        </svg>
        {hover && hover.volatility != null && hover.returns["3"] != null ? (
          <div
            className="pointer-events-none absolute z-10 w-48 rounded-2xl bg-ink p-3 t-small text-surface shadow-lg"
            style={{
              left: `clamp(0px, calc(${(px(hover.volatility) / W) * 100}% - 6rem), calc(100% - 12rem))`,
              top: `calc(${(py(hover.returns["3"]) / H) * 100}% + 14px)`,
            }}
          >
            <p className="font-bold">{hover.ticker}</p>
            {hover.manager ? <p className="opacity-80">{hover.manager}</p> : null}
            <p className="tabular-nums">
              {x.cols.r3}: {one(hover.returns["3"])} · {x.cols.vol}: {one(hover.volatility)}
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
