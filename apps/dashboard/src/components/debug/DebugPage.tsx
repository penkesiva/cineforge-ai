"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { buildDebugLog, type DebugIssue, type DebugLogBundle } from "@/lib/debugLog";
import { formatDateTime } from "@/lib/format";
import { AppNoticeDialog, type NoticeState } from "../dialogs/AppNoticeDialog";
import { IconAlert, IconRefresh } from "../icons";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, Mono, PageHeader } from "../ui";

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.left = "-9999px";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
}

function IssueRow({ issue }: { issue: DebugIssue }) {
  return (
    <li className="rounded-lg border border-rose-500/20 bg-rose-500/[0.04] px-3 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <Badge tone="danger">{issue.kind.replace(/_/g, " ")}</Badge>
        <Link href={`/productions/${issue.production_id}`} className="text-sm text-gold-300 hover:underline">
          {issue.title}
        </Link>
        <Mono className="text-[11px] text-zinc-500">{issue.production_id}</Mono>
        <span className="text-xs text-zinc-500">
          {issue.state}
          {issue.approval_stage ? ` · ${issue.approval_stage}` : ""}
        </span>
        {issue.when && (
          <time dateTime={issue.when} className="ml-auto text-[11px] tabular-nums text-zinc-600">
            {formatDateTime(issue.when)}
          </time>
        )}
      </div>
      <p className="mt-1.5 text-sm text-zinc-200">{issue.summary}</p>
      {issue.detail && (
        <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-rose-200/90">
          {issue.detail}
        </pre>
      )}
    </li>
  );
}

export function DebugPage() {
  const [bundle, setBundle] = useState<DebugLogBundle | null>(null);
  const [error, setError] = useState<Error | undefined>();
  const [loading, setLoading] = useState(true);
  const [copying, setCopying] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      const next = await buildDebugLog(
        () => api.listProductions(),
        (id) => api.getProduction(id),
      );
      setBundle(next);
    } catch (err) {
      setBundle(null);
      setError(err instanceof Error ? err : new Error(errorMessage(err)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onCopy = useCallback(async () => {
    if (!bundle) return;
    setCopying(true);
    try {
      await copyText(bundle.text);
      setNotice({
        variant: "success",
        title: "Debug log copied",
        message: "Paste it into chat so we can see the exact failures.",
        note: `${bundle.issue_count} issue(s) from ${bundle.inspected} inspected production(s)`,
      });
    } catch (err) {
      setNotice({
        variant: "error",
        title: "Could not copy",
        message: errorMessage(err),
        note: "Select the log text below and copy manually.",
      });
    } finally {
      setCopying(false);
    }
  }, [bundle]);

  return (
    <>
      <PageHeader
        title="Debug"
        description="Project-wide failures, pauses and blocked approvals. Copy the log and paste it into chat."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" onClick={() => void reload()} disabled={loading}>
              <IconRefresh size={15} /> Refresh
            </Button>
            <Button onClick={() => void onCopy()} disabled={!bundle || copying} busy={copying}>
              Copy debug log
            </Button>
          </div>
        }
      />

      <div className="space-y-6">
        <Card
          title="Debug log"
          description={
            bundle
              ? `${bundle.issue_count} issue(s) · inspected ${bundle.inspected} of ${bundle.production_count} productions · ${formatDateTime(bundle.generated_at)}`
              : "Loads recent and stuck productions"
          }
          actions={
            bundle ? (
              <Button variant="ghost" className="!px-2.5 !py-1 text-xs" onClick={() => void onCopy()} busy={copying}>
                Copy
              </Button>
            ) : undefined
          }
        >
          {loading ? (
            <Loading rows={6} />
          ) : error || !bundle ? (
            <ErrorState error={error} onRetry={() => void reload()} />
          ) : (
            <textarea
              readOnly
              aria-label="Debug log text"
              value={bundle.text}
              className="h-[28rem] w-full resize-y rounded-lg border border-white/[0.08] bg-ink-950/80 p-3 font-mono text-[11px] leading-relaxed text-zinc-200 outline-none focus:border-gold-500/40 focus:ring-2 focus:ring-gold-500/15"
              onFocus={(e) => e.currentTarget.select()}
            />
          )}
        </Card>

        <Card
          title="Error sections"
          description="Same issues, one card each. Open a production to act on it."
        >
          {loading ? (
            <Loading rows={4} />
          ) : error || !bundle ? (
            <ErrorState error={error} onRetry={() => void reload()} />
          ) : bundle.issues.length === 0 ? (
            <EmptyState title="No errors right now">
              Approvals that fail later in the worker still land here after you refresh.
            </EmptyState>
          ) : (
            <ul className="space-y-2" aria-label="Error sections">
              {bundle.issues.map((issue, i) => (
                <IssueRow key={`${issue.production_id}-${issue.kind}-${issue.when ?? i}-${i}`} issue={issue} />
              ))}
            </ul>
          )}
        </Card>

        <p className="flex items-start gap-2 text-xs text-zinc-500">
          <IconAlert size={14} className="mt-0.5 shrink-0 text-zinc-600" />
          Approve can return success while the worker is still generating. If a clip fails later, the
          production comes back to an approval gate and the failure shows up here (and on the
          production Events card).
        </p>
      </div>

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
