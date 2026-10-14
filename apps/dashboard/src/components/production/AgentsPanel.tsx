import { AGENT_DEFINITIONS, type AgentDefinition, type AgentId, type AgentRun } from "@cineforge/schemas";
import { formatDuration, formatTime, formatUsd, humanize, secondsBetween } from "@/lib/format";
import { Card, cx, EmptyState, Mono, StatusBadge } from "../ui";

const AGENTS_BY_ID = new Map<AgentId, AgentDefinition>(AGENT_DEFINITIONS.map((a) => [a.id, a]));

export function agentLabel(id: AgentId): { code: string; name: string } {
  const def = AGENTS_BY_ID.get(id);
  return def ? { code: def.code, name: def.name } : { code: "?", name: humanize(id) };
}

function sortRuns(runs: readonly AgentRun[]): AgentRun[] {
  return [...runs].sort((a, b) => {
    const ta = a.started_at ? Date.parse(a.started_at) : 0;
    const tb = b.started_at ? Date.parse(b.started_at) : 0;
    return ta - tb;
  });
}

export function AgentsPanel({ runs }: { runs: readonly AgentRun[] }) {
  const sorted = sortRuns(runs);
  const runsByAgent = new Map<AgentId, AgentRun[]>();
  for (const run of runs) {
    runsByAgent.set(run.agent_id, [...(runsByAgent.get(run.agent_id) ?? []), run]);
  }
  return (
    <Card id="agents" title="Agents involved" description={`${runs.length} agent runs`}>
      <ul aria-label="Agent roster" className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {AGENT_DEFINITIONS.map((agent) => {
          const agentRuns = runsByAgent.get(agent.id) ?? [];
          const ran = agentRuns.length > 0;
          const failed = agentRuns.some((r) => r.status === "failed");
          return (
            <li
              key={agent.id}
              data-testid="agent-roster-item"
              data-ran={ran}
              title={agent.responsibility}
              className={cx(
                "rounded-lg border px-2.5 py-2 text-xs",
                ran
                  ? failed
                    ? "border-rose-500/30 bg-rose-500/[0.06]"
                    : "border-gold-500/25 bg-gold-500/[0.06]"
                  : "border-white/[0.06] bg-white/[0.01] opacity-60",
              )}
            >
              <span className="font-mono font-semibold text-gold-300">{agent.code}</span>
              <span className="block truncate text-zinc-300">{agent.name}</span>
              <span className="text-[10px] text-zinc-500">
                {ran ? `${agentRuns.length} run${agentRuns.length > 1 ? "s" : ""}` : "Not run yet"}
              </span>
            </li>
          );
        })}
      </ul>
      {sorted.length === 0 ? (
        <EmptyState title="No agent runs yet">Runs appear here as the orchestrator advances the workflow.</EmptyState>
      ) : (
        <ol aria-label="Agent run timeline" className="relative space-y-2 border-l border-white/[0.08] pl-4">
          {sorted.map((run) => {
            const { code, name } = agentLabel(run.agent_id);
            const duration = secondsBetween(run.started_at, run.finished_at);
            return (
              <li key={run.id} data-testid="agent-run" className="relative">
                <span
                  aria-hidden="true"
                  className={cx(
                    "absolute -left-[21px] top-3 h-2.5 w-2.5 rounded-full ring-4 ring-ink-900",
                    run.status === "succeeded"
                      ? "bg-emerald-400"
                      : run.status === "failed"
                        ? "bg-rose-400"
                        : run.status === "running"
                          ? "animate-pulse bg-sky-400"
                          : "bg-zinc-500",
                  )}
                />
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/[0.05] bg-white/[0.015] px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-sm text-zinc-100">
                      <span className="mr-1.5 font-mono font-semibold text-gold-300">{code}</span>
                      {name}
                      <span className="ml-2 text-xs text-zinc-500">
                        {humanize(run.step)} · attempt {run.attempt ?? 1}
                      </span>
                    </p>
                    <p className="mt-0.5 text-xs text-zinc-500">
                      {formatTime(run.started_at)} · {duration === null ? "running" : formatDuration(duration)}
                      {run.prompt_template_id && (
                        <>
                          {" · "}
                          <Mono>
                            {run.prompt_template_id}@{run.prompt_template_version ?? 1}
                          </Mono>
                        </>
                      )}
                      {run.output_model && <> · {run.output_model}</>}
                    </p>
                    {run.error && <p className="mt-1 text-xs text-rose-300">{run.error}</p>}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm tabular-nums text-zinc-200">{formatUsd(run.actual_cost ?? 0)}</span>
                    <StatusBadge status={run.status} />
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
