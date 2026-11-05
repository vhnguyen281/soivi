import { getCard } from "@/lib/api";
import { cardIdFromSlug, vnd, type Lang } from "@/lib/format";
import { t } from "@/lib/i18n";
import { OG_SIZE, ogImage } from "@/lib/og";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Soivi";

export default async function Image({ params }: { params: Promise<{ lang: string; card: string }> }) {
  const { lang: raw, card: slug } = await params;
  const lang = raw as Lang;
  const d = t(lang);
  const id = cardIdFromSlug(slug);
  const card = id === null ? null : await getCard(id);
  const fee = card?.terms?.values.annual_fee_primary_vnd;
  return ogImage({
    eyebrow: d.nav.cards,
    title: card?.name ?? d.cards.title,
    figure: fee != null ? vnd(Number(fee), lang) : undefined,
    note: fee != null ? d.cards.fields.annual_fee_primary_vnd : undefined,
  });
}
