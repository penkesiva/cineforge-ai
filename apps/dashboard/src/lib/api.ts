import type {
  ActionResponse,
  AgentDefinition,
  ApproveProductionRequest,
  CostOverview,
  CostSummary,
  CreateProductionRequest,
  ErrorResponse,
  HealthResponse,
  LedgerEvent,
  PriceCatalogEntry,
  ProductionDetail,
  ProductionModePolicy,
  ProductionSummary,
  ThemeSummary,
} from "@cineforge/schemas";

export const DEFAULT_API_BASE_PATH = "/api/v1";

/** Error raised for any failed API call. `status` is 0 when the API could not be reached. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: ErrorResponse | null;

  constructor(status: number, message: string, body: ErrorResponse | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  /** True when the API is down or the proxy could not reach it (as opposed to a business error). */
  get unavailable(): boolean {
    return this.status === 0 || (this.status >= 500 && this.body === null);
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** Human-readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (isApiError(error)) {
    if (error.unavailable) return "The CineForge API is unavailable. Check that the API service is running.";
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { error?: unknown }).error === "string"
  );
}

/** FastAPI's default validation errors use `{detail: [...]}`; normalise them to a message. */
function messageFromDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item !== "object" || item === null) return null;
        const { msg, loc } = item as { msg?: unknown; loc?: unknown };
        if (typeof msg !== "string") return null;
        const field = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(".") : "";
        return field ? `${field}: ${msg}` : msg;
      })
      .filter((part): part is string => part !== null);
    return parts.length ? parts.join("; ") : null;
  }
  return null;
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function errorFromPayload(status: number, statusText: string, payload: unknown): ApiError {
  if (isErrorResponse(payload)) {
    const detailMessage =
      payload.detail && typeof payload.detail.message === "string" ? payload.detail.message : null;
    return new ApiError(status, detailMessage ?? payload.error, payload);
  }
  const detail =
    typeof payload === "object" && payload !== null ? (payload as { detail?: unknown }).detail : undefined;
  const fromDetail = messageFromDetail(detail);
  if (fromDetail) {
    return new ApiError(status, fromDetail, { error: fromDetail, detail: { raw: detail } });
  }
  return new ApiError(status, statusText || `Request failed with status ${status}`);
}

async function toApiError(response: Response): Promise<ApiError> {
  return errorFromPayload(response.status, response.statusText, await readJson(response));
}

export interface ApiClientOptions {
  /** Prefix for `/api/v1` routes. Same-origin by default (proxied by Next.js rewrites). */
  basePath?: string;
  /** Origin for `/health` routes. Empty string = same origin. */
  healthBase?: string;
  tenantId?: string;
  fetchImpl?: typeof fetch;
}

type Method = "GET" | "POST";

export function createApiClient(options: ApiClientOptions = {}) {
  const basePath = (options.basePath ?? DEFAULT_API_BASE_PATH).replace(/\/+$/, "");
  const healthBase = (options.healthBase ?? "").replace(/\/+$/, "");
  const doFetch: typeof fetch = (...args) => (options.fetchImpl ?? globalThis.fetch)(...args);

  async function send(url: string, method: Method, body?: unknown): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (options.tenantId) headers["X-Tenant-Id"] = options.tenantId;
    try {
      return await doFetch(url, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
      });
    } catch (cause) {
      const error = new ApiError(0, "Network error: the API could not be reached.");
      (error as Error & { cause?: unknown }).cause = cause;
      throw error;
    }
  }

  async function request<T>(path: string, method: Method = "GET", body?: unknown): Promise<T> {
    const response = await send(`${basePath}${path}`, method, body);
    if (!response.ok) throw await toApiError(response);
    return (await readJson(response)) as T;
  }

  const enc = encodeURIComponent;

  return {
    /** `/health` may answer 503 with a HealthResponse body when dependencies are down. */
    async health(): Promise<HealthResponse> {
      const response = await send(`${healthBase}/health`, "GET");
      const payload = await readJson(response);
      const status = (payload as { status?: unknown } | null)?.status;
      if (status === "ok" || status === "degraded" || status === "down") {
        return payload as HealthResponse;
      }
      if (!response.ok) throw errorFromPayload(response.status, response.statusText, payload);
      throw new ApiError(response.status, "Unexpected health response");
    },
    listAgents: () => request<AgentDefinition[]>("/agents"),
    listThemes: () => request<ThemeSummary[]>("/themes"),
    listModes: () => request<ProductionModePolicy[]>("/modes"),
    listPricing: () => request<PriceCatalogEntry[]>("/pricing"),
    getCostOverview: () => request<CostOverview>("/costs/overview"),
    listProductions: () => request<ProductionSummary[]>("/productions"),
    createProduction: (payload: CreateProductionRequest) =>
      request<ProductionDetail>("/productions", "POST", payload),
    getProduction: (id: string) => request<ProductionDetail>(`/productions/${enc(id)}`),
    runProduction: (id: string) => request<ActionResponse>(`/productions/${enc(id)}/run`, "POST"),
    approveProduction: (id: string, payload: ApproveProductionRequest = {}) =>
      request<ActionResponse>(`/productions/${enc(id)}/approve`, "POST", payload),
    cancelProduction: (id: string) => request<ActionResponse>(`/productions/${enc(id)}/cancel`, "POST"),
    deliverProduction: (id: string) => request<ActionResponse>(`/productions/${enc(id)}/deliver`, "POST"),
    getProductionCosts: (id: string) => request<CostSummary>(`/productions/${enc(id)}/costs`),
    getProductionLedger: (id: string) => request<LedgerEvent[]>(`/productions/${enc(id)}/ledger`),
    assetContentUrl: (assetId: string) => `${basePath}/assets/${enc(assetId)}/content`,
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

export const api: ApiClient = createApiClient({
  basePath: process.env.NEXT_PUBLIC_API_BASE_PATH || DEFAULT_API_BASE_PATH,
});

