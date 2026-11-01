import { TriangleAlert } from "lucide-react";

/** Always visible: this is a demo with synthetic data, and not medical advice. */
export function DisclaimerBanner() {
  return (
    <div role="note" className="border-warn-border bg-warn text-warn-foreground border-b">
      <p className="mx-auto flex max-w-3xl items-start gap-2 px-4 py-2 text-xs leading-relaxed sm:text-sm">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          <strong>Demo with synthetic data.</strong> Not medical advice. Emergency:{" "}
          <strong>112</strong> (EU) · <strong>911</strong> (US)
        </span>
      </p>
    </div>
  );
}
