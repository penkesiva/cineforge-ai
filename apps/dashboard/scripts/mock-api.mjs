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

const THEMES = [
  { id: "time-traveler", version: 1, name: "Time Traveler", purpose: "A curious host visits a historical landmark at a pivotal moment.", genres: ["documentary-adventure"], default_mode: "balanced" },
  { id: "mystery-explorer", version: 1, name: "Mystery Explorer", purpose: "Unsolved mysteries told with evidence and suspense.", genres: ["mystery"], default_mode: "balanced" },
  { id: "fascinating-places", version: 1, name: "Fascinating Places", purpose: "Remarkable places on Earth in under a minute.", genres: ["travel"], default_mode: "economy" },
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
const price = (provider, model, capability, unit, unit_price) => ({ provider, model, capability, unit, unit_price, currency: "USD", version: "mock-2026-10", effective_from: "2026-10-01" });
const PRICING = [
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
    theme_profile: { id: body.theme_id ?? "time-traveler", version: 1 },
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
    p.artifacts.research = {
      topic: m.creative_brief.topic, summary: "Mock research brief.",
      claims: [
        { id: "claim_01", text: "The tower was illuminated by gas lamps at the 1889 opening.", status: "verified", confidence: 0.9, sources: [{ url: "https://en.wikipedia.org/wiki/Eiffel_Tower", title: "Eiffel Tower (Wikipedia)" }] },
        { id: "claim_02", text: "A beacon swept the city in the national colours.", status: "unverified", confidence: 0.55 },
      ],
    };
  } else if (state === "SCRIPTING") {
    p.artifacts.script = {
      hook: "You are standing in Paris, May 1889. Look up.", logline: "A night of light.", beats: [], word_count: 24, estimated_duration_sec: 44,
      lines: sampleManifest.scenes.map((s) => ({ scene_order: s.order, speaker: "narrator", text: s.narration })),
      cta: "Follow for the next stop in time",
    };
  } else if (state === "STORYBOARDING") {
    m.scenes = structuredClone(sampleManifest.scenes);
    m.scenes.forEach((s) => {
      s.estimated_cost = 0.5;
      s.shots.forEach((shot) => (shot.estimated_cost = 0.25));
    });
    m.budget.estimated = round(m.scenes.length * 0.5 + m.budget.actual);
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
    id: p.id, tenant_id: TENANT, title: m.title, topic: m.creative_brief.topic, theme_id: m.theme_profile.id, theme_version: 1, mode: m.mode,
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
  if (req.method === "POST") {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    body = raw ? JSON.parse(raw) : {};
  }
  const path = url.pathname.replace(/\/+$/, "");
  const route = `${req.method} ${path}`;
  if (route === "GET /health") return send(res, 200, { status: "ok", service: "cineforge-api (mock)", version: "0.1.0", environment: "mock", paid_providers_enabled: false, checks: [{ name: "database", status: "ok" }, { name: "redis", status: "ok" }, { name: "storage", status: "ok" }] });
  if (route === "GET /health/live") return send(res, 200, { status: "ok" });
  if (route === "GET /api/v1/agents") return send(res, 200, AGENTS);
  if (route === "GET /api/v1/themes") return send(res, 200, THEMES);
  if (route === "GET /api/v1/modes") return send(res, 200, MODES);
  if (route === "GET /api/v1/pricing") return send(res, 200, PRICING);
  if (route === "GET /api/v1/productions") return send(res, 200, [...productions.values()].reverse().map(summary));
  if (route === "POST /api/v1/productions") {
    if (typeof body.topic !== "string" || body.topic.trim().length < 3) return fail(res, 422, "validation_error", "topic: String should have at least 3 characters");
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
  const match = path.match(/^\/api\/v1\/productions\/([^/]+)(?:\/(\w+))?$/);
  if (match) {
    const p = productions.get(decodeURIComponent(match[1]));
    if (!p) return fail(res, 404, "production_not_found", `Production ${match[1]} not found`);
    const sub = `${req.method} ${match[2] ?? ""}`;
    if (sub === "GET ") return send(res, 200, detail(p));
    if (sub === "GET costs") return send(res, 200, costSummary(p));
    if (sub === "GET ledger") return send(res, 200, []);
    if (sub === "POST run") return action(res, p, ["DRAFT"], "RESEARCHING", "Run");
    if (sub === "POST approve") {
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
