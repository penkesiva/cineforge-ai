import type { AssetCandidate, AssetSelection, Scene, Shot } from "@cineforge/schemas";
import { formatDuration, humanize } from "@/lib/format";
import { attributionText, candidateIndex } from "@/lib/review";
import { Badge, Card, EmptyState } from "../../ui";
import { AssetThumb } from "./AssetThumb";
import { RightsBadge } from "./badges";

function disclosureLabel(shot: Shot): string | null {
  const d = shot.disclosure;
  if (!d) return null;
  if (d.label_text) return d.label_text;
  if (d.reconstruction) return "Reconstruction";
  if (d.synthetic_media) return "AI-generated";
  return null;
}

function BoundAsset({ candidate, blockedReason }: { candidate: AssetCandidate; blockedReason?: string }) {
  return (
    <figure data-testid="storyboard-asset" data-asset={candidate.candidate_id} className="w-36">
      <AssetThumb candidate={candidate} className="aspect-[9/16] w-36" />
      <figcaption className="mt-1.5 space-y-1">
        <RightsBadge status={candidate.rights_status} />
        <p className="text-[11px] leading-snug text-zinc-500" data-testid="asset-attribution">
          {attributionText(candidate)}
        </p>
        {blockedReason && <p className="text-[11px] text-rose-300">{blockedReason}</p>}
      </figcaption>
    </figure>
  );
}

function ShotCard({ shot, candidates, blocked }: { shot: Shot; candidates: Map<string, AssetCandidate>; blocked: Record<string, string> }) {
  const bound = (shot.assets ?? [])
    .map((ref) => candidates.get(ref.asset_id))
    .filter((c): c is AssetCandidate => c !== undefined);
  const disclosure = disclosureLabel(shot);
  return (
    <li data-testid="storyboard-shot" className="rounded-lg border border-white/[0.05] bg-white/[0.015] p-3">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="font-mono text-zinc-600">#{shot.order}</span>
        <span className="text-zinc-200">{humanize(shot.visual.shot_type)}</span>
        <span className="text-zinc-500">· {humanize(shot.visual.camera_motion)}</span>
        <span className="text-zinc-500">· {formatDuration(shot.duration_sec)}</span>
        <Badge>{humanize(shot.provider_plan?.strategy ?? "generative")}</Badge>
        {disclosure && (
          <Badge tone="violet" title="AI disclosure shown on screen">
            {disclosure}
          </Badge>
        )}
      </div>
      {shot.description && <p className="mt-1 text-xs text-zinc-400">{shot.description}</p>}
      {bound.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-3">
          {bound.map((c) => (
            <BoundAsset key={c.candidate_id} candidate={c} blockedReason={blocked[c.candidate_id]} />
          ))}
        </div>
      )}
    </li>
  );
}

export function StoryboardPanel({ scenes, media }: { scenes: readonly Scene[]; media?: AssetSelection | null }) {
  const sorted = [...scenes].sort((a, b) => a.order - b.order);
  const candidates = candidateIndex(media);
  const blocked = media?.blocked ?? {};
  return (
    <Card id="storyboard" title="Storyboard" description="Scenes, shots and the licensed stills bound to them">
      {sorted.length === 0 ? (
        <EmptyState title="No storyboard yet">The Scene Director (A6) builds it during storyboarding.</EmptyState>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {sorted.map((scene) => (
            <article
              key={scene.id}
              data-testid="storyboard-scene"
              aria-label={`Storyboard scene ${scene.order}: ${scene.title || "Untitled"}`}
              className="rounded-xl border border-white/[0.06] bg-white/[0.015] p-4"
            >
              <header className="flex items-start gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gold-500/10 text-sm font-semibold text-gold-300 ring-1 ring-gold-500/20">
                  {scene.order}
                </span>
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-zinc-100">{scene.title || `Scene ${scene.order}`}</h3>
                  <p className="text-xs text-zinc-500">
                    {scene.story_beat ? humanize(scene.story_beat) : "No beat"} · {formatDuration(scene.duration_sec)}
                  </p>
                </div>
              </header>
              {scene.narration && <p className="mt-2 text-sm italic text-zinc-400">&ldquo;{scene.narration}&rdquo;</p>}
              <ul className="mt-3 space-y-2">
                {scene.shots.map((shot) => (
                  <ShotCard key={shot.id} shot={shot} candidates={candidates} blocked={blocked} />
                ))}
              </ul>
            </article>
          ))}
        </div>
      )}
    </Card>
  );
}
