"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import type { Lang } from "@/lib/format";
import { termById } from "@/lib/glossary";
import { href } from "@/lib/i18n";

/** An underlined word; tapping it opens a short definition (and a link to its lesson). */
export function Term({ id, lang, children }: { id: string; lang: Lang; children?: React.ReactNode }) {
  const t = termById(id);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const tip = useId();
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", close);
    document.addEventListener("click", close);
    return () => {
      document.removeEventListener("keydown", close);
      document.removeEventListener("click", close);
    };
  }, [open]);
  if (!t) return <>{children}</>;
  const x = t[lang];
  return (
    <span ref={box} className="relative inline">
      <button
        type="button"
        className="cursor-help underline decoration-dotted decoration-2 underline-offset-4"
        aria-expanded={open}
        aria-controls={tip}
        onClick={() => setOpen(!open)}
      >
        {children ?? x.term}
      </button>
      {open ? (
        <span
          id={tip}
          role="note"
          className="absolute left-0 top-full z-50 mt-2 block w-72 max-w-[80vw] rounded-lg border-2 border-[var(--map-ink,currentColor)] bg-[var(--map-card,var(--surface))] p-3 text-left text-sm font-normal not-italic text-[var(--map-ink,var(--ink))] shadow-lg"
        >
          <b className="block">{x.term}</b>
          {x.def}
          {t.lesson ? (
            <Link href={href(lang, `/hoc/${t.lesson}`)} className="mt-1 block">
              {lang === "vi" ? "Học thêm" : "Learn more"} →
            </Link>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}
