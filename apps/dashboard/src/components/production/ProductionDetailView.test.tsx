import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { buildDetail, buildGeneratedDetail, productionDetail } from "@/test/fixtures";
import { ProductionDetailView } from "./ProductionDetailView";
import { StoryboardPanel } from "./review/StoryboardPanel";

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

  it("badges AI-generated shots and names real generation providers", () => {
    const detail = buildGeneratedDetail();
    const synthetic = (detail.manifest.scenes ?? []).flatMap((s) => s.shots).filter((s) => s.disclosure?.synthetic_media);
    render(<ProductionDetailView detail={detail} contentUrl={contentUrl} />);
    const shots = within(screen.getByRole("article", { name: "Scene 1: Hook" })).getAllByTestId("shot-row");

    const badge = within(shots[0]!).getByTestId("ai-generated-badge");
    expect(badge).toHaveTextContent("AI-generated");
    expect(badge.parentElement).toHaveAttribute("title", "AI-generated (synthetic media)");
    expect(within(shots[0]!).getByTestId("shot-generated-by")).toHaveTextContent("higgsfield / kling2_6");

    expect(within(shots[1]!).getByTestId("ai-generated-badge")).toHaveTextContent("Reconstruction");
    expect(within(shots[1]!).queryByTestId("shot-generated-by")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("ai-generated-badge")).toHaveLength(synthetic.length);
    const scenesCard = screen.getByRole("region", { name: "Scenes & shots" });
    expect(within(scenesCard).getAllByTestId("shot-generated-by")).toHaveLength(1);
  });

  it("shows the same disclosure and provider on storyboard shots", () => {
    const detail = buildGeneratedDetail("AWAITING_APPROVAL");
    render(<StoryboardPanel scenes={detail.manifest.scenes ?? []} assets={detail.assets} />);
    const shots = screen.getAllByTestId("storyboard-shot");
    expect(shots[0]).toHaveTextContent("AI-generated");
    expect(within(shots[0]!).getByTestId("shot-generated-by")).toHaveTextContent("higgsfield / kling2_6");
    expect(shots[1]).toHaveTextContent("Reconstruction");
    expect(within(shots[1]!).queryByTestId("shot-generated-by")).not.toBeInTheDocument();
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
    expect(screen.getAllByTestId("claim-row")).toHaveLength(2);
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
