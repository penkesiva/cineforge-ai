import type { ProductionEvent, ProductionState } from "@cineforge/schemas";
import { formatDateTime, humanize } from "@/lib/format";
import {
  EXCEPTION_DEFAULT_MESSAGES,
  isExceptionState,
  latestEventInto,
  workflowSteps,
  type StepStatus,
} from "@/lib/workflow";
import { IconAlert, IconCheck, IconStop } from "./icons";
import { cx } from "./ui";

const STEP_LABELS: Partial<Record<ProductionState, string>> = {
  AWAITING_APPROVAL: "Approval",
};

const DOT: Record<StepStatus, string> = {
  complete: "border-gold-500/60 bg-gold-500/20 text-gold-300",
  current: "border-sky-300 bg-sky-400/20 text-sky-200 shadow-[0_0_0_4px_rgb(56_189_248/0.15)]",
  halted: "border-amber-400 bg-amber-400/20 text-amber-200 shadow-[0_0_0_4px_rgb(251_191_36/0.15)]",
  upcoming: "border-white/10 bg-ink-850 text-zinc-600",
};

export function WorkflowStepper({
  state,
  events = [],
}: {
  state: ProductionState;
  events?: readonly ProductionEvent[];
}) {
  const steps = workflowSteps(state, events);
  return (
    <div>
      <ol aria-label="Workflow progress" className="flex w-full items-start overflow-x-auto pb-1">
        {steps.map((step, index) => {
          const isLast = index === steps.length - 1;
          return (
            <li
              key={step.state}
              data-step={step.state}
              data-status={step.status}
              aria-current={step.status === "current" || step.status === "halted" ? "step" : undefined}
              className="relative flex min-w-[76px] flex-1 flex-col items-center text-center"
            >
              {!isLast && (
                <span
                  aria-hidden="true"
                  className={cx(
                    "absolute left-1/2 top-3.5 h-px w-full",
                    step.status === "complete" ? "bg-gold-500/50" : "bg-white/10",
                  )}
                />
              )}
              <span
                className={cx(
                  "relative z-10 flex h-7 w-7 items-center justify-center rounded-full border text-[11px] font-semibold",
                  DOT[step.status],
                )}
              >
                {step.status === "complete" ? (
                  <IconCheck size={13} />
                ) : step.status === "halted" ? (
                  <IconAlert size={13} />
                ) : (
                  index + 1
                )}
              </span>
              <span
                className={cx(
                  "mt-2 px-1 text-[11px] leading-tight",
                  step.status === "current" && "font-semibold text-sky-200",
                  step.status === "halted" && "font-semibold text-amber-200",
                  step.status === "complete" && "text-zinc-300",
                  step.status === "upcoming" && "text-zinc-600",
                )}
              >
                {STEP_LABELS[step.state] ?? humanize(step.state)}
                <span className="sr-only"> ({step.status})</span>
              </span>
            </li>
          );
        })}
      </ol>
      <ExceptionBanner state={state} events={events} />
    </div>
  );
}

export function ExceptionBanner({
  state,
  events = [],
}: {
  state: ProductionState;
  events?: readonly ProductionEvent[];
}) {
  if (!isExceptionState(state)) return null;
  const event = latestEventInto(state, events);
  const message = event?.message || EXCEPTION_DEFAULT_MESSAGES[state];
  const danger = state === "FAILED";
  const muted = state === "CANCELLED";
  return (
    <div
      role="alert"
      data-testid="exception-banner"
      data-state={state}
      className={cx(
        "mt-5 flex items-start gap-3 rounded-xl border p-4",
        danger && "border-rose-500/30 bg-rose-500/[0.08] text-rose-100",
        muted && "border-zinc-500/30 bg-zinc-500/[0.08] text-zinc-200",
        !danger && !muted && "border-amber-500/30 bg-amber-500/[0.08] text-amber-100",
      )}
    >
      <span className="mt-0.5">{muted ? <IconStop /> : <IconAlert />}</span>
      <div className="min-w-0">
        <p className="text-sm font-semibold">
          {humanize(state)}
          {event?.from_state && (
            <span className="font-normal opacity-70"> during {humanize(event.from_state)}</span>
          )}
        </p>
        <p className="mt-0.5 text-sm opacity-80">{message}</p>
        {event?.created_at && <p className="mt-1 text-xs opacity-50">{formatDateTime(event.created_at)}</p>}
      </div>
    </div>
  );
}
