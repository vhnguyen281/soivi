"use client";

import Link from "next/link";
import { useState } from "react";

import type { Lang } from "@/lib/format";
import { href } from "@/lib/i18n";

import { LEARN_KEY, useProgress } from "../useProgress";

/** One numbered step of a lesson. */
export function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="map-card space-y-4" aria-labelledby={`step-${n}`}>
      <p className="map-hand text-[20px] text-[var(--map-teal)]">{`${n}`.padStart(2, "0")}</p>
      <h2 id={`step-${n}`} className="map-title text-[clamp(26px,3vw,36px)]">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** A multiple-choice check: the answer and why, once picked. */
export function Quiz({ lang, question, options, answer, why }: { lang: Lang; question: string; options: string[]; answer: number; why: string }) {
  const [picked, setPicked] = useState<number | null>(null);
  return (
    <fieldset className="space-y-3">
      <legend className="font-semibold">{question}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((o, i) => {
          const state = picked === null ? "" : i === answer ? "border-[var(--map-teal)] bg-[color-mix(in_srgb,var(--map-teal)_12%,transparent)]" : i === picked ? "border-[var(--map-terra)]" : "opacity-70";
          return (
            <button
              key={o}
              type="button"
              aria-pressed={picked === i}
              className={`min-h-11 rounded-lg border-2 border-[var(--map-ink)] px-3 py-2 text-left ${state}`}
              onClick={() => setPicked(i)}
            >
              {o}
              {picked !== null && i === answer ? " ✓" : ""}
            </button>
          );
        })}
      </div>
      {picked !== null ? (
        <p aria-live="polite" className="map-hand text-[20px]">
          {picked === answer ? (lang === "vi" ? "Chính xác! " : "Right! ") : lang === "vi" ? "Chưa đúng. " : "Not quite. "}
          <span className="font-sans text-base">{why}</span>
        </p>
      ) : null}
    </fieldset>
  );
}

/** End of a lesson: mark it learnt, apply it with a tool, go on to the next lesson. */
export function LessonEnd({
  lang,
  slug,
  tool,
  toolLabel,
  next,
}: {
  lang: Lang;
  slug: string;
  tool: string;
  toolLabel: string;
  next: { slug: string; title: string } | null;
}) {
  const { done, set } = useProgress(LEARN_KEY);
  const learnt = done.includes(slug);
  const v = lang === "vi";
  return (
    <section className="map-card map-card--pinned space-y-4">
      <h2 className="map-title text-[30px]">{v ? "Áp dụng cho bạn" : "Apply it to you"}</h2>
      <p>
        <Link href={href(lang, tool)} className="map-hand text-[24px]">
          {toolLabel} →
        </Link>
      </p>
      <div className="flex flex-wrap items-center gap-4">
        <button type="button" className="sv-btn sv-btn--primary" aria-pressed={learnt} onClick={() => set(slug, !learnt)}>
          {learnt ? (v ? "✓ Đã học (bấm để bỏ)" : "✓ Learnt (tap to undo)") : v ? "Đánh dấu đã học" : "Mark as learnt"}
        </button>
        {next ? (
          <Link href={href(lang, `/hoc/${next.slug}`)} className="map-hand text-[22px]">
            {v ? "Bài tiếp: " : "Next: "}
            {next.title} →
          </Link>
        ) : (
          <Link href={href(lang, "/hoc")} className="map-hand text-[22px]">
            {v ? "Tất cả bài học" : "All lessons"} →
          </Link>
        )}
      </div>
      <p className="text-xs text-[var(--map-muted)]">
        {v ? "Tiến độ chỉ lưu trên trình duyệt này." : "Progress stays in this browser."}
      </p>
    </section>
  );
}
