import { getRates } from "@/lib/api";
import { bankSlug, pct, type Lang } from "@/lib/format";
import { t } from "@/lib/i18n";
import { OG_SIZE, ogImage } from "@/lib/og";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Soivi";

export default async function Image({ params }: { params: Promise<{ lang: string; bank: string }> }) {
  const { lang: raw, bank } = await params;
  const lang = raw as Lang;
  const d = t(lang);
  const rates = (await getRates()).filter((r) => bankSlug(r.institution.short_name) === bank);
  const twelve = rates.filter((r) => r.term_months === 12 && !r.term_days);
  const best = twelve.reduce<number | null>((m, r) => Math.max(m ?? 0, Number(r.rate_pct)), null);
  const name = rates[0]?.institution.short_name ?? bank.toUpperCase();
  return ogImage({
    eyebrow: d.nav.savings,
    title: d.savings.bankTitle(name),
    figure: best !== null ? pct(best, lang) : undefined,
    note: best !== null ? (lang === "vi" ? "cao nhất kỳ hạn 12 tháng" : "best 12-month rate") : undefined,
  });
}
