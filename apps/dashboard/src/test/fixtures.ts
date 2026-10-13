import type {
  AgentId,
  AgentRun,
  CostSummary,
  ProductionArtifacts,
  ProductionDetail,
  ProductionEvent,
  ProductionManifest,
  ProductionState,
  ProductionSummary,
  Scene,
  Shot,
} from "@cineforge/schemas";
import sampleManifestJson from "../../../../packages/schemas/fixtures/sample-manifest.json";

const PRODUCTION_ID = "prod_sample0000000001";
const TENANT_ID = "tenant_demo";

function nonEmpty<T>(items: T[]): [T, ...T[]] {
  if (items.length === 0) throw new Error("sample manifest scene has no shots");
  return items as [T, ...T[]];
}

/**
 * The generated sample manifest (Pydantic `sample_manifest()`). JSON imports widen
 * literal unions and tuples, so each part is asserted against the contract type.
 */
const { scenes: sampleScenes, ...sampleRest } = sampleManifestJson;
export const sampleManifest: ProductionManifest = {
  ...(sampleRest as Omit<ProductionManifest, "scenes">),
  scenes: sampleScenes.map(({ shots, ...scene }) => ({
    ...(scene as Omit<Scene, "shots">),
    shots: nonEmpty(shots as Shot[]),
  })),
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function at(minutes: number): string {
  return new Date(Date.UTC(2026, 9, 13, 12, minutes, 0)).toISOString();
}

export function buildManifest(state: ProductionState = "GENERATING"): ProductionManifest {
  const manifest = clone(sampleManifest);
  manifest.state = state;
  manifest.budget = { currency: "USD", limit: 10, estimated: 4.2, reserved: 0.35, actual: 1.8765 };
  const scenes = manifest.scenes ?? [];
  scenes.forEach((scene, i) => {
    scene.estimated_cost = 0.6 + i * 0.1;
    scene.actual_cost = i === 0 ? 0.42 : 0;
    scene.status = i === 0 ? "complete" : i === 1 ? "in_progress" : "planned";
  });
  const firstShot = scenes[0]?.shots[0];
  if (firstShot) {
    firstShot.status = "complete";
    firstShot.estimated_cost = 0.12;
    firstShot.actual_cost = 0.1;
    firstShot.attempts = [
      { attempt: 1, provider: "mock-video", model: "mock-video-draft", status: "failed", cost: 0.05, error: "mock failure" },
      { attempt: 2, provider: "mock-video", model: "mock-video-draft", status: "succeeded", cost: 0.05 },
    ];
  }
  return manifest;
}

function run(
  agent_id: AgentId,
  step: ProductionState,
  minute: number,
  status: AgentRun["status"] = "succeeded",
  actual_cost = 0.01,
): AgentRun {
  return {
    id: `run_${agent_id}`,
    production_id: PRODUCTION_ID,
    tenant_id: TENANT_ID,
    agent_id,
    step,
    status,
    attempt: 1,
    idempotency_key: `${PRODUCTION_ID}:${step}:${agent_id}:production:1`,
    prompt_template_id: agent_id,
    prompt_template_version: 1,
    estimated_cost: actual_cost,
    actual_cost,
    started_at: at(minute),
    finished_at: status === "running" ? null : new Date(Date.parse(at(minute)) + 1500).toISOString(),
  };
}

export const agentRuns: AgentRun[] = [
  run("a1_master_orchestrator", "RESEARCHING", 1),
  run("a4_creative_director", "RESEARCHING", 2),
  run("a2_research", "RESEARCHING", 3, "succeeded", 0.0425),
  run("a3_media_discovery", "RESEARCHING", 4),
  run("a5_scriptwriter", "SCRIPTING", 5, "succeeded", 0.03),
  run("a6_scene_director", "STORYBOARDING", 6),
  run("a10_cost_optimizer", "STORYBOARDING", 7, "succeeded", 0),
  run("a7_visual_production", "GENERATING", 9, "running", 0.1),
];

function transition(from: ProductionState | null, to: ProductionState, minute: number, message = ""): ProductionEvent {
  return {
    id: minute,
    production_id: PRODUCTION_ID,
    tenant_id: TENANT_ID,
    event_type: "state_changed",
    from_state: from,
    to_state: to,
    message,
    payload: {},
    created_at: at(minute),
  };
}

export const happyEvents: ProductionEvent[] = [
  transition("DRAFT", "RESEARCHING", 1, "Production started"),
  transition("RESEARCHING", "SCRIPTING", 5),
  transition("SCRIPTING", "STORYBOARDING", 6),
  transition("STORYBOARDING", "AWAITING_APPROVAL", 7, "Estimate $4.20 within $10.00 budget"),
  transition("AWAITING_APPROVAL", "GENERATING", 8, "Approved by operator"),
];

export const costSummary: CostSummary = {
  production_id: PRODUCTION_ID,
  currency: "USD",
  limit: 10,
  estimated: 4.2,
  reserved: 0.35,
  actual: 1.8765,
  remaining: 7.7735,
  by_scene: [
    { key: "scene_01", label: "Hook", estimated: 0.6, actual: 0.42, event_count: 3 },
    { key: "scene_02", label: "Arrival", estimated: 0.7, actual: 0, event_count: 0 },
  ],
  by_agent: [
    { key: "a2_research", label: "A2 Research & Fact Agent", estimated: 0.05, actual: 0.0425, event_count: 1 },
    { key: "a7_visual_production", label: "A7 Visual Production Agent", estimated: 2.5, actual: 1.2, event_count: 4 },
  ],
  by_provider: [{ key: "mock-video", label: "mock-video", estimated: 2.5, actual: 1.2, event_count: 4 }],
  retry_count: 1,
  cache_hits: 0,
  event_count: 9,
  simulated: true,
};

export const artifacts: ProductionArtifacts = {
  research: {
    topic: sampleManifest.creative_brief.topic,
    summary: "On 6 May 1889 the tower opened the Exposition Universelle lit by thousands of gas lamps.",
    claims: [
      {
        id: "claim_01",
        text: "The tower was lit by about 10,000 gas lamps.",
        status: "verified",
        confidence: 0.92,
        sources: [{ url: "https://example.org/eiffel-1889", title: "Eiffel Tower history", publisher: "Example Archive" }],
      },
      { id: "claim_02", text: "A searchlight swept Paris from the summit.", status: "unverified", confidence: 0.6 },
    ],
  },
  script: {
    hook: "You are standing in Paris, May 1889. Look up.",
    logline: "A time traveler witnesses the first night of the Eiffel Tower.",
    beats: [{ order: 1, beat: "hook", purpose: "grab attention" }],
    lines: [
      { scene_order: 1, speaker: "narrator", text: "You are standing in Paris, May 1889." },
      { scene_order: 2, speaker: "narrator", text: "Ten thousand gas lamps flicker to life.", claim_ids: ["claim_01"] },
    ],
    cta: "Follow for the next stop in time",
    word_count: 16,
    estimated_duration_sec: 44,
  },
};

export function buildDetail(
  state: ProductionState = "GENERATING",
  overrides: Partial<ProductionDetail> = {},
): ProductionDetail {
  const manifest = buildManifest(state);
  const scenes = manifest.scenes ?? [];
  const summary: ProductionSummary = {
    id: PRODUCTION_ID,
    tenant_id: TENANT_ID,
    title: manifest.title ?? null,
    topic: manifest.creative_brief.topic,
    theme_id: manifest.theme_profile.id,
    theme_version: manifest.theme_profile.version,
    mode: manifest.mode ?? "balanced",
    state,
    progress_pct: 56,
    scene_count: scenes.length,
    shot_count: scenes.reduce((n, s) => n + s.shots.length, 0),
    currency: "USD",
    budget_limit: 10,
    estimated_cost: 4.2,
    actual_cost: 1.8765,
    created_at: at(0),
    updated_at: at(9),
  };
  return {
    summary,
    manifest,
    agent_runs: agentRuns,
    events: happyEvents,
    cost: costSummary,
    artifacts,
    assets: [],
    ...overrides,
  };
}

export const productionDetail: ProductionDetail = buildDetail();
