"use client";

import type { CreateProductionRequest, ProductionState, ProductionSummary } from "@cineforge/schemas";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { formatUsd, humanize } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { isExceptionState, isWorkingState } from "@/lib/workflow";
import { AppNoticeDialog, type NoticeState } from "../dialogs/AppNoticeDialog";
import { HealthDot, useHealth } from "../HealthIndicator";
import { IconSpark } from "../icons";
import { ProductionsTable } from "../productions/ProductionsTable";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, SimulatedBadge, Stat } from "../ui";

export const SAMPLE_PRODUCTION: CreateProductionRequest = {
  theme_id: "time-traveler",
  topic: "The night the Eiffel Tower first lit up for the 1889 World's Fair",
  title: "Eiffel Tower, 1889",
  mode: "balanced",
  duration_target_sec: 45,
  auto_approve: false,
};

const GROUPS: Array<{ label: string; match: (s: ProductionState) => boolean }> = [
  { label: "Draft", match: (s) => s === "DRAFT" },
  { label: "In progress", match: isWorkingState },
  { label: "Awaiting approval", match: (s) => s === "AWAITING_APPROVAL" },
  { label: "Ready", match: (s) => s === "READY" },
  { label: "Delivered", match: (s) => s === "DELIVERED" },
  { label: "Needs attention", match: (s) => isExceptionState(s) && s !== "CANCELLED" },
];

export function countByState(productions: readonly ProductionSummary[]): Partial<Record<ProductionState, number>> {
  const counts: Partial<Record<ProductionState, number>> = {};
  for (const p of productions) counts[p.state] = (counts[p.state] ?? 0) + 1;
  return counts;
}

function HealthCard() {
  const { data, level, error } = useHealth();
  return (
    <Card title="API health" description="Polled every 15 seconds">
      <div className="flex items-center gap-3">
        <HealthDot level={level} className="h-3 w-3" />
        <span className="text-lg font-semibold capitalize text-zinc-100">
          {level === "checking" ? "Checking…" : level}
        </span>
        {data && (
          <span className="text-xs text-zinc-500">
            {data.service ?? "cineforge-api"} {data.version} · {data.environment}
          </span>
        )}
      </div>
      {data?.checks && data.checks.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {data.checks.map((check) => (
            <li key={check.name} className="flex items-center justify-between gap-3 text-sm">
              <span className="flex items-center gap-2 text-zinc-300">
                <HealthDot level={check.status} /> {humanize(check.name)}
              </span>
              <span className="truncate text-xs text-zinc-500" title={check.detail}>
                {check.detail || check.status}
              </span>
            </li>
          ))}
        </ul>
      )}
      {data && (
        <p className="mt-4 text-xs text-zinc-500">
          Paid providers{" "}
          {data.paid_providers_enabled ? (
            <Badge tone="danger">enabled</Badge>
          ) : (
            <Badge tone="success">disabled</Badge>
          )}
        </p>
      )}
      {!data && level === "down" && (
        <p className="mt-3 text-sm text-zinc-400">{errorMessage(error)}</p>
      )}
    </Card>
  );
}

export function OverviewPage() {
  const router = useRouter();
  const productions = useResource("productions", () => api.listProductions());
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);

  async function createSample() {
    setCreating(true);
    try {
      const detail = await api.createProduction(SAMPLE_PRODUCTION);
      router.push(`/productions/${encodeURIComponent(detail.summary.id)}`);
    } catch (err) {
      setNotice({
        variant: "error",
        title: "Could not create the sample production",
        message: errorMessage(err),
      });
      setCreating(false);
    }
  }

  const list = productions.data ?? [];
  const totalActual = list.reduce((sum, p) => sum + p.actual_cost, 0);

  return (
    <>
      <PageHeader
        title="Overview"
        description="Ten logical agents turn a theme and a topic into a cinematic vertical short, under a hard budget."
        actions={
          <Button variant="primary" onClick={() => void createSample()} busy={creating}>
            <IconSpark size={15} /> Create sample production
          </Button>
        }
      />
      <p className="-mt-3 mb-6 text-xs text-zinc-500">
        Sample: Time Traveler · &ldquo;{SAMPLE_PRODUCTION.topic}&rdquo; · balanced · auto-approve off
      </p>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-6">
          <Card title="Productions by state" actions={<SimulatedBadge />}>
            {productions.loading ? (
              <Loading rows={2} />
            ) : !productions.data ? (
              <ErrorState error={productions.error} onRetry={() => void productions.reload()} />
            ) : (
              <dl className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
                <Stat label="Total" value={list.length} hint={`${formatUsd(totalActual)} actual spend`} />
                {GROUPS.map((group) => (
                  <Stat
                    key={group.label}
                    label={group.label}
                    value={list.filter((p) => group.match(p.state)).length}
                  />
                ))}
              </dl>
            )}
          </Card>

          <Card
            title="Recent productions"
            actions={
              <Link href="/productions" className="text-xs text-sky-300 hover:underline">
                View all
              </Link>
            }
          >
            {productions.loading ? (
              <Loading rows={4} />
            ) : !productions.data ? (
              <p className="text-sm text-zinc-500">Productions will appear here once the API is reachable.</p>
            ) : list.length === 0 ? (
              <EmptyState title="No productions yet">Use &ldquo;Create sample production&rdquo; to start a demo.</EmptyState>
            ) : (
              <ProductionsTable productions={list.slice(0, 5)} compact />
            )}
          </Card>
        </div>
        <HealthCard />
      </div>

      <AppNoticeDialog
        open={notice !== null}
        variant={notice?.variant}
        title={notice?.title ?? ""}
        message={notice?.message}
        onClose={() => setNotice(null)}
      />
    </>
  );
}
