/**
 * Economic balance sheet and goal plan (CFA private wealth, step 7). Runs in the browser; nothing the
 * visitor types leaves the device.
 *
 * Everything is in today's money (real terms). Cash flows are discounted at the real government bond
 * return from VNCMA: r = (1 + gov) / (1 + pi) - 1. Human capital adds a premium for how uncertain the
 * income is, as in the CFA curriculum (survival probabilities are left out, which overstates both sides).
 *
 * Assets:      financial assets + human capital (PV of income to retirement) + PV of the state pension.
 * Liabilities: debts + PV of spending to retirement + PV of spending in retirement + PV of the goals.
 * Economic net worth = assets - liabilities. A deficit means the plan does not add up at the risk-free
 * rate; investing above that rate narrows it, which the goal plan below measures with simulations.
 */

import { allocate, CONFIDENCE, type Allocation, type Goal, type ModelMix } from "./buckets.ts";
import { quantile, simulatePaths } from "./goals.ts";

export const ASSET_KINDS = ["deposit", "bond", "stock", "gold", "usd", "home", "property", "business", "other"] as const;
export type AssetKind = (typeof ASSET_KINDS)[number];
/** Kinds that can be sold within weeks and so fund the liquidity reserve and the goals. */
export const LIQUID: ReadonlySet<AssetKind> = new Set(["deposit", "bond", "stock", "gold", "usd"]);

export const JOBS = ["stable", "average", "volatile"] as const;
export type Job = (typeof JOBS)[number];
/** Premium (pp a year) over the real risk-free rate when discounting income. */
export const JOB_PREMIUM: Record<Job, number> = { stable: 1, average: 2.5, volatile: 4 };

export type Profile = {
  age: number;
  retirementAge: number;
  lifeExpectancy: number;
  monthlyIncome: number; // household, after tax and social insurance, VND
  annualBonus: number; // VND a year
  incomeGrowth: number; // real, percent a year
  job: Job;
  monthlySpending: number; // VND
  retirementSpending: number; // VND a month in today's money
  monthlyPension: number; // expected state pension, VND a month in today's money
  monthlyDebtPayment: number; // VND
  assets: { kind: AssetKind; name: string; value: number }[];
  debts: { name: string; balance: number }[];
  goals: Goal[]; // amounts in today's money
};

export type Rates = { govBond: number; inflation: number }; // percent a year, nominal

export type BalanceSheet = {
  realRate: number; // percent a year
  financial: number;
  liquid: number;
  illiquid: number; // home, property, business stake: usable only by selling them
  humanCapital: number;
  pension: number;
  totalAssets: number;
  debts: number;
  spendingToRetirement: number;
  spendingInRetirement: number;
  goals: number;
  totalLiabilities: number;
  netWorth: number;
  ratios: {
    liquidityMonths: number;
    debtToAssets: number; // debts / financial assets, 0..
    debtService: number; // monthly debt payment / monthly income
    savingsRate: number; // (income - spending - debt payment) / income
  };
  fix: { monthly: number; extraYears: number | null }; // ways to close a deficit
};

export const realRate = (r: Rates) => 100 * ((1 + r.govBond / 100) / (1 + r.inflation / 100) - 1);

/** PV of 1 a year paid at the end of years from+1 .. to, growing by g, discounted at r (percent). */
export function annuity(from: number, to: number, r: number, g = 0): number {
  let pv = 0;
  for (let t = from + 1; t <= to; t++) pv += Math.pow(1 + g / 100, t - 1 - from) / Math.pow(1 + r / 100, t);
  return pv;
}

const yearsTo = (p: Profile) => Math.max(0, p.retirementAge - p.age);
const yearsLeft = (p: Profile) => Math.max(yearsTo(p), p.lifeExpectancy - p.age);
const annualIncome = (p: Profile) => 12 * p.monthlyIncome + p.annualBonus;
const sum = (xs: number[]) => xs.reduce((s, v) => s + v, 0);

function netWorthOf(p: Profile, r: number): number {
  return balanceSheet(p, r, false).netWorth;
}

function balanceSheet(p: Profile, r: number, withFix: boolean): BalanceSheet {
  const n = yearsTo(p);
  const life = yearsLeft(p);
  const financial = sum(p.assets.map((a) => a.value));
  const liquid = sum(p.assets.filter((a) => LIQUID.has(a.kind)).map((a) => a.value));
  // Income starts its growth after the first year; human capital is discounted at r + the job premium.
  const humanCapital = annualIncome(p) * annuity(0, n, r + JOB_PREMIUM[p.job], p.incomeGrowth);
  const pension = 12 * p.monthlyPension * annuity(n, life, r);
  const debts = sum(p.debts.map((d) => d.balance));
  const spendingToRetirement = 12 * p.monthlySpending * annuity(0, n, r);
  const spendingInRetirement = 12 * p.retirementSpending * annuity(n, life, r);
  const goals = sum(p.goals.map((g) => g.amount / Math.pow(1 + r / 100, g.years)));
  const totalAssets = financial + humanCapital + pension;
  const totalLiabilities = debts + spendingToRetirement + spendingInRetirement + goals;
  const netWorth = totalAssets - totalLiabilities;
  const income = p.monthlyIncome + p.annualBonus / 12;

  let fix = { monthly: 0, extraYears: null as number | null };
  if (withFix && netWorth < 0) {
    const months = 12 * annuity(0, n, r);
    let extraYears: number | null = null;
    for (let k = 1; k <= 15; k++) {
      if (netWorthOf({ ...p, retirementAge: p.retirementAge + k, lifeExpectancy: Math.max(p.lifeExpectancy, p.retirementAge + k) }, r) >= 0) {
        extraYears = k;
        break;
      }
    }
    fix = { monthly: months > 0 ? -netWorth / months : Infinity, extraYears };
  }

  return {
    realRate: r,
    financial,
    liquid,
    illiquid: financial - liquid,
    humanCapital,
    pension,
    totalAssets,
    debts,
    spendingToRetirement,
    spendingInRetirement,
    goals,
    totalLiabilities,
    netWorth,
    ratios: {
      liquidityMonths: p.monthlySpending > 0 ? sum(p.assets.filter((a) => a.kind === "deposit").map((a) => a.value)) / p.monthlySpending : Infinity,
      debtToAssets: financial > 0 ? debts / financial : debts > 0 ? Infinity : 0,
      debtService: income > 0 ? p.monthlyDebtPayment / income : 0,
      savingsRate: income > 0 ? (income - p.monthlySpending - p.monthlyDebtPayment) / income : 0,
    },
    fix,
  };
}

export function economicBalanceSheet(p: Profile, rates: Rates): BalanceSheet {
  return balanceSheet(p, realRate(rates), true);
}

/** Retirement as a goal: what is needed at retirement (today's money) to cover spending above the pension. */
export function retirementGoal(p: Profile, rates: Rates, name: string): Goal | null {
  const n = yearsTo(p);
  const gap = 12 * Math.max(0, p.retirementSpending - p.monthlyPension);
  if (gap <= 0 || n <= 0) return null;
  // Value at the retirement date of the spending gap, discounted back to that date only.
  const atRetirement = gap * annuity(n, yearsLeft(p), realRate(rates)) * Math.pow(1 + realRate(rates) / 100, n);
  return { name, amount: atRetirement, years: n, essential: true };
}

/** VND a month (today's money, rising with inflation) that closes a goal's gap with `confidence`. */
export function monthlyNeeded(
  goal: Goal,
  mix: ModelMix,
  confidence: number,
  inflation: number,
  funded: number,
  seed: number,
): number {
  const target = goal.amount * Math.pow(1 + inflation / 100, goal.years);
  const { growth, annuity: fund } = simulatePaths(mix.expectedReturn, mix.volatility, goal.years, inflation, seed, 2000);
  const need = Array.from(growth, (g, i) => Math.max(0, (target - funded * g) / fund[i])).sort((a, b) => a - b);
  return quantile(need, confidence);
}

export type GoalPlan = {
  allocation: Allocation;
  monthly: { name: string; amount: number }[]; // monthly saving needed per underfunded goal
  monthlyTotal: number;
  monthlySurplus: number; // income - spending - debt payments
};

/** Liquid assets fund the reserve and the goals (retirement included); gaps become a monthly saving. */
export function goalPlan(p: Profile, rates: Rates, mixes: ModelMix[], riskLevel: number, liquidityMonths: number, retirementName: string): GoalPlan {
  const retirement = retirementGoal(p, rates, retirementName);
  const goals = retirement ? [...p.goals, retirement] : p.goals;
  const allocation = allocate(
    {
      total: sum(p.assets.filter((a) => LIQUID.has(a.kind)).map((a) => a.value)),
      monthlySpending: p.monthlySpending,
      liquidityMonths,
      goals,
      riskLevel,
      inflation: rates.inflation,
    },
    mixes,
  );
  const monthly = allocation.goals
    .filter((g) => g.funded < g.needed - 1)
    .map((g, i) => ({
      name: g.goal.name,
      amount: monthlyNeeded(g.goal, g.portfolio, g.confidence, rates.inflation, g.funded, 7177 + 13 * i),
    }));
  return {
    allocation,
    monthly,
    monthlyTotal: sum(monthly.map((m) => m.amount)),
    monthlySurplus: p.monthlyIncome + p.annualBonus / 12 - p.monthlySpending - p.monthlyDebtPayment,
  };
}

export { CONFIDENCE };
