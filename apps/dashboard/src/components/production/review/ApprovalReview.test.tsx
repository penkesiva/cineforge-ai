import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import { buildReviewDetail } from "@/test/fixtures";
import { ProductionDetailContainer } from "../ProductionDetailContainer";
import { ProductionDetailView } from "../ProductionDetailView";
import { ClaimsReview } from "./ClaimsReview";
import { CostPreflight } from "./CostPreflight";
import { MediaCandidatesPanel } from "./MediaCandidatesPanel";
import { StoryboardPanel } from "./StoryboardPanel";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const contentUrl = (id: string) => `/api/v1/assets/${id}/content`;
const claimRow = (id: string) => {
  const row = screen.getAllByTestId("claim-row").find((r) => r.getAttribute("data-claim") === id);
  if (!row) throw new Error(`no claim row ${id}`);
  return row;
};

describe("ClaimsReview", () => {
  it("shows status, confidence, sources, citations and the needs-review count", () => {
    const detail = buildReviewDetail();
    render(
      <ClaimsReview research={detail.artifacts.research!} script={detail.artifacts.script} canReview reviews={[]} onDecide={vi.fn()} />,
    );
    expect(screen.getByTestId("claims-needing-review")).toHaveTextContent("2 claims need review");
    expect(within(claimRow("claim_01")).getByTestId("claim-status")).toHaveTextContent("Verified");
    expect(within(claimRow("claim_02")).getByTestId("claim-status")).toHaveTextContent("Needs review");
    expect(within(claimRow("claim_03")).getByTestId("claim-status")).toHaveTextContent("Dramatized");
    expect(within(claimRow("claim_04")).getByTestId("claim-status")).toHaveTextContent("Needs review");
    expect(claimRow("claim_01")).toHaveTextContent("92%");
    expect(within(claimRow("claim_01")).getByTestId("claim-cited")).toHaveTextContent("Cited in S1");
    expect(claimRow("claim_02")).toHaveTextContent("Not cited");
    expect(claimRow("claim_02")).toHaveTextContent("No sources cited");

    const source = within(claimRow("claim_01")).getByTestId("claim-source");
    expect(within(source).getByRole("link", { name: /Eiffel Tower history/ })).toHaveAttribute(
      "href",
      "https://example.org/eiffel-1889",
    );
    expect(source).toHaveTextContent("some 10,000 gas lamps lit the tower");
    expect(claimRow("claim_01").querySelector("details")).not.toBeNull();
  });

  it("counts only undecided unverified/disputed claims and uses the latest decision", () => {
    const detail = buildReviewDetail();
    render(
      <ClaimsReview
        research={detail.artifacts.research!}
        script={detail.artifacts.script}
        canReview
        reviews={[
          { claim_id: "claim_02", decision: "rejected", reviewed_at: "2026-10-13T12:00:00Z" },
          { claim_id: "claim_02", decision: "approved", reviewed_at: "2026-10-13T12:05:00Z", reviewed_by: "sam" },
        ]}
      />,
    );
    expect(screen.getByTestId("claims-needing-review")).toHaveTextContent("1 claim needs review");
    expect(within(claimRow("claim_02")).getByTestId("claim-decision")).toHaveTextContent("Approved");
    expect(claimRow("claim_02")).toHaveTextContent("by sam");
    expect(screen.queryByTestId("rewrite-warning")).not.toBeInTheDocument();
  });

  it("is read-only outside the approval gate", () => {
    render(<ProductionDetailView detail={buildReviewDetail("GENERATING")} contentUrl={contentUrl} />);
    expect(screen.getAllByTestId("claim-row")).toHaveLength(4);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });
});

describe("claim review actions", () => {
  it("posts an approval for an uncited claim without asking", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "getProduction").mockResolvedValue(buildReviewDetail());
    const review = vi.spyOn(api, "reviewClaims").mockResolvedValue(
      buildReviewDetail("AWAITING_APPROVAL", { claimReviews: [{ claim_id: "claim_02", decision: "approved", reviewed_by: "operator" }] }),
    );
    render(<ProductionDetailContainer id="prod_1" />);
    await screen.findAllByTestId("claim-row");

    await user.click(within(claimRow("claim_02")).getByRole("button", { name: "Approve" }));
    expect(review).toHaveBeenCalledWith("prod_1", {
      reviewed_by: "operator",
      decisions: [{ claim_id: "claim_02", decision: "approved" }],
    });
    await waitFor(() => expect(within(claimRow("claim_02")).getByTestId("claim-decision")).toHaveTextContent("Approved"));
    expect(screen.getByTestId("claims-needing-review")).toHaveTextContent("1 claim needs review");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("warns before rejecting a cited claim, then offers a script rewrite", async () => {
    const user = userEvent.setup();
    const rejected = buildReviewDetail("AWAITING_APPROVAL", {
      claimReviews: [{ claim_id: "claim_04", decision: "rejected", reviewed_by: "operator" }],
    });
    const get = vi.spyOn(api, "getProduction").mockResolvedValueOnce(buildReviewDetail()).mockResolvedValue(rejected);
    const review = vi.spyOn(api, "reviewClaims").mockResolvedValue(rejected);
    const rewrite = vi
      .spyOn(api, "rewriteScript")
      .mockResolvedValue({ production_id: "prod_1", state: "SCRIPTING", message: "Back to scripting." });
    render(<ProductionDetailContainer id="prod_1" />);
    await screen.findAllByTestId("claim-row");

    await user.click(within(claimRow("claim_04")).getByRole("button", { name: "Reject" }));
    const warn = screen.getByRole("alertdialog");
    expect(warn).toHaveAttribute("data-variant", "warning");
    expect(warn).toHaveTextContent("Approval will be blocked until the script is rewritten");
    expect(review).not.toHaveBeenCalled();
    await user.click(within(warn).getByRole("button", { name: "Reject claim" }));
    expect(review).toHaveBeenCalledWith("prod_1", {
      reviewed_by: "operator",
      decisions: [{ claim_id: "claim_04", decision: "rejected" }],
    });

    const banner = await screen.findByTestId("rewrite-warning");
    expect(banner).toHaveTextContent("Approval is blocked until the script is rewritten");
    await user.click(within(banner).getByRole("button", { name: "Rewrite script" }));
    const confirm = screen.getByRole("alertdialog");
    expect(confirm).toHaveTextContent("Rewrite the script?");
    await user.click(within(confirm).getByRole("button", { name: "Rewrite script" }));
    await waitFor(() => expect(rewrite).toHaveBeenCalledWith("prod_1"));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Script rewrite started");
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("shows an approve 409 in a notice and offers the rewrite", async () => {
    const user = userEvent.setup();
    const rejected = buildReviewDetail("AWAITING_APPROVAL", {
      claimReviews: [{ claim_id: "claim_01", decision: "rejected" }],
    });
    vi.spyOn(api, "getProduction").mockResolvedValue(rejected);
    vi.spyOn(api, "approveProduction").mockRejectedValue(
      new ApiError(409, "Script line in scene 1 cites rejected claim claim_01", { error: "rejected_claim_cited" }),
    );
    render(<ProductionDetailContainer id="prod_1" />);
    const group = await screen.findByRole("group", { name: "Production actions" });
    await user.click(within(group).getByRole("button", { name: /Approve/ }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Approve spend" }));

    const notice = await screen.findByRole("alertdialog");
    expect(notice).toHaveTextContent("Script line in scene 1 cites rejected claim claim_01");
    expect(notice).toHaveTextContent("HTTP 409");
    await user.click(within(notice).getByRole("button", { name: "Rewrite script" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Rewrite the script?");
  });
});

describe("StoryboardPanel", () => {
  it("renders scene cards with bound licensed stills, rights badges and attribution", () => {
    const detail = buildReviewDetail();
    render(<StoryboardPanel scenes={detail.manifest.scenes ?? []} media={detail.artifacts.media} />);
    expect(screen.getAllByTestId("storyboard-scene")).toHaveLength(5);
    const hook = screen.getByRole("article", { name: "Storyboard scene 1: Hook" });
    expect(hook).toHaveTextContent("Opening hook");
    expect(within(hook).getAllByText("Reconstruction").length).toBeGreaterThan(0);

    const assets = within(hook).getAllByTestId("storyboard-asset");
    expect(assets.map((a) => a.getAttribute("data-asset"))).toEqual(["cand_eiffel", "cand_nothumb"]);

    const img = within(assets[0]!).getByRole("img", { name: "Eiffel Tower 1889 (wikimedia)" });
    expect(img.tagName).toBe("IMG");
    expect(img).toHaveAttribute("src", "https://commons.example.org/thumb/eiffel.jpg");
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(within(assets[0]!).getByTestId("rights-badge")).toHaveTextContent("Rights approved");
    expect(within(assets[0]!).getByTestId("asset-attribution")).toHaveTextContent("Public domain, via Wikimedia Commons");

    expect(within(assets[1]!).getByTestId("asset-placeholder")).toHaveAccessibleName("No thumbnail: Exposition crowd (openverse)");
    expect(within(assets[1]!).getByTestId("rights-badge")).toHaveTextContent("Rights pending");
    expect(within(assets[1]!).getByTestId("asset-attribution")).toHaveTextContent("CC-BY-4.0 by Jane Doe");

    const arrival = screen.getByRole("article", { name: "Storyboard scene 2: Arrival" });
    const blocked = within(arrival).getByTestId("storyboard-asset");
    expect(within(blocked).getByTestId("rights-badge")).toHaveTextContent("Rights blocked");
    expect(within(blocked).getByTestId("asset-placeholder")).toBeInTheDocument();
    expect(blocked).toHaveTextContent("License unknown: rights fail closed");
  });
});

describe("MediaCandidatesPanel", () => {
  it("lists every candidate with rights, selection and blocked reason", () => {
    render(<MediaCandidatesPanel media={buildReviewDetail().artifacts.media!} />);
    const items = screen.getAllByTestId("media-candidate");
    expect(items).toHaveLength(3);
    expect(screen.getByText("3 found · 2 selected · 1 blocked by the rights gate")).toBeInTheDocument();
    expect(within(items[0]!).getByText("Selected")).toBeInTheDocument();
    expect(within(items[2]!).getByTestId("rights-badge")).toHaveTextContent("Rights blocked");
    expect(within(items[2]!).getByTestId("blocked-reason")).toHaveTextContent("Blocked: License unknown: rights fail closed");
    expect(within(items[2]!).queryByText("Selected")).not.toBeInTheDocument();
  });
});

describe("CostPreflight", () => {
  it("flags an estimate over the budget limit", () => {
    const detail = buildReviewDetail("PAUSED_BUDGET", { estimateTotal: 12.5 });
    render(
      <CostPreflight
        estimate={detail.artifacts.cost_plan!.estimate}
        limit={detail.manifest.budget.limit}
        scenes={detail.manifest.scenes}
        cost={detail.cost}
      />,
    );
    expect(screen.getByTestId("over-budget")).toHaveTextContent("Estimate $12.50 exceeds the $10.00 budget by $2.50");
    expect(screen.getByText("Over budget")).toBeInTheDocument();
    const bars = screen.getAllByTestId("preflight-bar");
    expect(bars.map((b) => b.textContent)).toEqual([
      "S1 Hook$7.50",
      "S2 Arrival$5.00",
      "A7 Visual Production Agent$8.75",
      "A8 Audio & Performance Agent$3.75",
    ]);
    const stat = (label: string) => screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent;
    expect(stat("Simulated costs")).toBe("$1.8765");
    expect(stat("Real spend so far")).toBe("$0.00");
  });

  it("shows within budget and real spend when costs are not simulated", () => {
    const detail = buildReviewDetail("AWAITING_APPROVAL", { estimateTotal: 4.2 });
    render(
      <CostPreflight
        estimate={detail.artifacts.cost_plan!.estimate}
        limit={10}
        cost={{ ...detail.cost, simulated: false, actual: 0.5 }}
      />,
    );
    expect(screen.queryByTestId("over-budget")).not.toBeInTheDocument();
    expect(screen.getByText("Within budget")).toBeInTheDocument();
    const stat = (label: string) => screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent;
    expect(stat("Real spend so far")).toBe("$0.50");
    expect(stat("Simulated costs")).toBe("$0.00");
  });

  it("appears on the production page when a cost plan exists", () => {
    render(<ProductionDetailView detail={buildReviewDetail("PAUSED_BUDGET", { estimateTotal: 12 })} contentUrl={contentUrl} />);
    expect(screen.getByRole("region", { name: "Cost preflight" })).toBeInTheDocument();
    expect(screen.getByTestId("over-budget")).toBeInTheDocument();
  });
});
