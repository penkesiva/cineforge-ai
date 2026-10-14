import type { ClaimReview, FactClaim, ResearchBrief, Script } from "@cineforge/schemas";
import { useId } from "react";
import { formatPct, humanize } from "@/lib/format";
import {
  claimCitations,
  claimsNeedingReview,
  latestClaimReviews,
  type ClaimDecisionValue,
} from "@/lib/review";
import { IconAlert } from "../../icons";
import { Badge, Button, Card, cx, ExternalLink, safeHref } from "../../ui";
import { ClaimStatusBadge } from "./badges";

export interface ClaimsReviewHandlers {
  onDecide?: (claim: FactClaim, decision: ClaimDecisionValue) => void;
  onRewrite?: () => void;
  busyClaimId?: string | null;
  rewriting?: boolean;
}

export interface ClaimsReviewProps extends ClaimsReviewHandlers {
  research: ResearchBrief;
  script?: Script | null;
  reviews?: readonly ClaimReview[];
  /** Decisions are accepted only at the approval gate / budget pause. */
  canReview: boolean;
  /** The API accepts a rewrite only from AWAITING_APPROVAL / NEEDS_REVIEW. */
  canRewrite?: boolean;
}

function Sources({ claim }: { claim: FactClaim }) {
  const sources = claim.sources ?? [];
  if (sources.length === 0) return <p className="mt-1 text-[11px] text-amber-300/80">No sources cited</p>;
  return (
    <details className="group mt-1.5">
      <summary className="cursor-pointer select-none text-[11px] text-zinc-500 hover:text-zinc-300">
        {sources.length} {sources.length === 1 ? "source" : "sources"}
      </summary>
      <ul className="mt-1.5 space-y-2 border-l border-white/10 pl-3">
        {sources.map((source) => {
          const href = safeHref(source.url);
          return (
            <li key={source.url} className="text-xs" data-testid="claim-source">
              {href ? <ExternalLink href={href}>{source.title}</ExternalLink> : <span className="text-zinc-400">{source.title}</span>}
              {source.publisher && <span className="text-zinc-600"> · {source.publisher}</span>}
              {source.excerpt && (
                <blockquote className="mt-1 border-l-2 border-gold-500/30 pl-2 italic text-zinc-400">
                  &ldquo;{source.excerpt}&rdquo;
                </blockquote>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function DecisionBadge({ review }: { review: ClaimReview | undefined }) {
  if (!review) return <span className="text-xs text-zinc-600">Not reviewed</span>;
  return (
    <span className="flex flex-col items-start gap-0.5">
      <Badge tone={review.decision === "approved" ? "success" : "danger"}>
        <span data-testid="claim-decision">{humanize(review.decision)}</span>
      </Badge>
      {review.reviewed_by && <span className="text-[11px] text-zinc-600">by {review.reviewed_by}</span>}
      {review.note && <span className="text-[11px] text-zinc-500">{review.note}</span>}
    </span>
  );
}

export function ClaimsReview({
  research,
  script,
  reviews,
  canReview,
  canRewrite = false,
  onDecide,
  onRewrite,
  busyClaimId = null,
  rewriting = false,
}: ClaimsReviewProps) {
  const uid = useId();
  const latest = latestClaimReviews(reviews);
  const citations = claimCitations(script);
  const pending = claimsNeedingReview(research.claims, latest);
  const rejectedCited = research.claims.filter((c) => latest.get(c.id)?.decision === "rejected" && citations.has(c.id));
  const interactive = canReview && Boolean(onDecide);

  return (
    <Card
      id="claims"
      title="Research claims"
      description={research.summary}
      actions={
        <Badge tone={pending.length ? "warning" : "success"}>
          <span data-testid="claims-needing-review">
            {pending.length === 1 ? "1 claim needs review" : `${pending.length} claims need review`}
          </span>
        </Badge>
      }
    >
      {rejectedCited.length > 0 && (
        <div
          role="alert"
          data-testid="rewrite-warning"
          className="mb-4 flex flex-wrap items-start justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.07] px-4 py-3"
        >
          <p className="flex items-start gap-2 text-sm text-amber-200">
            <IconAlert size={16} className="mt-0.5 shrink-0" />
            <span>
              Approval is blocked until the script is rewritten: it cites{" "}
              {rejectedCited.length === 1 ? "a rejected claim" : `${rejectedCited.length} rejected claims`}.
              {!canRewrite && " A rewrite is possible once the production is back at the approval gate."}
            </span>
          </p>
          {canRewrite && onRewrite && (
            <Button variant="warning" className="px-3 py-1.5 text-xs" onClick={onRewrite} busy={rewriting}>
              Rewrite script
            </Button>
          )}
        </div>
      )}
      {research.claims.length === 0 ? (
        <p className="text-sm text-zinc-500">The research brief has no claims.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <caption className="sr-only">Research claims and review decisions</caption>
            <thead className="text-[11px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th scope="col" className="pb-2 pr-3 font-medium">Claim</th>
                <th scope="col" className="pb-2 pr-3 font-medium">Status</th>
                <th scope="col" className="pb-2 pr-3 text-right font-medium">Confidence</th>
                <th scope="col" className="pb-2 pr-3 font-medium">Script</th>
                <th scope="col" className="pb-2 pr-3 font-medium">Decision</th>
                {interactive && (
                  <th scope="col" className="pb-2 text-right font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {research.claims.map((claim) => {
                const review = latest.get(claim.id);
                const scenes = citations.get(claim.id);
                const textId = `${uid}-${claim.id}`;
                const busy = busyClaimId === claim.id;
                return (
                  <tr
                    key={claim.id}
                    data-testid="claim-row"
                    data-claim={claim.id}
                    className={cx(
                      "border-t border-white/[0.05] align-top",
                      review?.decision === "rejected" && "bg-rose-500/[0.03]",
                    )}
                  >
                    <td className="py-2.5 pr-3">
                      <p id={textId} className="text-zinc-200">
                        {claim.text}
                      </p>
                      <Sources claim={claim} />
                    </td>
                    <td className="py-2.5 pr-3">
                      <ClaimStatusBadge status={claim.status} />
                    </td>
                    <td className="py-2.5 pr-3 text-right tabular-nums text-zinc-300">
                      {formatPct(claim.confidence * 100)}
                    </td>
                    <td className="py-2.5 pr-3 text-xs">
                      {scenes ? (
                        <span className="text-zinc-300" data-testid="claim-cited">
                          Cited in {scenes.map((s) => `S${s}`).join(", ")}
                        </span>
                      ) : (
                        <span className="text-zinc-600">Not cited</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-3">
                      <DecisionBadge review={review} />
                    </td>
                    {interactive && (
                      <td className="py-2.5 text-right">
                        <div className="inline-flex gap-1.5">
                          <Button
                            variant="secondary"
                            className="px-2.5 py-1 text-xs"
                            aria-describedby={textId}
                            aria-pressed={review?.decision === "approved"}
                            disabled={busyClaimId !== null || review?.decision === "approved"}
                            busy={busy}
                            onClick={() => onDecide?.(claim, "approved")}
                          >
                            Approve
                          </Button>
                          <Button
                            variant="ghost"
                            className="px-2.5 py-1 text-xs text-rose-300 hover:text-rose-200"
                            aria-describedby={textId}
                            aria-pressed={review?.decision === "rejected"}
                            disabled={busyClaimId !== null || review?.decision === "rejected"}
                            onClick={() => onDecide?.(claim, "rejected")}
                          >
                            Reject
                          </Button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
