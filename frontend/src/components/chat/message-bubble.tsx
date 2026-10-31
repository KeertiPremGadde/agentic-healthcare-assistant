"use client";

import {
  CalendarPlus,
  CircleCheck,
  HeartHandshake,
  Info,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { parseReply } from "@/lib/citations";
import { downloadIcs } from "@/lib/ics";
import type { ChatMessage } from "@/lib/use-chat";
import { cn } from "@/lib/utils";

export function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="bg-primary text-primary-foreground max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
          {message.text}
        </p>
      </div>
    );
  }
  if (message.isError)
    return (
      <Notice tone="danger" icon={TriangleAlert} title="Something went wrong" text={message.text} />
    );
  if (message.kind === "emergency") return <EmergencyCard text={message.text} />;
  if (message.kind === "harmful_intent") return <CrisisCard text={message.text} />;
  if (message.kind === "booked") return <BookedCard message={message} />;
  return <AssistantBubble message={message} />;
}

function AssistantBubble({ message }: { message: ChatMessage }) {
  const { body, sources, attributions, disclaimer } = parseReply(message.text);
  return (
    <div className="flex">
      <div className="bg-card max-w-[92%] rounded-2xl rounded-bl-md border px-4 py-3 text-sm leading-relaxed shadow-xs">
        <p className="whitespace-pre-wrap">{body || (message.streaming ? "…" : "")}</p>
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
    </div>
  );
}

function Notice({
  tone,
  icon: Icon,
  title,
  text,
  children,
}: {
  tone: "danger" | "care" | "success";
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  title: string;
  text: string;
  children?: React.ReactNode;
}) {
  const styles = {
    danger: "border-danger-border bg-danger text-danger-foreground",
    care: "border-care-border bg-care text-care-foreground",
    success: "border-success-border bg-success text-success-foreground",
  }[tone];
  return (
    <div className={cn("max-w-[92%] rounded-2xl rounded-bl-md border px-4 py-3 text-sm", styles)}>
      <p className="flex items-center gap-2 font-semibold">
        <Icon className="size-5 shrink-0" aria-hidden />
        {title}
      </p>
      <p className="mt-1.5 leading-relaxed whitespace-pre-wrap">{text}</p>
      {children}
    </div>
  );
}

/** Acute emergency: the one place red is used. role=alert so screen readers announce it. */
function EmergencyCard({ text }: { text: string }) {
  return (
    <div role="alert" className="flex">
      <Notice tone="danger" icon={ShieldAlert} title="This may be an emergency" text={text} />
    </div>
  );
}

/** Self-harm or harm to others: calm and supportive, not an alarm. Shows the fixed helplines. */
function CrisisCard({ text }: { text: string }) {
  return (
    <div role="alert" className="flex">
      <Notice tone="care" icon={HeartHandshake} title="You are not alone" text={text} />
    </div>
  );
}

function BookedCard({ message }: { message: ChatMessage }) {
  const { token } = useAuth();
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");

  async function addToCalendar() {
    if (!token || message.appointmentId === undefined) return;
    setState("loading");
    try {
      // The file is built in the browser from the appointment record (doctor and time only).
      const all = await api.getAppointments(token);
      const found = all.find((a) => a.id === message.appointmentId);
      if (!found) throw new Error("not found");
      downloadIcs({ id: found.id, doctorName: found.doctor_name, start: found.start });
      setState("idle");
    } catch {
      setState("error");
    }
  }

  return (
    <div className="flex">
      <Notice tone="success" icon={CircleCheck} title="Appointment booked" text={message.text}>
        {message.appointmentId !== undefined && (
          <div className="mt-3">
            <Button
              variant="outline"
              size="lg"
              onClick={addToCalendar}
              disabled={state === "loading"}
            >
              <CalendarPlus aria-hidden />
              Add to calendar
            </Button>
            {state === "error" && (
              <p role="status" className="mt-2 text-xs">
                Couldn&apos;t create the calendar file. Please try again.
              </p>
            )}
          </div>
        )}
      </Notice>
    </div>
  );
}
