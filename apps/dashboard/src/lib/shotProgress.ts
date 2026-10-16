import type { Shot } from "@cineforge/schemas";

export type StageProgress = "complete" | "active" | "pending" | "failed" | "skipped";

export interface ShotStage {
  id: "still" | "voice" | "clip";
  label: string;
  state: StageProgress;
}

export interface ShotProgress {
  overall: StageProgress;
  /** Generative stage dots when the shot has a stages map; otherwise empty. */
  stages: ShotStage[];
  label: string;
}

type StageRecord = { done?: boolean; stale?: boolean; attempt?: number };

function stagesMap(shot: Shot): Record<string, StageRecord> | null {
  const raw = shot.provider_plan?.parameters?.stages;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  return raw as Record<string, StageRecord>;
}

function stageState(record: StageRecord | undefined, failed: boolean): StageProgress {
  if (record?.done && !record.stale) return "complete";
  if (failed) return "failed";
  if (record && (record.attempt ?? 0) > 0 && !record.done) return "active";
  return "pending";
}

function shotHasFailedAttempt(shot: Shot, stageId: string): boolean {
  return (shot.attempts ?? []).some(
    (a) => a.status === "failed" && (a.error?.includes(`${stageId}:`) || a.error?.startsWith(stageId)),
  );
}

function fromWorkStatus(status: Shot["status"] | undefined): StageProgress {
  switch (status) {
    case "complete":
    case "approved":
      return "complete";
    case "in_progress":
    case "queued":
      return "active";
    case "failed":
    case "needs_repair":
      return "failed";
    case "skipped":
      return "skipped";
    default:
      return "pending";
  }
}

function overallOf(stages: readonly ShotStage[]): StageProgress {
  const needed = stages.filter((s) => s.state !== "skipped");
  if (needed.some((s) => s.state === "failed")) return "failed";
  if (needed.some((s) => s.state === "active")) return "active";
  if (needed.length > 0 && needed.every((s) => s.state === "complete")) return "complete";
  if (needed.some((s) => s.state === "complete")) return "active"; // partial progress
  return "pending";
}

const LABELS: Record<StageProgress, string> = {
  complete: "Complete",
  active: "In progress",
  pending: "Not started",
  failed: "Failed",
  skipped: "Skipped",
};

/**
 * Storyboard progress for one shot.
 * Generative (vlog) shots use still / voice / clip stages; classic shots use ``shot.status``.
 */
export function shotProgress(shot: Shot): ShotProgress {
  const map = stagesMap(shot);
  if (map) {
    const needsVoice = Boolean(shot.audio?.dialogue_text);
    const stages: ShotStage[] = [
      {
        id: "still",
        label: "Still",
        state: stageState(map.still, shotHasFailedAttempt(shot, "still") && !map.still?.done),
      },
      {
        id: "voice",
        label: "Voice",
        state: needsVoice
          ? stageState(map.voice, shotHasFailedAttempt(shot, "voice") && !map.voice?.done)
          : "skipped",
      },
      {
        id: "clip",
        label: "Clip",
        state: stageState(map.clip, shotHasFailedAttempt(shot, "clip") && !map.clip?.done),
      },
    ];
    const overall = overallOf(stages);
    return { overall, stages, label: LABELS[overall] };
  }

  const overall = fromWorkStatus(shot.status);
  return { overall, stages: [], label: LABELS[overall] };
}
