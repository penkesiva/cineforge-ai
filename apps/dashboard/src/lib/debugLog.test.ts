import { describe, expect, it } from "vitest";
import {
  collectProductionIssues,
  filterOpenIssues,
  formatDebugLog,
  selectProductionsToInspect,
} from "./debugLog";
import type { ProductionDetail, ProductionSummary } from "@cineforge/schemas";

function summary(partial: Partial<ProductionSummary> & Pick<ProductionSummary, "id" | "state">): ProductionSummary {
  return {
    tenant_id: "tenant_demo",
    title: partial.title ?? null,
    topic: "topic",
    theme_id: "lena-vlog",
    theme_version: 1,
    mode: "premium",
    progress_pct: 0,
    scene_count: 1,
    shot_count: 1,
    currency: "USD",
    budget_limit: 10,
    estimated_cost: 1,
    actual_cost: 0,
    created_at: "2026-10-15T00:00:00Z",
    updated_at: partial.updated_at ?? "2026-10-15T12:00:00Z",
    ...partial,
  };
}

describe("debugLog", () => {
  it("prefers failed and awaiting productions over delivered demos", () => {
    const rows = [
      summary({ id: "prod_old", state: "DELIVERED", updated_at: "2026-10-14T00:00:00Z", title: "E2E Eiffel" }),
      summary({ id: "prod_fail", state: "FAILED", updated_at: "2026-10-15T10:00:00Z", title: "Lepakshi" }),
      summary({
        id: "prod_wait",
        state: "AWAITING_APPROVAL",
        updated_at: "2026-10-15T11:00:00Z",
        approval_stage: "preview",
        title: "Lepakshi",
      }),
    ];
    expect(selectProductionsToInspect(rows, 2).map((r) => r.id)).toEqual(["prod_wait", "prod_fail"]);
  });

  it("hides resolved shot failures after stage_ready", () => {
    const detail = {
      summary: summary({
        id: "prod_a",
        state: "AWAITING_APPROVAL",
        title: "Lena at Lepakshi",
        approval_stage: "pilot",
      }),
      events: [
        {
          production_id: "prod_a",
          tenant_id: "tenant_demo",
          event_type: "stage_failed",
          message: "scene_01_shot_02 clip failed: preset notice",
          created_at: "2026-10-16T04:07:00Z",
        },
        {
          production_id: "prod_a",
          tenant_id: "tenant_demo",
          event_type: "stage_ready",
          message: "Pilot clips ready for review",
          created_at: "2026-10-16T04:15:00Z",
        },
      ],
      agent_runs: [
        {
          id: "run_1",
          production_id: "prod_a",
          tenant_id: "tenant_demo",
          agent_id: "a7_visual_production",
          step: "GENERATING",
          status: "failed",
          attempt: 4,
          idempotency_key: "k",
          error: "scene_01_shot_02 clip failed: preset",
          finished_at: "2026-10-16T04:07:00Z",
        },
      ],
      manifest: {
        production_id: "prod_a",
        tenant_id: "tenant_demo",
        theme_id: "lena-vlog",
        theme_version: 1,
        mode: "premium",
        topic: "Lepakshi",
        state: "AWAITING_APPROVAL",
        scenes: [
          {
            id: "scene_01",
            order: 1,
            duration_sec: 10,
            shots: [
              {
                id: "scene_01_shot_02",
                order: 1,
                duration_sec: 6,
                kind: "b_roll",
                description: "scarf",
                provider_plan: {
                  strategy: "generative",
                  capability: "image_to_video",
                  parameters: { stages: { clip: { done: true } } },
                },
                attempts: [
                  {
                    attempt: 4,
                    provider: "higgsfield",
                    model: "kling3_0",
                    status: "failed",
                    error: "clip: preset",
                  },
                ],
              },
            ],
          },
        ],
      },
      cost: { production_id: "prod_a", currency: "USD", limit: 10, estimated: 1, reserved: 0, actual: 1 },
      artifacts: {},
    } as unknown as ProductionDetail;

    const raw = collectProductionIssues(detail);
    expect(raw.length).toBeGreaterThan(0);
    const open = filterOpenIssues([detail], raw);
    expect(open).toEqual([]);
  });

  it("honors a clear watermark", () => {
    const issues = [
      {
        production_id: "prod_a",
        title: "x",
        state: "FAILED",
        kind: "event" as const,
        when: "2026-10-16T04:00:00Z",
        summary: "old",
      },
      {
        production_id: "prod_a",
        title: "x",
        state: "FAILED",
        kind: "event" as const,
        when: "2026-10-16T05:00:00Z",
        summary: "new",
      },
    ];
    const detail = {
      summary: summary({ id: "prod_a", state: "FAILED", title: "x" }),
      events: [],
      agent_runs: [],
      manifest: { scenes: [] },
      cost: {},
      artifacts: {},
    } as unknown as ProductionDetail;
    const open = filterOpenIssues([detail], issues, { since: "2026-10-16T04:30:00Z" });
    expect(open.map((i) => i.summary)).toEqual(["new"]);
  });

  it("formats an empty open log", () => {
    const log = formatDebugLog({ production_count: 40, inspected: 1, issues: [] });
    expect(log.text).toContain("No open failures");
    expect(log.issue_count).toBe(0);
  });
});
