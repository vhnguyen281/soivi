import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Disclaimer, JsonLd, PageHead, UnverifiedBadge } from "@/components/Chrome";
import { HistoryChart } from "@/components/HistoryChart";
import { RatesTable } from "@/components/RatesTable";
import { getHistory, getInstitutions, getRates } from "@/lib/api";
import { bankSlug, type Lang } from "@/lib/format";
import { absolute, t } from "@/lib/i18n";
import { chartSeries, rateRow } from "@/lib/rows";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PLACEHOLDER = "_";

type Props = PageProps<"/[lang]/lai-suat-tiet-kiem/[bank]">;

/** Every bank with at least one approved rate is prerendered. */
export async function generateStaticParams() {
  const rates = await getRates();
  const banks = [...new Set(rates.map((r) => bankSlug(r.institution.short_name)))];
  // Cache Components needs at least one; before any rate is approved this one is a 404.
  return (banks.length ? banks : [PLACEHOLDER]).map((bank) => ({ bank }));
}

async function bankOf(slug: string) {
  const institutions = await getInstitutions();
  return institutions.find((i) => bankSlug(i.short_name) === slug) ?? null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { lang, bank } = await params;
  const d = t(lang as Lang);
  const inst = await bankOf(bank);
  if (!inst) return { title: d.notFound };
  return pageMetadata(
    lang as Lang,
    `/lai-suat-tiet-kiem/${bank}`,
    d.savings.bankTitle(inst.short_name),
    `${inst.legal_name_vi}. ${d.savings.intro}`,
  );
}

/** Rendered inline (no Suspense) so prerendered pages paint in one pass (CLS 0). */
export default function BankPage({ params }: Props) {
  return <Bank params={params} />;
}

async function Bank({ params }: { params: Props["params"] }) {
  const { lang: rawLang, bank } = await params;
  const lang = rawLang as Lang;
  const d = t(lang);
  const inst = await bankOf(bank);
  if (!inst) notFound();
  const [history, rates] = await Promise.all([getHistory(inst.short_name), getRates()]);
  const rows = rates.filter((r) => r.institution.short_name === inst.short_name).map(rateRow);
  const chart = history ? chartSeries(history, lang) : { series: [], end: 0 };
  const path = `/lai-suat-tiet-kiem/${bank}`;

  const jsonLd = [
    breadcrumbs(lang, [
      { name: d.siteName, path: "/" },
      { name: d.savings.title, path: "/lai-suat-tiet-kiem" },
      { name: inst.short_name, path },
    ]),
    {
      "@context": "https://schema.org",
      "@type": "BankOrCreditUnion",
      name: inst.legal_name_vi,
      alternateName: inst.short_name,
      ...(inst.website ? { url: inst.website, sameAs: [inst.website] } : {}),
      mainEntityOfPage: absolute(lang, path),
    },
  ];

  return (
    <div className="sv-container space-y-12 py-12">
      <JsonLd data={jsonLd} />
      <PageHead
        eyebrow={d.nav.savings}
        title={
          <>
            {d.savings.bankTitle(inst.short_name)}
            {inst.unverified ? <UnverifiedBadge lang={lang} /> : null}
          </>
        }
        intro={
          <>
            {inst.legal_name_vi}
            {inst.website ? (
              <>
                {" · "}
                <a href={inst.website} rel="nofollow noopener" target="_blank">
                  {inst.website.replace(/^https?:\/\//, "")}
                </a>
              </>
            ) : null}
          </>
        }
      />

      <section aria-labelledby="history" className="sv-panel space-y-4">
        <h2 id="history" className="t-h2">
          {d.savings.history}
        </h2>
        {chart.series.length ? (
          <HistoryChart
            lang={lang}
            series={chart.series}
            end={chart.end}
            labels={{
              series: d.savings.series,
              chart: d.savings.chartLabel,
              rate: d.rate,
              from: lang === "vi" ? "Từ" : "From",
              to: lang === "vi" ? "Đến" : "To",
            }}
          />
        ) : (
          <p>{d.empty}</p>
        )}
      </section>

      <section aria-labelledby="current" className="space-y-4">
        <h2 id="current" className="t-h2">
          {d.savings.current}
        </h2>
        {rows.length ? (
          <RatesTable
            lang={lang}
            rows={rows}
            defaultTerm="all"
            showBank={false}
            caption={`${d.savings.current} · ${inst.short_name}`}
            institution={inst.short_name}
          />
        ) : (
          <p>{d.empty}</p>
        )}
      </section>
      <Disclaimer lang={lang} />
    </div>
  );
}
