import type { Metadata } from "next";
import Link from "next/link";

import { JsonLd, PageHead } from "@/components/Chrome";
import { FundGroups } from "@/components/FundGroups";
import { Icon } from "@/components/ui";
import { getFundStats } from "@/lib/api";
import { date, type Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/quy-dau-tu";

const TEXT = {
  vi: {
    title: "Quỹ đầu tư ở Việt Nam đã sinh lời ra sao?",
    intro:
      "Lợi nhuận thực tế của các quỹ mở cổ phiếu, trái phiếu, cân bằng và ETF, so với mốc đơn giản nhất: mua cả rổ VN30 hoặc gửi tiết kiệm.",
    none: "Chưa có thống kê quỹ được duyệt.",
    meta: (asOf: string, by: string, at: string) => `Dữ liệu đến ${asOf} · duyệt bởi ${by} ngày ${at}`,
    eqHead: "số quỹ cổ phiếu thắng VN30 trong 3 năm qua",
    eqSub: (f: string, b: string) => `Trung vị quỹ cổ phiếu ${f}/năm, VN30 gồm cổ tức ${b}/năm.`,
    bondHead: "số quỹ trái phiếu thắng tiền gửi 12 tháng (3 năm)",
    bondSub: (f: string, b: string) => `Trung vị ${f}/năm so với ${b}/năm (3 năm).`,
    etfHead: "lợi nhuận trung vị mỗi năm của ETF (3 năm)",
    etfSub: "Giá giao dịch, 3 năm. ETF mô phỏng chỉ số nên thường bám sát mốc.",
    what: "Cách đọc",
    whatBody: [
      "Mỗi quỹ được tính lợi nhuận bình quân mỗi năm từ giá trị tài sản ròng (NAV) cuối tháng; ETF tính theo giá giao dịch.",
      "Mốc so sánh lấy từ chuỗi lợi nhuận của VNCMA cùng kỳ: VN30 gồm cổ tức cho quỹ cổ phiếu và ETF, tiền gửi 12 tháng cho quỹ trái phiếu.",
      "Đây là số liệu theo nhóm. Trang so sánh từng quỹ sẽ có khi NAV của mỗi quỹ được đối chiếu với báo cáo của chính công ty quản lý quỹ.",
    ],
    source: "Nguồn NAV: CafeF qua vnstock (giá trị tổng hợp, không đăng lại chuỗi gốc). Mốc: VNCMA.",
    links: ["Giả định thị trường (VNCMA)", "Thử nghiệm giả định", "Bài học: Đa dạng hoá"],
  },
  en: {
    title: "How have Vietnam's investment funds done?",
    intro:
      "Real returns of open-end equity, bond and balanced funds and ETFs, against the simplest benchmarks: buying the whole VN30 basket or keeping a deposit.",
    none: "No approved fund statistics yet.",
    meta: (asOf: string, by: string, at: string) => `Data to ${asOf} · approved by ${by} on ${at}`,
    eqHead: "of equity funds beat VN30 over 3 years",
    eqSub: (f: string, b: string) => `Median equity fund ${f} a year; VN30 with dividends ${b} a year.`,
    bondHead: "of bond funds beat a 12-month deposit (3 years)",
    bondSub: (f: string, b: string) => `Median ${f} a year against ${b} a year (3 years).`,
    etfHead: "median yearly return of ETFs (3 years)",
    etfSub: "Trading prices, 3 years. ETFs track an index, so they usually stay close to it.",
    what: "How to read this",
    whatBody: [
      "Each fund's average yearly return comes from its month-end net asset value (NAV) per unit; ETFs use the trading price.",
      "Benchmarks come from the VNCMA return series for the same window: VN30 with dividends for equity funds and ETFs, 12-month deposits for bond funds.",
      "These are group figures. A fund-by-fund comparison follows once each fund's NAV is checked against its manager's own reports.",
    ],
    source: "NAV source: CafeF via vnstock (derived figures only, raw series not republished). Benchmarks: VNCMA.",
    links: ["Market assumptions (VNCMA)", "Assumption lab", "Lesson: diversification"],
  },
};

export async function generateMetadata({ params }: PageProps<"/[lang]/quy-dau-tu">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

export default async function FundsPage({ params }: PageProps<"/[lang]/quy-dau-tu">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const x = TEXT[lang];
  const stats = await getFundStats();
  const p = (v: number | null | undefined) =>
    v == null ? "–" : `${v.toLocaleString(lang === "vi" ? "vi-VN" : "en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
  const share = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const eq = stats?.groups.equity_fund.horizons["3"];
  const bond = stats?.groups.bond_fund.horizons["3"];
  const etf = stats?.groups.etf.horizons["3"];

  return (
    <article className="sv-container space-y-10 py-12">
      <JsonLd
        data={breadcrumbs(lang, [
          { name: d.siteName, path: "/" },
          { name: x.title, path: PATH },
        ])}
      />
      <PageHead eyebrow={d.nav.compare} title={x.title} intro={x.intro}>
        {stats ? <p className="t-small text-muted">{x.meta(date(stats.as_of, lang), stats.approved_by, date(stats.approved_at, lang))}</p> : null}
      </PageHead>
      {stats ? (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            {eq ? (
              <div className="sv-panel space-y-2">
                <p className="text-[34px] leading-none font-extrabold tracking-tight">{share(eq.beat)}</p>
                <p className="font-semibold">{x.eqHead}</p>
                <p className="t-small text-muted">{x.eqSub(p(eq.stats?.p50), p(eq.benchmark))}</p>
              </div>
            ) : null}
            {bond ? (
              <div className="sv-panel space-y-2">
                <p className="text-[34px] leading-none font-extrabold tracking-tight">{share(bond.beat)}</p>
                <p className="font-semibold">{x.bondHead}</p>
                <p className="t-small text-muted">{x.bondSub(p(bond.stats?.p50), p(bond.benchmark))}</p>
              </div>
            ) : null}
            {etf ? (
              <div className="sv-panel space-y-2">
                <p className="text-[34px] leading-none font-extrabold tracking-tight">{p(etf.stats?.p50)}</p>
                <p className="font-semibold">{x.etfHead}</p>
                <p className="t-small text-muted">{x.etfSub}</p>
              </div>
            ) : null}
          </div>
          <section className="sv-panel">
            <FundGroups lang={lang} stats={stats} />
          </section>
          <section className="space-y-3" aria-labelledby="fund-how">
            <h2 id="fund-how" className="t-h2">
              {x.what}
            </h2>
            <ul className="list-disc space-y-1 pl-5">
              {x.whatBody.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <p className="t-small text-muted">{x.source}</p>
            <p role="note" className="sv-note">
              <Icon name="info" />
              <span>{stats.disclaimer[lang]}</span>
            </p>
          </section>
        </>
      ) : (
        <p role="note" className="sv-note">
          <Icon name="info" />
          <span>{x.none}</span>
        </p>
      )}
      <ul className="flex flex-wrap gap-x-6 gap-y-2">
        {["/gia-dinh-thi-truong", "/gia-dinh-thi-truong/thu-nghiem", "/hoc/da-dang-hoa"].map((path, i) => (
          <li key={path}>
            <Link href={href(lang, path)}>{x.links[i]} →</Link>
          </li>
        ))}
      </ul>
    </article>
  );
}
