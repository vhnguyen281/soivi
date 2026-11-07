import type { Metadata } from "next";
import Link from "next/link";

import { Disclaimer, JsonLd } from "@/components/Chrome";
import { Journey, type JourneyBank } from "@/components/Journey";
import { ReportButton } from "@/components/ReportButton";
import { Badge, Button, Icon, SectionHead, SourceStamp, TipBox } from "@/components/ui";
import { getChanges, getModelPortfolios, getPersonas, getRank, getVncma } from "@/lib/api";
import { date, direction, pct, term, vnd, type Lang, localizeLabel } from "@/lib/format";
import { absolute, href, t } from "@/lib/i18n";
import { LESSONS } from "@/lib/learn";
import { HOME_TERMS } from "@/lib/rows";
import { pageMetadata } from "@/lib/seo";

const AMOUNT = 100_000_000;

export async function generateMetadata({ params }: PageProps<"/[lang]">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  return pageMetadata(lang, "/", d.home.title, d.tagline);
}

export default async function Home({ params }: PageProps<"/[lang]">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const [ranks, changes, personas, year, vncma, models] = await Promise.all([
    Promise.all(HOME_TERMS.map((m) => getRank(AMOUNT, m))),
    getChanges(2),
    getPersonas(),
    getRank(AMOUNT, 12),
    getVncma(),
    getModelPortfolios(),
  ]);
  // Each bank's best 12-month equivalent rate for the journey's hero, highest first.
  const byBank = new Map<string, JourneyBank>();
  for (const r of year.results) {
    const name = r.rate.institution.short_name;
    // The equivalent rate (end-of-term basis), so the hero agrees with the ranked table below.
    const rate = Number(r.equivalent_rate_pct);
    if (!byBank.has(name) || (byBank.get(name) as JourneyBank).rate < rate)
      byBank.set(name, { name, rate, product: r.rate.product_name });
  }
  const banks = [...byBank.values()].sort((a, b) => b.rate - a.rate || a.name.localeCompare(b.name));
  const portfolios =
    models?.portfolios.map((p) => ({
      name: lang === "vi" ? p.name : p.name_en,
      expectedReturn: Number(p.expected_return),
      volatility: Number(p.volatility),
    })) ?? [];
  const lessons = LESSONS.map((l) => ({ slug: l.slug, title: l[lang].title, minutes: l.minutes, ready: l.status === "ready" }));
  const best = ranks
    .map((r, i) => ({ months: HOME_TERMS[i], top: r.results[0] }))
    .filter((b) => b.top);
  const moves = changes.changes.filter((c) => c.table === "savings_rate").slice(0, 6);

  const jsonLd = [
    {
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: d.siteName,
      url: absolute(lang),
      inLanguage: lang,
      description: d.tagline,
    },
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: d.siteName,
      url: absolute("vi"),
      description: d.footerFunding,
    },
  ];

  return (
    <>
      <JsonLd data={jsonLd} />

      <div>
        <Journey lang={lang} banks={banks} inflation={Number(vncma?.macro.pi?.value ?? 4)} portfolios={portfolios} lessons={lessons} />
      </div>

      {/* Best rates */}
      <section aria-labelledby="best" className="sv-band sv-section">
        <div className="sv-container">
          <SectionHead
            id="best"
            title={d.home.best}
            intro={d.home.bestNote(vnd(AMOUNT, lang))}
            action={<ReportButton labels={d.report} productRef={d.home.best} />}
          />
          {best.length === 0 ? (
            <p>{d.empty}</p>
          ) : (
            <div className="sv-table-wrap" role="region" aria-labelledby="best" tabIndex={0}>
              <table className="sv-table min-w-[44rem]">
                <caption>{d.home.bestNote(vnd(AMOUNT, lang))}</caption>
                <thead>
                  <tr>
                    <th scope="col">{d.term}</th>
                    <th scope="col">{d.bank}</th>
                    <th scope="col" className="sv-num">
                      {d.rate}
                    </th>
                    <th scope="col" className="sv-num">
                      {d.savings.equivalent}
                    </th>
                    <th scope="col">{d.source}</th>
                  </tr>
                </thead>
                <tbody>
                  {best.map(({ months, top }) => (
                    <tr key={months}>
                      <th scope="row" className="whitespace-nowrap">
                        {term(months, 0, lang)}
                      </th>
                      <td>
                        <Link
                          href={href(lang, `/lai-suat-tiet-kiem/${top.rate.institution.short_name.toLowerCase()}`)}
                          className="font-semibold"
                        >
                          {top.rate.institution.short_name}
                        </Link>
                        <span className="sv-sub">
                          {top.rate.product_name} · {d.channels[top.rate.channel]} ·{" "}
                          {d.payments[top.rate.interest_payment]}
                        </span>
                      </td>
                      <td className="sv-num">
                        <span className="sv-rate text-jade">{pct(top.rate.rate_pct, lang)}</span>
                      </td>
                      <td className="sv-num font-semibold">{vnd(top.equivalent_interest_vnd, lang)}</td>
                      <td>
                        <SourceStamp
                          lang={lang}
                          cell
                          status={top.rate.unverified ? "unverified" : "verified"}
                          checkedAt={date(top.rate.provenance.checked_at, lang)}
                          sourceLabel={top.rate.institution.short_name}
                          href={top.rate.provenance.source_url}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_24rem] lg:items-start">
            <Button variant="ghost" href={href(lang, "/lai-suat-tiet-kiem")} iconRight="arrow" className="justify-self-start">
              {d.home.allRates}
            </Button>
            <TipBox title={d.home.tipTitle}>
              <p className="t-small">{d.home.tip}</p>
            </TipBox>
          </div>
        </div>
      </section>

      {/* Moves + card finder */}
      <section className="sv-section">
        <div className="sv-container grid gap-12 md:grid-cols-2">
          <section aria-labelledby="moves">
            <SectionHead id="moves" title={d.home.moves} />
            {moves.length === 0 ? (
              <p className="text-muted">{d.moves.none}</p>
            ) : (
              <ul className="divide-y divide-line border-y border-line">
                {moves.map((c) => {
                  const rate = c.changes.find((x) => x.field === "rate_pct");
                  const dir = rate ? direction(rate.old, rate.new) : 0;
                  return (
                    <li key={`${c.table}-${c.version_id}`} className="flex items-start justify-between gap-4 py-3">
                      <div>
                        <p className="font-semibold">{c.institution.short_name}</p>
                        <p className="t-small text-muted">{localizeLabel(c.label, d.channels)}</p>
                        <p className="t-caption text-muted">{date(c.approved_at, lang)}</p>
                      </div>
                      {rate && rate.old != null ? (
                        <p className={`num t-small flex items-center gap-1 font-semibold ${dir > 0 ? "text-up" : dir < 0 ? "text-down" : ""}`}>
                          {pct(String(rate.old), lang)} → {pct(String(rate.new), lang)}
                          {dir ? <Icon name={dir > 0 ? "up" : "down"} size={14} /> : null}
                          <span className="sr-only">{dir > 0 ? d.moves.up : dir < 0 ? d.moves.down : ""}</span>
                        </p>
                      ) : (
                        <Badge tone="jade">{d.moves.new}</Badge>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
            <Button variant="ghost" href={href(lang, "/bien-dong-lai-suat")} iconRight="arrow" className="mt-4">
              {d.home.allMoves}
            </Button>
          </section>

          <section aria-labelledby="finder" className="sv-panel self-start">
            <span className="sv-tile__icon mb-4">
              <Icon name="card" size={24} />
            </span>
            <h2 id="finder" className="t-h2">
              {d.home.finder}
            </h2>
            <p className="t-small mt-2 mb-4 text-muted">{d.home.finderIntro}</p>
            <ul className="flex flex-wrap gap-2">
              {personas.map((p) => (
                <li key={p.key}>
                  <Link href={`${href(lang, "/the-tin-dung")}#${p.key}`} className="sv-pill">
                    {lang === "vi" ? p.name_vi : p.name_en}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </section>

      {/* Trust */}
      <section aria-labelledby="trust" className="sv-band sv-section">
        <div className="sv-container">
          <SectionHead id="trust" title={d.home.trustTitle} />
          <ul className="grid gap-6 md:grid-cols-3">
            {d.home.trust.map(([title, text]) => (
              <li key={title} className="space-y-2">
                <p className="flex items-center gap-2 t-h3">
                  <Icon name="check" size={20} className="text-jade" />
                  {title}
                </p>
                <p className="t-small text-muted">{text}</p>
              </li>
            ))}
          </ul>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button variant="secondary" size="sm" href={href(lang, "/doc-lap")}>
              {d.nav.independence}
            </Button>
            <Button variant="ghost" size="sm" href={href(lang, "/phuong-phap")} iconRight="arrow">
              {d.nav.method}
            </Button>
          </div>
        </div>
      </section>

      <div className="sv-container pt-12">
        <Disclaimer lang={lang} />
      </div>
    </>
  );
}
