"use client";

import { ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export function LoginForm() {
  const { token, ready, signIn, signUp } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("register");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && token) router.replace("/");
  }, [ready, token, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await (mode === "login" ? signIn : signUp)(username.trim(), password);
      router.replace("/");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  const register = mode === "register";
  return (
    <div className="flex flex-1 items-center justify-center py-8">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-lg">
            {register ? "Create a demo account" : "Welcome back"}
          </CardTitle>
          <CardDescription>
            {register
              ? "Pick any username. No email or real name is needed."
              : "Log in with your demo username."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                name="username"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                required
                minLength={3}
                maxLength={32}
                pattern="[a-zA-Z0-9_\-]{3,32}"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                aria-describedby={register ? "username-hint" : undefined}
                className="h-10 text-base sm:text-sm"
              />
              {register && (
                <p id="username-hint" className="text-muted-foreground text-xs">
                  3 to 32 letters, digits, &quot;_&quot; or &quot;-&quot;.
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                required
                minLength={register ? 10 : undefined}
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-describedby={register ? "password-hint" : undefined}
                className="h-10 text-base sm:text-sm"
              />
              {register && (
                <p id="password-hint" className="text-muted-foreground text-xs">
                  At least 10 characters. Stored only as a hash.
                </p>
              )}
            </div>
            {error && (
              <p
                role="alert"
                className="border-danger-border bg-danger text-danger-foreground rounded-lg border px-3 py-2 text-sm"
              >
                {error}
              </p>
            )}
            <Button type="submit" size="lg" disabled={busy} className="h-10 w-full">
              {busy ? "Please wait…" : register ? "Create account" : "Log in"}
            </Button>
          </form>
          <p className="text-muted-foreground mt-4 text-center text-sm">
            {register ? "Already have an account?" : "New here?"}{" "}
            <button
              type="button"
              onClick={() => {
                setMode(register ? "login" : "register");
                setError(null);
              }}
              className="text-primary focus-visible:ring-ring/50 rounded font-medium underline underline-offset-2 hover:no-underline focus-visible:ring-3 focus-visible:outline-none"
            >
              {register ? "Log in" : "Create an account"}
            </button>
          </p>
          <p className="bg-warn text-warn-foreground mt-5 flex gap-2 rounded-lg px-3 py-2 text-xs">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
            This is a demo with synthetic data. Do not enter real personal or health information.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
