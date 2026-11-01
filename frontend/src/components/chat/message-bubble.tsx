"use client";

import { Info, TriangleAlert } from "lucide-react";
import { parseReply } from "@/lib/citations";
import { splitDoctorReply } from "@/lib/doctor-reply";
import type { ChatMessage } from "@/lib/use-chat";
import { BookedCard } from "./booked-card";
import { DoctorCards, type BookState } from "./doctor-cards";
import { Notice } from "./notice";
import { CrisisCard, EmergencyCard } from "./safety-cards";

export function MessageBubble({
  message,
  bookState,
  onBook,
}: {
  message: ChatMessage;
  bookState: BookState;
  onBook: (number: number) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="bg-primary text-primary-foreground max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
          {message.text}
        </p>
      </div>
    );
  }
  if (message.isError) {
    return (
      <div className="flex">
        <Notice tone="danger" icon={TriangleAlert} title="Something went wrong">
          <p className="mt-1.5 leading-relaxed">{message.text}</p>
        </Notice>
      </div>
    );
  }
  if (message.kind === "emergency") return <EmergencyCard text={message.text} />;
  if (message.kind === "harmful_intent") return <CrisisCard text={message.text} />;
  if (message.kind === "booked") {
    return <BookedCard booking={message.booking} text={message.text} />;
  }
  return <AssistantBubble message={message} bookState={bookState} onBook={onBook} />;
}

const BOOK_HINT =
  'Tap Book, or tell me a day and time (e.g. "Book number 1 next Tuesday afternoon")';

function AssistantBubble({
  message,
  bookState,
  onBook,
}: {
  message: ChatMessage;
  bookState: BookState;
  onBook: (number: number) => void;
}) {
  const { body, sources, attributions, disclaimer } = parseReply(message.text);
  const doctors = message.doctors?.length ? message.doctors : undefined;
  // Doctor suggestions read as: intro, cards, hint, note. If the list isn't recognised the text is
  // shown as it is and the cards follow it.
  const split = doctors ? splitDoctorReply(body, doctors) : null;
  const shown = split ? split.intro : body;
  return (
    <div className="flex flex-col items-start">
      <div className="bg-card max-w-[92%] rounded-2xl rounded-bl-md border px-4 py-3 text-sm leading-relaxed shadow-xs">
        <p className="whitespace-pre-wrap">{shown || (message.streaming ? "…" : "")}</p>
        {sources.length > 0 && (
          <div className="mt-3 border-t pt-2.5">
            <p className="text-muted-foreground mb-1 text-xs font-medium">Sources</p>
            <ul className="space-y-1 text-xs">
              {sources.map((source, i) => (
                <li key={i} className="flex gap-1.5">
                  <span aria-hidden className="text-muted-foreground">
                    {i + 1}.
                  </span>
                  {source.url ? (
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary underline underline-offset-2 hover:no-underline"
                    >
                      {source.label}
                    </a>
                  ) : (
                    <span>{source.label}</span>
                  )}
                </li>
              ))}
            </ul>
            {attributions.map((line) => (
              <p key={line} className="text-muted-foreground mt-1.5 text-[0.7rem]">
                {line}
              </p>
            ))}
          </div>
        )}
        {disclaimer && (
          <p className="bg-warn text-warn-foreground mt-3 flex gap-1.5 rounded-lg px-2.5 py-2 text-xs">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {disclaimer}
          </p>
        )}
      </div>
      {doctors && (
        <div className="w-full max-w-[92%]">
          <DoctorCards doctors={doctors} state={bookState} onBook={onBook} />
          <p className="text-muted-foreground mt-2 text-xs">{BOOK_HINT}</p>
          {split?.notes.map((note) => (
            <p key={note} className="text-muted-foreground mt-2 flex gap-1.5 text-xs">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {note}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
