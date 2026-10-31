import { HeartPulse } from "lucide-react";

export const EXAMPLE_PROMPTS = [
  "I have a rash, who should I see?",
  "What causes migraines?",
  "Show hospitals near Berlin",
];

export function EmptyState({
  onPick,
  disabled,
}: {
  onPick: (text: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 py-10 text-center">
      <span className="bg-accent text-primary flex size-14 items-center justify-center rounded-2xl">
        <HeartPulse className="size-8" aria-hidden />
      </span>
      <div>
        <h1 className="text-xl font-semibold tracking-tight">How can I help today?</h1>
        <p className="text-muted-foreground mt-1.5 max-w-sm text-sm">
          Ask a health question, find a doctor, or book an appointment. Answers come with their
          sources.
        </p>
      </div>
      <ul className="flex w-full max-w-sm flex-col gap-2" aria-label="Example questions">
        {EXAMPLE_PROMPTS.map((prompt) => (
          <li key={prompt}>
            <button
              type="button"
              onClick={() => onPick(prompt)}
              disabled={disabled}
              className="bg-card hover:border-primary/40 hover:bg-accent focus-visible:ring-ring/50 w-full rounded-xl border px-4 py-3 text-left text-sm shadow-xs transition-colors focus-visible:ring-3 focus-visible:outline-none disabled:opacity-50"
            >
              {prompt}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
