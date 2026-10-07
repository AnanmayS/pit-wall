import type { Change, ChangeType, Compound, ScenarioSpec } from "./types";

export const MAX_CHANGES = 10;
export const MIN_RUNS = 100;
export const MAX_RUNS = 100_000;
export const DEFAULT_RUNS = 10_000;

/** Which inputs each change type needs (mirrors the API's validation rules). */
export interface ChangeFields {
  driver: boolean;
  lap: boolean;
  stop: boolean;
  compound: boolean;
}

export const CHANGE_TYPES: { value: ChangeType; label: string; fields: ChangeFields }[] = [
  { value: "pit_lap", label: "Pit on a different lap", fields: { driver: true, lap: true, stop: false, compound: false } },
  { value: "compound", label: "Change tyre compound", fields: { driver: true, lap: false, stop: true, compound: true } },
  { value: "skip_stop", label: "Skip a pit stop", fields: { driver: true, lap: false, stop: true, compound: false } },
  { value: "extra_stop", label: "Add an extra stop", fields: { driver: true, lap: true, stop: false, compound: true } },
  { value: "safety_car", label: "Safety car on a lap", fields: { driver: false, lap: true, stop: false, compound: false } },
  { value: "no_safety_car", label: "No safety car", fields: { driver: false, lap: false, stop: false, compound: false } },
  { value: "dnf", label: "Driver retires (DNF)", fields: { driver: true, lap: true, stop: false, compound: false } },
];

export function fieldsFor(type: ChangeType): ChangeFields {
  return CHANGE_TYPES.find((t) => t.value === type)?.fields ?? CHANGE_TYPES[0].fields;
}

/** Form state for one change; numeric inputs are kept as strings while editing. */
export interface ChangeDraft {
  key: number;
  type: ChangeType;
  driver: string;
  lap: string;
  stop: string;
  compound: Compound;
}

export function newDraft(key: number): ChangeDraft {
  return { key, type: "pit_lap", driver: "", lap: "", stop: "1", compound: "HARD" };
}

function parsePositiveInt(input: string): number | null {
  const n = Number(input);
  return input.trim() !== "" && Number.isInteger(n) && n >= 1 ? n : null;
}

/**
 * Turn a draft into an API change. Returns the problems instead when required inputs are missing.
 * `driver` is the resolved driver (the draft's pick, or the default when it is not in the list).
 */
export function buildChange(
  draft: ChangeDraft,
  driver: string,
  maxLap: number | null,
): { change: Change; problems: string[] } {
  const f = fieldsFor(draft.type);
  const problems: string[] = [];
  const change: Change = { type: draft.type };

  if (f.driver) {
    if (!driver) problems.push("pick a driver");
    change.driver = driver || null;
  }
  if (f.lap) {
    const lap = parsePositiveInt(draft.lap);
    if (lap == null) problems.push("enter a lap");
    else if (maxLap != null && lap > maxLap) problems.push(`lap must be at most ${maxLap}`);
    change.lap = lap;
  }
  if (f.stop) {
    const stop = parsePositiveInt(draft.stop);
    if (stop == null) problems.push("enter a stop number (1 = next stop)");
    change.stop = stop;
  }
  if (f.compound) change.compound = draft.compound;

  return { change, problems };
}

function stopPhrase(stop: number | null | undefined): string {
  if (stop == null || stop === 1) return "their next stop";
  return `remaining stop ${stop}`;
}

function title(compound: Compound | null | undefined): string {
  return compound ? compound.charAt(0) + compound.slice(1).toLowerCase() : "an unspecified tyre";
}

/** "NOR pits on lap 20" etc. */
export function describeChange(c: Change): string {
  const who = c.driver ?? "A driver";
  const lap = c.lap ?? "?";
  switch (c.type) {
    case "pit_lap":
      return `${who} pits on lap ${lap}`;
    case "compound":
      return `${who} fits ${title(c.compound)}s at ${stopPhrase(c.stop)}`;
    case "skip_stop":
      return `${who} skips ${stopPhrase(c.stop)}`;
    case "extra_stop":
      return `${who} makes an extra stop on lap ${lap} for ${title(c.compound)}s`;
    case "safety_car":
      return `Safety car deployed on lap ${lap}`;
    case "no_safety_car":
      return "No safety car";
    case "dnf":
      return `${who} retires on lap ${lap}`;
    default:
      return String((c as { type: string }).type);
  }
}

export function describeSpec(spec: ScenarioSpec): string[] {
  return spec.changes.map(describeChange);
}

export { formatPct, formatTimestamp } from "./format";
