import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  poweredByHeader: false,
  // `next start` in Docker: a self-contained server bundle.
  output: "standalone",
  cacheLife: {
    // All data comes from the Soivi API. Pages are rebuilt as soon as the review
    // app reports an approval (POST /api/revalidate); this hourly refresh also
    // picks up changes that aren't approvals, such as a source becoming stale.
    // If the API is down, the last good page is kept for up to 30 days.
    soivi: { stale: 300, revalidate: 3600, expire: 60 * 60 * 24 * 30 },
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
