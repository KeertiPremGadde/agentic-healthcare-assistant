"use client";

import { CalendarDays, HeartPulse, LogOut, MessageCircle } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function AppHeader() {
  const { user, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  function logout() {
    signOut();
    router.push("/login");
  }

  const link = (href: string, label: string, icon: React.ReactNode) => (
    <Link
      href={href}
      aria-current={pathname === href ? "page" : undefined}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium transition-colors",
        "hover:bg-accent focus-visible:ring-ring/50 focus-visible:ring-3 focus-visible:outline-none",
        pathname === href ? "bg-accent text-accent-foreground" : "text-muted-foreground",
      )}
    >
      {icon}
      <span className="sr-only sm:not-sr-only">{label}</span>
    </Link>
  );

  return (
    <header className="bg-card border-b">
      <div className="mx-auto flex h-14 max-w-3xl items-center gap-2 px-4">
        <Link
          href="/"
          className="focus-visible:ring-ring/50 mr-auto flex items-center gap-2 rounded-lg font-semibold focus-visible:ring-3 focus-visible:outline-none"
        >
          <span className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-lg">
            <HeartPulse className="size-5" aria-hidden />
          </span>
          MedAgent
        </Link>
        {user && (
          <nav aria-label="Main" className="flex items-center gap-1">
            {link("/", "Chat", <MessageCircle className="size-4" aria-hidden />)}
            {link(
              "/appointments",
              "My appointments",
              <CalendarDays className="size-4" aria-hidden />,
            )}
            <span className="text-muted-foreground ml-2 hidden max-w-32 truncate text-sm sm:inline">
              {user.username}
            </span>
            <Button variant="ghost" size="icon" onClick={logout} aria-label="Log out">
              <LogOut aria-hidden />
            </Button>
          </nav>
        )}
        <ThemeToggle />
      </div>
    </header>
  );
}
