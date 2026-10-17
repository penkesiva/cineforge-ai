import type { ProductionState } from "@cineforge/schemas";
import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { buildDetail, ledgerEvents } from "@/test/fixtures";
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
    vi.spyOn(api, "getProductionLedger").mockResolvedValue([]);
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
    expect(api.getProductionLedger).toHaveBeenCalledTimes(3);
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

describe("re-render", () => {
  beforeEach(() => {
    vi.spyOn(api, "getProductionLedger").mockResolvedValue(ledgerEvents);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("is offered only in READY", async () => {
    vi.spyOn(api, "getProduction").mockResolvedValue(buildDetail("GENERATING"));
    const { unmount } = render(<ProductionDetailContainer id="prod_1" />);
    const group = await screen.findByRole("group", { name: "Production actions" });
    expect(within(group).queryByRole("button", { name: /Re-render/ })).not.toBeInTheDocument();
    unmount();

    vi.spyOn(api, "getProduction").mockResolvedValue(buildDetail("READY"));
    render(<ProductionDetailContainer id="prod_1" />);
    const ready = await screen.findByRole("group", { name: "Production actions" });
    expect(within(ready).getByRole("button", { name: /Re-render/ })).toBeEnabled();
  });

  it("confirms, posts the render request, refreshes and shows the job id", async () => {
    const user = userEvent.setup();
    const get = vi
      .spyOn(api, "getProduction")
      .mockResolvedValueOnce(buildDetail("READY"))
      .mockResolvedValue(buildDetail("ASSEMBLING"));
    const renderProduction = vi.spyOn(api, "renderProduction").mockResolvedValue({
      production_id: "prod_1",
      state: "ASSEMBLING",
      message: "Re-render queued.",
      job_id: "job_render_1",
    });
    render(<ProductionDetailContainer id="prod_1" />);
    const group = await screen.findByRole("group", { name: "Production actions" });
    await user.click(within(group).getByRole("button", { name: /Re-render/ }));

    const confirm = screen.getByRole("alertdialog", { name: "Render a new master version?" });
    expect(confirm).toHaveTextContent("current clips, stills and narration");
    expect(confirm).toHaveTextContent("no paid provider calls");
    expect(renderProduction).not.toHaveBeenCalled();
    await user.click(within(confirm).getByRole("button", { name: "Re-render" }));

    expect(renderProduction).toHaveBeenCalledWith("prod_1", { requested_by: "operator" });
    const notice = await screen.findByRole("dialog", { name: "Re-render started" });
    expect(notice).toHaveTextContent("Re-render queued.");
    expect(notice).toHaveTextContent("Job job_render_1");
    expect(get).toHaveBeenCalledTimes(2);
    expect(api.getProductionLedger).toHaveBeenCalledTimes(2);
    expect(screen.getAllByTestId("ledger-credits")[0]).toHaveTextContent("15");
    await waitFor(() => expect(screen.getAllByTestId("state-badge")[0]).toHaveTextContent("Assembling"));
  });

  it("shows the API error when the production is no longer READY", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "getProduction").mockResolvedValue(buildDetail("READY"));
    vi.spyOn(api, "renderProduction").mockRejectedValue(
      new ApiError(409, "Cannot re-render from DELIVERED", { error: "invalid_transition" }),
    );
    render(<ProductionDetailContainer id="prod_1" />);
    const group = await screen.findByRole("group", { name: "Production actions" });
    await user.click(within(group).getByRole("button", { name: /Re-render/ }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Re-render" }));

    const notice = await screen.findByRole("alertdialog", { name: "Could not re-render production" });
    expect(notice).toHaveTextContent("Cannot re-render from DELIVERED");
    expect(notice).toHaveTextContent("HTTP 409 · invalid_transition");
  });
});

describe("script confirmation", () => {
  beforeEach(() => {
    vi.spyOn(api, "getProductionLedger").mockResolvedValue([]);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function scriptGate() {
    const detail = buildDetail("AWAITING_APPROVAL");
    detail.manifest.approval_stage = "script";
    return detail;
  }

  it("shows the script and waits until open facts are decided", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "getProduction").mockResolvedValue(scriptGate());
    render(<ProductionDetailContainer id="prod_1" />);
    const group = await screen.findByRole("group", { name: "Production actions" });
    await user.click(within(group).getByRole("button", { name: /^Approve/ }));
    const dialog = await screen.findByRole("alertdialog", { name: "Confirm the script" });
    expect(dialog).toHaveTextContent("You are standing in Paris, May 1889.");
    expect(dialog).toHaveTextContent("still need a decision");
    expect(within(dialog).getByRole("button", { name: "Script looks right" })).toBeDisabled();
  });

  it("opens spend approval after the script is confirmed", async () => {
    const user = userEvent.setup();
    const detail = scriptGate();
    detail.manifest.claim_reviews = [
      {
        claim_id: "claim_02",
        decision: "approved",
        reviewed_by: "operator",
        reviewed_at: "2026-10-15T00:00:00Z",
      },
    ];
    vi.spyOn(api, "getProduction").mockResolvedValue(detail);
    render(<ProductionDetailContainer id="prod_1" />);
    const group = await screen.findByRole("group", { name: "Production actions" });
    await user.click(within(group).getByRole("button", { name: /^Approve/ }));
    const dialog = await screen.findByRole("alertdialog", { name: "Confirm the script" });
    expect(within(dialog).getByRole("button", { name: "Script looks right" })).toBeEnabled();
    await user.click(within(dialog).getByRole("button", { name: "Script looks right" }));
    expect(screen.getByRole("alertdialog", { name: "Approve generation spend?" })).toBeInTheDocument();
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
