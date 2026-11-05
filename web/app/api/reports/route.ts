import { API_URL } from "@/lib/api";

const MAX_BYTES = 6_000_000; // the API rejects screenshots over 5 MB; leave room for the form

/**
 * Same-origin proxy for "Báo sai số liệu". The API rate-limits by client IP, so
 * the visitor's IP is passed on in X-Forwarded-For (the API trusts it only when
 * TRUST_PROXY_HEADERS=true, which the Compose file sets for this setup).
 */
export async function POST(request: Request) {
  const length = Number(request.headers.get("content-length") ?? 0);
  if (length > MAX_BYTES) return Response.json({ error: "too large" }, { status: 413 });
  const forwarded = request.headers.get("x-forwarded-for");
  const ip = forwarded?.split(",")[0]?.trim() || request.headers.get("x-real-ip") || "";
  const res = await fetch(`${API_URL}/reports`, {
    method: "POST",
    headers: {
      "Content-Type": request.headers.get("content-type") ?? "",
      ...(ip ? { "X-Forwarded-For": ip } : {}),
    },
    body: await request.arrayBuffer(),
  });
  const headers: Record<string, string> = { "Content-Type": "application/json", "Cache-Control": "no-store" };
  const retry = res.headers.get("retry-after");
  if (retry) headers["Retry-After"] = retry;
  return new Response(res.body, { status: res.status, headers });
}
