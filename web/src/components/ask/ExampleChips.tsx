export const EXAMPLE_QUESTIONS = [
  "Where did Lando Norris lose time to Max Verstappen in qualifying at the 2025 Chinese Grand Prix?",
  "What if Lando Norris had pitted on lap 20 at the 2025 Chinese Grand Prix?",
  "What was the gap at lap 30 of the 2025 Japanese Grand Prix?",
  "Who had the fastest race lap at the 2025 Australian Grand Prix, and on which tyre?",
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
