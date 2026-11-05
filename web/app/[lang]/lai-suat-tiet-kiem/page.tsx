import type { Metadata } from "next";

import { Disclaimer, JsonLd, PageHead } from "@/components/Chrome";
import { RatesTable } from "@/components/RatesTable";
import { SavingsCalculator } from "@/components/SavingsCalculator";
import { TipBox } from "@/components/ui";
import { getRank, getRates } from "@/lib/api";
import type { Lang } from "@/lib/format";
import { absolute, t } from "@/lib/i18n";
import { rateRow, termsOf } from "@/lib/rows";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/lai-suat-tiet-kiem";

export async function generateMetadata({ params }: PageProps<"/[lang]/lai-suat-tiet-kiem">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  return pageMetadata(lang, PATH, d.savings.title, d.savings.intro);
}

export default async function SavingsPage({ params }: PageProps<"/[lang]/lai-suat-tiet-kiem">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const rates = await getRates();
  const terms = termsOf(rates);
  // The calculator opens already answered: 100 million for 12 months (or the first term).
  const initial = await getRank(100_000_000, terms.includes(12) ? 12 : (terms[0] ?? 12));
  const rows = rates.map(rateRow);
  const defaultTerm = terms.includes(12) ? 12 : "all";

  const jsonLd = [
    breadcrumbs(lang, [
      { name: d.siteName, path: "/" },
      { name: d.savings.title, path: PATH },
    ]),
    {
      "@context": "https://schema.org",
      "@type": "ItemList",
      name: d.savings.caption,
      url: absolute(lang, PATH),
      numberOfItems: rates.length,
      // The 12-month rates, so the list stays small; the table holds the rest.
      itemListElement: rates
        .filter((r) => r.term_months === 12 && !r.term_days)
        .slice(0, 100)
        .map((r, i) => ({
          "@type": "ListItem",
          position: i + 1,
          item: {
            "@type": "DepositAccount",
            name: `${r.institution.short_name} ${r.product_name} 12 ${lang === "vi" ? "tháng" : "months"}`,
            provider: { "@type": "BankOrCreditUnion", name: r.institution.legal_name_vi },
            interestRate: Number(r.rate_pct),
            ...(r.provenance.source_url ? { url: r.provenance.source_url } : {}),
          },
        })),
    },
  ];

  return (
    <>
      <JsonLd data={jsonLd} />
      <section className="sv-container space-y-8 py-12">
        <PageHead eyebrow={d.nav.savings} title={d.savings.title} intro={d.savings.intro} />
        <SavingsCalculator lang={lang} terms={terms.length ? terms : [12]} initial={initial} />
      </section>
      <section aria-labelledby="all-rates" className="sv-band sv-section">
        <div className="sv-container space-y-6">
          <div className="grid gap-6 lg:grid-cols-[1fr_24rem] lg:items-start">
            <h2 id="all-rates" className="t-h2">
              {d.savings.caption}
            </h2>
            <TipBox title={d.home.tipTitle}>
              <p className="t-small">{d.home.tip}</p>
            </TipBox>
          </div>
          {rows.length === 0 ? (
            <p>{d.empty}</p>
          ) : (
            <RatesTable lang={lang} rows={rows} defaultTerm={defaultTerm} caption={d.savings.caption} />
          )}
        </div>
      </section>
      <div className="sv-container pt-12">
        <Disclaimer lang={lang} />
      </div>
    </>
  );
}
