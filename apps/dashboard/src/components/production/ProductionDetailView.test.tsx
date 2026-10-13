import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { buildDetail, productionDetail } from "@/test/fixtures";
import { ProductionDetailView } from "./ProductionDetailView";

const contentUrl = (id: string) => `/api/v1/assets/${id}/content`;

describe("ProductionDetailView", () => {
  it("renders the header with state, theme and simulated badge", () => {
    render(<ProductionDetailView detail={productionDetail} contentUrl={contentUrl} />);
    expect(screen.getByRole("heading", { level: 1, name: "Eiffel Tower, 1889" })).toBeInTheDocument();
    expect(screen.getAllByTestId("state-badge")[0]).toHaveTextContent("Generating");
    expect(screen.getAllByText(/Simulated costs/).length).toBeGreaterThan(0);
    expect(screen.getByText("Time traveler")).toBeInTheDocument();
  });

  it("renders scenes and shots from the manifest", () => {
    render(<ProductionDetailView detail={productionDetail} contentUrl={contentUrl} />);
    const scenes = screen.getAllByTestId("scene");
    expect(scenes).toHaveLength(5);
    expect(screen.getAllByTestId("shot-row")).toHaveLength(10);

    const hook = screen.getByRole("article", { name: "Scene 1: Hook" });
    expect(within(hook).getByText(/Opening hook/)).toBeInTheDocument();
    const shots = within(hook).getAllByTestId("shot-row");
    expect(shots[0]).toHaveTextContent("Wide");
    expect(shots[0]).toHaveTextContent("Ken burns");
    expect(shots[0]).toHaveTextContent("mock-video/mock-video-draft");
    expect(shots[0]).toHaveTextContent("(1 failed)");
    expect(shots[1]).toHaveTextContent("Lip-sync");
    expect(shots[1]).toHaveTextContent("Reconstruction");
    expect(shots[1]).toHaveTextContent("Generative");
  });

  it("renders the agent run timeline and the 10-agent roster", () => {
    render(<ProductionDetailView detail={productionDetail} contentUrl={contentUrl} />);
    const runs = screen.getAllByTestId("agent-run");
    expect(runs).toHaveLength(8);
    expect(runs[0]).toHaveTextContent("A1");
    expect(runs[0]).toHaveTextContent("Master Orchestrator");
    expect(runs[0]).toHaveTextContent("a1_master_orchestrator@1");
    expect(runs[0]).toHaveTextContent("1.5s");
    expect(runs[7]).toHaveTextContent("Visual Production Agent");
    expect(runs[7]).toHaveTextContent("running");

    const roster = screen.getAllByTestId("agent-roster-item");
    expect(roster).toHaveLength(10);
    expect(roster.filter((r) => r.getAttribute("data-ran") === "true")).toHaveLength(8);
    const notRun = roster.filter((r) => r.getAttribute("data-ran") === "false").map((r) => r.textContent);
    expect(notRun.join(" ")).toMatch(/A8.*A9/);
  });

  it("renders the cost panel from CostSummary", () => {
    render(<ProductionDetailView detail={productionDetail} contentUrl={contentUrl} />);
    const costs = screen.getByRole("region", { name: "Costs" });
    const stat = (label: string) => within(costs).getByText(label, { selector: "dt" }).nextElementSibling?.textContent;
    expect(stat("Limit")).toBe("$10.00");
    expect(stat("Estimated")).toBe("$4.20");
    expect(stat("Reserved")).toBe("$0.35");
    expect(stat("Actual")).toBe("$1.8765");
    expect(stat("Remaining")).toBe("$7.7735");
    expect(stat("Retries")).toBe("1");
    expect(within(costs).getByText("Simulated costs")).toBeInTheDocument();
    expect(within(costs).getByRole("table", { name: "By scene" })).toHaveTextContent("Hook");
    expect(within(costs).getByRole("table", { name: "By agent" })).toHaveTextContent("A7 Visual Production Agent");
    expect(within(costs).getByRole("table", { name: "By provider" })).toHaveTextContent("mock-video");
  });

  it("renders artifacts: claims with sources and script lines", () => {
    render(<ProductionDetailView detail={productionDetail} contentUrl={contentUrl} />);
    expect(screen.getAllByTestId("research-claim")).toHaveLength(2);
    const link = screen.getByRole("link", { name: /Eiffel Tower history/ });
    expect(link).toHaveAttribute("href", "https://example.org/eiffel-1889");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("You are standing in Paris, May 1889. Look up.")).toBeInTheDocument();
    expect(screen.getAllByTestId("script-line")).toHaveLength(2);
  });

  it("shows a placeholder until a master render exists, then a video player", () => {
    const { unmount } = render(<ProductionDetailView detail={productionDetail} contentUrl={contentUrl} />);
    expect(screen.queryByTestId("master-video")).not.toBeInTheDocument();
    expect(screen.getByText("No master render yet")).toBeInTheDocument();
    unmount();

    const ready = buildDetail("READY");
    ready.manifest.master_render_asset_id = "ast_master";
    ready.artifacts = {
      ...ready.artifacts,
      master: {
        asset_id: "ast_master",
        uri: "local://x",
        duration_sec: 44.8,
        width: 1080,
        height: 1920,
        fps: 30,
        codec: "h264",
        audio_codec: "aac",
        size_bytes: 3_500_000,
        sha256: "abcdef0123456789abcdef",
      },
      review: { production_id: "p", status: "passed", passed: true, findings: [
        { gate: "master", severity: "minor", message: "Caption slightly late in scene 3", blocking: false },
      ] },
    };
    render(<ProductionDetailView detail={ready} contentUrl={contentUrl} />);
    expect(screen.getByTestId("master-video")).toHaveAttribute("src", "/api/v1/assets/ast_master/content");
    expect(screen.getByText("1080×1920")).toBeInTheDocument();
    expect(screen.getByTestId("review-finding")).toHaveTextContent("Caption slightly late in scene 3");
  });

  it("exposes only the actions allowed in the current state", async () => {
    const onAction = vi.fn();
    const { rerender } = render(
      <ProductionDetailView detail={buildDetail("AWAITING_APPROVAL")} contentUrl={contentUrl} onAction={onAction} />,
    );
    const group = screen.getByRole("group", { name: "Production actions" });
    expect(within(group).queryByRole("button", { name: /Run/ })).not.toBeInTheDocument();
    await userEvent.click(within(group).getByRole("button", { name: /Approve/ }));
    expect(onAction).toHaveBeenCalledWith("approve");

    rerender(<ProductionDetailView detail={buildDetail("DELIVERED")} contentUrl={contentUrl} onAction={onAction} />);
    expect(within(screen.getByRole("group", { name: "Production actions" })).queryAllByRole("button")).toHaveLength(0);
  });
});
