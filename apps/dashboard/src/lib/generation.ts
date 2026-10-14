import type { AssetRecord, Shot } from "@cineforge/schemas";

export const AI_GENERATED_LABEL = "AI-generated";

export interface DisclosureBadge {
  text: string;
  title: string;
}

/** Badge for shots that carry synthetic media; the manifest's `label_text` wins over the default label. */
export function aiDisclosureBadge(shot: Pick<Shot, "disclosure">): DisclosureBadge | null {
  const disclosure = shot.disclosure;
  if (!disclosure?.synthetic_media) return null;
  const label = disclosure.label_text?.trim();
  return label
    ? { text: label, title: `${AI_GENERATED_LABEL}: ${label}` }
    : { text: AI_GENERATED_LABEL, title: `${AI_GENERATED_LABEL} (synthetic media)` };
}

export function assetIndex(assets: readonly AssetRecord[] | null | undefined): Map<string, AssetRecord> {
  const index = new Map<string, AssetRecord>();
  for (const asset of assets ?? []) if (asset.id) index.set(asset.id, asset);
  return index;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/**
 * "provider / model" of the first `generated` asset on the shot that came from a real
 * (non-mock) provider, e.g. "higgsfield / kling2_6". Null when nothing qualifies.
 */
export function generatedBy(shot: Pick<Shot, "assets">, assets: ReadonlyMap<string, AssetRecord>): string | null {
  for (const ref of shot.assets ?? []) {
    if (ref.role !== "generated") continue;
    const generation = assets.get(ref.asset_id)?.generation;
    const provider = nonEmptyString(generation?.provider);
    if (!provider || provider.toLowerCase().startsWith("mock")) continue;
    const model = nonEmptyString(generation?.model);
    return model ? `${provider} / ${model}` : provider;
  }
  return null;
}
