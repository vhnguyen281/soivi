// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { nominalGoal, outcome, plan, quantile, rng, scenarioShift, simulatePaths, type GoalInput } from "../lib/goals.ts";

const base: GoalInput = {
  goal: 1_000_000_000,
  years: 10,
  savings: 200_000_000,
  monthly: 5_000_000,
  contributionGrowth: 0,
  inTodaysMoney: false,
  inflation: 4,
};

test("seeded generator is repeatable and uniform-ish", () => {
  const a = rng(1);
  const b = rng(1);
  const xs = Array.from({ length: 10000 }, () => a());
  assert.deepEqual(xs.slice(0, 5), Array.from({ length: 5 }, () => b()));
  const mean = xs.reduce((s, x) => s + x, 0) / xs.length;
  assert.ok(Math.abs(mean - 0.5) < 0.01);
});

test("zero volatility gives the textbook future value", () => {
  const sims = simulatePaths(6, 0, 10, 0, 1, 10);
  const monthly = Math.pow(1.06, 1 / 12);
  assert.ok(Math.abs(sims.growth[0] - Math.pow(1.06, 10)) < 1e-9);
  const annuity = (Math.pow(monthly, 120) - 1) / (monthly - 1); // end-of-month payments
  assert.ok(Math.abs(sims.annuity[0] - annuity) < 1e-6);
  const r = outcome({ ...base, goal: 200_000_000 * Math.pow(1.06, 10) + 5_000_000 * annuity - 1 }, sims);
  assert.equal(r.probability, 1);
});

test("the monthly amount for 80% gives about an 80% chance", () => {
  const sims = simulatePaths(8, 12, 10, 0, 7, 4000);
  const first = outcome(base, sims);
  const second = outcome({ ...base, monthly: first.monthlyFor80 }, sims);
  assert.ok(Math.abs(second.probability - 0.8) < 0.01, String(second.probability));
});

test("goal in today's money is inflated; more risk widens the spread", () => {
  assert.ok(Math.abs(nominalGoal({ ...base, inTodaysMoney: true }) - 1e9 * Math.pow(1.04, 10)) < 1);
  const calm = outcome(base, simulatePaths(8, 3, 10, 0, 3));
  const wild = outcome(base, simulatePaths(8, 20, 10, 0, 3));
  assert.ok(calm.median - calm.p10 < wild.median - wild.p10);
});

test("scenarios move the chance the right way, and plans are repeatable", () => {
  const portfolios = [
    { id: "g", name: "Growth", expectedReturn: 9, volatility: 12, scenarioShift: { adverse: -1.2, favourable: 1.2 } },
  ];
  const [r] = plan(base, portfolios);
  assert.ok(r.adverse.probability < r.base.probability && r.base.probability < r.favourable.probability);
  assert.deepEqual(plan(base, portfolios), plan(base, portfolios));
  const shift = scenarioShift(
    [
      { asset_class: "a", percent: 50 },
      { asset_class: "b", percent: 50 },
    ],
    [
      { id: "a", expected_return: "10", scenarios: { adverse: "8", favourable: "12" } },
      { id: "b", expected_return: "5", scenarios: { adverse: "5", favourable: "5" } },
    ],
  );
  assert.deepEqual(shift, { adverse: -1, favourable: 1 });
  assert.equal(quantile([1, 2, 3, 4, 5], 0.5), 3);
});
