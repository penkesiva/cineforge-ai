import type { ProductionDetail } from "@cineforge/schemas";
import { formatDateTime, formatDuration, humanize } from "@/lib/format";
import { availableActions } from "@/lib/workflow";
import { IconCheck, IconPlay, IconSend, IconStop } from "../icons";
import { Badge, Button, SimulatedBadge, Spinner, StateBadge } from "../ui";

export type ProductionAction = "run" | "approve" | "cancel" | "deliver";
/** Header actions plus review-only actions that should also lock the header. */
export type BusyAction = ProductionAction | "rewrite";

export interface ProductionActionHandlers {
  onAction?: (action: ProductionAction) => void;
  busyAction?: BusyAction | null;
}

export function ProductionHeader({
  detail,
  onAction,
  busyAction = null,
  polling = false,
}: { detail: ProductionDetail; polling?: boolean } & ProductionActionHandlers) {
  const { summary, manifest } = detail;
  const actions = availableActions(summary.state);
  const disabled = busyAction !== null || !onAction;
  const simulated = detail.cost.simulated !== false;
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 max-w-3xl">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <StateBadge state={summary.state} />
          <Badge tone="gold">{humanize(summary.theme_id)}</Badge>
          <Badge>{humanize(summary.mode)} mode</Badge>
          {simulated && <SimulatedBadge />}
          {polling && (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-sky-300/80">
              <Spinner className="h-2.5 w-2.5" /> Live
            </span>
          )}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">
          {summary.title || manifest.title || "Untitled production"}
        </h1>
        <p className="mt-1 text-sm text-zinc-400">{summary.topic}</p>
        <p className="mt-2 text-xs text-zinc-500">
          {summary.scene_count} scenes · {summary.shot_count} shots · target{" "}
          {formatDuration(manifest.output?.duration_target_sec)} · {manifest.output?.aspect_ratio ?? "9:16"} ·
          created {formatDateTime(summary.created_at)}
          {manifest.approval?.auto_approve ? " · auto-approve on" : ""}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Production actions">
        {actions.run && (
          <Button variant="primary" onClick={() => onAction?.("run")} disabled={disabled} busy={busyAction === "run"}>
            <IconPlay size={15} /> Run
          </Button>
        )}
        {actions.approve && (
          <Button
            variant="warning"
            onClick={() => onAction?.("approve")}
            disabled={disabled}
            busy={busyAction === "approve"}
          >
            <IconCheck size={15} /> {summary.state === "PAUSED_BUDGET" ? "Raise budget & approve" : "Approve"}
          </Button>
        )}
        {actions.deliver && (
          <Button
            variant="primary"
            onClick={() => onAction?.("deliver")}
            disabled={disabled}
            busy={busyAction === "deliver"}
          >
            <IconSend size={15} /> Deliver
          </Button>
        )}
        {actions.cancel && (
          <Button
            variant="ghost"
            onClick={() => onAction?.("cancel")}
            disabled={disabled}
            busy={busyAction === "cancel"}
            className="text-rose-300 hover:text-rose-200"
          >
            <IconStop size={15} /> Cancel
          </Button>
        )}
      </div>
    </div>
  );
}
