"use client";

import type { ThemeProfile } from "@cineforge/schemas";
import { useId, useState, type FormEvent } from "react";
import { humanize } from "@/lib/format";
import {
  buildThemeProfile,
  FACTUAL_RIGOR,
  themeToForm,
  type FactualRigor,
  type ThemeFormErrors,
  type ThemeFormValues,
} from "@/lib/themeForm";
import { Field } from "../Field";
import { Button, cx, inputClass } from "../ui";

export interface ThemeVersionFormProps {
  /** Latest version; the form is prefilled from it and `base_version` is its version. */
  base: ThemeProfile;
  onSubmit: (profile: ThemeProfile) => void | Promise<void>;
  submitting?: boolean;
  onCancel?: () => void;
}

type TextKey = Exclude<keyof ThemeFormValues, "factualRigor">;

export function ThemeVersionForm({ base, onSubmit, submitting = false, onCancel }: ThemeVersionFormProps) {
  const uid = useId();
  const [values, setValues] = useState<ThemeFormValues>(() => themeToForm(base));
  const [errors, setErrors] = useState<ThemeFormErrors>({});
  const [submitted, setSubmitted] = useState(false);

  const fieldId = (key: keyof ThemeFormValues) => `${uid}-${key}`;

  function update<K extends keyof ThemeFormValues>(key: K, value: ThemeFormValues[K]) {
    const next = { ...values, [key]: value };
    setValues(next);
    if (submitted) setErrors(buildThemeProfile(base, next).errors);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    const result = buildThemeProfile(base, values);
    setErrors(result.errors);
    if (!result.profile) {
      const first = Object.keys(result.errors)[0] as keyof ThemeFormValues | undefined;
      if (first) document.getElementById(fieldId(first))?.focus();
      return;
    }
    await onSubmit(result.profile);
  }

  function text(key: TextKey, label: string, options: { hint?: string; rows?: number; wide?: boolean; type?: string } = {}) {
    const id = fieldId(key);
    const describedBy = errors[key] ? `${id}-error` : options.hint ? `${id}-hint` : undefined;
    const common = {
      id,
      value: values[key],
      "aria-invalid": errors[key] ? true : undefined,
      "aria-describedby": describedBy,
      className: cx(inputClass, options.rows !== undefined && "resize-y"),
    };
    return (
      <Field id={id} label={label} hint={options.hint} error={errors[key]} className={options.wide ? "md:col-span-2" : undefined}>
        {options.rows ? (
          <textarea {...common} rows={options.rows} onChange={(e) => update(key, e.target.value)} />
        ) : (
          <input
            {...common}
            type={options.type ?? "text"}
            inputMode={options.type === "number" ? "decimal" : undefined}
            onChange={(e) => update(key, e.target.value)}
          />
        )}
      </Field>
    );
  }

  return (
    <form noValidate onSubmit={handleSubmit} aria-label="New theme version" className="grid gap-4 md:grid-cols-2">
      <p className="text-xs text-zinc-500 md:col-span-2">
        Prefilled from v{base.version}. Saving creates v{base.version + 1}; existing productions keep their pinned
        version.
      </p>
      {text("name", "Name")}
      {text("audience", "Audience")}
      {text("purpose", "Purpose", { rows: 2, wide: true })}
      {text("tone", "Tone")}
      {text("pacing", "Pacing")}
      {text("visualStyle", "Visual style", { wide: true })}

      <h3 className="mt-2 text-[11px] font-semibold uppercase tracking-wider text-gold-400/80 md:col-span-2">Narrative</h3>
      {text("hookStrategy", "Hook strategy", { wide: true })}
      {text("storyBeats", "Story beats", { rows: 5, hint: "One beat per line, in order." })}
      <div className="space-y-4">
        <Field id={fieldId("factualRigor")} label="Factual rigor" error={errors.factualRigor}>
          <select
            id={fieldId("factualRigor")}
            className={inputClass}
            value={values.factualRigor}
            onChange={(e) => update("factualRigor", e.target.value as FactualRigor)}
          >
            {FACTUAL_RIGOR.map((rigor) => (
              <option key={rigor} value={rigor}>
                {humanize(rigor)}
              </option>
            ))}
          </select>
        </Field>
        {text("cta", "Call to action", { hint: "Optional." })}
      </div>
      {text("narrationStyle", "Narration style", { wide: true })}

      <h3 className="mt-2 text-[11px] font-semibold uppercase tracking-wider text-gold-400/80 md:col-span-2">Direction</h3>
      {text("cameraGrammar", "Camera grammar", { hint: "Comma-separated, e.g. slow_push, drone_reveal" })}
      {text("lighting", "Lighting", { hint: "Comma-separated." })}
      {text("atmosphere", "Atmosphere", { hint: "Comma-separated.", wide: true })}

      <h3 className="mt-2 text-[11px] font-semibold uppercase tracking-wider text-gold-400/80 md:col-span-2">Production</h3>
      {text("durationTargetSec", "Duration target (seconds)", { type: "number" })}
      <div className="grid grid-cols-2 gap-4">
        {text("minScenes", "Min scenes", { type: "number" })}
        {text("maxScenes", "Max scenes", { type: "number" })}
      </div>

      <h3 className="mt-2 text-[11px] font-semibold uppercase tracking-wider text-gold-400/80 md:col-span-2">Constraints</h3>
      {text("prohibitedClaims", "Prohibited claims", { rows: 3, wide: true, hint: "One per line." })}

      <div className="flex justify-end gap-2 md:col-span-2">
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
        )}
        <Button type="submit" variant="primary" busy={submitting}>
          Create v{base.version + 1}
        </Button>
      </div>
    </form>
  );
}
