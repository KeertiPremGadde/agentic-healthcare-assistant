import { describe, expect, it } from "vitest";
import { linkifyPhones } from "@/lib/phone";

const tels = (text: string) =>
  linkifyPhones(text)
    .filter((s) => s.tel)
    .map((s) => [s.text, s.tel]);

describe("linkifyPhones", () => {
  it("links the emergency and crisis numbers of the fixed replies", () => {
    expect(
      tels(
        "- Germany: TelefonSeelsorge, free: 0800 111 0 111\n- EU: 112 (emergency services)\n" +
          "- US: call or text 988 (Suicide & Crisis Lifeline)",
      ),
    ).toEqual([
      ["0800 111 0 111", "08001110111"],
      ["112", "112"],
      ["988", "988"],
    ]);
  });

  it("links the US poison line and 911", () => {
    expect(tels("Poison Help 1-800-222-1222 or 911")).toEqual([
      ["1-800-222-1222", "18002221222"],
      ["911", "911"],
    ]);
  });

  it("links the German numbers of the fixed German replies", () => {
    expect(
      tels(
        "wählen Sie sofort die 112. Giftnotruf: Berlin 030 19240 · Bonn 0228 19240 · " +
          "Erfurt 0361 730730 · Freiburg 0761 19240 · Göttingen 0551 19240 · " +
          "Mainz 06131 19240 · München 089 19240. Bereitschaftsdienst 116 117, " +
          "TelefonSeelsorge 0800 111 0 111 oder 116 123.",
      ),
    ).toEqual([
      ["112", "112"],
      ["030 19240", "03019240"],
      ["0228 19240", "022819240"],
      ["0361 730730", "0361730730"],
      ["0761 19240", "076119240"],
      ["0551 19240", "055119240"],
      ["06131 19240", "0613119240"],
      ["089 19240", "08919240"],
      ["116 117", "116117"],
      ["0800 111 0 111", "08001110111"],
      ["116 123", "116123"],
    ]);
  });

  it("does not link look-alikes of the German numbers", () => {
    expect(tels("Az. 030 19241, 1161171, 0361 7307300, 116 118, 9030 19240")).toEqual([]);
  });

  it("does not turn other numbers into links", () => {
    expect(tels("Confirmation #A-0112 on 4 Mar 2030, room 1129, 2112")).toEqual([]);
  });

  it("keeps all the text, in order", () => {
    const text = "Call 112 now, or 911.";
    expect(
      linkifyPhones(text)
        .map((s) => s.text)
        .join(""),
    ).toBe(text);
  });
});
