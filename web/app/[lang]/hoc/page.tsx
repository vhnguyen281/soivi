import type { Metadata } from "next";

import { JsonLd } from "@/components/Chrome";
import { LessonScraps } from "@/components/LessonScraps";
import { mapFonts } from "@/lib/fonts";
import type { Lang } from "@/lib/format";
import { t } from "@/lib/i18n";
import { LESSONS } from "@/lib/learn";
import { breadcrumbs, pageMetadata } from "@/lib/seo";

const PATH = "/hoc";

const TEXT = {
  vi: {
    title: "Học cùng SoiVí",
    hand: "kéo, bấm, thử: mỗi bài vài phút",
    intro:
      "Các bài học tương tác dùng số liệu thật đã kiểm tra trên SoiVí. Mỗi bài kết thúc bằng một công cụ để bạn áp dụng ngay. Tiến độ chỉ lưu trên trình duyệt này.",
  },
  en: {
    title: "Learn with SoiVí",
    hand: "drag, tap, try: a few minutes each",
    intro:
      "Interactive lessons built on the checked numbers in SoiVí. Each ends with a tool to apply it right away. Progress stays in this browser.",
  },
};

export async function generateMetadata({ params }: PageProps<"/[lang]/hoc">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  return pageMetadata(lang, PATH, TEXT[lang].title, TEXT[lang].intro);
}

export default async function LearnPage({ params }: PageProps<"/[lang]/hoc">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const x = TEXT[lang];
  const lessons = LESSONS.map((l) => ({ slug: l.slug, title: l[lang].title, summary: l[lang].summary, minutes: l.minutes, ready: l.status === "ready" }));
  return (
    <div className={`map ${mapFonts}`}>
      <article className="sv-container space-y-10 py-14">
        <JsonLd
          data={breadcrumbs(lang, [
            { name: d.siteName, path: "/" },
            { name: x.title, path: PATH },
          ])}
        />
        <header className="max-w-3xl space-y-3">
          <h1 className="map-title text-[clamp(40px,5vw,72px)]">{x.title}</h1>
          <p className="map-hand -rotate-1 text-[26px] text-[var(--map-terra)]">{x.hand}</p>
          <p>{x.intro}</p>
        </header>
        <LessonScraps lang={lang} lessons={lessons} showCount />
      </article>
    </div>
  );
}
