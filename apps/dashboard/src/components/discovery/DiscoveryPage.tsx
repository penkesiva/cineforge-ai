"use client";

import type { DiscoveryMode, DiscoveryRun, TrendCandidate } from "@cineforge/schemas";
import Link from "next/link";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { AppNoticeDialog, type NoticeState } from "../dialogs/AppNoticeDialog";
import { Button, Card, EmptyState, PageHeader } from "../ui";

function newKey(): string {
  return `disc-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function count(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString();
}

export function DiscoveryPage() {
  const [mode, setMode] = useState<DiscoveryMode>("popular");
  const [region, setRegion] = useState("US");
  const [query, setQuery] = useState("");
  const [lookback, setLookback] = useState<1 | 7 | 30>(7);
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);

  async function search() {
    setBusy(true);
    try {
      const next = await api.startDiscovery({
        mode,
        region_code: region.trim().toUpperCase() || "US",
        query: mode === "recent" ? query.trim() : null,
        lookback_days: mode === "recent" ? lookback : null,
        page_size: 25,
        idempotency_key: newKey(),
      });
      setRun(next);
    } catch (err) {
      setNotice({ variant: "error", title: "Discovery failed", message: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  async function more() {
    if (!run?.id || !run.next_cursor) return;
    setBusy(true);
    try {
      setRun(await api.discoveryPage(run.id, { cursor: run.next_cursor }));
    } catch (err) {
      setNotice({ variant: "error", title: "Could not load the next page", message: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Discovery"
        description="YouTube chart and recent videos. These are references, not assets, and they are not research claims."
      />
      <Card className="mb-6">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="text-sm text-zinc-300">
            Mode
            <select
              className="mt-1 w-full rounded-md border border-white/10 bg-ink-950 px-2 py-2"
              value={mode}
              onChange={(event) => setMode(event.target.value as DiscoveryMode)}
            >
              <option value="popular">Popular chart</option>
              <option value="recent">Recent search</option>
            </select>
          </label>
          <label className="text-sm text-zinc-300">
            Region
            <input
              className="mt-1 w-full rounded-md border border-white/10 bg-ink-950 px-2 py-2"
              value={region}
              maxLength={2}
              onChange={(event) => setRegion(event.target.value.toUpperCase())}
            />
          </label>
          {mode === "recent" ? (
            <>
              <label className="text-sm text-zinc-300">
                Query
                <input
                  className="mt-1 w-full rounded-md border border-white/10 bg-ink-950 px-2 py-2"
                  value={query}
                  maxLength={200}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <label className="text-sm text-zinc-300">
                Lookback
                <select
                  className="mt-1 w-full rounded-md border border-white/10 bg-ink-950 px-2 py-2"
                  value={lookback}
                  onChange={(event) => setLookback(Number(event.target.value) as 1 | 7 | 30)}
                >
                  <option value={1}>1 day</option>
                  <option value={7}>7 days</option>
                  <option value={30}>30 days</option>
                </select>
              </label>
            </>
          ) : null}
        </div>
        <div className="mt-4">
          <Button variant="primary" onClick={() => void search()} disabled={busy}>
            {busy ? "Loading…" : "Find videos"}
          </Button>
        </div>
      </Card>
      {run ? <Results run={run} busy={busy} onMore={() => void more()} /> : null}
      <AppNoticeDialog
        open={notice !== null}
        variant={notice?.variant}
        title={notice?.title ?? ""}
        message={notice?.message}
        onClose={() => setNotice(null)}
      />
    </>
  );
}

function Results({ run, busy, onMore }: { run: DiscoveryRun; busy: boolean; onMore: () => void }) {
  return (
    <Card
      title={run.is_mock ? "Mock results" : run.freshness === "cached" ? "Cached results" : "Live results"}
        description={`Retrieved ${run.retrieved_at ?? "just now"}. YouTube data. Open the source before you use it.`}
    >
      {(run.warnings ?? []).length > 0 ? (
        <ul className="mb-4 list-disc pl-5 text-sm text-amber-200">
          {(run.warnings ?? []).map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {(run.candidates ?? []).length === 0 ? (
        <EmptyState title="No videos">Try another region or query.</EmptyState>
      ) : (
        <ul className="grid gap-3">
          {(run.candidates ?? []).map((candidate) => (
            <Candidate key={`${candidate.platform}:${candidate.video_id}`} candidate={candidate} />
          ))}
        </ul>
      )}
      {run.next_cursor ? (
        <div className="mt-4">
          <Button variant="ghost" onClick={onMore} disabled={busy}>
            Load more
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

function Candidate({ candidate }: { candidate: TrendCandidate }) {
  const topic = encodeURIComponent(candidate.title.slice(0, 500));
  const href = `/productions?topic=${topic}&video=${encodeURIComponent(candidate.video_id)}&retrieved=${encodeURIComponent(candidate.retrieved_at)}`;
  return (
    <li className="flex gap-3 rounded-xl border border-white/10 p-3">
      {candidate.thumbnail_url ? (
        // Remote YouTube thumbnail only. Do not download or proxy it.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={candidate.thumbnail_url} alt="" className="h-20 w-28 rounded-md object-cover" />
      ) : (
        <div className="h-20 w-28 rounded-md bg-white/5" />
      )}
      <div className="min-w-0 flex-1">
        <a href={candidate.watch_url} target="_blank" rel="noreferrer" className="font-medium text-zinc-100 hover:underline">
          {candidate.title || candidate.video_id}
        </a>
        <p className="text-sm text-zinc-400">
          {candidate.channel_name} · {count(candidate.view_count)} views · {count(candidate.like_count)} likes ·{" "}
          {count(candidate.comment_count)} comments
          {candidate.duration_sec != null ? ` · ${candidate.duration_sec}s` : ""}
        </p>
        <Link href={href} className="mt-2 inline-block text-sm text-gold-300 hover:underline">
          Use as inspiration
        </Link>
      </div>
    </li>
  );
}
