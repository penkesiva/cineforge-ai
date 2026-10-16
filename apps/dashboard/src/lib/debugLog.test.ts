import { describe, expect, it } from "vitest";
import {
  collectProductionIssues,
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
      summary({ id: "prod_old", state: "DELIVERED", updated_at: "2026-10-14T00:00:00Z", title: "E2E" }),
      summary({ id: "prod_fail", state: "FAILED", updated_at: "2026-10-15T10:00:00Z", title: "Lepakshi" }),
      summary({
        id: "prod_wait",
        state: "AWAITING_APPROVAL",
        updated_at: "2026-10-15T11:00:00Z",
        approval_stage: "preview",
      }),
    ];
    expect(selectProductionsToInspect(rows, 2).map((r) => r.id)).toEqual(["prod_wait", "prod_fail"]);
  });

  it("collects stage_failed events, failed agent runs and shot attempts", () => {
    const detail = {
      summary: summary({
        id: "prod_a",
        state: "AWAITING_APPROVAL",
        title: "Lena at Lepakshi",
        approval_stage: "preview",
      }),
      events: [
        {
          production_id: "prod_a",
          tenant_id: "tenant_demo",
          event_type: "stage_failed",
          message: "scene_01_shot_02 clip failed: quote returned no credit amount. Approve again to retry.",
          created_at: "2026-10-15T16:37:36Z",
        },
        {
          production_id: "prod_a",
          tenant_id: "tenant_demo",
          event_type: "state_changed",
          to_state: "AWAITING_APPROVAL",
          message: "ok",
          created_at: "2026-10-15T16:30:00Z",
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
          attempt: 1,
          idempotency_key: "k",
          error: "higgsfield: quote returned no credit amount",
          finished_at: "2026-10-15T16:37:36Z",
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
                attempts: [
                  {
                    attempt: 1,
                    provider: "higgsfield",
                    model: "kling3_0",
                    status: "failed",
                    error: "clip: quote returned no credit amount",
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

    const issues = collectProductionIssues(detail);
    expect(issues.map((i) => i.kind).sort()).toEqual(["agent_run", "event", "shot_attempt"]);
    const log = formatDebugLog({ production_count: 3, inspected: 1, issues });
    expect(log.text).toContain("prod_a");
    expect(log.text).toContain("quote returned no credit amount");
    expect(log.text).toContain("stage preview");
    expect(log.issue_count).toBe(3);
  });
});
