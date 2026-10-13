"use client";

import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { cx } from "../ui";
import { IconX } from "../icons";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export type DialogTone = "default" | "warning" | "danger" | "success" | "error" | "info";

const BADGE_TONES: Record<DialogTone, string> = {
  default: "from-gold-300/25 to-gold-600/10 text-gold-300 ring-gold-400/30",
  info: "from-sky-300/25 to-sky-600/10 text-sky-300 ring-sky-400/30",
  success: "from-emerald-300/25 to-emerald-600/10 text-emerald-300 ring-emerald-400/30",
  warning: "from-amber-300/25 to-amber-600/10 text-amber-300 ring-amber-400/30",
  danger: "from-rose-300/25 to-rose-600/10 text-rose-300 ring-rose-400/30",
  error: "from-rose-300/25 to-rose-600/10 text-rose-300 ring-rose-400/30",
};

const NOTE_TONES: Record<DialogTone, string> = {
  default: "border-gold-500/20 bg-gold-500/[0.06]",
  info: "border-sky-500/20 bg-sky-500/[0.06]",
  success: "border-emerald-500/20 bg-emerald-500/[0.06]",
  warning: "border-amber-500/25 bg-amber-500/[0.07]",
  danger: "border-rose-500/25 bg-rose-500/[0.07]",
  error: "border-rose-500/25 bg-rose-500/[0.07]",
};

export interface DialogShellProps {
  open: boolean;
  role: "dialog" | "alertdialog";
  tone: DialogTone;
  /** Exposed as `data-variant` for styling hooks and tests. */
  variant: string;
  icon: ReactNode;
  title: ReactNode;
  message?: ReactNode;
  note?: ReactNode;
  noteLabel?: string;
  children?: ReactNode;
  footer: ReactNode;
  onDismiss: () => void;
  /** While true, Escape / backdrop / close button are ignored. */
  dismissDisabled?: boolean;
  initialFocusRef: RefObject<HTMLElement | null>;
}

export function DialogShell({
  open,
  role,
  tone,
  variant,
  icon,
  title,
  message,
  note,
  noteLabel,
  children,
  footer,
  onDismiss,
  dismissDisabled = false,
  initialFocusRef,
}: DialogShellProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const messageId = useId();
  const dismissRef = useRef({ onDismiss, dismissDisabled });
  useEffect(() => {
    dismissRef.current = { onDismiss, dismissDisabled };
  }, [onDismiss, dismissDisabled]);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTarget = initialFocusRef.current ?? panelRef.current?.querySelector<HTMLElement>(FOCUSABLE);
    focusTarget?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        if (!dismissRef.current.dismissDisabled) dismissRef.current.onDismiss();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusables = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusables.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusables[0]!;
      const last = focusables[focusables.length - 1]!;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !panelRef.current.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !panelRef.current.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus?.();
    };
  }, [open, initialFocusRef]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        aria-hidden="true"
        data-testid="dialog-backdrop"
        className="absolute inset-0 animate-backdrop-in bg-ink-950/70 backdrop-blur-md"
        onClick={() => {
          if (!dismissDisabled) onDismiss();
        }}
      />
      <div
        ref={panelRef}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={message ? messageId : undefined}
        data-variant={variant}
        className="film-grain relative w-full max-w-md animate-dialog-in rounded-2xl border border-white/10 bg-gradient-to-b from-ink-800 to-ink-900 p-6 shadow-[0_30px_80px_-20px_rgb(0_0_0/0.9)]"
      >
        <button
          type="button"
          aria-label="Close"
          onClick={onDismiss}
          disabled={dismissDisabled}
          className="absolute right-3 top-3 rounded-md p-1.5 text-zinc-500 transition hover:bg-white/5 hover:text-zinc-200 disabled:opacity-40"
        >
          <IconX size={16} />
        </button>
        <div className="flex items-start gap-4">
          <span
            data-testid="dialog-icon"
            className={cx(
              "flex h-11 w-11 shrink-0 animate-badge-pop items-center justify-center rounded-xl bg-gradient-to-br ring-1",
              BADGE_TONES[tone],
            )}
          >
            {icon}
          </span>
          <div className="min-w-0 flex-1 pt-0.5">
            <h2 id={titleId} className="pr-6 text-base font-semibold text-zinc-50">
              {title}
            </h2>
            {message && (
              <div id={messageId} className="mt-1.5 text-sm leading-relaxed text-zinc-400">
                {message}
              </div>
            )}
          </div>
        </div>
        {note && (
          <div className={cx("mt-4 rounded-xl border px-3.5 py-3 text-sm text-zinc-300", NOTE_TONES[tone])}>
            {noteLabel && (
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">{noteLabel}</p>
            )}
            {note}
          </div>
        )}
        {children && <div className="mt-4">{children}</div>}
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">{footer}</div>
      </div>
    </div>,
    document.body,
  );
}
