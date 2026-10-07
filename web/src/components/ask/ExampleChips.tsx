export const EXAMPLE_QUESTIONS = [
  "Where did NOR lose time to VER in qualifying at 2025 round 2?",
  "What if NOR had pitted on lap 20 at 2025 round 2?",
  "What was the gap at lap 30 of 2025 round 3?",
  "Who had the fastest race lap at 2025 round 1, and on which tyre?",
];

export function ExampleChips({
  onPick,
  disabled,
}: {
  onPick: (question: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {EXAMPLE_QUESTIONS.map((q) => (
        <button
          key={q}
          type="button"
          disabled={disabled}
          onClick={() => onPick(q)}
          className="rounded-full border border-border bg-surface-2 px-3 py-1 text-left text-xs text-muted transition-colors hover:border-accent/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
        >
          {q}
        </button>
      ))}
    </div>
  );
}
