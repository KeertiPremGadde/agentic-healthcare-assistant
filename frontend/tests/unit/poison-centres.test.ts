import { describe, expect, it } from "vitest";
import { linkifyPhones } from "@/lib/phone";
import { POISON_CENTRES, POISON_DIRECTORY } from "@/lib/poison-centres";

// The seven "Notruf" lines of the BfR directory (Stand 22.07.2026), written out here on purpose,
// independently of the module under test.
const BFR = {
  Berlin: "030 19240",
  Bonn: "0228 19240",
  Erfurt: "0361 730730",
  Freiburg: "0761 19240",
  Göttingen: "0551 19240",
  Mainz: "06131 19240",
  München: "089 19240",
};

describe("poison centres", () => {
  it("lists all seven centres of the BfR directory with their emergency lines", () => {
    expect(Object.fromEntries(POISON_CENTRES.map((c) => [c.city, c.number]))).toEqual(BFR);
  });

  it("points to the official directory", () => {
    expect(POISON_DIRECTORY).toMatch(/^https:\/\/www\.bfr\.bund\.de\//);
  });

  it("makes every centre's number a tel: link in a fixed reply", () => {
    const text = POISON_CENTRES.map((c) => `${c.city} ${c.number}`).join(" · ");
    const linked = linkifyPhones(text)
      .filter((s) => s.tel)
      .map((s) => s.tel);
    expect(linked).toEqual(POISON_CENTRES.map((c) => c.number.replace(/\s/g, "")));
  });
});
