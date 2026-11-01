import { POISON_CENTRES } from "@/lib/poison-centres";

/**
 * Make the phone numbers in a fixed safety reply tappable (tel: links).
 *
 * Only used on the emergency and crisis cards, whose text is fixed on the server, so the list of
 * numbers is small and known: 112 (EU), 911 and 988 (US), TelefonSeelsorge (0800 111 0 111 and
 * 116 123) and the on-call doctor service 116 117 (Germany), the US Poison Help line, and the
 * seven German poison centres (BfR directory, Stand 22.07.2026; the same list as
 * src/medagent/guardrails/texts.py). A regex over arbitrary numbers would turn dates and ids into
 * links.
 */
export interface Segment {
  text: string;
  tel?: string;
}

const POISON_NUMBERS = POISON_CENTRES.map((centre) => centre.number).join("|");
const NUMBER = new RegExp(
  `(\\b0800 111 0 111\\b|\\b0800 111 0550\\b|\\b1-800-222-1222\\b|\\b116 1(?:11|17|23)\\b|\\b(?:${POISON_NUMBERS})\\b|` +
    "\\b(?:112|911|988)\\b)",
  "g",
);

export function linkifyPhones(text: string): Segment[] {
  const segments: Segment[] = [];
  let last = 0;
  for (const match of text.matchAll(NUMBER)) {
    const start = match.index ?? 0;
    if (start > last) segments.push({ text: text.slice(last, start) });
    segments.push({ text: match[0], tel: match[0].replace(/[^\d]/g, "") });
    last = start + match[0].length;
  }
  if (last < text.length) segments.push({ text: text.slice(last) });
  return segments;
}
