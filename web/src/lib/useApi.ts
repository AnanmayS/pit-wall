"use client";

import { useEffect, useState } from "react";
import { ApiError, apiUrl, fetchJson } from "./api";

interface Settled<T> {
  key: string;
  data: T | null;
  error: ApiError | null;
}

export interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
}

/**
 * Fetch `path` from the API whenever it changes. Pass `null` to skip.
 * Bump `nonce` to force a refetch of the same path (e.g. a retry button).
 * Results are keyed by request, so stale responses are never shown for a newer request.
 */
export function useApi<T>(
  path: string | null,
  nonce = 0,
  timeoutMs?: number,
): ApiState<T> {
  const key = path == null ? null : `${nonce}:${path}`;
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    if (path == null || key == null) return;
    const controller = new AbortController();
    fetchJson<T>(path, { signal: controller.signal, timeoutMs }).then(
      (data) => setSettled({ key, data, error: null }),
      (err: unknown) => {
        if (controller.signal.aborted) return;
        const error =
          err instanceof ApiError
            ? err
            : new ApiError(err instanceof Error ? err.message : String(err), apiUrl(path), null);
        setSettled({ key, data: null, error });
      },
    );
    return () => controller.abort();
  }, [path, key, timeoutMs]);

  const current = settled !== null && settled.key === key ? settled : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: key !== null && current === null,
  };
}
