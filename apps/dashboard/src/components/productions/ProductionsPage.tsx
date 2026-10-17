"use client";

import type { CreateProductionRequest } from "@cineforge/schemas";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { AppNoticeDialog, type NoticeState } from "../dialogs/AppNoticeDialog";
import { IconPlus, IconRefresh } from "../icons";
import { Button, Card, EmptyState, ErrorState, Loading, PageHeader, SimulatedBadge } from "../ui";
import { CreateProductionForm, type InspirationSeed } from "./CreateProductionForm";
import { ProductionsTable } from "./ProductionsTable";

function NewProductionPanel({ onClose, inspiration }: { onClose: () => void; inspiration?: InspirationSeed | null }) {
  const router = useRouter();
  const themes = useResource("themes", () => api.listThemes());
  const modes = useResource("modes", () => api.listModes());
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);

  async function submit(request: CreateProductionRequest) {
    setSubmitting(true);
    try {
      const detail = await api.createProduction(request);
      router.push(`/productions/${encodeURIComponent(detail.summary.id)}`);
    } catch (err) {
      setNotice({ variant: "error", title: "Could not create production", message: errorMessage(err) });
      setSubmitting(false);
    }
  }

  const loadError = themes.error ?? modes.error;
  return (
    <Card title="New production" description="Pick a theme and mode. The engine plans, scripts and storyboards before asking for spend approval." className="mb-6">
      {themes.loading || modes.loading ? (
        <Loading label="Loading themes and modes…" />
      ) : loadError || !themes.data || !modes.data ? (
        <ErrorState
          error={loadError}
          onRetry={() => {
            void themes.reload();
            void modes.reload();
          }}
        />
      ) : (
        <CreateProductionForm
          themes={themes.data}
          modes={modes.data}
          onSubmit={submit}
          submitting={submitting}
          onCancel={onClose}
          inspiration={inspiration}
        />
      )}
      <AppNoticeDialog
        open={notice !== null}
        variant={notice?.variant}
        title={notice?.title ?? ""}
        message={notice?.message}
        onClose={() => setNotice(null)}
      />
    </Card>
  );
}

export function ProductionsPage({ inspiration = null }: { inspiration?: InspirationSeed | null }) {
  const productions = useResource("productions", () => api.listProductions());
  const [showForm, setShowForm] = useState(Boolean(inspiration));

  return (
    <>
      <PageHeader
        title="Productions"
        description="Every cinematic short the engine is planning, generating or has delivered."
        actions={
          <>
            <SimulatedBadge />
            <Button variant="ghost" onClick={() => void productions.reload()} aria-label="Refresh productions">
              <IconRefresh size={15} />
            </Button>
            {!showForm && (
              <Button variant="primary" onClick={() => setShowForm(true)}>
                <IconPlus size={15} /> New production
              </Button>
            )}
          </>
        }
      />
      {showForm && <NewProductionPanel onClose={() => setShowForm(false)} inspiration={inspiration} />}
      <Card>
        {productions.loading ? (
          <Loading label="Loading productions…" rows={5} />
        ) : !productions.data ? (
          <ErrorState error={productions.error} onRetry={() => void productions.reload()} />
        ) : productions.data.length === 0 ? (
          <EmptyState title="No productions yet">Create one to watch the ten agents at work.</EmptyState>
        ) : (
          <ProductionsTable productions={productions.data} />
        )}
      </Card>
    </>
  );
}
