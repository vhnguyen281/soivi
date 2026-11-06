import type { Metadata } from "next";
import Link from "next/link";

import { JsonLd, PageHead } from "@/components/Chrome";
import { GoalPlanner } from "@/components/GoalPlanner";
import { Icon } from "@/components/ui";
import { getModelPortfolios, getVncma } from "@/lib/api";
import type { Lang } from "@/lib/format";
import { scenarioShift, type PortfolioInput } from "@/lib/goals";
import { href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/muc-tieu";

const TEXT = {
  vi: {
    title: "Khả năng đạt mục tiêu tài chính",
    intro:
      "Nhập mục tiêu, thời gian và số tiền góp mỗi tháng để xem mỗi danh mục mẫu cho bạn bao nhiêu khả năng đạt mục tiêu, kể cả khi thị trường xấu.",
    none: "Chưa có danh mục mẫu được duyệt, nên chưa tính được.",
    disclaimer:
      "Đây là công cụ học tập dựa trên giả định dài hạn, không phải lời khuyên đầu tư cho cá nhân bạn. Khả năng thực tế có thể khác; hãy xem lại kế hoạch mỗi năm.",
    links: ["Danh mục mẫu", "Giả định thị trường (VNCMA)", "Chưa biết chọn danh mục nào? Làm bảng hỏi hồ sơ rủi ro"],
  },
  en: {
    title: "Chance of reaching a financial goal",
    intro:
      "Enter a goal, a horizon and a monthly amount to see how likely each model portfolio is to get you there, including when markets go badly.",
    none: "No model portfolios have been approved yet, so nothing can be calculated.",
    disclaimer:
      "A learning tool built on long-term assumptions, not personal investment advice. Real chances can differ; review your plan every year.",
    links: ["Model portfolios", "Market assumptions (VNCMA)", "Not sure which portfolio? Take the risk questionnaire"],
  },
};

export async function generateMetadata({ params }: PageProps<"/[lang]/muc-tieu">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

export default async function GoalPage({ params }: PageProps<"/[lang]/muc-tieu">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const x = TEXT[lang];
  const [models, vncma] = await Promise.all([getModelPortfolios(), getVncma()]);
  const portfolios: PortfolioInput[] =
    models && vncma
      ? models.portfolios.map((p) => ({
          id: p.id,
          name: lang === "vi" ? p.name : p.name_en,
          expectedReturn: Number(p.expected_return),
          volatility: Number(p.volatility),
          scenarioShift: scenarioShift(p.weights, vncma.classes),
        }))
      : [];
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
        <span>{portfolios.length ? x.disclaimer : x.none}</span>
      </p>
      {portfolios.length ? <GoalPlanner lang={lang} portfolios={portfolios} inflation={inflation} /> : null}
      <p className="flex flex-wrap gap-4">
        <Link href={href(lang, "/danh-muc-mau")}>{x.links[0]}</Link>
        <Link href={href(lang, "/gia-dinh-thi-truong")}>{x.links[1]}</Link>
        <Link href={href(lang, "/ho-so-rui-ro")}>{x.links[2]}</Link>
      </p>
    </article>
  );
}
