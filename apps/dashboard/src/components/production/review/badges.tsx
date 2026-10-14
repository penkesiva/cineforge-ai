import type { ClaimStatus, RightsStatus } from "@cineforge/schemas";
import { humanize } from "@/lib/format";
import { claimNeedsAttention } from "@/lib/review";
import { Badge, type Tone } from "../../ui";

const CLAIM_TONES: Record<ClaimStatus, Tone> = {
  verified: "success",
  dramatized: "info",
  unverified: "warning",
  disputed: "warning",
};

export function ClaimStatusBadge({ status }: { status: ClaimStatus }) {
  const label = claimNeedsAttention(status) ? "Needs review" : humanize(status);
  return (
    <Badge tone={CLAIM_TONES[status]} title={humanize(status)}>
      <span data-testid="claim-status">{label}</span>
      {claimNeedsAttention(status) && <span className="text-amber-200/70">· {status}</span>}
    </Badge>
  );
}

const RIGHTS_TONES: Record<RightsStatus, Tone> = {
  approved: "success",
  pending: "warning",
  unknown: "warning",
  blocked: "danger",
};

export function RightsBadge({ status }: { status: RightsStatus | undefined }) {
  const value = status ?? "unknown";
  return (
    <Badge tone={RIGHTS_TONES[value]} title={`Rights status: ${value}`}>
      <span data-testid="rights-badge">Rights {value}</span>
    </Badge>
  );
}
