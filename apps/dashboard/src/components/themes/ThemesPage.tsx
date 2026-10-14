"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { IconRefresh } from "../icons";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader } from "../ui";

export function ThemesPage() {
  const themes = useResource("themes", () => api.listThemes());
  return (
    <>
      <PageHeader
        title="Themes"
        description="Versioned creative profiles. Productions pin a theme version, so edits never change past work."
        actions={
          <Button variant="ghost" onClick={() => void themes.reload()} aria-label="Refresh themes">
            <IconRefresh size={15} />
          </Button>
        }
      />
      <Card>
        {themes.loading ? (
          <Loading label="Loading themes…" rows={4} />
        ) : !themes.data ? (
          <ErrorState error={themes.error} onRetry={() => void themes.reload()} />
        ) : themes.data.length === 0 ? (
          <EmptyState title="No themes yet">Themes are seeded from packages/configurations/themes.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <caption className="sr-only">Themes (latest versions)</caption>
              <thead className="text-[11px] uppercase tracking-wider text-zinc-500">
                <tr>
                  <th scope="col" className="pb-2 pr-3 font-medium">Theme</th>
                  <th scope="col" className="pb-2 pr-3 font-medium">Genres</th>
                  <th scope="col" className="pb-2 pr-3 font-medium">Default mode</th>
                  <th scope="col" className="pb-2 text-right font-medium">Version</th>
                </tr>
              </thead>
              <tbody>
                {themes.data.map((theme) => (
                  <tr key={theme.id} data-testid="theme-row" className="border-t border-white/[0.05] align-top">
                    <td className="py-3 pr-3">
                      <Link
                        href={`/themes/${encodeURIComponent(theme.id)}`}
                        className="font-semibold text-zinc-100 hover:text-gold-300"
                      >
                        {theme.name}
                      </Link>
                      <p className="mt-0.5 max-w-xl text-xs text-zinc-500">{theme.purpose}</p>
                    </td>
                    <td className="py-3 pr-3">
                      <span className="flex flex-wrap gap-1">
                        {theme.genres.map((genre) => (
                          <Badge key={genre}>{humanize(genre)}</Badge>
                        ))}
                      </span>
                    </td>
                    <td className="py-3 pr-3 text-zinc-300">{humanize(theme.default_mode)}</td>
                    <td className="py-3 text-right">
                      <Badge tone="gold">v{theme.version}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
