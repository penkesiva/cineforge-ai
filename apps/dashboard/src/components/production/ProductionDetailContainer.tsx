"use client";

import type { ProductionDetail } from "@cineforge/schemas";
import Link from "next/link";
import { useCallback, useState } from "react";
import { api, errorMessage, isApiError } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { usePolling, useResource } from "@/lib/hooks";
import { isWorkingState } from "@/lib/workflow";
import { AppConfirmDialog } from "../dialogs/AppConfirmDialog";
import { AppNoticeDialog, type NoticeState } from "../dialogs/AppNoticeDialog";
import { IconAlert } from "../icons";
import { EmptyState, ErrorState, Loading } from "../ui";
import type { ProductionAction } from "./ProductionHeader";
import { ProductionDetailView } from "./ProductionDetailView";

export const DETAIL_POLL_MS = 2_000;

/** Suggested cap when resuming from PAUSED_BUDGET: 25% headroom over the larger of estimate and limit. */
export function suggestedBudget(detail: ProductionDetail): number {
  const base = Math.max(detail.cost.estimated ?? 0, detail.cost.limit, (detail.cost.actual ?? 0) + (detail.cost.reserved ?? 0));
  return Math.ceil(base * 1.25 * 100) / 100;
}

function BudgetInput({
  value,
  onChange,
  error,
}: {
  value: string;
  onChange: (value: string) => void;
  error: string | null;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium text-zinc-400">Raise budget to (USD)</span>
      <input
        type="number"
        inputMode="decimal"
        min={0}
        step="0.01"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? "raise-budget-error" : undefined}
        className="w-full rounded-lg border border-white/10 bg-ink-950/60 px-3 py-2 tabular-nums text-zinc-100 outline-none focus:border-amber-400/60 focus:ring-2 focus:ring-amber-400/20"
      />
      {error && (
        <span id="raise-budget-error" className="mt-1 block text-xs text-rose-300">
          {error}
        </span>
      )}
    </label>
  );
}

export function ProductionDetailContainer({ id }: { id: string }) {
  const { data, error, loading, reload } = useResource(id, () => api.getProduction(id));
  const state = data?.summary.state;
  const polling = state !== undefined && isWorkingState(state);
  usePolling(reload, DETAIL_POLL_MS, polling);

  const [confirming, setConfirming] = useState<Exclude<ProductionAction, "run"> | null>(null);
  const [busyAction, setBusyAction] = useState<ProductionAction | null>(null);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [raiseTo, setRaiseTo] = useState("");

  const execute = useCallback(
    async (action: ProductionAction) => {
      if (!data) return;
      setBusyAction(action);
      try {
        let message: string;
        if (action === "run") message = (await api.runProduction(id)).message;
        else if (action === "approve") {
          const payload =
            data.summary.state === "PAUSED_BUDGET" && raiseTo.trim() ? { raise_budget_to_usd: Number(raiseTo) } : {};
          message = (await api.approveProduction(id, payload)).message;
        } else if (action === "cancel") message = (await api.cancelProduction(id)).message;
        else message = (await api.deliverProduction(id)).message;

        setConfirming(null);
        await reload();
        if (action === "cancel") {
          setNotice({ variant: "success", title: "Production cancelled", message });
        } else if (action === "deliver") {
          setNotice({ variant: "success", title: "Production delivered", message });
        }
      } catch (err) {
        setConfirming(null);
        setNotice({
          variant: "error",
          title: `Could not ${action} production`,
          message: errorMessage(err),
          note: isApiError(err) && err.status ? `HTTP ${err.status}${err.body ? ` · ${err.body.error}` : ""}` : undefined,
        });
        void reload();
      } finally {
        setBusyAction(null);
      }
    },
    [data, id, raiseTo, reload],
  );

  const onAction = useCallback(
    (action: ProductionAction) => {
      if (!data) return;
      if (action === "run") {
        void execute("run");
        return;
      }
      if (action === "approve" && data.summary.state === "PAUSED_BUDGET") {
        setRaiseTo(suggestedBudget(data).toFixed(2));
      }
      setConfirming(action);
    },
    [data, execute],
  );

  if (!data) {
    if (loading) return <Loading label="Loading production…" rows={6} />;
    if (isApiError(error) && error.status === 404) {
      return (
        <EmptyState title="Production not found">
          It may belong to another tenant or was never created.{" "}
          <Link href="/productions" className="text-sky-300 hover:underline">
            Back to productions
          </Link>
        </EmptyState>
      );
    }
    return <ErrorState error={error} onRetry={() => void reload()} />;
  }

  const paused = data.summary.state === "PAUSED_BUDGET";
  const estimated = data.cost.estimated ?? data.manifest.budget.estimated ?? 0;
  const raiseValue = Number(raiseTo);
  const raiseError =
    paused && confirming === "approve"
      ? !raiseTo.trim() || !Number.isFinite(raiseValue) || raiseValue <= data.cost.limit
        ? `Enter an amount above the current limit (${formatUsd(data.cost.limit)}).`
        : null
      : null;

  return (
    <>
      {error !== undefined && (
        <div role="status" className="mb-4 flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-3 py-2 text-sm text-amber-200">
          <IconAlert size={15} /> Live updates interrupted: {errorMessage(error)}
        </div>
      )}
      <ProductionDetailView
        detail={data}
        contentUrl={api.assetContentUrl}
        polling={polling}
        onAction={onAction}
        busyAction={busyAction}
      />

      <AppConfirmDialog
        open={confirming === "approve"}
        variant="warning"
        title={paused ? "Raise budget and resume generation?" : "Approve generation spend?"}
        message={
          paused
            ? "The production paused because the next step would exceed its hard budget. Raise the cap to continue."
            : `Generation runs the visual and audio agents for ${data.summary.shot_count} shots and commits spend against the budget.`
        }
        noteLabel="Estimated cost"
        note={
          <span className="tabular-nums">
            <strong className="text-zinc-50">{formatUsd(estimated)}</strong> estimated of{" "}
            {formatUsd(data.cost.limit)} limit · {formatUsd(data.cost.actual ?? 0)} spent so far
            <span className="mt-1 block text-xs text-zinc-500">Simulated costs: mock providers only.</span>
          </span>
        }
        confirmLabel={paused ? "Raise & approve" : "Approve spend"}
        busy={busyAction === "approve"}
        confirmDisabled={raiseError !== null}
        onConfirm={() => void execute("approve")}
        onCancel={() => setConfirming(null)}
      >
        {paused && <BudgetInput value={raiseTo} onChange={setRaiseTo} error={raiseError} />}
      </AppConfirmDialog>

      <AppConfirmDialog
        open={confirming === "cancel"}
        variant="danger"
        title="Cancel this production?"
        message="All remaining work stops and open budget reservations are released. This cannot be undone."
        noteLabel="Spent so far"
        note={<span className="tabular-nums">{formatUsd(data.cost.actual ?? 0)} actual (simulated)</span>}
        confirmLabel="Cancel production"
        cancelLabel="Keep production"
        busy={busyAction === "cancel"}
        onConfirm={() => void execute("cancel")}
        onCancel={() => setConfirming(null)}
      />

      <AppConfirmDialog
        open={confirming === "deliver"}
        variant="default"
        title="Deliver this production?"
        message="The reviewed master render is marked as delivered and the production is closed."
        note={
          data.artifacts.master
            ? `${data.artifacts.master.width}×${data.artifacts.master.height}, ${Math.round(data.artifacts.master.duration_sec)}s ${data.artifacts.master.codec}`
            : undefined
        }
        noteLabel="Master render"
        confirmLabel="Deliver"
        busy={busyAction === "deliver"}
        onConfirm={() => void execute("deliver")}
        onCancel={() => setConfirming(null)}
      />

      <AppNoticeDialog
        open={notice !== null}
        variant={notice?.variant}
        title={notice?.title ?? ""}
        message={notice?.message}
        note={notice?.note}
        onClose={() => setNotice(null)}
      />
    </>
  );
}
