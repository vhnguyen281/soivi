import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Disclaimer, JsonLd, UnverifiedBadge } from "@/components/Chrome";
import { CardArt, SourceStamp } from "@/components/ui";
import { ReportButton } from "@/components/ReportButton";
import { getCard, getCards } from "@/lib/api";
import { cardIdFromSlug, cardSlug, date, pct, vnd, type Lang } from "@/lib/format";
import { absolute, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PLACEHOLDER = "_";
import type { CardDetail, Evidence, Provenance, Valued } from "@/lib/types";

type Props = PageProps<"/[lang]/the-tin-dung/[card]">;

export async function generateStaticParams() {
  const cards = (await getCards()).map((c) => cardSlug(c.name, c.id));
  // Cache Components needs at least one; before any card is approved this one is a 404.
  return (cards.length ? cards : [PLACEHOLDER]).map((card) => ({ card }));
}

async function cardOf(slug: string): Promise<CardDetail | null> {
  const id = cardIdFromSlug(slug);
  return id === null ? null : getCard(id);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { lang, card } = await params;
  const d = t(lang as Lang);
  const found = await cardOf(card);
  if (!found) return { title: d.notFound };
  return pageMetadata(
    lang as Lang,
    `/the-tin-dung/${cardSlug(found.name, found.id)}`,
    `${found.name}: ${d.cards.fees}`,
    `${found.institution.legal_name_vi}. ${d.cards.intro}`,
  );
}

/** Rendered inline (no Suspense) so prerendered pages paint in one pass (CLS 0). */
export default function CardPage({ params }: Props) {
  return <Card params={params} />;
}

/** A value as people read it: amounts in VND, rates in %, booleans in words. */
function show(field: string, value: unknown, lang: Lang): string {
  if (value === null || value === undefined) return "—";
  const d = t(lang);
  if (field === "category") return d.cards.categories[String(value)] ?? String(value);
  if (field === "reward_type") return d.cards.rewardTypes[String(value)] ?? String(value);
  if (typeof value === "boolean") return value ? (lang === "vi" ? "Có" : "Yes") : lang === "vi" ? "Không" : "No";
  if (field.endsWith("_vnd")) return vnd(Number(value), lang);
  if (field.endsWith("_pct")) return pct(String(value), lang);
  return String(value);
}

/** Link to the exact page of a PDF source when we know it. */
function sourceLink(p: Provenance, e?: Evidence): string | null {
  if (!p.source_url) return null;
  return e?.page && /\.pdf($|\?)/i.test(p.source_url) ? `${p.source_url}#page=${e.page}` : p.source_url;
}

function Facts({
  lang,
  valued,
  title,
  id,
  unverified,
}: {
  lang: Lang;
  valued: Valued;
  title: string;
  id: string;
  unverified: boolean;
}) {
  const d = t(lang);
  const p = valued.provenance;
  const entries = Object.entries(valued.values).filter(([, v]) => v !== null && v !== false);
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="t-h2">
        {title}
      </h2>
      <div className="sv-table-wrap" role="region" aria-labelledby={id} tabIndex={0}>
        <table className="sv-table min-w-[36rem]">
          <thead>
            <tr>
              <th scope="col">{lang === "vi" ? "Khoản" : "Item"}</th>
              <th scope="col" className="sv-num">
                {lang === "vi" ? "Giá trị" : "Value"}
              </th>
              <th scope="col">{d.cards.quote}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([field, value]) => {
              const e = p.evidence?.[field];
              const link = sourceLink(p, e);
              return (
                <tr key={field}>
                  <th scope="row" className="font-normal">
                    {d.cards.fields[field] ?? field}
                  </th>
                  {/* Numbers stay on one line, right-aligned; text (perks, rules) wraps. */}
                  <td className={typeof value === "string" && !/_(vnd|pct)$/.test(field) && isNaN(Number(value)) ? "min-w-48" : "sv-num"}>
                    <span className="font-bold">{show(field, value, lang)}</span>
                  </td>
                  <td>
                    {e ? (
                      <>
                        <q lang="vi" className="text-ink">
                          {e.quote}
                        </q>
                        {e.also?.map((x) => (
                          <q key={x.quote} lang="vi" className="mt-1 block text-ink">
                            {x.quote}
                          </q>
                        ))}
                        <span className="t-caption block text-muted">
                          {link ? (
                            <a href={link} rel="nofollow noopener" target="_blank">
                              {d.source}, {d.cards.page(e.page)}
                            </a>
                          ) : (
                            d.cards.page(e.page)
                          )}
                        </span>
                      </>
                    ) : link ? (
                      <a href={link} rel="nofollow noopener" target="_blank">
                        {d.source}
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <SourceStamp
        lang={lang}
        status={unverified ? "unverified" : "verified"}
        checkedAt={date(p.checked_at, lang)}
        effectiveFrom={p.effective_from ? date(p.effective_from, lang) : null}
        sourceLabel={p.source_url ? new URL(p.source_url).hostname.replace(/^www\./, "") : undefined}
        href={p.source_url}
      />
    </section>
  );
}

async function Card({ params }: { params: Props["params"] }) {
  const { lang: rawLang, card: slug } = await params;
  const lang = rawLang as Lang;
  const d = t(lang);
  const card = await cardOf(slug);
  if (!card) notFound();
  const path = `/the-tin-dung/${cardSlug(card.name, card.id)}`;
  const terms = card.terms?.values ?? {};
  const fee = terms.annual_fee_primary_vnd;
  // The card page's yearly rate is used instead of the fee schedule's (methodology §2).
  const apr = card.interest?.values.interest_rate_pct ?? terms.interest_rate_pct;

  const jsonLd = [
    breadcrumbs(lang, [
      { name: d.siteName, path: "/" },
      { name: d.cards.title, path: "/the-tin-dung" },
      { name: card.name, path },
    ]),
    {
      "@context": "https://schema.org",
      "@type": "CreditCard",
      name: card.name,
      url: absolute(lang, path),
      provider: { "@type": "BankOrCreditUnion", name: card.institution.legal_name_vi },
      ...(fee != null
        ? {
            annualPercentageRate: apr != null ? Number(apr) : undefined,
            feesAndCommissionsSpecification: `${d.cards.fields.annual_fee_primary_vnd}: ${vnd(Number(fee), lang)}`,
          }
        : {}),
    },
  ];

  const keyFacts: [string, string, string?][] = [
    [d.cards.fields.annual_fee_primary_vnd, fee != null ? vnd(Number(fee), lang) : "—"],
    [d.cards.fields.interest_rate_pct, apr != null ? pct(String(apr), lang) : "—"],
    [d.cards.fields.fx_fee_pct, terms.fx_fee_pct != null ? pct(String(terms.fx_fee_pct), lang) : "—"],
    [d.cards.fields.cash_advance_pct ?? "", terms.cash_advance_pct != null ? pct(String(terms.cash_advance_pct), lang) : "—"],
  ];

  return (
    <div className="sv-container space-y-12 py-12">
      <JsonLd data={jsonLd} />
      <header className="sv-pcard">
        <div className="sv-pcard__head">
          <CardArt issuer={card.institution.short_name} />
          <div className="sv-pcard__title">
            <span className="sv-pcard__bestfor">{d.nav.cards}</span>
            <h1 className="t-display">
              {card.name}
              {card.unverified ? <UnverifiedBadge lang={lang} /> : null}
            </h1>
            <p className="sv-pcard__issuer">
              {card.institution.legal_name_vi} · {card.network.toUpperCase()}
              {card.tier ? ` · ${card.tier}` : ""}
            </p>
          </div>
          <ReportButton labels={d.report} institution={card.institution.short_name} productRef={card.name} />
        </div>
        <dl className="sv-pcard__facts">
          {keyFacts.map(([label, value]) => (
            <div key={label} className="sv-fact">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </header>
      {card.terms ? (
        <Facts unverified={card.unverified} lang={lang} valued={card.terms} title={d.cards.fees} id="fees" />
      ) : (
        <p>{d.cards.notStated}</p>
      )}
      {card.interest ? (
        <Facts unverified={card.unverified} lang={lang} valued={card.interest} title={d.cards.interestTitle} id="interest" />
      ) : null}
      {card.rewards.map((r, i) => (
        <Facts key={r.version_id} unverified={card.unverified} lang={lang} valued={r} title={`${d.cards.rewardsTitle} ${i + 1}`} id={`reward-${i}`} />
      ))}
      {card.perks ? <Facts unverified={card.unverified} lang={lang} valued={card.perks} title={d.cards.perksTitle} id="perks" /> : null}
      <Disclaimer lang={lang} />
    </div>
  );
}
