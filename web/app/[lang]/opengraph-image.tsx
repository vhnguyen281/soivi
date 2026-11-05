import type { Lang } from "@/lib/format";
import { t } from "@/lib/i18n";
import { OG_SIZE, ogImage } from "@/lib/og";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "SoiVí";

export default async function Image({ params }: { params: Promise<{ lang: string }> }) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  return ogImage({
    eyebrow: lang === "vi" ? "So sánh tài chính Việt Nam" : "Vietnamese finance, compared",
    title: d.tagline,
    note: d.footerFunding.split(".")[0],
  });
}
