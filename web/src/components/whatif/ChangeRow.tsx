"use client";

import { Field, controlClass } from "@/components/Field";
import { COMPOUNDS, type ChangeType, type Compound, type DriverSummary } from "@/lib/types";
import { CHANGE_TYPES, fieldsFor, type ChangeDraft } from "@/lib/whatif";

export function ChangeRow({
  index,
  draft,
  driver,
  drivers,
  maxLap,
  problems,
  showProblems,
  onChange,
  onRemove,
  disabled,
}: {
  index: number;
  draft: ChangeDraft;
  /** Resolved driver (draft pick, or the default). */
  driver: string;
  drivers: DriverSummary[];
  maxLap: number | null;
  problems: string[];
  showProblems: boolean;
  onChange: (patch: Partial<ChangeDraft>) => void;
  onRemove: (() => void) | null;
  disabled: boolean;
}) {
  const f = fieldsFor(draft.type);

  return (
    <div className="rounded-lg border border-border bg-surface-2/40 p-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-[minmax(11rem,1.4fr)_1fr_6rem_6rem_1fr_auto] sm:items-end">
        <div className="col-span-2 sm:col-span-1">
          <Field label={`Change ${index + 1}`}>
            <select
              className={controlClass}
              value={draft.type}
              disabled={disabled}
              onChange={(e) => onChange({ type: e.target.value as ChangeType })}
            >
              {CHANGE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Driver">
          <select
            className={controlClass}
            value={f.driver ? driver : ""}
            disabled={disabled || !f.driver || drivers.length === 0}
            onChange={(e) => onChange({ driver: e.target.value })}
          >
            {(!f.driver || drivers.length === 0) && <option value="">-</option>}
            {f.driver &&
              drivers.map((d) => (
                <option key={d.driver} value={d.driver}>
                  {d.driver} &middot; {d.team}
                </option>
              ))}
          </select>
        </Field>
        <Field label="Lap">
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={maxLap ?? undefined}
            placeholder={f.lap ? "e.g. 20" : "-"}
            className={controlClass}
            value={f.lap ? draft.lap : ""}
            disabled={disabled || !f.lap}
            onChange={(e) => onChange({ lap: e.target.value })}
          />
        </Field>
        <Field label="Stop #">
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={6}
            title="1 = the driver's next remaining stop"
            className={controlClass}
            value={f.stop ? draft.stop : ""}
            placeholder={f.stop ? "1" : "-"}
            disabled={disabled || !f.stop}
            onChange={(e) => onChange({ stop: e.target.value })}
          />
        </Field>
        <Field label="Compound">
          <select
            className={controlClass}
            value={f.compound ? draft.compound : ""}
            disabled={disabled || !f.compound}
            onChange={(e) => onChange({ compound: e.target.value as Compound })}
          >
            {!f.compound && <option value="">-</option>}
            {f.compound &&
              COMPOUNDS.map((c) => (
                <option key={c} value={c}>
                  {c.charAt(0) + c.slice(1).toLowerCase()}
                </option>
              ))}
          </select>
        </Field>
        <button
          type="button"
          onClick={onRemove ?? undefined}
          disabled={disabled || !onRemove}
          aria-label={`Remove change ${index + 1}`}
          className="h-9 rounded-md px-3 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:invisible"
        >
          Remove
        </button>
      </div>
      {showProblems && problems.length > 0 && (
        <p className="mt-2 text-xs text-amber-300">To run this change: {problems.join(", ")}.</p>
      )}
    </div>
  );
}
