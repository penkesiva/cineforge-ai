import type { ProductionState } from "@cineforge/schemas";
import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { buildDetail } from "@/test/fixtures";
import { DETAIL_POLL_MS, ProductionDetailContainer } from "./ProductionDetailContainer";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("production detail polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("polls every 2 s while working and stops at the approval gate", async () => {
    const sequence: ProductionState[] = ["RESEARCHING", "SCRIPTING", "AWAITING_APPROVAL"];
    const getProduction = vi
      .spyOn(api, "getProduction")
      .mockImplementation(async () => buildDetail(sequence.shift() ?? "AWAITING_APPROVAL"));

    render(<ProductionDetailContainer id="prod_1" />);
    await flush();
    expect(getProduction).toHaveBeenCalledTimes(1);
    expect(getProduction).toHaveBeenCalledWith("prod_1");
    expect(screen.getAllByTestId("state-badge")[0]).toHaveTextContent("Researching");

    await flush(DETAIL_POLL_MS);
    expect(getProduction).toHaveBeenCalledTimes(2);
    expect(screen.getAllByTestId("state-badge")[0]).toHaveTextContent("Scripting");

    await flush(DETAIL_POLL_MS);
    expect(getProduction).toHaveBeenCalledTimes(3);
    expect(screen.getAllByTestId("state-badge")[0]).toHaveTextContent("Awaiting approval");

    await flush(DETAIL_POLL_MS * 10);
    expect(getProduction).toHaveBeenCalledTimes(3);
  });

  it.each(["DRAFT", "READY", "DELIVERED", "PAUSED_BUDGET", "FAILED"] as const)(
    "does not poll in %s",
    async (state) => {
      const getProduction = vi.spyOn(api, "getProduction").mockResolvedValue(buildDetail(state));
      render(<ProductionDetailContainer id="prod_1" />);
      await flush();
      await flush(DETAIL_POLL_MS * 5);
      expect(getProduction).toHaveBeenCalledTimes(1);
    },
  );

  it("shows a friendly message when the API is unavailable", async () => {
    const { ApiError } = await import("@/lib/api");
    vi.spyOn(api, "getProduction").mockRejectedValue(new ApiError(0, "Network error"));
    render(<ProductionDetailContainer id="prod_1" />);
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("API unavailable");
  });
});

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("only calls back while enabled", async () => {
    const callback = vi.fn();
    const { rerender, unmount } = renderHook(({ enabled }) => usePolling(callback, 1000, enabled), {
      initialProps: { enabled: true },
    });
    await flush(3000);
    expect(callback).toHaveBeenCalledTimes(3);
    rerender({ enabled: false });
    await flush(5000);
    expect(callback).toHaveBeenCalledTimes(3);
    unmount();
  });
});
