"use client";

import Link from "next/link";

import type { Lang } from "@/lib/format";
import { href } from "@/lib/i18n";

import { LEARN_KEY, useProgress } from "./useProgress";

export type ScrapLesson = { slug: string; title: string; summary?: string; minutes: number; ready: boolean };

/** Lessons as torn map pieces; a red seal marks the ones learnt in this browser. */
export function LessonScraps({ lang, lessons, showCount }: { lang: Lang; lessons: ScrapLesson[]; showCount?: boolean }) {
  const { done } = useProgress(LEARN_KEY);
  const learnt = lessons.filter((l) => done.includes(l.slug)).length;
  const soon = lang === "vi" ? "Sắp có" : "Coming soon";
  const min = lang === "vi" ? "phút" : "min";
  return (
    <div className="space-y-4">
      {showCount ? (
        <p className="map-hand">
          {lang === "vi" ? `Đã học ${learnt}/${lessons.length} bài` : `${learnt}/${lessons.length} lessons done`}
        </p>
      ) : null}
      <ul className="grid gap-6 md:grid-cols-3">
        {lessons.map((l, i) => {
          const isDone = done.includes(l.slug);
          const inner = (
            <>
              <span className="map-hand text-[18px] text-[var(--map-teal)]">
                {i + 1} · {l.minutes} {min}
                {l.ready ? "" : ` · ${soon}`}
              </span>
              <span className="map-title mt-2 block text-[22px]">{l.title}</span>
              {l.summary ? <span className="mt-2 block pr-12 text-sm">{l.summary}</span> : null}
              <span className={`map-seal ${isDone ? "map-seal--done" : ""}`} aria-hidden="true">
                {isDone ? "✓" : "?"}
              </span>
              {isDone ? <span className="sr-only">{lang === "vi" ? "(đã học)" : "(learnt)"}</span> : null}
            </>
          );
          return (
            <li key={l.slug}>
              {l.ready ? (
                <Link href={href(lang, `/hoc/${l.slug}`)} className="map-scrap min-h-32">
                  {inner}
                </Link>
              ) : (
                <div className="map-scrap min-h-32 opacity-70">{inner}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
