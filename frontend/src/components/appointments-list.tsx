"use client";

import { CalendarPlus, CalendarX2, Stethoscope } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadIcs } from "@/lib/ics";
import type { Appointment } from "@/lib/types";

/** Shown in the viewer's own timezone, with the zone name so there is no ambiguity. */
const formatStart = (iso: string) =>
  new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(iso));

export function AppointmentsList() {
  const { token, ready, signOut } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<Appointment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<number | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);

  const [version, setVersion] = useState(0); // bump to reload the list

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    api
      .getAppointments(token)
      .then((list) => {
        setItems(list);
        setError(null);
      })
      .catch((e) => {
        if (e instanceof api.ApiError && e.isAuth) signOut();
        else setError(e instanceof api.ApiError ? e.message : "Couldn't load your appointments.");
      });
  }, [token, version, signOut]);

  async function cancel(id: number) {
    if (!token) return;
    setCancelling(id);
    try {
      await api.cancelAppointment(token, id);
      setConfirmId(null);
      setVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof api.ApiError ? e.message : "Couldn't cancel the appointment.");
    } finally {
      setCancelling(null);
    }
  }

  return (
    <div className="py-2">
      <h1 className="text-xl font-semibold tracking-tight">My appointments</h1>
      <p className="text-muted-foreground mt-1 text-sm">Your upcoming appointments.</p>

      {error && (
        <p
          role="alert"
          className="border-danger-border bg-danger text-danger-foreground mt-4 rounded-lg border px-3 py-2 text-sm"
        >
          {error}
        </p>
      )}

      {items === null && !error && <p className="text-muted-foreground mt-6 text-sm">Loading…</p>}

      {items?.length === 0 && (
        <div className="mt-8 flex flex-col items-center gap-3 rounded-2xl border border-dashed py-12 text-center">
          <CalendarX2 className="text-muted-foreground size-8" aria-hidden />
          <p className="text-muted-foreground text-sm">You have no upcoming appointments.</p>
          <Link
            href="/"
            className="text-primary focus-visible:ring-ring/50 rounded text-sm font-medium underline underline-offset-2 hover:no-underline focus-visible:ring-3 focus-visible:outline-none"
          >
            Book one in the chat
          </Link>
        </div>
      )}

      <ul className="mt-5 space-y-3">
        {items?.map((appointment) => (
          <li key={appointment.id} className="bg-card rounded-2xl border p-4 shadow-xs">
            <div className="flex items-start gap-3">
              <span className="bg-accent text-primary flex size-10 shrink-0 items-center justify-center rounded-xl">
                <Stethoscope className="size-5" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-medium">{appointment.doctor_name}</p>
                <p className="text-muted-foreground text-sm">
                  <time dateTime={appointment.start}>{formatStart(appointment.start)}</time>
                </p>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  Confirmation #A-{String(appointment.id).padStart(4, "0")}
                </p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="lg"
                onClick={() =>
                  downloadIcs({
                    id: appointment.id,
                    doctorName: appointment.doctor_name,
                    start: appointment.start,
                  })
                }
              >
                <CalendarPlus aria-hidden />
                Add to calendar
              </Button>
              {confirmId === appointment.id ? (
                <>
                  <span className="text-sm">Cancel this appointment?</span>
                  <Button
                    variant="destructive"
                    size="lg"
                    disabled={cancelling === appointment.id}
                    onClick={() => cancel(appointment.id)}
                  >
                    {cancelling === appointment.id ? "Cancelling…" : "Yes, cancel"}
                  </Button>
                  <Button variant="ghost" size="lg" onClick={() => setConfirmId(null)}>
                    Keep it
                  </Button>
                </>
              ) : (
                <Button variant="ghost" size="lg" onClick={() => setConfirmId(appointment.id)}>
                  Cancel
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
