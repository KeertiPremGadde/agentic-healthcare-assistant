"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import { useAuth } from "./auth";
import { CONVERSATION_KEY, readSession, writeSession } from "./session-storage";
import type { ChatEvent, Confirmation, Limits, MessageKind } from "./types";

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  kind: MessageKind;
  appointmentId?: number;
  streaming?: boolean;
  isError?: boolean;
}

export interface LimitNotice {
  message: string;
  retryAfterSeconds?: number;
}

/**
 * The chat state machine. One turn = one request: the server streams `step` events while it
 * works, `token` events with the answer, then `message` (the final text and how to present it)
 * and `done`. A turn ends either with a reply or with a `confirmation` that the user answers
 * through `confirm()`, which resumes the same conversation.
 */
export function useChat() {
  const { token, signOut } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [step, setStep] = useState<string | null>(null);
  const [pending, setPending] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [limitNotice, setLimitNotice] = useState<LimitNotice | null>(null);
  const conversationId = useRef<string | null>(null);
  const nextId = useRef(1);
  const abort = useRef<AbortController | null>(null);

  const refreshLimits = useCallback(async () => {
    if (!token) return;
    try {
      setLimits(await api.getLimits(token));
    } catch {
      // the counter is a nicety: never block the chat on it
    }
  }, [token]);

  const add = useCallback((message: Omit<ChatMessage, "id">) => {
    const id = nextId.current++;
    setMessages((all) => [...all, { ...message, id }]);
    return id;
  }, []);

  // Restore the conversation after a page refresh (history + a pending confirmation).
  useEffect(() => {
    if (!token) return;
    api
      .getLimits(token)
      .then(setLimits)
      .catch(() => {});
    const saved = readSession(CONVERSATION_KEY);
    if (!saved) return;
    api
      .getHistory(token, saved)
      .then((history) => {
        conversationId.current = saved;
        setMessages(
          history.messages.map((m) => ({
            id: nextId.current++,
            role: m.role,
            text: m.content,
            kind: "normal" as const,
          })),
        );
        setPending(history.pending);
      })
      .catch(() => writeSession(CONVERSATION_KEY, null)); // gone or not ours: start fresh
  }, [token]);

  useEffect(() => () => abort.current?.abort(), []);

  const run = useCallback(
    async (events: AsyncGenerator<ChatEvent>) => {
      let streamingId: number | null = null;
      const finishStreaming = (patch: Partial<ChatMessage>) =>
        setMessages((all) =>
          all.map((m) => (m.id === streamingId ? { ...m, streaming: false, ...patch } : m)),
        );
      try {
        for await (const event of events) {
          switch (event.type) {
            case "step":
              setStep(event.label);
              break;
            case "token":
              setStep(null);
              if (streamingId === null) {
                streamingId = add({
                  role: "assistant",
                  text: event.text,
                  kind: "normal",
                  streaming: true,
                });
              } else {
                const id = streamingId;
                setMessages((all) =>
                  all.map((m) => (m.id === id ? { ...m, text: m.text + event.text } : m)),
                );
              }
              break;
            case "confirmation":
              setStep(null);
              setPending(event.confirmation);
              break;
            case "message":
              setStep(null);
              if (streamingId === null) {
                add({
                  role: "assistant",
                  text: event.text,
                  kind: event.kind,
                  appointmentId: event.appointmentId,
                });
              } else {
                // the final text replaces the replayed chunks and carries how to present it
                finishStreaming({
                  text: event.text,
                  kind: event.kind,
                  appointmentId: event.appointmentId,
                });
              }
              break;
            case "done":
              conversationId.current = event.conversationId;
              writeSession(CONVERSATION_KEY, event.conversationId);
              break;
            case "error":
              add({ role: "assistant", text: event.message, kind: "normal", isError: true });
              break;
          }
        }
      } catch (error) {
        if ((error as Error).name === "AbortError") return;
        if (streamingId !== null) finishStreaming({});
        if (error instanceof api.ApiError) {
          if (error.isAuth) {
            signOut();
            return;
          }
          if (error.isDemoLimit) {
            setLimitNotice({ message: error.message, retryAfterSeconds: error.retryAfterSeconds });
            return;
          }
          add({ role: "assistant", text: error.message, kind: "normal", isError: true });
          return;
        }
        add({
          role: "assistant",
          text: "Something went wrong. Please try again.",
          kind: "normal",
          isError: true,
        });
      } finally {
        setStep(null);
        setBusy(false);
        void refreshLimits();
      }
    },
    [add, refreshLimits, signOut],
  );

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!token || !message || busy || pending) return;
      setBusy(true);
      setLimitNotice(null);
      add({ role: "user", text: message, kind: "normal" });
      abort.current = new AbortController();
      await run(api.sendMessage(token, message, conversationId.current, abort.current.signal));
    },
    [token, busy, pending, add, run],
  );

  const confirm = useCallback(
    async (confirmed: boolean) => {
      if (!token || !conversationId.current || busy) return;
      setBusy(true);
      setPending(null);
      abort.current = new AbortController();
      await run(api.resumeChat(token, conversationId.current, confirmed, abort.current.signal));
    },
    [token, busy, run],
  );

  const reset = useCallback(() => {
    abort.current?.abort();
    conversationId.current = null;
    writeSession(CONVERSATION_KEY, null);
    setMessages([]);
    setPending(null);
    setStep(null);
    setBusy(false);
  }, []);

  return { messages, step, pending, busy, limits, limitNotice, send, confirm, reset };
}
