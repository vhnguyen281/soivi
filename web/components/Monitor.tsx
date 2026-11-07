"use client";

import type { BalanceSheet, GoalPlan, Profile } from "@/lib/balanceSheet";
import { vnd, vndShort, type Lang } from "@/lib/format";
import {
  addSnapshot,
  CORRIDOR,
  drift,
  REVIEW_MONTHS,
  snapshot,
  triggers,
  type Group,
  type Snapshot,
  type Trigger,
} from "@/lib/monitor";

const TEXT = {
  vi: {
    title: "Theo dõi và điều chỉnh",
    intro: `Lưu kết quả mỗi lần xem lại (nên ít nhất ${REVIEW_MONTHS} tháng một lần, hoặc khi hoàn cảnh thay đổi) để thấy tiến độ qua thời gian.`,
    save: "Lưu kết quả kỳ này vào lịch sử",
    saved: "Đã lưu kết quả hôm nay.",
    notKept:
      "Lịch sử chỉ còn khi bạn bật “Lưu trên trình duyệt này” ở trên, hoặc tải file dữ liệu về sau khi lưu.",
    review: "Nên xem lại kế hoạch vì",
    calm: "Chưa có lý do cần điều chỉnh. Hẹn xem lại sau tối đa 12 tháng.",
    trig: (t: Trigger, lang: Lang): string => {
      switch (t.kind) {
        case "first":
          return "Đây là lần đầu. Hãy lưu kết quả để có mốc so sánh cho lần sau.";
        case "annual":
          return `Đã ${t.months} tháng từ lần xem lại trước: đến hạn xem lại định kỳ.`;
        case "assumptions":
          return `Giả định thị trường đã cập nhật (VNCMA ${t.from} → ${t.to}): lợi nhuận kỳ vọng và danh mục mẫu có thể đã đổi.`;
        case "income":
          return `Thu nhập ${t.change > 0 ? "tăng" : "giảm"} ${Math.round(Math.abs(t.change) * 100)}% so với lần trước: hãy xem lại mức để dành và mức rủi ro.`;
        case "funding":
          return `Tỷ lệ mục tiêu đã có tiền giảm từ ${Math.round(t.from * 100)}% xuống ${Math.round(t.to * 100)}%.`;
        case "drift":
          return `Tỷ trọng tài sản lệch quá ${CORRIDOR} điểm % so với kế hoạch: cân nhắc tái cân bằng (bảng bên dưới).`;
        case "soon":
          return `“${t.name}” chỉ còn ${t.years} năm: nên chuyển dần số tiền dành cho mục tiêu này sang tiền gửi.`;
        case "reserve":
          return `Quỹ dự phòng chỉ đủ ${Number.isFinite(t.months) ? t.months.toLocaleString(lang === "vi" ? "vi-VN" : "en-US", { maximumFractionDigits: 1 }) : "0"} tháng chi tiêu: nên bổ sung trước khi đầu tư thêm.`;
      }
    },
    since: (d: string) => `So với lần xem lại ngày ${d}`,
    metric: "Chỉ số",
    before: "Lần trước",
    now: "Hôm nay",
    change: "Thay đổi",
    rows: {
      financialNet: "Tài sản tài chính trừ nợ",
      netWorth: "Giá trị ròng kinh tế",
      funded: "Mục tiêu đã có tiền",
      monthlySurplus: "Để dành mỗi tháng",
      monthlyNeeded: "Mục tiêu cần góp mỗi tháng",
    },
    chart: "Tài sản tài chính trừ nợ qua các lần xem lại",
    history: "Lịch sử",
    date: "Ngày",
    release: "VNCMA",
    remove: "Xoá",
    rebalance: "Tái cân bằng tài sản dễ bán",
    rebalanceHint: `So tỷ trọng hiện nay với kế hoạch (gồm quỹ thanh khoản, các mục tiêu và phần tăng trưởng). Chỉ điều chỉnh nhóm lệch quá ${CORRIDOR} điểm %. Nên dùng tiền để dành mới để mua phần thiếu trước, rồi mới bán, để giảm phí và thuế.`,
    groups: { deposit: "Tiền gửi", bond: "Trái phiếu", stock: "Cổ phiếu", gold: "Vàng", usd: "Ngoại tệ" } satisfies Record<Group, string>,
    group: "Nhóm",
    actual: "Hiện nay",
    target: "Kế hoạch",
    action: "Gợi ý",
    buy: (v: string) => `Mua thêm ${v}`,
    sell: (v: string) => `Giảm ${v}`,
    inside: "Trong biên",
    noPlan: "Cần danh mục mẫu đã duyệt để tính tái cân bằng.",
  },
  en: {
    title: "Monitor and adjust",
    intro: `Save the result at every review (at least every ${REVIEW_MONTHS} months, or when your situation changes) to see progress over time.`,
    save: "Save this review to the history",
    saved: "Today's result is saved.",
    notKept: "The history is kept only if you tick “Keep it in this browser” above, or download the data file after saving.",
    review: "Review your plan because",
    calm: "No reason to change anything now. Review again within 12 months.",
    trig: (t: Trigger, lang: Lang): string => {
      switch (t.kind) {
        case "first":
          return "This is your first review. Save it so the next one has something to compare with.";
        case "annual":
          return `${t.months} months since your last review: the scheduled review is due.`;
        case "assumptions":
          return `Market assumptions were updated (VNCMA ${t.from} → ${t.to}): expected returns and model portfolios may have changed.`;
        case "income":
          return `Income is ${t.change > 0 ? "up" : "down"} ${Math.round(Math.abs(t.change) * 100)}% since last time: review your saving and risk level.`;
        case "funding":
          return `The share of your goals that is funded fell from ${Math.round(t.from * 100)}% to ${Math.round(t.to * 100)}%.`;
        case "drift":
          return `Your mix is more than ${CORRIDOR} points away from the plan: consider rebalancing (table below).`;
        case "soon":
          return `“${t.name}” is only ${t.years} years away: move the money for it into deposits step by step.`;
        case "reserve":
          return `The emergency fund covers only ${Number.isFinite(t.months) ? t.months.toLocaleString(lang === "vi" ? "vi-VN" : "en-US", { maximumFractionDigits: 1 }) : "0"} months of spending: top it up before investing more.`;
      }
    },
    since: (d: string) => `Compared with your review on ${d}`,
    metric: "Measure",
    before: "Last time",
    now: "Today",
    change: "Change",
    rows: {
      financialNet: "Financial assets less debts",
      netWorth: "Economic net worth",
      funded: "Goals funded",
      monthlySurplus: "Saved each month",
      monthlyNeeded: "Goals need each month",
    },
    chart: "Financial assets less debts at each review",
    history: "History",
    date: "Date",
    release: "VNCMA",
    remove: "Delete",
    rebalance: "Rebalance your liquid assets",
    rebalanceHint: `Today's mix against the plan (liquidity reserve, goals and growth together). Adjust only groups more than ${CORRIDOR} points away. Use new savings to buy what is short before selling anything, to save fees and tax.`,
    groups: { deposit: "Deposits", bond: "Bonds", stock: "Shares", gold: "Gold", usd: "Foreign currency" } satisfies Record<Group, string>,
    group: "Group",
    actual: "Today",
    target: "Plan",
    action: "Suggestion",
    buy: (v: string) => `Add ${v}`,
    sell: (v: string) => `Reduce ${v}`,
    inside: "Within range",
    noPlan: "Rebalancing needs approved model portfolios.",
  },
};

const todayIso = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Ho_Chi_Minh" });
const showDate = (iso: string) => iso.split("-").reverse().join("/");
const share = (s: Snapshot) => (s.goalsNeeded > 0 ? s.goalsFunded / s.goalsNeeded : 1);

export function Monitor({
  lang,
  release,
  profile,
  sheet,
  plan,
  level,
  history,
  kept,
  onChange,
}: {
  lang: Lang;
  release: string;
  profile: Profile;
  sheet: BalanceSheet;
  plan: GoalPlan | null;
  level: number;
  history: Snapshot[];
  kept: boolean;
  onChange: (history: Snapshot[]) => void;
}) {
  const x = TEXT[lang];
  const today = todayIso();
  const current = snapshot(today, release, level, profile, sheet, plan);
  const earlier = history.filter((h) => h.date < today);
  const last = earlier.at(-1);
  const d = plan ? drift(profile, plan) : null;
  const reasons = triggers(earlier, current, today, profile, sheet, d);
  const savedToday = history.some((h) => h.date === today);
  const money = (v: number) => vnd(Math.round(v), lang);
  const pctText = (v: number) => `${Math.round(v * 100)}%`;
  const delta = (a: number, b: number, asPct = false) => {
    const v = b - a;
    const text = asPct ? `${Math.round(v * 100)} ${lang === "vi" ? "điểm %" : "pts"}` : money(v);
    return v > 0 ? `+${text}` : text;
  };

  return (
    <section aria-labelledby="mon-title" className="space-y-6">
      <div className="space-y-2">
        <h2 id="mon-title" className="t-h2">
          {x.title}
        </h2>
        <p className="t-small text-muted">{x.intro}</p>
      </div>

      <div className="sv-panel space-y-2">
        <h3 className="t-h3">{reasons.length ? x.review : x.calm}</h3>
        {reasons.length ? (
          <ul className="list-disc space-y-1 pl-5">
            {reasons.map((t, i) => (
              <li key={i}>{x.trig(t, lang)}</li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="no-print space-y-2">
        <button type="button" className="sv-btn sv-btn--primary" onClick={() => onChange(addSnapshot(history, current))}>
          {x.save}
        </button>
        {savedToday ? <p className="t-small">{x.saved}</p> : null}
        {!kept ? <p className="t-small text-muted">{x.notKept}</p> : null}
      </div>

      {last ? (
        <div className="space-y-2">
          <h3 className="t-h3">{x.since(showDate(last.date))}</h3>
          <div className="sv-table-wrap" role="region" aria-label={x.since(showDate(last.date))} tabIndex={0}>
            <table className="sv-table">
              <thead>
                <tr>
                  <th scope="col">{x.metric}</th>
                  <th scope="col" className="text-right">{x.before}</th>
                  <th scope="col" className="text-right">{x.now}</th>
                  <th scope="col" className="text-right">{x.change}</th>
                </tr>
              </thead>
              <tbody>
                {(["financialNet", "netWorth", "monthlySurplus", "monthlyNeeded"] as const).map((k) => (
                  <tr key={k}>
                    <th scope="row">{x.rows[k]}</th>
                    <td className="text-right tabular-nums">{money(last[k])}</td>
                    <td className="text-right tabular-nums">{money(current[k])}</td>
                    <td className="text-right tabular-nums">{delta(last[k], current[k])}</td>
                  </tr>
                ))}
                <tr>
                  <th scope="row">{x.rows.funded}</th>
                  <td className="text-right tabular-nums">{pctText(share(last))}</td>
                  <td className="text-right tabular-nums">{pctText(share(current))}</td>
                  <td className="text-right tabular-nums">{delta(share(last), share(current), true)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {history.length >= 2 ? <Trend lang={lang} history={history} title={x.chart} /> : null}

      {history.length ? (
        <div className="space-y-2">
          <h3 className="t-h3">{x.history}</h3>
          <div className="sv-table-wrap" role="region" aria-label={x.history} tabIndex={0}>
            <table className="sv-table min-w-[44rem]">
              <thead>
                <tr>
                  <th scope="col">{x.date}</th>
                  <th scope="col">{x.release}</th>
                  <th scope="col" className="text-right">{x.rows.financialNet}</th>
                  <th scope="col" className="text-right">{x.rows.netWorth}</th>
                  <th scope="col" className="text-right">{x.rows.funded}</th>
                  <th scope="col" className="no-print">
                    <span className="sr-only">{x.remove}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {[...history].reverse().map((h) => (
                  <tr key={h.date}>
                    <th scope="row" className="tabular-nums">{showDate(h.date)}</th>
                    <td>{h.release}</td>
                    <td className="text-right tabular-nums">{money(h.financialNet)}</td>
                    <td className="text-right tabular-nums">{money(h.netWorth)}</td>
                    <td className="text-right tabular-nums">{pctText(share(h))}</td>
                    <td className="no-print">
                      <button
                        type="button"
                        className="sv-btn sv-btn--secondary"
                        onClick={() => onChange(history.filter((y) => y.date !== h.date))}
                      >
                        {x.remove}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <div className="space-y-2">
        <h3 className="t-h3">{x.rebalance}</h3>
        {d ? (
          <>
            <p className="t-small text-muted">{x.rebalanceHint}</p>
            <div className="sv-table-wrap" role="region" aria-label={x.rebalance} tabIndex={0}>
              <table className="sv-table">
                <thead>
                  <tr>
                    <th scope="col">{x.group}</th>
                    <th scope="col" className="text-right">{x.actual}</th>
                    <th scope="col" className="text-right">{x.target}</th>
                    <th scope="col">{x.action}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.map((r) => (
                    <tr key={r.group}>
                      <th scope="row">{x.groups[r.group]}</th>
                      <td className="text-right tabular-nums">
                        {Math.round(r.actual)}% <span className="t-small text-muted">({money(r.amount)})</span>
                      </td>
                      <td className="text-right tabular-nums">{Math.round(r.target)}%</td>
                      <td>
                        {Math.abs(r.actual - r.target) <= CORRIDOR
                          ? x.inside
                          : r.trade > 0
                            ? x.buy(money(r.trade))
                            : x.sell(money(-r.trade))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="sv-note">{x.noPlan}</p>
        )}
      </div>
    </section>
  );
}

/** One series over time: financial assets less debts at each saved review. */
function Trend({ lang, history, title }: { lang: Lang; history: Snapshot[]; title: string }) {
  const W = 640;
  const H = 220;
  const pad = { l: 72, r: 16, t: 16, b: 32 };
  const values = history.map((h) => h.financialNet);
  let lo = Math.min(0, ...values);
  let hi = Math.max(...values);
  if (hi === lo) hi = lo + 1;
  const span = hi - lo;
  lo -= span * 0.05;
  hi += span * 0.05;
  const t0 = Date.parse(history[0].date);
  const t1 = Date.parse(history[history.length - 1].date);
  const px = (iso: string) => pad.l + ((Date.parse(iso) - t0) / Math.max(1, t1 - t0)) * (W - pad.l - pad.r);
  const py = (v: number) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const ticks = [lo + (hi - lo) * 0.05, (lo + hi) / 2, hi - (hi - lo) * 0.05];
  const path = history.map((h, i) => `${i ? "L" : "M"}${px(h.date).toFixed(1)},${py(h.financialNet).toFixed(1)}`).join(" ");
  return (
    <figure className="space-y-2">
      <figcaption className="t-h3">{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${title}: ${history.map((h) => `${showDate(h.date)} ${vndShort(h.financialNet, lang)}`).join(", ")}`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={W - pad.r} y1={py(v)} y2={py(v)} stroke="var(--line)" strokeWidth="1" />
            <text x={pad.l - 8} y={py(v) + 4} textAnchor="end" fontSize="12" fill="var(--ink-muted)">
              {vndShort(Math.round(v), lang)}
            </text>
          </g>
        ))}
        <text x={pad.l} y={H - 8} fontSize="12" fill="var(--ink-muted)">
          {showDate(history[0].date)}
        </text>
        <text x={W - pad.r} y={H - 8} textAnchor="end" fontSize="12" fill="var(--ink-muted)">
          {showDate(history[history.length - 1].date)}
        </text>
        <path d={path} fill="none" stroke="var(--jade)" strokeWidth="2" strokeLinejoin="round" />
        {history.map((h) => (
          <g key={h.date}>
            <circle cx={px(h.date)} cy={py(h.financialNet)} r="12" fill="transparent">
              <title>{`${showDate(h.date)}: ${vnd(Math.round(h.financialNet), lang)}`}</title>
            </circle>
            <circle cx={px(h.date)} cy={py(h.financialNet)} r="4" fill="var(--jade)" stroke="var(--surface)" strokeWidth="2" pointerEvents="none" />
          </g>
        ))}
      </svg>
    </figure>
  );
}
