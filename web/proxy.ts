import { NextResponse, type NextRequest } from "next/server";

/**
 * Vietnamese is served at the root (/lai-suat-tiet-kiem), English under /en/...
 * Both map onto one route tree, app/[lang]/..., by rewriting root paths to /vi/...
 * A request for /vi/... is redirected to the root, so each page has one URL.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname === "/en" || pathname.startsWith("/en/")) return NextResponse.next();
  // Open Graph images keep their generated /vi/... URL (it's what the meta tag names).
  if (pathname.startsWith("/vi/") && pathname.endsWith("/opengraph-image")) return NextResponse.next();
  if (pathname === "/vi/opengraph-image") return NextResponse.next();
  if (pathname === "/vi" || pathname.startsWith("/vi/")) {
    const url = request.nextUrl.clone();
    url.pathname = pathname.slice(3) || "/";
    return NextResponse.redirect(url, 308);
  }
  const url = request.nextUrl.clone();
  url.pathname = `/vi${pathname === "/" ? "" : pathname}`;
  return NextResponse.rewrite(url);
}

export const config = {
  // Everything except API routes, Next internals, metadata files and static assets.
  matcher: [
    "/((?!api/|_next/|sitemap.xml|robots.txt|favicon.ico|icon.svg|.*\\.(?:png|jpg|svg|ico|txt|xml)$).*)",
  ],
};
