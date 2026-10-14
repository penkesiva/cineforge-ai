import { describe, expect, it } from "vitest";
import { generatedAsset } from "@/test/fixtures";
import { aiDisclosureBadge, assetIndex, generatedBy } from "./generation";

describe("aiDisclosureBadge", () => {
  it("is null unless the shot carries synthetic media", () => {
    expect(aiDisclosureBadge({})).toBeNull();
    expect(aiDisclosureBadge({ disclosure: { synthetic_media: false, reconstruction: true, label_text: "Reconstruction" } })).toBeNull();
  });

  it("defaults to the AI-generated label", () => {
    expect(aiDisclosureBadge({ disclosure: { synthetic_media: true, label_text: null } })).toEqual({
      text: "AI-generated",
      title: "AI-generated (synthetic media)",
    });
    expect(aiDisclosureBadge({ disclosure: { synthetic_media: true, label_text: "   " } })?.text).toBe("AI-generated");
  });

  it("prefers the manifest label text", () => {
    expect(aiDisclosureBadge({ disclosure: { synthetic_media: true, label_text: " AI reconstruction " } })).toEqual({
      text: "AI reconstruction",
      title: "AI-generated: AI reconstruction",
    });
  });
});

describe("generatedBy", () => {
  const assets = assetIndex([
    generatedAsset("ast_higgs", { provider: "higgsfield", model: "kling2_6", job_id: "hf_1", via: "external" }),
    generatedAsset("ast_mock", { provider: "mock-video", model: "mock-video-draft" }),
    generatedAsset("ast_mock_upper", { provider: "MockVideo", model: "x" }),
    generatedAsset("ast_no_model", { provider: "runway" }),
    generatedAsset("ast_no_gen", null),
  ]);

  it("shows provider / model for a real generated asset", () => {
    expect(generatedBy({ assets: [{ asset_id: "ast_higgs", role: "generated" }] }, assets)).toBe("higgsfield / kling2_6");
  });

  it("skips mock providers, other roles, missing records and missing provenance", () => {
    expect(generatedBy({ assets: [{ asset_id: "ast_mock", role: "generated" }] }, assets)).toBeNull();
    expect(generatedBy({ assets: [{ asset_id: "ast_mock_upper", role: "generated" }] }, assets)).toBeNull();
    expect(generatedBy({ assets: [{ asset_id: "ast_higgs", role: "source" }] }, assets)).toBeNull();
    expect(generatedBy({ assets: [{ asset_id: "missing", role: "generated" }] }, assets)).toBeNull();
    expect(generatedBy({ assets: [{ asset_id: "ast_no_gen", role: "generated" }] }, assets)).toBeNull();
    expect(generatedBy({}, assets)).toBeNull();
  });

  it("uses the first qualifying generated asset and tolerates a missing model", () => {
    expect(
      generatedBy(
        {
          assets: [
            { asset_id: "ast_mock", role: "generated" },
            { asset_id: "ast_no_model", role: "generated" },
            { asset_id: "ast_higgs", role: "generated" },
          ],
        },
        assets,
      ),
    ).toBe("runway");
  });

  it("indexes only records with an id", () => {
    const { id: _omit, ...noId } = generatedAsset("x", null);
    void _omit;
    expect(assetIndex([noId, generatedAsset("y", null)]).size).toBe(1);
    expect(assetIndex(undefined).size).toBe(0);
  });
});
