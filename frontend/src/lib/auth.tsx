"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import * as api from "./api";
import { CONVERSATION_KEY, readSession, TOKEN_KEY, writeSession } from "./session-storage";
import type { User } from "./types";

/**
 * Where the token lives (ADR 0011): in memory (this context) and in sessionStorage, so a page
 * refresh keeps you logged in but closing the tab logs you out. Not an httpOnly cookie: that
 * would need cookie auth, CSRF protection and credentialed CORS on the API. The token is short
 * lived, holds no personal data, and the app never renders untrusted HTML, which is what an
 * XSS attack would need.
 */

interface AuthState {
  token: string | null;
  user: User | null;
  /** false until the stored token (if any) has been checked against the API */
  ready: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signUp: (username: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

/** Token in, conversation out: a saved conversation belongs to whoever created it. */
function storeToken(token: string | null) {
  writeSession(TOKEN_KEY, token);
  writeSession(CONVERSATION_KEY, null);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const signOut = useCallback(() => {
    storeToken(null);
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    const stored = readSession(TOKEN_KEY);
    const check = stored
      ? api
          .getMe(stored)
          .then((me) => {
            setToken(stored);
            setUser(me);
          })
          .catch((error) => {
            // An expired or invalid token is dropped; on a network error nothing is kept either.
            if (error instanceof api.ApiError) storeToken(null);
          })
      : Promise.resolve();
    void check.finally(() => setReady(true));
  }, []);

  const signIn = useCallback(async (username: string, password: string) => {
    const { access_token } = await api.login(username, password);
    const me = await api.getMe(access_token);
    storeToken(access_token);
    setToken(access_token);
    setUser(me);
  }, []);

  const signUp = useCallback(
    async (username: string, password: string) => {
      await api.register(username, password);
      await signIn(username, password);
    },
    [signIn],
  );

  const value = useMemo(
    () => ({ token, user, ready, signIn, signUp, signOut }),
    [token, user, ready, signIn, signUp, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
