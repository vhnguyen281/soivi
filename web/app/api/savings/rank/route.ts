import type { NextRequest } from "next/server";

import { API_URL } from "@/lib/api";

/** Same-origin proxy for the calculator (the API keeps the formula and its cache). */
export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams;
  const qs = new URLSearchParams();
  for (const key of ["amount", "term", "channel", "region"]) {
    const value = q.get(key);
    if (value) qs.set(key, value);
  }
  const res = await fetch(`${API_URL}/savings/rank?${qs}`, { headers: { Accept: "application/json" } });
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=60" },
  });
}
