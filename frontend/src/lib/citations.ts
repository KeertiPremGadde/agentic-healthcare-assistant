/**
 * Split an assistant reply into the answer, its sources and the disclaimer.
 *
 * The backend appends these in a fixed layout (src/medagent/rag/answer.py: a "Sources:" list of
 * "- label <url>" lines, "Content: ..." attribution lines, then the disclaimer), in English or
 * German ("Quellen:", "Inhalt:", German disclaimer). The labels and the disclaimer start must
 * match src/medagent/guardrails/texts.py. This only decides how the text is displayed; nothing
 * here affects what is safe to say.
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

const DISCLAIMER_STARTS = [
  "This is general health information",
  "Dies sind allgemeine Gesundheitsinformationen",
];
const SOURCES_LINE = /^(?:Sources|Quellen):\s*$/m;
const CONTENT_LABEL = /^(?:Content|Inhalt):\s*/;

export function parseReply(text: string): ParsedReply {
  let rest = text;
  let disclaimer: string | undefined;
  const disclaimerAt = Math.min(
    ...DISCLAIMER_STARTS.map((start) => rest.indexOf(start)).filter((at) => at !== -1),
  );
  if (Number.isFinite(disclaimerAt)) {
    disclaimer = rest.slice(disclaimerAt).trim();
    rest = rest.slice(0, disclaimerAt);
  }

  const sources: Source[] = [];
  const attributions: string[] = [];
  const marker = rest.search(SOURCES_LINE);
  if (marker === -1) return { body: rest.trim(), sources, attributions, disclaimer };

  const body = rest.slice(0, marker).trim();
  for (const line of rest.slice(marker).split(/\r?\n/).slice(1)) {
    const text = line.trim();
    if (!text) continue;
    if (CONTENT_LABEL.test(text)) {
      attributions.push(text.replace(CONTENT_LABEL, ""));
      continue;
    }
    const item = /^[-*]\s+(.*?)(?:\s+<(https?:\/\/[^>\s]+)>)?$/.exec(text);
    if (item) sources.push({ label: item[1], url: item[2] });
  }
  return { body, sources, attributions, disclaimer };
}
