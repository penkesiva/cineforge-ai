"use client";

import { api } from "@/lib/api";
import { formatDateTime, formatPct, formatUsd, humanize } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { BreakdownTable } from "../production/CostPanel";
import { Badge, Card, EmptyState, ErrorState, Loading, Mono, PageHeader, SimulatedBadge, Stat } from "../ui";

function OverviewCard() {
  const { data, error, loading, reload } = useResource("cost-overview", () => api.getCostOverview());
  return (
    <Card title="Tenant spend" actions={data?.simulated !== false ? <SimulatedBadge /> : undefined}>
      {loading ? (
        <Loading rows={4} />
      ) : !data ? (
        <ErrorState error={error} onRetry={() => void reload()} />
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Productions" value={data.production_count ?? 0} />
            <Stat label="Total limit" value={formatUsd(data.total_limit ?? 0)} />
            <Stat label="Estimated" value={formatUsd(data.total_estimated ?? 0)} />
            <Stat label="Reserved" value={formatUsd(data.total_reserved ?? 0)} />
            <Stat label="Actual" value={formatUsd(data.total_actual ?? 0)} />
            <Stat label="Retries" value={data.retry_count ?? 0} />
          </dl>
          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            <BreakdownTable title="By production" rows={data.by_production} />
            <BreakdownTable title="By provider" rows={data.by_provider} />
            <BreakdownTable title="By agent" rows={data.by_agent} />
          </div>
          {!data.by_production?.length && !data.by_provider?.length && !data.by_agent?.length && (
            <EmptyState title="No spend recorded yet" />
          )}
          {data.credit_balances && data.credit_balances.length > 0 && (
            <div className="mt-6">
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Provider credit balances
              </h3>
              <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {data.credit_balances.map((b) => (
                  <li key={b.provider} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                    <p className="text-xs text-zinc-500">{b.provider}</p>
                    <p className="text-sm font-semibold tabular-nums text-zinc-100">
                      {b.balance} {b.unit ?? "credits"}
                      {b.is_estimated && <span className="ml-1 text-[11px] font-normal text-zinc-500">(est.)</span>}
                    </p>
                    {b.updated_at && <p className="text-[11px] text-zinc-600">{formatDateTime(b.updated_at)}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function PricingCard() {
  const { data, error, loading, reload } = useResource("pricing", () => api.listPricing());
  return (
    <Card title="Price catalog" description={data?.[0] ? `Version ${data[0].version}` : undefined}>
      {loading ? (
        <Loading rows={5} />
      ) : !data ? (
        <ErrorState error={error} onRetry={() => void reload()} />
      ) : data.length === 0 ? (
        <EmptyState title="No prices loaded" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <caption className="sr-only">Provider price catalog</caption>
            <thead className="text-[11px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th scope="col" className="pb-2 pr-4 font-medium">Provider</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Model</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Capability</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Unit</th>
                <th scope="col" className="pb-2 pr-4 text-right font-medium">Unit price</th>
                <th scope="col" className="pb-2 font-medium">Version</th>
              </tr>
            </thead>
            <tbody>
              {data.map((entry) => (
                <tr key={`${entry.provider}/${entry.model}/${entry.capability}/${entry.unit}`} className="border-t border-white/[0.05]">
                  <td className="py-2 pr-4 text-zinc-200">{entry.provider}</td>
                  <td className="py-2 pr-4">
                    <Mono>{entry.model}</Mono>
                  </td>
                  <td className="py-2 pr-4">
                    <Badge tone="violet">{humanize(entry.capability)}</Badge>
                  </td>
                  <td className="py-2 pr-4 text-zinc-400">{entry.unit.replace(/_/g, " ")}</td>
                  <td className="py-2 pr-4 text-right tabular-nums text-zinc-100">{formatUsd(entry.unit_price)}</td>
                  <td className="py-2 text-xs text-zinc-500">{entry.version}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ModesCard() {
  const { data, error, loading, reload } = useResource("modes", () => api.listModes());
  return (
    <Card title="Production modes" description="Budget and quality policies applied per production">
      {loading ? (
        <Loading rows={3} />
      ) : !data ? (
        <ErrorState error={error} onRetry={() => void reload()} />
      ) : (
        <div className="grid gap-3 md:grid-cols-3">
          {data.map((mode) => (
            <article key={mode.mode} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
              <header className="flex items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold text-zinc-50">{humanize(mode.mode)}</h3>
                <span className="text-lg font-semibold tabular-nums text-gold-300">
                  {formatUsd(mode.default_budget_usd)}
                </span>
              </header>
              <p className="mt-1 text-xs text-zinc-400">{mode.description}</p>
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <dt className="text-zinc-500">Max attempts/shot</dt>
                <dd className="text-right tabular-nums text-zinc-200">{mode.max_attempts_per_shot}</dd>
                <dt className="text-zinc-500">Expected retries</dt>
                <dd className="text-right tabular-nums text-zinc-200">{formatPct(mode.expected_retry_rate * 100)}</dd>
                <dt className="text-zinc-500">Generative shots</dt>
                <dd className="text-right tabular-nums text-zinc-200">{formatPct(mode.generative_shot_ratio * 100)}</dd>
                <dt className="text-zinc-500">Quality tier</dt>
                <dd className="text-right text-zinc-200">{humanize(mode.quality_tier)}</dd>
                <dt className="text-zinc-500">Draft first</dt>
                <dd className="text-right text-zinc-200">{mode.draft_first ? "Yes" : "No"}</dd>
              </dl>
              <div className="mt-3 flex flex-wrap gap-1">
                {mode.allowed_strategies.map((s) => (
                  <Badge key={s}>{humanize(s)}</Badge>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </Card>
  );
}

export function CostsPage() {
  return (
    <>
      <PageHeader
        title="Costs"
        description="Every provider call reserves budget before it runs and commits actual spend to the ledger afterwards."
        actions={<SimulatedBadge />}
      />
      <div className="space-y-6">
        <OverviewCard />
        <ModesCard />
        <PricingCard />
      </div>
    </>
  );
}
