"use client";

import { Clock, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { useChat } from "@/lib/use-chat";
import { Composer } from "./composer";
import { ConfirmationCard } from "./confirmation-card";
import { EmptyState } from "./empty-state";
import { MessageBubble } from "./message-bubble";

function waitText(seconds?: number): string {
  if (!seconds) return "";
  const hours = Math.round(seconds / 3600);
  return hours >= 1 ? ` Try again in about ${hours} hour${hours === 1 ? "" : "s"}.` : "";
}

export function Chat() {
  const { token, ready } = useAuth();
  const router = useRouter();
  const chat = useChat();
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat.messages, chat.step, chat.pending]);

  if (!ready || !token)
    return <p className="text-muted-foreground py-10 text-center text-sm">Loading…</p>;

  const empty = chat.messages.length === 0 && !chat.pending;
  const blocked = chat.busy || chat.pending !== null;

  return (
    <div className="flex flex-1 flex-col">
      {!empty && (
        <div className="mb-2 flex justify-end">
          <Button variant="ghost" size="sm" onClick={chat.reset} disabled={chat.busy}>
            <Plus aria-hidden />
            New conversation
          </Button>
        </div>
      )}
      {empty ? (
        <EmptyState onPick={chat.send} disabled={blocked} />
      ) : (
        <div
          role="log"
          aria-label="Conversation"
          aria-live="polite"
          aria-busy={chat.busy}
          className="flex flex-1 flex-col gap-3 pb-4"
        >
          {chat.messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {chat.pending && (
            <ConfirmationCard
              confirmation={chat.pending}
              disabled={chat.busy}
              onAnswer={chat.confirm}
            />
          )}
          {chat.step && (
            <p
              role="status"
              className="text-muted-foreground flex items-center gap-2 px-1 text-sm italic"
            >
              <span aria-hidden className="flex gap-1">
                {[0, 150, 300].map((delay) => (
                  <span
                    key={delay}
                    className="bg-primary/60 size-1.5 animate-bounce rounded-full"
                    style={{ animationDelay: `${delay}ms` }}
                  />
                ))}
              </span>
              {chat.step}
            </p>
          )}
          <div ref={bottom} className="scroll-mb-32" />
        </div>
      )}
      {chat.limitNotice && (
        <p
          role="alert"
          className="border-info-border bg-info text-info-foreground mb-3 flex items-start gap-2 rounded-xl border px-4 py-3 text-sm"
        >
          <Clock className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {chat.limitNotice.message}
            {waitText(chat.limitNotice.retryAfterSeconds)} You can still confirm or cancel anything
            that is waiting for your answer.
          </span>
        </p>
      )}
      <Composer
        limits={chat.limits}
        disabled={blocked}
        placeholder={
          chat.pending ? "Answer the question above to continue" : "Ask a health question…"
        }
        onSend={chat.send}
      />
    </div>
  );
}
