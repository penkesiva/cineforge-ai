import path from "node:path";
import type { NextConfig } from "next";

const monorepoRoot = path.join(__dirname, "..", "..");

/**
 * Upstream FastAPI service. Rewrites are resolved when `next dev` starts and
 * baked into the build output by `next build`, so production images must have
 * API_INTERNAL_URL set at build time as well as at runtime.
 */
export function apiInternalUrl(env: NodeJS.ProcessEnv = process.env): string {
  return (env.API_INTERNAL_URL?.trim() || "http://localhost:8000").replace(/\/+$/, "");
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  transpilePackages: ["@cineforge/schemas"],
  outputFileTracingRoot: monorepoRoot,
  turbopack: { root: monorepoRoot },
  async rewrites() {
    const api = apiInternalUrl();
    return [
      { source: "/api/v1/:path*", destination: `${api}/api/v1/:path*` },
      { source: "/health", destination: `${api}/health` },
      { source: "/health/live", destination: `${api}/health/live` },
    ];
  },
};

export default nextConfig;
