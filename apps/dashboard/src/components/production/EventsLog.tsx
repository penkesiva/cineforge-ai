import type { ProductionEvent } from "@cineforge/schemas";
import { formatDateTime, humanize } from "@/lib/format";
import { Card, EmptyState, Mono } from "../ui";

function newestFirst(events: readonly ProductionEvent[]): ProductionEvent[] {
  return events
    .map((event, index) => ({ event, index }))
    .sort((a, b) => {
      const ta = a.event.created_at ? Date.parse(a.event.created_at) : 0;
      const tb = b.event.created_at ? Date.parse(b.event.created_at) : 0;
      return tb - ta || b.index - a.index;
    })
    .map(({ event }) => event);
}

export function EventsLog({ events }: { events: readonly ProductionEvent[] }) {
  const sorted = newestFirst(events);
  return (
    <Card id="events" title="Events" description={`${events.length} events, newest first`}>
      {sorted.length === 0 ? (
        <EmptyState title="No events yet" />
      ) : (
        <ol className="max-h-96 space-y-1 overflow-y-auto pr-1 text-sm" aria-label="Production events">
          {sorted.map((event, i) => (
            <li
              key={event.id ?? `${event.created_at}-${i}`}
              className="grid grid-cols-[150px_1fr] gap-3 border-t border-white/[0.04] py-1.5 first:border-t-0"
            >
              <time dateTime={event.created_at} className="text-xs tabular-nums text-zinc-500">
                {formatDateTime(event.created_at)}
              </time>
              <div className="min-w-0">
                <Mono className="text-zinc-400">{event.event_type}</Mono>
                {event.to_state && (
                  <span className="ml-2 text-xs text-zinc-500">
                    {event.from_state ? `${humanize(event.from_state)} → ` : ""}
                    <span className="text-zinc-300">{humanize(event.to_state)}</span>
                  </span>
                )}
                {event.message && <p className="text-zinc-300">{event.message}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
