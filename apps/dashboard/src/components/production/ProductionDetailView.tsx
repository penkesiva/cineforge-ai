import type { ProductionDetail } from "@cineforge/schemas";
import { WorkflowStepper } from "../WorkflowStepper";
import { Card } from "../ui";
import { AgentsPanel } from "./AgentsPanel";
import { ArtifactsPanel } from "./ArtifactsPanel";
import { CostPanel } from "./CostPanel";
import { EventsLog } from "./EventsLog";
import { MasterRenderPanel } from "./MasterRenderPanel";
import { ProductionHeader, type ProductionActionHandlers } from "./ProductionHeader";
import { ScenesPanel } from "./ScenesPanel";

export interface ProductionDetailViewProps extends ProductionActionHandlers {
  detail: ProductionDetail;
  contentUrl: (assetId: string) => string;
  polling?: boolean;
}

export function ProductionDetailView({ detail, contentUrl, polling, onAction, busyAction }: ProductionDetailViewProps) {
  const { summary, manifest } = detail;
  return (
    <div className="animate-fade-up">
      <ProductionHeader detail={detail} onAction={onAction} busyAction={busyAction} polling={polling} />
      <Card title="Workflow" className="mb-6">
        <WorkflowStepper state={summary.state} events={detail.events} />
      </Card>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-6">
          <MasterRenderPanel
            assetId={manifest.master_render_asset_id}
            master={detail.artifacts.master}
            contentUrl={contentUrl}
          />
          <ScenesPanel scenes={manifest.scenes ?? []} />
          <AgentsPanel runs={detail.agent_runs} />
          <ArtifactsPanel artifacts={detail.artifacts} manifestFindings={manifest.review_findings} />
        </div>
        <div className="space-y-6">
          <CostPanel cost={detail.cost} />
          <EventsLog events={detail.events} />
        </div>
      </div>
    </div>
  );
}
