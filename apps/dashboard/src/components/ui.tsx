import type { ProductionState } from "@cineforge/schemas";
import type { ComponentPropsWithRef, ReactNode } from "react";
import { errorMessage, isApiError } from "@/lib/api";
import { humanize } from "@/lib/format";
import { isWorkingState } from "@/lib/workflow";
import { IconAlert, IconRefresh } from "./icons";

export function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function Card({
  title,
  description,
  actions,
  children,
  className,
  id,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={title ? headingId : undefined}
      className={cx(
        "relative rounded-2xl border border-white/[0.07] bg-ink-900/80 p-5 shadow-[0_1px_0_0_rgb(255_255_255/0.04)_inset,0_20px_40px_-24px_rgb(0_0_0/0.8)] backdrop-blur",
        className,
      )}
    >
      {(title || actions) && (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && (
              <h2 id={headingId} className="text-sm font-semibold tracking-wide text-zinc-100">
                {title}
              </h2>
            )}
            {description && <p className="mt-0.5 text-xs text-zinc-500">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

type Tone = "neutral" | "info" | "working" | "success" | "warning" | "danger" | "gold" | "violet";

const TONES: Record<Tone, string> = {
  neutral: "border-zinc-600/40 bg-zinc-500/10 text-zinc-300",
  info: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  working: "border-sky-400/40 bg-sky-400/10 text-sky-200",
  success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  danger: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  gold: "border-gold-500/40 bg-gold-500/10 text-gold-300",
  violet: "border-violet-500/40 bg-violet-500/10 text-violet-300",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const STATE_TONES: Record<ProductionState, Tone> = {
  DRAFT: "neutral",
  RESEARCHING: "working",
  SCRIPTING: "working",
  STORYBOARDING: "working",
  AWAITING_APPROVAL: "gold",
  GENERATING: "working",
  ASSEMBLING: "working",
  REVIEWING: "working",
  READY: "success",
  DELIVERED: "success",
  PAUSED_BUDGET: "warning",
  NEEDS_REVIEW: "warning",
  FAILED: "danger",
  CANCELLED: "neutral",
};

export function StateBadge({ state }: { state: ProductionState }) {
  const working = isWorkingState(state);
  return (
    <Badge tone={STATE_TONES[state]} className="uppercase tracking-wider">
      {working && (
        <span className="relative flex h-1.5 w-1.5" aria-hidden="true">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-300 opacity-75" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-sky-300" />
        </span>
      )}
      <span data-testid="state-badge">{humanize(state)}</span>
    </Badge>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const value = status ?? "planned";
  const tone: Tone =
    value === "complete" || value === "approved" || value === "succeeded" || value === "verified" || value === "passed"
      ? "success"
      : value === "failed" || value === "blocked" || value === "disputed"
        ? "danger"
        : value === "in_progress" || value === "running" || value === "queued"
          ? "working"
          : value === "needs_repair" || value === "needs_human" || value === "unverified" || value === "dramatized"
            ? "warning"
            : "neutral";
  return <Badge tone={tone}>{humanize(value)}</Badge>;
}

export function SimulatedBadge({ className }: { className?: string }) {
  return (
    <Badge
      tone="violet"
      className={className}
      title="Phase 0 uses mock providers only. Costs are simulated but go through the real budget ledger."
    >
      <span aria-hidden="true">◆</span> Simulated costs
    </Badge>
  );
}

export function ProgressBar({
  value,
  label,
  tone = "gold",
  className,
}: {
  value: number;
  label: string;
  tone?: "gold" | "sky" | "emerald" | "rose";
  className?: string;
}) {
  const pct = Math.min(100, Math.max(0, Math.round(value)));
  const fill = {
    gold: "from-gold-600 to-gold-300",
    sky: "from-sky-600 to-sky-300",
    emerald: "from-emerald-600 to-emerald-300",
    rose: "from-rose-600 to-rose-300",
  }[tone];
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className={cx("h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]", className)}
    >
      <div
        className={cx("h-full rounded-full bg-gradient-to-r transition-[width] duration-700", fill)}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "warning";

const BUTTONS: Record<ButtonVariant, string> = {
  primary:
    "bg-gradient-to-b from-gold-400 to-gold-600 text-ink-950 shadow-[0_8px_24px_-12px_rgb(235_165_59/0.8)] hover:from-gold-300 hover:to-gold-500",
  secondary: "border border-white/10 bg-white/[0.04] text-zinc-100 hover:bg-white/[0.08]",
  ghost: "text-zinc-300 hover:bg-white/[0.06] hover:text-zinc-100",
  danger: "bg-gradient-to-b from-rose-500 to-rose-700 text-white hover:from-rose-400 hover:to-rose-600",
  warning: "bg-gradient-to-b from-amber-400 to-amber-600 text-ink-950 hover:from-amber-300 hover:to-amber-500",
};

export function Button({
  variant = "secondary",
  busy = false,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ComponentPropsWithRef<"button"> & { variant?: ButtonVariant; busy?: boolean }) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold-400 disabled:cursor-not-allowed disabled:opacity-50",
        BUTTONS[variant],
        className,
      )}
      {...rest}
    >
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx("inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent", className)}
    />
  );
}

export function Loading({ label = "Loading…", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-2.5">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="h-4 animate-pulse rounded bg-white/[0.05]"
          style={{ width: `${92 - i * 14}%` }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const unavailable = isApiError(error) && error.unavailable;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-rose-500/20 bg-rose-500/[0.06] p-4">
      <span className="mt-0.5 text-rose-300">
        <IconAlert />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-rose-200">
          {title ?? (unavailable ? "API unavailable" : "Could not load data")}
        </p>
        <p className="mt-0.5 text-sm text-rose-200/70">{errorMessage(error)}</p>
      </div>
      {onRetry && (
        <Button variant="ghost" onClick={onRetry} className="shrink-0">
          <IconRefresh size={15} /> Retry
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-white/10 p-6 text-center">
      <p className="text-sm font-medium text-zinc-300">{title}</p>
      {children && <div className="mt-1 text-sm text-zinc-500">{children}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3", className)}>
      <dt className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">{label}</dt>
      <dd className="mt-1 text-lg font-semibold tabular-nums text-zinc-100">{value}</dd>
      {hint && <dd className="mt-0.5 text-xs text-zinc-500">{hint}</dd>}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-zinc-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <code className={cx("font-mono text-[12px] text-zinc-400", className)}>{children}</code>;
}
