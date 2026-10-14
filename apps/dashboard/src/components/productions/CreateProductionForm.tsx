"use client";

import type {
  CreateProductionRequest,
  ProductionMode,
  ProductionModePolicy,
  ThemeSummary,
} from "@cineforge/schemas";
import { useId, useState, type FormEvent } from "react";
import { formatUsd, humanize } from "@/lib/format";
import {
  DEFAULT_DURATION_SEC,
  DURATION_MAX_SEC,
  DURATION_MIN_SEC,
  TOPIC_MAX,
  validateCreateProduction,
  type CreateProductionFormErrors,
  type CreateProductionFormValues,
} from "@/lib/validation";
import { Field } from "../Field";
import { Button, cx, inputClass } from "../ui";

export interface CreateProductionFormProps {
  themes: readonly ThemeSummary[];
  modes: readonly ProductionModePolicy[];
  onSubmit: (request: CreateProductionRequest) => void | Promise<void>;
  submitting?: boolean;
  onCancel?: () => void;
}

function initialValues(themes: readonly ThemeSummary[], modes: readonly ProductionModePolicy[]): CreateProductionFormValues {
  const theme = themes.find((t) => t.id === "time-traveler") ?? themes[0];
  const preferred: ProductionMode = theme?.default_mode ?? "balanced";
  const mode = modes.find((m) => m.mode === preferred)?.mode ?? modes[0]?.mode ?? "";
  return {
    themeId: theme?.id ?? "",
    themeVersion: "",
    topic: "",
    title: "",
    mode,
    durationSec: String(DEFAULT_DURATION_SEC),
    budgetUsd: "",
    autoApprove: false,
  };
}

/** Theme versions are created sequentially from 1, so every version up to the latest exists. */
export function themeVersionOptions(theme: ThemeSummary | undefined): number[] {
  if (!theme) return [];
  return Array.from({ length: Math.max(0, theme.version - 1) }, (_, i) => theme.version - 1 - i);
}

export function CreateProductionForm({ themes, modes, onSubmit, submitting = false, onCancel }: CreateProductionFormProps) {
  const uid = useId();
  const [values, setValues] = useState<CreateProductionFormValues>(() => initialValues(themes, modes));
  const [errors, setErrors] = useState<CreateProductionFormErrors>({});
  const [submitted, setSubmitted] = useState(false);

  const selectedMode = modes.find((m) => m.mode === values.mode);
  const selectedTheme = themes.find((t) => t.id === values.themeId);

  function update<K extends keyof CreateProductionFormValues>(key: K, value: CreateProductionFormValues[K]) {
    const next = { ...values, [key]: value };
    setValues(next);
    if (submitted) setErrors(validateCreateProduction(next).errors);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    const result = validateCreateProduction(values);
    setErrors(result.errors);
    if (!result.request) {
      const firstInvalid = Object.keys(result.errors)[0];
      if (firstInvalid) document.getElementById(`${uid}-${firstInvalid}`)?.focus();
      return;
    }
    await onSubmit(result.request);
  }

  const fieldId = (key: keyof CreateProductionFormValues) => `${uid}-${key}`;
  const describedBy = (key: keyof CreateProductionFormValues, hasHint = false) =>
    errors[key] ? `${fieldId(key)}-error` : hasHint ? `${fieldId(key)}-hint` : undefined;

  return (
    <form noValidate onSubmit={handleSubmit} aria-label="New production" className="grid gap-4 md:grid-cols-2">
      <Field id={fieldId("themeId")} label="Theme" error={errors.themeId} hint={selectedTheme?.purpose}>
        <select
          id={fieldId("themeId")}
          className={inputClass}
          value={values.themeId}
          aria-invalid={errors.themeId ? true : undefined}
          aria-describedby={describedBy("themeId", Boolean(selectedTheme))}
          onChange={(e) => {
            const next = { ...values, themeId: e.target.value, themeVersion: "" };
            setValues(next);
            if (submitted) setErrors(validateCreateProduction(next).errors);
          }}
        >
          {themes.length === 0 && <option value="">No themes available</option>}
          {themes.map((theme) => (
            <option key={theme.id} value={theme.id}>
              {theme.name} (v{theme.version})
            </option>
          ))}
        </select>
      </Field>

      <Field
        id={fieldId("themeVersion")}
        label="Theme version"
        error={errors.themeVersion}
        hint="Pin an older version to reproduce earlier productions."
      >
        <select
          id={fieldId("themeVersion")}
          className={inputClass}
          value={values.themeVersion ?? ""}
          disabled={!selectedTheme}
          aria-invalid={errors.themeVersion ? true : undefined}
          aria-describedby={describedBy("themeVersion", true)}
          onChange={(e) => update("themeVersion", e.target.value)}
        >
          {selectedTheme && <option value="">Latest (v{selectedTheme.version})</option>}
          {themeVersionOptions(selectedTheme).map((version) => (
            <option key={version} value={String(version)}>
              v{version}
            </option>
          ))}
        </select>
      </Field>

      <Field
        id={fieldId("mode")}
        label="Production mode"
        error={errors.mode}
        hint={selectedMode ? `${selectedMode.description}` : undefined}
        className="md:col-span-2"
      >
        <select
          id={fieldId("mode")}
          className={inputClass}
          value={values.mode}
          aria-invalid={errors.mode ? true : undefined}
          aria-describedby={describedBy("mode", Boolean(selectedMode))}
          onChange={(e) => update("mode", e.target.value as ProductionMode)}
        >
          {modes.length === 0 && <option value="">No modes available</option>}
          {modes.map((mode) => (
            <option key={mode.mode} value={mode.mode}>
              {humanize(mode.mode)} · {formatUsd(mode.default_budget_usd)} default budget
            </option>
          ))}
        </select>
      </Field>

      <Field
        id={fieldId("topic")}
        label="Topic"
        error={errors.topic}
        hint={`${values.topic.trim().length}/${TOPIC_MAX} characters`}
        className="md:col-span-2"
      >
        <textarea
          id={fieldId("topic")}
          rows={2}
          className={cx(inputClass, "resize-y")}
          placeholder="The night the Eiffel Tower first lit up for the 1889 World's Fair"
          value={values.topic}
          maxLength={TOPIC_MAX + 50}
          aria-invalid={errors.topic ? true : undefined}
          aria-describedby={describedBy("topic", true)}
          onChange={(e) => update("topic", e.target.value)}
        />
      </Field>

      <Field id={fieldId("title")} label="Title (optional)" className="md:col-span-2">
        <input
          id={fieldId("title")}
          className={inputClass}
          value={values.title}
          placeholder="Eiffel Tower, 1889"
          onChange={(e) => update("title", e.target.value)}
        />
      </Field>

      <Field
        id={fieldId("durationSec")}
        label="Target duration (seconds)"
        error={errors.durationSec}
        hint={`${DURATION_MIN_SEC} to ${DURATION_MAX_SEC} seconds`}
      >
        <input
          id={fieldId("durationSec")}
          type="number"
          inputMode="numeric"
          min={DURATION_MIN_SEC}
          max={DURATION_MAX_SEC}
          step={1}
          className={inputClass}
          value={values.durationSec}
          aria-invalid={errors.durationSec ? true : undefined}
          aria-describedby={describedBy("durationSec", true)}
          onChange={(e) => update("durationSec", e.target.value)}
        />
      </Field>

      <Field
        id={fieldId("budgetUsd")}
        label="Budget override (USD)"
        error={errors.budgetUsd}
        hint={
          selectedMode
            ? `Leave empty to use the ${humanize(selectedMode.mode).toLowerCase()} default of ${formatUsd(selectedMode.default_budget_usd)}`
            : "Leave empty to use the mode default"
        }
      >
        <input
          id={fieldId("budgetUsd")}
          type="number"
          inputMode="decimal"
          min={0}
          step="0.01"
          className={inputClass}
          placeholder={selectedMode ? selectedMode.default_budget_usd.toFixed(2) : ""}
          value={values.budgetUsd}
          aria-invalid={errors.budgetUsd ? true : undefined}
          aria-describedby={describedBy("budgetUsd", true)}
          onChange={(e) => update("budgetUsd", e.target.value)}
        />
      </Field>

      <div className="flex items-center justify-between gap-4 rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3 md:col-span-2">
        <div>
          <p id={`${uid}-auto-label`} className="text-sm font-medium text-zinc-200">
            Auto-approve generation spend
          </p>
          <p className="text-xs text-zinc-500">
            When off, the production stops at the approval gate so you can review the estimate.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={values.autoApprove}
          aria-labelledby={`${uid}-auto-label`}
          onClick={() => update("autoApprove", !values.autoApprove)}
          className={cx(
            "relative h-6 w-11 shrink-0 rounded-full transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold-400",
            values.autoApprove ? "bg-gold-500" : "bg-white/10",
          )}
        >
          <span
            aria-hidden="true"
            className={cx(
              "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-[left] duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]",
              values.autoApprove ? "left-[22px]" : "left-0.5",
            )}
          />
        </button>
      </div>

      <div className="flex justify-end gap-2 md:col-span-2">
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
        )}
        <Button type="submit" variant="primary" busy={submitting}>
          Create production
        </Button>
      </div>
    </form>
  );
}
