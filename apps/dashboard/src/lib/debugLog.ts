import type {
  AgentRun,
  ProductionDetail,
  ProductionEvent,
  ProductionManifest,
  ProductionSummary,
} from "@cineforge/schemas";

/** Events that mean something went wrong or the operator must act. */
const PROBLEM_EVENT =
  /fail|error|paused|blocked|stage_failed|budget_paused|approval_blocked|credit cap/i;

const PROBLEM_STATES = new Set([
  "FAILED",
  "PAUSED_BUDGET",
  "NEEDS_REVIEW",
  "AWAITING_APPROVAL",
]);

export interface DebugIssue {
  production_id: string;
  title: string;
  state: string;
  approval_stage?: string | null;
  kind: "event" | "agent_run" | "shot_attempt" | "summary";
  when?: string;
  summary: string;
  detail?: string;
}

export interface DebugLogBundle {
  generated_at: string;
  production_count: number;
  inspected: number;
  issue_count: number;
  issues: DebugIssue[];
  text: string;
}

function titleOf(summary: ProductionSummary): string {
  return summary.title?.trim() || summary.topic;
}

function isProblemEvent(event: ProductionEvent): boolean {
  if (PROBLEM_EVENT.test(event.event_type)) return true;
  if (event.message && PROBLEM_EVENT.test(event.message)) return true;
  if (event.to_state === "FAILED" || event.to_state === "PAUSED_BUDGET") return true;
  return false;
}

function shotAttemptIssues(manifest: ProductionManifest, summary: ProductionSummary): DebugIssue[] {
  const out: DebugIssue[] = [];
  for (const scene of manifest.scenes ?? []) {
    for (const shot of scene.shots ?? []) {
      for (const attempt of shot.attempts ?? []) {
        if (attempt.status !== "failed" && !attempt.error) continue;
        out.push({
          production_id: summary.id,
          title: titleOf(summary),
          state: summary.state,
          approval_stage: summary.approval_stage,
          kind: "shot_attempt",
          summary: `${shot.id} attempt ${attempt.attempt} (${attempt.provider}/${attempt.model}): ${attempt.status}`,
          detail: attempt.error ?? undefined,
        });
      }
    }
  }
  return out;
}

function agentRunIssues(runs: AgentRun[], summary: ProductionSummary): DebugIssue[] {
  return runs
    .filter((run) => run.status === "failed")
    .map((run) => ({
      production_id: summary.id,
      title: titleOf(summary),
      state: summary.state,
      approval_stage: summary.approval_stage,
      kind: "agent_run" as const,
      when: run.finished_at ?? run.started_at,
      summary: `${run.agent_id} @ ${run.step}: failed (attempt ${run.attempt ?? 1})`,
      detail: run.error ?? undefined,
    }));
}

function eventIssues(events: ProductionEvent[], summary: ProductionSummary): DebugIssue[] {
  return events.filter(isProblemEvent).map((event) => ({
    production_id: summary.id,
    title: titleOf(summary),
    state: summary.state,
    approval_stage: summary.approval_stage,
    kind: "event" as const,
    when: event.created_at,
    summary: `${event.event_type}${event.to_state ? ` → ${event.to_state}` : ""}`,
    detail: event.message || (event.payload ? JSON.stringify(event.payload) : undefined),
  }));
}

/** Pull every actionable failure from one production detail payload. */
export function collectProductionIssues(detail: ProductionDetail): DebugIssue[] {
  const { summary, events, agent_runs, manifest } = detail;
  const issues = [
    ...eventIssues(events ?? [], summary),
    ...agentRunIssues(agent_runs ?? [], summary),
    ...shotAttemptIssues(manifest, summary),
  ];
  if (summary.state === "FAILED" && issues.length === 0) {
    issues.push({
      production_id: summary.id,
      title: titleOf(summary),
      state: summary.state,
      approval_stage: summary.approval_stage,
      kind: "summary",
      when: summary.updated_at,
      summary: "Production is FAILED with no detailed error events",
    });
  }
  return issues;
}

/**
 * Prefer stuck / failed productions, then the most recently updated ones.
 * Caps how many details we fetch so the Debug page stays snappy.
 */
export function selectProductionsToInspect(
  summaries: readonly ProductionSummary[],
  limit = 20,
): ProductionSummary[] {
  const sorted = [...summaries].sort(
    (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at) || a.id.localeCompare(b.id),
  );
  const priority = sorted.filter((s) => PROBLEM_STATES.has(s.state) || s.state === "FAILED");
  const rest = sorted.filter((s) => !priority.includes(s));
  const picked: ProductionSummary[] = [];
  const seen = new Set<string>();
  for (const row of [...priority, ...rest]) {
    if (seen.has(row.id)) continue;
    seen.add(row.id);
    picked.push(row);
    if (picked.length >= limit) break;
  }
  return picked;
}

export function formatDebugLog(input: {
  generated_at?: string;
  production_count: number;
  inspected: number;
  issues: readonly DebugIssue[];
}): DebugLogBundle {
  const generated_at = input.generated_at ?? new Date().toISOString();
  const issues = [...input.issues].sort((a, b) => {
    const ta = a.when ? Date.parse(a.when) : 0;
    const tb = b.when ? Date.parse(b.when) : 0;
    return tb - ta || a.production_id.localeCompare(b.production_id);
  });

  const lines: string[] = [
    "CineForge debug log",
    `generated_at: ${generated_at}`,
    `productions: ${input.production_count} (inspected ${input.inspected})`,
    `issues: ${issues.length}`,
    "",
  ];

  if (issues.length === 0) {
    lines.push("No failures, pauses, or blocked approvals in the inspected productions.");
  } else {
    for (const issue of issues) {
      lines.push("────────────────────────────────────────");
      lines.push(`production: ${issue.production_id}`);
      lines.push(`title: ${issue.title}`);
      lines.push(
        `state: ${issue.state}${issue.approval_stage ? ` · stage ${issue.approval_stage}` : ""}`,
      );
      lines.push(`kind: ${issue.kind}`);
      if (issue.when) lines.push(`when: ${issue.when}`);
      lines.push(`summary: ${issue.summary}`);
      if (issue.detail) lines.push(`detail: ${issue.detail}`);
      lines.push("");
    }
  }

  return {
    generated_at,
    production_count: input.production_count,
    inspected: input.inspected,
    issue_count: issues.length,
    issues,
    text: lines.join("\n").trimEnd() + "\n",
  };
}

export async function buildDebugLog(
  listProductions: () => Promise<ProductionSummary[]>,
  getProduction: (id: string) => Promise<ProductionDetail>,
  limit = 20,
): Promise<DebugLogBundle> {
  const summaries = await listProductions();
  const selected = selectProductionsToInspect(summaries, limit);
  const details = await Promise.all(selected.map((s) => getProduction(s.id)));
  const issues = details.flatMap(collectProductionIssues);
  return formatDebugLog({
    production_count: summaries.length,
    inspected: details.length,
    issues,
  });
}
