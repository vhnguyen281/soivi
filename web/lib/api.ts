import "server-only";

import { cacheLife, cacheTag } from "next/cache";

import type {
  CardDetail,
  CardRank,
  CardSummary,
  Change,
  History,
  Institution,
  Persona,
  SavingsRank,
  SavingsRate,
  FundStats,
  ModelPortfolios,
  Vncma,
} from "./types";

/**
 * Server-side reads from the Soivi API. Every function is cached under the
 * "soivi" tag: POST /api/revalidate (called by the review app after an approval)
 * expires them all, and the "soivi" cacheLife profile refreshes them hourly.
 *
 * "Cache-Control: no-cache" asks the API to skip its own one-minute cache, so a
 * rebuild right after an approval sees the new values.
 */
export const API_URL = process.env.SOIVI_API_URL ?? "http://127.0.0.1:8002";

/**
 * Headers for every call to the Soivi API. When the API is on the internet it requires
 * SOIVI_API_TOKEN in X-Soivi-Token (server-side only: this module is "server-only").
 */
export function apiHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = process.env.SOIVI_API_TOKEN;
  return token ? { ...extra, "X-Soivi-Token": token } : extra;
}
export const TAG = "soivi";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: apiHeaders({ "Cache-Control": "no-cache", Accept: "application/json" }),
  });
  if (!res.ok) throw new Error(`Soivi API ${path} answered HTTP ${res.status}`);
  return (await res.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json", "Cache-Control": "no-cache" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Soivi API ${path} answered HTTP ${res.status}`);
  return (await res.json()) as T;
}

export async function getInstitutions(): Promise<Institution[]> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  return (await get<{ institutions: Institution[] }>("/institutions")).institutions;
}

export async function getRates(): Promise<SavingsRate[]> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  return (await get<{ rates: SavingsRate[] }>("/savings/rates")).rates;
}

export async function getRank(amount: number, term: number): Promise<SavingsRank> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  return get<SavingsRank>(`/savings/rank?amount=${amount}&term=${term}`);
}

/** `fetchedAt`: when this copy was read, so a chart can run up to "now". */
export async function getHistory(institution: string): Promise<(History & { fetchedAt: string }) | null> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  const res = await fetch(
    `${API_URL}/savings/history?institution=${encodeURIComponent(institution)}`,
    { headers: apiHeaders({ "Cache-Control": "no-cache" }) },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Soivi API history answered HTTP ${res.status}`);
  return { ...((await res.json()) as History), fetchedAt: new Date().toISOString() };
}

export async function getCards(): Promise<CardSummary[]> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  return (await get<{ cards: CardSummary[] }>("/cards")).cards;
}

export async function getCard(id: number): Promise<CardDetail | null> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  const res = await fetch(`${API_URL}/cards/${id}`, { headers: apiHeaders({ "Cache-Control": "no-cache" }) });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Soivi API card answered HTTP ${res.status}`);
  return ((await res.json()) as { card: CardDetail }).card;
}

export async function getPersonas(): Promise<Persona[]> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  return (await get<{ personas: Persona[] }>("/cards/personas")).personas;
}

export async function getPersonaRank(persona: string): Promise<CardRank> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  return post<CardRank>("/cards/rank", { persona });
}

/** Approved changes over the last `weeks` weeks (the date is fixed per cache entry). */
export async function getChanges(weeks: number): Promise<{ since: string; changes: Change[] }> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  const since = new Date(Date.now() - weeks * 7 * 86_400_000).toISOString().slice(0, 10);
  return get<{ since: string; changes: Change[] }>(`/changes?since=${since}&limit=500`);
}

export async function getMethodologyVersion(): Promise<string> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  return (await get<{ methodology_version: string }>("/methodology")).methodology_version;
}

/** The latest approved VNCMA release, or null before the first one. */
export async function getVncma(): Promise<Vncma | null> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  const res = await fetch(`${API_URL}/vncma/latest`, { headers: apiHeaders({ "Cache-Control": "no-cache" }) });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Soivi API vncma answered HTTP ${res.status}`);
  return (await res.json()) as Vncma;
}

/** Model portfolios approved for the latest VNCMA release, or null if none yet. */
export async function getModelPortfolios(): Promise<ModelPortfolios | null> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  const res = await fetch(`${API_URL}/vncma/latest/portfolios`, {
    headers: apiHeaders({ "Cache-Control": "no-cache" }),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Soivi API portfolios answered HTTP ${res.status}`);
  return (await res.json()) as ModelPortfolios;
}

/** The latest approved fund statistics by group, or null before the first approval. */
export async function getFundStats(): Promise<FundStats | null> {
  "use cache";
  cacheLife("soivi");
  cacheTag(TAG);
  const res = await fetch(`${API_URL}/funds/stats`, { headers: apiHeaders({ "Cache-Control": "no-cache" }) });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Soivi API funds answered HTTP ${res.status}`);
  return (await res.json()) as FundStats;
}
