import type { Metadata } from "next";

import { CardFinder } from "@/components/CardFinder";
import { Disclaimer, JsonLd, PageHead } from "@/components/Chrome";
import { getPersonaRank, getPersonas } from "@/lib/api";
import type { Lang } from "@/lib/format";
import { t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";
import type { CardRank } from "@/lib/types";

const PATH = "/the-tin-dung";

export async function generateMetadata({ params }: PageProps<"/[lang]/the-tin-dung">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  return pageMetadata(lang, PATH, d.cards.title, d.cards.intro);
}

export default async function CardsPage({ params }: PageProps<"/[lang]/the-tin-dung">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const personas = await getPersonas();
  // Every preset is ranked at build time, so switching presets needs no request.
  const ranked = await Promise.all(personas.map((p) => getPersonaRank(p.key)));
  const ranks: Record<string, CardRank> = Object.fromEntries(personas.map((p, i) => [p.key, ranked[i]]));

  return (
    <div className="sv-container space-y-10 py-12">
      <JsonLd
        data={breadcrumbs(lang, [
          { name: d.siteName, path: "/" },
          { name: d.cards.title, path: PATH },
        ])}
      />
      <PageHead eyebrow={d.nav.cards} title={d.cards.title} intro={d.cards.intro} />
      <CardFinder lang={lang} personas={personas} ranks={ranks} />
      <Disclaimer lang={lang} />
    </div>
  );
}
