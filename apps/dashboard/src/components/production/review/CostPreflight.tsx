import { AGENT_DEFINITIONS, type CostEstimate, type CostSummary, type Scene } from "@cineforge/schemas";
import { formatUsd, humanize, ratioPct } from "@/lib/format";
import { IconAlert } from "../../icons";
import { Badge, Card, cx, Stat } from "../../ui";

interface BarRow {
  key: string;
  label: string;
  value: number;
}

function Bars({ title, rows, scale, limit }: { title: string; rows: BarRow[]; scale: number; limit: number }) {
  if (rows.length === 0) return null;
  const limitPct = ratioPct(limit, scale);
  return (
    <section aria-label={title}>
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">{title}</h3>
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row.key} data-testid="preflight-bar" className="text-xs">
            <div className="flex justify-between gap-2">
              <span className="truncate text-zinc-300">{row.label}</span>
              <span className="tabular-nums text-zinc-100">{formatUsd(row.value)}</span>
            </div>
            <div
              role="img"
              aria-label={`${row.label}: ${formatUsd(row.value)} of ${formatUsd(limit)} budget`}
              className="relative mt-1 h-1.5 overflow-hidden rounded-full bg-white/[0.05]"
            >
              <span
                className={cx("absolute inset-y-0 left-0 rounded-full", row.value > limit ? "bg-rose-400/80" : "bg-gold-500/70")}
                style={{ width: `${ratioPct(row.value, scale)}%` }}
              />
              {limitPct < 100 && (
                <span aria-hidden="true" className="absolute inset-y-0 w-px bg-zinc-100/50" style={{ left: `${limitPct}%` }} />
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

const AGENT_LABELS = new Map(AGENT_DEFINITIONS.map((a) => [a.id as string, `${a.code} ${a.name}`]));

export function CostPreflight({
  estimate,
  limit,
  scenes = [],
  cost,
}: {
  estimate: CostEstimate;
  limit: number;
  scenes?: readonly Scene[];
  cost: CostSummary;
}) {
  const total = estimate.total_estimated;
  const over = total > limit;
  const scale = Math.max(limit, total, ...Object.values(estimate.by_scene ?? {}), ...Object.values(estimate.by_agent ?? {}));
  const sceneLabels = new Map(scenes.map((s) => [s.id, `S${s.order} ${s.title || humanize(s.story_beat)}`]));
  const sceneRows: BarRow[] = Object.entries(estimate.by_scene ?? {}).map(([key, value]) => ({
    key,
    label: sceneLabels.get(key) ?? key,
    value,
  }));
  const agentRows: BarRow[] = Object.entries(estimate.by_agent ?? {})
    .map(([key, value]) => ({ key, label: AGENT_LABELS.get(key) ?? humanize(key), value }))
    .sort((a, b) => b.value - a.value);
  const simulated = cost.simulated !== false;
  const spent = cost.actual ?? 0;

  return (
    <Card
      id="cost-preflight"
      title="Cost preflight"
      description={`Estimate from price catalog ${estimate.price_catalog_version} · ${humanize(estimate.mode)} mode`}
      actions={over ? <Badge tone="danger">Over budget</Badge> : <Badge tone="success">Within budget</Badge>}
    >
      {over && (
        <p
          role="alert"
          data-testid="over-budget"
          className="mb-4 flex items-start gap-2 rounded-lg border border-rose-500/25 bg-rose-500/[0.07] px-3 py-2 text-sm text-rose-200"
        >
          <IconAlert size={15} className="mt-0.5 shrink-0" />
          Estimate {formatUsd(total)} exceeds the {formatUsd(limit)} budget by {formatUsd(total - limit)}. Raise the budget
          to approve.
        </p>
      )}
      <dl className="grid grid-cols-2 gap-2.5">
        <Stat label="Estimated total" value={formatUsd(total)} hint={`${formatUsd(limit)} limit`} />
        <Stat label="Budget used" value={`${Math.round(limit > 0 ? (total / limit) * 100 : 0)}%`} />
        <Stat
          label="Simulated costs"
          value={formatUsd(simulated ? spent : 0)}
          hint="Mock providers, no real money"
        />
        <Stat label="Real spend so far" value={formatUsd(simulated ? 0 : spent)} hint="Paid providers" />
      </dl>
      <div className="mt-4">
        <div
          role="img"
          aria-label={`Estimate ${formatUsd(total)} against ${formatUsd(limit)} limit`}
          className="relative h-3 overflow-hidden rounded-full bg-white/[0.06]"
        >
          <span
            className={cx(
              "absolute inset-y-0 left-0 rounded-full bg-gradient-to-r",
              over ? "from-rose-600 to-rose-400" : "from-gold-600 to-gold-300",
            )}
            style={{ width: `${ratioPct(total, scale)}%` }}
          />
          <span aria-hidden="true" className="absolute inset-y-0 w-0.5 bg-zinc-100/80" style={{ left: `calc(${ratioPct(limit, scale)}% - 1px)` }} />
        </div>
        <p className="mt-1 text-[11px] text-zinc-500">White marker = budget limit</p>
      </div>
      <div className="mt-5 space-y-5">
        <Bars title="By scene" rows={sceneRows} scale={scale} limit={limit} />
        <Bars title="By agent" rows={agentRows} scale={scale} limit={limit} />
      </div>
    </Card>
  );
}
