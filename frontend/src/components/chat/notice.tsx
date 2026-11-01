import { cn } from "@/lib/utils";

type Icon = React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

const TONES = {
  danger: "border-danger-border bg-danger text-danger-foreground",
  care: "border-care-border bg-care text-care-foreground",
  success: "border-success-border bg-success text-success-foreground",
} as const;

/** A coloured assistant card with an icon and a title. The colour is never the only signal. */
export function Notice({
  tone,
  icon: Icon,
  title,
  children,
}: {
  tone: keyof typeof TONES;
  icon: Icon;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn("max-w-[92%] rounded-2xl rounded-bl-md border px-4 py-3 text-sm", TONES[tone])}
    >
      <p className="flex items-center gap-2 font-semibold">
        <Icon className="size-5 shrink-0" aria-hidden />
        {title}
      </p>
      {children}
    </div>
  );
}
