// SoiVí design system components (https://claude.ai/artifact/8HDJ378MFAbBLaTZgLWvtG),
// ported from its bundle to server-friendly React. Styles live in app/globals.css (sv-*).

import Link from "next/link";
import type { ReactNode } from "react";

import type { Lang } from "@/lib/format";

// ---- icons: 24px grid, 1.75 stroke, currentColor; always next to a word ----
const ICON_PATHS = {
  check: "M20 6 9 17l-5-5",
  alert:
    "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  info: "M12 16v-4M12 8h.01M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z",
  card: "M2 7a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2zM2 10h20M6 15h4",
  savings:
    "M12 3v18M17 7.5c0-1.9-2.2-3.5-5-3.5s-5 1.6-5 3.5S9.2 11 12 11s5 1.6 5 3.5S14.8 18 12 18s-5-1.6-5-3.5",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  chart: "M3 3v18h18M7 15l4-4 3 3 5-6",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  external: "M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6",
  sort: "M7 4v16M3 16l4 4 4-4M17 20V4M13 8l4-4 4 4",
  up: "M12 19V5M5 12l7-7 7 7",
  down: "M12 5v14M19 12l-7 7-7-7",
  arrow: "M5 12h14M13 5l7 7-7 7",
} as const;

export type IconName = keyof typeof ICON_PATHS;

export function Icon({ name, size = 16, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`sv-icon flex-none ${className ?? ""}`}
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

// ---- Button (a link when href is set) ----
type ButtonProps = {
  variant?: "primary" | "secondary" | "ghost";
  size?: "md" | "sm";
  block?: boolean;
  href?: string;
  external?: boolean;
  iconRight?: IconName;
  children: ReactNode;
  className?: string;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children">;

export function Button({
  variant = "secondary",
  size = "md",
  block,
  href,
  external,
  iconRight,
  children,
  className,
  ...rest
}: ButtonProps) {
  const cls = [
    "sv-btn",
    `sv-btn--${variant}`,
    size === "sm" ? "sv-btn--sm" : "",
    block ? "sv-btn--block" : "",
    className ?? "",
  ].join(" ");
  const kids = (
    <>
      {children}
      {iconRight ? <Icon name={iconRight} /> : null}
    </>
  );
  if (href && external) {
    return (
      <a href={href} className={cls} rel="nofollow noopener" target="_blank">
        {kids}
      </a>
    );
  }
  if (href) {
    return (
      <Link href={href} className={cls}>
        {kids}
      </Link>
    );
  }
  return (
    <button type="button" className={cls} {...rest}>
      {kids}
    </button>
  );
}

// ---- Badge ----
export type Tone = "neutral" | "jade" | "gold" | "verified" | "warn" | "danger";

export function Badge({
  tone = "neutral",
  icon,
  title,
  children,
}: {
  tone?: Tone;
  icon?: IconName;
  title?: string;
  children: ReactNode;
}) {
  const shown = icon ?? (tone === "verified" ? "check" : tone === "warn" ? "alert" : undefined);
  return (
    <span className={`sv-badge sv-badge--${tone}`} title={title}>
      {shown ? <Icon name={shown} size={14} /> : null}
      {children}
    </span>
  );
}

// ---- SourceStamp: under every number we publish ----
const STAMP = {
  vi: { ok: "Đã xác minh", warn: "Chưa xác minh", checked: "Kiểm tra", effective: "Hiệu lực", source: "Nguồn" },
  en: { ok: "Verified", warn: "Unverified", checked: "Checked", effective: "Effective", source: "Source" },
};

export function SourceStamp({
  lang,
  status = "verified",
  checkedAt,
  effectiveFrom,
  sourceLabel,
  href,
  cell,
}: {
  lang: Lang;
  status?: "verified" | "unverified";
  checkedAt?: string | null;
  effectiveFrom?: string | null;
  sourceLabel?: string;
  href?: string | null;
  cell?: boolean;
}) {
  const w = STAMP[lang];
  const ok = status !== "unverified";
  const parts: string[] = [];
  if (checkedAt) parts.push(`${w.checked} ${checkedAt}`);
  if (effectiveFrom) parts.push(`${w.effective} ${effectiveFrom}`);
  return (
    <p className={`sv-stamp ${ok ? "sv-stamp--ok" : "sv-stamp--warn"} ${cell ? "sv-stamp--cell" : ""}`}>
      <span className="sv-stamp__status">
        <Icon name={ok ? "check" : "alert"} size={14} />
        {ok ? w.ok : w.warn}
      </span>
      {parts.length ? <span> · {parts.join(" · ")}</span> : null}
      {sourceLabel ? (
        <span>
          {" · "}
          {w.source}:{" "}
          {href ? (
            <a href={href} rel="nofollow noopener" target="_blank">
              {sourceLabel}
            </a>
          ) : (
            sourceLabel
          )}
        </span>
      ) : null}
    </p>
  );
}

// ---- TipBox: "Mẹo Soi" ----
export function TipBox({ title, children }: { title: string; children: ReactNode }) {
  return (
    <aside className="sv-tip">
      <span className="sv-tip__label">{title}</span>
      <div>{children}</div>
    </aside>
  );
}

// ---- CategoryTile ----
export function CategoryTile({
  icon,
  title,
  description,
  href,
}: {
  icon: IconName;
  title: string;
  description: string;
  href: string;
}) {
  return (
    <Link href={href} className="sv-tile">
      <span className="sv-tile__icon">
        <Icon name={icon} size={24} />
      </span>
      <span className="sv-tile__title">{title}</span>
      <span className="sv-tile__desc">{description}</span>
    </Link>
  );
}

// ---- Card art: a flat placeholder with the issuer's initials (no card images) ----
export function CardArt({ issuer }: { issuer: string }) {
  const name = issuer
    .replace(/\(.*?\)/g, "")
    .replace(/^\s*(Ngân hàng|Công ty Tài chính|Công ty)\s+/i, "")
    .trim();
  // A short bank code reads best whole (BIDV, VPBANK); a long one is cut to 4 letters.
  const initials = /^[A-Z0-9]{2,}$/.test(name)
    ? name.length <= 6
      ? name
      : name.slice(0, 4)
    : name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 3)
        .map((w) => w[0])
        .join("")
        .toUpperCase();
  return (
    <div className="sv-pcard__art" aria-hidden="true">
      <span>{initials}</span>
    </div>
  );
}

// ---- Section heading with an optional action on the right ----
export function SectionHead({
  id,
  title,
  intro,
  action,
}: {
  id: string;
  title: string;
  intro?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="space-y-1">
        <h2 id={id} className="t-h2">
          {title}
        </h2>
        {intro ? <p className="t-small text-muted">{intro}</p> : null}
      </div>
      {action}
    </div>
  );
}
