// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { allocate, amountNeeded, goalLevel, type BucketInput, type ModelMix } from "../lib/buckets.ts";

const classes = ["cash_vnd", "gov_bond", "eq_large"];
const mix = (level: number, cash: number, ret: number, vol: number): ModelMix => ({
  id: `l${level}`,
  name: `Level ${level}`,
  expectedReturn: ret,
  volatility: vol,
  weights: [
    { asset_class: classes[0], percent: cash },
    { asset_class: classes[1], percent: 10 },
    { asset_class: classes[2], percent: 90 - cash },
  ],
});
const mixes = [mix(1, 80, 5, 2), mix(2, 60, 6, 5), mix(3, 40, 7, 8), mix(4, 20, 8, 11), mix(5, 10, 9, 13)];

const input: BucketInput = {
  total: 2_000_000_000,
  monthlySpending: 20_000_000,
  liquidityMonths: 12,
  goals: [
    { name: "Học phí", amount: 500_000_000, years: 5, essential: true },
    { name: "Du lịch", amount: 200_000_000, years: 2, essential: false },
  ],
  riskLevel: 4,
  inflation: 4,
};

test("goal level follows horizon and priority, capped by the risk level", () => {
  assert.equal(goalLevel({ name: "", amount: 1, years: 2, essential: false }, 5), 1);
  assert.equal(goalLevel({ name: "", amount: 1, years: 5, essential: true }, 5), 2);
  assert.equal(goalLevel({ name: "", amount: 1, years: 10, essential: false }, 5), 5);
  assert.equal(goalLevel({ name: "", amount: 1, years: 10, essential: false }, 2), 2);
});

test("with no volatility the amount needed is the discounted goal", () => {
  const flat = { ...mixes[0], expectedReturn: 5, volatility: 0 };
  const need = amountNeeded({ name: "", amount: 100, years: 10, essential: true }, flat, 0.9, 0, 1);
  assert.ok(Math.abs(need - 100 / Math.pow(1.05, 10)) < 1e-6);
});

test("higher confidence needs more money", () => {
  const goal = { name: "", amount: 1e9, years: 8, essential: true };
  assert.ok(amountNeeded(goal, mixes[3], 0.9, 4, 1) > amountNeeded(goal, mixes[3], 0.6, 4, 1));
});

test("the parts add up to the total, liquidity first, essential goals before aspirational", () => {
  const a = allocate(input, mixes);
  assert.equal(a.liquidity, 240_000_000);
  assert.equal(a.goals[0].goal.name, "Học phí"); // essential first, even though it is later
  const sum = a.liquidity + a.goals.reduce((s, g) => s + g.funded, 0) + a.growth;
  assert.ok(Math.abs(sum - input.total) < 1);
  const pct = a.mix.reduce((s, m) => s + m.percent, 0);
  assert.ok(Math.abs(pct - 100) < 1e-9);
  assert.deepEqual(a.mix.map((m) => m.asset_class), classes);
});

test("when money runs short, aspirational goals give way first", () => {
  const a = allocate({ ...input, total: 500_000_000 }, mixes);
  const [essential, wish] = a.goals;
  assert.ok(essential.funded > 0);
  assert.ok(wish.funded < wish.needed);
  assert.equal(a.growth, 0);
  const tiny = allocate({ ...input, total: 100_000_000 }, mixes);
  assert.equal(tiny.liquidity, 100_000_000);
  assert.equal(tiny.liquidityShort, 140_000_000);
});
