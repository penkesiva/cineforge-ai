import type { LedgerEvent } from "@cineforge/schemas";
import { errorMessage } from "@/lib/api";
import { formatCredits, formatTime, formatUsd } from "@/lib/format";
import { Card, EmptyState, Loading, Mono, StatusBadge } from "../ui";
import { agentLabel } from "./AgentsPanel";

export interface LedgerPanelProps {
  events: readonly LedgerEvent[] | undefined;
  error?: unknown;
  loading?: boolean;
}

function LedgerRow({ event }: { event: LedgerEvent }) {
  const agent = agentLabel(event.agent_id);
  return (
    <tr data-testid="ledger-row" className="border-t border-white/[0.05] align-top">
      <td className="py-2 pr-3 text-xs tabular-nums text-zinc-500">{formatTime(event.timestamp)}</td>
      <td className="py-2 pr-3 text-zinc-300" title={agent.name}>
        {agent.code}
        {(event.attempt ?? 1) > 1 && <span className="ml-1 text-xs text-amber-300">try {event.attempt}</span>}
      </td>
      <td className="py-2 pr-3">
        <Mono>
          {event.provider}/{event.model}
        </Mono>
        {event.cache_hit && <span className="ml-1 text-[11px] text-sky-300">cache</span>}
      </td>
      <td className="py-2 pr-3">
        <StatusBadge status={event.status ?? "reserved"} />
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-zinc-500">{formatUsd(event.reserved_cost)}</td>
      <td className="py-2 pr-3 text-right tabular-nums text-zinc-100">{formatUsd(event.actual_cost ?? 0)}</td>
      <td data-testid="ledger-credits" className="py-2 text-right tabular-nums text-zinc-300">
        {formatCredits(event.credits_used)}
      </td>
    </tr>
  );
}

export function LedgerPanel({ events, error, loading = false }: LedgerPanelProps) {
  return (
    <Card
      id="ledger"
      title="Cost ledger"
      description={events ? `${events.length} ledger events` : "Every reservation and commit for this production"}
    >
      {!events ? (
        loading ? (
          <Loading label="Loading ledger…" rows={3} />
        ) : (
          <p className="text-sm text-rose-200/80">Could not load the ledger: {errorMessage(error)}</p>
        )
      ) : events.length === 0 ? (
        <EmptyState title="No ledger events yet">Provider calls reserve budget here before they run.</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <caption className="sr-only">Cost ledger events</caption>
            <thead className="text-[11px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th scope="col" className="pb-1.5 pr-3 font-medium">Time</th>
                <th scope="col" className="pb-1.5 pr-3 font-medium">Agent</th>
                <th scope="col" className="pb-1.5 pr-3 font-medium">Provider / model</th>
                <th scope="col" className="pb-1.5 pr-3 font-medium">Status</th>
                <th scope="col" className="pb-1.5 pr-3 text-right font-medium">Reserved</th>
                <th scope="col" className="pb-1.5 pr-3 text-right font-medium">Actual</th>
                <th scope="col" className="pb-1.5 text-right font-medium">Credits</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event, i) => (
                <LedgerRow key={event.event_id ?? `${event.idempotency_key}:${i}`} event={event} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
