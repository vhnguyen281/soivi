/**
 * Probability of reaching a savings goal with a model portfolio (goals-based planning, Phase B).
 * Runs in the browser: nothing the visitor types leaves the device.
 *
 * Model: monthly log returns are normal with mean ln(1 + G) / 12 and variance sigma^2 / 12, where G is
 * the portfolio's expected geometric return and sigma its volatility (VNCMA). The goal value at the end
 * is linear in the monthly contribution C:
 *     V = A * growth + C * annuity,
 * growth = the path's growth of today's savings A, annuity = the path's value of 1 VND contributed at
 * the end of every month (raised by `contributionGrowth` each year). So one simulation answers both
 * "what is the chance?" and "how much a month for an 80% chance?" (a quantile of (goal - A*growth)/annuity).
 * A seeded generator makes the same inputs give the same answer.
 */

export type PortfolioInput = {
  id: string;
  name: string;
  expectedReturn: number; // geometric, percent a year
  volatility: number; // percent a year
  scenarioShift: { adverse: number; favourable: number }; // pp a year, from the VNCMA scenarios
};

export type GoalInput = {
  goal: number; // VND, in today's money when `inTodaysMoney`
  years: number;
  savings: number; // VND today
  monthly: number; // VND a month
  contributionGrowth: number; // percent a year
  inTodaysMoney: boolean;
  inflation: number; // percent a year (VNCMA pi)
};

export type Outcome = {
  probability: number; // 0..1
  median: number;
  p10: number; // 10th percentile of the final value
  monthlyFor80: number; // monthly contribution for an 80% chance (0 if already met)
};

export type PortfolioResult = {
  id: string;
  name: string;
  base: Outcome;
  adverse: Outcome;
  favourable: Outcome;
};

export const PATHS = 4000;
export const TARGET_PROBABILITY = 0.8;

/** Mulberry32: a small, fast, seeded PRNG. */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function normals(random: () => number): () => number {
  let spare: number | null = null;
  return () => {
    if (spare !== null) {
      const s = spare;
      spare = null;
      return s;
    }
    let u = 0;
    while (u === 0) u = random();
    const v = random();
    const r = Math.sqrt(-2 * Math.log(u));
    spare = r * Math.sin(2 * Math.PI * v);
    return r * Math.cos(2 * Math.PI * v);
  };
}

export function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** The goal in money of the final year. */
export function nominalGoal(input: GoalInput): number {
  return input.inTodaysMoney ? input.goal * Math.pow(1 + input.inflation / 100, input.years) : input.goal;
}

/** growth and annuity per path, for an expected geometric return and volatility (percent). */
export function simulatePaths(
  expectedReturn: number,
  volatility: number,
  years: number,
  contributionGrowth: number,
  seed: number,
  paths = PATHS,
): { growth: Float64Array; annuity: Float64Array } {
  const months = Math.max(1, Math.round(years * 12));
  const mu = Math.log(1 + expectedReturn / 100) / 12;
  const sd = volatility / 100 / Math.sqrt(12);
  const step = 1 + contributionGrowth / 100;
  const z = normals(rng(seed));
  const growth = new Float64Array(paths);
  const annuity = new Float64Array(paths);
  for (let p = 0; p < paths; p++) {
    let value = 1; // growth of 1 VND held from today
    let fund = 0; // value of the contributions so far, per 1 VND of first-year contribution
    let contribution = 1;
    for (let m = 0; m < months; m++) {
      if (m > 0 && m % 12 === 0) contribution *= step;
      const factor = Math.exp(mu + sd * z());
      value *= factor;
      fund = fund * factor + contribution;
    }
    growth[p] = value;
    annuity[p] = fund;
  }
  return { growth, annuity };
}

export function outcome(
  input: GoalInput,
  sims: { growth: Float64Array; annuity: Float64Array },
): Outcome {
  const goal = nominalGoal(input);
  const finals: number[] = [];
  const needed: number[] = [];
  let hits = 0;
  for (let p = 0; p < sims.growth.length; p++) {
    const v = input.savings * sims.growth[p] + input.monthly * sims.annuity[p];
    finals.push(v);
    if (v >= goal) hits++;
    needed.push(Math.max(0, (goal - input.savings * sims.growth[p]) / sims.annuity[p]));
  }
  finals.sort((a, b) => a - b);
  needed.sort((a, b) => a - b);
  return {
    probability: hits / sims.growth.length,
    median: quantile(finals, 0.5),
    p10: quantile(finals, 0.1),
    monthlyFor80: quantile(needed, TARGET_PROBABILITY),
  };
}

export function plan(input: GoalInput, portfolios: PortfolioInput[], seed = 2027): PortfolioResult[] {
  return portfolios.map((p, i) => {
    const run = (shift: number, k: number) =>
      outcome(input, simulatePaths(p.expectedReturn + shift, p.volatility, input.years, input.contributionGrowth, seed + 97 * i + k));
    return {
      id: p.id,
      name: p.name,
      base: run(0, 0),
      adverse: run(p.scenarioShift.adverse, 1),
      favourable: run(p.scenarioShift.favourable, 2),
    };
  });
}

/** Portfolio scenario shift = weighted shift of its classes (pp a year). */
export function scenarioShift(
  weights: { asset_class: string; percent: number }[],
  classes: { id: string; expected_return: string; scenarios: { adverse: string; favourable: string } }[],
): { adverse: number; favourable: number } {
  const by = new Map(classes.map((c) => [c.id, c]));
  let adverse = 0;
  let favourable = 0;
  for (const w of weights) {
    const c = by.get(w.asset_class);
    if (!c) continue;
    adverse += (w.percent / 100) * (Number(c.scenarios.adverse) - Number(c.expected_return));
    favourable += (w.percent / 100) * (Number(c.scenarios.favourable) - Number(c.expected_return));
  }
  return { adverse, favourable };
}
