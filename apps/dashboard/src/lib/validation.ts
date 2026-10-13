import type { CreateProductionRequest, ProductionMode } from "@cineforge/schemas";

// Mirrors CreateProductionRequest field constraints in cineforge.contracts.api.
export const TOPIC_MIN = 3;
export const TOPIC_MAX = 500;
export const DURATION_MIN_SEC = 15;
export const DURATION_MAX_SEC = 180;
export const DEFAULT_DURATION_SEC = 45;

const MODES: readonly ProductionMode[] = ["economy", "balanced", "premium"];

export interface CreateProductionFormValues {
  themeId: string;
  topic: string;
  title: string;
  mode: ProductionMode | "";
  durationSec: string;
  /** Empty = use the mode's default budget. */
  budgetUsd: string;
  autoApprove: boolean;
}

export type CreateProductionFormErrors = Partial<Record<keyof CreateProductionFormValues, string>>;

export interface ValidationResult {
  errors: CreateProductionFormErrors;
  request: CreateProductionRequest | null;
}

function parseNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export function validateCreateProduction(values: CreateProductionFormValues): ValidationResult {
  const errors: CreateProductionFormErrors = {};

  if (!values.themeId) errors.themeId = "Choose a theme.";

  const topic = values.topic.trim();
  if (topic.length < TOPIC_MIN) errors.topic = `Topic must be at least ${TOPIC_MIN} characters.`;
  else if (topic.length > TOPIC_MAX) errors.topic = `Topic must be at most ${TOPIC_MAX} characters.`;

  if (!values.mode || !MODES.includes(values.mode)) errors.mode = "Choose a production mode.";

  const duration = parseNumber(values.durationSec);
  if (duration === null || duration < DURATION_MIN_SEC || duration > DURATION_MAX_SEC) {
    errors.durationSec = `Duration must be between ${DURATION_MIN_SEC} and ${DURATION_MAX_SEC} seconds.`;
  }

  let budget: number | null = null;
  if (values.budgetUsd.trim() !== "") {
    budget = parseNumber(values.budgetUsd);
    if (budget === null || budget <= 0) errors.budgetUsd = "Budget must be a positive amount in USD.";
    else if ((values.budgetUsd.trim().split(".")[1]?.length ?? 0) > 6) {
      errors.budgetUsd = "Budget supports at most 6 decimal places.";
    }
  }

  if (Object.keys(errors).length > 0) return { errors, request: null };

  const request: CreateProductionRequest = {
    theme_id: values.themeId,
    topic,
    mode: values.mode as ProductionMode,
    duration_target_sec: duration as number,
    auto_approve: values.autoApprove,
  };
  const title = values.title.trim();
  if (title) request.title = title;
  if (budget !== null) request.budget_limit_usd = budget;
  return { errors, request };
}
