/**
 * Monitoring and rebalancing (CFA private wealth, step 8). Runs in the browser; the history lives only in the
 * visitor's browser storage or data file.
 *
 * Each review is a snapshot of the balance sheet and the goal plan. Comparing snapshots shows progress; comparing
 * the liquid assets with the plan's target mix shows drift. Review triggers follow the curriculum: a scheduled
 * annual review, a change in circumstances, a change in capital market expectations, and drift past a corridor.
 */

import type { BalanceSheet, GoalPlan, Profile } from "./balanceSheet.ts";

/** Asset groups the visitor can hold directly; the model classes fold into them. */
export const GROUPS = ["deposit", "bond", "stock", "gold", "usd"] as const;
export type Group = (typeof GROUPS)[number];
const CLASS_GROUP: Record<string, Group> = {
  cash_vnd: "deposit",
  gov_bond: "bond",
  corp_bond: "bond",
  eq_large: "stock",
  eq_midsmall: "stock",
  gold: "gold",
  usd: "usd",
};

/** Rebalance when a group is this many percentage points away from its target. */
export const CORRIDOR = 5;
export const REVIEW_MONTHS = 12;

export type Snapshot = {
  date: string; // YYYY-MM-DD
  release: string; // VNCMA version used
  level: number;
  income: number; // VND a month, bonus included
  netWorth: number; // economic
  financialNet: number; // financial assets - debts
  liquid: number;
  goalsNeeded: number; // VND today, all goals incl. retirement
  goalsFunded: number;
  monthlyNeeded: number;
  monthlySurplus: number;
};

export function snapshot(
  date: string,
  release: string,
  level: number,
  profile: Profile,
  sheet: BalanceSheet,
  plan: GoalPlan | null,
): Snapshot {
  const goals = plan?.allocation.goals ?? [];
  return {
    date,
    release,
    level,
    income: profile.monthlyIncome + profile.annualBonus / 12,
    netWorth: sheet.netWorth,
    financialNet: sheet.financial - sheet.debts,
    liquid: sheet.liquid,
    goalsNeeded: goals.reduce((s, g) => s + g.needed, 0),
    goalsFunded: goals.reduce((s, g) => s + g.funded, 0),
    monthlyNeeded: plan?.monthlyTotal ?? 0,
    monthlySurplus: plan?.monthlySurplus ?? 0,
  };
}

export type Drift = { group: Group; amount: number; actual: number; target: number; trade: number };

/** Liquid holdings vs the plan's mix (percent of liquid assets). `trade` > 0 means buy, < 0 sell. */
export function drift(profile: Profile, plan: GoalPlan): Drift[] {
  const held = new Map<Group, number>(GROUPS.map((g) => [g, 0]));
  for (const a of profile.assets) {
    if ((GROUPS as readonly string[]).includes(a.kind)) held.set(a.kind as Group, (held.get(a.kind as Group) ?? 0) + a.value);
  }
  const target = new Map<Group, number>(GROUPS.map((g) => [g, 0]));
  for (const m of plan.allocation.mix) {
    const g = CLASS_GROUP[m.asset_class];
    if (g) target.set(g, (target.get(g) ?? 0) + m.percent);
  }
  const total = [...held.values()].reduce((s, v) => s + v, 0);
  return GROUPS.map((group) => {
    const amount = held.get(group) ?? 0;
    const actual = total > 0 ? (100 * amount) / total : 0;
    const t = target.get(group) ?? 0;
    return { group, amount, actual, target: t, trade: (total * t) / 100 - amount };
  });
}

export const needsRebalance = (d: Drift[]) => d.some((x) => Math.abs(x.actual - x.target) > CORRIDOR);

export type Trigger =
  | { kind: "first" }
  | { kind: "annual"; months: number }
  | { kind: "assumptions"; from: string; to: string }
  | { kind: "income"; change: number } // fraction
  | { kind: "drift" }
  | { kind: "funding"; from: number; to: number } // share of goals funded, 0..1
  | { kind: "soon"; name: string; years: number }
  | { kind: "reserve"; months: number };

export function monthsBetween(from: string, to: string): number {
  const [y1, m1, d1] = from.split("-").map(Number);
  const [y2, m2, d2] = to.split("-").map(Number);
  return (y2 - y1) * 12 + (m2 - m1) - (d2 < d1 ? 1 : 0);
}

const funded = (s: Snapshot) => (s.goalsNeeded > 0 ? s.goalsFunded / s.goalsNeeded : 1);

/** Reasons to review the plan now, given the history and today's figures. */
export function triggers(
  history: Snapshot[],
  current: Snapshot,
  today: string,
  profile: Profile,
  sheet: BalanceSheet,
  driftNow: Drift[] | null,
): Trigger[] {
  const out: Trigger[] = [];
  const last = history.at(-1);
  if (!last) out.push({ kind: "first" });
  else {
    const months = monthsBetween(last.date, today);
    if (months >= REVIEW_MONTHS) out.push({ kind: "annual", months });
    if (last.release !== current.release) out.push({ kind: "assumptions", from: last.release, to: current.release });
    if (last.income > 0 && Math.abs(current.income / last.income - 1) >= 0.2)
      out.push({ kind: "income", change: current.income / last.income - 1 });
    if (funded(current) < funded(last) - 0.1) out.push({ kind: "funding", from: funded(last), to: funded(current) });
  }
  if (driftNow && needsRebalance(driftNow)) out.push({ kind: "drift" });
  for (const g of profile.goals) if (g.years <= 2) out.push({ kind: "soon", name: g.name, years: g.years });
  if (sheet.ratios.liquidityMonths < 6) out.push({ kind: "reserve", months: sheet.ratios.liquidityMonths });
  return out;
}

/** Keeps at most one snapshot per day (the latest) and the newest `max`, oldest first. */
export function addSnapshot(history: Snapshot[], s: Snapshot, max = 40): Snapshot[] {
  return [...history.filter((h) => h.date !== s.date), s].sort((a, b) => a.date.localeCompare(b.date)).slice(-max);
}

/** Validates a stored history (from localStorage or a file). */
export function parseHistory(raw: unknown): Snapshot[] {
  if (!Array.isArray(raw)) return [];
  const n = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const out: Snapshot[] = [];
  for (const r of raw.slice(-40)) {
    if (!r || typeof r !== "object") continue;
    const o = r as Record<string, unknown>;
    if (typeof o.date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(o.date)) continue;
    const nums = ["level", "income", "netWorth", "financialNet", "liquid", "goalsNeeded", "goalsFunded", "monthlyNeeded", "monthlySurplus"] as const;
    if (nums.some((k) => n(o[k]) === null)) continue;
    out.push({
      date: o.date,
      release: typeof o.release === "string" ? o.release.slice(0, 20) : "",
      level: o.level as number,
      income: o.income as number,
      netWorth: o.netWorth as number,
      financialNet: o.financialNet as number,
      liquid: o.liquid as number,
      goalsNeeded: o.goalsNeeded as number,
      goalsFunded: o.goalsFunded as number,
      monthlyNeeded: o.monthlyNeeded as number,
      monthlySurplus: o.monthlySurplus as number,
    });
  }
  return out.sort((a, b) => a.date.localeCompare(b.date));
}
