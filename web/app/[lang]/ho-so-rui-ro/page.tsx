import type { Metadata } from "next";

import { JsonLd, PageHead } from "@/components/Chrome";
import { RiskQuiz, type QuizPortfolio } from "@/components/RiskQuiz";
import { Icon } from "@/components/ui";
import { getModelPortfolios } from "@/lib/api";
import type { Lang } from "@/lib/format";
import { t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/ho-so-rui-ro";

const SHORT: Record<string, { vi: string; en: string }> = {
  cash_vnd: { vi: "tiền gửi", en: "deposits" },
  gov_bond: { vi: "TPCP", en: "gov bonds" },
  corp_bond: { vi: "TPDN", en: "corp bonds" },
  eq_large: { vi: "VN30", en: "VN30" },
  eq_midsmall: { vi: "cổ phiếu vừa & nhỏ", en: "mid/small caps" },
  gold: { vi: "vàng", en: "gold" },
  usd: { vi: "USD", en: "USD" },
};

const TEXT = {
  vi: {
    title: "Hồ sơ rủi ro của bạn",
    intro:
      "9 câu hỏi ngắn về hoàn cảnh và cảm nhận của bạn với rủi ro, để gợi ý một trong năm danh mục mẫu. Mất khoảng 2 phút.",
    none: "Chưa có danh mục mẫu được duyệt, nên bảng hỏi chưa gợi ý được danh mục.",
    disclaimer:
      "Công cụ học tập, không phải lời khuyên đầu tư cho cá nhân bạn. Nếu hoàn cảnh phức tạp (nợ lớn, sắp nghỉ hưu, tài sản lớn), hãy trao đổi với chuyên gia.",
  },
  en: {
    title: "Your risk profile",
    intro:
      "Nine short questions about your situation and how you feel about risk, to suggest one of the five model portfolios. About two minutes.",
    none: "No model portfolios have been approved yet, so the questionnaire cannot suggest one.",
    disclaimer:
      "A learning tool, not personal investment advice. If your situation is complex (large debts, retiring soon, large wealth), talk to a professional.",
  },
};

export async function generateMetadata({ params }: PageProps<"/[lang]/ho-so-rui-ro">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

export default async function RiskProfilePage({ params }: PageProps<"/[lang]/ho-so-rui-ro">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const x = TEXT[lang];
  const models = await getModelPortfolios();
  const portfolios: QuizPortfolio[] =
    models?.portfolios.map((p) => ({
      id: p.id,
      name: lang === "vi" ? p.name : p.name_en,
      summary: p.weights
        .filter((w) => w.percent > 0)
        .map((w) => `${w.percent}% ${SHORT[w.asset_class]?.[lang] ?? w.asset_class}`)
        .join(", "),
    })) ?? [];

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
      {portfolios.length ? <RiskQuiz lang={lang} portfolios={portfolios} /> : null}
    </article>
  );
}
