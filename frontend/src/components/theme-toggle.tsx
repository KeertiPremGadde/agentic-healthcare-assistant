"use client";

import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Light or dark: follows the system until the user picks one (stored per browser). */
export function ThemeToggle() {
  function toggle() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      // storage blocked: the choice just doesn't persist
    }
  }

  // Both icons are rendered; CSS shows the one for the current theme (no state, no flash).
  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle light and dark mode">
      <Sun aria-hidden className="hidden dark:block" />
      <Moon aria-hidden className="dark:hidden" />
    </Button>
  );
}

/** Runs before first paint (inline in <head>) so there is no flash of the wrong theme. */
export const THEME_INIT_SCRIPT = `try{var t=localStorage.getItem("theme");if(t==="dark"||(!t&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}`;
