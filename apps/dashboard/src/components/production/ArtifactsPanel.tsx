import type { ProductionArtifacts, ReviewFinding, Severity } from "@cineforge/schemas";
import { humanize } from "@/lib/format";
import { Badge, Card, EmptyState, StatusBadge } from "../ui";

const SEVERITY_TONE: Record<Severity, "neutral" | "info" | "warning" | "danger"> = {
  info: "info",
  minor: "neutral",
  major: "warning",
  critical: "danger",
};

function Findings({ findings }: { findings: readonly ReviewFinding[] }) {
  if (findings.length === 0) return <p className="text-sm text-zinc-500">No findings. Review passed cleanly.</p>;
  return (
    <ul className="space-y-2">
      {findings.map((f, i) => (
        <li
          key={f.id ?? i}
          data-testid="review-finding"
          className="rounded-lg border border-white/[0.05] bg-white/[0.015] px-3 py-2 text-sm"
        >
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={SEVERITY_TONE[f.severity]}>{humanize(f.severity)}</Badge>
            <Badge>{humanize(f.gate)} gate</Badge>
            {f.blocking && <Badge tone="danger">Blocking</Badge>}
            {f.retry_scope && f.retry_scope !== "none" && <Badge tone="info">Retry {f.retry_scope}</Badge>}
          </div>
          <p className="mt-1.5 text-zinc-200">{f.message}</p>
          {f.recommended_fix && <p className="mt-0.5 text-xs text-zinc-500">Fix: {f.recommended_fix}</p>}
        </li>
      ))}
    </ul>
  );
}

export function ArtifactsPanel({
  artifacts,
  manifestFindings = [],
}: {
  artifacts: ProductionArtifacts;
  manifestFindings?: readonly ReviewFinding[];
}) {
  const { script, review, treatment } = artifacts;
  const findings = review?.findings ?? manifestFindings;
  const empty = !script && !review && !treatment;
  return (
    <Card id="artifacts" title="Artifacts" description="Typed outputs from the latest successful agent runs">
      {empty ? (
        <EmptyState title="No artifacts yet">Treatment, script and review outputs appear as agents finish.</EmptyState>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          {treatment && (
            <section aria-label="Creative treatment" className="lg:col-span-2">
              <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Creative treatment
              </h3>
              <p className="text-sm text-zinc-200">{treatment.logline}</p>
              <p className="mt-1 text-xs text-zinc-500">
                {humanize(treatment.genre)} · {treatment.tone} · {treatment.narrative_style}
              </p>
            </section>
          )}

          {script && (
            <section aria-label="Script" className="lg:col-span-2">
              <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Script · {script.word_count} words · ~{Math.round(script.estimated_duration_sec)}s
              </h3>
              <p className="mb-2 rounded-lg border border-gold-500/20 bg-gold-500/[0.05] px-3 py-2 text-sm text-gold-200">
                <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-gold-400/80">Hook</span>
                {script.hook}
              </p>
              <ol className="space-y-1.5">
                {script.lines.map((line, i) => (
                  <li key={i} data-testid="script-line" className="flex gap-2 text-sm">
                    <span className="w-6 shrink-0 text-right font-mono text-[11px] leading-5 text-zinc-600">
                      S{line.scene_order}
                    </span>
                    <span className="text-zinc-300">
                      {line.speaker && line.speaker !== "narrator" && (
                        <span className="mr-1 font-semibold text-zinc-200">{line.speaker}:</span>
                      )}
                      {line.text}
                      {line.dramatized && (
                        <Badge tone="violet" className="ml-1.5">
                          Dramatized
                        </Badge>
                      )}
                    </span>
                  </li>
                ))}
              </ol>
              {script.cta && <p className="mt-2 text-xs text-zinc-500">CTA: {script.cta}</p>}
            </section>
          )}

          {(review || findings.length > 0) && (
            <section aria-label="Review findings" className="lg:col-span-2">
              <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Review findings
                {review && <StatusBadge status={review.status} />}
              </h3>
              {review?.scores && review.scores.length > 0 && (
                <dl className="mb-3 flex flex-wrap gap-2">
                  {review.scores.map((s) => (
                    <div key={s.dimension} className="rounded-md bg-white/[0.03] px-2.5 py-1 text-xs">
                      <dt className="inline text-zinc-500">{humanize(s.dimension)} </dt>
                      <dd className="inline tabular-nums text-zinc-200">{s.score.toFixed(2)}</dd>
                    </div>
                  ))}
                </dl>
              )}
              <Findings findings={findings} />
            </section>
          )}
        </div>
      )}
    </Card>
  );
}
