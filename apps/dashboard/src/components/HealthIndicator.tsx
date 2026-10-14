"use client";

import type { HealthResponse } from "@cineforge/schemas";
import { api } from "@/lib/api";
import { usePolling, useResource } from "@/lib/hooks";
import { cx } from "./ui";

export const HEALTH_POLL_MS = 15_000;

export type HealthLevel = "checking" | "ok" | "degraded" | "down";

export function healthLevel(data: HealthResponse | undefined, error: unknown, loading: boolean): HealthLevel {
  if (error) return "down";
  if (!data) return loading ? "checking" : "down";
  return data.status;
}

const LABELS: Record<HealthLevel, string> = {
  checking: "Checking API…",
  ok: "API healthy",
  degraded: "API degraded",
  down: "API down",
};

const DOTS: Record<HealthLevel, string> = {
  checking: "bg-zinc-500",
  ok: "bg-emerald-400 shadow-[0_0_10px_2px_rgb(52_211_153/0.45)]",
  degraded: "bg-amber-400 shadow-[0_0_10px_2px_rgb(251_191_36/0.45)]",
  down: "bg-rose-500 shadow-[0_0_10px_2px_rgb(244_63_94/0.45)]",
};

export function useHealth() {
  const resource = useResource("health", () => api.health());
  usePolling(resource.reload, HEALTH_POLL_MS, true);
  return { ...resource, level: healthLevel(resource.data, resource.error, resource.loading) };
}

export function HealthDot({ level, className }: { level: HealthLevel; className?: string }) {
  return <span aria-hidden="true" className={cx("inline-block h-2 w-2 rounded-full", DOTS[level], className)} />;
}

export function HealthIndicator() {
  const { data, level } = useHealth();
  const failing = data?.checks?.filter((c) => c.status !== "ok").map((c) => c.name) ?? [];
  const title =
    level === "degraded" && failing.length
      ? `Degraded: ${failing.join(", ")}`
      : data
        ? `${data.service ?? "cineforge-api"} ${data.version} (${data.environment})`
        : LABELS[level];
  return (
    <div
      role="status"
      aria-live="polite"
      title={title}
      className="inline-flex items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-xs text-zinc-300"
    >
      <HealthDot level={level} />
      <span>{LABELS[level]}</span>
      {data?.provider_mode && (
        <span data-testid="provider-mode" className="border-l border-white/10 pl-2 text-zinc-500">
          {data.provider_mode === "live" ? "Live providers" : "Mock mode"}
        </span>
      )}
    </div>
  );
}
