import type { Metadata } from "next";
import Link from "next/link";

import { AssumptionLab, type LabPortfolio } from "@/components/AssumptionLab";
import { JsonLd, PageHead } from "@/components/Chrome";
import { Icon } from "@/components/ui";
import { getModelPortfolios, getVncma } from "@/lib/api";
import { labBase } from "@/lib/cmaLab";
import type { Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/gia-dinh-thi-truong/thu-nghiem";

const TEXT = {
  vi: {
    title: "Thử nghiệm giả định thị trường",
    intro:
      "Điều gì xảy ra với kế hoạch của bạn nếu lạm phát cao hơn, kinh tế tăng chậm hơn hay cổ phiếu đắt lên? Kéo các giả định lớn của VNCMA và xem hàng nghìn tương lai mô phỏng thay đổi ngay.",
    none: "Chưa có giả định thị trường hoặc danh mục mẫu được duyệt.",
    links: ["Giả định thị trường (VNCMA)", "Bài học: Biến động là gì?", "Danh mục mẫu"],
  },
  en: {
    title: "Market assumption lab",
    intro:
      "What happens to your plan if inflation runs hotter, growth slows or shares get pricier? Move the big VNCMA assumptions and watch thousands of simulated futures change at once.",
    none: "No approved market assumptions or model portfolios yet.",
    links: ["Market assumptions (VNCMA)", "Lesson: what is volatility?", "Model portfolios"],
  },
};

export async function generateMetadata({ params }: PageProps<"/[lang]/gia-dinh-thi-truong/thu-nghiem">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

export default async function LabPage({ params }: PageProps<"/[lang]/gia-dinh-thi-truong/thu-nghiem">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const x = TEXT[lang];
  const [vncma, models] = await Promise.all([getVncma(), getModelPortfolios()]);
  const base = vncma ? labBase(vncma) : null;
  const portfolios: LabPortfolio[] =
    models?.portfolios.map((p) => ({
      id: p.id,
      name: lang === "vi" ? p.name : p.name_en,
      weights: Object.fromEntries(p.weights.map((w) => [w.asset_class, w.percent])),
    })) ?? [];

  return (
    <article className="sv-container space-y-10 py-12">
      <JsonLd
        data={breadcrumbs(lang, [
          { name: d.siteName, path: "/" },
          { name: d.nav.vncma, path: "/gia-dinh-thi-truong" },
          { name: x.title, path: PATH },
        ])}
      />
      <PageHead eyebrow={d.nav.vncma} title={x.title} intro={x.intro} />
      {base && vncma && portfolios.length ? (
        <AssumptionLab lang={lang} base={base} portfolios={portfolios} release={vncma.version} />
      ) : (
        <p role="note" className="sv-note">
          <Icon name="info" />
          <span>{x.none}</span>
        </p>
      )}
      <ul className="flex flex-wrap gap-x-6 gap-y-2">
        {["/gia-dinh-thi-truong", "/hoc/bien-dong", "/danh-muc-mau"].map((path, i) => (
          <li key={path}>
            <Link href={href(lang, path)}>{x.links[i]} →</Link>
          </li>
        ))}
      </ul>
    </article>
  );
}
