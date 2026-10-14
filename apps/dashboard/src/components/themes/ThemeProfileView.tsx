import type { ThemeProfile } from "@cineforge/schemas";
import type { ReactNode } from "react";
import { formatDuration, humanize } from "@/lib/format";
import { Badge } from "../ui";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 border-t border-white/[0.04] py-2 sm:grid-cols-[160px_1fr]">
      <dt className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">{label}</dt>
      <dd className="text-sm text-zinc-200">{children}</dd>
    </div>
  );
}

function Chips({ items }: { items: readonly string[] | undefined }) {
  if (!items || items.length === 0) return <span className="text-zinc-600">None</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((item) => (
        <Badge key={item}>{humanize(item)}</Badge>
      ))}
    </span>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title}>
      <h3 className="mb-1 mt-4 text-[11px] font-semibold uppercase tracking-wider text-gold-400/80">{title}</h3>
      <dl>{children}</dl>
    </section>
  );
}

/** Read-only view of one theme version. */
export function ThemeProfileView({ profile }: { profile: ThemeProfile }) {
  const { narrative, direction, production, constraints, performance } = profile;
  return (
    <div data-testid="theme-profile" data-version={profile.version}>
      <Section title="Identity">
        <Row label="Name">{profile.name}</Row>
        <Row label="Purpose">{profile.purpose}</Row>
        <Row label="Audience">{profile.audience}</Row>
        <Row label="Genres">
          <Chips items={profile.genres} />
        </Row>
        <Row label="Tone">{profile.tone}</Row>
        <Row label="Visual style">{profile.visual_style}</Row>
        <Row label="Pacing">{profile.pacing}</Row>
      </Section>
      <Section title="Narrative">
        <Row label="Hook strategy">{narrative.hook_strategy}</Row>
        <Row label="Story beats">
          <ol className="list-decimal space-y-0.5 pl-5">
            {narrative.story_beats.map((beat, i) => (
              <li key={`${beat}-${i}`}>{beat}</li>
            ))}
          </ol>
        </Row>
        <Row label="Factual rigor">{humanize(narrative.factual_rigor ?? "strict")}</Row>
        <Row label="Narration style">{narrative.narration_style}</Row>
        <Row label="Call to action">{narrative.cta || <span className="text-zinc-600">None</span>}</Row>
      </Section>
      <Section title="Performance">
        <Row label="Voice">{performance.voice}</Row>
        <Row label="Language">{performance.language ?? "en-US"}</Row>
      </Section>
      <Section title="Direction">
        <Row label="Camera grammar">
          <Chips items={direction.camera_grammar} />
        </Row>
        <Row label="Lighting">
          <Chips items={direction.lighting} />
        </Row>
        <Row label="Atmosphere">
          <Chips items={direction.atmosphere} />
        </Row>
      </Section>
      <Section title="Production">
        <Row label="Duration target">{formatDuration(production.duration_target_sec ?? 45)}</Row>
        <Row label="Scenes">
          {production.min_scenes ?? 4} to {production.max_scenes ?? 6}
        </Row>
        <Row label="Default mode">{humanize(production.default_mode ?? "balanced")}</Row>
        <Row label="Strategies">
          <Chips items={production.preferred_strategies} />
        </Row>
      </Section>
      <Section title="Constraints">
        <Row label="Prohibited claims">
          {constraints.prohibited_claims && constraints.prohibited_claims.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-5">
              {constraints.prohibited_claims.map((claim) => (
                <li key={claim}>{claim}</li>
              ))}
            </ul>
          ) : (
            <span className="text-zinc-600">None</span>
          )}
        </Row>
        <Row label="Rights policy">{humanize(constraints.rights_policy ?? "fail_closed")}</Row>
      </Section>
    </div>
  );
}
