"use client";

import Link from "next/link";

import type { Lang } from "@/lib/format";
import { href } from "@/lib/i18n";

import { JOURNEY_KEY, useProgress } from "./useProgress";

export type PlanStep = { id: string; path: string; title: string; what: string; need: string; minutes: number };

/** The planning journey: numbered stops on a trail; a stop is ticked once opened from here (kept in this browser). */
export function PlanSteps({ lang, steps }: { lang: Lang; steps: PlanStep[] }) {
  const { done, set } = useProgress(JOURNEY_KEY);
  const count = steps.filter((s) => done.includes(s.id)).length;
  const v = lang === "vi";
  return (
    <div className="space-y-6">
      <p className="map-hand" aria-live="polite">
        {v ? `Đã mở ${count}/${steps.length} bước` : `${count}/${steps.length} steps opened`}
      </p>
      <ol className="relative space-y-4 border-l-2 border-[var(--line)] pl-8">
        {steps.map((s, i) => {
          const visited = done.includes(s.id);
          return (
            <li key={s.id} className="relative">
              <span
                className={`map-seal ${visited ? "map-seal--done" : ""} !-left-[3.35rem] !top-3 !bottom-auto !right-auto`}
                aria-hidden="true"
              >
                {visited ? "✓" : i + 1}
              </span>
              <div className="map-card space-y-2">
                <p className="map-hand text-[20px] text-[var(--map-teal)]">
                  {v ? "Bước" : "Step"} {i + 1} · ~{s.minutes} {v ? "phút" : "min"}
                  {visited ? (v ? " · đã mở" : " · opened") : ""}
                </p>
                <h2 className="map-title text-[28px]">
                  <Link href={href(lang, s.path)} onClick={() => set(s.id, true)}>
                    {s.title} →
                  </Link>
                </h2>
                <p>{s.what}</p>
                <p className="text-sm text-[var(--map-muted)]">
                  {v ? "Cần chuẩn bị: " : "Have ready: "}
                  {s.need}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
