/* GENERATED from packages/schemas/json/contracts.schema.json - do not edit. Run `make contracts`. */

/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "HealthStatus".
 */
export type HealthStatus = "ok" | "degraded" | "down";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionMode".
 */
export type ProductionMode = "economy" | "balanced" | "premium";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionState".
 */
export type ProductionState =
  | "DRAFT"
  | "RESEARCHING"
  | "SCRIPTING"
  | "STORYBOARDING"
  | "AWAITING_APPROVAL"
  | "GENERATING"
  | "ASSEMBLING"
  | "REVIEWING"
  | "READY"
  | "DELIVERED"
  | "PAUSED_BUDGET"
  | "NEEDS_REVIEW"
  | "FAILED"
  | "CANCELLED";
/**
 * Gates of a fully generative production, cheapest first.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ApprovalStage".
 */
export type ApprovalStage = "script" | "preview" | "pilot" | "final";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ShotKind".
 */
export type ShotKind = "standard" | "a_roll" | "b_roll";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AssetRole".
 */
export type AssetRole = "source" | "reference" | "keyframe" | "generated" | "audio" | "caption" | "render";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "GenerationStrategy".
 */
export type GenerationStrategy = "licensed_still_motion" | "generative" | "hybrid" | "reuse";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProviderCapability".
 */
export type ProviderCapability =
  | "llm_text"
  | "web_research"
  | "media_search"
  | "image_generation"
  | "image_edit"
  | "video_generation"
  | "image_to_video"
  | "voice_tts"
  | "music_generation"
  | "sfx_generation"
  | "lip_sync"
  | "video_discovery"
  | "transcription"
  | "embedding";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "WorkStatus".
 */
export type WorkStatus =
  "planned" | "queued" | "in_progress" | "complete" | "approved" | "needs_repair" | "failed" | "skipped";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ReviewStatus".
 */
export type ReviewStatus = "pending" | "passed" | "failed" | "needs_human";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ReviewGate".
 */
export type ReviewGate = "research" | "media" | "script" | "scene" | "audio" | "master" | "budget";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Severity".
 */
export type Severity = "info" | "minor" | "major" | "critical";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "RetryScope".
 */
export type RetryScope = "none" | "shot" | "scene" | "audio" | "production";
/**
 * The 10 logical agents (PRD 3 section 3). Roles, not containers.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AgentId".
 */
export type AgentId =
  | "a1_master_orchestrator"
  | "a2_research"
  | "a3_media_discovery"
  | "a4_creative_director"
  | "a5_scriptwriter"
  | "a6_scene_director"
  | "a7_visual_production"
  | "a8_audio_performance"
  | "a9_editor_qc"
  | "a10_cost_optimizer";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AgentRunStatus".
 */
export type AgentRunStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ClaimStatus".
 */
export type ClaimStatus = "verified" | "unverified" | "disputed" | "dramatized";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "RightsStatus".
 */
export type RightsStatus = "approved" | "pending" | "unknown" | "blocked";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PriceUnit".
 */
export type PriceUnit =
  | "1k_tokens"
  | "1k_input_tokens"
  | "1k_output_tokens"
  | "1k_characters"
  | "image"
  | "video_second"
  | "audio_second"
  | "track"
  | "request"
  | "compute_second"
  | "gb_month"
  | "credit";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AssetKind".
 */
export type AssetKind = "image" | "video" | "audio" | "render" | "reference" | "subtitle" | "document";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AssetOrigin".
 */
export type AssetOrigin = "licensed" | "open_license" | "public_domain" | "uploaded" | "generated" | "rendered";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "LedgerStatus".
 */
export type LedgerStatus = "reserved" | "committed" | "released" | "failed";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProviderStatus".
 */
export type ProviderStatus =
  "ready" | "missing_key" | "disabled" | "blocked_paid_off" | "blocked_mock_mode" | "planned";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "KeySource".
 */
export type KeySource = "none" | "environment" | "stored";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ReferenceAngle".
 */
export type ReferenceAngle = "front" | "three_quarter" | "profile" | "close_up" | "waist_up" | "full_body" | "other";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "DiscoveryMode".
 */
export type DiscoveryMode = "popular" | "recent";
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Freshness".
 */
export type Freshness = "fresh" | "cached";

/**
 * GENERATED by scripts/export_contracts.py - do not edit.
 */
export interface CineForgeContracts {
  HealthResponse?: HealthResponse;
  ProductionSummary?: ProductionSummary;
  ProductionDetail?: ProductionDetail;
  ActionResponse?: ActionResponse;
  ErrorResponse?: ErrorResponse;
  AgentDefinition?: AgentDefinition;
  AgentRun?: AgentRun;
  ProductionManifest?: ProductionManifest;
  CostSummary?: CostSummary;
  CostOverview?: CostOverview;
  CostEstimate?: CostEstimate;
  PriceCatalogEntry?: PriceCatalogEntry;
  LedgerEvent?: LedgerEvent;
  CreditBalance?: CreditBalance;
  AssetRecord?: AssetRecord;
  ReviewReport?: ReviewReport;
  ThemeSummary?: ThemeSummary;
  ThemeProfile?: ThemeProfile;
  ProductionModePolicy?: ProductionModePolicy;
  ProviderInfo?: ProviderInfo;
  ProviderCatalogEntry?: ProviderCatalogEntry;
  ProvidersOverview?: ProvidersOverview;
  ProviderTestResult?: ProviderTestResult;
  GenerationPack?: GenerationPack;
  ExternalGenerationResponse?: ExternalGenerationResponse;
  StageQuote?: StageQuote;
  OAuthStartResponse?: OAuthStartResponse;
  ConnectorStatus?: ConnectorStatus;
  PersonaSummary?: PersonaSummary;
  PersonaDetail?: PersonaDetail;
  ProductionEvent?: ProductionEvent;
  DiscoveryRun?: DiscoveryRun;
  CreateProductionRequest?: CreateProductionRequest;
  StartDiscoveryRequest?: StartDiscoveryRequest;
  DiscoveryPageRequest?: DiscoveryPageRequest;
  ApproveProductionRequest?: ApproveProductionRequest;
  ReviewClaimsRequest?: ReviewClaimsRequest;
  UpdateProviderRequest?: UpdateProviderRequest;
  SetProviderKeyRequest?: SetProviderKeyRequest;
  CreateThemeVersionRequest?: CreateThemeVersionRequest;
  ExternalGenerationRequest?: ExternalGenerationRequest;
  ExternalGenerationComplete?: ExternalGenerationComplete;
  ExternalGenerationRelease?: ExternalGenerationRelease;
  RenderRequest?: RenderRequest;
  RegenerateShotRequest?: RegenerateShotRequest;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "HealthResponse".
 */
export interface HealthResponse {
  status: HealthStatus;
  service?: string;
  version: string;
  environment: string;
  paid_providers_enabled: boolean;
  provider_mode?: string;
  checks?: DependencyHealth[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "DependencyHealth".
 */
export interface DependencyHealth {
  name: string;
  status: HealthStatus;
  detail?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionSummary".
 */
export interface ProductionSummary {
  id: string;
  tenant_id: string;
  title: string | null;
  topic: string;
  theme_id: string;
  theme_version: number;
  mode: ProductionMode;
  state: ProductionState;
  progress_pct: number;
  approval_stage?: string | null;
  scene_count: number;
  shot_count: number;
  currency: string;
  budget_limit: number;
  estimated_cost: number;
  actual_cost: number;
  created_at: string;
  updated_at: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionDetail".
 */
export interface ProductionDetail {
  summary: ProductionSummary;
  manifest: ProductionManifest;
  agent_runs: AgentRun[];
  events: ProductionEvent[];
  cost: CostSummary;
  artifacts: ProductionArtifacts;
  assets?: AssetRecord[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionManifest".
 */
export interface ProductionManifest {
  schema_version?: "1.0";
  production_id: string;
  tenant_id: string;
  title?: string | null;
  theme_profile: ThemeRef;
  mode?: ProductionMode;
  state?: ProductionState;
  config_version?: number;
  creative_brief: CreativeBrief;
  output?: OutputProfile;
  budget: BudgetSnapshot;
  approval?: ApprovalPolicy;
  /**
   * Current gate of a fully generative production
   */
  approval_stage?: ApprovalStage | null;
  persona_id?: string | null;
  look?: ProductionLook | null;
  authored_script?: AuthoredScript | null;
  /**
   * YouTube video identity used as inspiration. No cached title or statistics.
   */
  inspiration?: InspirationReference | null;
  /**
   * Persona version pinned at creation (like the theme)
   */
  persona_version?: number | null;
  character_bible_ref?: string | null;
  style_bible_ref?: string | null;
  research_brief_ref?: string | null;
  scenes?: Scene[];
  captions?: CaptionTrack[];
  soundtrack?: Soundtrack | null;
  master_render_asset_id?: string | null;
  provenance_refs?: string[];
  review_status?: ReviewStatus;
  review_findings?: ReviewFinding[];
  /**
   * Latest decision per claim wins
   */
  claim_reviews?: ClaimReview[];
  audit?: AuditEntry[];
  created_at?: string;
  updated_at?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ThemeRef".
 */
export interface ThemeRef {
  id: string;
  version: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CreativeBrief".
 */
export interface CreativeBrief {
  topic: string;
  genre?: string | null;
  language?: string;
  audience?: string | null;
  notes?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "OutputProfile".
 */
export interface OutputProfile {
  aspect_ratio?: "9:16" | "1:1" | "16:9";
  width?: number;
  height?: number;
  fps?: number;
  codec?: string;
  audio_codec?: string;
  container?: string;
  bitrate_kbps?: number | null;
  duration_target_sec?: number;
}
/**
 * Denormalized view of the production budget; the cost ledger is authoritative.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "BudgetSnapshot".
 */
export interface BudgetSnapshot {
  currency?: string;
  limit: number;
  estimated?: number;
  reserved?: number;
  actual?: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ApprovalPolicy".
 */
export interface ApprovalPolicy {
  auto_approve?: boolean;
  approved_by?: string | null;
  approved_at?: string | null;
  note?: string | null;
}
/**
 * Per-production art direction shared by every shot (consistency across clips).
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionLook".
 */
export interface ProductionLook {
  /**
   * Replaces the persona's default wardrobe
   */
  wardrobe?: string | null;
  /**
   * Location bible: place, materials, light
   */
  location?: string | null;
  notes?: string[];
  references?: ProductionReference[];
}
/**
 * An owned or rights-approved image that guides generation; never shown on screen.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionReference".
 */
export interface ProductionReference {
  id: string;
  asset_id: string;
  description: string;
  usage?: "reference_only";
  /**
   * Provider -> uploaded media id (upload once)
   */
  provider_media?: {
    [k: string]: string;
  };
}
/**
 * A human-approved script used as-is instead of the A5 draft.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AuthoredScript".
 */
export interface AuthoredScript {
  /**
   * @minItems 2
   * @maxItems 24
   */
  lines: [ScriptLine, ScriptLine, ...ScriptLine[]];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ScriptLine".
 */
export interface ScriptLine {
  scene_order: number;
  speaker?: string;
  text: string;
  claim_ids?: string[];
  dramatized?: boolean;
  /**
   * dialogue = host on camera says text; broll = cutaway (text is spoken over it when voiceover is true, else a caption)
   */
  kind?: "narration" | "dialogue" | "broll";
  /**
   * What the camera sees (vlog themes)
   */
  visual?: string | null;
  /**
   * broll only: the host says text over it
   */
  voiceover?: boolean;
  /**
   * broll only: the host is visible
   */
  in_frame?: boolean;
  /**
   * What moves, beat by beat (video model)
   */
  motion?: string | null;
  /**
   * Ambient sound
   */
  sound?: string | null;
  on_screen_text?: string | null;
  /**
   * ProductionReference ids guiding this shot's still
   */
  refs?: string[];
  duration_sec?: number | null;
}
/**
 * Identity of a source video. No title, thumbnail, or statistics.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "InspirationReference".
 */
export interface InspirationReference {
  platform?: "youtube";
  video_id: string;
  watch_url: string;
  retrieved_at: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Scene".
 */
export interface Scene {
  id: string;
  order: number;
  title?: string;
  duration_sec: number;
  story_beat?: string;
  narration?: string | null;
  /**
   * FactClaim IDs used
   */
  facts?: string[];
  /**
   * @minItems 1
   */
  shots: [Shot, ...Shot[]];
  depends_on?: string[];
  budget_limit?: number | null;
  estimated_cost?: number;
  actual_cost?: number;
  version?: number;
  status?: WorkStatus;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Shot".
 */
export interface Shot {
  id: string;
  order: number;
  duration_sec: number;
  kind?: ShotKind;
  description?: string;
  visual: VisualSpec;
  performance?: PerformanceSpec;
  audio?: AudioSpec;
  assets?: AssetRef[];
  provider_plan?: ProviderPlan;
  attempts?: ProviderAttempt[];
  review_scores?: ReviewScore[];
  disclosure?: Disclosure;
  /**
   * Overlay text
   */
  on_screen_text?: string | null;
  /**
   * Artifact IDs
   */
  depends_on?: string[];
  estimated_cost?: number;
  actual_cost?: number;
  artifact_hash?: string | null;
  version?: number;
  status?: WorkStatus;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "VisualSpec".
 */
export interface VisualSpec {
  /**
   * e.g. wide, medium, close_up, extreme_close_up
   */
  shot_type: string;
  /**
   * e.g. static, slow_push, dolly, pan, tilt, drone
   */
  camera_motion: string;
  lens?: string | null;
  lighting?: string | null;
  atmosphere?: string | null;
  color_grade?: string | null;
  vfx?: string[];
  camera_path?: {
    [k: string]: unknown;
  } | null;
  camera_control_supported?: boolean;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PerformanceSpec".
 */
export interface PerformanceSpec {
  character_ref?: string | null;
  emotion?: string | null;
  gesture?: string | null;
  lip_sync_required?: boolean;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AudioSpec".
 */
export interface AudioSpec {
  dialogue_ref?: string | null;
  /**
   * What the host says: lip-synced on A-roll, voice-over on B-roll
   */
  dialogue_text?: string | null;
  /**
   * dialogue_text plays over this B-roll
   */
  voiceover?: boolean;
  narration_text?: string | null;
  ambience?: string | null;
  music_cue?: string | null;
  sfx?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AssetRef".
 */
export interface AssetRef {
  asset_id: string;
  role: AssetRole;
  uri?: string | null;
  /**
   * Per-asset transform, e.g. crop, ken_burns, grade
   */
  transform?: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProviderPlan".
 */
export interface ProviderPlan {
  strategy?: GenerationStrategy;
  capability?: ProviderCapability | null;
  provider?: string;
  model?: string;
  prompt_template_id?: string | null;
  prompt_template_version?: number | null;
  /**
   * Compiled prompt (short)
   */
  prompt?: string | null;
  /**
   * Storage ref for long prompts
   */
  prompt_ref?: string | null;
  negative_prompt?: string | null;
  seed?: number | null;
  reference_asset_ids?: string[];
  parameters?: {
    [k: string]: unknown;
  };
  draft_first?: boolean;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProviderAttempt".
 */
export interface ProviderAttempt {
  attempt: number;
  provider: string;
  model: string;
  status: "succeeded" | "failed";
  provider_request_id?: string | null;
  ledger_event_id?: string | null;
  cost?: number;
  error?: string | null;
  output_asset_id?: string | null;
  at?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ReviewScore".
 */
export interface ReviewScore {
  /**
   * e.g. narrative, continuity, av_sync, technical
   */
  dimension: string;
  score: number;
  notes?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Disclosure".
 */
export interface Disclosure {
  synthetic_media?: boolean;
  reconstruction?: boolean;
  label_text?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CaptionTrack".
 */
export interface CaptionTrack {
  language?: string;
  burn_in?: boolean;
  cues?: Caption[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Caption".
 */
export interface Caption {
  start_sec: number;
  end_sec: number;
  text: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Soundtrack".
 */
export interface Soundtrack {
  music_asset_id?: string | null;
  music_cue?: string | null;
  ambience?: string | null;
  loudness_target_lufs?: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ReviewFinding".
 */
export interface ReviewFinding {
  id?: string;
  gate: ReviewGate;
  severity: Severity;
  message: string;
  evidence?: string[];
  affected_artifact_ids?: string[];
  recommended_fix?: string | null;
  retry_scope?: RetryScope;
  created_at?: string;
  blocking: boolean;
}
/**
 * Human decision on a research claim at the approval gate (ENG-04).
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ClaimReview".
 */
export interface ClaimReview {
  claim_id: string;
  decision: "approved" | "rejected";
  reviewed_by?: string;
  reviewed_at?: string;
  note?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AuditEntry".
 */
export interface AuditEntry {
  at?: string;
  /**
   * agent id, 'system' or a user identifier
   */
  actor: string;
  action: string;
  details?: {
    [k: string]: unknown;
  };
}
/**
 * Persisted record of one agent invocation (shown on the dashboard).
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AgentRun".
 */
export interface AgentRun {
  id: string;
  production_id: string;
  tenant_id: string;
  agent_id: AgentId;
  step: ProductionState;
  status: AgentRunStatus;
  attempt?: number;
  idempotency_key: string;
  prompt_template_id?: string | null;
  prompt_template_version?: number | null;
  input_summary?: {
    [k: string]: unknown;
  };
  /**
   * Typed artifact as JSON
   */
  output?: {
    [k: string]: unknown;
  } | null;
  output_model?: string | null;
  error?: string | null;
  estimated_cost?: number;
  actual_cost?: number;
  started_at?: string;
  finished_at?: string | null;
}
/**
 * Immutable audit record of something that happened to a production.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionEvent".
 */
export interface ProductionEvent {
  id?: number | null;
  production_id: string;
  tenant_id: string;
  /**
   * e.g. state_changed, agent_started, budget_paused
   */
  event_type: string;
  from_state?: ProductionState | null;
  to_state?: ProductionState | null;
  message?: string;
  payload?: {
    [k: string]: unknown;
  };
  created_at?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CostSummary".
 */
export interface CostSummary {
  production_id: string;
  currency?: string;
  limit: number;
  estimated?: number;
  reserved?: number;
  actual?: number;
  remaining?: number;
  by_scene?: CostBreakdownRow[];
  by_agent?: CostBreakdownRow[];
  by_provider?: CostBreakdownRow[];
  retry_count?: number;
  cache_hits?: number;
  event_count?: number;
  /**
   * True while only mock providers are used
   */
  simulated?: boolean;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CostBreakdownRow".
 */
export interface CostBreakdownRow {
  key: string;
  label: string;
  estimated?: number;
  reserved?: number;
  actual?: number;
  event_count?: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionArtifacts".
 */
export interface ProductionArtifacts {
  plan?: ProductionPlan | null;
  treatment?: CreativeTreatment | null;
  research?: ResearchBrief | null;
  media?: AssetSelection | null;
  script?: Script | null;
  cost_plan?: CostPlan | null;
  review?: ReviewReport | null;
  master?: MasterRender | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionPlan".
 */
export interface ProductionPlan {
  production_id: string;
  mode: ProductionMode;
  steps: PlannedStep[];
  scene_count_target: number;
  budget_envelope: number;
  notes?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PlannedStep".
 */
export interface PlannedStep {
  state: ProductionState;
  agent_ids: AgentId[];
  parallel?: boolean;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CreativeTreatment".
 */
export interface CreativeTreatment {
  theme_id: string;
  theme_version: number;
  logline: string;
  genre: string;
  tone: string;
  narrative_style: string;
  visual_language: string[];
  style_bible?: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ResearchBrief".
 */
export interface ResearchBrief {
  topic: string;
  summary: string;
  claims: FactClaim[];
  unresolved_questions?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "FactClaim".
 */
export interface FactClaim {
  id: string;
  text: string;
  status: ClaimStatus;
  sources?: SourceCitation[];
  confidence: number;
  notes?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "SourceCitation".
 */
export interface SourceCitation {
  url: string;
  title: string;
  publisher?: string | null;
  published_at?: string | null;
  retrieved_at?: string;
  /**
   * Source text supporting the claim (provenance check)
   */
  excerpt?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AssetSelection".
 */
export interface AssetSelection {
  candidates: AssetCandidate[];
  selected_ids?: string[];
  /**
   * candidate_id -> reason it was blocked
   */
  blocked?: {
    [k: string]: string;
  };
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AssetCandidate".
 */
export interface AssetCandidate {
  candidate_id: string;
  provider: string;
  media_type: "image" | "video" | "audio";
  title: string;
  source_url: string;
  thumbnail_url?: string | null;
  width?: number | null;
  height?: number | null;
  license?: LicenseInfo | null;
  rights_status?: RightsStatus;
  score?: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "LicenseInfo".
 */
export interface LicenseInfo {
  /**
   * e.g. CC0, CC-BY-4.0, public-domain, commercial, customer-upload, generated, unknown
   */
  license_type: string;
  license_url?: string | null;
  author?: string | null;
  attribution_text?: string | null;
  attribution_required?: boolean;
  commercial_use_allowed?: boolean | null;
  modifications_allowed?: boolean | null;
  restrictions?: string[];
  source_provider?: string | null;
  source_url?: string | null;
  retrieved_at?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Script".
 */
export interface Script {
  hook: string;
  logline: string;
  beats: StoryBeat[];
  lines: ScriptLine[];
  cta?: string | null;
  word_count: number;
  estimated_duration_sec: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "StoryBeat".
 */
export interface StoryBeat {
  order: number;
  beat: string;
  purpose: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CostPlan".
 */
export interface CostPlan {
  production_id: string;
  estimate: CostEstimate;
  within_budget: boolean;
  recommendations?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CostEstimate".
 */
export interface CostEstimate {
  production_id: string;
  currency?: string;
  mode: ProductionMode;
  price_catalog_version: string;
  line_items?: CostLineItem[];
  total_estimated: number;
  by_scene?: {
    [k: string]: number;
  };
  by_agent?: {
    [k: string]: number;
  };
  created_at?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CostLineItem".
 */
export interface CostLineItem {
  /**
   * Stable key, e.g. 'scene_01/shot_01/a7_visual_production'
   */
  key: string;
  scene_id?: string | null;
  shot_id?: string | null;
  agent_id: AgentId;
  provider: string;
  model: string;
  capability: ProviderCapability;
  unit: PriceUnit;
  quantity: string;
  unit_price: number;
  expected_attempts?: string;
  estimated_cost: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ReviewReport".
 */
export interface ReviewReport {
  production_id: string;
  status: ReviewStatus;
  findings?: ReviewFinding[];
  scores?: ReviewScore[];
  reviewed_at?: string;
  passed: boolean;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "MasterRender".
 */
export interface MasterRender {
  asset_id: string;
  uri: string;
  duration_sec: number;
  width: number;
  height: number;
  fps: number;
  codec: string;
  audio_codec?: string | null;
  size_bytes: number;
  sha256: string;
  probe?: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AssetRecord".
 */
export interface AssetRecord {
  id?: string;
  tenant_id: string;
  production_id?: string | null;
  kind: AssetKind;
  origin: AssetOrigin;
  storage_backend: string;
  storage_key: string;
  uri: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  perceptual_hash?: string | null;
  width?: number | null;
  height?: number | null;
  duration_sec?: number | null;
  source_url?: string | null;
  source_provider?: string | null;
  license?: LicenseInfo | null;
  rights: RightsDecision;
  /**
   * provider/model/prompt refs for generated assets
   */
  generation?: {
    [k: string]: unknown;
  } | null;
  usage_cost?: number;
  metadata?: {
    [k: string]: unknown;
  };
  created_at?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "RightsDecision".
 */
export interface RightsDecision {
  status: RightsStatus;
  reasons?: string[];
  decided_by?: string;
  policy_version?: string;
  decided_at?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ActionResponse".
 */
export interface ActionResponse {
  production_id: string;
  state: ProductionState;
  message: string;
  job_id?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ErrorResponse".
 */
export interface ErrorResponse {
  error: string;
  detail?: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "AgentDefinition".
 */
export interface AgentDefinition {
  id: AgentId;
  code: string;
  name: string;
  responsibility: string;
  /**
   * Contract model name of the agent input
   */
  input_model: string;
  /**
   * Contract model name of the agent output
   */
  output_model: string;
  outputs: string[];
  key_checks: string[];
  workflow_states: ProductionState[];
  capabilities: ProviderCapability[];
  prompt_template_id: string;
  prompt_template_version?: number;
}
/**
 * Tenant-wide cost report across productions.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CostOverview".
 */
export interface CostOverview {
  tenant_id: string;
  currency?: string;
  production_count?: number;
  total_limit?: number;
  total_estimated?: number;
  total_reserved?: number;
  total_actual?: number;
  by_production?: CostBreakdownRow[];
  by_provider?: CostBreakdownRow[];
  by_agent?: CostBreakdownRow[];
  retry_count?: number;
  credit_balances?: CreditBalance[];
  simulated?: boolean;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CreditBalance".
 */
export interface CreditBalance {
  tenant_id: string;
  provider: string;
  balance: string;
  unit?: string;
  is_estimated?: boolean;
  updated_at?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PriceCatalogEntry".
 */
export interface PriceCatalogEntry {
  provider: string;
  model: string;
  capability: ProviderCapability;
  unit: PriceUnit;
  unit_price: number;
  currency?: string;
  credits_per_unit?: string | null;
  version: string;
  effective_from: string;
  effective_to?: string | null;
  notes?: string;
}
/**
 * One row of the cost ledger (PRD 3 section 9 'Ledger minimum').
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "LedgerEvent".
 */
export interface LedgerEvent {
  event_id?: string;
  tenant_id: string;
  production_id: string;
  scene_id?: string | null;
  shot_id?: string | null;
  agent_id: AgentId;
  provider: string;
  model: string;
  capability: ProviderCapability;
  provider_request_id?: string | null;
  usage_units: string;
  usage_unit: PriceUnit;
  unit_price_version: string;
  estimated_cost: number;
  reserved_cost: number;
  actual_cost?: number;
  currency?: string;
  status?: LedgerStatus;
  /**
   * Why the row is released/failed, or 'overspend: ...' when actual > reserved
   */
  status_reason?: string | null;
  attempt?: number;
  retry_reason?: string | null;
  cache_hit?: boolean;
  credits_used?: string | null;
  idempotency_key: string;
  timestamp?: string;
  updated_at?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ThemeSummary".
 */
export interface ThemeSummary {
  id: string;
  version: number;
  name: string;
  purpose: string;
  genres: string[];
  default_mode: ProductionMode;
}
/**
 * Versioned, editable creative configuration. Loaded from packages/configurations/themes.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ThemeProfile".
 */
export interface ThemeProfile {
  id: string;
  version: number;
  name: string;
  purpose: string;
  audience: string;
  /**
   * @minItems 1
   */
  genres: [string, ...string[]];
  tone: string;
  visual_style: string;
  pacing: string;
  narrative: NarrativeRules;
  performance: PerformanceRules;
  direction: DirectionRules;
  production: ProductionRules;
  constraints: ConstraintRules;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "NarrativeRules".
 */
export interface NarrativeRules {
  hook_strategy: string;
  /**
   * @minItems 1
   */
  story_beats: [string, ...string[]];
  factual_rigor?: "strict" | "moderate" | "creative";
  narration_style: string;
  cta?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PerformanceRules".
 */
export interface PerformanceRules {
  recurring_character?: string | null;
  /**
   * PersonaProfile id of the on-camera host, if any
   */
  persona_id?: string | null;
  voice: string;
  language?: string;
  accent?: string | null;
  camera_relationship?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "DirectionRules".
 */
export interface DirectionRules {
  camera_grammar?: string[];
  lighting?: string[];
  atmosphere?: string[];
  vfx_intensity?: "none" | "low" | "medium" | "high";
  crowd_rules?: string | null;
  sound_palette?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionRules".
 */
export interface ProductionRules {
  /**
   * @minItems 1
   */
  preferred_strategies: [GenerationStrategy, ...GenerationStrategy[]];
  min_scenes?: number;
  max_scenes?: number;
  max_shots_per_scene?: number;
  duration_target_sec?: number;
  aspect_ratio?: "9:16" | "1:1" | "16:9";
  resolution?: string;
  default_mode?: ProductionMode;
  qc_thresholds?: {
    [k: string]: number;
  };
  /**
   * Set for fully generative themes (host-led vlogs)
   */
  generative?: GenerativeRules | null;
}
/**
 * Fully generative productions: every frame is generated; licensed or public media
 * only steer the generator as context references and never appear on screen.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "GenerativeRules".
 */
export interface GenerativeRules {
  provider?: string;
  still: GenerativeModel;
  a_roll: GenerativeModel;
  b_roll: GenerativeModel;
  words_per_sec?: number;
  pilot_shots?: number;
  /**
   * Provider credits per production
   */
  credit_cap?: number;
  max_context_refs?: number;
  voice_model?: string;
  /**
   * Estimated credits per line
   */
  voice_credits?: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "GenerativeModel".
 */
export interface GenerativeModel {
  model: string;
  parameters?: {
    [k: string]: unknown;
  };
  min_sec?: number | null;
  max_sec?: number | null;
  /**
   * Estimated credits per call
   */
  credits?: number;
  /**
   * Estimated credits per second
   */
  credits_per_sec?: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ConstraintRules".
 */
export interface ConstraintRules {
  prohibited_claims?: string[];
  rights_policy?: string;
  disclosure_rules?: string[];
  avoid?: string[];
}
/**
 * Economy / Balanced / Premium behaviour (PRD 3 section 9).
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProductionModePolicy".
 */
export interface ProductionModePolicy {
  mode: ProductionMode;
  description: string;
  default_budget_usd: number;
  max_attempts_per_shot: number;
  /**
   * Used by preflight estimates
   */
  expected_retry_rate: number;
  generative_shot_ratio: number;
  draft_first: boolean;
  storyboard_preflight: boolean;
  quality_tier: "draft" | "standard" | "high";
  /**
   * @minItems 1
   */
  allowed_strategies: [GenerationStrategy, ...GenerationStrategy[]];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProviderInfo".
 */
export interface ProviderInfo {
  name: string;
  display_name: string;
  capabilities: ProviderCapability[];
  models: string[];
  is_mock: boolean;
  /**
   * True if invoking it can incur real spend
   */
  is_paid: boolean;
  description?: string;
  requires_key?: boolean;
  key_env_var?: string | null;
  docs_url?: string | null;
  /**
   * oauth: the stored 'key' is a token set from sign-in
   */
  auth_method?: "api_key" | "oauth";
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProviderCatalogEntry".
 */
export interface ProviderCatalogEntry {
  name: string;
  display_name: string;
  description?: string;
  capabilities: ProviderCapability[];
  models?: string[];
  is_mock: boolean;
  is_paid: boolean;
  requires_key?: boolean;
  key_env_var?: string | null;
  docs_url?: string | null;
  auth_method?: "api_key" | "oauth";
  /**
   * Set for providers listed but not implemented yet
   */
  planned_phase?: string | null;
  enabled: boolean;
  priority: number;
  status: ProviderStatus;
  status_detail?: string;
  key_source?: KeySource;
  /**
   * e.g. '...a1b2'; never the key
   */
  key_hint?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProvidersOverview".
 */
export interface ProvidersOverview {
  provider_mode: "mock" | "live";
  paid_providers_allowed: boolean;
  secrets_backend: string;
  groups: CapabilityGroup[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CapabilityGroup".
 */
export interface CapabilityGroup {
  capability: ProviderCapability;
  label: string;
  /**
   * Best (routable) first
   */
  providers: ProviderCatalogEntry[];
  /**
   * What routing would pick right now, if anything
   */
  active_provider?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ProviderTestResult".
 */
export interface ProviderTestResult {
  provider: string;
  ok: boolean;
  detail: string;
  latency_ms?: number;
  /**
   * True if the check itself costs money
   */
  paid_call?: boolean;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "GenerationPack".
 */
export interface GenerationPack {
  production_id: string;
  state: ProductionState;
  width: number;
  height: number;
  /**
   * e.g. '9:16'
   */
  aspect_ratio: string;
  scenes: GenerationPackScene[];
  shots: GenerationPackShot[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "GenerationPackScene".
 */
export interface GenerationPackScene {
  scene_id: string;
  order: number;
  duration_sec: number;
  narration?: string | null;
  /**
   * Real narration audio already attached to the scene
   */
  narration_asset_id?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "GenerationPackShot".
 */
export interface GenerationPackShot {
  scene_id: string;
  scene_order: number;
  shot_id: string;
  shot_order: number;
  duration_sec: number;
  prompt: string;
  camera_motion: string;
  /**
   * Rights-approved still to animate; None if there is none
   */
  still?: GenerationPackStill | null;
  /**
   * Still ranking score from A3
   */
  score?: number;
  /**
   * Real generated clip already attached to the shot
   */
  generated_asset_id?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "GenerationPackStill".
 */
export interface GenerationPackStill {
  candidate_id: string;
  provider: string;
  title: string;
  /**
   * Full-resolution https URL a generator can import
   */
  image_url?: string | null;
  source_url: string;
  license?: LicenseInfo | null;
  rights_status: RightsStatus;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ExternalGenerationResponse".
 */
export interface ExternalGenerationResponse {
  production_id: string;
  ledger_event: LedgerEvent;
  asset?: AssetRecord | null;
}
/**
 * Credits the next gate will spend, before the operator approves it.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "StageQuote".
 */
export interface StageQuote {
  stage: string;
  items: number;
  credits: string;
  usd: number;
  /**
   * Provider credits used so far
   */
  credits_used: string;
  credit_cap?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "OAuthStartResponse".
 */
export interface OAuthStartResponse {
  provider: string;
  authorize_url: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ConnectorStatus".
 */
export interface ConnectorStatus {
  provider: string;
  connected: boolean;
  balance_credits?: string | null;
  detail?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaSummary".
 */
export interface PersonaSummary {
  id: string;
  version: number;
  name: string;
  handle?: string | null;
  age: number;
  tagline: string;
  voice_name?: string | null;
  reference_count?: number;
  references_available?: number;
  cover_url?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaDetail".
 */
export interface PersonaDetail {
  summary: PersonaSummary;
  profile: PersonaProfile;
  canon: PersonaCanon;
  references?: PersonaReference[];
  versions?: number[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaProfile".
 */
export interface PersonaProfile {
  id: string;
  version: number;
  name: string;
  handle?: string | null;
  identity: PersonaIdentity;
  look: PersonaLook;
  wardrobe: PersonaWardrobe;
  personality: PersonaPersonality;
  voice?: PersonaVoice;
  delivery?: PersonaDelivery;
  content?: PersonaContent;
  camera?: PersonaCamera;
  /**
   * Provider -> reference element id, e.g. {'higgsfield': '<uuid>'}
   */
  provider_refs?: {
    [k: string]: string;
  };
  references?: ReferenceImage[];
  ownership: Ownership;
  disclosure?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaIdentity".
 */
export interface PersonaIdentity {
  /**
   * Personas are adults
   */
  age: number;
  pronouns?: string;
  origin?: string | null;
  based_in?: string | null;
  occupation?: string | null;
  backstory?: string;
  values?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaLook".
 */
export interface PersonaLook {
  /**
   * Appearance bible used in every image prompt
   */
  description: string;
  /**
   * Traits that must never change between shots
   */
  locks?: string[];
  /**
   * Never show (negative prompt)
   */
  avoid?: string[];
  signature_items?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaWardrobe".
 */
export interface PersonaWardrobe {
  default: string;
  rules?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaPersonality".
 */
export interface PersonaPersonality {
  summary: string;
  traits?: string[];
  humor?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaVoice".
 */
export interface PersonaVoice {
  provider?: string;
  model?: string;
  /**
   * Speech engine for text2speech_v2, e.g. elevenlabs
   */
  variant?: string | null;
  voice_type?: "preset" | "element";
  /**
   * None until a voice is chosen
   */
  voice_id?: string | null;
  voice_name?: string | null;
  /**
   * Voices sampled or saved for later
   */
  candidates?: VoiceOption[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "VoiceOption".
 */
export interface VoiceOption {
  voice_id: string;
  name: string;
  model?: string | null;
  variant?: string | null;
  note?: string | null;
}
/**
 * How the persona speaks; fed to the scriptwriter, not to the TTS engine.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaDelivery".
 */
export interface PersonaDelivery {
  pace?: string;
  energy?: string;
  catchphrases?: string[];
  greeting?: string | null;
  sign_off?: string | null;
  avoid_words?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaContent".
 */
export interface PersonaContent {
  niches?: string[];
  topics_avoid?: string[];
  tone?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaCamera".
 */
export interface PersonaCamera {
  framing?: string;
  lighting?: string;
  color?: string | null;
  notes?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ReferenceImage".
 */
export interface ReferenceImage {
  id: string;
  /**
   * File name under the persona's references/ folder
   */
  file: string;
  sha256: string;
  angle?: ReferenceAngle;
  description?: string | null;
  usage?: "reference_only";
}
/**
 * Who owns the persona and its reference media; required before any use.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Ownership".
 */
export interface Ownership {
  owner: string;
  created_by: string;
  /**
   * Tool used to create images
   */
  created_with?: string | null;
  created_on?: string | null;
  commercial_use?: boolean;
  /**
   * Rights statement, e.g. owner-created AI images
   */
  statement: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaCanon".
 */
export interface PersonaCanon {
  persona_id: string;
  /**
   * Established, never contradict
   */
  facts?: string[];
  running_jokes?: string[];
  episodes?: Episode[];
}
/**
 * One past trip, curated in canon.yaml or derived from a finished production.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "Episode".
 */
export interface Episode {
  title: string;
  place?: string | null;
  era?: string | null;
  summary?: string | null;
  production_id?: string | null;
  on?: string | null;
}
/**
 * A reference image entry and whether its file is present in storage.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "PersonaReference".
 */
export interface PersonaReference {
  id: string;
  file: string;
  angle: string;
  description?: string | null;
  available?: boolean;
  /**
   * API path to the image when available
   */
  url?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "DiscoveryRun".
 */
export interface DiscoveryRun {
  id?: string;
  tenant_id: string;
  filters: DiscoveryFilters;
  provider: string;
  is_mock: boolean;
  freshness: Freshness;
  partial?: boolean;
  warnings?: string[];
  candidates?: TrendCandidate[];
  next_cursor?: string | null;
  retrieved_at?: string;
  idempotency_key: string;
  search_pages?: number;
  seen_cursors?: string[];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "DiscoveryFilters".
 */
export interface DiscoveryFilters {
  mode?: DiscoveryMode;
  region_code?: string;
  video_category_id?: string | null;
  query?: string | null;
  lookback_days?: (1 | 7 | 30) | null;
  relevance_language?: string | null;
  page_size?: number;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "TrendCandidate".
 */
export interface TrendCandidate {
  platform?: "youtube";
  video_id: string;
  watch_url: string;
  title: string;
  channel_id: string;
  channel_name: string;
  published_at?: string | null;
  duration_sec?: number | null;
  category_id?: string | null;
  thumbnail_url?: string | null;
  view_count?: number | null;
  like_count?: number | null;
  comment_count?: number | null;
  retrieved_at: string;
  source_mode: DiscoveryMode;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CreateProductionRequest".
 */
export interface CreateProductionRequest {
  theme_id?: string;
  /**
   * Latest when omitted
   */
  theme_version?: number | null;
  topic: string;
  title?: string | null;
  mode?: ProductionMode;
  duration_target_sec?: number;
  /**
   * Defaults to the mode policy's default budget
   */
  budget_limit_usd?: number | string | null;
  language?: string;
  auto_approve?: boolean;
  idempotency_key?: string | null;
  /**
   * Fully generative themes: outfit, location, references
   */
  look?: ProductionLook | null;
  /**
   * Fully generative themes: approved script used as-is
   */
  script?: AuthoredScript | null;
  /**
   * Optional YouTube inspiration. Identity only: no title or statistics.
   */
  reference?: InspirationReference | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "StartDiscoveryRequest".
 */
export interface StartDiscoveryRequest {
  mode?: DiscoveryMode;
  region_code?: string;
  video_category_id?: string | null;
  query?: string | null;
  lookback_days?: (1 | 7 | 30) | null;
  relevance_language?: string | null;
  page_size?: number;
  idempotency_key: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "DiscoveryPageRequest".
 */
export interface DiscoveryPageRequest {
  cursor: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ApproveProductionRequest".
 */
export interface ApproveProductionRequest {
  approved_by?: string;
  note?: string | null;
  /**
   * Optional new hard cap when resuming from PAUSED_BUDGET
   */
  raise_budget_to_usd?: number | string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ReviewClaimsRequest".
 */
export interface ReviewClaimsRequest {
  reviewed_by?: string;
  /**
   * @minItems 1
   */
  decisions: [ClaimDecision, ...ClaimDecision[]];
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ClaimDecision".
 */
export interface ClaimDecision {
  claim_id: string;
  decision: "approved" | "rejected";
  note?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "UpdateProviderRequest".
 */
export interface UpdateProviderRequest {
  enabled?: boolean | null;
  priority?: number | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "SetProviderKeyRequest".
 */
export interface SetProviderKeyRequest {
  api_key: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "CreateThemeVersionRequest".
 */
export interface CreateThemeVersionRequest {
  /**
   * Must be the current latest version
   */
  base_version: number;
  profile: ThemeProfile;
}
/**
 * Reserve budget before a human-approved generation runs outside the engine.
 *
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ExternalGenerationRequest".
 */
export interface ExternalGenerationRequest {
  scene_id: string;
  /**
   * None for scene-level audio
   */
  shot_id?: string | null;
  provider: string;
  model: string;
  capability: ProviderCapability;
  /**
   * Provider quote for this one call
   */
  quoted_credits: number | string;
  /**
   * Max credits this provider may use in this production, incl. this call
   */
  credit_cap?: number | string | null;
  attempt?: number;
  requested_by?: string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ExternalGenerationComplete".
 */
export interface ExternalGenerationComplete {
  /**
   * https URL of the finished output on the provider CDN
   */
  result_url: string;
  provider_request_id: string;
  credits_used: number | string;
  prompt?: string | null;
  /**
   * A3 candidate the output was derived from (start image)
   */
  source_candidate_id?: string | null;
  parameters?: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "ExternalGenerationRelease".
 */
export interface ExternalGenerationRelease {
  reason: string;
  failed?: boolean;
  credits_used?: number | string;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "RenderRequest".
 */
export interface RenderRequest {
  requested_by?: string;
  reason?: string | null;
}
/**
 * This interface was referenced by `CineForgeContracts`'s JSON-Schema
 * via the `definition` "RegenerateShotRequest".
 */
export interface RegenerateShotRequest {
  target: "still" | "voice" | "clip";
  /**
   * What to change, added to the prompt
   */
  note?: string | null;
  /**
   * New line for voice redo (A-roll only)
   */
  dialogue_text?: string | null;
  requested_by?: string;
}

export const PRODUCTION_STATES = ["DRAFT","RESEARCHING","SCRIPTING","STORYBOARDING","AWAITING_APPROVAL","GENERATING","ASSEMBLING","REVIEWING","READY","DELIVERED","PAUSED_BUDGET","NEEDS_REVIEW","FAILED","CANCELLED"] as const;
export const HAPPY_PATH = ["DRAFT","RESEARCHING","SCRIPTING","STORYBOARDING","AWAITING_APPROVAL","GENERATING","ASSEMBLING","REVIEWING","READY","DELIVERED"] as const;
export const WORKING_STATES = ["RESEARCHING","SCRIPTING","STORYBOARDING","GENERATING","ASSEMBLING","REVIEWING"] as const;
export const TERMINAL_STATES = ["DELIVERED","FAILED","CANCELLED"] as const;
export const EXCEPTION_STATES = ["PAUSED_BUDGET","NEEDS_REVIEW","FAILED","CANCELLED"] as const;
export const ALLOWED_TRANSITIONS: Record<ProductionState, readonly ProductionState[]> = {
  "DRAFT": [
    "RESEARCHING",
    "PAUSED_BUDGET",
    "NEEDS_REVIEW",
    "FAILED",
    "CANCELLED"
  ],
  "RESEARCHING": [
    "SCRIPTING",
    "PAUSED_BUDGET",
    "NEEDS_REVIEW",
    "FAILED",
    "CANCELLED"
  ],
  "SCRIPTING": [
    "STORYBOARDING",
    "PAUSED_BUDGET",
    "NEEDS_REVIEW",
    "FAILED",
    "CANCELLED"
  ],
  "STORYBOARDING": [
    "AWAITING_APPROVAL",
    "PAUSED_BUDGET",
    "NEEDS_REVIEW",
    "FAILED",
    "CANCELLED"
  ],
  "AWAITING_APPROVAL": [
    "GENERATING",
    "PAUSED_BUDGET",
    "NEEDS_REVIEW",
    "FAILED",
    "CANCELLED"
  ],
  "GENERATING": [
    "AWAITING_APPROVAL",
    "ASSEMBLING",
    "PAUSED_BUDGET",
    "NEEDS_REVIEW",
    "FAILED",
    "CANCELLED"
  ],
  "ASSEMBLING": [
    "REVIEWING",
    "PAUSED_BUDGET",
    "NEEDS_REVIEW",
    "FAILED",
    "CANCELLED"
  ],
  "REVIEWING": [
    "GENERATING",
    "READY",
    "PAUSED_BUDGET",
    "NEEDS_REVIEW",
    "FAILED",
    "CANCELLED"
  ],
  "READY": [
    "DELIVERED",
    "PAUSED_BUDGET",
    "NEEDS_REVIEW",
    "FAILED",
    "CANCELLED"
  ],
  "DELIVERED": [],
  "PAUSED_BUDGET": [
    "AWAITING_APPROVAL",
    "GENERATING",
    "ASSEMBLING",
    "FAILED",
    "CANCELLED"
  ],
  "NEEDS_REVIEW": [
    "RESEARCHING",
    "SCRIPTING",
    "STORYBOARDING",
    "AWAITING_APPROVAL",
    "GENERATING",
    "ASSEMBLING",
    "REVIEWING",
    "READY",
    "FAILED",
    "CANCELLED"
  ],
  "FAILED": [],
  "CANCELLED": []
};
export const AGENT_DEFINITIONS: AgentDefinition[] = [
  {
    "id": "a1_master_orchestrator",
    "code": "A1",
    "name": "Master Orchestrator",
    "responsibility": "Workflow, dependencies, task delegation, budgets and escalation.",
    "input_model": "PlanningInput",
    "output_model": "ProductionPlan",
    "outputs": [
      "ProductionPlan",
      "TaskGraph"
    ],
    "key_checks": [
      "state",
      "retries",
      "budget gates"
    ],
    "workflow_states": [
      "RESEARCHING"
    ],
    "capabilities": [
      "llm_text"
    ],
    "prompt_template_id": "a1_master_orchestrator",
    "prompt_template_version": 1
  },
  {
    "id": "a2_research",
    "code": "A2",
    "name": "Research & Fact Agent",
    "responsibility": "Topics, source discovery, evidence and claim verification.",
    "input_model": "ResearchInput",
    "output_model": "ResearchBrief",
    "outputs": [
      "ResearchBrief",
      "FactClaims"
    ],
    "key_checks": [
      "claim citations",
      "ambiguity"
    ],
    "workflow_states": [
      "RESEARCHING"
    ],
    "capabilities": [
      "llm_text",
      "web_research"
    ],
    "prompt_template_id": "a2_research",
    "prompt_template_version": 2
  },
  {
    "id": "a3_media_discovery",
    "code": "A3",
    "name": "Media Discovery Agent",
    "responsibility": "Federated image/video search, rights checks, dedup and asset selection.",
    "input_model": "MediaDiscoveryInput",
    "output_model": "AssetSelection",
    "outputs": [
      "AssetCandidates",
      "AssetSelections"
    ],
    "key_checks": [
      "license",
      "authenticity",
      "quality"
    ],
    "workflow_states": [
      "RESEARCHING"
    ],
    "capabilities": [
      "media_search"
    ],
    "prompt_template_id": "a3_media_discovery",
    "prompt_template_version": 1
  },
  {
    "id": "a4_creative_director",
    "code": "A4",
    "name": "Creative Director",
    "responsibility": "Theme, genre, narrative style, visual language and creative brief.",
    "input_model": "CreativeInput",
    "output_model": "CreativeTreatment",
    "outputs": [
      "CreativeTreatment",
      "StyleBible"
    ],
    "key_checks": [
      "consistency",
      "novelty"
    ],
    "workflow_states": [
      "RESEARCHING"
    ],
    "capabilities": [
      "llm_text"
    ],
    "prompt_template_id": "a4_creative_director",
    "prompt_template_version": 2
  },
  {
    "id": "a5_scriptwriter",
    "code": "A5",
    "name": "Scriptwriter & Reasoner",
    "responsibility": "Hook, story beats, screenplay, dialogue and pacing.",
    "input_model": "ScriptInput",
    "output_model": "Script",
    "outputs": [
      "Script",
      "StoryBeats"
    ],
    "key_checks": [
      "coherence",
      "fact use",
      "word budget"
    ],
    "workflow_states": [
      "SCRIPTING"
    ],
    "capabilities": [
      "llm_text"
    ],
    "prompt_template_id": "a5_scriptwriter",
    "prompt_template_version": 2
  },
  {
    "id": "a6_scene_director",
    "code": "A6",
    "name": "Scene Director",
    "responsibility": "Scene decomposition, storyboards, shots, cinematography and prompt compilation.",
    "input_model": "SceneDirectionInput",
    "output_model": "SceneGraph",
    "outputs": [
      "SceneGraph",
      "ShotSpecs"
    ],
    "key_checks": [
      "continuity",
      "feasible shots"
    ],
    "workflow_states": [
      "STORYBOARDING"
    ],
    "capabilities": [
      "llm_text"
    ],
    "prompt_template_id": "a6_scene_director",
    "prompt_template_version": 2
  },
  {
    "id": "a7_visual_production",
    "code": "A7",
    "name": "Visual Production Agent",
    "responsibility": "Image/video provider routing, generation, reuse and shot repairs.",
    "input_model": "ShotProductionInput",
    "output_model": "RenderedShotRef",
    "outputs": [
      "RenderedShotRefs"
    ],
    "key_checks": [
      "cost",
      "artifacts",
      "temporal quality"
    ],
    "workflow_states": [
      "GENERATING"
    ],
    "capabilities": [
      "image_generation",
      "image_to_video",
      "video_generation"
    ],
    "prompt_template_id": "a7_visual_production",
    "prompt_template_version": 1
  },
  {
    "id": "a8_audio_performance",
    "code": "A8",
    "name": "Audio & Performance Agent",
    "responsibility": "Voice, multilingual speech, music, Foley, lip-sync and gestures.",
    "input_model": "AudioInput",
    "output_model": "AudioPackage",
    "outputs": [
      "AudioTracks",
      "Alignment",
      "PerformanceRefs"
    ],
    "key_checks": [
      "timing",
      "consent",
      "sync"
    ],
    "workflow_states": [
      "GENERATING"
    ],
    "capabilities": [
      "voice_tts",
      "music_generation",
      "sfx_generation",
      "lip_sync"
    ],
    "prompt_template_id": "a8_audio_performance",
    "prompt_template_version": 1
  },
  {
    "id": "a9_editor_qc",
    "code": "A9",
    "name": "Editor & QC Agent",
    "responsibility": "Timeline assembly, compositing, grading and technical/creative review.",
    "input_model": "ReviewInput",
    "output_model": "ReviewReport",
    "outputs": [
      "MasterRender",
      "ReviewReport"
    ],
    "key_checks": [
      "export",
      "continuity",
      "safety"
    ],
    "workflow_states": [
      "ASSEMBLING",
      "REVIEWING"
    ],
    "capabilities": [
      "llm_text"
    ],
    "prompt_template_id": "a9_editor_qc",
    "prompt_template_version": 1
  },
  {
    "id": "a10_cost_optimizer",
    "code": "A10",
    "name": "Cost & Optimization Agent",
    "responsibility": "Quotes, routing advice, budgets, caching and spend reports.",
    "input_model": "CostPlanningInput",
    "output_model": "CostPlan",
    "outputs": [
      "CostPlan",
      "CostLedger",
      "Alerts"
    ],
    "key_checks": [
      "hard budget enforcement"
    ],
    "workflow_states": [
      "STORYBOARDING"
    ],
    "capabilities": [],
    "prompt_template_id": "a10_cost_optimizer",
    "prompt_template_version": 1
  }
];
