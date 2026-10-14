import type { ProductionSummary } from "@cineforge/schemas";
import Link from "next/link";
import { formatRelative, formatUsd, humanize } from "@/lib/format";
import { isExceptionState } from "@/lib/workflow";
import { ProgressBar, StateBadge } from "../ui";

export function ProductionsTable({
  productions,
  compact = false,
}: {
  productions: readonly ProductionSummary[];
  compact?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <caption className="sr-only">Productions</caption>
        <thead className="text-[11px] uppercase tracking-wider text-zinc-500">
          <tr>
            <th scope="col" className="pb-2 pr-4 font-medium">Production</th>
            {!compact && (
              <>
                <th scope="col" className="pb-2 pr-4 font-medium">Theme</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Mode</th>
              </>
            )}
            <th scope="col" className="pb-2 pr-4 font-medium">State</th>
            <th scope="col" className="w-36 pb-2 pr-4 font-medium">Progress</th>
            <th scope="col" className="pb-2 pr-4 text-right font-medium">Est / actual</th>
            <th scope="col" className="pb-2 text-right font-medium">Updated</th>
          </tr>
        </thead>
        <tbody>
          {productions.map((p) => (
            <tr key={p.id} className="group border-t border-white/[0.05] align-middle transition hover:bg-white/[0.02]">
              <td className="max-w-[340px] py-3 pr-4">
                <Link
                  href={`/productions/${encodeURIComponent(p.id)}`}
                  className="block font-medium text-zinc-100 group-hover:text-gold-300"
                >
                  {p.title || "Untitled production"}
                </Link>
                <span className="block truncate text-xs text-zinc-500" title={p.topic}>
                  {p.topic}
                </span>
              </td>
              {!compact && (
                <>
                  <td className="py-3 pr-4 text-zinc-300">{humanize(p.theme_id)}</td>
                  <td className="py-3 pr-4 text-zinc-400">{humanize(p.mode)}</td>
                </>
              )}
              <td className="py-3 pr-4">
                <StateBadge state={p.state} />
              </td>
              <td className="py-3 pr-4">
                <ProgressBar
                  value={p.progress_pct}
                  label={`${p.title || p.topic} progress`}
                  tone={isExceptionState(p.state) ? "rose" : p.state === "DELIVERED" ? "emerald" : "gold"}
                />
                <span className="mt-1 block text-[11px] tabular-nums text-zinc-500">{p.progress_pct}%</span>
              </td>
              <td className="py-3 pr-4 text-right tabular-nums">
                <span className="text-zinc-500">{formatUsd(p.estimated_cost)}</span>
                <span className="block text-zinc-100">{formatUsd(p.actual_cost)}</span>
              </td>
              <td className="py-3 text-right text-xs text-zinc-500">{formatRelative(p.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
