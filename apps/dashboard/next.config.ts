import path from "node:path";
import type { NextConfig } from "next";
import { apiInternalUrl, PROXIED_PATHS } from "./src/lib/apiTarget";

const monorepoRoot = path.join(__dirname, "..", "..");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The repo-level AGENTS.md is the single source of agent guidance.
  agentRules: false,
  transpilePackages: ["@cineforge/schemas"],
  outputFileTracingRoot: monorepoRoot,
  turbopack: { root: monorepoRoot },
  // `next build` bakes these destinations into the build output; src/proxy.ts
  // re-resolves API_INTERNAL_URL per request so the runtime value always wins.
  async rewrites() {
    const api = apiInternalUrl();
    return PROXIED_PATHS.map((source) => ({ source, destination: `${api}${source}` }));
  },
};

export default nextConfig;
