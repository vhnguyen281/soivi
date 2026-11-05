"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { date, pct, term as termLabel, vndShort, type Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";

import { ReportButton } from "./ReportButton";
import { Badge, Icon, SourceStamp } from "./ui";

/** The fields the table needs (the full API row is much larger). */
export type RateRow = {
  id: number;
  bank: string;
  bankName: string;
  product: string;
  channel: string;
  months: number;
  days: number;
  min: number;
  payment: string;
  rate: number;
  conditions: string | null;
  checked: string | null;
  source: string | null;
  unverified: boolean;
};

type Key = "bank" | "term" | "channel" | "rate" | "checked";

/**
 * Sortable, filterable table of current rates. It is server-rendered with the
 * default filters, so it shows content before any JavaScript runs.
 */
export function RatesTable({
  lang,
  rows,
  defaultTerm,
  showBank = true,
  caption,
  institution,
}: {
  lang: Lang;
  rows: RateRow[];
  defaultTerm: number | "all";
  showBank?: boolean;
  caption: string;
  institution?: string;
}) {
  const d = t(lang);
  const [termFilter, setTerm] = useState<string>(String(defaultTerm));
  const [channel, setChannel] = useState("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: "rate", dir: -1 });

  const terms = useMemo(
    () =>
      [...new Set(rows.filter((r) => !r.days).map((r) => r.months))].sort((a, b) => a - b),
    [rows],
  );

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = rows.filter(
      (r) =>
        (termFilter === "all" || (r.months === Number(termFilter) && !r.days)) &&
        (channel === "all" || r.channel === channel) &&
        (!q || r.bank.toLowerCase().includes(q) || r.bankName.toLowerCase().includes(q)),
    );
    const value = (r: RateRow): string | number => {
      switch (sort.key) {
        case "bank":
          return r.bank;
        case "term":
          return r.months * 31 + r.days;
        case "channel":
          return r.channel;
        case "checked":
          return r.checked ?? "";
        default:
          return r.rate;
      }
    };
    return [...filtered].sort((a, b) => {
      const x = value(a);
      const y = value(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir || a.bank.localeCompare(b.bank);
    });
  }, [rows, termFilter, channel, query, sort]);

  function header(key: Key, label: string, numeric = false) {
    const active = sort.key === key;
    return (
      <th
        scope="col"
        className={numeric ? "sv-num" : undefined}
        aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
      >
        <button
          type="button"
          onClick={() =>
            setSort({ key, dir: active ? (sort.dir === 1 ? -1 : 1) : key === "rate" ? -1 : 1 })
          }
          className="sv-sort"
          aria-label={d.savings.sortBy(label)}
        >
          {label}
          <Icon name={active ? (sort.dir === 1 ? "up" : "down") : "sort"} size={14} />
        </button>
      </th>
    );
  }

  // One "highest" badge per table: the best rate among the rows shown.
  const best = shown.length ? Math.max(...shown.map((r) => r.rate)) : null;
  return (
    <div className="space-y-3">
      <fieldset className="flex flex-wrap items-end gap-4">
        <legend className="sr-only">{d.savings.filters}</legend>
        <label className="sv-field min-w-36">
          {d.term}
          <select value={termFilter} onChange={(e) => setTerm(e.target.value)}>
            <option value="all">{d.all}</option>
            {terms.map((m) => (
              <option key={m} value={m}>
                {termLabel(m, 0, lang)}
              </option>
            ))}
          </select>
        </label>
        <label className="sv-field min-w-36">
          {d.channel}
          <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="all">{d.all}</option>
            {Object.entries(d.channels).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        {showBank ? (
          <label className="sv-field min-w-48">
            {d.savings.search}
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
        ) : null}
        <p className="t-small pb-3 text-muted" aria-live="polite">
          {d.savings.count(shown.length)}
        </p>
        <div className="ml-auto">
          <ReportButton labels={d.report} productRef={caption} institution={institution} />
        </div>
      </fieldset>
      <div className="sv-table-wrap" role="region" aria-label={caption} tabIndex={0}>
        <table className="sv-table min-w-[60rem]">
          <caption>{caption}</caption>
          <thead>
            <tr>
              {showBank ? header("bank", d.bank) : null}
              <th scope="col">{d.product}</th>
              {header("term", d.term)}
              {header("channel", d.channel)}
              <th scope="col">{d.payment}</th>
              <th scope="col" className="sv-num">
                {d.minAmount}
              </th>
              {header("rate", d.rate, true)}
              <th scope="col">{d.conditions}</th>
              {header("checked", d.source)}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const top = best !== null && r.rate === best;
              return (
                <tr key={r.id} className={top ? "sv-row--best" : undefined}>
                  {showBank ? (
                    <th scope="row">
                      <Link href={href(lang, `/lai-suat-tiet-kiem/${r.bank.toLowerCase()}`)}>{r.bank}</Link>
                    </th>
                  ) : null}
                  <td>{r.product}</td>
                  <td className="whitespace-nowrap">{termLabel(r.months, r.days, lang)}</td>
                  <td>{d.channels[r.channel] ?? r.channel}</td>
                  <td>{d.payments[r.payment] ?? r.payment}</td>
                  <td className="sv-num">{r.min ? vndShort(r.min, lang) : "—"}</td>
                  <td className="sv-num">
                    <span className="sv-rate">{pct(r.rate, lang)}</span>
                    {top ? (
                      <span className="ml-2">
                        <Badge tone="gold">{lang === "vi" ? "Cao nhất" : "Highest"}</Badge>
                      </span>
                    ) : null}
                  </td>
                  <td className="t-caption max-w-xs text-muted">{r.conditions ?? ""}</td>
                  <td>
                    <SourceStamp
                      lang={lang}
                      cell
                      status={r.unverified ? "unverified" : "verified"}
                      checkedAt={date(r.checked, lang)}
                      sourceLabel={r.bank}
                      href={r.source}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
