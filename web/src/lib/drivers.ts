"use client";

import { useEffect, useSyncExternalStore } from "react";
import { fetchJson } from "./api";
import type { DriverInfo } from "./types";

/** Driver code -> driver details for one season. */
export type DriverMap = ReadonlyMap<string, DriverInfo>;

const EMPTY: DriverMap = new Map();

/** Loaded seasons, shared by every component on the page. */
const cache = new Map<number, DriverMap>();
const inflight = new Map<number, Promise<void>>();
const listeners = new Set<() => void>();

export const driversPath = (season: number) =>
  `/api/drivers?${new URLSearchParams({ season: String(season) })}`;

function load(season: number): void {
  if (cache.has(season) || inflight.has(season)) return;
  const request = fetchJson<DriverInfo[]>(driversPath(season))
    .then((list) => {
      cache.set(season, new Map((Array.isArray(list) ? list : []).map((d) => [d.driver, d])));
      listeners.forEach((notify) => notify());
    })
    .catch(() => {
      // Names are a nicety: callers fall back to the code, and the next mount retries.
    })
    .finally(() => inflight.delete(season));
  inflight.set(season, request);
}

function subscribe(notify: () => void): () => void {
  listeners.add(notify);
  return () => listeners.delete(notify);
}

/**
 * The season's drivers keyed by code, fetched once per season and shared across components.
 * Empty until loaded (or when `season` is null), so pair it with `driverName` for a fallback.
 */
export function useDrivers(season: number | null | undefined): DriverMap {
  useEffect(() => {
    if (season != null) load(season);
  }, [season]);
  return useSyncExternalStore(
    subscribe,
    () => (season != null ? (cache.get(season) ?? EMPTY) : EMPTY),
    () => EMPTY,
  );
}

/**
 * "Lando Norris" for "NOR". A name the API already sent (`known`) wins; the 3-letter code is the
 * last resort when the driver is unknown.
 */
export function driverName(map: DriverMap | null | undefined, code: string, known?: string | null): string {
  return known?.trim() || map?.get(code)?.full_name?.trim() || code;
}

/** "Norris" for "NOR", for tight spots such as track-map labels and chart legends. */
export function driverSurname(map: DriverMap | null | undefined, code: string, known?: string | null): string {
  const last = map?.get(code)?.last_name?.trim();
  if (last) return last;
  const full = known?.trim() || map?.get(code)?.full_name?.trim();
  if (full) return full.split(/\s+/).at(-1) ?? full;
  return code;
}
