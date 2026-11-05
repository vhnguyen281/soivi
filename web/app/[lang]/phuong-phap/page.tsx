import type { Metadata } from "next";

import { JsonLd } from "@/components/Chrome";
import { getMethodologyVersion } from "@/lib/api";
import { methodologyHtml } from "@/lib/content";
import type { Lang } from "@/lib/format";
import { absolute, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/phuong-phap";

export async function generateMetadata({ params }: PageProps<"/[lang]/phuong-phap">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  return pageMetadata(
    lang,
    PATH,
    d.method.title,
    lang === "vi"
      ? "Công thức xếp hạng tiết kiệm và thẻ tín dụng, giải thích bằng lời đơn giản."
      : "How savings and credit cards are ranked, every formula in plain words.",
  );
}

export default async function MethodPage({ params }: PageProps<"/[lang]/phuong-phap">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const [html, version] = await Promise.all([methodologyHtml(lang), getMethodologyVersion()]);
  return (
    <article className="sv-container py-12"><div className="prose-soivi max-w-3xl">
      <JsonLd
        data={[
          breadcrumbs(lang, [
            { name: d.siteName, path: "/" },
            { name: d.method.title, path: PATH },
          ]),
          {
            "@context": "https://schema.org",
            "@type": "TechArticle",
            headline: d.method.title,
            version,
            inLanguage: lang,
            url: absolute(lang, PATH),
            publisher: { "@type": "Organization", name: d.siteName },
          },
        ]}
      />
      {/* Our own repository file (docs/methodology.md), rendered at build time. */}
      <div dangerouslySetInnerHTML={{ __html: html }} />
    </div></article>
  );
}
