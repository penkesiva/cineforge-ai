import { shotProgress, type StageProgress } from "@/lib/shotProgress";
import type { Shot } from "@cineforge/schemas";
import { cx } from "../ui";

const DOT: Record<Exclude<StageProgress, "skipped">, string> = {
  complete: "bg-emerald-400",
  active: "animate-[status-blink_1.1s_ease-in-out_infinite] bg-sky-400",
  pending: "bg-zinc-600 ring-1 ring-inset ring-zinc-500/50",
  failed: "bg-rose-400",
};

export function StatusDot({
  state,
  label,
  title,
  testId = "status-dot",
}: {
  state: StageProgress;
  label?: string;
  title?: string;
  testId?: string;
}) {
  if (state === "skipped") return null;
  return (
    <span
      data-testid={testId}
      data-state={state}
      title={title ?? label}
      aria-label={title ?? label}
      className="inline-flex items-center gap-1"
    >
      <span aria-hidden="true" className={cx("inline-block h-2 w-2 shrink-0 rounded-full", DOT[state])} />
      {label && <span className="text-[11px] text-zinc-500">{label}</span>}
    </span>
  );
}

/** Overall + Still/Voice/Clip dots for one shot (blink = in progress). */
export function ShotProgressDots({ shot, compact = false }: { shot: Shot; compact?: boolean }) {
  const progress = shotProgress(shot);
  return (
    <div
      data-testid="shot-progress"
      data-overall={progress.overall}
      className={cx("flex flex-wrap items-center gap-x-2 gap-y-1", compact ? "justify-end" : "")}
      aria-label={`Shot status: ${progress.label}`}
    >
      <StatusDot state={progress.overall} label={progress.label} title={`Shot ${progress.label.toLowerCase()}`} />
      {progress.stages.length > 0 && (
        <span
          className={cx(
            "flex flex-wrap items-center gap-2",
            compact ? "" : "border-l border-white/[0.06] pl-2",
          )}
        >
          {progress.stages
            .filter((s) => s.state !== "skipped")
            .map((stage) => (
              <StatusDot
                key={stage.id}
                state={stage.state}
                label={compact ? undefined : stage.label}
                title={`${stage.label}: ${stage.state}`}
              />
            ))}
        </span>
      )}
    </div>
  );
}

export function ProgressLegend({ className }: { className?: string }) {
  return (
    <ul
      data-testid="progress-legend"
      className={cx("flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500", className)}
      aria-label="Status legend"
    >
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="h-2 w-2 rounded-full bg-emerald-400" /> Complete
      </li>
      <li className="inline-flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className="h-2 w-2 animate-[status-blink_1.1s_ease-in-out_infinite] rounded-full bg-sky-400"
        />{" "}
        In progress
      </li>
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="h-2 w-2 rounded-full bg-zinc-600 ring-1 ring-inset ring-zinc-500/50" />{" "}
        Not started
      </li>
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="h-2 w-2 rounded-full bg-rose-400" /> Failed
      </li>
    </ul>
  );
}

/** Scene-level rollup from its shots (more accurate than stale ``scene.status``). */
export function sceneProgressOverall(shots: readonly Shot[]): StageProgress {
  const states = shots.map((s) => shotProgress(s).overall);
  if (states.some((s) => s === "failed")) return "failed";
  if (states.some((s) => s === "active")) return "active";
  if (states.length > 0 && states.every((s) => s === "complete" || s === "skipped")) return "complete";
  if (states.some((s) => s === "complete")) return "active";
  return "pending";
}

const SCENE_LABEL: Record<StageProgress, string> = {
  complete: "Complete",
  active: "In progress",
  pending: "Not started",
  failed: "Failed",
  skipped: "Skipped",
};

export function SceneProgressBadge({ shots }: { shots: readonly Shot[] }) {
  const overall = sceneProgressOverall(shots);
  return (
    <StatusDot
      state={overall}
      label={SCENE_LABEL[overall]}
      title={`Scene ${SCENE_LABEL[overall].toLowerCase()}`}
      testId="scene-progress-dot"
    />
  );
}
