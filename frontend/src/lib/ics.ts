/**
 * Build an iCalendar (RFC 5545) file for one appointment, so a patient can add it to their own
 * calendar. (The clinic's shared demo calendar is separate: a service account can't invite people.)
 *
 * Privacy: the event names the doctor and the time only. No patient data goes into the file.
 */

export interface IcsAppointment {
  id: number;
  doctorName: string;
  start: string; // ISO 8601
  durationMinutes?: number;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** 2026-11-02T08:00:00Z as 20261102T080000Z (UTC, so no timezone definition is needed). */
export function icsDate(date: Date): string {
  return (
    `${date.getUTCFullYear()}${pad(date.getUTCMonth() + 1)}${pad(date.getUTCDate())}` +
    `T${pad(date.getUTCHours())}${pad(date.getUTCMinutes())}${pad(date.getUTCSeconds())}Z`
  );
}

/** Escape TEXT values: backslash, semicolon, comma and newlines (RFC 5545, section 3.3.11). */
export function escapeText(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r\n|\r|\n/g, "\\n");
}

/** Lines are at most 75 octets; longer ones are folded with CRLF plus one space. */
export function foldLine(line: string): string {
  const encoder = new TextEncoder();
  const parts: string[] = [];
  let current = "";
  let bytes = 0;
  for (const char of line) {
    const size = encoder.encode(char).length;
    const limit = parts.length === 0 ? 75 : 74; // continuation lines start with a space
    if (bytes + size > limit) {
      parts.push(current);
      current = "";
      bytes = 0;
    }
    current += char;
    bytes += size;
  }
  parts.push(current);
  return parts.join("\r\n ");
}

export function buildIcs(appointment: IcsAppointment, now: Date = new Date()): string {
  const start = new Date(appointment.start);
  if (Number.isNaN(start.getTime())) throw new Error("Invalid appointment start time");
  const end = new Date(start.getTime() + (appointment.durationMinutes ?? 30) * 60_000);
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//MedAgent//Demo//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    // Stable per appointment: importing the file twice updates the event instead of duplicating it.
    `UID:medagent-appointment-${appointment.id}@medagent.demo`,
    `DTSTAMP:${icsDate(now)}`,
    `DTSTART:${icsDate(start)}`,
    `DTEND:${icsDate(end)}`,
    `SUMMARY:${escapeText(`Appointment with ${appointment.doctorName}`)}`,
    `DESCRIPTION:${escapeText("MedAgent demo appointment (synthetic data).")}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ];
  return lines.map(foldLine).join("\r\n") + "\r\n";
}

/** Offer the file as a download. Browser only. */
export function downloadIcs(appointment: IcsAppointment): void {
  const blob = new Blob([buildIcs(appointment)], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `appointment-${appointment.id}.ics`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
