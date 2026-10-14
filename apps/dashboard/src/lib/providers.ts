import type { ProviderCatalogEntry, ProviderStatus } from "@cineforge/schemas";

type StatusTone = "success" | "warning" | "neutral" | "info" | "danger";

export const PROVIDER_STATUS: Record<ProviderStatus, { label: string; tone: StatusTone }> = {
  ready: { label: "Ready", tone: "success" },
  missing_key: { label: "Missing key", tone: "warning" },
  disabled: { label: "Disabled", tone: "neutral" },
  blocked_paid_off: { label: "Blocked: paid calls off", tone: "warning" },
  blocked_mock_mode: { label: "Blocked: mock mode", tone: "info" },
  planned: { label: "Planned", tone: "neutral" },
};

/** "2" / "phase 2" / "Phase 2" -> "Planned (Phase 2)". */
export function plannedLabel(phase: string | null | undefined): string {
  const raw = (phase ?? "").trim();
  if (!raw) return "Planned";
  const digits = raw.match(/^(?:phase\s*)?(\d+)$/i);
  return `Planned (${digits ? `Phase ${digits[1]}` : raw})`;
}

export const isPlanned = (p: ProviderCatalogEntry): boolean => p.status === "planned" || Boolean(p.planned_phase);

/** Human description of where the provider's key comes from; never includes the key itself. */
export function keySourceLabel(p: ProviderCatalogEntry): string {
  switch (p.key_source ?? "none") {
    case "environment":
      return `Set via environment${p.key_env_var ? ` (${p.key_env_var})` : ""}`;
    case "stored":
      return `Stored key${p.key_hint ? ` ${p.key_hint}` : ""}`;
    default:
      return "No key set";
  }
}
