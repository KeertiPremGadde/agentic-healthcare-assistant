"use client";

import { CalendarClock, Stethoscope } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Confirmation } from "@/lib/types";

/**
 * The assistant never books or cancels on its own: the graph pauses (interrupt) and this card asks.
 * Both buttons resume the same conversation; neither calls the language model.
 */
export function ConfirmationCard({
  confirmation,
  disabled,
  onAnswer,
}: {
  confirmation: Confirmation;
  disabled: boolean;
  onAnswer: (confirmed: boolean) => void;
}) {
  const booking = confirmation.type === "confirm_booking";
  return (
    <section
      aria-label={booking ? "Confirm booking" : "Confirm cancellation"}
      className="border-info-border bg-info text-info-foreground max-w-[92%] rounded-2xl rounded-bl-md border p-4 text-sm"
    >
      <p className="font-semibold">
        {booking ? "Please confirm your appointment" : "Please confirm"}
      </p>
      <dl className="mt-2.5 space-y-1.5">
        <div className="flex items-center gap-2">
          <dt className="sr-only">Doctor</dt>
          <Stethoscope className="size-4 shrink-0" aria-hidden />
          <dd>{confirmation.doctor}</dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="sr-only">Time</dt>
          <CalendarClock className="size-4 shrink-0" aria-hidden />
          <dd>{confirmation.start}</dd>
        </div>
      </dl>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="lg" onClick={() => onAnswer(true)} disabled={disabled} className="h-10 px-4">
          {booking ? "Confirm" : "Yes, cancel it"}
        </Button>
        <Button
          size="lg"
          variant="outline"
          onClick={() => onAnswer(false)}
          disabled={disabled}
          className="h-10 px-4"
        >
          {booking ? "Change time" : "Keep it"}
        </Button>
      </div>
    </section>
  );
}
