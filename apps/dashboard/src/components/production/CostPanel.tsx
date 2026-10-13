import type { CostBreakdownRow, CostSummary } from "@cineforge/schemas";
import { formatUsd, ratioPct } from "@/lib/format";
import { Card, SimulatedBadge, Stat } from "../ui";

export function costRemaining(cost: CostSummary): number {
  if (typeof cost.remaining === "number") return cost.remaining;
  return Math.max(0, cost.limit - (cost.reserved ?? 0) - (cost.actual ?? 0));
}

export function BudgetBar({
  limit,
  actual,
  reserved,
  estimated,
}: {
  limit: number;
  actual: number;
  reserved: number;
  estimated: number;
}) {
  const actualPct = ratioPct(actual, limit);
  const reservedPct = Math.min(100 - actualPct, ratioPct(reserved, limit));
  const estimatedPct = ratioPct(estimated, limit);
  const over = estimated > limit;
  return (
    <div>
      <div
        role="img"
        aria-label={`Budget usage: ${formatUsd(actual)} actual and ${formatUsd(reserved)} reserved of ${formatUsd(limit)} limit; estimate ${formatUsd(estimated)}`}
        className="relative h-3 w-full overflow-hidden rounded-full bg-white/[0.06]"
      >
        <div
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-gold-600 to-gold-300 transition-[width] duration-700"
          style={{ width: `${actualPct}%` }}
        />
        <div
          className="bar-striped absolute inset-y-0 bg-sky-400/40 transition-all duration-700"
          style={{ left: `${actualPct}%`, width: `${reservedPct}%` }}
        />
        {estimated > 0 && (
          <div
            className={`absolute inset-y-0 w-0.5 ${over ? "bg-rose-400" : "bg-zinc-100/80"}`}
            style={{ left: `calc(${Math.min(estimatedPct, 100)}% - 1px)` }}
          />
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-gold-400" /> Actual
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-sky-400/60" /> Reserved
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className={`h-2.5 w-0.5 ${over ? "bg-rose-400" : "bg-zinc-100/80"}`} /> Estimate
          {over && <span className="text-rose-300">(over limit)</span>}
        </span>
      </div>
    </div>
  );
}

export function BreakdownTable({
  title,
  rows,
  total,
}: {
  title: string;
  rows: readonly CostBreakdownRow[] | undefined;
  total?: number;
}) {
  if (!rows || rows.length === 0) return null;
  const max = Math.max(total ?? 0, ...rows.map((r) => Math.max(r.actual ?? 0, r.estimated ?? 0)));
  return (
    <div>
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">{title}</h3>
      <table className="w-full text-left text-xs">
        <caption className="sr-only">{title}</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Item</th>
            <th scope="col">Estimated</th>
            <th scope="col">Actual</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-t border-white/[0.04]">
              <th scope="row" className="py-1.5 pr-2 font-normal text-zinc-300">
                <span className="block truncate">{row.label || row.key}</span>
                <span className="mt-1 block h-1 overflow-hidden rounded-full bg-white/[0.05]">
                  <span
                    className="block h-full rounded-full bg-gold-500/70"
                    style={{ width: `${ratioPct(row.actual ?? 0, max)}%` }}
                  />
                </span>
              </th>
              <td className="py-1.5 pr-2 text-right tabular-nums text-zinc-500">{formatUsd(row.estimated ?? 0)}</td>
              <td className="py-1.5 text-right tabular-nums text-zinc-100">{formatUsd(row.actual ?? 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CostPanel({ cost }: { cost: CostSummary }) {
  const estimated = cost.estimated ?? 0;
  const reserved = cost.reserved ?? 0;
  const actual = cost.actual ?? 0;
  const remaining = costRemaining(cost);
  return (
    <Card
      id="costs"
      title="Costs"
      description={`${cost.event_count ?? 0} ledger events · ${cost.cache_hits ?? 0} cache hits`}
      actions={cost.simulated !== false ? <SimulatedBadge /> : undefined}
    >
      <dl className="grid grid-cols-2 gap-2.5">
        <Stat label="Limit" value={formatUsd(cost.limit)} />
        <Stat label="Estimated" value={formatUsd(estimated)} />
        <Stat label="Reserved" value={formatUsd(reserved)} />
        <Stat label="Actual" value={formatUsd(actual)} />
        <Stat label="Remaining" value={formatUsd(remaining)} />
        <Stat label="Retries" value={cost.retry_count ?? 0} />
      </dl>
      <div className="mt-4">
        <BudgetBar limit={cost.limit} actual={actual} reserved={reserved} estimated={estimated} />
      </div>
      <div className="mt-5 space-y-5">
        <BreakdownTable title="By scene" rows={cost.by_scene} />
        <BreakdownTable title="By agent" rows={cost.by_agent} />
        <BreakdownTable title="By provider" rows={cost.by_provider} />
      </div>
    </Card>
  );
}
