import type { ProductionDetail } from "@cineforge/schemas";
import { canRewriteScript, isReviewState } from "@/lib/workflow";
import { WorkflowStepper } from "../WorkflowStepper";
import { Card } from "../ui";
import { AgentsPanel } from "./AgentsPanel";
import { ArtifactsPanel } from "./ArtifactsPanel";
import { CostPanel } from "./CostPanel";
import { EventsLog } from "./EventsLog";
import { MasterRenderPanel } from "./MasterRenderPanel";
import { ProductionHeader, type ProductionActionHandlers } from "./ProductionHeader";
import { ClaimsReview, type ClaimsReviewHandlers } from "./review/ClaimsReview";
import { CostPreflight } from "./review/CostPreflight";
import { MediaCandidatesPanel } from "./review/MediaCandidatesPanel";
import { StoryboardPanel } from "./review/StoryboardPanel";
import { ScenesPanel } from "./ScenesPanel";

export interface ProductionDetailViewProps extends ProductionActionHandlers {
  detail: ProductionDetail;
  contentUrl: (assetId: string) => string;
  polling?: boolean;
  review?: ClaimsReviewHandlers;
}

export function ProductionDetailView({ detail, contentUrl, polling, onAction, busyAction, review }: ProductionDetailViewProps) {
  const { summary, manifest, artifacts } = detail;
  const inReview = isReviewState(summary.state);
  const scenes = manifest.scenes ?? [];

  const preproduction = (
    <>
      {artifacts.research && (
        <ClaimsReview
          research={artifacts.research}
          script={artifacts.script}
          reviews={manifest.claim_reviews}
          canReview={inReview}
          canRewrite={canRewriteScript(summary.state)}
          {...review}
        />
      )}
      {scenes.length > 0 && <StoryboardPanel scenes={scenes} media={artifacts.media} assets={detail.assets} />}
      {artifacts.media && <MediaCandidatesPanel media={artifacts.media} />}
    </>
  );
  const master = (
    <MasterRenderPanel assetId={manifest.master_render_asset_id} master={artifacts.master} contentUrl={contentUrl} />
  );

  return (
    <div className="animate-fade-up">
      <ProductionHeader detail={detail} onAction={onAction} busyAction={busyAction} polling={polling} />
      <Card title="Workflow" className="mb-6">
        <WorkflowStepper state={summary.state} events={detail.events} />
      </Card>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-6">
          {inReview ? preproduction : master}
          <ScenesPanel scenes={scenes} assets={detail.assets} />
          {inReview ? master : preproduction}
          <AgentsPanel runs={detail.agent_runs} />
          <ArtifactsPanel artifacts={artifacts} manifestFindings={manifest.review_findings} />
        </div>
        <div className="space-y-6">
          {artifacts.cost_plan && (
            <CostPreflight estimate={artifacts.cost_plan.estimate} limit={manifest.budget.limit} scenes={scenes} cost={detail.cost} />
          )}
          <CostPanel cost={detail.cost} />
          <EventsLog events={detail.events} />
        </div>
      </div>
    </div>
  );
}
