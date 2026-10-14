// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatCredits,
  formatDateTime,
  formatDuration,
  formatPct,
  formatRelative,
  formatUsd,
  humanize,
  ratioPct,
  secondsBetween,
} from "./format";

describe("formatUsd", () => {
  it("uses 2 to 4 decimals", () => {
    expect(formatUsd(10)).toBe("$10.00");
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(0.0425)).toBe("$0.0425");
    expect(formatUsd(1.23456)).toBe("$1.2346");
    expect(formatUsd(1234.5)).toBe("$1,234.50");
  });

  it("accepts numeric strings and handles missing values", () => {
    expect(formatUsd("3.5")).toBe("$3.50");
    expect(formatUsd(null)).toBe("-");
    expect(formatUsd(undefined)).toBe("-");
    expect(formatUsd("abc")).toBe("-");
  });
});

describe("formatCredits", () => {
  it("formats ledger decimal strings without trailing zeros", () => {
    expect(formatCredits("15.000000")).toBe("15");
    expect(formatCredits("0.125")).toBe("0.125");
    expect(formatCredits("2.123456")).toBe("2.1235");
    expect(formatCredits("1234.5")).toBe("1,234.5");
    expect(formatCredits(" 7 ")).toBe("7");
    expect(formatCredits(0)).toBe("0");
    expect(formatCredits("0")).toBe("0");
  });

  it("shows a dash when credits are missing or invalid", () => {
    expect(formatCredits(null)).toBe("-");
    expect(formatCredits(undefined)).toBe("-");
    expect(formatCredits("")).toBe("-");
    expect(formatCredits("  ")).toBe("-");
    expect(formatCredits("n/a")).toBe("-");
  });
});

describe("formatDuration", () => {
  it("formats seconds, minutes and hours", () => {
    expect(formatDuration(0.42)).toBe("0.4s");
    expect(formatDuration(7)).toBe("7s");
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(75.5)).toBe("1m 16s");
    expect(formatDuration(120)).toBe("2m");
    expect(formatDuration(3720)).toBe("1h 2m");
  });

  it("returns a dash for invalid input", () => {
    expect(formatDuration(undefined)).toBe("-");
    expect(formatDuration(-1)).toBe("-");
    expect(formatDuration(Number.NaN)).toBe("-");
  });
});

describe("dates", () => {
  it("formats ISO timestamps (UTC in tests)", () => {
    expect(formatDateTime("2026-10-13T12:00:00Z")).toBe("Oct 13, 2026, 12:00 PM");
    expect(formatDateTime("nope")).toBe("-");
    expect(formatDateTime(null)).toBe("-");
  });

  it("formats relative times", () => {
    const now = Date.parse("2026-10-13T12:00:00Z");
    expect(formatRelative("2026-10-13T11:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-10-13T11:55:00Z", now)).toBe("5m ago");
    expect(formatRelative("2026-10-13T09:00:00Z", now)).toBe("3h ago");
    expect(formatRelative("2026-10-11T12:00:00Z", now)).toBe("2d ago");
    expect(formatRelative("2026-09-01T12:00:00Z", now)).toBe("Sep 1, 2026, 12:00 PM");
  });

  it("computes elapsed seconds", () => {
    expect(secondsBetween("2026-10-13T12:00:00Z", "2026-10-13T12:00:01.500Z")).toBe(1.5);
    expect(secondsBetween("2026-10-13T12:00:00Z", null)).toBeNull();
  });
});

describe("misc helpers", () => {
  it("humanizes enum values", () => {
    expect(humanize("AWAITING_APPROVAL")).toBe("Awaiting approval");
    expect(humanize("slow_push")).toBe("Slow push");
    expect(humanize("time-traveler")).toBe("Time traveler");
    expect(humanize(undefined)).toBe("-");
  });

  it("formats percentages, bytes and ratios", () => {
    expect(formatPct(56)).toBe("56%");
    expect(formatPct(92.345, 1)).toBe("92.3%");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(ratioPct(2.5, 10)).toBe(25);
    expect(ratioPct(20, 10)).toBe(100);
    expect(ratioPct(1, 0)).toBe(0);
  });
});
