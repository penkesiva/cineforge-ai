import type { MasterRender } from "@cineforge/schemas";
import { formatBytes, formatDuration } from "@/lib/format";
import { Card, EmptyState, Mono, Stat } from "../ui";

export function MasterRenderPanel({
  assetId,
  master,
  contentUrl,
}: {
  assetId: string | null | undefined;
  master: MasterRender | null | undefined;
  contentUrl: (assetId: string) => string;
}) {
  return (
    <Card id="master" title="Master render">
      {!assetId ? (
        <EmptyState title="No master render yet">
          The media worker renders the master with FFmpeg during assembling.
        </EmptyState>
      ) : (
        <div className="grid gap-5 md:grid-cols-[minmax(0,260px)_1fr]">
          <div className="overflow-hidden rounded-xl border border-white/10 bg-black shadow-[0_20px_50px_-20px_rgb(0_0_0/0.9)]">
            <video
              data-testid="master-video"
              controls
              playsInline
              preload="metadata"
              src={contentUrl(assetId)}
              className="aspect-[9/16] w-full bg-black object-contain"
            >
              Your browser cannot play this video.
            </video>
          </div>
          <div>
            {master ? (
              <dl className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                <Stat label="Duration" value={formatDuration(master.duration_sec)} />
                <Stat label="Resolution" value={`${master.width}×${master.height}`} />
                <Stat label="Frame rate" value={`${master.fps} fps`} />
                <Stat label="Video codec" value={master.codec} />
                <Stat label="Audio codec" value={master.audio_codec ?? "none"} />
                <Stat label="Size" value={formatBytes(master.size_bytes)} />
              </dl>
            ) : (
              <p className="text-sm text-zinc-500">Probe information is not available yet.</p>
            )}
            <p className="mt-3 text-xs text-zinc-500">
              Asset <Mono>{assetId}</Mono>
              {master?.sha256 && (
                <>
                  {" · sha256 "}
                  <Mono>{master.sha256.slice(0, 16)}…</Mono>
                </>
              )}
            </p>
            <a
              href={contentUrl(assetId)}
              download
              className="mt-3 inline-block text-sm text-sky-300 hover:text-sky-200 hover:underline"
            >
              Download MP4
            </a>
          </div>
        </div>
      )}
    </Card>
  );
}
