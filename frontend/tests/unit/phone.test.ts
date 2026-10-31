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
