/**
 * Incremental Server-Sent Events parser.
 *
 * `EventSource` can't send an Authorization header or use POST, so we read `fetch()` response
 * bodies ourselves. Network chunks do not respect event boundaries (an event can arrive in two
 * pieces, or two events in one), so the parser buffers text until a blank line ends an event.
 */

export interface SseEvent {
  event: string;
  data: string;
}

export class SseParser {
  private buffer = "";

  /** Feed the next chunk of text; returns every event that is now complete. */
  push(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const events: SseEvent[] = [];
    // An event ends with a blank line. Accept \n\n, \r\n\r\n and \r\r.
    const boundary = /\r\n\r\n|\n\n|\r\r/;
    for (;;) {
      const match = boundary.exec(this.buffer);
      if (!match) break;
      const block = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      const parsed = parseBlock(block);
      if (parsed) events.push(parsed);
    }
    return events;
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split(/\r\n|\n|\r/)) {
    if (line === "" || line.startsWith(":")) continue; // blank or comment (keepalive)
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length === 0 ? null : { event, data: data.join("\n") };
}

/** Read a streaming Response body as a sequence of SSE events. */
export async function* readSse(response: Response): AsyncGenerator<SseEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      yield* parser.push(decoder.decode(value, { stream: true }));
    }
    yield* parser.push(decoder.decode() + "\n\n");
  } finally {
    reader.releaseLock();
  }
}
