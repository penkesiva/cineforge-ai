import type { AssetSelection } from "@cineforge/schemas";
import { humanize } from "@/lib/format";
import { attributionText } from "@/lib/review";
import { Badge, Card, EmptyState, ExternalLink, safeHref } from "../../ui";
import { AssetThumb } from "./AssetThumb";
import { RightsBadge } from "./badges";

export function MediaCandidatesPanel({ media }: { media: AssetSelection }) {
  const selected = new Set(media.selected_ids ?? []);
  const blocked = media.blocked ?? {};
  const blockedCount = media.candidates.filter((c) => blocked[c.candidate_id]).length;
  return (
    <Card
      id="media-candidates"
      title="Media candidates"
      description={`${media.candidates.length} found · ${selected.size} selected · ${blockedCount} blocked by the rights gate`}
    >
      {media.candidates.length === 0 ? (
        <EmptyState title="No media candidates" />
      ) : (
        <ul className="divide-y divide-white/[0.05]">
          {media.candidates.map((c) => {
            const href = safeHref(c.source_url);
            const reason = blocked[c.candidate_id];
            return (
              <li key={c.candidate_id} data-testid="media-candidate" data-candidate={c.candidate_id} className="flex gap-3 py-2.5">
                <AssetThumb candidate={c} className="h-12 w-12" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {href ? (
                      <ExternalLink href={href} className="text-sm">
                        {c.title}
                      </ExternalLink>
                    ) : (
                      <span className="text-sm text-zinc-200">{c.title}</span>
                    )}
                    <RightsBadge status={c.rights_status} />
                    {selected.has(c.candidate_id) && <Badge tone="gold">Selected</Badge>}
                  </div>
                  <p className="mt-0.5 text-[11px] text-zinc-500">
                    {c.provider} · {humanize(c.media_type)} · {attributionText(c)}
                  </p>
                  {reason && (
                    <p className="mt-0.5 text-[11px] text-rose-300" data-testid="blocked-reason">
                      Blocked: {reason}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
