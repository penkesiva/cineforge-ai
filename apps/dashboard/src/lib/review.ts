import type {
  AssetCandidate,
  AssetSelection,
  ClaimReview,
  ClaimStatus,
  FactClaim,
  ProductionDetail,
  Script,
} from "@cineforge/schemas";

export type ClaimDecisionValue = ClaimReview["decision"];

/** Unverified and disputed claims need a human decision before approval. */
export const claimNeedsAttention = (status: ClaimStatus): boolean => status === "unverified" || status === "disputed";

/** Latest decision per claim. Later `reviewed_at` wins; without timestamps, later array entries win. */
export function latestClaimReviews(reviews: readonly ClaimReview[] | undefined): Map<string, ClaimReview> {
  const latest = new Map<string, ClaimReview>();
  for (const review of reviews ?? []) {
    const prev = latest.get(review.claim_id);
    const prevAt = prev?.reviewed_at ? Date.parse(prev.reviewed_at) : NaN;
    const at = review.reviewed_at ? Date.parse(review.reviewed_at) : NaN;
    if (!prev || Number.isNaN(prevAt) || Number.isNaN(at) || at >= prevAt) latest.set(review.claim_id, review);
  }
  return latest;
}

/** Open facts that still need a human decision before the script can be confirmed. */
export function openFactCount(
  claims: readonly FactClaim[] | undefined,
  reviews: readonly ClaimReview[] | undefined,
): number {
  const decided = latestClaimReviews(reviews);
  return (claims ?? []).filter((claim) => claimNeedsAttention(claim.status) && !decided.has(claim.id)).length;
}

/** claim id -> scene orders of the script lines citing it. */
export function claimCitations(script: Script | null | undefined): Map<string, number[]> {
  const cited = new Map<string, number[]>();
  for (const line of script?.lines ?? []) {
    for (const claimId of line.claim_ids ?? []) {
      const scenes = cited.get(claimId) ?? [];
      if (!scenes.includes(line.scene_order)) scenes.push(line.scene_order);
      cited.set(claimId, scenes);
    }
  }
  return cited;
}

export function claimsNeedingReview(claims: readonly FactClaim[], reviews: Map<string, ClaimReview>): FactClaim[] {
  return claims.filter((c) => claimNeedsAttention(c.status) && !reviews.has(c.id));
}

/** Rejected claims that a script line still cites; approval returns 409 while any exist. */
export function rejectedCitedClaimIds(detail: ProductionDetail): string[] {
  const reviews = latestClaimReviews(detail.manifest.claim_reviews);
  const cited = claimCitations(detail.artifacts.script);
  return [...cited.keys()].filter((id) => reviews.get(id)?.decision === "rejected");
}

export function candidateIndex(media: AssetSelection | null | undefined): Map<string, AssetCandidate> {
  return new Map((media?.candidates ?? []).map((c) => [c.candidate_id, c]));
}

/** Attribution line for a licensed asset, falling back to license type and author. */
export function attributionText(candidate: AssetCandidate): string {
  const license = candidate.license;
  if (!license) return "License unknown";
  if (license.attribution_text) return license.attribution_text;
  return [license.license_type, license.author ? `by ${license.author}` : null].filter(Boolean).join(" ");
}
