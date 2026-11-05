import type { Metadata } from "next";

import { JsonLd, PageHead } from "@/components/Chrome";
import { Button, Icon } from "@/components/ui";
import type { Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/doc-lap";

const TEXT = {
  vi: {
    description: "Ai trả tiền cho SoiVí? Không ai cả. Cách chúng tôi giữ số liệu độc lập.",
    sections: [
      {
        h: "Ai trả tiền cho chúng tôi: không ai cả",
        p: [
          "SoiVí không nhận tiền từ ngân hàng, công ty tài chính hay bất kỳ ai được so sánh trên trang. Chúng tôi không có quảng cáo, không có liên kết hoa hồng (affiliate) và không bán vị trí trên bảng xếp hạng.",
          "Nếu sau này có nguồn thu, chúng tôi sẽ công bố trên trang này trước, và nguồn thu đó sẽ không bao giờ ảnh hưởng đến thứ hạng.",
        ],
      },
      {
        h: "Số liệu chỉ lấy từ ngân hàng",
        p: [
          "Mỗi con số đều lấy từ trang web hoặc biểu phí của chính ngân hàng. Chúng tôi lưu bản sao tài liệu, ghi lại thời điểm kiểm tra, và mỗi thay đổi đều được một người duyệt trước khi hiển thị.",
          "Tin tức và báo cáo của người dùng chỉ giúp chúng tôi biết cần kiểm tra lại. Chúng không bao giờ là nguồn của một con số.",
        ],
      },
      {
        h: "Thứ hạng theo công thức công khai",
        p: [
          "Thứ hạng do công thức công khai quyết định, có số phiên bản, và mọi thay đổi đều được ghi lại. Không ai, kể cả chúng tôi, có thể đẩy một sản phẩm lên trên.",
        ],
      },
      {
        h: "Khi chúng tôi sai",
        p: [
          "Mỗi bảng đều có nút “Báo sai số liệu”. Chúng tôi kiểm tra lại mọi báo cáo với trang của ngân hàng và sửa bằng một phiên bản mới; số cũ vẫn được giữ trong lịch sử.",
        ],
      },
    ],
  },
  en: {
    description: "Who pays SoiVí? Nobody. How we keep the numbers independent.",
    sections: [
      {
        h: "Who pays us: nobody",
        p: [
          "SoiVí takes no money from the banks, finance companies or anyone else we compare. We have no ads, no affiliate links and no paid placement.",
          "If we ever have income, we will publish it here first, and it will never affect a ranking.",
        ],
      },
      {
        h: "Numbers come only from the banks",
        p: [
          "Every number comes from the bank's own website or fee schedule. We keep a copy of the document, record when we checked it, and a person approves every change before it appears.",
          "News and reader reports only tell us to check again. They are never the source of a number.",
        ],
      },
      {
        h: "Rankings follow a public formula",
        p: [
          "Rankings come from a public, versioned formula, and every change to it is logged. Nobody, including us, can push a product up.",
        ],
      },
      {
        h: "When we are wrong",
        p: [
          "Every table has a “Report a wrong number” button. We re-check every report against the bank's page and fix it with a new version; the old value stays in the history.",
        ],
      },
    ],
  },
};

export async function generateMetadata({ params }: PageProps<"/[lang]/doc-lap">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, t(lang).independence.title, TEXT[lang].description);
}

export default async function IndependencePage({ params }: PageProps<"/[lang]/doc-lap">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  return (
    <article className="sv-container space-y-10 py-12">
      <JsonLd
        data={breadcrumbs(lang, [
          { name: d.siteName, path: "/" },
          { name: d.independence.title, path: PATH },
        ])}
      />
      <PageHead eyebrow={d.nav.independence} title={d.independence.title} intro={TEXT[lang].description} />
      <div className="grid gap-6 md:grid-cols-2">
        {TEXT[lang].sections.map((s) => (
          <section key={s.h} className="sv-panel space-y-2">
            <h2 className="flex items-center gap-2 t-h3">
              <Icon name="check" size={20} className="text-jade" />
              {s.h}
            </h2>
            {s.p.map((p) => (
              <p key={p} className="text-muted">
                {p}
              </p>
            ))}
          </section>
        ))}
      </div>
      <Button variant="secondary" href={href(lang, "/phuong-phap")} iconRight="arrow">
        {d.nav.method}
      </Button>
    </article>
  );
}
