import * as schemas from "@cineforge/schemas";
import { describe, expect, it } from "vitest";
import {
  availableActions,
  canRewriteScript,
  canTransition,
  EXCEPTION_STATES,
  isExceptionState,
  isReviewState,
  isTerminalState,
  isWorkingState,
  TERMINAL_STATES,
  WORKING_STATES,
} from "./workflow";

describe("workflow constants", () => {
  it("come from the generated @cineforge/schemas exports", () => {
    expect([...WORKING_STATES]).toEqual([...schemas.WORKING_STATES]);
    expect([...TERMINAL_STATES]).toEqual([...schemas.TERMINAL_STATES]);
    expect([...EXCEPTION_STATES]).toEqual([...schemas.EXCEPTION_STATES]);
  });

  it("classify every production state consistently with the generated lists", () => {
    for (const state of schemas.PRODUCTION_STATES) {
      expect(isWorkingState(state)).toBe((schemas.WORKING_STATES as readonly string[]).includes(state));
      expect(isTerminalState(state)).toBe((schemas.TERMINAL_STATES as readonly string[]).includes(state));
      expect(isExceptionState(state)).toBe((schemas.EXCEPTION_STATES as readonly string[]).includes(state));
    }
  });

  it("checks transitions against ALLOWED_TRANSITIONS", () => {
    for (const from of schemas.PRODUCTION_STATES) {
      for (const to of schemas.PRODUCTION_STATES) {
        expect(canTransition(from, to)).toBe(schemas.ALLOWED_TRANSITIONS[from].includes(to));
      }
    }
    expect(canTransition("AWAITING_APPROVAL", "GENERATING")).toBe(true);
    expect(canTransition("DELIVERED", "READY")).toBe(false);
  });

  it("treats only the approval gate and budget pause as review states", () => {
    const review = schemas.PRODUCTION_STATES.filter(isReviewState);
    expect(review).toEqual(["AWAITING_APPROVAL", "PAUSED_BUDGET"]);
    expect(availableActions("PAUSED_BUDGET").approve).toBe(true);
    expect(availableActions("GENERATING").approve).toBe(false);
  });

  it("allows a script rewrite only where the API accepts it", () => {
    expect(schemas.PRODUCTION_STATES.filter(canRewriteScript)).toEqual(["AWAITING_APPROVAL", "NEEDS_REVIEW"]);
    expect(canTransition("AWAITING_APPROVAL", "NEEDS_REVIEW") && canTransition("NEEDS_REVIEW", "SCRIPTING")).toBe(true);
    expect(canTransition("PAUSED_BUDGET", "NEEDS_REVIEW")).toBe(false);
  });
});
