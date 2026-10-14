import type { ThemeProfile, ThemeSummary } from "@cineforge/schemas";

export function themeProfile(version = 1, overrides: Partial<ThemeProfile> = {}): ThemeProfile {
  return {
    id: "time-traveler",
    version,
    name: "Time Traveler",
    purpose: "A curious host visits a historical landmark at a pivotal moment.",
    audience: "Curious 18-45 short-form viewers",
    genres: ["documentary-adventure", "epic"],
    tone: "Wonder-filled",
    visual_style: "Golden-hour period reconstruction",
    pacing: "Fast hook, then 5-8s scenes",
    narrative: {
      hook_strategy: "Open on a vivid moment",
      story_beats: ["hook", "arrival", "reveal"],
      factual_rigor: "strict",
      narration_style: "Second-person present tense",
      cta: "Follow for the next stop in time",
    },
    performance: { voice: "warm-curious-narrator", language: "en-US", recurring_character: "asset://characters/host-v1" },
    direction: {
      camera_grammar: ["slow_push", "drone_reveal"],
      lighting: ["golden_hour"],
      atmosphere: ["dust", "light_haze"],
      vfx_intensity: "medium",
      sound_palette: ["period_ambience"],
    },
    production: {
      preferred_strategies: ["hybrid", "licensed_still_motion"],
      min_scenes: 4,
      max_scenes: 6,
      max_shots_per_scene: 2,
      duration_target_sec: 45,
      aspect_ratio: "9:16",
      default_mode: "balanced",
      qc_thresholds: { narrative: 0.7 },
    },
    constraints: {
      prohibited_claims: ["unsourced dates"],
      rights_policy: "fail_closed",
      disclosure_rules: ["Label AI reconstructions"],
      avoid: ["anachronisms"],
    },
    ...overrides,
  };
}

export const themeSummaries: ThemeSummary[] = [
  {
    id: "time-traveler",
    version: 3,
    name: "Time Traveler",
    purpose: "Visit history",
    genres: ["documentary-adventure"],
    default_mode: "balanced",
  },
  { id: "mystery-explorer", version: 1, name: "Mystery Explorer", purpose: "Mysteries", genres: ["mystery"], default_mode: "economy" },
];
