"use client";

import type { ProviderCatalogEntry } from "@cineforge/schemas";
import { useId, useState, type FormEvent } from "react";
import { keySourceLabel } from "@/lib/providers";
import { IconKey } from "../icons";
import { Button, cx, inputClass } from "../ui";

export interface ProviderKeyFieldProps {
  provider: ProviderCatalogEntry;
  busy?: "save" | "remove" | null;
  disabled?: boolean;
  onSave: (apiKey: string) => void;
  onRemove: () => void;
}

/**
 * Write-only key input. The typed key is handed to `onSave` and cleared from
 * local state immediately; the API never returns it, only `key_hint`.
 */
export function ProviderKeyField({ provider, busy = null, disabled = false, onSave, onRemove }: ProviderKeyFieldProps) {
  const uid = useId();
  const [value, setValue] = useState("");
  const source = provider.key_source ?? "none";
  const fromEnv = source === "environment";

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const key = value.trim();
    setValue("");
    if (key) onSave(key);
  }

  return (
    <form onSubmit={submit} className="mt-3 space-y-1.5" aria-label={`API key for ${provider.display_name}`}>
      <p
        id={`${uid}-status`}
        data-testid="key-status"
        className={cx(
          "inline-flex items-center gap-1.5 text-xs",
          source === "none" ? "text-amber-300/90" : "text-zinc-400",
        )}
      >
        <IconKey size={13} /> {keySourceLabel(provider)}
      </p>
      {fromEnv ? (
        <p className="text-[11px] text-zinc-500">
          Environment keys win over stored keys and can only be changed in <code>.env</code>.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={`${uid}-key`} className="sr-only">
            {`API key for ${provider.display_name}`}
          </label>
          <input
            id={`${uid}-key`}
            type="password"
            autoComplete="new-password"
            spellCheck={false}
            value={value}
            disabled={disabled || busy !== null}
            placeholder={source === "stored" ? "Paste a new key to replace" : provider.key_env_var ?? "Paste API key"}
            aria-describedby={`${uid}-status`}
            onChange={(e) => setValue(e.target.value)}
            className={cx(inputClass, "max-w-xs flex-1 py-1.5 font-mono text-xs")}
          />
          <Button
            type="submit"
            variant="secondary"
            className="px-3 py-1.5 text-xs"
            disabled={disabled || !value.trim()}
            busy={busy === "save"}
          >
            Save key
          </Button>
          {source === "stored" && (
            <Button
              variant="ghost"
              className="px-3 py-1.5 text-xs text-rose-300 hover:text-rose-200"
              disabled={disabled}
              busy={busy === "remove"}
              onClick={onRemove}
            >
              Remove key
            </Button>
          )}
        </div>
      )}
    </form>
  );
}
