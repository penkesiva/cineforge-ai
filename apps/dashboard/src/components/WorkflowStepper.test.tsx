import { HAPPY_PATH, type ProductionEvent } from "@cineforge/schemas";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { availableActions, workflowSteps } from "@/lib/workflow";
import { happyEvents } from "@/test/fixtures";
import { WorkflowStepper } from "./WorkflowStepper";

function statuses() {
  const list = screen.getByRole("list", { name: "Workflow progress" });
  return within(list)
    .getAllByRole("listitem")
    .map((li) => [li.getAttribute("data-step"), li.getAttribute("data-status")]);
}

describe("WorkflowStepper", () => {
  it("renders every HAPPY_PATH step in order", () => {
    render(<WorkflowStepper state="DRAFT" />);
    expect(statuses().map(([step]) => step)).toEqual([...HAPPY_PATH]);
  });

  it("marks earlier steps complete and highlights the current step", () => {
    render(<WorkflowStepper state="GENERATING" events={happyEvents} />);
    expect(statuses()).toEqual([
      ["DRAFT", "complete"],
      ["RESEARCHING", "complete"],
      ["SCRIPTING", "complete"],
      ["STORYBOARDING", "complete"],
      ["AWAITING_APPROVAL", "complete"],
      ["GENERATING", "current"],
      ["ASSEMBLING", "upcoming"],
      ["REVIEWING", "upcoming"],
      ["READY", "upcoming"],
      ["DELIVERED", "upcoming"],
    ]);
    const current = screen.getAllByRole("listitem").find((li) => li.getAttribute("aria-current") === "step");
    expect(current).toHaveAttribute("data-step", "GENERATING");
    expect(screen.queryByTestId("exception-banner")).not.toBeInTheDocument();
  });

  it("marks everything complete once delivered", () => {
    render(<WorkflowStepper state="DELIVERED" />);
    expect(statuses().every(([, status]) => status === "complete")).toBe(true);
  });

  it("shows the exception banner with the latest event message and halts the step it left", () => {
    const events: ProductionEvent[] = [
      ...happyEvents,
      {
        production_id: "p",
        tenant_id: "t",
        event_type: "state_changed",
        from_state: "GENERATING",
        to_state: "PAUSED_BUDGET",
        message: "Reservation for scene_02_shot_01 would exceed the $10.00 limit",
        created_at: "2026-10-13T12:10:00Z",
      },
    ];
    render(<WorkflowStepper state="PAUSED_BUDGET" events={events} />);
    const banner = screen.getByTestId("exception-banner");
    expect(banner).toHaveAttribute("role", "alert");
    expect(banner).toHaveTextContent("Paused budget");
    expect(banner).toHaveTextContent("during Generating");
    expect(banner).toHaveTextContent("Reservation for scene_02_shot_01 would exceed the $10.00 limit");
    const byStep = Object.fromEntries(statuses());
    expect(byStep.AWAITING_APPROVAL).toBe("complete");
    expect(byStep.GENERATING).toBe("halted");
    expect(byStep.ASSEMBLING).toBe("upcoming");
  });

  it.each(["NEEDS_REVIEW", "FAILED", "CANCELLED"] as const)("falls back to a default message for %s", (state) => {
    render(<WorkflowStepper state={state} />);
    expect(screen.getByTestId("exception-banner")).toHaveAttribute("data-state", state);
    expect(statuses().every(([, status]) => status === "upcoming")).toBe(true);
  });
});

describe("workflow helpers", () => {
  it("derives available actions from the state", () => {
    expect(availableActions("DRAFT")).toEqual({ run: true, approve: false, cancel: true, deliver: false });
    expect(availableActions("AWAITING_APPROVAL")).toMatchObject({ approve: true, cancel: true });
    expect(availableActions("PAUSED_BUDGET")).toMatchObject({ approve: true, cancel: true });
    expect(availableActions("READY")).toMatchObject({ deliver: true, cancel: true });
    expect(availableActions("DELIVERED")).toEqual({ run: false, approve: false, cancel: false, deliver: false });
    expect(availableActions("FAILED").cancel).toBe(false);
  });

  it("uses the newest event when an exception state was entered more than once", () => {
    const steps = workflowSteps("NEEDS_REVIEW", [
      { production_id: "p", tenant_id: "t", event_type: "x", from_state: "SCRIPTING", to_state: "NEEDS_REVIEW", created_at: "2026-10-13T12:00:00Z" },
      { production_id: "p", tenant_id: "t", event_type: "x", from_state: "REVIEWING", to_state: "NEEDS_REVIEW", created_at: "2026-10-13T12:30:00Z" },
    ]);
    expect(steps.find((s) => s.status === "halted")?.state).toBe("REVIEWING");
  });
});
