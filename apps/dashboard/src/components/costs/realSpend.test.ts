import { describe, expect, it } from "vitest";
import { isMockProvider, realSpendOverview } from "./realSpend";
import type { CostOverview } from "@cineforge/schemas";

const base: CostOverview = {
  tenant_id: "tenant_demo",
  production_count: 40,
  total_limit: 401.9,
  total_estimated: 255,
  total_reserved: 0,
  total_actual: 204.7,
  retry_count: 21,
  simulated: false,
  by_provider: [
    { key: "higgsfield", label: "higgsfield", estimated: 3.9, reserved: 0, actual: 3.97, event_count: 38 },
    { key: "anthropic", label: "anthropic", estimated: 1.3, reserved: 0, actual: 0.63, event_count: 41 },
    { key: "mock-video", label: "mock-video", estimated: 198, reserved: 0, actual: 185.85, event_count: 407 },
  ],
  by_production: [{ key: "prod_x", label: "prod_x", actual: 5 }],
  credit_balances: [
    { tenant_id: "tenant_demo", provider: "higgsfield", balance: "2255", unit: "credit" },
    { tenant_id: "tenant_demo", provider: "mock-llm", balance: "99999", unit: "credit" },
  ],
};

describe("realSpendOverview", () => {
  it("keeps mock spend when the tenant is still fully simulated", () => {
    const view = realSpendOverview({ ...base, simulated: true });
    expect(view.total_actual).toBe(204.7);
    expect(view.by_provider).toHaveLength(3);
    expect(view.excluded_mock_actual).toBe(0);
  });

  it("drops mock providers once any real spend exists", () => {
    const view = realSpendOverview(base);
    expect(view.total_actual).toBeCloseTo(4.6, 5);
    expect(view.total_estimated).toBeCloseTo(5.2, 5);
    expect(view.by_provider.map((r) => r.key)).toEqual(["higgsfield", "anthropic"]);
    expect(view.by_production).toEqual([]);
    expect(view.by_agent).toEqual([]);
    expect(view.credit_balances?.map((b) => b.provider)).toEqual(["higgsfield"]);
    expect(view.excluded_mock_actual).toBeCloseTo(185.85, 5);
  });

  it("detects mock provider names", () => {
    expect(isMockProvider("mock-video")).toBe(true);
    expect(isMockProvider("higgsfield")).toBe(false);
  });
});
