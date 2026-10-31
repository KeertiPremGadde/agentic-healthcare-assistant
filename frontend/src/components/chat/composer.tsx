"use client";

import { SendHorizontal } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { Limits } from "@/lib/types";

export function Composer({
  limits,
  disabled,
  placeholder,
  onSend,
}: {
  limits: Limits | null;
  disabled: boolean;
  placeholder: string;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const max = limits?.max_message_chars ?? 1000;
  const left = limits ? Math.max(limits.daily_message_limit - limits.messages_used_today, 0) : null;

  function submit() {
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value);
    setText("");
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="bg-background/95 sticky bottom-0 -mx-4 border-t px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur"
    >
      <label htmlFor="message" className="sr-only">
        Your message
      </label>
      <div className="flex items-end gap-2">
        <Textarea
          id="message"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
          maxLength={max}
          rows={1}
          placeholder={placeholder}
          className="bg-card max-h-40 min-h-11 resize-none rounded-xl px-3.5 py-2.5 text-base sm:text-sm"
        />
        <Button
          type="submit"
          size="icon"
          disabled={disabled || !text.trim()}
          aria-label="Send message"
          className="size-11 rounded-xl"
        >
          <SendHorizontal aria-hidden />
        </Button>
      </div>
      <p className="text-muted-foreground mt-1.5 flex justify-between text-xs">
        <span>Enter to send, Shift+Enter for a new line</span>
        <span aria-live="polite">
          {text.length > max * 0.8 && `${text.length}/${max} · `}
          {left !== null && `${left} messages left today`}
        </span>
      </p>
    </form>
  );
}
