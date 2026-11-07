import Link from "next/link";
import { Suspense } from "react";

import type { Lang } from "@/lib/format";
import { href, t } from "@/lib/i18n";

import { LangToggle } from "./LangToggle";
import { NavMenu, type NavItem } from "./NavMenu";
import { Badge, Icon } from "./ui";

export function Header({ lang }: { lang: Lang }) {
  const d = t(lang);
  const items: NavItem[] = [
    {
      label: d.nav.compare,
      children: [
        { label: d.nav.savings, href: href(lang, "/lai-suat-tiet-kiem") },
        { label: d.nav.cards, href: href(lang, "/the-tin-dung") },
        { label: d.nav.moves, href: href(lang, "/bien-dong-lai-suat") },
        { label: d.nav.funds, href: href(lang, "/quy-dau-tu") },
      ],
    },
    { label: d.nav.plan, href: href(lang, "/lap-ke-hoach") },
    { label: d.nav.learn, href: href(lang, "/hoc") },
    {
      label: d.nav.trust,
      children: [
        { label: d.nav.method, href: href(lang, "/phuong-phap") },
        { label: d.nav.vncma, href: href(lang, "/gia-dinh-thi-truong") },
        { label: d.nav.independence, href: href(lang, "/doc-lap") },
      ],
    },
  ];
  return (
    <header className="border-b border-line bg-surface">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-surface focus:p-2"
      >
        {d.skip}
      </a>
      <div className="sv-container flex flex-wrap items-center gap-x-8 gap-y-2 py-3">
        {/* No logo yet: the name in Be Vietnam Pro 800 (brand book). */}
        <Link href={href(lang)} className="text-[26px] leading-8 font-extrabold tracking-tight text-ink no-underline">
          SoiVí
        </Link>
        <NavMenu items={items} label={d.nav.menu} />
        <div className="ml-auto">
          <Suspense fallback={null}>
            <LangToggle lang={lang} label={d.langSwitch} title={d.langSwitchLabel} />
          </Suspense>
        </div>
      </div>
    </header>
  );
}

/** "For information only": shown under every comparison. */
export function Disclaimer({ lang }: { lang: Lang }) {
  return (
    <p role="note" className="sv-note">
      <Icon name="info" />
      <span>{t(lang).disclaimer}</span>
    </p>
  );
}

export function Footer({ lang, version }: { lang: Lang; version: string }) {
  const d = t(lang);
  return (
    <footer className="mt-16 border-t border-line bg-surface-alt">
      <div className="sv-container grid gap-6 py-12 sm:grid-cols-[1fr_auto]">
        <div className="space-y-2">
          <p className="text-[22px] leading-7 font-extrabold text-ink">SoiVí</p>
          <p className="t-small max-w-xl text-muted">{d.tagline}</p>
          <p className="t-small flex items-center gap-2 font-semibold text-ink">
            <Icon name="shield" className="text-jade" />
            {d.footerFunding}
          </p>
          <p className="t-caption text-muted">{d.disclaimerShort}</p>
        </div>
        <ul className="t-small space-y-2">
          <li>
            <Link href={href(lang, "/doc-lap")}>{d.nav.independence}</Link>
          </li>
          <li>
            <Link href={href(lang, "/phuong-phap")}>{d.nav.method}</Link>{" "}
            <span className="text-muted">v{version}</span>
          </li>
          <li>
            <Link href={href(lang, "/bien-dong-lai-suat")}>{d.nav.moves}</Link>
          </li>
        </ul>
      </div>
    </footer>
  );
}

export function UnverifiedBadge({ lang }: { lang: Lang }) {
  const d = t(lang);
  return (
    <span className="ml-2 align-middle">
      <Badge tone="warn" title={d.unverifiedTitle}>
        {d.unverified}
        <span className="sr-only">: {d.unverifiedTitle}</span>
      </Badge>
    </span>
  );
}

export function JsonLd({ data }: { data: unknown }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }}
    />
  );
}

/** A page's title block: eyebrow, h1, intro. */
export function PageHead({
  eyebrow,
  title,
  intro,
  children,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  intro?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="space-y-3 pb-2">
      {eyebrow ? <p className="t-label text-jade">{eyebrow}</p> : null}
      <h1 className="t-display">{title}</h1>
      {intro ? <p className="t-body-lg max-w-3xl text-muted">{intro}</p> : null}
      {children}
    </header>
  );
}
