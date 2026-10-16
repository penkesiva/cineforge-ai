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

/** Finished demo / sample rows we usually hide from the Debug page. */
const NOISE_TITLE = /^e2e\b/i;

export const DEBUG_CLEARED_AT_KEY = "cineforge.debug.clearedAt";

export interface DebugIssue {
  production_id: string;
  title: string;
  state: string;
  approval_stage?: string | null;
  kind: "event" | "agent_run" | "shot_attempt" | "summary";
  when?: string;
  summary: string;
  detail?: string;
  /** Shot id when the issue is about one shot (for resolved filtering). */
  shot_id?: string;
}

export interface DebugLogBundle {
  generated_at: string;
  production_count: number;
  inspected: number;
  issue_count: number;
  issues: DebugIssue[];
  text: string;
  cleared_at?: string | null;
}

export interface DebugLogOptions {
  /** Only inspect stuck / failed productions (default true). */
  activeOnly?: boolean;
  /** Drop issues at or before this ISO timestamp (Clear button). */
  since?: string | null;
  limit?: number;
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

function shotClipDone(manifest: ProductionManifest, shotId: string): boolean {
  for (const scene of manifest.scenes ?? []) {
    for (const shot of scene.shots ?? []) {
      if (shot.id !== shotId) continue;
      const stages = (shot.provider_plan?.parameters?.stages ?? {}) as Record<
        string,
        { done?: boolean; stale?: boolean }
      >;
      return Boolean(stages.clip?.done) && !stages.clip?.stale;
    }
  }
  return false;
}

function shotIdFromText(text: string | undefined): string | undefined {
  if (!text) return undefined;
  const match = text.match(/\b(scene_\d+_shot_\d+)\b/);
  return match?.[1];
}

function latestRecoveryAt(events: readonly ProductionEvent[]): number {
  let latest = 0;
  for (const event of events) {
    if (event.event_type !== "stage_ready" && event.to_state !== "READY" && event.to_state !== "DELIVERED") {
      continue;
    }
    const t = event.created_at ? Date.parse(event.created_at) : 0;
    if (t > latest) latest = t;
  }
  return latest;
}

function shotAttemptIssues(manifest: ProductionManifest, summary: ProductionSummary): DebugIssue[] {
  const out: DebugIssue[] = [];
  for (const scene of manifest.scenes ?? []) {
    for (const shot of scene.shots ?? []) {
      if (shotClipDone(manifest, shot.id)) continue; // old failed attempts are resolved
      for (const attempt of shot.attempts ?? []) {
        if (attempt.status !== "failed" && !attempt.error) continue;
        out.push({
          production_id: summary.id,
          title: titleOf(summary),
          state: summary.state,
          approval_stage: summary.approval_stage,
          kind: "shot_attempt",
          shot_id: shot.id,
          when: attempt.at ?? undefined,
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
      shot_id: shotIdFromText(run.error ?? undefined),
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
    shot_id: shotIdFromText(event.message),
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
 * Drop resolved / stale noise so Approve-again retries don't bury the truth.
 * - Skip finished productions when ``activeOnly``.
 * - Skip failures that happened before the latest ``stage_ready``.
 * - Skip shot issues once that shot's clip is done.
 * - Honor a Clear watermark (``since``).
 */
export function filterOpenIssues(
  details: readonly ProductionDetail[],
  issues: readonly DebugIssue[],
  options: DebugLogOptions = {},
): DebugIssue[] {
  const activeOnly = options.activeOnly !== false;
  const sinceMs = options.since ? Date.parse(options.since) : 0;
  const byId = new Map(details.map((d) => [d.summary.id, d]));

  return issues.filter((issue) => {
    if (sinceMs && issue.when && Date.parse(issue.when) <= sinceMs) return false;

    const detail = byId.get(issue.production_id);
    if (!detail) return true;

    const { summary, events, manifest } = detail;
    if (activeOnly) {
      if (!PROBLEM_STATES.has(summary.state)) return false;
      if (NOISE_TITLE.test(titleOf(summary))) return false;
    }

    if (issue.shot_id && shotClipDone(manifest, issue.shot_id)) return false;

    const recoveredAt = latestRecoveryAt(events ?? []);
    if (recoveredAt && issue.when && Date.parse(issue.when) <= recoveredAt) return false;

    return true;
  });
}

/**
 * Prefer stuck / failed productions, then the most recently updated ones.
 * Caps how many details we fetch so the Debug page stays snappy.
 */
export function selectProductionsToInspect(
  summaries: readonly ProductionSummary[],
  limit = 20,
  activeOnly = true,
): ProductionSummary[] {
  const sorted = [...summaries].sort(
    (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at) || a.id.localeCompare(b.id),
  );
  const pool = activeOnly
    ? sorted.filter((s) => PROBLEM_STATES.has(s.state) && !NOISE_TITLE.test(titleOf(s)))
    : sorted;
  const picked: ProductionSummary[] = [];
  const seen = new Set<string>();
  for (const row of pool) {
    if (seen.has(row.id)) continue;
    seen.add(row.id);
    picked.push(row);
    if (picked.length >= limit) break;
  }
  // If nothing is stuck, still show the newest few so the page is not empty.
  if (picked.length === 0) {
    for (const row of sorted) {
      if (seen.has(row.id)) continue;
      seen.add(row.id);
      picked.push(row);
      if (picked.length >= Math.min(5, limit)) break;
    }
  }
  return picked;
}

export function formatDebugLog(input: {
  generated_at?: string;
  production_count: number;
  inspected: number;
  issues: readonly DebugIssue[];
  cleared_at?: string | null;
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
  ];
  if (input.cleared_at) lines.push(`cleared_at: ${input.cleared_at} (older issues hidden)`);
  lines.push("");

  if (issues.length === 0) {
    lines.push("No open failures in the inspected productions.");
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
    cleared_at: input.cleared_at ?? null,
    text: lines.join("\n").trimEnd() + "\n",
  };
}

export async function buildDebugLog(
  listProductions: () => Promise<ProductionSummary[]>,
  getProduction: (id: string) => Promise<ProductionDetail>,
  options: DebugLogOptions = {},
): Promise<DebugLogBundle> {
  const activeOnly = options.activeOnly !== false;
  const limit = options.limit ?? 20;
  const summaries = await listProductions();
  const selected = selectProductionsToInspect(summaries, limit, activeOnly);
  const details = await Promise.all(selected.map((s) => getProduction(s.id)));
  const raw = details.flatMap(collectProductionIssues);
  const issues = filterOpenIssues(details, raw, options);
  return formatDebugLog({
    production_count: summaries.length,
    inspected: details.length,
    issues,
    cleared_at: options.since ?? null,
  });
}

export function readClearedAt(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(DEBUG_CLEARED_AT_KEY);
  } catch {
    return null;
  }
}

export function writeClearedAt(iso: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (iso) window.localStorage.setItem(DEBUG_CLEARED_AT_KEY, iso);
    else window.localStorage.removeItem(DEBUG_CLEARED_AT_KEY);
  } catch {
    /* private mode */
  }
}
