import type { Doctor } from "./types";

export interface DoctorReplyParts {
  /** the sentence(s) before the list: what the assistant says about the specialty */
  intro: string;
  /** paragraphs after the list and its hint (the "not a diagnosis" note), shown below the cards */
  notes: string[];
}

/**
 * Lay out a doctor suggestion as intro, cards, hint and note.
 *
 * The server writes the reply as: intro line(s), a "Doctors you can book:" label, one numbered line
 * per doctor, a hint line ("Tell me which doctor and when ..."), then a blank line and the safety
 * note. With cards on screen the numbered lines, the label and the text hint are redundant (the UI
 * has its own hint), so they are dropped; the list is found by matching the known doctor names, not
 * by guessing at the format. Returns null when the list isn't recognised: the caller then shows the
 * text as it is.
 */
export function splitDoctorReply(body: string, doctors: Doctor[]): DoctorReplyParts | null {
  const lines = body.split("\n");
  const isListed = (line: string) =>
    doctors.some((d, i) => line.trim().startsWith(`${i + 1}. ${d.name}`));
  const first = lines.findIndex(isListed);
  const last = lines.findLastIndex(isListed);
  if (first === -1) return null;

  const before = lines.slice(0, first);
  const label = before.findLastIndex((line) => line.trim() !== "");
  if (label !== -1) {
    const line = before[label].trim();
    if (line === "Doctors you can book:")
      before.splice(label, 1); // the generic label is redundant
    else if (line.endsWith(":")) before[label] = line.replace(/:$/, "."); // keep "...so here are others"
  }
  const intro = before.join("\n").trim();

  const after = lines.slice(last + 1);
  if (after.length && after[0].trim() !== "") {
    // a hint line directly under the list: drop it up to the next blank line
    const blank = after.findIndex((line) => line.trim() === "");
    after.splice(0, blank === -1 ? after.length : blank);
  }
  const notes = after
    .join("\n")
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  return { intro, notes };
}
