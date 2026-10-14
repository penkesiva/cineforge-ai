import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { HealthIndicator } from "./HealthIndicator";

afterEach(() => {
  vi.restoreAllMocks();
});

const health = { status: "ok" as const, version: "0.1.0", environment: "test", paid_providers_enabled: false };

describe("HealthIndicator", () => {
  it("shows the provider mode reported by /health", async () => {
    vi.spyOn(api, "health").mockResolvedValue({ ...health, provider_mode: "mock" });
    render(<HealthIndicator />);
    expect(await screen.findByTestId("provider-mode")).toHaveTextContent("Mock mode");
    expect(screen.getByRole("status")).toHaveTextContent("API healthy");
  });

  it("labels live mode and hides the label when the API omits it", async () => {
    vi.spyOn(api, "health").mockResolvedValueOnce({ ...health, provider_mode: "live" });
    const { unmount } = render(<HealthIndicator />);
    expect(await screen.findByTestId("provider-mode")).toHaveTextContent("Live providers");
    unmount();

    vi.spyOn(api, "health").mockResolvedValue(health);
    render(<HealthIndicator />);
    await screen.findByText("API healthy");
    expect(screen.queryByTestId("provider-mode")).not.toBeInTheDocument();
  });
});
