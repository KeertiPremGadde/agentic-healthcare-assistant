import { describe, expect, it } from "vitest";
import { parseReply } from "@/lib/citations";

const DISCLAIMER =
  "This is general health information from the sources listed above, not medical advice.";

describe("parseReply", () => {
  it("splits answer, sources, attribution and disclaimer", () => {
    const text = [
      "Migraines are recurring headaches.",
      "",
      "Sources:",
      "- MedlinePlus: Migraine <https://medlineplus.gov/migraine.html>",
      "- Medical_book.pdf, p. 12",
      "",
      "Content: MedlinePlus, National Library of Medicine (public domain)",
      "",
      DISCLAIMER,
    ].join("\n");
    expect(parseReply(text)).toEqual({
      body: "Migraines are recurring headaches.",
      sources: [
        { label: "MedlinePlus: Migraine", url: "https://medlineplus.gov/migraine.html" },
        { label: "Medical_book.pdf, p. 12", url: undefined },
      ],
      attributions: ["MedlinePlus, National Library of Medicine (public domain)"],
      disclaimer: DISCLAIMER,
    });
  });

  it("leaves plain replies alone", () => {
    expect(parseReply("Hello! How can I help?")).toEqual({
      body: "Hello! How can I help?",
      sources: [],
      attributions: [],
      disclaimer: undefined,
    });
  });

  it("keeps the disclaimer of an answer without sources", () => {
    const parsed = parseReply(`I don't know.\n\n${DISCLAIMER}`);
    expect(parsed.body).toBe("I don't know.");
    expect(parsed.disclaimer).toBe(DISCLAIMER);
  });

  it("does not treat a javascript: link as a url", () => {
    const parsed = parseReply("A\n\nSources:\n- X <javascript:alert(1)>");
    expect(parsed.sources.every((s) => !s.url)).toBe(true);
  });
});
