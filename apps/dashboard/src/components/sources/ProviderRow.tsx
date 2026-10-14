"use client";

import type { ProviderCatalogEntry } from "@cineforge/schemas";
import { useId, useState } from "react";
import { humanize } from "@/lib/format";
import { isPlanned, plannedLabel, PROVIDER_STATUS } from "@/lib/providers";
import { Badge, Button, cx, ExternalLink, inputClass, safeHref, Switch } from "../ui";
import { ProviderKeyField } from "./ProviderKeyField";

export type ProviderOp = "toggle" | "priority" | "save-key" | "remove-key" | "test";

export interface ProviderRowHandlers {
  onToggle: (provider: ProviderCatalogEntry, enabled: boolean) => void;
  onPriority: (provider: ProviderCatalogEntry, priority: number) => void;
  onSaveKey: (provider: ProviderCatalogEntry, apiKey: string) => void;
  onRemoveKey: (provider: ProviderCatalogEntry) => void;
  onTest: (provider: ProviderCatalogEntry) => void;
}

export interface ProviderRowProps extends ProviderRowHandlers {
  provider: ProviderCatalogEntry;
  active?: boolean;
  busy?: ProviderOp | null;
}

function PriorityInput({
  provider,
  disabled,
  onCommit,
}: {
  provider: ProviderCatalogEntry;
  disabled: boolean;
  onCommit: (priority: number) => void;
}) {
  const id = useId();
  const [value, setValue] = useState(String(provider.priority));
  const parsed = Number(value);
  const valid = /^\d+$/.test(value.trim()) && Number.isSafeInteger(parsed);

  function commit() {
    if (!valid) {
      setValue(String(provider.priority));
      return;
    }
    if (parsed !== provider.priority) onCommit(parsed);
  }

  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor={id} className="text-[11px] text-zinc-500">
        Priority
      </label>
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={0}
        step={1}
        value={value}
        disabled={disabled}
        aria-label={`Priority for ${provider.display_name}`}
        aria-invalid={valid ? undefined : true}
        title="Lower numbers are tried first"
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
        className={cx(inputClass, "w-16 px-2 py-1 text-xs tabular-nums")}
      />
    </div>
  );
}

export function ProviderRow({
  provider,
  active = false,
  busy = null,
  onToggle,
  onPriority,
  onSaveKey,
  onRemoveKey,
  onTest,
}: ProviderRowProps) {
  const planned = isPlanned(provider);
  const status = PROVIDER_STATUS[provider.status];
  const docs = safeHref(provider.docs_url);
  const locked = planned || busy !== null;
  const nameId = useId();

  return (
    <li
      data-testid="provider-row"
      data-provider={provider.name}
      aria-labelledby={nameId}
      className={cx(
        "rounded-xl border px-4 py-3",
        active ? "border-gold-500/25 bg-gold-500/[0.04]" : "border-white/[0.06] bg-white/[0.015]",
        planned && "opacity-55",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 id={nameId} className="text-sm font-semibold text-zinc-100">
              {provider.display_name}
            </h3>
            {active && <Badge tone="gold">Active</Badge>}
            {planned ? (
              <Badge title={provider.status_detail || undefined}>
                <span data-testid="provider-status">{plannedLabel(provider.planned_phase)}</span>
              </Badge>
            ) : (
              <Badge tone={status.tone} title={provider.status_detail || undefined}>
                <span data-testid="provider-status">{status.label}</span>
              </Badge>
            )}
            <Badge tone={provider.is_paid ? "warning" : "success"}>{provider.is_paid ? "Paid" : "Free"}</Badge>
            {provider.is_mock && <Badge tone="violet">Mock</Badge>}
          </div>
          {provider.description && <p className="mt-1 text-xs text-zinc-400">{provider.description}</p>}
          {provider.status_detail && !planned && (
            <p className="mt-1 text-[11px] text-zinc-500" data-testid="provider-status-detail">
              {provider.status_detail}
            </p>
          )}
          <p className="mt-1 font-mono text-[11px] text-zinc-600">
            {provider.name}
            {provider.models && provider.models.length > 0 && ` · ${provider.models.join(", ")}`}
            {provider.capabilities.length > 1 && ` · ${provider.capabilities.map(humanize).join(", ")}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <PriorityInput
            key={`${provider.name}:${provider.priority}`}
            provider={provider}
            disabled={locked}
            onCommit={(priority) => onPriority(provider, priority)}
          />
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-zinc-500" aria-hidden="true">
              {provider.enabled ? "On" : "Off"}
            </span>
            <Switch
              checked={provider.enabled}
              disabled={locked}
              label={`Enable ${provider.display_name}`}
              onChange={(next) => onToggle(provider, next)}
            />
          </div>
          <Button
            variant="secondary"
            className="px-3 py-1.5 text-xs"
            disabled={planned || (busy !== null && busy !== "test")}
            busy={busy === "test"}
            onClick={() => onTest(provider)}
            aria-label={`Test ${provider.display_name}`}
          >
            Test
          </Button>
          {docs && <ExternalLink href={docs} className="text-xs">Docs</ExternalLink>}
        </div>
      </div>
      {provider.requires_key && !planned && (
        <ProviderKeyField
          provider={provider}
          disabled={busy !== null && busy !== "save-key" && busy !== "remove-key"}
          busy={busy === "save-key" ? "save" : busy === "remove-key" ? "remove" : null}
          onSave={(key) => onSaveKey(provider, key)}
          onRemove={() => onRemoveKey(provider)}
        />
      )}
    </li>
  );
}
