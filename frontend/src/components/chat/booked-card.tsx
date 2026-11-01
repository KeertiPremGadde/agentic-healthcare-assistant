"use client";

import { CalendarClock, CalendarPlus, CircleCheck, Hash, Stethoscope } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadIcs } from "@/lib/ics";
import type { Booking } from "@/lib/types";
import { Notice } from "./notice";

/** Same layout as the confirmation card: doctor and time with icons, then the number. */
export function BookedCard({ booking, text }: { booking?: Booking; text: string }) {
  const { token } = useAuth();
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");

  async function addToCalendar() {
    if (!token || !booking) return;
    setState("loading");
    try {
      // The file is built in the browser from the appointment record (doctor and time only).
      const all = await api.getAppointments(token);
      const found = all.find((a) => a.id === booking.appointment_id);
      if (!found) throw new Error("not found");
      downloadIcs({ id: found.id, doctorName: found.doctor_name, start: found.start });
      setState("idle");
    } catch {
      setState("error");
    }
  }

  return (
    <div className="flex">
      <Notice tone="success" icon={CircleCheck} title="Appointment booked">
        {booking ? (
          <>
            <dl className="mt-2.5 space-y-1.5">
              <div className="flex items-center gap-2">
                <dt className="sr-only">Doctor</dt>
                <Stethoscope className="size-4 shrink-0" aria-hidden />
                <dd>{booking.doctor}</dd>
              </div>
              <div className="flex items-center gap-2">
                <dt className="sr-only">Time</dt>
                <CalendarClock className="size-4 shrink-0" aria-hidden />
                <dd>{booking.start}</dd>
              </div>
              <div className="flex items-center gap-2">
                <dt className="sr-only">Confirmation number</dt>
                <Hash className="size-4 shrink-0" aria-hidden />
                <dd>Confirmation #A-{String(booking.appointment_id).padStart(4, "0")}</dd>
              </div>
            </dl>
            <div className="mt-4">
              <Button
                variant="outline"
                size="lg"
                className="h-10 px-4"
                onClick={addToCalendar}
                disabled={state === "loading"}
              >
                <CalendarPlus aria-hidden />
                Add to calendar
              </Button>
              {state === "error" && (
                <p role="status" className="mt-2 text-xs">
                  Couldn&apos;t create the calendar file. Please try again.
                </p>
              )}
            </div>
          </>
        ) : (
          <p className="mt-1.5 leading-relaxed whitespace-pre-wrap">{text}</p>
        )}
      </Notice>
    </div>
  );
}
