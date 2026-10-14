"use client";

import type { ThemeProfile } from "@cineforge/schemas";
import Link from "next/link";
import { useId, useState } from "react";
import { api, errorMessage, isApiError } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { AppNoticeDialog } from "../dialogs/AppNoticeDialog";
import { IconPlus } from "../icons";
import { Badge, Button, Card, EmptyState, ErrorState, inputClass, Loading, PageHeader } from "../ui";
import { ThemeProfileView } from "./ThemeProfileView";
import { ThemeVersionForm } from "./ThemeVersionForm";

export const STALE_VERSION_MESSAGE = "Someone created a newer version; reload";

interface DetailNotice {
  variant: "success" | "error";
  title: string;
  message: string;
  stale?: boolean;
}

export function ThemeDetail({ id }: { id: string }) {
  const selectId = useId();
  const versions = useResource(id, () => api.listThemeVersions(id));
  const [selected, setSelected] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<DetailNotice | null>(null);

  const list = versions.data ?? [];
  const latest = list.reduce<ThemeProfile | undefined>((best, v) => (!best || v.version > best.version ? v : best), undefined);
  const shown = list.find((v) => v.version === selected) ?? latest;

  async function submit(profile: ThemeProfile) {
    if (!latest) return;
    setSubmitting(true);
    try {
      const created = await api.createThemeVersion(id, { base_version: latest.version, profile });
      setEditing(false);
      await versions.reload();
      setSelected(created.version);
      setNotice({ variant: "success", title: `Created v${created.version}`, message: `${created.name} v${created.version} is now the latest version.` });
    } catch (err) {
      const stale = isApiError(err) && err.status === 409;
      setNotice({
        variant: "error",
        title: stale ? "Theme changed meanwhile" : "Could not create version",
        message: stale ? STALE_VERSION_MESSAGE : errorMessage(err),
        stale,
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function reloadAfterConflict() {
    setNotice(null);
    setEditing(false);
    setSelected(null);
    await versions.reload();
  }

  if (!versions.data) {
    if (versions.loading) return <Loading label="Loading theme…" rows={6} />;
    if (isApiError(versions.error) && versions.error.status === 404) {
      return (
        <EmptyState title="Theme not found">
          <Link href="/themes" className="text-sky-300 hover:underline">
            Back to themes
          </Link>
        </EmptyState>
      );
    }
    return <ErrorState error={versions.error} onRetry={() => void versions.reload()} />;
  }

  if (!latest || !shown) return <EmptyState title="This theme has no versions" />;

  return (
    <>
      <PageHeader
        title={latest.name}
        description={latest.purpose}
        actions={
          <>
            <Link href="/themes" className="text-sm text-zinc-400 hover:text-zinc-200">
              All themes
            </Link>
            {!editing && (
              <Button variant="primary" onClick={() => setEditing(true)}>
                <IconPlus size={15} /> Create new version
              </Button>
            )}
          </>
        }
      />

      {editing && (
        <Card title={`New version of ${latest.name}`} className="mb-6">
          <ThemeVersionForm base={latest} onSubmit={submit} submitting={submitting} onCancel={() => setEditing(false)} />
        </Card>
      )}

      <Card
        title={`Version ${shown.version}`}
        description={shown.version === latest.version ? "Latest version" : `Older version (latest is v${latest.version})`}
        actions={
          <div className="flex items-center gap-2">
            <label htmlFor={selectId} className="text-xs text-zinc-400">
              Version
            </label>
            <select
              id={selectId}
              className={`${inputClass} w-auto py-1.5`}
              value={shown.version}
              onChange={(e) => setSelected(Number(e.target.value))}
            >
              {[...list]
                .sort((a, b) => b.version - a.version)
                .map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version}
                    {v.version === latest.version ? " (latest)" : ""}
                  </option>
                ))}
            </select>
            {shown.version === latest.version && <Badge tone="gold">Latest</Badge>}
          </div>
        }
      >
        <ThemeProfileView profile={shown} />
      </Card>

      <AppNoticeDialog
        open={notice !== null}
        variant={notice?.variant}
        title={notice?.title ?? ""}
        message={notice?.message}
        actionLabel={notice?.stale ? "Close" : undefined}
        secondaryLabel={notice?.stale ? "Reload" : undefined}
        onSecondary={notice?.stale ? () => void reloadAfterConflict() : undefined}
        onClose={() => setNotice(null)}
      />
    </>
  );
}
