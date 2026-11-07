import { API_URL, apiHeaders } from "@/lib/api";

/** Same-origin proxy for the card finder's custom profile. */
export async function POST(request: Request) {
  const body = await request.text();
  if (body.length > 10_000) return Response.json({ error: "too large" }, { status: 413 });
  const res = await fetch(`${API_URL}/cards/rank`, {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body,
  });
  return new Response(res.body, { status: res.status, headers: { "Content-Type": "application/json" } });
}
