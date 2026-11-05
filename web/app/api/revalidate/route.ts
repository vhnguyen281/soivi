import { timingSafeEqual } from "node:crypto";

import { revalidateTag } from "next/cache";
import type { NextRequest } from "next/server";

import { TAG } from "@/lib/api";

/**
 * Called by the review app after an approval (review_app/webhook.py).
 * Expires every cached API read, so each page is rebuilt with the new values on
 * its next visit. `{ expire: 0 }`: visitors never see the old numbers again.
 */
export async function POST(request: NextRequest) {
  const secret = process.env.REVALIDATE_SECRET ?? "";
  const given = request.headers.get("x-soivi-secret") ?? "";
  const ok =
    secret.length > 0 &&
    given.length === secret.length &&
    timingSafeEqual(Buffer.from(given), Buffer.from(secret));
  if (!ok) return Response.json({ revalidated: false }, { status: 401 });
  revalidateTag(TAG, { expire: 0 });
  return Response.json({ revalidated: true, tag: TAG });
}
