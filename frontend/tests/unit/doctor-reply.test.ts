import { describe, expect, it } from "vitest";
import { splitDoctorReply } from "@/lib/doctor-reply";
import type { Doctor } from "@/lib/types";

const doctors: Doctor[] = [
  {
    id: 1,
    name: "Dr. Anna Schmidt",
    specialty: "Dermatologist",
    city: "Berlin",
    languages: ["German"],
  },
  {
    id: 2,
    name: "Dr. Jonas Weber",
    specialty: "Dermatologist",
    city: "München",
    languages: ["German"],
  },
];
const NOTE = "This suggestion is based on what you described and is not a diagnosis.";
// The layout the doctor_finder node and the output guard produce.
const reply = [
  "Based on what you describe, a Dermatologist is the right specialist to see.",
  "Doctors you can book:",
  "1. Dr. Anna Schmidt - Berlin (German)",
  "2. Dr. Jonas Weber - München (German)",
  'Tell me which doctor and when, for example: "Book number 1 next Tuesday afternoon".',
  "",
  NOTE,
].join("\n");

describe("splitDoctorReply", () => {
  it("keeps the intro and the note, drops the list, the label and the text hint", () => {
    expect(splitDoctorReply(reply, doctors)).toEqual({
      intro: "Based on what you describe, a Dermatologist is the right specialist to see.",
      notes: [NOTE],
    });
  });

  it("keeps a relaxed-filter sentence that comes before the label", () => {
    const text = reply.replace(
      "Doctors you can book:",
      "I couldn't find one speaking French, so here are others:",
    );
    expect(splitDoctorReply(text, doctors)?.intro).toBe(
      "Based on what you describe, a Dermatologist is the right specialist to see.\n" +
        "I couldn't find one speaking French, so here are others.",
    );
  });

  it("keeps a safety notice that was put in front of the reply", () => {
    const text = `Please call 112 if this is an emergency.\n\n${reply}`;
    expect(splitDoctorReply(text, doctors)?.intro).toBe(
      "Please call 112 if this is an emergency.\n\n" +
        "Based on what you describe, a Dermatologist is the right specialist to see.",
    );
  });

  it("works without a hint line or without a note", () => {
    const noHint = reply.replace(/\nTell me which[^\n]*/, "");
    expect(splitDoctorReply(noHint, doctors)?.notes).toEqual([NOTE]);
    const noNote = reply.split("\n\n")[0];
    expect(splitDoctorReply(noNote, doctors)?.notes).toEqual([]);
  });

  it("returns null when the list isn't recognised, so the text is shown unchanged", () => {
    expect(splitDoctorReply("I couldn't find a dermatologist right now.", doctors)).toBeNull();
    expect(splitDoctorReply(reply, [{ ...doctors[0], name: "Dr. Somebody Else" }])).toBeNull();
  });
});
