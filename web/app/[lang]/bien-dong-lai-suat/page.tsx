import type { Metadata } from "next";
import Link from "next/link";

import { Disclaimer, JsonLd, PageHead } from "@/components/Chrome";
import { Badge, Icon, SourceStamp } from "@/components/ui";
import { ReportButton } from "@/components/ReportButton";
import { getChanges } from "@/lib/api";
import { date, direction, isoWeek, pct, vnd, weekStart, type Lang, localizeLabel } from "@/lib/format";
import { absolute, href, t } from "@/lib/i18n";
import { breadcrumbs, pageMetadata } from "@/lib/seo";
import type { Change } from "@/lib/types";

const PATH = "/bien-dong-lai-suat";
const WEEKS = 12;
const ROWS_PER_WEEK = 40; // the largest moves; the summary line counts them all

export async function generateMetadata({ params }: PageProps<"/[lang]/bien-dong-lai-suat">): Promise<Metadata> {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  return pageMetadata(lang, PATH, d.moves.title, d.moves.intro);
}

function rateChange(c: Change) {
  return c.changes.find((x) => x.field === "rate_pct");
}

function showValue(field: string, value: unknown, lang: Lang): string {
  if (value === null || value === undefined) return "—";
  if (field.endsWith("_pct")) return pct(String(value), lang);
  if (field.endsWith("_vnd")) return vnd(Number(value), lang);
  return String(value);
}

export default async function MovesPage({ params }: PageProps<"/[lang]/bien-dong-lai-suat">) {
  const lang = (await params).lang as Lang;
  const d = t(lang);
  const { changes } = await getChanges(WEEKS);

  const weeks = new Map<string, Change[]>();
  for (const c of changes) {
    const key = weekStart(c.approved_at);
    weeks.set(key, [...(weeks.get(key) ?? []), c]);
  }
  const ordered = [...weeks.entries()].sort(([a], [b]) => (a < b ? 1 : -1));

  return (
    <div className="sv-container space-y-12 py-12">
      <JsonLd
        data={[
          breadcrumbs(lang, [
            { name: d.siteName, path: "/" },
            { name: d.moves.title, path: PATH },
          ]),
          {
            "@context": "https://schema.org",
            "@type": "Dataset",
            name: d.moves.title,
            description: d.moves.intro,
            url: absolute(lang, PATH),
            creator: { "@type": "Organization", name: d.siteName },
            isAccessibleForFree: true,
          },
        ]}
      />
      <PageHead eyebrow={d.nav.moves} title={d.moves.title} intro={d.moves.intro} />
      {ordered.length === 0 ? <p>{d.moves.none}</p> : null}
      {ordered.map(([monday, items]) => {
        const rates = items.filter((c) => c.table === "savings_rate");
        const up = rates.filter((c) => {
          const r = rateChange(c);
          return c.kind === "changed" && r && direction(r.old, r.new) > 0;
        }).length;
        const down = rates.filter((c) => {
          const r = rateChange(c);
          return c.kind === "changed" && r && direction(r.old, r.new) < 0;
        }).length;
        const added = items.filter((c) => c.kind === "new").length;
        const size = (c: Change) => {
          const r = rateChange(c);
          return c.kind === "new" ? -1 : r ? Math.abs(Number(r.new) - Number(r.old)) : 0;
        };
        const shownItems = [...items].sort((a, b) => size(b) - size(a)).slice(0, ROWS_PER_WEEK);
        const hidden = items.length - shownItems.length;
        const id = `w-${monday}`;
        return (
          <section key={monday} aria-labelledby={id} className="space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id={id} className="t-h2">
                {d.moves.week(isoWeek(monday), date(monday, lang))}
              </h2>
              <ReportButton labels={d.report} productRef={`${d.moves.title} ${monday}`} />
            </div>
            <p className="flex flex-wrap gap-2">
              <Badge tone="jade" icon="up">{`${up} ${d.moves.up}`}</Badge>
              <Badge tone="danger" icon="down">{`${down} ${d.moves.down}`}</Badge>
              <Badge>{`${added} ${d.moves.new}`}</Badge>
              <span className="sr-only">{d.moves.summary(up, down, added)}</span>
            </p>
            <div className="sv-table-wrap" role="region" aria-labelledby={id} tabIndex={0}>
              <table className="sv-table min-w-[44rem]">
                <caption className="sr-only">{d.moves.week(isoWeek(monday), date(monday, lang))}</caption>
                <thead>
                  <tr>
                    <th scope="col">{d.bank}</th>
                    <th scope="col">{d.product}</th>
                    <th scope="col">{lang === "vi" ? "Thay đổi" : "Change"}</th>
                    <th scope="col">{lang === "vi" ? "Duyệt ngày" : "Approved"}</th>
                    <th scope="col">{d.source}</th>
                  </tr>
                </thead>
                <tbody>
                  {shownItems.map((c) => {
                    const isCard = c.table !== "savings_rate";
                    const target = isCard
                      ? null
                      : href(lang, `/lai-suat-tiet-kiem/${c.institution.short_name.toLowerCase()}`);
                    return (
                      <tr key={`${c.table}-${c.version_id}`}>
                        <th scope="row">
                          {target ? <Link href={target}>{c.institution.short_name}</Link> : c.institution.short_name}
                        </th>
                        <td>{localizeLabel(c.label, d.channels)}</td>
                        <td>
                          {c.kind === "new" ? (
                            <span className="text-muted">{d.moves.new}</span>
                          ) : (
                            <ul>
                              {c.changes.map((x) => {
                                const dir = direction(x.old, x.new);
                                return (
                                  <li
                                    key={x.field}
                                    className={`flex items-center gap-1 font-semibold ${dir > 0 ? "text-up" : dir < 0 ? "text-down" : ""}`}
                                  >
                                    {isCard ? `${d.cards.fields[x.field] ?? x.field}: ` : ""}
                                    {showValue(x.field, x.old, lang)} → {showValue(x.field, x.new, lang)}
                                    {dir ? <Icon name={dir > 0 ? "up" : "down"} size={14} /> : null}
                                    {dir > 0 ? <span className="sr-only">{d.moves.up}</span> : null}
                                    {dir < 0 ? <span className="sr-only">{d.moves.down}</span> : null}
                                  </li>
                                );
                              })}
                            </ul>
                          )}
                        </td>
                        <td className="whitespace-nowrap">{date(c.approved_at, lang)}</td>
                        <td>
                          <SourceStamp
                            lang={lang}
                            cell
                            checkedAt={date(c.provenance.checked_at, lang)}
                            sourceLabel={c.institution.short_name}
                            href={c.provenance.source_url}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {hidden > 0 ? (
              <p className="t-caption text-muted">
                {lang === "vi"
                  ? `Và ${hidden} thay đổi nhỏ hơn; xem từng ngân hàng để biết chi tiết.`
                  : `And ${hidden} smaller changes; see each bank's page for details.`}
              </p>
            ) : null}
          </section>
        );
      })}
      <Disclaimer lang={lang} />
    </div>
  );
}
