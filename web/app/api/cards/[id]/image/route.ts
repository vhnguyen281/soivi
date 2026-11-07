import { API_URL, apiHeaders } from "@/lib/api";

/** Same-origin card picture (the API is not public). Only reviewer-approved pictures exist. */
export async function GET(request: Request, ctx: RouteContext<"/api/cards/[id]/image">) {
  const { id } = await ctx.params;
  if (!/^\d{1,9}$/.test(id)) return new Response("not found", { status: 404 });
  const inm = request.headers.get("if-none-match");
  const res = await fetch(`${API_URL}/cards/${id}/image`, { headers: apiHeaders(inm ? { "If-None-Match": inm } : {}) });
  const headers = new Headers();
  for (const h of ["content-type", "cache-control", "etag"]) {
    const v = res.headers.get(h);
    if (v) headers.set(h, v);
  }
  headers.set("X-Content-Type-Options", "nosniff");
  return new Response(res.status === 304 ? null : res.body, { status: res.status, headers });
}
