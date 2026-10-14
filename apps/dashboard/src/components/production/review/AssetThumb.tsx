import type { AssetCandidate } from "@cineforge/schemas";
import { IconFilm } from "../../icons";
import { cx, safeHref } from "../../ui";

/** Remote provider thumbnail, or a placeholder when there is no http(s) thumbnail. */
export function AssetThumb({ candidate, className }: { candidate: AssetCandidate; className?: string }) {
  const src = safeHref(candidate.thumbnail_url);
  const alt = `${candidate.title} (${candidate.provider})`;
  const box = cx("shrink-0 overflow-hidden rounded-lg border border-white/10 bg-ink-950", className);
  if (!src) {
    return (
      <div role="img" aria-label={`No thumbnail: ${alt}`} data-testid="asset-placeholder" className={cx(box, "flex items-center justify-center text-zinc-700")}>
        <IconFilm size={20} />
      </div>
    );
  }
  return (
    <div className={box}>
      {/* Provider thumbnails come from arbitrary hosts, so next/image (domain allowlist) does not fit. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" className="h-full w-full object-cover" />
    </div>
  );
}
