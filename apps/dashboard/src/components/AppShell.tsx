"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { HealthIndicator } from "./HealthIndicator";
import { IconAgents, IconCoins, IconFilm, IconOverview, Logo } from "./icons";
import { cx } from "./ui";

const NAV = [
  { href: "/", label: "Overview", icon: IconOverview },
  { href: "/productions", label: "Productions", icon: IconFilm },
  { href: "/agents", label: "Agents", icon: IconAgents },
  { href: "/costs", label: "Costs", icon: IconCoins },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  return (
    <div className="flex min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-gold-400 focus:px-3 focus:py-2 focus:text-ink-950"
      >
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-white/[0.06] bg-ink-950/60 px-4 py-5 backdrop-blur md:flex">
        <Link href="/" className="mb-8 flex items-center gap-2.5 px-2">
          <Logo />
          <span className="leading-tight">
            <span className="block text-sm font-semibold tracking-wide text-zinc-50">CineForge AI</span>
            <span className="block text-[11px] text-zinc-500">Production control room</span>
          </span>
        </Link>
        <nav aria-label="Main" className="flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition",
                  active
                    ? "bg-gradient-to-r from-gold-500/15 to-transparent text-gold-300 ring-1 ring-gold-500/20"
                    : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-100",
                )}
              >
                <Icon />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-[11px] leading-relaxed text-zinc-500">
          <p className="font-semibold text-zinc-400">Phase 0 demo</p>
          Mock providers only. No paid API calls are made.
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-white/[0.06] bg-ink-950/70 px-4 py-3 backdrop-blur md:px-8">
          <Link href="/" className="flex items-center gap-2 md:hidden">
            <Logo size={26} />
            <span className="text-sm font-semibold text-zinc-50">CineForge AI</span>
          </Link>
          <nav aria-label="Main mobile" className="flex gap-1 overflow-x-auto md:hidden">
            {NAV.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                aria-current={isActive(pathname, href) ? "page" : undefined}
                className={cx(
                  "rounded-md px-2 py-1 text-xs",
                  isActive(pathname, href) ? "bg-gold-500/15 text-gold-300" : "text-zinc-400",
                )}
              >
                {label}
              </Link>
            ))}
          </nav>
          <p className="hidden text-xs text-zinc-500 md:block">Theme-driven multi-agent cinematic shorts</p>
          <HealthIndicator />
        </header>
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 md:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
