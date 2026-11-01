import type { Confirmation } from "./types";

/**
 * The reason the assistant gives before asking, if any.
 *
 * The confirmation question can start with an explanation, e.g. "Dr. X has no free morning slot on
 * that day. Shall I book Thu 5 Nov 2026, 09:00 with Dr. X?". The card shows the doctor and the time
 * as data, so only the explanation is kept (the question itself would repeat them). Without this,
 * a booking offered for a different day than the one requested would come with no reason.
 */
export function confirmationNote(confirmation: Confirmation): string {
  const question = confirmation.question;
  const at = question.indexOf("Shall I book");
  return at > 0 ? question.slice(0, at).trim() : "";
}
