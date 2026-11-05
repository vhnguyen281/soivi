// Pure helpers (no Next.js imports) so they can be unit-tested with `node --test`.

export type Lang = "vi" | "en";
export const LANGS: Lang[] = ["vi", "en"];
export const isLang = (value: string): value is Lang => value === "vi" || value === "en";

const TZ = "Asia/Ho_Chi_Minh";

/** 1500000 -> "1.500.000 ₫" (vi) / "₫1,500,000" (en). */
export function vnd(amount: number, lang: Lang): string {
  return new Intl.NumberFormat(lang === "vi" ? "vi-VN" : "en-US", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(amount);
}

/** Short amounts for tables: 1500000 -> "1,5 triệu" / "1.5M". */
export function vndShort(amount: number, lang: Lang): string {
  const units: [number, string, string][] = [
    [1e9, " tỷ", "B"],
    [1e6, " triệu", "M"],
    [1e3, " nghìn", "K"],
  ];
  for (const [size, vi, en] of units) {
    if (Math.abs(amount) >= size) {
      const n = amount / size;
      const text = new Intl.NumberFormat(lang === "vi" ? "vi-VN" : "en-US", {
        maximumFractionDigits: 2,
      }).format(n);
      return lang === "vi" ? `${text}${vi}` : `${text}${en}`;
    }
  }
  return String(amount);
}

/** "5.900" -> "5,90%" (vi) / "5.90%" (en): two decimals, as banks write them. */
export function pct(value: string | number, lang: Lang): string {
  const n = typeof value === "number" ? value : Number(value);
  return (
    new Intl.NumberFormat(lang === "vi" ? "vi-VN" : "en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 3,
    }).format(n) + "%"
  );
}

/** ISO time -> local date, e.g. "28/10/2026" (vi) / "28 Oct 2026" (en). */
export function date(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00+07:00` : iso);
  return new Intl.DateTimeFormat(lang === "vi" ? "vi-VN" : "en-GB", {
    day: "2-digit",
    month: lang === "vi" ? "2-digit" : "short",
    year: "numeric",
    timeZone: TZ,
  }).format(d);
}

/** "Techcombank Visa Signature" -> "techcombank-visa-signature" (accents removed). */
export function slugify(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export const cardSlug = (name: string, id: number) => `${slugify(name)}-${id}`;

/** "techcombank-visa-signature-12" -> 12 (the id is what the API needs). */
export function cardIdFromSlug(slug: string): number | null {
  const m = /-(\d+)$/.exec(slug) ?? /^(\d+)$/.exec(slug);
  return m ? Number(m[1]) : null;
}

export const bankSlug = (shortName: string) => shortName.toLowerCase();

/** Term label: 12 months -> "12 tháng" / "12 months"; 0/0 -> demand. */
export function term(months: number, days: number, lang: Lang): string {
  if (days) return lang === "vi" ? `${days} ngày` : `${days} days`;
  if (!months) return lang === "vi" ? "Không kỳ hạn" : "Demand";
  return lang === "vi" ? `${months} tháng` : `${months} month${months === 1 ? "" : "s"}`;
}

/** Monday of the ISO week containing the date, in Vietnam time, as YYYY-MM-DD. */
export function weekStart(iso: string): string {
  const local = new Date(new Date(iso).getTime() + 7 * 3_600_000); // UTC+7, no DST
  const day = (local.getUTCDay() + 6) % 7; // Monday = 0
  local.setUTCDate(local.getUTCDate() - day);
  return local.toISOString().slice(0, 10);
}

/** ISO week number (1-53) of a YYYY-MM-DD Monday. */
export function isoWeek(monday: string): number {
  const d = new Date(`${monday}T00:00:00Z`);
  const thursday = new Date(d);
  thursday.setUTCDate(d.getUTCDate() + 3);
  const firstThursday = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 4));
  return 1 + Math.round((thursday.getTime() - firstThursday.getTime()) / (7 * 86_400_000));
}

/** "Tiết kiệm thường · counter · 12 tháng" -> channel words in the page's language. */
export function localizeLabel(label: string, channels: Record<string, string>): string {
  return label
    .split(" · ")
    .map((part) => channels[part] ?? part)
    .join(" · ");
}

/** Direction of a numeric change: 1 up, -1 down, 0 same or not numeric. */
export function direction(oldValue: unknown, newValue: unknown): -1 | 0 | 1 {
  const a = Number(oldValue);
  const b = Number(newValue);
  if (oldValue === null || newValue === null || Number.isNaN(a) || Number.isNaN(b)) return 0;
  return b > a ? 1 : b < a ? -1 : 0;
}

/** Scale points to an SVG box: returns "x,y" pairs for a polyline. */
export function polyline(
  points: { t: number; v: number }[],
  box: { width: number; height: number; tMin: number; tMax: number; vMin: number; vMax: number },
): string {
  const { width, height, tMin, tMax, vMin, vMax } = box;
  const sx = (t: number) => (tMax === tMin ? width / 2 : ((t - tMin) / (tMax - tMin)) * width);
  const sy = (v: number) => (vMax === vMin ? height / 2 : height - ((v - vMin) / (vMax - vMin)) * height);
  return points.map((p) => `${sx(p.t).toFixed(1)},${sy(p.v).toFixed(1)}`).join(" ");
}

/** JSON for <script type="application/ld+json">, with "<" escaped (no </script> breakout). */
export function jsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
