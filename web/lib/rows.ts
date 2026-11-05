import type { ChartSeries } from "@/components/HistoryChart";
import type { RateRow } from "@/components/RatesTable";

import { term, vndShort, type Lang } from "./format";
import { t } from "./i18n";
import type { History, SavingsRate } from "./types";

export function rateRow(r: SavingsRate): RateRow {
  return {
    id: r.id,
    bank: r.institution.short_name,
    bankName: r.institution.legal_name_vi,
    product: r.product_name,
    channel: r.channel,
    months: r.term_months,
    days: r.term_days,
    min: r.min_amount_vnd,
    payment: r.interest_payment,
    rate: Number(r.rate_pct),
    conditions: r.conditions_text,
    checked: r.provenance.checked_at,
    source: r.provenance.source_url,
    unverified: r.unverified,
  };
}

export const HOME_TERMS = [1, 3, 6, 12, 24, 36];

/** Terms (in months) that have at least one rate, for the term pickers. */
export function termsOf(rates: SavingsRate[]): number[] {
  return [...new Set(rates.filter((r) => r.term_months && !r.term_days).map((r) => r.term_months))].sort(
    (a, b) => a - b,
  );
}

/** One chart series per product line; the 12-month counter, end-of-term line first. */
export function chartSeries(
  history: History & { fetchedAt?: string },
  lang: Lang,
): { series: ChartSeries[]; end: number } {
  const d = t(lang);
  let end = history.fetchedAt ? Date.parse(history.fetchedAt) : 0;
  const series = history.series
    .filter((s) => s.points.some((p) => p.valid_from))
    .map((s) => {
      const steps = s.points
        .filter((p) => p.valid_from)
        .map((p) => {
          const checked = p.provenance.checked_at ? Date.parse(p.provenance.checked_at) : 0;
          const from = Date.parse(p.valid_from as string);
          end = Math.max(end, from, checked, p.valid_to ? Date.parse(p.valid_to) : 0);
          return { from, to: p.valid_to ? Date.parse(p.valid_to) : null, rate: Number(p.rate_pct) };
        });
      const parts = [
        term(s.term_months, s.term_days, lang),
        s.product_name,
        d.channels[s.channel] ?? s.channel,
        d.payments[s.interest_payment] ?? s.interest_payment,
      ];
      if (s.min_amount_vnd) parts.push(`≥ ${vndShort(s.min_amount_vnd, lang)}`);
      if (s.region) parts.push(s.region);
      return {
        key: [s.product_name, s.channel, s.region, s.term_months, s.term_days, s.min_amount_vnd, s.interest_payment].join("|"),
        label: parts.join(" · "),
        steps,
        order: [
          s.term_months === 12 ? 0 : 1,
          s.channel === "counter" ? 0 : 1,
          s.interest_payment === "end" ? 0 : 1,
          s.min_amount_vnd,
          s.term_months,
        ],
      };
    })
    .sort((a, b) => {
      for (let i = 0; i < a.order.length; i++) if (a.order[i] !== b.order[i]) return a.order[i] - b.order[i];
      return a.label.localeCompare(b.label);
    })
    .map(({ key, label, steps }) => ({ key, label, steps }));
  return { series, end };
}
