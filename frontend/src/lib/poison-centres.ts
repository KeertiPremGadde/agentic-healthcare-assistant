/**
 * German poison information centres (Giftinformationszentren): emergency ("Notruf") lines from the
 * official directory of the Federal Institute for Risk Assessment (BfR), marked "Stand: 22.07.2026":
 * https://www.bfr.bund.de/deutsches-produktregister-de-pro/giftinformationszentren-in-deutschland/
 *
 * Germany has several regional centres and no single number. Any centre takes calls from anywhere.
 * The directory states no opening hours, so none are claimed. Re-check against the directory
 * before changing a number.
 *
 * The same list is POISON_CENTRES_DE in src/medagent/guardrails/texts.py (the German fixed replies);
 * a backend test compares the two, so they cannot drift apart.
 */
export const POISON_DIRECTORY =
  "https://www.bfr.bund.de/deutsches-produktregister-de-pro/giftinformationszentren-in-deutschland/";

export const POISON_CENTRES = [
  { city: "Berlin", number: "030 19240" },
  { city: "Bonn", number: "0228 19240" },
  { city: "Erfurt", number: "0361 730730" },
  { city: "Freiburg", number: "0761 19240" },
  { city: "Göttingen", number: "0551 19240" },
  { city: "Mainz", number: "06131 19240" },
  { city: "München", number: "089 19240" },
] as const;
