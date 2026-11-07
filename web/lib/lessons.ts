/**
 * Maths behind the homepage journey and the interactive lessons. Pure functions, run in the browser.
 * Rates are percent a year; money is VND.
 */

import { rng } from "./goals.ts";

/** What 100 VND kept at `rate` buys after `years`, with inflation `pi` (both percent a year, compounded yearly). */
export function realValue(years: number, rate: number, pi: number): number {
  return (100 * Math.pow(1 + rate / 100, years)) / Math.pow(1 + pi / 100, years);
}

/** Years for prices to double ("rule of 72", exact form). */
export function doublingYears(pi: number): number {
  return pi > 0 ? Math.log(2) / Math.log(1 + pi / 100) : Infinity;
}

/** Interest on a term deposit kept to maturity vs. withdrawn early at the demand rate (simple interest, end of term). */
export function earlyWithdrawal(amount: number, termRate: number, termMonths: number, demandRate: number, monthsHeld: number) {
  const held = Math.min(Math.max(0, monthsHeld), termMonths);
  const atMaturity = (amount * termRate * termMonths) / 12 / 100;
  const early = (amount * demandRate * held) / 12 / 100;
  // What the full-term interest would have been for the months actually held.
  const promised = (amount * termRate * held) / 12 / 100;
  return { atMaturity, early, lost: promised - early };
}

export type Payoff = { months: number; interest: number; paid: number; never: boolean };

/**
 * Paying off a card balance with no new spending: each month interest at apr/12 is added, then the payment is
 * max(minPct of the balance, floor), or `fixed` when given. Stops after 50 years.
 */
export function payoff(balance: number, apr: number, minPct: number, floor: number, fixed?: number): Payoff {
  let b = balance;
  let interest = 0;
  let paid = 0;
  let months = 0;
  const r = apr / 100 / 12;
  while (b > 0.5 && months < 600) {
    const i = b * r;
    const due = b + i;
    const pay = Math.min(due, fixed ?? Math.max((minPct / 100) * b, floor));
    if (pay <= i) return { months: Infinity, interest: Infinity, paid: Infinity, never: true };
    interest += i;
    paid += pay;
    b = due - pay;
    months++;
  }
  return { months, interest, paid, never: b > 0.5 };
}

/** Yearly value paths of 100 VND for a portfolio (geometric expected return and volatility, percent). */
export function fanPaths(expectedReturn: number, volatility: number, years: number, n: number, seed: number): number[][] {
  const random = rng(seed);
  const mu = Math.log(1 + expectedReturn / 100);
  const sd = volatility / 100;
  const out: number[][] = [];
  for (let p = 0; p < n; p++) {
    let v = 100;
    const path = [v];
    for (let y = 0; y < years; y++) {
      let u = 0;
      while (u === 0) u = random();
      const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * random());
      v *= Math.exp(mu + sd * z);
      path.push(v);
    }
    out.push(path);
  }
  return out;
}

/** 10th and 90th percentile of the final values, and the share of paths below the start. */
export function fanSummary(paths: number[][]): { low: number; high: number; loss: number } {
  const finals = paths.map((p) => p[p.length - 1]).sort((a, b) => a - b);
  const at = (q: number) => finals[Math.min(finals.length - 1, Math.floor(q * finals.length))];
  return { low: at(0.1), high: at(0.9), loss: finals.filter((v) => v < 100).length / finals.length };
}

/** Monthly saving that reaches `goal` in `years` at `rate` percent a year (deterministic). */
export function monthlyFor(goal: number, years: number, rate: number): number {
  const i = Math.pow(1 + rate / 100, 1 / 12) - 1;
  const n = Math.max(1, Math.round(years * 12));
  return i === 0 ? goal / n : (goal * i) / (Math.pow(1 + i, n) - 1);
}

/** 80% range of the average yearly return over `years` (normal approximation, as in VNCMA's band_80). */
export function band80(expectedReturn: number, volatility: number, years: number): [number, number] {
  const half = (1.2816 * volatility) / Math.sqrt(Math.max(1, years));
  return [expectedReturn - half, expectedReturn + half];
}

/**
 * Yearly returns (percent) for the hold-or-sell game: seeded draws from the class's return and volatility, with a
 * fall of `crash` percent forced in year `crashYear` (0-based). A simulation, not history.
 */
export function gameReturns(expectedReturn: number, volatility: number, years: number, seed: number, crashYear: number, crash: number): number[] {
  const random = rng(seed);
  const mu = Math.log(1 + expectedReturn / 100);
  const sd = volatility / 100;
  return Array.from({ length: years }, (_, y) => {
    let u = 0;
    while (u === 0) u = random();
    const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * random());
    return y === crashYear ? -Math.abs(crash) : 100 * (Math.exp(mu + sd * z) - 1);
  });
}

/**
 * Value of 100 through the game. `invested[y]` says whether the money is in the market during year y; out of the
 * market it earns `cashRate`.
 */
export function playGame(returns: number[], invested: boolean[], cashRate: number): number[] {
  const path = [100];
  returns.forEach((r, y) => path.push(path[y] * (1 + (invested[y] ?? true ? r : cashRate) / 100)));
  return path;
}

/** Expected return and volatility of a two-asset mix (`w` in the first), percent a year. */
export function mix2(w: number, a: { ret: number; vol: number }, b: { ret: number; vol: number }, rho: number) {
  const ret = w * a.ret + (1 - w) * b.ret;
  const vol = Math.sqrt((w * a.vol) ** 2 + ((1 - w) * b.vol) ** 2 + 2 * w * (1 - w) * rho * a.vol * b.vol);
  return { ret, vol, saved: w * a.vol + (1 - w) * b.vol - vol };
}
