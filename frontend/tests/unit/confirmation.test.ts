import { describe, expect, it } from "vitest";
import { confirmationNote } from "@/lib/confirmation";
import type { Confirmation } from "@/lib/types";

const base: Confirmation = {
  type: "confirm_booking",
  doctor: "Dr. A",
  start: "Thu 5 Nov 2026, 09:00",
  question: "",
};

describe("confirmationNote", () => {
  it("returns the explanation that comes before the question", () => {
    expect(
      confirmationNote({
        ...base,
        question: "Dr. A doesn't work on Mondays. Shall I book Thu 5 Nov 2026, 09:00 with Dr. A?",
      }),
    ).toBe("Dr. A doesn't work on Mondays.");
  });

  it("is empty for a plain question and for a cancellation", () => {
    expect(
      confirmationNote({ ...base, question: "Shall I book Thu 5 Nov 2026, 09:00 with Dr. A?" }),
    ).toBe("");
    expect(
      confirmationNote({
        ...base,
        type: "confirm_cancel",
        question: "Cancel your appointment with Dr. A on Thu 5 Nov 2026, 09:00?",
      }),
    ).toBe("");
  });
});
