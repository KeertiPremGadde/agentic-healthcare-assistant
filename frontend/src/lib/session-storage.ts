/**
 * sessionStorage that never throws (it can be blocked, e.g. in some private modes): the app
 * still works for the page view, it just can't remember across a refresh.
 * Everything here is cleared when the user logs out or a different user logs in.
 */
export const TOKEN_KEY = "medagent.token";
export const CONVERSATION_KEY = "medagent.conversation";

export function readSession(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeSession(key: string, value: string | null): void {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    // ignore
  }
}
