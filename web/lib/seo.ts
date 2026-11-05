import type { Metadata } from "next";

import type { Lang } from "./format";
import { absolute, t } from "./i18n";

/** Title, description, canonical URL, hreflang alternates and Open Graph for a page. */
export function pageMetadata(
  lang: Lang,
  path: string,
  title: string,
  description: string,
): Metadata {
  const url = absolute(lang, path);
  return {
    title,
    description,
    alternates: {
      canonical: url,
      languages: { vi: absolute("vi", path), en: absolute("en", path), "x-default": absolute("vi", path) },
    },
    openGraph: {
      type: "website",
      url,
      title,
      description,
      siteName: t(lang).siteName,
      locale: lang === "vi" ? "vi_VN" : "en_US",
      alternateLocale: lang === "vi" ? "en_US" : "vi_VN",
    },
    twitter: { card: "summary_large_image", title, description },
  };
}

export function breadcrumbs(lang: Lang, items: { name: string; path: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: item.name,
      item: absolute(lang, item.path),
    })),
  };
}
