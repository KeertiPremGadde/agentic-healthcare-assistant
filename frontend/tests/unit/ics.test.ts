import { describe, expect, it } from "vitest";
import { buildIcs, escapeText, foldLine, icsDate } from "@/lib/ics";

const NOW = new Date("2026-11-01T10:00:00Z");
const appointment = { id: 12, doctorName: "Dr. Anna Schmidt", start: "2026-11-02T07:00:00+00:00" };

describe("buildIcs", () => {
  const lines = buildIcs(appointment, NOW).split("\r\n");

  it("is a VCALENDAR with one VEVENT and CRLF endings", () => {
    expect(lines[0]).toBe("BEGIN:VCALENDAR");
    expect(lines).toContain("BEGIN:VEVENT");
    expect(lines.filter((l) => l === "END:VEVENT")).toHaveLength(1);
    expect(lines.at(-2)).toBe("END:VCALENDAR");
    expect(lines.at(-1)).toBe(""); // the file ends with a CRLF
  });

  it("writes UTC times and a 30 minute default duration", () => {
    expect(lines).toContain("DTSTART:20261102T070000Z");
    expect(lines).toContain("DTEND:20261102T073000Z");
    expect(lines).toContain("DTSTAMP:20261101T100000Z");
  });

  it("uses a stable UID so re-importing updates instead of duplicating", () => {
    expect(lines).toContain("UID:medagent-appointment-12@medagent.demo");
    expect(buildIcs(appointment, new Date())).toContain(
      "UID:medagent-appointment-12@medagent.demo",
    );
  });

  it("names the doctor and time only, nothing about the patient", () => {
    expect(lines).toContain("SUMMARY:Appointment with Dr. Anna Schmidt");
    const text = lines.join("\n").toLowerCase();
    expect(text).not.toContain("patient");
    expect(text).not.toContain("attendee");
  });

  it("rejects an invalid date", () => {
    expect(() => buildIcs({ ...appointment, start: "soon" })).toThrow();
  });
});

describe("escaping and folding", () => {
  it("escapes the characters RFC 5545 reserves", () => {
    expect(escapeText("a,b;c\\d\ne")).toBe("a\\,b\\;c\\\\d\\ne");
  });

  it("escapes a doctor name with a comma", () => {
    expect(buildIcs({ ...appointment, doctorName: "Dr. Meier, Hans" }, NOW)).toContain(
      "SUMMARY:Appointment with Dr. Meier\\, Hans",
    );
  });

  it("folds long lines at 75 octets without splitting a character", () => {
    const long = "SUMMARY:" + "ä".repeat(60); // 2 octets each
    const folded = foldLine(long).split("\r\n");
    expect(folded.length).toBeGreaterThan(1);
    for (const part of folded) {
      expect(new TextEncoder().encode(part).length).toBeLessThanOrEqual(75);
    }
    expect(folded.map((p, i) => (i ? p.slice(1) : p)).join("")).toBe(long);
  });

  it("formats dates as UTC basic format", () => {
    expect(icsDate(new Date("2027-01-05T09:05:03Z"))).toBe("20270105T090503Z");
  });
});
