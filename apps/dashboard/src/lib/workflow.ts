import {
  ALLOWED_TRANSITIONS,
  EXCEPTION_STATES as EXCEPTION_STATE_LIST,
  HAPPY_PATH,
  TERMINAL_STATES as TERMINAL_STATE_LIST,
  WORKING_STATES as WORKING_STATE_LIST,
  type ProductionEvent,
  type ProductionState,
} from "@cineforge/schemas";

export const WORKING_STATES: ReadonlySet<ProductionState> = new Set<ProductionState>(WORKING_STATE_LIST);
export const TERMINAL_STATES: ReadonlySet<ProductionState> = new Set<ProductionState>(TERMINAL_STATE_LIST);
export const EXCEPTION_STATES: ReadonlySet<ProductionState> = new Set<ProductionState>(EXCEPTION_STATE_LIST);

export type HappyPathState = (typeof HAPPY_PATH)[number];

export const isWorkingState = (state: ProductionState): boolean => WORKING_STATES.has(state);
export const isTerminalState = (state: ProductionState): boolean => TERMINAL_STATES.has(state);
export const isExceptionState = (state: ProductionState): boolean => EXCEPTION_STATES.has(state);

export const canTransition = (from: ProductionState, to: ProductionState): boolean =>
  ALLOWED_TRANSITIONS[from].includes(to);

/** States where the operator reviews claims, storyboard and cost before generation. */
export const isReviewState = (state: ProductionState): boolean =>
  state === "AWAITING_APPROVAL" || state === "PAUSED_BUDGET";

/** `POST /rewrite-script` goes AWAITING_APPROVAL -> NEEDS_REVIEW -> SCRIPTING, so only these two states qualify. */
export const canRewriteScript = (state: ProductionState): boolean =>
  state === "AWAITING_APPROVAL" || state === "NEEDS_REVIEW";

export function isHappyPathState(state: ProductionState): state is HappyPathState {
  return (HAPPY_PATH as readonly ProductionState[]).includes(state);
}

export interface AvailableActions {
  run: boolean;
  approve: boolean;
  cancel: boolean;
  deliver: boolean;
  rerender: boolean;
}

export function availableActions(state: ProductionState): AvailableActions {
  return {
    run: state === "DRAFT",
    approve: isReviewState(state),
    cancel: !isTerminalState(state),
    deliver: state === "READY",
    rerender: state === "READY",
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
