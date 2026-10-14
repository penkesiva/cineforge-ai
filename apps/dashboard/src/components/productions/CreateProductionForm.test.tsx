import type { ProductionModePolicy, ThemeSummary } from "@cineforge/schemas";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { validateCreateProduction, type CreateProductionFormValues } from "@/lib/validation";
import { CreateProductionForm } from "./CreateProductionForm";

const themes: ThemeSummary[] = [
  { id: "time-traveler", version: 1, name: "Time Traveler", purpose: "Visit history", genres: ["epic"], default_mode: "balanced" },
  { id: "mystery-explorer", version: 1, name: "Mystery Explorer", purpose: "Mysteries", genres: ["mystery"], default_mode: "economy" },
];

const policy = (mode: ProductionModePolicy["mode"], budget: number): ProductionModePolicy => ({
  mode,
  description: `${mode} policy`,
  default_budget_usd: budget,
  max_attempts_per_shot: 3,
  expected_retry_rate: 0.2,
  generative_shot_ratio: 0.3,
  draft_first: true,
  storyboard_preflight: true,
  quality_tier: "standard",
  allowed_strategies: ["licensed_still_motion"],
});
const modes = [policy("economy", 3), policy("balanced", 10), policy("premium", 40)];

const valid: CreateProductionFormValues = {
  themeId: "time-traveler",
  topic: "The night the Eiffel Tower first lit up",
  title: "",
  mode: "balanced",
  durationSec: "45",
  budgetUsd: "",
  autoApprove: false,
};

describe("validateCreateProduction", () => {
  it("builds a request from valid values", () => {
    const { errors, request } = validateCreateProduction({ ...valid, title: "  Eiffel  ", budgetUsd: "12.5" });
    expect(errors).toEqual({});
    expect(request).toEqual({
      theme_id: "time-traveler",
      topic: "The night the Eiffel Tower first lit up",
      title: "Eiffel",
      mode: "balanced",
      duration_target_sec: 45,
      budget_limit_usd: 12.5,
      auto_approve: false,
    });
  });

  it("enforces topic length 3..500 after trimming", () => {
    expect(validateCreateProduction({ ...valid, topic: "  ab  " }).errors.topic).toMatch(/at least 3/);
    expect(validateCreateProduction({ ...valid, topic: "x".repeat(501) }).errors.topic).toMatch(/at most 500/);
    expect(validateCreateProduction({ ...valid, topic: "abc" }).errors.topic).toBeUndefined();
    expect(validateCreateProduction({ ...valid, topic: "x".repeat(500) }).errors.topic).toBeUndefined();
  });

  it("enforces duration 15..180", () => {
    expect(validateCreateProduction({ ...valid, durationSec: "14" }).errors.durationSec).toBeDefined();
    expect(validateCreateProduction({ ...valid, durationSec: "181" }).errors.durationSec).toBeDefined();
    expect(validateCreateProduction({ ...valid, durationSec: "abc" }).errors.durationSec).toBeDefined();
    expect(validateCreateProduction({ ...valid, durationSec: "15" }).errors.durationSec).toBeUndefined();
    expect(validateCreateProduction({ ...valid, durationSec: "180" }).errors.durationSec).toBeUndefined();
  });

  it("validates the optional budget override", () => {
    expect(validateCreateProduction({ ...valid, budgetUsd: "0" }).errors.budgetUsd).toBeDefined();
    expect(validateCreateProduction({ ...valid, budgetUsd: "-5" }).errors.budgetUsd).toBeDefined();
    expect(validateCreateProduction({ ...valid, budgetUsd: "1.1234567" }).errors.budgetUsd).toMatch(/6 decimal/);
    expect(validateCreateProduction({ ...valid, budgetUsd: "" }).request).not.toHaveProperty("budget_limit_usd");
  });

  it("requires theme and mode", () => {
    const { errors } = validateCreateProduction({ ...valid, themeId: "", mode: "" });
    expect(errors.themeId).toBeDefined();
    expect(errors.mode).toBeDefined();
  });
});

describe("CreateProductionForm", () => {
  it("shows mode default budgets and theme options", () => {
    render(<CreateProductionForm themes={themes} modes={modes} onSubmit={vi.fn()} />);
    expect(screen.getByRole("option", { name: /Balanced · \$10\.00 default budget/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Time Traveler (v1)" })).toBeInTheDocument();
    expect(screen.getByLabelText("Production mode")).toHaveValue("balanced");
    expect(screen.getByRole("switch", { name: /Auto-approve/ })).toHaveAttribute("aria-checked", "false");
  });

  it("blocks submission and shows errors for invalid input", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<CreateProductionForm themes={themes} modes={modes} onSubmit={onSubmit} />);
    await user.type(screen.getByLabelText("Topic"), "ab");
    const duration = screen.getByLabelText("Target duration (seconds)");
    await user.clear(duration);
    await user.type(duration, "200");
    await user.click(screen.getByRole("button", { name: "Create production" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Topic must be at least 3 characters.")).toBeInTheDocument();
    expect(screen.getByText("Duration must be between 15 and 180 seconds.")).toBeInTheDocument();
    expect(screen.getByLabelText("Topic")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Topic")).toHaveFocus();
  });

  it("submits a valid CreateProductionRequest", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<CreateProductionForm themes={themes} modes={modes} onSubmit={onSubmit} />);
    await user.selectOptions(screen.getByLabelText("Theme"), "mystery-explorer");
    await user.selectOptions(screen.getByLabelText("Production mode"), "premium");
    await user.type(screen.getByLabelText("Topic"), "The lost colony of Roanoke");
    await user.type(screen.getByLabelText("Budget override (USD)"), "25");
    await user.click(screen.getByRole("switch", { name: /Auto-approve/ }));
    await user.click(screen.getByRole("button", { name: "Create production" }));

    expect(onSubmit).toHaveBeenCalledWith({
      theme_id: "mystery-explorer",
      topic: "The lost colony of Roanoke",
      mode: "premium",
      duration_target_sec: 45,
      budget_limit_usd: 25,
      auto_approve: true,
    });
  });
});
