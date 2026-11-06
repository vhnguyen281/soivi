import type { Metadata } from "next";
import Link from "next/link";

import { BucketPlanner } from "@/components/BucketPlanner";
import { JsonLd, PageHead } from "@/components/Chrome";
import { Icon } from "@/components/ui";
import { getModelPortfolios, getVncma } from "@/lib/api";
import type { ModelMix } from "@/lib/buckets";
import type { Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/phan-bo-theo-muc-tieu";

const TEXT = {
  vi: {
    title: "Chia tài sản theo mục tiêu",
    intro:
      "Chia tiền thành ba phần: quỹ thanh khoản cho chi tiêu bất ngờ, phần dành riêng cho từng mục tiêu, và phần tăng trưởng dài hạn. Mỗi phần dùng danh mục phù hợp với thời gian và mức quan trọng của nó.",
    none: "Chưa có danh mục mẫu được duyệt, nên chưa tính được.",
    disclaimer:
      "Công cụ học tập, không phải lời khuyên đầu tư cho cá nhân bạn. Hãy xem lại mỗi năm hoặc khi mục tiêu thay đổi.",
    quiz: "Chưa biết mức rủi ro của mình? Làm bảng hỏi hồ sơ rủi ro",
  },
  en: {
    title: "Split your money by goal",
    intro:
      "Three parts: a liquidity reserve for the unexpected, money set aside for each goal, and long-term growth. Each part uses a portfolio that fits its horizon and importance.",
    none: "No model portfolios have been approved yet, so nothing can be calculated.",
    disclaimer: "A learning tool, not personal investment advice. Review it every year or when your goals change.",
    quiz: "Not sure of your risk level? Take the risk questionnaire",
  },
};

export async function generateMetadata({ params }: PageProps<"/[lang]/phan-bo-theo-muc-tieu">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

export default async function BucketsPage({ params }: PageProps<"/[lang]/phan-bo-theo-muc-tieu">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const x = TEXT[lang];
  const [models, vncma] = await Promise.all([getModelPortfolios(), getVncma()]);
  const mixes: ModelMix[] =
    models?.portfolios.map((p) => ({
      id: p.id,
      name: lang === "vi" ? p.name : p.name_en,
      expectedReturn: Number(p.expected_return),
      volatility: Number(p.volatility),
      weights: p.weights.map((w) => ({ asset_class: w.asset_class, percent: w.percent })),
    })) ?? [];
  const inflation = Number(vncma?.macro.pi?.value ?? 4);

  return (
    <article className="sv-container space-y-10 py-12">
      <JsonLd
        data={breadcrumbs(lang, [
          { name: d.siteName, path: "/" },
          { name: x.title, path: PATH },
        ])}
      />
      <PageHead eyebrow={d.nav.vncma} title={x.title} intro={x.intro} />
      <p role="note" className="sv-note">
        <Icon name="info" />
        <span>{mixes.length ? x.disclaimer : x.none}</span>
      </p>
      {mixes.length ? (
        <BucketPlanner lang={lang} mixes={mixes} inflation={inflation} initialLevel={Math.min(3, mixes.length)} />
      ) : null}
      <p>
        <Link href={href(lang, "/ho-so-rui-ro")}>{x.quiz}</Link>
      </p>
    </article>
  );
}
