import type { Metadata } from "next";
import Link from "next/link";

import { JsonLd, PageHead } from "@/components/Chrome";
import { Badge, Button, Icon } from "@/components/ui";
import { getVncma } from "@/lib/api";
import { date, type Lang } from "@/lib/format";
import { absolute, href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";
import type { Vncma, VncmaClass } from "@/lib/types";

const PATH = "/gia-dinh-thi-truong";

const TEXT = {
  vi: {
    title: "Giả định thị trường vốn Việt Nam (VNCMA)",
    intro:
      "Lợi nhuận kỳ vọng 10 năm, độ biến động và tương quan của các lớp tài sản ở Việt Nam, tính bằng VND. Dùng để lập kế hoạch tài chính dài hạn, theo công thức công khai và được một người duyệt trước khi công bố.",
    none: "Chưa có bản phát hành nào được duyệt. Bản đầu tiên sẽ xuất hiện ở đây sau khi được duyệt.",
    meta: (v: Vncma, lang: Lang) =>
      `Bản ${v.version} · dữ liệu đến ${date(v.as_of, lang)} · duyệt ${date(v.approved_at, lang)} bởi ${v.approved_by} · phương pháp ${v.methodology_version}`,
    table: "Lợi nhuận kỳ vọng 10 năm (%/năm, bình quân nhân, VND)",
    cls: "Lớp tài sản",
    expected: "Kỳ vọng",
    vol: "Biến động",
    band: "Dải 80%",
    adverse: "Kịch bản xấu",
    favourable: "Kịch bản tốt",
    grade: "Hạng dữ liệu",
    reference: "tham khảo",
    adjusted: "Đã điều chỉnh",
    rangeNote: "khoảng",
    bandNote:
      "Dải 80%: lợi nhuận bình quân 10 năm rơi vào khoảng này với xác suất khoảng 80%, nếu độ biến động đúng như ước tính.",
    scenarios: "Kịch bản",
    scenarioText:
      "Kịch bản xấu: tăng trưởng GDP thấp hơn 1 điểm %, VND mất giá thêm 1 điểm %/năm và P/E mục tiêu ở mức thấp (phân vị 25). Kịch bản tốt: ngược lại. VND mất giá nhanh hơn làm tài sản bằng ngoại tệ (vàng, USD, cổ phiếu toàn cầu) có lợi hơn tính theo VND.",
    grades: "A: dữ liệu dài, nguồn trực tiếp. B: dữ liệu ngắn hơn hoặc gián tiếp. C: ít dữ liệu, dựa nhiều vào giả định.",
    corr: "Tương quan giữa các lớp tài sản",
    corrNote:
      "Màu xanh: hai lớp thường cùng tăng giảm. Màu đỏ: thường ngược chiều. Màu xám: gần như không liên quan. Tính trên lợi nhuận tháng, có co về 0 (Ledoit–Wolf) để giảm nhiễu.",
    macro: "Giả định vĩ mô",
    value: "Giá trị",
    how: "Cách tính",
    method: "Phương pháp và nguồn",
    methodText:
      "Công thức, nguồn dữ liệu và mọi quyết định đều công khai. Số liệu thị trường lấy từ vnstock, HNX, NHNN, World Bank và Shiller; lãi tiền gửi lấy từ dữ liệu đã duyệt của SoiVí. Chúng tôi chỉ công bố các con số đã tính ra, không công bố chuỗi dữ liệu gốc.",
    methodLink: "Đặc tả phương pháp",
    downloads: "Tải về",
    disclaimer: "Lưu ý",
  },
  en: {
    title: "Vietnam capital market assumptions (VNCMA)",
    intro:
      "10-year expected returns, volatilities and correlations of Vietnamese asset classes, in VND. For long-term financial planning, from a public formula, approved by a person before publication.",
    none: "No release has been approved yet. The first one will appear here once it is approved.",
    meta: (v: Vncma, lang: Lang) =>
      `Release ${v.version} · data to ${date(v.as_of, lang)} · approved ${date(v.approved_at, lang)} by ${v.approved_by} · methodology ${v.methodology_version}`,
    table: "10-year expected returns (% a year, geometric, VND)",
    cls: "Asset class",
    expected: "Expected",
    vol: "Volatility",
    band: "80% band",
    adverse: "Adverse",
    favourable: "Favourable",
    grade: "Data grade",
    reference: "reference",
    adjusted: "Adjusted",
    rangeNote: "range",
    bandNote:
      "80% band: the 10-year average return falls in this range with about 80% probability, if volatility is as estimated.",
    scenarios: "Scenarios",
    scenarioText:
      "Adverse: GDP growth 1 pp lower, the VND 1 pp a year weaker, and a low target P/E (25th percentile). Favourable: the opposite. A weaker VND helps foreign-currency assets (gold, USD, global equities) in VND terms.",
    grades: "A: long history, direct source. B: shorter or indirect data. C: little data, mostly assumptions.",
    corr: "Correlations between asset classes",
    corrNote:
      "Blue: the two classes tend to move together. Red: they tend to move opposite. Grey: nearly unrelated. From monthly returns, shrunk towards 0 (Ledoit–Wolf) to reduce noise.",
    macro: "Macro assumptions",
    value: "Value",
    how: "How it is derived",
    method: "Method and sources",
    methodText:
      "The formulas, data sources and every decision are public. Market data come from vnstock, HNX, the SBV, the World Bank and Shiller; deposit rates from SoiVí's approved data. We publish derived numbers only, never the raw series.",
    methodLink: "Methodology specification",
    downloads: "Downloads",
    disclaimer: "Note",
  },
};

const SHORT: Record<string, { vi: string; en: string }> = {
  cash_vnd: { vi: "Tiền gửi", en: "Deposits" },
  gov_bond: { vi: "TPCP", en: "Gov bonds" },
  corp_bond: { vi: "TPDN", en: "Corp bonds" },
  eq_large: { vi: "VN30", en: "VN30" },
  eq_midsmall: { vi: "Vừa & nhỏ", en: "Mid/small" },
  gold: { vi: "Vàng", en: "Gold" },
  usd: { vi: "USD", en: "USD" },
  eq_global: { vi: "Toàn cầu", en: "Global" },
};

function num(value: string | null | undefined, lang: Lang, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(lang === "vi" ? "vi-VN" : "en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value));
}

/** Diverging fill: blue for +, red for -, the neutral surface at 0. */
function cellStyle(rho: number, diagonal: boolean): React.CSSProperties {
  if (diagonal) return { background: "var(--surface-alt)", color: "var(--ink-muted)" };
  // At most 60% of the pole, so the ink text keeps its contrast in both themes.
  // Monochrome: positive = solid grey fill, negative = diagonal hatch, so the sign never rests on tone alone.
  const share = Math.round(Math.min(1, Math.abs(rho)) * 45);
  const fill = `color-mix(in oklab, ${rho >= 0 ? "var(--div-pos)" : "var(--div-neg)"} ${share}%, var(--surface-alt))`;
  if (rho >= 0) return { background: fill, color: "var(--ink)" };
  return {
    background: `repeating-linear-gradient(135deg, ${fill} 0 4px, var(--surface-alt) 4px 7px)`,
    color: "var(--ink)",
  };
}

export async function generateMetadata({ params }: PageProps<"/[lang]/gia-dinh-thi-truong">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

function Band({ c, lang, x }: { c: VncmaClass; lang: Lang; x: (typeof TEXT)["vi"] }) {
  if (c.band_80) return <>{`${num(c.band_80[0], lang)} … ${num(c.band_80[1], lang)}`}</>;
  if (c.range) return <>{`${x.rangeNote} ${num(c.range[0], lang)} … ${num(c.range[1], lang)}`}</>;
  return <>—</>;
}

export default async function VncmaPage({ params }: PageProps<"/[lang]/gia-dinh-thi-truong">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const x = TEXT[lang];
  const v = await getVncma();

  return (
    <article className="sv-container space-y-10 py-12">
      <JsonLd
        data={[
          breadcrumbs(lang, [
            { name: d.siteName, path: "/" },
            { name: x.title, path: PATH },
          ]),
          ...(v
            ? [
                {
                  "@context": "https://schema.org",
                  "@type": "Dataset",
                  name: `${x.title} ${v.version}`,
                  description: x.intro,
                  url: absolute(lang, PATH),
                  version: v.version,
                  dateModified: v.approved_at,
                  creator: { "@type": "Organization", name: d.siteName },
                  isAccessibleForFree: true,
                },
              ]
            : []),
        ]}
      />
      <PageHead eyebrow={d.nav.vncma} title={x.title} intro={x.intro}>
        {v ? <p className="t-small text-muted">{x.meta(v, lang)}</p> : null}
      </PageHead>

      {v ? (
        <>
          <section aria-labelledby="vncma-table" className="space-y-3">
            <h2 id="vncma-table" className="t-h2">
              {x.table}
            </h2>
            <div className="sv-table-wrap" role="region" aria-labelledby="vncma-table" tabIndex={0}>
              <table className="sv-table min-w-[48rem]">
                <thead>
                  <tr>
                    <th scope="col">{x.cls}</th>
                    <th scope="col" className="text-right">{x.expected}</th>
                    <th scope="col" className="text-right">{x.vol}</th>
                    <th scope="col" className="text-right">{x.band}</th>
                    <th scope="col" className="text-right">{x.adverse}</th>
                    <th scope="col" className="text-right">{x.favourable}</th>
                    <th scope="col">{x.grade}</th>
                  </tr>
                </thead>
                <tbody>
                  {v.classes.map((c) => (
                    <tr key={c.id}>
                      <th scope="row" title={c.formula}>
                        {c.name}{" "}
                        {c.optimizer_default ? null : <Badge>{x.reference}</Badge>}
                        {Number(c.adjustment_pp) !== 0 ? (
                          <Badge tone="gold">{`${x.adjusted} ${num(c.adjustment_pp, lang, 2)}: ${c.adjustment_reason}`}</Badge>
                        ) : null}
                      </th>
                      <td className="text-right font-semibold tabular-nums">{num(c.expected_return, lang)}</td>
                      <td className="text-right tabular-nums">{num(c.volatility, lang)}</td>
                      <td className="text-right tabular-nums">
                        <Band c={c} lang={lang} x={x} />
                      </td>
                      <td className="text-right tabular-nums">{num(c.scenarios.adverse, lang)}</td>
                      <td className="text-right tabular-nums">{num(c.scenarios.favourable, lang)}</td>
                      <td>{c.grade}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="t-small text-muted">{x.bandNote}</p>
            <p className="t-small text-muted">{x.grades}</p>
          </section>

          <section aria-labelledby="vncma-scen" className="sv-panel space-y-2">
            <h2 id="vncma-scen" className="t-h3">
              {x.scenarios}
            </h2>
            <p className="text-muted">{x.scenarioText}</p>
          </section>

          <section aria-labelledby="vncma-corr" className="space-y-3">
            <h2 id="vncma-corr" className="t-h2">
              {x.corr}
            </h2>
            <div className="sv-table-wrap" role="region" aria-labelledby="vncma-corr" tabIndex={0}>
              <table className="vncma-heat min-w-[40rem]">
                <thead>
                  <tr>
                    <th scope="col" />
                    {v.correlation.classes.map((c) => (
                      <th key={c} scope="col">
                        {SHORT[c]?.[lang] ?? c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {v.correlation.matrix.map((row, i) => {
                    const a = v.correlation.classes[i];
                    return (
                      <tr key={a}>
                        <th scope="row">{SHORT[a]?.[lang] ?? a}</th>
                        {row.map((rho, j) => {
                          const b = v.correlation.classes[j];
                          const label = `${SHORT[a]?.[lang] ?? a} – ${SHORT[b]?.[lang] ?? b}: ${num(String(rho), lang, 2)}`;
                          return (
                            <td key={b} style={cellStyle(rho, i === j)} title={label} aria-label={label}>
                              {num(String(rho), lang, 2)}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex items-center gap-3 t-small text-muted" aria-hidden="true">
              <span>−1</span>
              <span className="vncma-scale" />
              <span>+1</span>
            </div>
            <p className="t-small text-muted">{x.corrNote}</p>
          </section>

          <section aria-labelledby="vncma-macro" className="space-y-3">
            <h2 id="vncma-macro" className="t-h2">
              {x.macro}
            </h2>
            <div className="sv-table-wrap" role="region" aria-labelledby="vncma-macro" tabIndex={0}>
              <table className="sv-table min-w-[40rem]">
                <thead>
                  <tr>
                    <th scope="col">{lang === "vi" ? "Biến" : "Variable"}</th>
                    <th scope="col" className="text-right">{x.value}</th>
                    <th scope="col">{x.how}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(v.macro).map(([k, m]) => (
                    <tr key={k}>
                      <th scope="row">{m.name}</th>
                      <td className="text-right tabular-nums">{num(m.value, lang, 2)}</td>
                      <td className="t-small text-muted">{m.derivation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section aria-labelledby="vncma-method" className="grid gap-6 md:grid-cols-2">
            <div className="sv-panel space-y-3">
              <h2 id="vncma-method" className="t-h3">
                {x.method}
              </h2>
              <p className="text-muted">{x.methodText}</p>
              <p className="flex flex-wrap gap-3">
                <a href={v.methodology_url} rel="noopener noreferrer">
                  {x.methodLink}
                </a>
                <Link href={href(lang, "/phuong-phap")}>{d.nav.method}</Link>
                <Link href={href(lang, "/danh-muc-mau")}>{lang === "vi" ? "Danh mục mẫu" : "Model portfolios"}</Link>
              </p>
            </div>
            <div className="sv-panel space-y-3">
              <h2 className="t-h3">{x.downloads}</h2>
              <p className="flex flex-wrap gap-2">
                {(["xlsx", "json", "md"] as const).map((f) => (
                  <Button key={f} variant="secondary" href={`/api/vncma/${v.version}/${f}`}>
                    {`VNCMA ${v.version} · ${f}`}
                  </Button>
                ))}
              </p>
            </div>
          </section>

          <p role="note" className="sv-note">
            <Icon name="info" />
            <span>{v.disclaimer[lang]}</span>
          </p>
        </>
      ) : (
        <p className="sv-note">
          <Icon name="info" />
          <span>{x.none}</span>
        </p>
      )}
    </article>
  );
}
