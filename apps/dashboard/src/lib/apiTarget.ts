export const DEFAULT_API_INTERNAL_URL = "http://localhost:8000";

/** Upstream FastAPI origin used by the same-origin proxy (`API_INTERNAL_URL`). */
export function apiInternalUrl(env: Record<string, string | undefined> = process.env): string {
  return (env.API_INTERNAL_URL?.trim() || DEFAULT_API_INTERNAL_URL).replace(/\/+$/, "");
}

/** Paths forwarded to the API. Keep in sync with `config.matcher` in src/proxy.ts. */
export const PROXIED_PATHS = ["/api/v1/:path*", "/health", "/health/live"] as const;
