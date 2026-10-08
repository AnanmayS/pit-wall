import type { SessionSummary } from "./types";

/**
 * The race's name for a round, e.g. "Chinese Grand Prix", from GET /api/sessions.
 * Falls back to "Round N" when the sessions are unavailable or do not cover the round.
 */
export function raceName(sessions: readonly SessionSummary[] | null | undefined, round: number): string {
  const list = sessions ?? [];
  const name =
    list.find((s) => s.round === round && s.session_type === "R")?.event_name ??
    list.find((s) => s.round === round)?.event_name;
  return name || `Round ${round}`;
}

/** "Singapore Grand Prix" -> "Singapore", for chart ticks and other tight spots. */
export function shortRaceName(name: string): string {
  const short = name.replace(/\s+Grand Prix$/i, "").trim();
  return short || name;
}

/** "Singapore Grand Prix" -> "the Singapore Grand Prix", for use mid-sentence. */
export function theRace(name: string): string {
  return /grand prix$/i.test(name) ? `the ${name}` : name;
}

/** One entry per round, in round order, labelled by race name (round appended only to tell duplicates apart). */
export function raceOptions<T extends { round: number; event_name: string }>(
  items: readonly T[],
): (T & { label: string })[] {
  const counts = new Map<string, number>();
  for (const it of items) counts.set(it.event_name, (counts.get(it.event_name) ?? 0) + 1);
  return items.map((it) => ({
    ...it,
    label: !it.event_name
      ? `Round ${it.round}`
      : (counts.get(it.event_name) ?? 0) > 1
        ? `${it.event_name} (R${it.round})`
        : it.event_name,
  }));
}
