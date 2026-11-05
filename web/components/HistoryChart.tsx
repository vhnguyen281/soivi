"use client";

import { useId, useState } from "react";

import { date, pct, polyline, type Lang } from "@/lib/format";

export type ChartSeries = {
  key: string;
  label: string;
  /** Each approved value and the time it was live: [from, to) in ms; to = null while current. */
  steps: { from: number; to: number | null; rate: number }[];
};

const W = 640;
const H = 220;
const PAD = { left: 48, right: 12, top: 12, bottom: 28 };

/**
 * Rate history as a step line (a rate holds until the next approved value).
 * A plain SVG, no chart library; the same numbers are in a table for screen readers.
 */
export function HistoryChart({
  lang,
  series,
  end,
  labels,
}: {
  lang: Lang;
  series: ChartSeries[];
  end: number;
  labels: { series: string; chart: string; rate: string; from: string; to: string };
}) {
  const [key, setKey] = useState(series[0]?.key ?? "");
  const id = useId();
  const current = series.find((s) => s.key === key) ?? series[0];
  if (!current) return null;

  const points: { t: number; v: number }[] = [];
  for (const step of current.steps) {
    points.push({ t: step.from, v: step.rate }, { t: step.to ?? end, v: step.rate });
  }
  const rates = points.map((p) => p.v);
  const vMin = Math.max(0, Math.min(...rates) - 0.25);
  const vMax = Math.max(...rates) + 0.25;
  const tMin = Math.min(...points.map((p) => p.t));
  const tMax = Math.max(end, ...points.map((p) => p.t));
  const box = { width: W - PAD.left - PAD.right, height: H - PAD.top - PAD.bottom, tMin, tMax, vMin, vMax };
  const line = polyline(points, box);
  const iso = (ms: number) => new Date(ms).toISOString();

  return (
    <div className="space-y-2">
      {series.length > 1 ? (
        <label className="sv-field max-w-md">
          {labels.series}
          <select value={current.key} onChange={(e) => setKey(e.target.value)}>
            {series.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <figure>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-labelledby={`${id}-cap`}
          className="h-auto w-full max-w-3xl"
        >
          <g transform={`translate(${PAD.left},${PAD.top})`}>
            <line x1={0} y1={box.height} x2={box.width} y2={box.height} stroke="var(--line)" />
            <line x1={0} y1={0} x2={0} y2={box.height} stroke="var(--line)" />
            <text x={-6} y={4} textAnchor="end" fontSize="11" fill="var(--ink-muted)">
              {pct(vMax, lang)}
            </text>
            <text x={-6} y={box.height} textAnchor="end" fontSize="11" fill="var(--ink-muted)">
              {pct(vMin, lang)}
            </text>
            <text x={0} y={box.height + 18} fontSize="11" fill="var(--ink-muted)">
              {date(iso(tMin), lang)}
            </text>
            <text x={box.width} y={box.height + 18} textAnchor="end" fontSize="11" fill="var(--ink-muted)">
              {date(iso(tMax), lang)}
            </text>
            <polyline points={line} fill="none" stroke="var(--jade)" strokeWidth={2.5} />
          </g>
        </svg>
        <figcaption id={`${id}-cap`} className="t-caption text-muted">
          {labels.chart}: {current.label}
        </figcaption>
      </figure>
      <details className="t-small">
        <summary className="cursor-pointer text-muted">{labels.rate}</summary>
        <div className="sv-table-wrap mt-2 max-w-md"><table className="sv-table">
          <thead>
            <tr>
              <th scope="col">{labels.from}</th>
              <th scope="col">{labels.to}</th>
              <th scope="col" className="sv-num">
                {labels.rate}
              </th>
            </tr>
          </thead>
          <tbody>
            {current.steps.map((s) => (
              <tr key={s.from}>
                <td>{date(iso(s.from), lang)}</td>
                <td>{s.to ? date(iso(s.to), lang) : "—"}</td>
                <td className="sv-num">{pct(s.rate, lang)}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </details>
    </div>
  );
}
