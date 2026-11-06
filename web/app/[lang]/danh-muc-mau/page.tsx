import type { Metadata } from "next";
import Link from "next/link";

import { JsonLd, PageHead } from "@/components/Chrome";
import { Icon } from "@/components/ui";
import { getModelPortfolios } from "@/lib/api";
import { date, type Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/danh-muc-mau";

// Fixed colour per asset class (never by rank), in the validated series order.
const SERIES: Record<string, string> = {
  cash_vnd: "var(--series-1)",
  gov_bond: "var(--series-2)",
  corp_bond: "var(--series-3)",
  eq_large: "var(--series-4)",
  eq_midsmall: "var(--series-5)",
  gold: "var(--series-6)",
  usd: "var(--series-7)",
};

const SHORT: Record<string, { vi: string; en: string }> = {
  cash_vnd: { vi: "Tiền gửi", en: "Deposits" },
  gov_bond: { vi: "TPCP", en: "Gov bonds" },
  corp_bond: { vi: "TPDN", en: "Corp bonds" },
  eq_large: { vi: "VN30", en: "VN30" },
  eq_midsmall: { vi: "Vừa & nhỏ", en: "Mid/small" },
  gold: { vi: "Vàng", en: "Gold" },
  usd: { vi: "USD", en: "USD" },
};

const TEXT = {
  vi: {
    title: "Danh mục mẫu theo mức rủi ro",
    intro:
      "Năm cách phân bổ tài sản ở cấp lớp tài sản, từ thận trọng đến tăng trưởng cao, tính từ giả định thị trường VNCMA. Dùng để tham khảo và học cách phân bổ, không phải lời khuyên cho cá nhân bạn.",
    none: "Chưa có danh mục mẫu nào được duyệt.",
    meta: (r: string, asOf: string, by: string, lang: Lang) =>
      `Dựa trên VNCMA ${r} · dữ liệu đến ${date(asOf, lang)} · duyệt bởi ${by}`,
    expected: "Kỳ vọng",
    vol: "Biến động",
    perYear: "%/năm",
    table: "Tỷ trọng (%)",
    portfolio: "Danh mục",
    how: "Cách tính",
    howText:
      "Mỗi danh mục tối đa hoá lợi nhuận kỳ vọng với độ biến động không vượt mức mục tiêu (3%, 6%, 9%, 12%, 15%/năm). Không bán khống; mỗi lớp có tỷ trọng tối thiểu và tối đa (ví dụ trái phiếu doanh nghiệp tối đa 15% vì dữ liệu còn mỏng). Kết quả là trung bình của 500 lần tối ưu trên dữ liệu mô phỏng (resampling), để danh mục ổn định hơn. Cổ phiếu toàn cầu và bất động sản không có trong danh mục mẫu.",
    vncma: "Xem giả định thị trường (VNCMA)",
  },
  en: {
    title: "Model portfolios by risk level",
    intro:
      "Five asset-class allocations, from conservative to high growth, built on the VNCMA market assumptions. For reference and learning, not personal advice.",
    none: "No model portfolios have been approved yet.",
    meta: (r: string, asOf: string, by: string, lang: Lang) =>
      `Built on VNCMA ${r} · data to ${date(asOf, lang)} · approved by ${by}`,
    expected: "Expected",
    vol: "Volatility",
    perYear: "% a year",
    table: "Weights (%)",
    portfolio: "Portfolio",
    how: "How they are built",
    howText:
      "Each portfolio maximises expected return with volatility at most its target (3%, 6%, 9%, 12%, 15% a year). No short sales; every class has a minimum and a maximum weight (for example corporate bonds at most 15%, as the data are thin). The result averages 500 optimisations on simulated data (resampling), so portfolios move less between releases. Global equities and real estate are not used.",
    vncma: "See the market assumptions (VNCMA)",
  },
};

function num(value: string, lang: Lang): string {
  return new Intl.NumberFormat(lang === "vi" ? "vi-VN" : "en-US", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(Number(value));
}

export async function generateMetadata({ params }: PageProps<"/[lang]/danh-muc-mau">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

export default async function ModelPortfoliosPage({ params }: PageProps<"/[lang]/danh-muc-mau">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const x = TEXT[lang];
  const data = await getModelPortfolios();
  const classes = data?.portfolios[0]?.weights.map((w) => w.asset_class) ?? [];
  const label = (c: string) => SHORT[c]?.[lang] ?? c;

  return (
    <article className="sv-container space-y-10 py-12">
      <JsonLd
        data={breadcrumbs(lang, [
          { name: d.siteName, path: "/" },
          { name: x.title, path: PATH },
        ])}
      />
      <PageHead eyebrow={d.nav.vncma} title={x.title} intro={x.intro}>
        {data ? (
          <p className="t-small text-muted">{x.meta(data.release, data.as_of, data.approved_by, lang)}</p>
        ) : null}
      </PageHead>

      <p role="note" className="sv-note">
        <Icon name="info" />
        <span>{data ? data.disclaimer[lang] : x.none}</span>
      </p>

      {data ? (
        <>
          <section aria-labelledby="mp-chart" className="space-y-4">
            <h2 id="mp-chart" className="sr-only">
              {x.title}
            </h2>
            <ul className="flex flex-wrap gap-x-4 gap-y-1 t-small text-muted" aria-label={x.table}>
              {classes.map((c) => (
                <li key={c}>
                  <span className="mp-swatch" style={{ background: SERIES[c] }} aria-hidden="true" /> {label(c)}
                </li>
              ))}
            </ul>
            <div className="space-y-5">
              {data.portfolios.map((p) => (
                <div key={p.id} className="space-y-1.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="t-h3">{lang === "vi" ? p.name : p.name_en}</h3>
                    <p className="t-small text-muted tabular-nums">
                      {x.expected} <b className="text-ink">{num(p.expected_return, lang)}</b> · {x.vol}{" "}
                      {num(p.volatility, lang)} {x.perYear}
                    </p>
                  </div>
                  <div className="mp-bar" role="img" aria-label={p.weights.map((w) => `${label(w.asset_class)} ${w.percent}%`).join(", ")}>
                    {p.weights
                      .filter((w) => w.percent > 0)
                      .map((w) => (
                        <span
                          key={w.asset_class}
                          style={{ width: `${w.percent}%`, background: SERIES[w.asset_class] }}
                          title={`${label(w.asset_class)}: ${w.percent}%`}
                        />
                      ))}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section aria-labelledby="mp-table" className="space-y-3">
            <h2 id="mp-table" className="t-h2">
              {x.table}
            </h2>
            <div className="sv-table-wrap" role="region" aria-labelledby="mp-table" tabIndex={0}>
              <table className="sv-table min-w-[44rem]">
                <thead>
                  <tr>
                    <th scope="col">{x.portfolio}</th>
                    {classes.map((c) => (
                      <th key={c} scope="col" className="text-right">
                        {label(c)}
                      </th>
                    ))}
                    <th scope="col" className="text-right">{x.expected}</th>
                    <th scope="col" className="text-right">{x.vol}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.portfolios.map((p) => (
                    <tr key={p.id}>
                      <th scope="row">{lang === "vi" ? p.name : p.name_en}</th>
                      {p.weights.map((w) => (
                        <td key={w.asset_class} className="text-right tabular-nums">
                          {w.percent}
                        </td>
                      ))}
                      <td className="text-right font-semibold tabular-nums">{num(p.expected_return, lang)}</td>
                      <td className="text-right tabular-nums">{num(p.volatility, lang)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="sv-panel space-y-2">
            <h2 className="t-h3">{x.how}</h2>
            <p className="text-muted">{x.howText}</p>
            <p className="flex flex-wrap gap-4">
              <Link href={href(lang, "/ho-so-rui-ro")}>
                {lang === "vi" ? "Danh mục nào hợp với bạn? Làm bảng hỏi" : "Which one fits you? Take the questionnaire"}
              </Link>
              <Link href={href(lang, "/muc-tieu")}>
                {lang === "vi" ? "Tính khả năng đạt mục tiêu của bạn" : "Check the chance of reaching your goal"}
              </Link>
              <Link href={href(lang, "/gia-dinh-thi-truong")}>{x.vncma}</Link>
            </p>
          </section>
        </>
      ) : null}
    </article>
  );
}
