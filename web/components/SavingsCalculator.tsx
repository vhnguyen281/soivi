"use client";

import { useState } from "react";

import { pct, term as termLabel, vnd, type Lang } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { SavingsRank } from "@/lib/types";

import { ReportButton } from "./ReportButton";
import { Badge, Icon } from "./ui";

/**
 * Amount + term -> ranking by interest at maturity (the API applies the methodology).
 * Opens with a realistic example already answered (`initial`, ranked at build time).
 */
export function SavingsCalculator({
  lang,
  terms,
  initial,
}: {
  lang: Lang;
  terms: number[];
  initial: SavingsRank | null;
}) {
  const d = t(lang);
  const [amount, setAmount] = useState(String(initial?.query.amount_vnd ?? 100_000_000));
  const [months, setMonths] = useState(
    String(initial?.query.term_months ?? (terms.includes(12) ? 12 : (terms[0] ?? 12))),
  );
  const [channel, setChannel] = useState("any");
  const [result, setResult] = useState<SavingsRank | null>(initial);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    const qs = new URLSearchParams({ amount: amount.replace(/\D/g, ""), term: months, channel });
    try {
      const res = await fetch(`/api/savings/rank?${qs}`);
      if (!res.ok) throw new Error(String(res.status));
      setResult((await res.json()) as SavingsRank);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const top = result?.results[0];
  return (
    <section aria-labelledby="calc-title" className="sv-panel space-y-6">
      <div className="sv-calc">
        <form onSubmit={run} className="grid content-start gap-4">
          <h2 id="calc-title" className="t-h3">
            {d.savings.calc}
          </h2>
          <label className="sv-field">
            {d.savings.amount}
            <input
              inputMode="numeric"
              value={Number(amount.replace(/\D/g, "") || 0).toLocaleString(lang === "vi" ? "vi-VN" : "en-US")}
              onChange={(e) => setAmount(e.target.value.replace(/\D/g, "").slice(0, 13))}
              aria-describedby="calc-amount"
            />
            <span id="calc-amount" className="sv-field__hint">
              {vnd(Number(amount || 0), lang)}
            </span>
          </label>
          <div className="grid grid-cols-2 gap-4">
            <label className="sv-field">
              {d.term}
              <select value={months} onChange={(e) => setMonths(e.target.value)}>
                {terms.map((m) => (
                  <option key={m} value={m}>
                    {termLabel(m, 0, lang)}
                  </option>
                ))}
              </select>
            </label>
            <label className="sv-field">
              {d.channel}
              <select value={channel} onChange={(e) => setChannel(e.target.value)}>
                <option value="any">{d.all}</option>
                <option value="counter">{d.channels.counter}</option>
                <option value="digital">
                  {d.channels.online} / {d.channels.app}
                </option>
              </select>
            </label>
          </div>
          <button type="submit" disabled={busy} className="sv-btn sv-btn--primary sv-btn--block">
            {d.savings.calcButton}
          </button>
          {failed ? <p className="t-small text-danger">{d.report.error}</p> : null}
        </form>

        <div className="sv-calc__result" aria-live="polite">
          {top ? (
            <>
              <span className="sv-calc__label">
                {d.savings.equivalent} · {top.rate.institution.short_name}
              </span>
              <span className="sv-calc__figure">{vnd(top.equivalent_interest_vnd, lang)}</span>
              <span className="sv-calc__total">
                {d.savings.maturity}: {vnd(top.maturity_value_vnd, lang)}
              </span>
              <span className="t-caption text-muted">
                {pct(top.rate.rate_pct, lang)} · {d.payments[top.rate.interest_payment]} ·{" "}
                {termLabel(result!.query.term_months, 0, lang)} · {d.channels[top.rate.channel]}
              </span>
            </>
          ) : (
            <span className="sv-calc__label">{result ? d.empty : d.savings.calc}</span>
          )}
        </div>
      </div>

      {result && result.results.length > 0 ? (
        <div className="space-y-2">
          <div className="sv-table-wrap" role="region" aria-label={d.savings.calc} tabIndex={0}>
            <table className="sv-table min-w-[40rem]">
              <caption>
                {vnd(result.query.amount_vnd, lang)} · {termLabel(result.query.term_months, 0, lang)}
              </caption>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">{d.bank}</th>
                  <th scope="col" className="sv-num">
                    {d.rate}
                  </th>
                  <th scope="col" className="sv-num">
                    {d.savings.equivalent}
                  </th>
                  <th scope="col" className="sv-num">
                    {d.savings.maturity}
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.results.slice(0, 10).map((r, i) => (
                  <tr key={r.rate.id} className={i === 0 ? "sv-row--best" : undefined}>
                    <td className="num">{r.rank}</td>
                    <th scope="row">
                      {r.rate.institution.short_name}
                      <span className="sv-sub">
                        {r.rate.product_name} · {d.channels[r.rate.channel]} · {d.payments[r.rate.interest_payment]}
                      </span>
                    </th>
                    <td className="sv-num">
                      <span className="sv-rate">{pct(r.rate.rate_pct, lang)}</span>
                    </td>
                    <td className="sv-num font-semibold">
                      {vnd(r.equivalent_interest_vnd, lang)}
                      {i === 0 ? (
                        <span className="ml-2">
                          <Badge tone="gold">{lang === "vi" ? "Cao nhất" : "Highest"}</Badge>
                        </span>
                      ) : null}
                    </td>
                    <td className="sv-num">{vnd(r.maturity_value_vnd, lang)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            {result.excluded_min_amount ? (
              <p className="t-caption flex items-center gap-1 text-muted">
                <Icon name="info" size={14} />
                {d.savings.excluded(result.excluded_min_amount)}
              </p>
            ) : (
              <span />
            )}
            <ReportButton labels={d.report} productRef={d.savings.calc} />
          </div>
        </div>
      ) : null}
    </section>
  );
}
