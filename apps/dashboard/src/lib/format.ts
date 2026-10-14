const EMPTY = "-";

const usdFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** USD with 2 to 4 decimals: 10 -> "$10.00", 0.0425 -> "$0.0425", 1.23456 -> "$1.2346". */
export function formatUsd(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  return usdFormatter.format(n);
}

/** Seconds -> "0.4s", "45s", "1m 16s", "1h 2m". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return EMPTY;
  if (seconds < 10 && !Number.isInteger(seconds)) return `${seconds.toFixed(1)}s`;
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m`;
  return s ? `${m}m ${s}s` : `${m}m`;
}

/** Elapsed time between two ISO timestamps, or null if either is missing/invalid. */
export function secondsBetween(start?: string | null, end?: string | null): number | null {
  if (!start || !end) return null;
  const a = Date.parse(start);
  const b = Date.parse(end);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.max(0, (b - a) / 1000);
}

const dateTimeFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const timeFormatter = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? EMPTY : dateTimeFormatter.format(t);
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? EMPTY : timeFormatter.format(t);
}

/** "just now", "5m ago", "3h ago", "2d ago"; falls back to a date after a week. */
export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return EMPTY;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return EMPTY;
  const diff = Math.max(0, Math.round((now - t) / 1000));
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  if (diff < 7 * 86400) return `${Math.round(diff / 86400)}d ago`;
  return formatDateTime(iso);
}

export function formatPct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY;
  return `${value.toFixed(digits)}%`;
}

/** "AWAITING_APPROVAL" / "a7_visual_production" / "slow_push" -> "Awaiting approval" / ... */
export function humanize(value: string | null | undefined): string {
  if (!value) return EMPTY;
  const words = value.replace(/[_-]+/g, " ").trim().toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return EMPTY;
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

/** Share of `part` in `whole` clamped to 0..100 (for CSS bars). */
export function ratioPct(part: number | null | undefined, whole: number | null | undefined): number {
  const p = toNumber(part) ?? 0;
  const w = toNumber(whole) ?? 0;
  if (w <= 0) return 0;
  return Math.min(100, Math.max(0, (p / w) * 100));
}
