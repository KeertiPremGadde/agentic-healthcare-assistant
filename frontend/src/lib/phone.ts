/**
 * Make the phone numbers in a fixed safety reply tappable (tel: links).
 *
 * Only used on the emergency and crisis cards, whose text is fixed on the server, so the list of
 * numbers is small and known: 112 (EU), 911 and 988 (US), TelefonSeelsorge (Germany) and the US
 * Poison Help line. A regex over arbitrary numbers would turn dates and ids into links.
 */
export interface Segment {
  text: string;
  tel?: string;
}

const NUMBER = /(\b0800 111 0 111\b|\b1-800-222-1222\b|\b(?:112|911|988)\b)/g;

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
