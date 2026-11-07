import type { Metadata } from "next";
import Link from "next/link";

import { BalanceSheet } from "@/components/BalanceSheet";
import { JsonLd, PageHead } from "@/components/Chrome";
import { Icon } from "@/components/ui";
import { getModelPortfolios, getVncma } from "@/lib/api";
import type { ModelMix } from "@/lib/buckets";
import type { Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/bang-can-doi";

const TEXT = {
  vi: {
    title: "Bảng cân đối kinh tế và kế hoạch mục tiêu",
    intro:
      "Nhập tài sản, khoản nợ, thu nhập và chi tiêu thật của bạn để thấy bức tranh tài chính cả đời: hôm nay bạn có gì, sẽ cần gì, và cần làm gì để đạt các mục tiêu trung và dài hạn. Lưu kết quả mỗi lần xem lại để theo dõi tiến độ và biết khi nào cần tái cân bằng.",
    none: "Chưa có giả định thị trường được duyệt, nên chưa tính được.",
    disclaimer:
      "Công cụ học tập, không phải lời khuyên đầu tư cho cá nhân bạn. Dữ liệu bạn nhập chỉ nằm trên trình duyệt của bạn.",
    links: ["Chia tài sản theo mục tiêu", "Khả năng đạt mục tiêu", "Giả định thị trường (VNCMA)"],
  },
  en: {
    title: "Economic balance sheet and goal plan",
    intro:
      "Enter your real assets, debts, income and spending to see your lifetime financial picture: what you have today, what you will need, and what it takes to reach your medium and long-term goals. Save each review to track progress and know when to rebalance.",
    none: "No market assumptions have been approved yet, so nothing can be calculated.",
    disclaimer: "A learning tool, not personal investment advice. What you enter stays in your browser.",
    links: ["Split your money by goal", "Chance of reaching a goal", "Market assumptions (VNCMA)"],
  },
};

export async function generateMetadata({ params }: PageProps<"/[lang]/bang-can-doi">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

export default async function BalanceSheetPage({ params }: PageProps<"/[lang]/bang-can-doi">) {
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
  const gov = vncma?.classes.find((c) => c.id === "gov_bond");
  const rates = gov && vncma?.macro.pi ? { govBond: Number(gov.expected_return), inflation: Number(vncma.macro.pi.value) } : null;

  return (
    <article className="sv-container space-y-10 py-12">
      <JsonLd
        data={breadcrumbs(lang, [
          { name: d.siteName, path: "/" },
          { name: x.title, path: PATH },
        ])}
      />
      <PageHead eyebrow={d.nav.vncma} title={x.title} intro={x.intro} />
      <p role="note" className="sv-note no-print">
        <Icon name="info" />
        <span>{rates ? x.disclaimer : x.none}</span>
      </p>
      {rates && vncma ? <BalanceSheet lang={lang} mixes={mixes} rates={rates} release={vncma.version} /> : null}
      <ul className="no-print flex flex-wrap gap-x-6 gap-y-2">
        {["/phan-bo-theo-muc-tieu", "/muc-tieu", "/gia-dinh-thi-truong"].map((path, i) => (
          <li key={path}>
            <Link href={href(lang, path)}>{x.links[i]}</Link>
          </li>
        ))}
      </ul>
    </article>
  );
}
