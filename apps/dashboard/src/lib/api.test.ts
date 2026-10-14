// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient, errorMessage } from "./api";
import { apiInternalUrl } from "./apiTarget";

describe("apiInternalUrl", () => {
  it("defaults to localhost and strips trailing slashes", () => {
    expect(apiInternalUrl({})).toBe("http://localhost:8000");
    expect(apiInternalUrl({ API_INTERNAL_URL: "  " })).toBe("http://localhost:8000");
    expect(apiInternalUrl({ API_INTERNAL_URL: "http://api:8000/" })).toBe("http://api:8000");
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function setup(response: Response | (() => Promise<Response>) = jsonResponse([])) {
  const fetchImpl = vi.fn<typeof fetch>(async () => (typeof response === "function" ? response() : response.clone()));
  const client = createApiClient({ fetchImpl });
  const call = (i = 0) => {
    const [url, init] = fetchImpl.mock.calls[i] ?? [];
    return { url: String(url), init: init ?? {} };
  };
  return { client, fetchImpl, call };
}

describe("api client requests", () => {
  it.each([
    ["listAgents", "/api/v1/agents"],
    ["listThemes", "/api/v1/themes"],
    ["listModes", "/api/v1/modes"],
    ["listPricing", "/api/v1/pricing"],
    ["getCostOverview", "/api/v1/costs/overview"],
    ["listProductions", "/api/v1/productions"],
  ] as const)("%s GETs %s with no-store caching", async (method, url) => {
    const { client, call } = setup();
    await client[method]();
    expect(call().url).toBe(url);
    expect(call().init.method).toBe("GET");
    expect(call().init.cache).toBe("no-store");
    expect(call().init.body).toBeUndefined();
  });

  it("encodes production ids in paths", async () => {
    const { client, call } = setup(jsonResponse({}));
    await client.getProduction("prod/1 2");
    expect(call().url).toBe("/api/v1/productions/prod%2F1%202");
    await client.getProductionCosts("p1");
    expect(call(1).url).toBe("/api/v1/productions/p1/costs");
    await client.getProductionLedger("p1");
    expect(call(2).url).toBe("/api/v1/productions/p1/ledger");
  });

  it("POSTs a JSON body when creating a production", async () => {
    const { client, call } = setup(jsonResponse({ summary: { id: "p1" } }, 201));
    const created = await client.createProduction({ theme_id: "time-traveler", topic: "Eiffel", mode: "balanced" });
    expect(created).toEqual({ summary: { id: "p1" } });
    expect(call().url).toBe("/api/v1/productions");
    expect(call().init.method).toBe("POST");
    expect(JSON.parse(String(call().init.body))).toEqual({ theme_id: "time-traveler", topic: "Eiffel", mode: "balanced" });
    expect((call().init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("uses the right paths and bodies for workflow actions", async () => {
    const { client, call } = setup(jsonResponse({ production_id: "p1", state: "GENERATING", message: "ok" }, 202));
    await client.runProduction("p1");
    await client.approveProduction("p1", { raise_budget_to_usd: 25 });
    await client.cancelProduction("p1");
    await client.deliverProduction("p1");
    expect(call(0)).toMatchObject({ url: "/api/v1/productions/p1/run", init: { method: "POST" } });
    expect(call(0).init.body).toBeUndefined();
    expect(call(1)).toMatchObject({ url: "/api/v1/productions/p1/approve", init: { method: "POST" } });
    expect(JSON.parse(String(call(1).init.body))).toEqual({ raise_budget_to_usd: 25 });
    expect(call(2).url).toBe("/api/v1/productions/p1/cancel");
    expect(call(3).url).toBe("/api/v1/productions/p1/deliver");
  });

  it("sends the tenant header and honours a custom base path", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => jsonResponse([]));
    const client = createApiClient({ fetchImpl, basePath: "/proxy/api/v1/", tenantId: "tenant_x" });
    await client.listAgents();
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("/proxy/api/v1/agents");
    expect((init?.headers as Record<string, string>)["X-Tenant-Id"]).toBe("tenant_x");
    expect(client.assetContentUrl("asset 1")).toBe("/proxy/api/v1/assets/asset%201/content");
  });

  it("uses the provider routes with the right verbs and bodies", async () => {
    const { client, call } = setup(jsonResponse({}));
    await client.getProviders();
    await client.updateProvider("anthropic", { enabled: true });
    await client.setProviderKey("anthropic", "sk-secret");
    await client.deleteProviderKey("anthropic");
    await client.testProvider("open library");
    expect(call(0)).toMatchObject({ url: "/api/v1/providers", init: { method: "GET" } });
    expect(call(1)).toMatchObject({ url: "/api/v1/providers/anthropic", init: { method: "PATCH" } });
    expect(JSON.parse(String(call(1).init.body))).toEqual({ enabled: true });
    expect(call(2)).toMatchObject({ url: "/api/v1/providers/anthropic/key", init: { method: "PUT" } });
    expect(JSON.parse(String(call(2).init.body))).toEqual({ api_key: "sk-secret" });
    expect(call(3)).toMatchObject({ url: "/api/v1/providers/anthropic/key", init: { method: "DELETE" } });
    expect(call(3).init.body).toBeUndefined();
    expect(call(4)).toMatchObject({ url: "/api/v1/providers/open%20library/test", init: { method: "POST" } });
  });

  it("uses the theme version routes", async () => {
    const { client, call } = setup(jsonResponse({}));
    await client.getTheme("time-traveler");
    await client.getTheme("time-traveler", 2);
    await client.listThemeVersions("time-traveler");
    await client.createThemeVersion("time-traveler", { base_version: 2, profile: {} as never });
    expect(call(0).url).toBe("/api/v1/themes/time-traveler");
    expect(call(1).url).toBe("/api/v1/themes/time-traveler?version=2");
    expect(call(2).url).toBe("/api/v1/themes/time-traveler/versions");
    expect(call(3)).toMatchObject({ url: "/api/v1/themes/time-traveler/versions", init: { method: "POST" } });
    expect(JSON.parse(String(call(3).init.body))).toEqual({ base_version: 2, profile: {} });
  });

  it("posts claim decisions and script rewrites", async () => {
    const { client, call } = setup(jsonResponse({}));
    await client.reviewClaims("p1", { reviewed_by: "operator", decisions: [{ claim_id: "c1", decision: "rejected" }] });
    await client.rewriteScript("p1");
    expect(call(0)).toMatchObject({ url: "/api/v1/productions/p1/claims", init: { method: "POST" } });
    expect(JSON.parse(String(call(0).init.body))).toEqual({
      reviewed_by: "operator",
      decisions: [{ claim_id: "c1", decision: "rejected" }],
    });
    expect(call(1)).toMatchObject({ url: "/api/v1/productions/p1/rewrite-script", init: { method: "POST" } });
  });

  it("builds the master render content URL", () => {
    expect(createApiClient().assetContentUrl("ast_1")).toBe("/api/v1/assets/ast_1/content");
  });
});

describe("api client errors", () => {
  it("parses ErrorResponse bodies into ApiError", async () => {
    const { client } = setup(
      jsonResponse({ error: "invalid_state_transition", detail: { message: "Cannot run from READY" } }, 409),
    );
    const error = await client.runProduction("p1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(409);
    expect(apiError.body).toEqual({ error: "invalid_state_transition", detail: { message: "Cannot run from READY" } });
    expect(apiError.message).toBe("Cannot run from READY");
    expect(apiError.unavailable).toBe(false);
  });

  it("falls back to the error code when detail has no message", async () => {
    const { client } = setup(jsonResponse({ error: "production_not_found", detail: { production_id: "x" } }, 404));
    const error = (await client.getProduction("x").catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(404);
    expect(error.message).toBe("production_not_found");
  });

  it("normalises FastAPI 422 validation lists", async () => {
    const { client } = setup(
      jsonResponse({ detail: [{ loc: ["body", "topic"], msg: "String should have at least 3 characters" }] }, 422),
    );
    const error = (await client.createProduction({ topic: "x" }).catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(422);
    expect(error.message).toBe("topic: String should have at least 3 characters");
  });

  it("marks network failures as unavailable", async () => {
    const { client } = setup(() => Promise.reject(new TypeError("fetch failed")));
    const error = (await client.listProductions().catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
    expect(error.unavailable).toBe(true);
    expect(errorMessage(error)).toMatch(/API is unavailable/);
  });

  it("marks non-JSON proxy errors as unavailable", async () => {
    const { client } = setup(new Response("Internal Server Error", { status: 500 }));
    const error = (await client.listProductions().catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(500);
    expect(error.unavailable).toBe(true);
  });

  it("returns a degraded HealthResponse even with a 503 status", async () => {
    const body = { status: "degraded", version: "0.1.0", environment: "test", paid_providers_enabled: false, checks: [] };
    const { client, call } = setup(jsonResponse(body, 503));
    await expect(client.health()).resolves.toEqual(body);
    expect(call().url).toBe("/health");
  });

  it("throws for health when the API is unreachable", async () => {
    const { client } = setup(() => Promise.reject(new TypeError("fetch failed")));
    await expect(client.health()).rejects.toMatchObject({ status: 0 });
  });
});
