import { API_URL } from "@/lib/api";

const FORMATS = new Set(["xlsx", "json", "md"]);

/** Same-origin download of an approved VNCMA release (the API is not public). */
export async function GET(_request: Request, ctx: RouteContext<"/api/vncma/[version]/[fmt]">) {
  const { version, fmt } = await ctx.params;
  if (!/^\d{4}\.\d{1,3}$/.test(version) || !FORMATS.has(fmt)) {
    return Response.json({ error: "not found" }, { status: 404 });
  }
  const res = await fetch(`${API_URL}/vncma/${version}/download/${fmt}`);
  const headers = new Headers();
  for (const h of ["content-type", "content-disposition", "cache-control"]) {
    const v = res.headers.get(h);
    if (v) headers.set(h, v);
  }
  return new Response(res.body, { status: res.status, headers });
}
