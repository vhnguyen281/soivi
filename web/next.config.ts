import type { NextConfig } from "next";

/** A positive whole number from the environment, else the default. */
function envInt(name: string, fallback: number): number {
  const value = Number(process.env[name]);
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  poweredByHeader: false,
  // `next start` in Docker: a self-contained server bundle.
  output: "standalone",
  // Prerendering calls the API for every page. Unbounded parallel builds queued
  // past the API's database pool (15 connections to Neon) and timed out, so
  // keep at most 2 workers x 4 pages in flight and retry a page that fails.
  // On a hosted build (e.g. Vercel, API across the internet) tune with
  // SOIVI_BUILD_CPUS / SOIVI_BUILD_CONCURRENCY / SOIVI_BUILD_RETRIES.
  experimental: {
    cpus: envInt("SOIVI_BUILD_CPUS", 2),
    staticGenerationMaxConcurrency: envInt("SOIVI_BUILD_CONCURRENCY", 4),
    staticGenerationRetryCount: envInt("SOIVI_BUILD_RETRIES", 2),
  },
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
