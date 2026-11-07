import type { Metadata } from "next";
import Link from "next/link";

import { JsonLd } from "@/components/Chrome";
import { PlanSteps, type PlanStep } from "@/components/PlanSteps";
import type { Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/lap-ke-hoach";

const TEXT = {
  vi: {
    title: "Hành trình lập kế hoạch",
    hand: "Năm bước, theo quy trình của người tư vấn tài chính.",
    intro:
      "Từ biết mình là ai đến theo dõi mỗi năm. Mọi công cụ chạy trên trình duyệt của bạn; SoiVí không lưu con số nào.",
    steps: [
      ["risk", "/ho-so-rui-ro", "Biết mình chịu rủi ro đến đâu", "9 câu hỏi về hoàn cảnh và cảm nhận của bạn, gợi ý một danh mục mẫu.", "không cần gì", 3],
      ["sheet", "/bang-can-doi", "Lập bảng cân đối kinh tế", "Tài sản, nợ, thu nhập tương lai và mọi nghĩa vụ cả đời trên một trang.", "số dư tài khoản, khoản nợ, thu nhập, chi tiêu", 10],
      ["split", "/phan-bo-theo-muc-tieu", "Chia tài sản theo mục tiêu", "Ba phần: dự phòng, từng mục tiêu, tăng trưởng.", "tổng tài sản đầu tư được, các mục tiêu", 5],
      ["goal", "/muc-tieu", "Kiểm tra khả năng đạt mục tiêu", "Mỗi danh mục cho bạn bao nhiêu phần trăm cơ hội, kể cả khi thị trường xấu.", "một mục tiêu, số tiền góp mỗi tháng", 3],
      ["monitor", "/bang-can-doi", "Theo dõi và điều chỉnh mỗi năm", "Lưu kết quả mỗi lần xem lại, biết khi nào cần tái cân bằng.", "file dữ liệu lần trước (nếu có)", 5],
    ] as const,
    base: "Nền móng của hành trình",
    baseLinks: [
      ["/gia-dinh-thi-truong", "Giả định thị trường (VNCMA)"],
      ["/danh-muc-mau", "Danh mục mẫu"],
      ["/hoc", "Học trước khi đi"],
    ],
    note: "Công cụ học tập, không phải lời khuyên đầu tư cho cá nhân bạn.",
  },
  en: {
    title: "The planning journey",
    hand: "Five steps, the way a financial planner works.",
    intro: "From knowing yourself to a yearly check-up. Every tool runs in your browser; SoiVí stores nothing.",
    steps: [
      ["risk", "/ho-so-rui-ro", "Know how much risk you can take", "Nine questions about your situation and comfort; suggests a model portfolio.", "nothing", 3],
      ["sheet", "/bang-can-doi", "Build your economic balance sheet", "Assets, debts, future income and lifetime obligations on one page.", "balances, debts, income, spending", 10],
      ["split", "/phan-bo-theo-muc-tieu", "Split your money by goal", "Three parts: reserve, each goal, growth.", "investable assets, your goals", 5],
      ["goal", "/muc-tieu", "Check your chance of reaching a goal", "How likely each portfolio gets you there, even in bad markets.", "a goal, a monthly amount", 3],
      ["monitor", "/bang-can-doi", "Monitor and adjust every year", "Save each review and know when to rebalance.", "last time's data file (if any)", 5],
    ] as const,
    base: "Foundations",
    baseLinks: [
      ["/gia-dinh-thi-truong", "Market assumptions (VNCMA)"],
      ["/danh-muc-mau", "Model portfolios"],
      ["/hoc", "Learn before you go"],
    ],
    note: "A learning tool, not personal investment advice.",
  },
};

export async function generateMetadata({ params }: PageProps<"/[lang]/lap-ke-hoach">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

export default async function PlanHub({ params }: PageProps<"/[lang]/lap-ke-hoach">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const x = TEXT[lang];
  const steps: PlanStep[] = x.steps.map(([id, path, title, what, need, minutes]) => ({ id, path, title, what, need, minutes }));
  return (
    <div className="map">
      <article className="sv-container space-y-10 py-14">
        <JsonLd
          data={breadcrumbs(lang, [
            { name: d.siteName, path: "/" },
            { name: x.title, path: PATH },
          ])}
        />
        <header className="max-w-3xl space-y-3">
          <h1 className="map-title text-[clamp(40px,5vw,72px)]">{x.title}</h1>
          <p className="text-[18px] text-[var(--map-muted)]">{x.hand}</p>
          <p>{x.intro}</p>
        </header>
        <div className="max-w-3xl">
          <PlanSteps lang={lang} steps={steps} />
        </div>
        <section aria-labelledby="base" className="space-y-3">
          <h2 id="base" className="map-title text-[30px]">
            {x.base}
          </h2>
          <ul className="flex flex-wrap gap-x-6 gap-y-2">
            {x.baseLinks.map(([path, label]) => (
              <li key={path}>
                <Link href={href(lang, path)} className="map-hand text-[22px]">
                  {label} →
                </Link>
              </li>
            ))}
          </ul>
        </section>
        <p className="text-sm text-[var(--map-muted)]">{x.note}</p>
      </article>
    </div>
  );
}
