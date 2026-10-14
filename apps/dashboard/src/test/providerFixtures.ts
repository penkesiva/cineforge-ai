import type { ProviderCatalogEntry, ProvidersOverview } from "@cineforge/schemas";

export function provider(overrides: Partial<ProviderCatalogEntry> & Pick<ProviderCatalogEntry, "name">): ProviderCatalogEntry {
  return {
    display_name: overrides.name,
    description: "",
    capabilities: ["llm_text"],
    models: [],
    is_mock: false,
    is_paid: false,
    requires_key: false,
    key_env_var: null,
    docs_url: null,
    planned_phase: null,
    enabled: true,
    priority: 10,
    status: "ready",
    status_detail: "",
    key_source: "none",
    key_hint: null,
    ...overrides,
  };
}

export const mockLlm = provider({
  name: "mock-llm",
  display_name: "Mock LLM",
  description: "Deterministic offline LLM",
  is_mock: true,
  priority: 100,
  status: "ready",
  status_detail: "Mock provider, always available",
});

export const anthropic = provider({
  name: "anthropic",
  display_name: "Anthropic Claude",
  description: "Claude for structured reasoning",
  is_paid: true,
  requires_key: true,
  key_env_var: "ANTHROPIC_API_KEY",
  docs_url: "https://docs.anthropic.com",
  enabled: false,
  status: "missing_key",
  status_detail: "Set ANTHROPIC_API_KEY or store a key",
});

export const wikipedia = provider({
  name: "wikipedia",
  display_name: "Wikipedia",
  description: "Free encyclopedia search",
  capabilities: ["web_research"],
  status: "blocked_mock_mode",
  status_detail: "PROVIDER_MODE=mock routes only mock providers",
});

export const runway = provider({
  name: "runway",
  display_name: "Runway",
  description: "Image to video",
  capabilities: ["image_to_video"],
  is_paid: true,
  requires_key: true,
  key_env_var: "RUNWAY_API_KEY",
  enabled: false,
  planned_phase: "2",
  status: "planned",
});

export function buildOverview(overrides: Partial<ProvidersOverview> = {}): ProvidersOverview {
  return {
    provider_mode: "mock",
    paid_providers_allowed: false,
    secrets_backend: "memory",
    groups: [
      { capability: "web_research", label: "Research", providers: [wikipedia], active_provider: null },
      { capability: "llm_text", label: "LLM", providers: [mockLlm, anthropic], active_provider: "mock-llm" },
      { capability: "image_to_video", label: "Video", providers: [runway], active_provider: null },
    ],
    ...overrides,
  };
}
