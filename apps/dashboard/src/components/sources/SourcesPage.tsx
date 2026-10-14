"use client";

import type { CapabilityGroup, ProviderCatalogEntry, ProvidersOverview } from "@cineforge/schemas";
import { useCallback, useState, type ComponentProps, type ReactNode } from "react";
import { api, errorMessage } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { AppConfirmDialog } from "../dialogs/AppConfirmDialog";
import { AppNoticeDialog, type NoticeState } from "../dialogs/AppNoticeDialog";
import { IconAlert, IconCheck, IconInfo, IconRefresh } from "../icons";
import { Badge, Button, Card, cx, EmptyState, ErrorState, Loading, PageHeader } from "../ui";
import { ProviderRow, type ProviderOp } from "./ProviderRow";

export const MOCK_MODE_MESSAGE = "Offline mock mode: set PROVIDER_MODE=live in .env to use real sources";
export const PAID_OFF_MESSAGE = "Paid calls are off: set ALLOW_PAID_PROVIDERS=true in .env after approving spend";

function BannerLine({ tone, children }: { tone: "warning" | "info" | "success"; children: ReactNode }) {
  const styles = {
    warning: "border-amber-500/25 bg-amber-500/[0.06] text-amber-200",
    info: "border-sky-500/25 bg-sky-500/[0.06] text-sky-200",
    success: "border-emerald-500/25 bg-emerald-500/[0.06] text-emerald-200",
  }[tone];
  const Icon = tone === "warning" ? IconAlert : tone === "success" ? IconCheck : IconInfo;
  return (
    <p className={cx("flex items-start gap-2 rounded-lg border px-3 py-2 text-sm", styles)}>
      <span className="mt-0.5 shrink-0">
        <Icon size={15} />
      </span>
      {children}
    </p>
  );
}

export function SourcesBanner({ overview }: { overview: ProvidersOverview }) {
  return (
    <section aria-label="Provider mode" className="mb-6 grid gap-2 md:grid-cols-2">
      {overview.provider_mode === "mock" ? (
        <BannerLine tone="info">{MOCK_MODE_MESSAGE}</BannerLine>
      ) : (
        <BannerLine tone="success">Live mode: enabled, ready providers are used in priority order.</BannerLine>
      )}
      {overview.paid_providers_allowed ? (
        <BannerLine tone="warning">Paid calls are on: every paid call reserves budget before it runs.</BannerLine>
      ) : (
        <BannerLine tone="info">{PAID_OFF_MESSAGE}</BannerLine>
      )}
    </section>
  );
}

type Busy = { name: string; op: ProviderOp } | null;
type Pending = { kind: "enable-paid" | "remove-key"; provider: ProviderCatalogEntry } | null;

function GroupCard({
  group,
  busy,
  handlers,
}: {
  group: CapabilityGroup;
  busy: Busy;
  handlers: Omit<ComponentProps<typeof ProviderRow>, "provider" | "active" | "busy">;
}) {
  const active = group.providers.find((p) => p.name === group.active_provider);
  return (
    <Card
      id={`group-${group.capability}`}
      title={group.label}
      description={
        active ? (
          <span>
            Active: <span className="text-gold-300">{active.display_name}</span>
          </span>
        ) : (
          <span className="text-amber-300/80">No active provider</span>
        )
      }
      actions={<Badge>{group.providers.length} providers</Badge>}
    >
      {group.providers.length === 0 ? (
        <EmptyState title="No providers registered" />
      ) : (
        <ul className="space-y-2">
          {group.providers.map((provider) => (
            <ProviderRow
              key={provider.name}
              provider={provider}
              active={provider.name === group.active_provider}
              busy={busy?.name === provider.name ? busy.op : null}
              {...handlers}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

export function SourcesPage() {
  const overview = useResource("providers", () => api.getProviders());
  const { reload } = overview;
  const [busy, setBusy] = useState<Busy>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [notice, setNotice] = useState<NoticeState | null>(null);

  const mutate = useCallback(
    async (provider: ProviderCatalogEntry, op: ProviderOp, run: () => Promise<unknown>, success?: NoticeState) => {
      setBusy({ name: provider.name, op });
      try {
        await run();
        setPending(null);
        await reload();
        if (success) setNotice(success);
      } catch (err) {
        setPending(null);
        setNotice({ variant: "error", title: `Could not update ${provider.display_name}`, message: errorMessage(err) });
        void reload();
      } finally {
        setBusy(null);
      }
    },
    [reload],
  );

  const setEnabled = useCallback(
    (provider: ProviderCatalogEntry, enabled: boolean) =>
      mutate(provider, "toggle", () => api.updateProvider(provider.name, { enabled })),
    [mutate],
  );

  const removeKey = useCallback(
    (provider: ProviderCatalogEntry) =>
      mutate(provider, "remove-key", () => api.deleteProviderKey(provider.name), {
        variant: "success",
        title: "Key removed",
        message: `The stored key for ${provider.display_name} was deleted.`,
      }),
    [mutate],
  );

  const handlers = {
    onToggle: (provider: ProviderCatalogEntry, enabled: boolean) => {
      if (enabled && provider.is_paid) setPending({ kind: "enable-paid", provider });
      else void setEnabled(provider, enabled);
    },
    onPriority: (provider: ProviderCatalogEntry, priority: number) =>
      void mutate(provider, "priority", () => api.updateProvider(provider.name, { priority })),
    onSaveKey: (provider: ProviderCatalogEntry, apiKey: string) =>
      void mutate(provider, "save-key", () => api.setProviderKey(provider.name, apiKey), {
        variant: "success",
        title: "Key saved",
        message: `The key for ${provider.display_name} is stored encrypted. It is write-only: only its last characters are shown.`,
      }),
    onRemoveKey: (provider: ProviderCatalogEntry) => setPending({ kind: "remove-key", provider }),
    onTest: async (provider: ProviderCatalogEntry) => {
      setBusy({ name: provider.name, op: "test" });
      try {
        const result = await api.testProvider(provider.name);
        setNotice({
          variant: result.ok ? "success" : "error",
          title: `${provider.display_name}: ${result.ok ? "test passed" : "test failed"}`,
          message: result.detail,
          note: [
            typeof result.latency_ms === "number" ? `${Math.round(result.latency_ms)} ms` : null,
            result.paid_call ? "This check made a paid call." : "Free check, no spend.",
          ]
            .filter(Boolean)
            .join(" · "),
        });
      } catch (err) {
        setNotice({ variant: "error", title: `Could not test ${provider.display_name}`, message: errorMessage(err) });
      } finally {
        setBusy(null);
      }
    },
  };

  const data = overview.data;
  const pendingProvider = pending?.provider;

  return (
    <>
      <PageHeader
        title="Sources"
        description="Providers the agents can route to, grouped by capability. Lower priority numbers are tried first."
        actions={
          <>
            {data && <Badge title="Where provider keys are stored">Secrets: {data.secrets_backend}</Badge>}
            <Button variant="ghost" onClick={() => void reload()} aria-label="Refresh providers">
              <IconRefresh size={15} />
            </Button>
          </>
        }
      />
      {overview.loading ? (
        <Loading label="Loading providers…" rows={6} />
      ) : !data ? (
        <ErrorState error={overview.error} onRetry={() => void reload()} />
      ) : (
        <>
          <SourcesBanner overview={data} />
          {data.groups.length === 0 ? (
            <EmptyState title="No providers registered" />
          ) : (
            <div className="space-y-6">
              {data.groups.map((group) => (
                <GroupCard key={group.capability} group={group} busy={busy} handlers={handlers} />
              ))}
            </div>
          )}
        </>
      )}

      <AppConfirmDialog
        open={pending?.kind === "enable-paid"}
        variant="warning"
        title={`Enable ${pendingProvider?.display_name ?? "paid provider"}?`}
        message="This provider charges real money per call. Calls still need ALLOW_PAID_PROVIDERS=true and a budget reservation before they run."
        noteLabel="Spend"
        note="Only enable it after the spend has been approved."
        confirmLabel="Enable paid provider"
        busy={busy?.op === "toggle"}
        onConfirm={() => pendingProvider && void setEnabled(pendingProvider, true)}
        onCancel={() => setPending(null)}
      />

      <AppConfirmDialog
        open={pending?.kind === "remove-key"}
        variant="danger"
        title={`Remove the key for ${pendingProvider?.display_name ?? "this provider"}?`}
        message="The stored key is deleted. The provider stops routing until a new key is saved."
        confirmLabel="Remove key"
        busy={busy?.op === "remove-key"}
        onConfirm={() => pendingProvider && void removeKey(pendingProvider)}
        onCancel={() => setPending(null)}
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
