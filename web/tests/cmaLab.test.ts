// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bands,
  chance,
  cholesky,
  hundred,
  labBase,
  NO_SHOCK,
  scenarioCorr,
  scenarioReturns,
  scenarioVols,
  simulate,
  type LabBase,
} from "../lib/cmaLab.ts";

const IDS = ["cash_vnd", "gov_bond", "corp_bond", "eq_large", "eq_midsmall", "gold", "usd"];
const release = {
  horizon_years: 10,
  classes: [
    { id: "cash_vnd", expected_return: "5.23", volatility: "0.54", formula: "pi 3.90 + r_star 1.34 = 5.23" },
    { id: "gov_bond", expected_return: "4.35", volatility: "7.31", formula: "y0 4.49 + D 7.92 x (y0 - y_eq 4.68) / 10 = 4.35" },
    { id: "corp_bond", expected_return: "5.35", volatility: "3.00", formula: "E_gov 4.35 + spread 2.00 - loss 1.00 = 5.35" },
    { id: "eq_large", expected_return: "10.12", volatility: "20.61", formula: "VN30: D/P 2.34 + pi 3.90 + g 6.08 x 0.6 - dS 1.00 + ln(...)" },
    { id: "eq_midsmall", expected_return: "10.80", volatility: "22.69", formula: "..." },
    { id: "gold", expected_return: "4.40", volatility: "18.97", formula: "pi_us 2.30 + theta 0.50 + d 1.60 = 4.40" },
    { id: "usd", expected_return: "1.60", volatility: "2.00", formula: "i_usd 0.00 + d 1.60 = 1.60" },
    { id: "real_estate", expected_return: "7.42", volatility: null, formula: "" },
  ],
  correlation: {
    classes: IDS,
    matrix: IDS.map((a, i) => IDS.map((b, j) => (i === j ? 1 : (a.startsWith("eq") && b.startsWith("eq")) ? 0.8 : 0.1))),
  },
  macro: { pi: { value: "3.90" } },
};
const base = labBase(release) as LabBase;

test("the release is parsed, including duration and the growth haircut", () => {
  assert.ok(base);
  assert.equal(base.duration, 7.92);
  assert.equal(base.haircut, 0.6);
  assert.deepEqual(base.classes.map((c) => c.id), IDS);
  assert.deepEqual(scenarioReturns(base, NO_SHOCK), base.classes.map((c) => c.ret));
});

test("each driver moves the classes as the VNCMA blocks say", () => {
  const r0 = scenarioReturns(base, NO_SHOCK);
  const infl = scenarioReturns(base, { ...NO_SHOCK, inflation: 1 }).map((v, i) => v - r0[i]);
  assert.ok(Math.abs(infl[0] - 1) < 1e-9); // cash
  assert.ok(Math.abs(infl[1] + 0.792) < 1e-9); // gov: -D x 1 / 10
  assert.ok(Math.abs(infl[2] - infl[1]) < 1e-9); // corp follows gov
  assert.ok(Math.abs(infl[3] - 1) < 1e-9 && Math.abs(infl[5] - 1) < 1e-9 && Math.abs(infl[6] - 1) < 1e-9);
  const g = scenarioReturns(base, { ...NO_SHOCK, growth: 1 }).map((v, i) => v - r0[i]);
  assert.ok(Math.abs(g[3] - 0.6) < 1e-9 && g[0] === 0 && g[1] === 0);
  const pe = scenarioReturns(base, { ...NO_SHOCK, pe: -0.3 }).map((v, i) => v - r0[i]);
  assert.ok(Math.abs(pe[3] - (100 * Math.log(0.7)) / 10) < 1e-9);
  const real = scenarioReturns(base, { ...NO_SHOCK, real: 1 }).map((v, i) => v - r0[i]);
  assert.ok(Math.abs(real[0] - 1) < 1e-9 && Math.abs(real[1] + 0.792) < 1e-9 && real[3] === 0);
  const vols = scenarioVols(base, { ...NO_SHOCK, volScale: 1.5 });
  assert.ok(Math.abs(vols[3] - 20.61 * 1.5) < 1e-9 && vols[1] === 7.31);
});

test("Cholesky reproduces the matrix and correlation overrides stay positive definite", () => {
  const l = cholesky([
    [1, 0.5],
    [0.5, 1],
  ]);
  assert.ok(l && Math.abs(l[1][0] * l[1][0] + l[1][1] * l[1][1] - 1) < 1e-12);
  assert.equal(cholesky([[1, 1.2], [1.2, 1]]), null);
  const c = scenarioCorr(base, { ...NO_SHOCK, stockBond: 0.6 });
  assert.equal(c.shrunk, 0);
  assert.equal(c.corr[3][1], 0.6);
  const extreme = scenarioCorr(base, { ...NO_SHOCK, stockBond: -0.95 });
  assert.ok(extreme.shrunk > 0 && cholesky(extreme.corr));
});

test("with no volatility and no inflation the simulation is plain compounding", () => {
  const flat: LabBase = { ...base, classes: base.classes.map((c) => ({ ...c, ret: 6, vol: 0 })) };
  const w = [1, 0, 0, 0, 0, 0, 0];
  const s = simulate({ weights: w, initial: 100, monthly: 0, years: 2, paths: 3, seed: 1 }, scenarioReturns(flat, NO_SHOCK), scenarioVols(flat, NO_SHOCK), scenarioCorr(flat, NO_SHOCK).chol, 0, false);
  assert.ok(Math.abs(s.finals[0] - 100 * 1.06 ** 2) < 1e-6);
  assert.ok(Math.abs(bands(s, 2)[1].p50 - 106) < 1e-6);
});

test("same seed, worse assumptions: a lower chance; a crash costs equity-heavy portfolios", () => {
  const w = [0.1, 0.1, 0.1, 0.4, 0.2, 0.1, 0];
  const run = (shocks: typeof NO_SHOCK) =>
    simulate({ weights: w, initial: 1e9, monthly: 1e7, years: 10, paths: 400, seed: 7 }, scenarioReturns(base, shocks), scenarioVols(base, shocks), scenarioCorr(base, shocks).chol, base.inflation + shocks.inflation, shocks.crash);
  const a = run(NO_SHOCK);
  const b = run({ ...NO_SHOCK, growth: -2, pe: -0.3 });
  const c = run({ ...NO_SHOCK, crash: true });
  const goal = a.finals[200];
  assert.ok(chance(b.finals, goal) < chance(a.finals, goal));
  assert.ok(chance(c.finals, goal) < chance(a.finals, goal));
  assert.equal(hundred(a.finals).length, 100);
  assert.ok(hundred(a.finals)[0] <= hundred(a.finals)[99]);
});
