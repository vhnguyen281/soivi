"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

export type NavItem = { label: string; href: string } | { label: string; children: { label: string; href: string }[] };

/** Main navigation: four pillars; two open a short list. Lists close on navigation, Escape or a click outside. */
export function NavMenu({ items, label }: { items: NavItem[]; label: string }) {
  const path = usePathname();
  const root = useRef<HTMLUListElement>(null);
  const closeAll = () => root.current?.querySelectorAll("details[open]").forEach((d) => d.removeAttribute("open"));

  useEffect(closeAll, [path]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeAll();
    const onClick = (e: MouseEvent) => !root.current?.contains(e.target as Node) && closeAll();
    document.addEventListener("keydown", onKey);
    document.addEventListener("click", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("click", onClick);
    };
  }, []);

  const active = (href: string) => path === href || path.startsWith(`${href}/`);
  const link = "t-small font-semibold text-ink no-underline hover:text-jade";
  return (
    <nav aria-label={label} className="order-3 w-full sm:order-none sm:w-auto">
      <ul ref={root} className="flex flex-wrap gap-x-6 gap-y-1">
        {items.map((item, i) =>
          "href" in item ? (
            <li key={item.label}>
              <Link href={item.href} className={link} aria-current={active(item.href) ? "page" : undefined}>
                {item.label}
              </Link>
            </li>
          ) : (
            <li key={item.label} className="relative">
              <details
                onToggle={(e) => {
                  if ((e.target as HTMLDetailsElement).open)
                    root.current?.querySelectorAll("details[open]").forEach((d) => d !== e.target && d.removeAttribute("open"));
                }}
              >
                <summary className={`${link} cursor-pointer list-none`}>
                  {item.label} <span aria-hidden="true">▾</span>
                </summary>
                <ul className={`sv-panel absolute z-40 mt-2 grid min-w-56 gap-1 !p-2 ${i === items.length - 1 ? "right-0" : "left-0"}`}>
                  {item.children.map((c) => (
                    <li key={c.href}>
                      <Link
                        href={c.href}
                        className="block rounded px-3 py-2 t-small font-semibold text-ink no-underline hover:bg-surface-alt"
                        aria-current={active(c.href) ? "page" : undefined}
                      >
                        {c.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </details>
            </li>
          ),
        )}
      </ul>
    </nav>
  );
}
