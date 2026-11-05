"use client";

import Link from "next/link";
import { useState, useSyncExternalStore } from "react";

import { cardSlug, date, pct, vnd, type Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";
import type { CardRank, CardRankItem, Persona } from "@/lib/types";

import { ReportButton } from "./ReportButton";
import { Badge, Button, CardArt, SourceStamp } from "./ui";

const CATEGORIES = ["grocery", "dining", "online", "travel", "fuel", "other"] as const;

type Form = Record<string, string>;

function toForm(p: Persona["profile"]): Form {
  const form: Form = {};
  for (const c of CATEGORIES) form[c] = String(p.monthly_spend_vnd[c] ?? 0);
  form.foreign = String(p.foreign_monthly_vnd);
  form.balance = String(p.revolving_balance_vnd);
  form.lounge = String(p.lounge_visits_wanted);
  form.loungeValue = String(p.lounge_visit_value_vnd);
  form.insurance = String(p.travel_insurance_value_vnd);
  form.income = p.monthly_income_vnd == null ? "" : String(p.monthly_income_vnd);
  return form;
}

const num = (s: string) => Number(s.replace(/\D/g, "") || 0);

/**
 * Presets are ranked at build time (fast first view); a custom profile is ranked
 * by the API through /api/cards/rank, so the formula lives in one place.
 */
export function CardFinder({
  lang,
  personas,
  ranks,
}: {
  lang: Lang;
  personas: Persona[];
  ranks: Record<string, CardRank>;
}) {
  const d = t(lang);
  const first = personas[0]?.key ?? "everyday";
  // /the-tin-dung#traveller opens that preset (links from the home page).
  const hash = useSyncExternalStore(subscribeHash, () => window.location.hash.slice(1), () => "");
  const [chosen, setChosen] = useState<string | null>(null);
  const [edited, setEdited] = useState<Form | null>(null);
  const [custom, setCustom] = useState<CardRank | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const fromHash = personas.some((p) => p.key === hash) ? hash : null;
  const persona = custom ? null : (chosen ?? fromHash ?? first);
  const presetProfile = personas.find((p) => p.key === (chosen ?? fromHash ?? first))?.profile;
  const form = edited ?? toForm(presetProfile ?? emptyProfile());
  const setForm = (next: Form) => setEdited(next);

  function pick(p: Persona) {
    setChosen(p.key);
    setCustom(null);
    setEdited(null);
    history.replaceState(null, "", `#${p.key}`);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    const spend: Record<string, number> = {};
    for (const c of CATEGORIES) if (num(form[c])) spend[c] = num(form[c]);
    const profile = {
      monthly_spend_vnd: spend,
      foreign_monthly_vnd: num(form.foreign),
      revolving_balance_vnd: num(form.balance),
      lounge_visits_wanted: num(form.lounge),
      lounge_visit_value_vnd: num(form.loungeValue),
      travel_insurance_value_vnd: num(form.insurance),
      monthly_income_vnd: form.income.trim() ? num(form.income) : null,
    };
    try {
      const res = await fetch("/api/cards/rank", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setCustom((await res.json()) as CardRank);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const result = custom ?? (persona ? ranks[persona] : undefined);
  const chosenPersona = personas.find((p) => p.key === persona);
  const who = chosenPersona ? (lang === "vi" ? chosenPersona.name_vi : chosenPersona.name_en) : d.cards.yourProfile;
  const field = (name: string, label: string) => (
    <label key={name} className="sv-field">
      {label}
      <input
        inputMode="numeric"
        name={name}
        value={form[name] ?? ""}
        onChange={(e) => setForm({ ...form, [name]: e.target.value.replace(/[^\d]/g, "") })}
      />
    </label>
  );

  return (
    <div className="grid gap-8 lg:grid-cols-[22rem_1fr] lg:items-start">
      <div className="space-y-6 lg:sticky lg:top-6">
        <fieldset className="space-y-3">
          <legend className="t-label mb-3 text-muted">{d.cards.personas}</legend>
          <div className="flex flex-wrap gap-2">
            {personas.map((p) => (
              <button
                key={p.key}
                type="button"
                aria-pressed={persona === p.key}
                onClick={() => pick(p)}
                className="sv-pill"
              >
                {lang === "vi" ? p.name_vi : p.name_en}
              </button>
            ))}
          </div>
        </fieldset>
        <form onSubmit={submit} className="sv-panel space-y-4">
          <h2 className="t-h3">{d.cards.custom}</h2>
          <p className="t-caption text-muted">{d.cards.spend}</p>
          <div className="grid grid-cols-2 gap-3">{CATEGORIES.map((c) => field(c, d.cards.categories[c]))}</div>
          {field("foreign", d.cards.foreign)}
          {field("balance", d.cards.balance)}
          <div className="grid grid-cols-2 gap-3">
            {field("lounge", d.cards.lounge)}
            {field("loungeValue", d.cards.loungeValue)}
          </div>
          {field("insurance", d.cards.insurance)}
          {field("income", d.cards.income)}
          <button type="submit" disabled={busy} className="sv-btn sv-btn--primary sv-btn--block">
            {d.cards.rank}
          </button>
          {failed ? <p className="t-small text-danger">{d.report.error}</p> : null}
        </form>
      </div>
      <section aria-live="polite" aria-label={d.cards.value} className="space-y-6">
        {!result || (result.results.length === 0 && result.not_ranked.length === 0) ? (
          <p>{d.empty}</p>
        ) : null}
        {result?.results.map((item) => <CardResult key={item.card.id} lang={lang} item={item} who={who} />)}
        {result && result.not_ranked.length > 0 ? (
          <section aria-labelledby="not-ranked" className="space-y-3">
            <h3 id="not-ranked" className="t-h3">
              {d.cards.notRanked} ({result.not_ranked.length})
            </h3>
            <p className="t-small text-muted">{d.cards.notRankedIntro}</p>
            <ul className="sv-table-wrap divide-y divide-line">
              {result.not_ranked.map((n) => (
                <li key={n.card.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-3">
                  <span className="t-small">
                    <Link href={href(lang, `/the-tin-dung/${cardSlug(n.card.name, n.card.id)}`)} className="font-semibold">
                      {n.card.name}
                    </Link>{" "}
                    <span className="text-muted">· {n.card.institution.short_name}</span>
                  </span>
                  <span className="flex flex-wrap gap-1">
                    {n.reasons.map((r) => (
                      <Badge key={r}>{d.cards.reasons[r] ?? r}</Badge>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <ReportButton labels={d.report} productRef={d.cards.title} />
      </section>
    </div>
  );
}

/** One ranked card in the design system's ProductCard layout. */
function CardResult({ lang, item, who }: { lang: Lang; item: CardRankItem; who: string }) {
  const d = t(lang);
  const b = item.breakdown;
  const terms = item.card.terms;
  const fx = terms?.values.fx_fee_pct;
  const costs: [string, number][] = [
    ["fee", b.annual_fee_vnd],
    ["fx", b.fx_cost_vnd],
    ["interest", b.interest_cost_vnd],
  ];
  // The cost that hurts most for this profile is marked (design system: tone "danger").
  const worst = costs.reduce((a, c) => (c[1] > a[1] ? c : a), ["", 0]);
  const tone = (key: string) => (worst[0] === key && worst[1] > 0 ? "sv-fact sv-fact--danger" : "sv-fact");
  const checked = item.provenance
    .map((p) => p.checked_at)
    .filter(Boolean)
    .sort()
    .at(0);
  const path = href(lang, `/the-tin-dung/${cardSlug(item.card.name, item.card.id)}`);
  return (
    <article className="sv-pcard">
      <div className="sv-pcard__head">
        <CardArt issuer={item.card.institution.short_name} />
        <div className="sv-pcard__title">
          <span className="sv-pcard__bestfor">{d.cards.rankFor(item.rank, who)}</span>
          <h3>
            <Link href={path}>{item.card.name}</Link>
          </h3>
          <p className="sv-pcard__issuer">
            {item.card.institution.legal_name_vi} · {item.card.network.toUpperCase()}
          </p>
        </div>
        <div className="sv-pcard__value">
          <span className="t-caption text-muted">{d.cards.value}</span>
          <span className={`t-figure ${item.annual_value_vnd >= 0 ? "text-jade" : "text-danger"}`}>
            {item.annual_value_vnd > 0 ? "+" : ""}
            {vnd(item.annual_value_vnd, lang)}
          </span>
        </div>
      </div>
      <dl className="sv-pcard__facts">
        <div className="sv-fact sv-fact--jade">
          <dt>{d.cards.gains}</dt>
          <dd>{b.rewards_vnd + b.perks_vnd > 0 ? "+" : ""}{vnd(b.rewards_vnd + b.perks_vnd, lang)}</dd>
          {item.flags.points_not_valued ? <span className="sv-fact__note">{d.cards.pointsNotValued}</span> : null}
        </div>
        <div className={tone("fee")}>
          <dt>{d.cards.fee}</dt>
          <dd>{cost(b.annual_fee_vnd, lang)}</dd>
          {b.fee_waived ? <span className="sv-fact__note">{d.cards.feeWaived}</span> : null}
        </div>
        <div className={tone("fx")}>
          <dt>{d.cards.fx}</dt>
          <dd>{cost(b.fx_cost_vnd, lang)}</dd>
          {fx != null ? <span className="sv-fact__note">{pct(String(fx), lang)}</span> : null}
        </div>
        <div className={tone("interest")}>
          <dt>{d.cards.interest}</dt>
          <dd>{cost(b.interest_cost_vnd, lang)}</dd>
        </div>
      </dl>
      <div className="sv-pcard__foot">
        <SourceStamp
          lang={lang}
          status={item.card.unverified ? "unverified" : "verified"}
          checkedAt={checked ? date(checked, lang) : null}
          sourceLabel={item.card.institution.short_name}
          href={terms?.provenance.source_url}
        />
        <Button variant="primary" size="sm" href={path}>
          {d.cards.detail}
        </Button>
      </div>
    </article>
  );
}

/** A cost as a reader reads it: "−1.499.000 ₫", or plain "0 ₫" when there is none. */
function cost(amount: number, lang: Lang): string {
  return amount > 0 ? `−${vnd(amount, lang)}` : vnd(0, lang);
}

function subscribeHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function emptyProfile(): Persona["profile"] {
  return {
    monthly_spend_vnd: {},
    foreign_monthly_vnd: 0,
    revolving_balance_vnd: 0,
    lounge_visits_wanted: 0,
    lounge_visit_value_vnd: 0,
    travel_insurance_value_vnd: 0,
    monthly_income_vnd: null,
  };
}
