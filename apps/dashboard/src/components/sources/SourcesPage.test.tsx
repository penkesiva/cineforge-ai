import type { ProvidersOverview } from "@cineforge/schemas";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import { plannedLabel } from "@/lib/providers";
import { anthropic, buildOverview } from "@/test/providerFixtures";
import { MOCK_MODE_MESSAGE, PAID_OFF_MESSAGE, SourcesPage } from "./SourcesPage";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockOverview(...overviews: ProvidersOverview[]) {
  const queue = [...overviews];
  return vi.spyOn(api, "getProviders").mockImplementation(async () => (queue.length > 1 ? queue.shift()! : queue[0]!));
}

const row = (name: string) => {
  const el = screen.getAllByTestId("provider-row").find((r) => r.getAttribute("data-provider") === name);
  if (!el) throw new Error(`no row for ${name}`);
  return el;
};

describe("SourcesPage", () => {
  it("renders the mode banner and one card per capability group in API order", async () => {
    mockOverview(buildOverview());
    render(<SourcesPage />);
    expect(await screen.findByText(MOCK_MODE_MESSAGE)).toBeInTheDocument();
    expect(screen.getByText(PAID_OFF_MESSAGE)).toBeInTheDocument();
    expect(screen.getByText("Secrets: memory")).toBeInTheDocument();

    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Research", "LLM", "Video"]);

    const llm = screen.getByRole("region", { name: "LLM" });
    expect(within(llm).getByText("Mock LLM", { selector: "span" })).toBeInTheDocument();
    expect(within(row("mock-llm")).getByText("Active")).toBeInTheDocument();
    expect(within(row("mock-llm")).getByText("Mock")).toBeInTheDocument();
    expect(within(row("mock-llm")).getByText("Free")).toBeInTheDocument();
    expect(within(row("anthropic")).getByText("Paid")).toBeInTheDocument();
    expect(within(row("anthropic")).getByTestId("provider-status")).toHaveTextContent("Missing key");
    expect(within(row("anthropic")).getByText("Set ANTHROPIC_API_KEY or store a key")).toBeInTheDocument();
    expect(within(row("wikipedia")).getByTestId("provider-status")).toHaveTextContent("Blocked: mock mode");
    expect(within(screen.getByRole("region", { name: "Research" })).getByText("No active provider")).toBeInTheDocument();
  });

  it("greys out planned providers and disables their controls", async () => {
    mockOverview(buildOverview());
    render(<SourcesPage />);
    await screen.findByText(MOCK_MODE_MESSAGE);
    const planned = row("runway");
    expect(within(planned).getByTestId("provider-status")).toHaveTextContent("Planned (Phase 2)");
    expect(within(planned).getByRole("switch", { name: "Enable Runway" })).toBeDisabled();
    expect(within(planned).getByRole("button", { name: "Test Runway" })).toBeDisabled();
    expect(within(planned).queryByLabelText("API key for Runway")).not.toBeInTheDocument();
    expect(plannedLabel("Phase 3")).toBe("Planned (Phase 3)");
  });

  it("shows the live banner and paid-on warning", async () => {
    mockOverview(buildOverview({ provider_mode: "live", paid_providers_allowed: true }));
    render(<SourcesPage />);
    expect(await screen.findByText(/Live mode/)).toBeInTheDocument();
    expect(screen.getByText(/Paid calls are on/)).toBeInTheDocument();
    expect(screen.queryByText(MOCK_MODE_MESSAGE)).not.toBeInTheDocument();
  });

  it("asks before enabling a paid provider and only then PATCHes", async () => {
    const user = userEvent.setup();
    const getProviders = mockOverview(buildOverview());
    const update = vi.spyOn(api, "updateProvider").mockResolvedValue({ ...anthropic, enabled: true });
    render(<SourcesPage />);
    await screen.findByText(MOCK_MODE_MESSAGE);

    await user.click(within(row("anthropic")).getByRole("switch", { name: "Enable Anthropic Claude" }));
    let dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAttribute("data-variant", "warning");
    expect(dialog).toHaveTextContent("Enable Anthropic Claude?");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(update).not.toHaveBeenCalled();

    await user.click(within(row("anthropic")).getByRole("switch", { name: "Enable Anthropic Claude" }));
    dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Enable paid provider" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("anthropic", { enabled: true }));
    await waitFor(() => expect(getProviders).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("toggles free providers and changes priority without confirmation", async () => {
    const user = userEvent.setup();
    mockOverview(buildOverview());
    const update = vi.spyOn(api, "updateProvider").mockResolvedValue(anthropic);
    render(<SourcesPage />);
    await screen.findByText(MOCK_MODE_MESSAGE);

    await user.click(within(row("mock-llm")).getByRole("switch", { name: "Enable Mock LLM" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("mock-llm", { enabled: false }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    const priority = within(row("anthropic")).getByRole("spinbutton", { name: "Priority for Anthropic Claude" });
    await user.clear(priority);
    await user.type(priority, "5{Enter}");
    await waitFor(() => expect(update).toHaveBeenCalledWith("anthropic", { priority: 5 }));
  });

  it("saves a key, clears the input and never renders the key", async () => {
    const user = userEvent.setup();
    const stored = { ...anthropic, key_source: "stored" as const, key_hint: "...a1b2", status: "disabled" as const };
    const getProviders = mockOverview(
      buildOverview(),
      buildOverview({
        groups: [{ capability: "llm_text", label: "LLM", providers: [stored], active_provider: null }],
      }),
    );
    const setKey = vi.spyOn(api, "setProviderKey").mockResolvedValue(stored);
    const secret = "fake-ant-super-secret-a1b2";
    render(<SourcesPage />);
    await screen.findByText(MOCK_MODE_MESSAGE);

    const input = within(row("anthropic")).getByLabelText("API key for Anthropic Claude", { selector: "input" });
    expect(input).toHaveAttribute("type", "password");
    expect(within(row("anthropic")).getByTestId("key-status")).toHaveTextContent("No key set");
    await user.type(input, secret);
    await user.click(within(row("anthropic")).getByRole("button", { name: "Save key" }));

    expect(setKey).toHaveBeenCalledWith("anthropic", secret);
    await waitFor(() => expect(getProviders).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Key saved");
    const after = within(row("anthropic")).getByLabelText("API key for Anthropic Claude", { selector: "input" });
    expect(after).toHaveValue("");
    expect(within(row("anthropic")).getByTestId("key-status")).toHaveTextContent("Stored key ...a1b2");
    expect(document.body.innerHTML).not.toContain(secret);
  });

  it("asks before removing a stored key", async () => {
    const user = userEvent.setup();
    const stored = { ...anthropic, key_source: "stored" as const, key_hint: "...a1b2" };
    mockOverview(buildOverview({ groups: [{ capability: "llm_text", label: "LLM", providers: [stored] }] }));
    const remove = vi.spyOn(api, "deleteProviderKey").mockResolvedValue(anthropic);
    render(<SourcesPage />);
    await user.click(await screen.findByRole("button", { name: "Remove key" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAttribute("data-variant", "danger");
    expect(remove).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Remove key" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("anthropic"));
  });

  it("shows environment keys as read-only", async () => {
    const env = { ...anthropic, key_source: "environment" as const, key_hint: "...zz99", status: "ready" as const };
    mockOverview(buildOverview({ groups: [{ capability: "llm_text", label: "LLM", providers: [env] }] }));
    render(<SourcesPage />);
    expect(await screen.findByText("Set via environment (ANTHROPIC_API_KEY)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove key" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("API key for Anthropic Claude", { selector: "input" })).not.toBeInTheDocument();
  });

  it("shows the provider test result in a notice", async () => {
    const user = userEvent.setup();
    mockOverview(buildOverview());
    vi.spyOn(api, "testProvider").mockResolvedValue({
      provider: "mock-llm",
      ok: true,
      detail: "Mock LLM answered",
      latency_ms: 12.4,
      paid_call: false,
    });
    render(<SourcesPage />);
    await user.click(await screen.findByRole("button", { name: "Test Mock LLM" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Mock LLM: test passed");
    expect(dialog).toHaveTextContent("Mock LLM answered");
    expect(dialog).toHaveTextContent("12 ms · Free check, no spend.");
  });

  it("surfaces mutation errors in an error notice", async () => {
    const user = userEvent.setup();
    mockOverview(buildOverview());
    vi.spyOn(api, "updateProvider").mockRejectedValue(
      new ApiError(422, "priority must be >= 0", { error: "validation_error" }),
    );
    render(<SourcesPage />);
    await user.click(await screen.findByRole("switch", { name: "Enable Mock LLM" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Could not update Mock LLM");
    expect(dialog).toHaveTextContent("priority must be >= 0");
  });
});
