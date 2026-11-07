// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { doublingYears, earlyWithdrawal, fanPaths, fanSummary, monthlyFor, payoff, realValue } from "../lib/lessons.ts";

test("real value: no growth and no inflation keeps 100; inflation alone shrinks it", () => {
  assert.equal(realValue(10, 0, 0), 100);
  assert.ok(Math.abs(realValue(1, 0, 4) - 100 / 1.04) < 1e-9);
  assert.ok(Math.abs(realValue(5, 4, 4) - 100) < 1e-9);
  assert.ok(Math.abs(doublingYears(3.9) - 18.12) < 0.05);
});

test("early withdrawal earns the demand rate for the months held", () => {
  const r = earlyWithdrawal(100_000_000, 6, 12, 0.1, 6);
  assert.equal(r.atMaturity, 6_000_000);
  assert.ok(Math.abs(r.early - 50_000) < 1e-6);
  assert.ok(Math.abs(r.lost - (3_000_000 - 50_000)) < 1e-6);
  assert.equal(earlyWithdrawal(1, 6, 12, 0.1, 99).lost, earlyWithdrawal(1, 6, 12, 0.1, 12).lost);
});

test("card payoff: the minimum takes far longer and costs more than a fixed payment", () => {
  const min = payoff(20_000_000, 24, 5, 100_000);
  const fixed = payoff(20_000_000, 24, 5, 100_000, 2_000_000);
  assert.ok(!min.never && !fixed.never);
  assert.ok(min.months > fixed.months);
  assert.ok(min.interest > fixed.interest);
  assert.ok(Math.abs(fixed.paid - fixed.interest - 20_000_000) < 1);
  assert.ok(payoff(20_000_000, 24, 1, 0).never); // 1% a month never beats 2% interest
  assert.equal(payoff(0, 24, 5, 100_000).months, 0);
});

test("fan paths are seeded and summarised by percentiles", () => {
  const a = fanPaths(8, 12, 10, 50, 3);
  assert.deepEqual(a, fanPaths(8, 12, 10, 50, 3));
  assert.equal(a.length, 50);
  assert.equal(a[0].length, 11);
  const s = fanSummary(a);
  assert.ok(s.low < s.high && s.loss >= 0 && s.loss <= 1);
  const flat = fanSummary(fanPaths(0, 0, 5, 10, 1));
  assert.ok(Math.abs(flat.low - 100) < 1e-9 && flat.loss === 0);
});

test("monthly saving with no return is the goal spread evenly", () => {
  assert.ok(Math.abs(monthlyFor(1200, 1, 0) - 100) < 1e-9);
  assert.ok(monthlyFor(1e9, 8, 7) < monthlyFor(1e9, 8, 5));
});
