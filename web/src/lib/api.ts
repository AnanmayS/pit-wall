import type {
  AskRequest,
  AskResponse,
  CompareParams,
  CompareResult,
  DriverSummary,
  LapSummary,
  OddsHistory,
  OddsKind,
  OddsLatest,
  RecentScenario,
  ScenarioResult,
  ScenarioSpec,
  SessionSummary,
  SessionType,
} from "./types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080"
).replace(/\/+$/, "");

const DEFAULT_TIMEOUT_MS = 30_000;

/** Error raised for any failed API call; carries the URL that was tried. */
export class ApiError extends Error {
  readonly url: string;
  /** HTTP status, or null when the request never got a response. */
  readonly status: number | null;
  /** The server's `detail` message, when it sent one. */
  readonly detail: string | null;

  constructor(message: string, url: string, status: number | null, detail: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.url = url;
    this.status = status;
    this.detail = detail;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

/** FastAPI validation errors: [{loc: [...], msg}] -> "changes.0.lap: field required; ..." */
function formatValidationErrors(items: unknown[]): string {
  return items
    .map((item) => {
      if (item && typeof item === "object" && "msg" in item) {
        const { loc, msg } = item as { loc?: unknown; msg?: unknown };
        const where = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(".") : "";
        return where ? `${where}: ${String(msg)}` : String(msg);
      }
      return JSON.stringify(item);
    })
    .join("; ");
}

async function readErrorDetail(res: Response): Promise<string | null> {
  try {
    const text = await res.text();
    if (!text) return null;
    try {
      const body = JSON.parse(text) as { detail?: unknown; message?: unknown };
      const detail = body.detail ?? body.message;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) return formatValidationErrors(detail);
      if (detail != null) return JSON.stringify(detail);
    } catch {
      // Not JSON; fall through to raw text.
    }
    return text.slice(0, 300);
  } catch {
    return null;
  }
}

export interface FetchInit {
  signal?: AbortSignal;
  timeoutMs?: number;
  method?: "GET" | "POST";
  /** Serialized as JSON when present. */
  body?: unknown;
}

/** Fetch a JSON document from the API. `path` is relative to the API base URL. */
export async function fetchJson<T>(path: string, init?: FetchInit): Promise<T> {
  const url = apiUrl(path);
  const timeout = AbortSignal.timeout(init?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout;
  const hasBody = init?.body !== undefined;

  let res: Response;
  try {
    res = await fetch(url, {
      signal,
      method: init?.method ?? (hasBody ? "POST" : "GET"),
      headers: hasBody
        ? { Accept: "application/json", "Content-Type": "application/json" }
        : { Accept: "application/json" },
      body: hasBody ? JSON.stringify(init?.body) : undefined,
    });
  } catch (err) {
    if (init?.signal?.aborted) throw err;
    const reason =
      timeout.aborted
        ? "The request timed out."
        : "Could not reach the API. Is the server running?";
    throw new ApiError(reason, url, null);
  }

  if (!res.ok) {
    const detail = await readErrorDetail(res);
    const message = detail
      ? `${res.status} ${res.statusText}: ${detail}`
      : `${res.status} ${res.statusText}`;
    throw new ApiError(message, url, res.status, detail);
  }

  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("The API returned a response that is not valid JSON.", url, res.status);
  }
}

// ---------------------------------------------------------------------------
// Path builders (used directly by the data hooks, which key requests by path)
// ---------------------------------------------------------------------------

function sessionBase(season: number, round: number, sessionType: SessionType): string {
  return `/api/sessions/${season}/${round}/${encodeURIComponent(sessionType)}`;
}

export const paths = {
  sessions: (season: number) => `/api/sessions?${new URLSearchParams({ season: String(season) })}`,
  drivers: (season: number, round: number, sessionType: SessionType) =>
    `${sessionBase(season, round, sessionType)}/drivers`,
  laps: (season: number, round: number, sessionType: SessionType, driver: string) =>
    `${sessionBase(season, round, sessionType)}/laps?${new URLSearchParams({ driver })}`,
  compare: (p: CompareParams) =>
    `/api/compare?${new URLSearchParams({
      season: String(p.season),
      round: String(p.round),
      session_type: p.session_type,
      driver_a: p.driver_a,
      driver_b: p.driver_b,
      lap_a: String(p.lap_a),
      lap_b: String(p.lap_b),
    })}`,
  oddsLatest: (season: number) => `/api/odds/latest?${new URLSearchParams({ season: String(season) })}`,
  oddsHistory: (season: number, kind: OddsKind, top = 6) =>
    `/api/odds/history?${new URLSearchParams({ season: String(season), kind, top: String(top) })}`,
  whatif: (id: string) => `/api/whatif/${encodeURIComponent(id)}`,
  whatifRecent: (season: number, round: number) =>
    `/api/whatif/recent?${new URLSearchParams({ season: String(season), round: String(round) })}`,
};

// ---------------------------------------------------------------------------
// Typed endpoint wrappers
// ---------------------------------------------------------------------------

export function getSessions(season: number, signal?: AbortSignal) {
  return fetchJson<SessionSummary[]>(paths.sessions(season), { signal });
}

export function getDrivers(
  season: number,
  round: number,
  sessionType: SessionType,
  signal?: AbortSignal,
) {
  return fetchJson<DriverSummary[]>(paths.drivers(season, round, sessionType), { signal });
}

export function getLaps(
  season: number,
  round: number,
  sessionType: SessionType,
  driver: string,
  signal?: AbortSignal,
) {
  return fetchJson<LapSummary[]>(paths.laps(season, round, sessionType, driver), { signal });
}

export function getCompare(params: CompareParams, signal?: AbortSignal) {
  return fetchJson<CompareResult>(paths.compare(params), { signal, timeoutMs: 120_000 });
}

/** Monte Carlo runs can take a while on a cold cache. */
export const WHATIF_TIMEOUT_MS = 180_000;
/** Agentic answers make several tool calls. */
export const ASK_TIMEOUT_MS = 180_000;

export function runScenario(spec: ScenarioSpec, signal?: AbortSignal) {
  return fetchJson<ScenarioResult>("/api/whatif", {
    signal,
    method: "POST",
    body: spec,
    timeoutMs: WHATIF_TIMEOUT_MS,
  });
}

export function getScenario(id: string, signal?: AbortSignal) {
  return fetchJson<ScenarioResult>(paths.whatif(id), { signal, timeoutMs: WHATIF_TIMEOUT_MS });
}

export function getRecentScenarios(season: number, round: number, signal?: AbortSignal) {
  return fetchJson<RecentScenario[]>(paths.whatifRecent(season, round), { signal });
}

export function ask(request: AskRequest, signal?: AbortSignal) {
  return fetchJson<AskResponse>("/api/ask", {
    signal,
    method: "POST",
    body: request,
    timeoutMs: ASK_TIMEOUT_MS,
  });
}

/** Normalize anything thrown by a fetch into an ApiError. */
export function toApiError(err: unknown, path: string): ApiError {
  return err instanceof ApiError
    ? err
    : new ApiError(err instanceof Error ? err.message : String(err), apiUrl(path), null);
}

export function getOddsLatest(season: number, signal?: AbortSignal) {
  return fetchJson<OddsLatest>(paths.oddsLatest(season), { signal });
}

export function getOddsHistory(season: number, kind: OddsKind, top = 6, signal?: AbortSignal) {
  return fetchJson<OddsHistory>(paths.oddsHistory(season, kind, top), { signal });
}
