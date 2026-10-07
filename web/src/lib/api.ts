import type {
  CompareParams,
  CompareResult,
  DriverSummary,
  LapSummary,
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

  constructor(message: string, url: string, status: number | null) {
    super(message);
    this.name = "ApiError";
    this.url = url;
    this.status = status;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

async function readErrorDetail(res: Response): Promise<string | null> {
  try {
    const text = await res.text();
    if (!text) return null;
    try {
      const body = JSON.parse(text) as { detail?: unknown; message?: unknown };
      const detail = body.detail ?? body.message;
      if (typeof detail === "string") return detail;
      if (detail != null) return JSON.stringify(detail);
    } catch {
      // Not JSON; fall through to raw text.
    }
    return text.slice(0, 300);
  } catch {
    return null;
  }
}

/** Fetch a JSON document from the API. `path` is relative to the API base URL. */
export async function fetchJson<T>(
  path: string,
  init?: { signal?: AbortSignal; timeoutMs?: number },
): Promise<T> {
  const url = apiUrl(path);
  const timeout = AbortSignal.timeout(init?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout;

  let res: Response;
  try {
    res = await fetch(url, { signal, headers: { Accept: "application/json" } });
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
    throw new ApiError(message, url, res.status);
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
