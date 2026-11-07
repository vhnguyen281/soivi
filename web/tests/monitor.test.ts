// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { economicBalanceSheet, goalPlan, type Profile } from "../lib/balanceSheet.ts";
import type { ModelMix } from "../lib/buckets.ts";
import { addSnapshot, drift, monthsBetween, needsRebalance, parseHistory, snapshot, triggers, type Snapshot } from "../lib/monitor.ts";

const rates = { govBond: 4, inflation: 4 };
const profile: Profile = {
  age: 40,
  retirementAge: 60,
  lifeExpectancy: 85,
  monthlyIncome: 40_000_000,
  annualBonus: 0,
  incomeGrowth: 0,
  job: "average",
  monthlySpending: 20_000_000,
  retirementSpending: 15_000_000,
  monthlyPension: 5_000_000,
  monthlyDebtPayment: 0,
  assets: [
    { kind: "deposit", name: "", value: 800_000_000 },
    { kind: "stock", name: "", value: 200_000_000 },
  ],
  debts: [],
  goals: [{ name: "Xe", amount: 300_000_000, years: 2, essential: false }],
};
const mix: ModelMix = {
  id: "m",
  name: "Mix",
  expectedReturn: 7,
  volatility: 8,
  weights: [
    { asset_class: "cash_vnd", percent: 40 },
    { asset_class: "gov_bond", percent: 20 },
    { asset_class: "eq_large", percent: 30 },
    { asset_class: "eq_midsmall", percent: 10 },
  ],
};
const mixes = [mix, mix, mix, mix, mix];
const sheet = economicBalanceSheet(profile, rates);
const plan = goalPlan(profile, rates, mixes, 3, 6, "Nghỉ hưu");
const now = snapshot("2027-03-01", "2027.1", 3, profile, sheet, plan);

test("months between dates count whole months", () => {
  assert.equal(monthsBetween("2026-03-01", "2027-03-01"), 12);
  assert.equal(monthsBetween("2026-03-15", "2027-03-01"), 11);
});

test("drift compares liquid holdings with the plan's mix, folded into groups", () => {
  const d = drift(profile, plan);
  const total = d.reduce((s, x) => s + x.actual, 0);
  assert.ok(Math.abs(total - 100) < 1e-9);
  const targets = d.reduce((s, x) => s + x.target, 0);
  assert.ok(Math.abs(targets - 100) < 1e-6);
  assert.ok(Math.abs(d.reduce((s, x) => s + x.trade, 0)) < 1); // buys and sells net to zero
  assert.equal(d.find((x) => x.group === "deposit")?.actual, 80);
  assert.ok(needsRebalance(d));
});

test("the first review, then annual, assumption and income triggers", () => {
  const first = triggers([], now, "2027-03-01", profile, sheet, null).map((t) => t.kind);
  assert.ok(first.includes("first"));
  assert.ok(first.includes("soon")); // the car is 2 years away
  const old: Snapshot = { ...now, date: "2026-01-10", release: "2026.1", income: 30_000_000 };
  const kinds = triggers([old], now, "2027-03-01", profile, sheet, drift(profile, plan)).map((t) => t.kind);
  for (const k of ["annual", "assumptions", "income", "drift"]) assert.ok(kinds.includes(k as never), k);
  assert.ok(!kinds.includes("first"));
});

test("history keeps one snapshot a day and survives a round trip through JSON", () => {
  const h = addSnapshot(addSnapshot([], { ...now, netWorth: 1 }), now);
  assert.equal(h.length, 1);
  assert.equal(h[0].netWorth, now.netWorth);
  const h2 = addSnapshot(h, { ...now, date: "2026-01-01" });
  assert.deepEqual(h2.map((s) => s.date), ["2026-01-01", "2027-03-01"]);
  assert.deepEqual(parseHistory(JSON.parse(JSON.stringify(h2))), h2);
  assert.deepEqual(parseHistory([{ date: "x" }, null, 5]), []);
});
