#!/usr/bin/env node
/**
 * Throwaway in-memory stand-in for the CineForge FastAPI service, for working on
 * the dashboard without the Python stack. NOT the real engine: no agents, no
 * budgets, no media. It walks a production through the happy path on a timer.
 *
 *   npm run mock-api --workspace @cineforge/dashboard      # listens on :8000
 *   MOCK_API_PORT=8001 MOCK_STEP_MS=1500 node scripts/mock-api.mjs
 *
 * Then run `npm run dev` (API_INTERNAL_URL defaults to http://localhost:8000).
 * Asset content returns 404 because no media binaries exist in the repo.
 *
 * Phase 1 extras: provider catalog (/providers), theme versions, claim review,
 * rewrite-script. MOCK_PROVIDER_MODE=live and MOCK_ALLOW_PAID=true flip the
 * Sources banners; ANTHROPIC_API_KEY shows an environment-provided key.
 */
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const PORT = Number(process.env.MOCK_API_PORT ?? 8000);
const STEP_MS = Number(process.env.MOCK_STEP_MS ?? 2500);
const TENANT = "tenant_demo";
const schemas = join(dirname(fileURLToPath(import.meta.url)), "../../../packages/schemas");

const sampleManifest = JSON.parse(readFileSync(join(schemas, "fixtures/sample-manifest.json"), "utf8"));
const generatedTs = readFileSync(join(schemas, "src/contracts.generated.ts"), "utf8");
const agentsStart = generatedTs.indexOf("= [", generatedTs.indexOf("export const AGENT_DEFINITIONS")) + 2;
const AGENTS = JSON.parse(generatedTs.slice(agentsStart, generatedTs.lastIndexOf("]") + 1));
const HAPPY = JSON.parse(generatedTs.match(/HAPPY_PATH = (\[[^\]]+\])/)[1]);

const PROVIDER_MODE = process.env.MOCK_PROVIDER_MODE === "live" ? "live" : "mock";
const ALLOW_PAID = process.env.MOCK_ALLOW_PAID === "true";

const themeProfile = (id, name, purpose, genres, mode, extra = {}) => ({
  id, version: 1, name, purpose, audience: "Curious 18-45 short-form viewers", genres,
  tone: "Wonder-filled, energetic", visual_style: "Cinematic reconstruction blended with archival imagery", pacing: "Fast hook, then 5-8s scenes",
  narrative: { hook_strategy: "Open on a vivid moment with a question", story_beats: ["hook", "arrival", "context", "reveal", "legacy", "call-to-action"], factual_rigor: "strict", narration_style: "Second-person present tense, one fact per scene", cta: "Follow for more" },
  performance: { voice: "warm-curious-narrator", language: "en-US" },
  direction: { camera_grammar: ["slow_push", "drone_reveal", "tracking"], lighting: ["golden_hour", "overcast_soft"], atmosphere: ["dust", "light_haze"], vfx_intensity: "medium", sound_palette: ["period_ambience"] },
  production: { preferred_strategies: ["hybrid", "licensed_still_motion", "generative"], min_scenes: 4, max_scenes: 6, max_shots_per_scene: 2, duration_target_sec: 45, aspect_ratio: "9:16", resolution: "1080x1920", default_mode: mode, qc_thresholds: { narrative: 0.7 } },
  constraints: { prohibited_claims: ["unsourced dates", "invented quotes attributed to real people"], rights_policy: "fail_closed", disclosure_rules: ["Label AI reconstructions as \"Reconstruction\""], avoid: ["anachronisms"] },
  ...extra,
});
/** theme id -> versions, oldest first */
const THEME_VERSIONS = new Map(
  [
    themeProfile("time-traveler", "Time Traveler", "A curious host visits a historical landmark at a pivotal moment.", ["documentary-adventure", "time-travel"], "balanced"),
    themeProfile("mystery-explorer", "Mystery Explorer", "Unsolved mysteries told with evidence and suspense.", ["mystery"], "balanced"),
    themeProfile("fascinating-places", "Fascinating Places", "Remarkable places on Earth in under a minute.", ["travel"], "economy"),
  ].map((t) => [t.id, [t]]),
);
THEME_VERSIONS.get("time-traveler").push({ ...structuredClone(THEME_VERSIONS.get("time-traveler")[0]), version: 2, tone: "Wonder-filled, energetic, respectful of history" });
const latestTheme = (id) => THEME_VERSIONS.get(id)?.at(-1);
const themeSummary = (t) => ({ id: t.id, version: t.version, name: t.name, purpose: t.purpose, genres: t.genres, default_mode: t.production.default_mode });

const prov = (name, display_name, capabilities, o = {}) => ({
  name, display_name, capabilities, description: "", models: [], is_mock: false, is_paid: false, requires_key: false, key_env_var: null,
  docs_url: null, planned_phase: null, enabled: !o.is_paid, priority: o.is_mock ? 100 : 10, ...o,
});
const CAPABILITY_GROUPS = [
  ["web_research", "Research"], ["media_search", "Media search"], ["llm_text", "LLM"], ["image_generation", "Image"],
  ["video_generation", "Video"], ["voice_tts", "Voice"], ["music_generation", "Music"], ["sfx_generation", "SFX"], ["lip_sync", "Lip-sync"],
];
const PROVIDERS = [
  prov("mock-research", "Mock research", ["web_research"], { is_mock: true, description: "Deterministic offline research results" }),
  prov("wikipedia", "Wikipedia", ["web_research"], { description: "Free encyclopedia search and page extracts", docs_url: "https://www.mediawiki.org/wiki/API:Main_page" }),
  prov("mock-media", "Mock media search", ["media_search"], { is_mock: true, description: "Offline licensed-still candidates" }),
  prov("wikimedia-commons", "Wikimedia Commons", ["media_search"], { description: "Freely licensed images with license metadata", docs_url: "https://commons.wikimedia.org/wiki/Commons:API" }),
  prov("openverse", "Openverse", ["media_search"], { description: "CC-licensed images", priority: 20, docs_url: "https://api.openverse.org/v1/" }),
  prov("mock-llm", "Mock LLM", ["llm_text"], { is_mock: true, models: ["mock-llm-small"], description: "Deterministic offline LLM" }),
  prov("anthropic", "Anthropic Claude", ["llm_text"], { is_paid: true, requires_key: true, key_env_var: "ANTHROPIC_API_KEY", models: ["claude-sonnet-4-5"], description: "Structured reasoning for research, scripts and scenes", docs_url: "https://docs.anthropic.com" }),
  prov("mock-image", "Mock image", ["image_generation"], { is_mock: true, description: "Offline image generation" }),
  prov("mock-video", "Mock video", ["video_generation"], { is_mock: true, models: ["mock-video-draft", "mock-video-cinematic"], description: "Offline video generation" }),
  prov("runway", "Runway", ["video_generation"], { is_paid: true, requires_key: true, key_env_var: "RUNWAY_API_KEY", planned_phase: "2", description: "Image-to-video and text-to-video", docs_url: "https://docs.dev.runwayml.com" }),
  prov("mock-voice", "Mock voice", ["voice_tts"], { is_mock: true, models: ["mock-tts"], description: "Offline narration" }),
  prov("elevenlabs", "ElevenLabs", ["voice_tts"], { is_paid: true, requires_key: true, key_env_var: "ELEVENLABS_API_KEY", planned_phase: "2", description: "Expressive multilingual voices" }),
  prov("mock-music", "Mock music", ["music_generation"], { is_mock: true, description: "Offline music bed" }),
  prov("mock-sfx", "Mock SFX", ["sfx_generation"], { is_mock: true, description: "Offline sound effects" }),
  prov("mock-lipsync", "Mock lip-sync", ["lip_sync"], { is_mock: true, description: "Offline lip-sync" }),
];
/** provider name -> stored key (never returned) */
const storedKeys = new Map();

function catalogEntry(p) {
  const envKey = p.key_env_var ? process.env[p.key_env_var] : undefined;
  const key = envKey || storedKeys.get(p.name);
  const key_source = envKey ? "environment" : storedKeys.has(p.name) ? "stored" : "none";
  let status = "ready";
  let status_detail = p.is_mock ? "Mock provider, always available offline" : "Ready to route";
  if (p.planned_phase) [status, status_detail] = ["planned", `Planned for Phase ${p.planned_phase}`];
  else if (p.requires_key && !key) [status, status_detail] = ["missing_key", `Set ${p.key_env_var} in .env or store a key`];
  else if (!p.enabled) [status, status_detail] = ["disabled", "Disabled in Sources"];
  else if (p.is_paid && !ALLOW_PAID) [status, status_detail] = ["blocked_paid_off", "ALLOW_PAID_PROVIDERS=false"];
  else if (PROVIDER_MODE === "mock" && !p.is_mock) [status, status_detail] = ["blocked_mock_mode", "PROVIDER_MODE=mock routes only mock providers"];
  else if (PROVIDER_MODE === "live" && p.is_mock) status_detail = "Fallback when no real provider is ready";
  return { ...p, status, status_detail, key_source, key_hint: key ? `...${key.slice(-4)}` : null };
}

function providersOverview() {
  const rank = (e) => (e.status === "ready" ? 0 : e.status === "planned" ? 2 : 1);
  return {
    provider_mode: PROVIDER_MODE, paid_providers_allowed: ALLOW_PAID, secrets_backend: "memory (mock api)",
    groups: CAPABILITY_GROUPS.map(([capability, label]) => {
      const providers = PROVIDERS.filter((p) => p.capabilities.includes(capability)).map(catalogEntry)
        .sort((a, b) => rank(a) - rank(b) || a.priority - b.priority);
      return { capability, label, providers, active_provider: providers.find((e) => e.status === "ready")?.name ?? null };
    }),
  };
}

const CANDIDATES = [
  { candidate_id: "cand_tower_night", provider: "wikimedia-commons", media_type: "image", title: "Eiffel Tower illuminated, 1889 engraving", source_url: "https://commons.wikimedia.org/wiki/Category:Eiffel_Tower_in_1889", thumbnail_url: "https://picsum.photos/seed/cineforge-tower/270/480", width: 1080, height: 1920, license: { license_type: "public-domain", author: "Unknown", attribution_text: "Public domain, via Wikimedia Commons", license_url: "https://creativecommons.org/publicdomain/mark/1.0/" }, rights_status: "approved", score: 0.92 },
  { candidate_id: "cand_expo_crowd", provider: "openverse", media_type: "image", title: "Exposition Universelle crowd", source_url: "https://openverse.org/", thumbnail_url: "https://picsum.photos/seed/cineforge-crowd/270/480", license: { license_type: "CC-BY-4.0", author: "Jane Archivist", attribution_text: "\"Exposition crowd\" by Jane Archivist, CC BY 4.0" }, rights_status: "approved", score: 0.81 },
  { candidate_id: "cand_paris_map", provider: "wikimedia-commons", media_type: "image", title: "Map of Paris, 1889", source_url: "https://commons.wikimedia.org/", thumbnail_url: null, license: { license_type: "CC0", author: "Paris archives" }, rights_status: "pending", score: 0.7 },
  { candidate_id: "cand_poster", provider: "openverse", media_type: "image", title: "Untitled poster (unknown source)", source_url: "https://openverse.org/", thumbnail_url: "https://picsum.photos/seed/cineforge-poster/270/480", license: null, rights_status: "blocked", score: 0.4 },
];
const mode = (m, d, budget, attempts, retry, gen, tier, strategies) => ({
  mode: m, description: d, default_budget_usd: budget, max_attempts_per_shot: attempts, expected_retry_rate: retry,
  generative_shot_ratio: gen, draft_first: m !== "premium", storyboard_preflight: true, quality_tier: tier, allowed_strategies: strategies,
});
const MODES = [
  mode("economy", "Reuse licensed imagery, deterministic camera motion.", 3, 2, 0.1, 0, "draft", ["licensed_still_motion", "reuse"]),
  mode("balanced", "Hybrid licensed imagery plus selectively generated video.", 10, 3, 0.2, 0.3, "standard", ["licensed_still_motion", "hybrid", "generative", "reuse"]),
  mode("premium", "Higher-fidelity shots, richer VFX, more takes.", 40, 5, 0.35, 0.7, "high", ["licensed_still_motion", "hybrid", "generative", "reuse"]),
];
const price = (provider, model, capability, unit, unit_price, version = "mock-2026-10") => ({ provider, model, capability, unit, unit_price, currency: "USD", version, effective_from: "2026-10-01" });
const PRICING = [
  price("anthropic", "claude-sonnet-4-5", "llm_text", "1k_input_tokens", 0.003, "anthropic-2026-10"),
  price("anthropic", "claude-sonnet-4-5", "llm_text", "1k_output_tokens", 0.015, "anthropic-2026-10"),
  price("wikipedia", "rest-v1", "web_research", "request", 0, "open-sources-2026-10"),
  price("mock-llm", "mock-llm-small", "llm_text", "1k_tokens", 0.002),
  price("mock-research", "mock-search", "web_research", "request", 0.01),
  price("mock-video", "mock-video-draft", "image_to_video", "video_second", 0.05),
  price("mock-video", "mock-video-cinematic", "video_generation", "video_second", 0.25),
  price("mock-voice", "mock-tts", "voice_tts", "1k_characters", 0.03),
  price("mock-music", "mock-music", "music_generation", "track", 0.2),
];
const STEP_AGENTS = {
  RESEARCHING: ["a1_master_orchestrator", "a4_creative_director", "a2_research", "a3_media_discovery"],
  SCRIPTING: ["a5_scriptwriter"],
  STORYBOARDING: ["a6_scene_director", "a10_cost_optimizer"],
  GENERATING: ["a7_visual_production", "a8_audio_performance"],
  REVIEWING: ["a9_editor_qc"],
};
const WORKING = new Set(["RESEARCHING", "SCRIPTING", "STORYBOARDING", "GENERATING", "ASSEMBLING", "REVIEWING"]);
const TERMINAL = new Set(["DELIVERED", "FAILED", "CANCELLED"]);
const now = () => new Date().toISOString();
const round = (n) => Math.round(n * 10000) / 10000;

/** @type {Map<string, any>} */
const productions = new Map();

function create(body) {
  const id = `prod_${randomUUID().replace(/-/g, "").slice(0, 16)}`;
  const policy = MODES.find((m) => m.mode === (body.mode ?? "balanced")) ?? MODES[1];
  const manifest = structuredClone(sampleManifest);
  Object.assign(manifest, {
    production_id: id, title: body.title ?? null, mode: policy.mode, state: "DRAFT", scenes: [],
    theme_profile: { id: body.theme_id ?? "time-traveler", version: body.theme_version ?? latestTheme(body.theme_id ?? "time-traveler").version },
    claim_reviews: [],
    creative_brief: { ...manifest.creative_brief, topic: body.topic },
    budget: { currency: "USD", limit: Number(body.budget_limit_usd ?? policy.default_budget_usd), estimated: 0, reserved: 0, actual: 0 },
    approval: { auto_approve: Boolean(body.auto_approve) },
    output: { ...manifest.output, duration_target_sec: body.duration_target_sec ?? 45 },
    created_at: now(), updated_at: now(),
  });
  const p = { id, manifest, runs: [], events: [], artifacts: {}, retries: 0 };
  productions.set(id, p);
  event(p, null, "DRAFT", "Production created");
  return p;
}

function event(p, from, to, message) {
  p.events.push({ id: p.events.length + 1, production_id: p.id, tenant_id: TENANT, event_type: "state_changed", from_state: from, to_state: to, message, payload: {}, created_at: now() });
  p.manifest.state = to;
  p.manifest.updated_at = now();
}

function rejectedClaimIds(p) {
  const latest = new Map();
  for (const r of p.manifest.claim_reviews ?? []) latest.set(r.claim_id, r.decision);
  return [...latest].filter(([, d]) => d === "rejected").map(([id]) => id);
}

function citedRejected(p) {
  const rejected = new Set(rejectedClaimIds(p));
  return (p.artifacts.script?.lines ?? []).flatMap((l) => (l.claim_ids ?? []).filter((id) => rejected.has(id)).map((id) => ({ id, scene: l.scene_order })));
}

function runAgents(p, state) {
  for (const agent of STEP_AGENTS[state] ?? []) {
    const cost = agent === "a7_visual_production" ? 1.2 : agent === "a8_audio_performance" ? 0.45 : agent === "a10_cost_optimizer" ? 0 : 0.02;
    const def = AGENTS.find((a) => a.id === agent);
    p.runs.push({
      id: `run_${p.runs.length + 1}`, production_id: p.id, tenant_id: TENANT, agent_id: agent, step: state, status: "succeeded", attempt: 1,
      idempotency_key: `${p.id}:${state}:${agent}:production:1`, prompt_template_id: def.prompt_template_id, prompt_template_version: 1,
      output_model: def.output_model, estimated_cost: cost, actual_cost: cost,
      started_at: new Date(Date.now() - 1800).toISOString(), finished_at: now(),
    });
    p.manifest.budget.actual = round(p.manifest.budget.actual + cost);
  }
}

function doWork(p, state) {
  runAgents(p, state);
  const m = p.manifest;
  if (state === "RESEARCHING") {
    const wiki = { url: "https://en.wikipedia.org/wiki/Eiffel_Tower", title: "Eiffel Tower (Wikipedia)", publisher: "Wikipedia" };
    p.artifacts.research = {
      topic: m.creative_brief.topic, summary: "Mock research brief built from offline sources.",
      claims: [
        { id: "claim_01", text: "The tower was illuminated by gas lamps at the 1889 opening.", status: "verified", confidence: 0.9, sources: [{ ...wiki, excerpt: "lit by thousands of gas lamps" }] },
        { id: "claim_02", text: "A beacon swept the city in the national colours.", status: "unverified", confidence: 0.55 },
        { id: "claim_03", text: "Gustave Eiffel climbed to the top to raise the flag.", status: "disputed", confidence: 0.45, sources: [{ ...wiki, excerpt: "Eiffel led officials up the stairs" }] },
        { id: "claim_04", text: "The crowd fell silent as the lights came on.", status: "dramatized", confidence: 0.5 },
      ],
    };
    const blocked = Object.fromEntries(CANDIDATES.filter((c) => c.rights_status === "blocked").map((c) => [c.candidate_id, "License unknown: rights fail closed"]));
    p.artifacts.media = { candidates: structuredClone(CANDIDATES), selected_ids: CANDIDATES.filter((c) => !blocked[c.candidate_id]).map((c) => c.candidate_id), blocked };
  } else if (state === "SCRIPTING") {
    const rejected = new Set(rejectedClaimIds(p));
    const cite = (ids) => ids.filter((id) => !rejected.has(id));
    p.artifacts.script = {
      hook: "You are standing in Paris, May 1889. Look up.", logline: "A night of light.", beats: [], word_count: 24, estimated_duration_sec: 44,
      lines: sampleManifest.scenes.map((s) => ({ scene_order: s.order, speaker: "narrator", text: s.narration, claim_ids: cite(s.order === 1 ? ["claim_01"] : s.order === 4 ? ["claim_03"] : []) })),
      cta: "Follow for the next stop in time",
    };
  } else if (state === "STORYBOARDING") {
    m.scenes = structuredClone(sampleManifest.scenes);
    const stills = CANDIDATES.map((c) => c.candidate_id);
    let n = 0;
    m.scenes.forEach((s) => {
      s.estimated_cost = 0.5;
      s.shots.forEach((shot) => {
        shot.estimated_cost = 0.25;
        if (shot.provider_plan?.strategy === "licensed_still_motion") shot.assets = [{ asset_id: stills[n++ % stills.length], role: "source" }];
      });
    });
    m.budget.estimated = round(m.scenes.length * 0.5 + m.budget.actual);
    const est = m.budget.estimated;
    p.artifacts.cost_plan = {
      production_id: p.id, within_budget: est <= m.budget.limit, recommendations: [],
      estimate: {
        production_id: p.id, currency: "USD", mode: m.mode, price_catalog_version: "mock-2026-10", total_estimated: est, line_items: [], created_at: now(),
        by_scene: Object.fromEntries(m.scenes.map((s) => [s.id, s.estimated_cost])),
        by_agent: { a7_visual_production: round(est * 0.6), a8_audio_performance: round(est * 0.25), a2_research: round(est * 0.1), a5_scriptwriter: round(est * 0.05) },
      },
    };
  } else if (state === "GENERATING") {
    m.scenes.forEach((s, i) => {
      s.status = "complete";
      s.actual_cost = 0.33;
      s.shots.forEach((shot, j) => {
        const failedFirst = i === 1 && j === 0;
        if (failedFirst) p.retries += 1;
        shot.status = "complete";
        shot.actual_cost = failedFirst ? 0.3 : 0.15;
        shot.attempts = [
          ...(failedFirst ? [{ attempt: 1, provider: shot.provider_plan.provider, model: shot.provider_plan.model, status: "failed", cost: 0.15, error: "mock failure" }] : []),
          { attempt: failedFirst ? 2 : 1, provider: shot.provider_plan.provider, model: shot.provider_plan.model, status: "succeeded", cost: 0.15 },
        ];
      });
    });
  } else if (state === "ASSEMBLING") {
    m.master_render_asset_id = `ast_${p.id}_master`;
    p.artifacts.master = { asset_id: m.master_render_asset_id, uri: "local://mock", duration_sec: 44.8, width: 1080, height: 1920, fps: 30, codec: "h264", audio_codec: "aac", size_bytes: 3_400_000, sha256: "0".repeat(64) };
  } else if (state === "REVIEWING") {
    p.artifacts.review = { production_id: p.id, status: "passed", passed: true, findings: [{ gate: "master", severity: "minor", message: "Caption in scene 3 lands 120 ms late.", blocking: false }] };
  }
}

function advance(p) {
  const state = p.manifest.state;
  if (!WORKING.has(state)) return;
  doWork(p, state);
  let next = HAPPY[HAPPY.indexOf(state) + 1];
  if (next === "AWAITING_APPROVAL" && p.manifest.budget.estimated > p.manifest.budget.limit) next = "PAUSED_BUDGET";
  if (next === "AWAITING_APPROVAL" && p.manifest.approval.auto_approve) {
    event(p, state, next, "Auto-approved");
    return event(p, next, "GENERATING", "Generation started");
  }
  event(p, state, next, next === "PAUSED_BUDGET" ? "Estimate exceeds the hard budget" : "");
}

setInterval(() => productions.forEach(advance), STEP_MS).unref();

function byKey(rows) {
  const map = new Map();
  for (const [key, label, est, act] of rows) {
    const row = map.get(key) ?? { key, label, estimated: 0, actual: 0, event_count: 0 };
    row.estimated = round(row.estimated + est);
    row.actual = round(row.actual + act);
    row.event_count += 1;
    map.set(key, row);
  }
  return [...map.values()];
}

function costSummary(p) {
  const b = p.manifest.budget;
  return {
    production_id: p.id, currency: "USD", limit: b.limit, estimated: b.estimated, reserved: 0, actual: b.actual,
    remaining: round(Math.max(0, b.limit - b.actual)), retry_count: p.retries, cache_hits: 0, event_count: p.runs.length, simulated: true,
    by_scene: (p.manifest.scenes ?? []).map((s) => ({ key: s.id, label: s.title, estimated: s.estimated_cost, actual: s.actual_cost })),
    by_agent: byKey(p.runs.map((r) => [r.agent_id, `${AGENTS.find((a) => a.id === r.agent_id).code} ${AGENTS.find((a) => a.id === r.agent_id).name}`, r.estimated_cost, r.actual_cost])),
    by_provider: byKey(p.runs.filter((r) => r.actual_cost > 0).map((r) => [r.agent_id === "a7_visual_production" ? "mock-video" : "mock-llm", r.agent_id === "a7_visual_production" ? "mock-video" : "mock-llm", r.estimated_cost, r.actual_cost])),
  };
}

function summary(p) {
  const m = p.manifest;
  const idx = HAPPY.indexOf(m.state);
  return {
    id: p.id, tenant_id: TENANT, title: m.title, topic: m.creative_brief.topic, theme_id: m.theme_profile.id, theme_version: m.theme_profile.version, mode: m.mode,
    state: m.state, progress_pct: idx < 0 ? 0 : Math.round((100 * idx) / (HAPPY.length - 1)), scene_count: m.scenes.length,
    shot_count: m.scenes.reduce((n, s) => n + s.shots.length, 0), currency: "USD", budget_limit: m.budget.limit,
    estimated_cost: m.budget.estimated, actual_cost: m.budget.actual, created_at: m.created_at, updated_at: m.updated_at,
  };
}

const detail = (p) => ({ summary: summary(p), manifest: p.manifest, agent_runs: p.runs, events: p.events, cost: costSummary(p), artifacts: p.artifacts, assets: [] });

function send(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}
const fail = (res, status, error, message) => send(res, status, { error, detail: { message } });

function action(res, p, allowed, to, message, apply) {
  if (!allowed.includes(p.manifest.state)) return fail(res, 409, "invalid_state_transition", `Cannot ${message} from ${p.manifest.state}`);
  apply?.();
  event(p, p.manifest.state, to, message);
  send(res, to === "DELIVERED" || to === "CANCELLED" ? 200 : 202, { production_id: p.id, state: to, message: `${message}: now ${to}`, job_id: null });
}

createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://mock");
  let body = {};
  if (req.method !== "GET") {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    try {
      body = raw ? JSON.parse(raw) : {};
    } catch {
      return fail(res, 422, "validation_error", "Request body is not valid JSON");
    }
  }
  const path = url.pathname.replace(/\/+$/, "");
  const route = `${req.method} ${path}`;
  if (route === "GET /health") return send(res, 200, { status: "ok", service: "cineforge-api (mock)", version: "0.1.0", environment: "mock", paid_providers_enabled: ALLOW_PAID, provider_mode: PROVIDER_MODE, checks: [{ name: "database", status: "ok" }, { name: "redis", status: "ok" }, { name: "storage", status: "ok" }] });
  if (route === "GET /health/live") return send(res, 200, { status: "ok" });
  if (route === "GET /api/v1/agents") return send(res, 200, AGENTS);
  if (route === "GET /api/v1/themes") return send(res, 200, [...THEME_VERSIONS.keys()].map((id) => themeSummary(latestTheme(id))));
  const themeMatch = path.match(/^\/api\/v1\/themes\/([^/]+)(\/versions)?$/);
  if (themeMatch) {
    const id = decodeURIComponent(themeMatch[1]);
    const versions = THEME_VERSIONS.get(id);
    if (!versions) return fail(res, 404, "theme_not_found", `Theme ${id} not found`);
    if (req.method === "GET" && !themeMatch[2]) {
      const wanted = url.searchParams.get("version");
      const t = wanted ? versions.find((v) => v.version === Number(wanted)) : versions.at(-1);
      return t ? send(res, 200, t) : fail(res, 404, "theme_version_not_found", `Theme ${id} has no version ${wanted}`);
    }
    if (req.method === "GET") return send(res, 200, versions);
    if (req.method === "POST") {
      const latest = versions.at(-1);
      if (!body.profile || typeof body.profile.name !== "string" || !body.profile.name.trim()) return fail(res, 422, "validation_error", "profile.name: Field required");
      if (body.base_version !== latest.version) return fail(res, 409, "theme_version_conflict", `base_version ${body.base_version} is stale; latest is ${latest.version}`);
      const created = { ...body.profile, id, version: latest.version + 1 };
      versions.push(created);
      return send(res, 201, created);
    }
  }
  if (route === "GET /api/v1/providers") return send(res, 200, providersOverview());
  const providerMatch = path.match(/^\/api\/v1\/providers\/([^/]+)(?:\/(key|test))?$/);
  if (providerMatch) {
    const prov = PROVIDERS.find((x) => x.name === decodeURIComponent(providerMatch[1]));
    if (!prov) return fail(res, 404, "provider_not_found", `Provider ${providerMatch[1]} not found`);
    const sub = `${req.method} ${providerMatch[2] ?? ""}`;
    if (sub === "PATCH ") {
      if (prov.planned_phase) return fail(res, 409, "provider_planned", `${prov.display_name} is planned and cannot be changed yet`);
      if (body.priority != null && (!Number.isInteger(body.priority) || body.priority < 0)) return fail(res, 422, "validation_error", "priority: must be a whole number >= 0");
      if (typeof body.enabled === "boolean") prov.enabled = body.enabled;
      if (body.priority != null) prov.priority = body.priority;
      return send(res, 200, catalogEntry(prov));
    }
    if (sub === "PUT key") {
      if (typeof body.api_key !== "string" || !body.api_key.trim()) return fail(res, 422, "validation_error", "api_key: must not be empty");
      storedKeys.set(prov.name, body.api_key.trim());
      return send(res, 200, catalogEntry(prov));
    }
    if (sub === "DELETE key") {
      if (prov.key_env_var && process.env[prov.key_env_var]) return fail(res, 409, "key_from_environment", `${prov.key_env_var} is set in the environment and cannot be removed here`);
      storedKeys.delete(prov.name);
      return send(res, 200, catalogEntry(prov));
    }
    if (sub === "POST test") {
      const e = catalogEntry(prov);
      const ok = e.status === "ready" || (e.status === "blocked_mock_mode" && !prov.requires_key);
      return send(res, 200, { provider: prov.name, ok, detail: ok ? `${prov.display_name} responded (mock check)` : e.status_detail, latency_ms: ok ? 42 : 0, paid_call: false });
    }
  }
  if (route === "GET /api/v1/modes") return send(res, 200, MODES);
  if (route === "GET /api/v1/pricing") return send(res, 200, PRICING);
  if (route === "GET /api/v1/productions") return send(res, 200, [...productions.values()].reverse().map(summary));
  if (route === "POST /api/v1/productions") {
    if (typeof body.topic !== "string" || body.topic.trim().length < 3) return fail(res, 422, "validation_error", "topic: String should have at least 3 characters");
    const versions = THEME_VERSIONS.get(body.theme_id ?? "time-traveler");
    if (!versions) return fail(res, 404, "theme_not_found", `Theme ${body.theme_id} not found`);
    if (body.theme_version != null && !versions.some((v) => v.version === body.theme_version)) return fail(res, 404, "theme_version_not_found", `Theme ${body.theme_id} has no version ${body.theme_version}`);
    return send(res, 201, detail(create(body)));
  }
  if (route === "GET /api/v1/costs/overview") {
    const all = [...productions.values()];
    const sums = all.map(costSummary);
    return send(res, 200, {
      tenant_id: TENANT, currency: "USD", production_count: all.length, simulated: true, credit_balances: [],
      total_limit: round(sums.reduce((n, c) => n + c.limit, 0)), total_estimated: round(sums.reduce((n, c) => n + c.estimated, 0)),
      total_reserved: 0, total_actual: round(sums.reduce((n, c) => n + c.actual, 0)), retry_count: sums.reduce((n, c) => n + c.retry_count, 0),
      by_production: all.map((p) => ({ key: p.id, label: p.manifest.title ?? p.manifest.creative_brief.topic, estimated: p.manifest.budget.estimated, actual: p.manifest.budget.actual })),
      by_agent: byKey(sums.flatMap((c) => c.by_agent.map((r) => [r.key, r.label, r.estimated, r.actual]))),
      by_provider: byKey(sums.flatMap((c) => c.by_provider.map((r) => [r.key, r.label, r.estimated, r.actual]))),
    });
  }
  const match = path.match(/^\/api\/v1\/productions\/([^/]+)(?:\/([\w-]+))?$/);
  if (match) {
    const p = productions.get(decodeURIComponent(match[1]));
    if (!p) return fail(res, 404, "production_not_found", `Production ${match[1]} not found`);
    const sub = `${req.method} ${match[2] ?? ""}`;
    if (sub === "GET ") return send(res, 200, detail(p));
    if (sub === "GET costs") return send(res, 200, costSummary(p));
    if (sub === "GET ledger") return send(res, 200, []);
    if (sub === "POST run") return action(res, p, ["DRAFT"], "RESEARCHING", "Run");
    if (sub === "POST claims") {
      if (!["AWAITING_APPROVAL", "PAUSED_BUDGET"].includes(p.manifest.state)) return fail(res, 409, "invalid_state_transition", `Claims can only be reviewed at the approval gate, not in ${p.manifest.state}`);
      const known = new Set((p.artifacts.research?.claims ?? []).map((c) => c.id));
      const decisions = Array.isArray(body.decisions) ? body.decisions : [];
      if (decisions.length === 0) return fail(res, 422, "validation_error", "decisions: List should have at least 1 item");
      const unknown = decisions.find((d) => !known.has(d.claim_id));
      if (unknown) return fail(res, 422, "validation_error", `unknown claim id(s): ${unknown.claim_id}`);
      for (const d of decisions) p.manifest.claim_reviews.push({ claim_id: d.claim_id, decision: d.decision, note: d.note ?? null, reviewed_by: body.reviewed_by ?? "operator", reviewed_at: now() });
      return send(res, 200, detail(p));
    }
    if (sub === "POST rewrite-script") {
      if (!["AWAITING_APPROVAL", "NEEDS_REVIEW"].includes(p.manifest.state)) return fail(res, 409, "invalid_state_transition", `Cannot rewrite the script from ${p.manifest.state}`);
      if (p.manifest.state === "AWAITING_APPROVAL") event(p, "AWAITING_APPROVAL", "NEEDS_REVIEW", "Script cites rejected claims");
      event(p, "NEEDS_REVIEW", "SCRIPTING", "Rewriting script without rejected claims");
      return send(res, 202, { production_id: p.id, state: "SCRIPTING", message: "Script rewrite queued.", job_id: null });
    }
    if (sub === "POST approve") {
      const blocking = citedRejected(p);
      if (blocking.length && ["AWAITING_APPROVAL", "PAUSED_BUDGET"].includes(p.manifest.state)) {
        const first = blocking[0];
        return send(res, 409, { error: "approval_blocked", detail: `script scene(s) [${first.scene}] cite rejected claims; request a script rewrite first` });
      }
      return action(res, p, ["AWAITING_APPROVAL", "PAUSED_BUDGET"], "GENERATING", "Approve", () => {
        if (body.raise_budget_to_usd != null) p.manifest.budget.limit = Number(body.raise_budget_to_usd);
      });
    }
    if (sub === "POST cancel") return action(res, p, [...HAPPY, "PAUSED_BUDGET", "NEEDS_REVIEW"].filter((s) => !TERMINAL.has(s)), "CANCELLED", "Cancel");
    if (sub === "POST deliver") return action(res, p, ["READY"], "DELIVERED", "Deliver");
  }
  if (path.startsWith("/api/v1/assets/")) return fail(res, 404, "asset_not_found", "The mock API serves no media");
  fail(res, 404, "not_found", `${route} is not mocked`);
}).listen(PORT, () => console.log(`CineForge mock API on http://localhost:${PORT} (step ${STEP_MS} ms)`));
