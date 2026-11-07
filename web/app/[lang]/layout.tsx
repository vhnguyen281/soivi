import "../globals.css";

import type { Metadata, Viewport } from "next";
import { Be_Vietnam_Pro } from "next/font/google";
import { notFound } from "next/navigation";
import { lang as rootLang } from "next/root-params";

import { Footer, Header } from "@/components/Chrome";
import { getMethodologyVersion } from "@/lib/api";
import { isLang, LANGS } from "@/lib/format";
import { SITE_URL, t } from "@/lib/i18n";

// Drawn for Vietnamese diacritics; self-hosted by Next at build (no request to Google).
const beVietnam = Be_Vietnam_Pro({
  subsets: ["vietnamese", "latin"],
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
  variable: "--font-be-vietnam",
});

export function generateStaticParams() {
  return LANGS.map((lang) => ({ lang }));
}

export async function generateMetadata(): Promise<Metadata> {
  const lang = await rootLang();
  const d = t(isLang(lang) ? lang : "vi");
  return {
    metadataBase: new URL(SITE_URL),
    title: { default: `${d.siteName} · ${d.tagline}`, template: `%s · ${d.siteName}` },
    description: d.tagline,
    applicationName: d.siteName,
  };
}

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
  ],
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({ children }: LayoutProps<"/[lang]">) {
  const lang = await rootLang();
  if (!isLang(lang)) notFound();
  const version = await getMethodologyVersion();
  return (
    <html lang={lang} className={beVietnam.variable}>
      <body className="flex min-h-screen flex-col">
        <Header lang={lang} />
        <main id="main" className="flex-1">
          {children}
        </main>
        <Footer lang={lang} version={version} />
      </body>
    </html>
  );
}
