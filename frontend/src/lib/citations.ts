/**
 * Split an assistant reply into the answer, its sources and the disclaimer.
 *
 * The backend appends these in a fixed layout (src/medagent/rag/answer.py: a "Sources:" list of
 * "- label <url>" lines, "Content: ..." attribution lines, then the disclaimer). This only
 * decides how the text is displayed; nothing here affects what is safe to say.
 */

export interface Source {
  label: string;
  url?: string;
}

export interface ParsedReply {
  body: string;
  sources: Source[];
  attributions: string[];
  disclaimer?: string;
}

const DISCLAIMER_START = "This is general health information";

export function parseReply(text: string): ParsedReply {
  let rest = text;
  let disclaimer: string | undefined;
  const disclaimerAt = rest.indexOf(DISCLAIMER_START);
  if (disclaimerAt !== -1) {
    disclaimer = rest.slice(disclaimerAt).trim();
    rest = rest.slice(0, disclaimerAt);
  }

  const sources: Source[] = [];
  const attributions: string[] = [];
  const marker = rest.search(/^Sources:\s*$/m);
  if (marker === -1) return { body: rest.trim(), sources, attributions, disclaimer };

  const body = rest.slice(0, marker).trim();
  for (const line of rest.slice(marker).split(/\r?\n/).slice(1)) {
    const text = line.trim();
    if (!text) continue;
    if (text.startsWith("Content:")) {
      attributions.push(text.replace(/^Content:\s*/, ""));
      continue;
    }
    const item = /^[-*]\s+(.*?)(?:\s+<(https?:\/\/[^>\s]+)>)?$/.exec(text);
    if (item) sources.push({ label: item[1], url: item[2] });
  }
  return { body, sources, attributions, disclaimer };
}
