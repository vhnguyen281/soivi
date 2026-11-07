// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import type { ModelMix } from "../lib/buckets.ts";
import { annuity, economicBalanceSheet, goalPlan, realRate, retirementGoal, type Profile } from "../lib/balanceSheet.ts";

const rates = { govBond: 4, inflation: 4 }; // real rate 0: present values are plain sums
const base: Profile = {
  age: 40,
  retirementAge: 60,
  lifeExpectancy: 85,
  monthlyIncome: 40_000_000,
  annualBonus: 0,
  incomeGrowth: 0,
  job: "stable",
  monthlySpending: 20_000_000,
  retirementSpending: 15_000_000,
  monthlyPension: 5_000_000,
  monthlyDebtPayment: 0,
  assets: [
    { kind: "deposit", name: "", value: 300_000_000 },
    { kind: "home", name: "", value: 3_000_000_000 },
  ],
  debts: [{ name: "", balance: 500_000_000 }],
  goals: [{ name: "Học phí", amount: 600_000_000, years: 10, essential: true }],
};

test("annuity with no discount is the number of payments", () => {
  assert.equal(annuity(0, 20, 0), 20);
  assert.equal(annuity(20, 45, 0), 25);
  assert.ok(Math.abs(annuity(0, 1, 10) - 1 / 1.1) < 1e-12);
  assert.equal(realRate(rates), 0);
});

test("at a zero real rate every line is a plain sum", () => {
  const b = economicBalanceSheet({ ...base, job: "stable" }, { govBond: 4, inflation: 4 });
  assert.equal(b.financial, 3_300_000_000);
  assert.equal(b.liquid, 300_000_000);
  assert.equal(b.pension, 12 * 5_000_000 * 25);
  assert.equal(b.spendingToRetirement, 12 * 20_000_000 * 20);
  assert.equal(b.spendingInRetirement, 12 * 15_000_000 * 25);
  assert.equal(b.goals, 600_000_000);
  // Human capital is discounted at the job premium (1 pp for stable work), so it is below the plain sum.
  assert.ok(b.humanCapital < 12 * 40_000_000 * 20 && b.humanCapital > 0.8 * 12 * 40_000_000 * 20);
  assert.ok(Math.abs(b.netWorth - (b.totalAssets - b.totalLiabilities)) < 1e-6);
  assert.equal(b.ratios.liquidityMonths, 15);
});

test("more uncertain income is worth less today", () => {
  const stable = economicBalanceSheet(base, rates).humanCapital;
  const volatile = economicBalanceSheet({ ...base, job: "volatile" }, rates).humanCapital;
  assert.ok(volatile < stable);
});

test("a deficit comes with a monthly saving and the extra working years that close it", () => {
  const short = { ...base, monthlyIncome: 25_000_000 };
  const b = economicBalanceSheet(short, rates);
  assert.ok(b.netWorth < 0);
  assert.ok(Math.abs(b.fix.monthly - -b.netWorth / (12 * 20)) < 1);
  assert.ok(b.fix.extraYears !== null && b.fix.extraYears > 0);
  const later = economicBalanceSheet({ ...short, retirementAge: 60 + (b.fix.extraYears ?? 0) }, rates);
  assert.ok(later.netWorth >= 0);
  assert.equal(economicBalanceSheet(base, rates).fix.monthly, 0);
});

test("retirement becomes an essential goal sized by the spending above the pension", () => {
  const g = retirementGoal(base, rates, "Nghỉ hưu");
  assert.ok(g);
  assert.equal(g.amount, 12 * 10_000_000 * 25);
  assert.equal(g.years, 20);
  assert.equal(retirementGoal({ ...base, monthlyPension: 15_000_000 }, rates, "x"), null);
});

const mix = (level: number, ret: number, vol: number): ModelMix => ({
  id: `l${level}`,
  name: `Level ${level}`,
  expectedReturn: ret,
  volatility: vol,
  weights: [{ asset_class: "cash_vnd", percent: 100 }],
});
const mixes = [mix(1, 5, 2), mix(2, 6, 5), mix(3, 7, 8), mix(4, 8, 11), mix(5, 9, 13)];

test("the goal plan funds from liquid assets only and turns gaps into a monthly saving", () => {
  const plan = goalPlan(base, rates, mixes, 3, 6, "Nghỉ hưu");
  assert.equal(plan.allocation.liquidity, 120_000_000);
  const funded = plan.allocation.goals.reduce((s, g) => s + g.funded, 0);
  assert.ok(Math.abs(plan.allocation.liquidity + funded + plan.allocation.growth - 300_000_000) < 1);
  assert.ok(plan.allocation.goals.some((g) => g.goal.name === "Nghỉ hưu"));
  assert.ok(plan.monthly.length > 0 && plan.monthlyTotal > 0);
  assert.equal(plan.monthlySurplus, 20_000_000);
});
