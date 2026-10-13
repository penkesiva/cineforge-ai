"use client";

import { AGENT_DEFINITIONS, type AgentDefinition } from "@cineforge/schemas";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { IconInfo } from "../icons";
import { Badge, Mono, PageHeader } from "../ui";

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{label}</dt>
      <dd className="flex flex-wrap gap-1">{children}</dd>
    </div>
  );
}

export function AgentCard({ agent }: { agent: AgentDefinition }) {
  return (
    <article
      data-testid="agent-card"
      aria-labelledby={`agent-${agent.id}`}
      className="flex flex-col rounded-2xl border border-white/[0.07] bg-ink-900/80 p-5 transition hover:border-gold-500/25"
    >
      <header className="mb-3 flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-gold-400/20 to-gold-600/5 font-mono text-sm font-semibold text-gold-300 ring-1 ring-gold-500/25">
          {agent.code}
        </span>
        <div className="min-w-0">
          <h2 id={`agent-${agent.id}`} className="text-sm font-semibold text-zinc-50">
            {agent.name}
          </h2>
          <p className="mt-0.5 text-xs leading-relaxed text-zinc-400">{agent.responsibility}</p>
        </div>
      </header>
      <dl className="grid gap-3 text-xs">
        <Section label="Outputs">
          {agent.outputs.map((o) => (
            <Badge key={o} tone="gold">
              {o}
            </Badge>
          ))}
        </Section>
        <Section label="Key checks">
          {agent.key_checks.map((c) => (
            <Badge key={c}>{c}</Badge>
          ))}
        </Section>
        <Section label="Workflow states">
          {agent.workflow_states.map((s) => (
            <Badge key={s} tone="info">
              {humanize(s)}
            </Badge>
          ))}
        </Section>
        <Section label="Capabilities">
          {agent.capabilities.length === 0 ? (
            <span className="text-zinc-500">Deterministic (no provider calls)</span>
          ) : (
            agent.capabilities.map((c) => (
              <Badge key={c} tone="violet">
                {humanize(c)}
              </Badge>
            ))
          )}
        </Section>
      </dl>
      <p className="mt-4 border-t border-white/[0.05] pt-3 text-[11px] text-zinc-500">
        <Mono>{agent.input_model}</Mono> → <Mono>{agent.output_model}</Mono>
        <span className="block">
          prompt <Mono>{agent.prompt_template_id}@{agent.prompt_template_version ?? 1}</Mono>
        </span>
      </p>
    </article>
  );
}

export function AgentsRegistry() {
  const { data, error, loading } = useResource("agents", () => api.listAgents());
  const agents = data ?? AGENT_DEFINITIONS;
  const fallback = !data && !loading && error !== undefined;
  return (
    <>
      <PageHeader
        title="Agents"
        description="Ten logical agents (roles, not containers). Agents make creative decisions through typed artifacts; deterministic code handles budgets, rights and state."
        actions={<Badge tone={fallback ? "warning" : "neutral"}>{agents.length} agents</Badge>}
      />
      {fallback && (
        <p
          role="status"
          className="mb-5 flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-3 py-2 text-sm text-amber-200"
        >
          <IconInfo size={15} /> API unavailable. Showing the built-in registry from the shared contracts.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {agents.map((agent) => (
          <AgentCard key={agent.id} agent={agent} />
        ))}
      </div>
    </>
  );
}
