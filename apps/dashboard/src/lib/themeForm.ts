import type { NarrativeRules, ThemeProfile } from "@cineforge/schemas";

export type FactualRigor = NonNullable<NarrativeRules["factual_rigor"]>;
export const FACTUAL_RIGOR: readonly FactualRigor[] = ["strict", "moderate", "creative"];

/** Editable subset of a ThemeProfile; every other field is carried over from the base version. */
export interface ThemeFormValues {
  name: string;
  purpose: string;
  audience: string;
  tone: string;
  visualStyle: string;
  pacing: string;
  hookStrategy: string;
  /** One beat per line. */
  storyBeats: string;
  factualRigor: FactualRigor;
  narrationStyle: string;
  cta: string;
  /** Comma-separated lists. */
  cameraGrammar: string;
  lighting: string;
  atmosphere: string;
  durationTargetSec: string;
  minScenes: string;
  maxScenes: string;
  /** One claim per line. */
  prohibitedClaims: string;
}

export type ThemeFormErrors = Partial<Record<keyof ThemeFormValues, string>>;

export function themeToForm(profile: ThemeProfile): ThemeFormValues {
  const { narrative, direction, production, constraints } = profile;
  return {
    name: profile.name,
    purpose: profile.purpose,
    audience: profile.audience,
    tone: profile.tone,
    visualStyle: profile.visual_style,
    pacing: profile.pacing,
    hookStrategy: narrative.hook_strategy,
    storyBeats: narrative.story_beats.join("\n"),
    factualRigor: narrative.factual_rigor ?? "strict",
    narrationStyle: narrative.narration_style,
    cta: narrative.cta ?? "",
    cameraGrammar: (direction.camera_grammar ?? []).join(", "),
    lighting: (direction.lighting ?? []).join(", "),
    atmosphere: (direction.atmosphere ?? []).join(", "),
    durationTargetSec: String(production.duration_target_sec ?? 45),
    minScenes: String(production.min_scenes ?? 4),
    maxScenes: String(production.max_scenes ?? 6),
    prohibitedClaims: (constraints.prohibited_claims ?? []).join("\n"),
  };
}

export const splitLines = (raw: string): string[] =>
  raw
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);

export const splitCommas = (raw: string): string[] =>
  raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

const REQUIRED: ReadonlyArray<[keyof ThemeFormValues, string]> = [
  ["name", "Name"],
  ["purpose", "Purpose"],
  ["audience", "Audience"],
  ["tone", "Tone"],
  ["visualStyle", "Visual style"],
  ["pacing", "Pacing"],
  ["hookStrategy", "Hook strategy"],
  ["narrationStyle", "Narration style"],
];

function positiveInt(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const n = Number(trimmed);
  return n >= 1 ? n : null;
}

export interface ThemeFormResult {
  errors: ThemeFormErrors;
  profile: ThemeProfile | null;
}

/** Full profile for `POST /themes/{id}/versions`; the server overwrites id/version. */
export function buildThemeProfile(base: ThemeProfile, values: ThemeFormValues): ThemeFormResult {
  const errors: ThemeFormErrors = {};
  for (const [key, label] of REQUIRED) {
    if (!values[key].trim()) errors[key] = `${label} is required.`;
  }

  const beats = splitLines(values.storyBeats);
  if (beats.length === 0) errors.storyBeats = "Add at least one story beat.";

  if (!FACTUAL_RIGOR.includes(values.factualRigor)) errors.factualRigor = "Choose a factual rigor.";

  const durationRaw = values.durationTargetSec.trim();
  const duration = /^\d+(\.\d+)?$/.test(durationRaw) ? Number(durationRaw) : NaN;
  if (!(duration > 0)) errors.durationTargetSec = "Duration must be a positive number of seconds.";

  const minScenes = positiveInt(values.minScenes);
  const maxScenes = positiveInt(values.maxScenes);
  if (minScenes === null) errors.minScenes = "Min scenes must be a whole number of at least 1.";
  if (maxScenes === null) errors.maxScenes = "Max scenes must be a whole number of at least 1.";
  else if (minScenes !== null && maxScenes < minScenes) errors.maxScenes = "Max scenes must be at least min scenes.";

  if (Object.keys(errors).length > 0) return { errors, profile: null };

  const cta = values.cta.trim();
  const profile: ThemeProfile = {
    ...base,
    version: base.version + 1,
    name: values.name.trim(),
    purpose: values.purpose.trim(),
    audience: values.audience.trim(),
    tone: values.tone.trim(),
    visual_style: values.visualStyle.trim(),
    pacing: values.pacing.trim(),
    narrative: {
      ...base.narrative,
      hook_strategy: values.hookStrategy.trim(),
      story_beats: beats as [string, ...string[]],
      factual_rigor: values.factualRigor,
      narration_style: values.narrationStyle.trim(),
      cta: cta || null,
    },
    direction: {
      ...base.direction,
      camera_grammar: splitCommas(values.cameraGrammar),
      lighting: splitCommas(values.lighting),
      atmosphere: splitCommas(values.atmosphere),
    },
    production: {
      ...base.production,
      duration_target_sec: duration,
      min_scenes: minScenes as number,
      max_scenes: maxScenes as number,
    },
    constraints: {
      ...base.constraints,
      prohibited_claims: splitLines(values.prohibitedClaims),
    },
  };
  return { errors, profile };
}
