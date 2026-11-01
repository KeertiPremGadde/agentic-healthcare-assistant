import { describe, expect, it } from "vitest";
import { decodeEvent } from "@/lib/api";
import { SseParser } from "@/lib/sse";

describe("SseParser", () => {
  it("parses complete events", () => {
    const events = new SseParser().push(
      'event: step\ndata: {"label":"x"}\n\nevent: done\ndata: {}\n\n',
    );
    expect(events).toEqual([
      { event: "step", data: '{"label":"x"}' },
      { event: "done", data: "{}" },
    ]);
  });

  it("buffers an event split across chunks, even mid-line", () => {
    const parser = new SseParser();
    expect(parser.push("event: tok")).toEqual([]);
    expect(parser.push('en\ndata: {"text":"hi')).toEqual([]);
    expect(parser.push('"}\n')).toEqual([]);
    expect(parser.push("\n")).toEqual([{ event: "token", data: '{"text":"hi"}' }]);
  });

  it("handles CRLF line endings", () => {
    const events = new SseParser().push("event: message\r\ndata: {}\r\n\r\n");
    expect(events).toEqual([{ event: "message", data: "{}" }]);
  });

  it("ignores keepalive comments", () => {
    const parser = new SseParser();
    expect(parser.push(": keepalive\n\n")).toEqual([]);
    expect(parser.push(": keepalive\n\nevent: done\ndata: {}\n\n")).toEqual([
      { event: "done", data: "{}" },
    ]);
  });

  it("joins multiple data lines and defaults the event name", () => {
    expect(new SseParser().push("data: a\ndata: b\n\n")).toEqual([
      { event: "message", data: "a\nb" },
    ]);
  });

  it("keeps non-ASCII text intact", () => {
    const [event] = new SseParser().push('event: token\ndata: {"text":"Ärztin München"}\n\n');
    expect(JSON.parse(event.data).text).toBe("Ärztin München");
  });
});

describe("decodeEvent", () => {
  it("decodes the message kind and appointment id", () => {
    expect(
      decodeEvent("message", JSON.stringify({ text: "Booked", kind: "booked", appointment_id: 7 })),
    ).toEqual({ type: "message", text: "Booked", kind: "booked", appointmentId: 7 });
  });

  it("treats a message without a kind as normal", () => {
    expect(decodeEvent("message", '{"text":"hi"}')).toMatchObject({ kind: "normal" });
  });

  it("decodes confirmation, done and error", () => {
    const confirmation = { type: "confirm_booking", doctor: "Dr. A", start: "Mon", question: "?" };
    expect(decodeEvent("confirmation", JSON.stringify(confirmation))).toEqual({
      type: "confirmation",
      confirmation,
    });
    expect(
      decodeEvent("done", '{"conversation_id":"c","pending":true,"usage":{"input_tokens":1}}'),
    ).toMatchObject({ type: "done", conversationId: "c", pending: true });
    expect(decodeEvent("error", '{"code":"internal_error","message":"m"}')).toEqual({
      type: "error",
      code: "internal_error",
      message: "m",
    });
  });

  it("ignores unknown events and bad JSON", () => {
    expect(decodeEvent("mystery", "{}")).toBeNull();
    expect(decodeEvent("step", "not json")).toBeNull();
  });
});
