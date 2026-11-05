"use client";

import { usePathname } from "next/navigation";

/**
 * Same page in the other language: /x <-> /en/x. A plain <a>: the two languages
 * have separate root layouts, so this is always a full page load (and must not
 * be prefetched as a client-side transition).
 */
export function LangToggle({ lang, label, title }: { lang: "vi" | "en"; label: string; title: string }) {
  const pathname = usePathname() || "/";
  let target: string;
  if (lang === "vi") {
    target = pathname === "/" ? "/en" : `/en${pathname}`;
  } else {
    target = pathname.replace(/^\/en(?=\/|$)/, "") || "/";
  }
  return (
    <a
      href={target}
      hrefLang={lang === "vi" ? "en" : "vi"}
      lang={lang === "vi" ? "en" : "vi"}
      title={title}
      className="sv-pill"
    >
      {label}
    </a>
  );
}
