import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import { buildThemeProfile, themeToForm } from "@/lib/themeForm";
import { themeProfile, themeSummaries } from "@/test/themeFixtures";
import { STALE_VERSION_MESSAGE, ThemeDetail } from "./ThemeDetail";
import { ThemesPage } from "./ThemesPage";

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ThemesPage", () => {
  it("lists the latest version of each theme", async () => {
    vi.spyOn(api, "listThemes").mockResolvedValue(themeSummaries);
    render(<ThemesPage />);
    const rows = await screen.findAllByTestId("theme-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByRole("link", { name: "Time Traveler" })).toHaveAttribute("href", "/themes/time-traveler");
    expect(rows[0]).toHaveTextContent("Visit history");
    expect(rows[0]).toHaveTextContent("Documentary adventure");
    expect(rows[0]).toHaveTextContent("Balanced");
    expect(rows[0]).toHaveTextContent("v3");
    expect(rows[1]).toHaveTextContent("Economy");
  });
});

describe("buildThemeProfile", () => {
  it("round-trips the editable fields and keeps the rest of the base profile", () => {
    const base = themeProfile(2);
    const { errors, profile } = buildThemeProfile(base, themeToForm(base));
    expect(errors).toEqual({});
    expect(profile).toEqual({ ...base, version: 3 });
  });

  it("validates required fields, lists and scene bounds", () => {
    const base = themeProfile(1);
    const values = { ...themeToForm(base), name: " ", storyBeats: "\n \n", minScenes: "5", maxScenes: "3", durationTargetSec: "0" };
    const { errors, profile } = buildThemeProfile(base, values);
    expect(profile).toBeNull();
    expect(errors.name).toBe("Name is required.");
    expect(errors.storyBeats).toBeDefined();
    expect(errors.maxScenes).toMatch(/at least min scenes/);
    expect(errors.durationTargetSec).toBeDefined();
  });
});

describe("ThemeDetail", () => {
  const versions = [themeProfile(1, { tone: "Calm" }), themeProfile(2, { tone: "Wonder-filled" })];

  it("selects any version for a read-only view", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "listThemeVersions").mockResolvedValue(versions);
    render(<ThemeDetail id="time-traveler" />);
    const profile = await screen.findByTestId("theme-profile");
    expect(profile).toHaveAttribute("data-version", "2");
    expect(profile).toHaveTextContent("Wonder-filled");

    const select = screen.getByLabelText("Version");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["v2 (latest)", "v1"]);
    await user.selectOptions(select, "1");
    expect(screen.getByTestId("theme-profile")).toHaveAttribute("data-version", "1");
    expect(screen.getByTestId("theme-profile")).toHaveTextContent("Calm");
    expect(screen.getByText("Older version (latest is v2)")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("submits a full profile with base_version = latest", async () => {
    const user = userEvent.setup();
    const list = vi.spyOn(api, "listThemeVersions").mockResolvedValue(versions);
    const create = vi.spyOn(api, "createThemeVersion").mockResolvedValue(themeProfile(3, { name: "Time Traveler II" }));
    render(<ThemeDetail id="time-traveler" />);
    await user.click(await screen.findByRole("button", { name: /Create new version/ }));

    const form = screen.getByRole("form", { name: "New theme version" });
    const name = within(form).getByLabelText("Name");
    expect(name).toHaveValue("Time Traveler");
    expect(within(form).getByLabelText("Story beats")).toHaveValue("hook\narrival\nreveal");
    expect(within(form).getByLabelText("Camera grammar")).toHaveValue("slow_push, drone_reveal");

    await user.clear(name);
    await user.type(name, "Time Traveler II");
    const beats = within(form).getByLabelText("Story beats");
    await user.type(beats, "\nlegacy");
    const camera = within(form).getByLabelText("Camera grammar");
    await user.clear(camera);
    await user.type(camera, "tracking, close_up_reaction ,");
    await user.selectOptions(within(form).getByLabelText("Factual rigor"), "moderate");
    const maxScenes = within(form).getByLabelText("Max scenes");
    await user.clear(maxScenes);
    await user.type(maxScenes, "7");
    await user.type(within(form).getByLabelText("Prohibited claims"), "\ninvented quotes");
    await user.click(within(form).getByRole("button", { name: "Create v3" }));

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    const [themeId, payload] = create.mock.calls[0]!;
    expect(themeId).toBe("time-traveler");
    expect(payload.base_version).toBe(2);
    expect(payload.profile).toEqual({
      ...versions[1],
      version: 3,
      name: "Time Traveler II",
      narrative: { ...versions[1]!.narrative, story_beats: ["hook", "arrival", "reveal", "legacy"], factual_rigor: "moderate" },
      direction: { ...versions[1]!.direction, camera_grammar: ["tracking", "close_up_reaction"] },
      production: { ...versions[1]!.production, max_scenes: 7 },
      constraints: { ...versions[1]!.constraints, prohibited_claims: ["unsourced dates", "invented quotes"] },
    });
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Created v3");
  });

  it("blocks invalid submissions", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "listThemeVersions").mockResolvedValue(versions);
    const create = vi.spyOn(api, "createThemeVersion");
    render(<ThemeDetail id="time-traveler" />);
    await user.click(await screen.findByRole("button", { name: /Create new version/ }));
    const form = screen.getByRole("form", { name: "New theme version" });
    await user.clear(within(form).getByLabelText("Name"));
    await user.click(within(form).getByRole("button", { name: "Create v3" }));
    expect(create).not.toHaveBeenCalled();
    expect(within(form).getByText("Name is required.")).toBeInTheDocument();
    expect(within(form).getByLabelText("Name")).toHaveFocus();
  });

  it("explains a 409 stale base version and offers a reload", async () => {
    const user = userEvent.setup();
    const list = vi.spyOn(api, "listThemeVersions").mockResolvedValue(versions);
    vi.spyOn(api, "createThemeVersion").mockRejectedValue(
      new ApiError(409, "base_version 2 is stale", { error: "stale_theme_version" }),
    );
    render(<ThemeDetail id="time-traveler" />);
    await user.click(await screen.findByRole("button", { name: /Create new version/ }));
    await user.click(screen.getByRole("button", { name: "Create v3" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(STALE_VERSION_MESSAGE);
    await user.click(within(dialog).getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "New theme version" })).not.toBeInTheDocument();
  });
});
