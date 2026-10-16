import { describe, expect, it } from "vitest";
import { shotProgress } from "./shotProgress";
import type { Shot } from "@cineforge/schemas";

function shot(partial: Partial<Shot> & Pick<Shot, "id">): Shot {
  return {
    order: 1,
    duration_sec: 5,
    kind: "a_roll",
    description: "test",
    visual: { shot_type: "medium", camera_motion: "static" },
    audio: {},
    provider_plan: { strategy: "generative", capability: "image_to_video", parameters: {} },
    status: "planned",
    ...partial,
  } as Shot;
}

describe("shotProgress", () => {
  it("marks generative stages complete / active / pending", () => {
    const progress = shotProgress(
      shot({
        id: "s1",
        audio: { dialogue_text: "Hello" },
        provider_plan: {
          strategy: "generative",
          capability: "image_to_video",
          parameters: {
            stages: {
              still: { done: true },
              voice: { attempt: 1 },
              clip: {},
            },
          },
        },
      }),
    );
    expect(progress.stages.map((s) => s.state)).toEqual(["complete", "active", "pending"]);
    expect(progress.overall).toBe("active");
    expect(progress.label).toBe("In progress");
  });

  it("skips voice when there is no dialogue line", () => {
    const progress = shotProgress(
      shot({
        id: "s2",
        audio: {},
        provider_plan: {
          strategy: "generative",
          capability: "image_to_video",
          parameters: { stages: { still: { done: true }, clip: { done: true } } },
        },
      }),
    );
    expect(progress.stages.find((s) => s.id === "voice")?.state).toBe("skipped");
    expect(progress.overall).toBe("complete");
  });

  it("uses work status when there are no generative stages", () => {
    expect(shotProgress(shot({ id: "s3", status: "complete" })).overall).toBe("complete");
    expect(shotProgress(shot({ id: "s4", status: "in_progress" })).overall).toBe("active");
    expect(shotProgress(shot({ id: "s5", status: "planned" })).overall).toBe("pending");
  });

  it("marks a failed clip attempt until the stage is done", () => {
    const progress = shotProgress(
      shot({
        id: "s6",
        attempts: [
          { attempt: 1, provider: "higgsfield", model: "kling3_0", status: "failed", error: "clip: boom" },
        ],
        provider_plan: {
          strategy: "generative",
          capability: "image_to_video",
          parameters: { stages: { still: { done: true }, clip: { attempt: 1 } } },
        },
      }),
    );
    expect(progress.stages.find((s) => s.id === "clip")?.state).toBe("failed");
    expect(progress.overall).toBe("failed");
  });
});
