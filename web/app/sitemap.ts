import type { MetadataRoute } from "next";

import { getCards, getRates } from "@/lib/api";
import { bankSlug, cardSlug } from "@/lib/format";
import { absolute } from "@/lib/i18n";

/** Every page in both languages, each with its hreflang alternate. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [rates, cards] = await Promise.all([getRates(), getCards()]);
  const latest = (items: (string | null | undefined)[]) => {
    const times = items.filter(Boolean).map((x) => Date.parse(x as string));
    return times.length ? new Date(Math.max(...times)) : undefined;
  };
  const banks = new Map<string, (string | null)[]>();
  for (const r of rates) {
    const slug = bankSlug(r.institution.short_name);
    banks.set(slug, [...(banks.get(slug) ?? []), r.provenance.checked_at]);
  }
  const pages: { path: string; modified?: Date; priority: number }[] = [
    { path: "/", modified: latest(rates.map((r) => r.provenance.checked_at)), priority: 1 },
    { path: "/lai-suat-tiet-kiem", modified: latest(rates.map((r) => r.provenance.checked_at)), priority: 0.9 },
    { path: "/the-tin-dung", priority: 0.9 },
    { path: "/bien-dong-lai-suat", priority: 0.7 },
    { path: "/gia-dinh-thi-truong", priority: 0.6 },
    { path: "/danh-muc-mau", priority: 0.6 },
    { path: "/muc-tieu", priority: 0.6 },
    { path: "/phuong-phap", priority: 0.5 },
    { path: "/doc-lap", priority: 0.3 },
    ...[...banks.entries()].map(([slug, checked]) => ({
      path: `/lai-suat-tiet-kiem/${slug}`,
      modified: latest(checked),
      priority: 0.8,
    })),
    ...cards.map((c) => ({
      path: `/the-tin-dung/${cardSlug(c.name, c.id)}`,
      modified: latest([c.terms?.provenance.checked_at]),
      priority: 0.7,
    })),
  ];
  return pages.flatMap((p) =>
    (["vi", "en"] as const).map((lang) => ({
      url: absolute(lang, p.path),
      lastModified: p.modified,
      priority: lang === "vi" ? p.priority : Math.round(p.priority * 8) / 10,
      alternates: { languages: { vi: absolute("vi", p.path), en: absolute("en", p.path) } },
    })),
  );
}
