/**
 * Goals-based allocation in three parts (Brunel, "Goals-Based Wealth Management"; Phase D).
 * Runs in the browser; nothing is stored.
 *
 * 1. Liquidity: `months` of spending, held in deposits.
 * 2. Goals: each goal gets the amount that reaches it with a required confidence, in a model portfolio chosen
 *    by its horizon and priority (never riskier than the visitor's risk level). Essential goals need 90%
 *    confidence, aspirational goals 60%. The amount is the confidence-quantile of goal / growth over simulated
 *    paths, so A * growth >= goal on that share of paths.
 * 3. Growth: whatever is left, in the visitor's own model portfolio.
 * Money runs out in that order: liquidity, essential goals (soonest first), aspirational goals (soonest first).
 */

import { quantile, simulatePaths } from "./goals.ts";

export type ModelMix = {
  id: string;
  name: string;
  expectedReturn: number; // geometric, percent a year
  volatility: number; // percent a year
  weights: { asset_class: string; percent: number }[];
};

export type Goal = {
  name: string;
  amount: number; // VND in today's money
  years: number;
  essential: boolean;
};

export type BucketInput = {
  total: number; // investable assets, VND
  monthlySpending: number; // VND
  liquidityMonths: number;
  goals: Goal[];
  riskLevel: number; // 1..5
  inflation: number; // percent a year
};

export type GoalBucket = {
  goal: Goal;
  portfolio: ModelMix;
  confidence: number;
  needed: number; // VND today for the required confidence
  funded: number; // VND actually set aside
};

export type Allocation = {
  liquidity: number;
  liquidityShort: number; // how much short of the liquidity target
  goals: GoalBucket[];
  growth: number;
  growthPortfolio: ModelMix;
  mix: { asset_class: string; amount: number; percent: number }[]; // the whole picture by asset class
};

export const CONFIDENCE = { essential: 0.9, aspirational: 0.6 };
const PATHS = 2000;

/** Model portfolio level (1..5) for a goal: shorter and more essential means more cautious. */
export function goalLevel(goal: Goal, riskLevel: number): number {
  const byHorizon = goal.years < 3 ? 1 : goal.years < 7 ? (goal.essential ? 2 : 3) : goal.essential ? 3 : 5;
  return Math.max(1, Math.min(byHorizon, riskLevel));
}

/** VND needed today so that the goal (inflated to its year) is reached with `confidence`. */
export function amountNeeded(goal: Goal, mix: ModelMix, confidence: number, inflation: number, seed: number): number {
  const target = goal.amount * Math.pow(1 + inflation / 100, goal.years);
  const { growth } = simulatePaths(mix.expectedReturn, mix.volatility, goal.years, 0, seed, PATHS);
  const ratios = Array.from(growth, (g) => target / g).sort((a, b) => a - b);
  return quantile(ratios, confidence);
}

export function allocate(input: BucketInput, mixes: ModelMix[]): Allocation {
  if (mixes.length === 0) throw new Error("no model portfolios");
  const pick = (level: number) => mixes[Math.max(1, Math.min(level, mixes.length)) - 1];
  const wantLiquidity = input.monthlySpending * input.liquidityMonths;
  const liquidity = Math.min(input.total, wantLiquidity);
  let left = input.total - liquidity;

  const ordered = input.goals
    .map((goal, index) => ({ goal, index }))
    .filter(({ goal }) => goal.amount > 0 && goal.years > 0)
    .sort((a, b) => Number(b.goal.essential) - Number(a.goal.essential) || a.goal.years - b.goal.years);
  const goals: GoalBucket[] = [];
  for (const { goal, index } of ordered) {
    const portfolio = pick(goalLevel(goal, input.riskLevel));
    const confidence = goal.essential ? CONFIDENCE.essential : CONFIDENCE.aspirational;
    const needed = amountNeeded(goal, portfolio, confidence, input.inflation, 4049 + 31 * index);
    const funded = Math.min(left, needed);
    left -= funded;
    goals.push({ goal, portfolio, confidence, needed, funded });
  }

  const growthPortfolio = pick(input.riskLevel);
  const byClass = new Map<string, number>([["cash_vnd", liquidity]]);
  const add = (mix: ModelMix, amount: number) => {
    for (const w of mix.weights) byClass.set(w.asset_class, (byClass.get(w.asset_class) ?? 0) + (amount * w.percent) / 100);
  };
  for (const g of goals) add(g.portfolio, g.funded);
  add(growthPortfolio, left);
  const order = mixes[0].weights.map((w) => w.asset_class);
  const mix = order.map((c) => {
    const amount = byClass.get(c) ?? 0;
    return { asset_class: c, amount, percent: input.total > 0 ? (100 * amount) / input.total : 0 };
  });
  return {
    liquidity,
    liquidityShort: wantLiquidity - liquidity,
    goals,
    growth: left,
    growthPortfolio,
    mix,
  };
}
