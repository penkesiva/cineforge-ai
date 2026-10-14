import { HAPPY_PATH, type ProductionEvent, type ProductionState } from "@cineforge/schemas";

// Mirrors cineforge.contracts.workflow (not exported to TS by the schema generator).
export const WORKING_STATES: ReadonlySet<ProductionState> = new Set<ProductionState>([
  "RESEARCHING",
  "SCRIPTING",
  "STORYBOARDING",
  "GENERATING",
  "ASSEMBLING",
  "REVIEWING",
]);
export const TERMINAL_STATES: ReadonlySet<ProductionState> = new Set<ProductionState>([
  "DELIVERED",
  "FAILED",
  "CANCELLED",
]);
export const EXCEPTION_STATES: ReadonlySet<ProductionState> = new Set<ProductionState>([
  "PAUSED_BUDGET",
  "NEEDS_REVIEW",
  "FAILED",
  "CANCELLED",
]);

export type HappyPathState = (typeof HAPPY_PATH)[number];

export const isWorkingState = (state: ProductionState): boolean => WORKING_STATES.has(state);
export const isTerminalState = (state: ProductionState): boolean => TERMINAL_STATES.has(state);
export const isExceptionState = (state: ProductionState): boolean => EXCEPTION_STATES.has(state);

export function isHappyPathState(state: ProductionState): state is HappyPathState {
  return (HAPPY_PATH as readonly ProductionState[]).includes(state);
}

export interface AvailableActions {
  run: boolean;
  approve: boolean;
  cancel: boolean;
  deliver: boolean;
}

export function availableActions(state: ProductionState): AvailableActions {
  return {
    run: state === "DRAFT",
    approve: state === "AWAITING_APPROVAL" || state === "PAUSED_BUDGET",
    cancel: !isTerminalState(state),
    deliver: state === "READY",
  };
}

/** Newest event that moved the production into `state` (events may arrive in any order). */
export function latestEventInto(
  state: ProductionState,
  events: readonly ProductionEvent[],
): ProductionEvent | undefined {
  let latest: ProductionEvent | undefined;
  let latestKey = -Infinity;
  events.forEach((event, index) => {
    if (event.to_state !== state) return;
    const t = event.created_at ? Date.parse(event.created_at) : NaN;
    const key = Number.isNaN(t) ? index : t + index / 1e6;
    if (key >= latestKey) {
      latest = event;
      latestKey = key;
    }
  });
  return latest;
}

export type StepStatus = "complete" | "current" | "halted" | "upcoming";

export interface WorkflowStep {
  state: HappyPathState;
  status: StepStatus;
}

/**
 * Status of every HAPPY_PATH step. For exception states the step the production
 * left from (latest transition event) is marked "halted".
 */
export function workflowSteps(
  state: ProductionState,
  events: readonly ProductionEvent[] = [],
): WorkflowStep[] {
  let pivot: number;
  let pivotStatus: StepStatus;
  if (state === "DELIVERED") {
    pivot = HAPPY_PATH.length;
    pivotStatus = "complete";
  } else if (isHappyPathState(state)) {
    pivot = HAPPY_PATH.indexOf(state);
    pivotStatus = "current";
  } else {
    const from = latestEventInto(state, events)?.from_state;
    pivot = from && isHappyPathState(from) ? HAPPY_PATH.indexOf(from) : -1;
    pivotStatus = "halted";
  }
  return HAPPY_PATH.map((step, index) => ({
    state: step,
    status: index < pivot ? "complete" : index === pivot ? pivotStatus : "upcoming",
  }));
}

export const EXCEPTION_DEFAULT_MESSAGES: Partial<Record<ProductionState, string>> = {
  PAUSED_BUDGET: "Production paused: the next step would exceed the budget. Approve with a raised budget to resume.",
  NEEDS_REVIEW: "Quality review found blocking issues that need a human decision.",
  FAILED: "Production failed and cannot continue.",
  CANCELLED: "Production was cancelled.",
};
