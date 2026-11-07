import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { JsonLd } from "@/components/Chrome";
import { InflationLesson } from "@/components/lessons/Inflation";
import { MinPaymentLesson, type CardApr } from "@/components/lessons/MinPayment";
import { LessonEnd } from "@/components/lessons/Parts";
import { RealRateLesson, type Demand, type Offer } from "@/components/lessons/RealRate";
import { getCard, getCards, getRank, getRates, getVncma } from "@/lib/api";
import { mapFonts } from "@/lib/fonts";
import type { Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";
import { LESSONS, lessonBySlug } from "@/lib/learn";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const TOOL = {
  vi: { "lam-phat": "So sánh lãi suất tiết kiệm", "lai-thuc-nhan": "So sánh lãi suất theo số tiền và kỳ hạn của bạn", "tra-toi-thieu": "Tìm thẻ phù hợp cách bạn chi tiêu" },
  en: { "lam-phat": "Compare savings rates", "lai-thuc-nhan": "Compare rates for your amount and term", "tra-toi-thieu": "Find a card that fits how you spend" },
} as Record<Lang, Record<string, string>>;

export function generateStaticParams() {
  return LESSONS.filter((l) => l.status === "ready").map((l) => ({ slug: l.slug }));
}

export async function generateMetadata({ params }: PageProps<"/[lang]/hoc/[slug]">): Promise<Metadata> {
  const { lang, slug } = (await params) as { lang: Lang; slug: string };
  const lesson = lessonBySlug(slug);
  if (!lesson) return { title: t(lang).notFound };
  return pageMetadata(lang, `/hoc/${slug}`, lesson[lang].title, lesson[lang].summary);
}

const AMOUNT = 100_000_000;

/** Demand-deposit (không kỳ hạn) rates: each bank's highest. */
async function demandRates(): Promise<Demand[]> {
  const rates = await getRates();
  const by = new Map<string, number>();
  for (const r of rates) {
    if (r.term_months !== 0 || r.term_days !== 0) continue;
    const v = Number(r.rate_pct);
    by.set(r.institution.short_name, Math.max(by.get(r.institution.short_name) ?? 0, v));
  }
  return [...by.entries()].map(([bank, rate]) => ({ bank, rate }));
}

async function lessonBody(slug: string, lang: Lang) {
  const d = t(lang);
  if (slug === "lam-phat") {
    const [vncma, year, demand] = await Promise.all([getVncma(), getRank(AMOUNT, 12), demandRates()]);
    const top = year.results[0];
    const bestDemand = [...demand].sort((a, b) => b.rate - a.rate)[0] ?? { bank: "—", rate: 0 };
    return (
      <InflationLesson
        lang={lang}
        inflation={Number(vncma?.macro.pi?.value ?? 4)}
        demand={bestDemand}
        deposit={top ? { bank: top.rate.institution.short_name, rate: Number(top.rate.rate_pct) } : { bank: "—", rate: 0 }}
      />
    );
  }
  if (slug === "lai-thuc-nhan") {
    const [year, demand] = await Promise.all([getRank(AMOUNT, 12), demandRates()]);
    const offers: Offer[] = year.results.map((r) => ({
      bank: r.rate.institution.short_name,
      product: r.rate.product_name,
      channel: r.rate.channel,
      payment: r.rate.interest_payment,
      rate: Number(r.rate.rate_pct),
      equivalent: Number(r.equivalent_rate_pct),
      source: r.rate.provenance.source_url,
    }));
    return <RealRateLesson lang={lang} offers={offers} demand={demand} channels={d.channels} payments={d.payments} />;
  }
  if (slug === "tra-toi-thieu") {
    const summaries = await getCards();
    const details = await Promise.all(summaries.map((c) => getCard(c.id)));
    const cards: CardApr[] = [];
    for (const c of details) {
      if (!c) continue;
      const own = c.interest?.values.interest_rate_pct ?? c.terms?.values.interest_rate_pct;
      if (own == null) continue;
      const days = c.interest?.values.interest_free_days ?? c.terms?.values.interest_free_days;
      cards.push({
        id: c.id,
        label: c.name.toUpperCase().startsWith(c.institution.short_name.toUpperCase()) ? c.name : `${c.institution.short_name} ${c.name}`,
        apr: Number(own),
        freeDays: typeof days === "number" ? days : null,
        source: (c.interest ?? c.terms)?.provenance.source_url ?? null,
      });
    }
    cards.sort((a, b) => a.apr - b.apr || a.label.localeCompare(b.label));
    return <MinPaymentLesson lang={lang} cards={cards} />;
  }
  return null;
}

export default async function LessonPage({ params }: PageProps<"/[lang]/hoc/[slug]">) {
  const { lang, slug } = (await params) as { lang: Lang; slug: string };
  const lesson = lessonBySlug(slug);
  if (!lesson) notFound();
  const d = t(lang);
  const ready = LESSONS.filter((l) => l.status === "ready");
  const next = ready[ready.findIndex((l) => l.slug === slug) + 1];
  const body = await lessonBody(slug, lang);

  return (
    <div className={`map ${mapFonts}`}>
      <article className="sv-container max-w-4xl space-y-10 py-14">
        <JsonLd
          data={breadcrumbs(lang, [
            { name: d.siteName, path: "/" },
            { name: lang === "vi" ? "Học" : "Learn", path: "/hoc" },
            { name: lesson[lang].title, path: `/hoc/${slug}` },
          ])}
        />
        <header className="space-y-3">
          <Link href={href(lang, "/hoc")} className="map-hand text-[20px]">
            ← {lang === "vi" ? "Tất cả bài học" : "All lessons"}
          </Link>
          <h1 className="map-title text-[clamp(38px,5vw,64px)]">{lesson[lang].title}</h1>
          <p className="map-hand -rotate-1 text-[24px] text-[var(--map-terra)]">
            {lesson.minutes} {lang === "vi" ? "phút · kéo, bấm, thử" : "min · drag, tap, try"}
          </p>
          <p>{lesson[lang].summary}</p>
        </header>
        {body}
        <LessonEnd
          lang={lang}
          slug={slug}
          tool={lesson.tool}
          toolLabel={TOOL[lang][slug] ?? lesson.tool}
          next={next ? { slug: next.slug, title: next[lang].title } : null}
        />
        <p className="text-xs text-[var(--map-muted)]">{d.disclaimerShort}</p>
      </article>
    </div>
  );
}
