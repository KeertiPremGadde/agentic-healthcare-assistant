"use client";

import { Fragment } from "react";
import { useAuth } from "@/lib/auth";

/**
 * Remounts everything below it when the user changes (login, logout, expired session).
 *
 * Next.js keeps the component state of routes you navigated away from, so without this the chat
 * and appointment list of the previous user would still be in memory for the next one who logs in
 * on the same browser tab.
 */
export function UserScope({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  return <Fragment key={token ?? "signed-out"}>{children}</Fragment>;
}
