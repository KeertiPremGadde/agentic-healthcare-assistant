import { readSse } from "./sse";
import type {
  Appointment,
  ChatEvent,
  Booking,
  Confirmation,
  Doctor,
  Limits,
  MessageKind,
  Usage,
  User,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

/** An error from the API (its `{error: {code, message}}` envelope) or from the network. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
  }

  get isAuth(): boolean {
    return this.status === 401;
  }

  /** The demo's daily message limit or global budget (HTTP 429/503, code `demo_limit_reached`). */
  get isDemoLimit(): boolean {
    return this.code === "demo_limit_reached";
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `The server answered ${response.status}.`;
  try {
    const body = await response.json();
    if (body?.error?.message) {
      code = body.error.code ?? code;
      message = body.error.message;
    }
  } catch {
    // not JSON: keep the generic message
  }
  const retry = Number(response.headers.get("Retry-After"));
  return new ApiError(response.status, code, message, retry > 0 ? retry : undefined);
}

async function request(path: string, init: RequestInit & { token?: string } = {}) {
  const { token, ...rest } = init;
  const headers = new Headers(rest.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...rest, headers });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(0, "network_error", "Can't reach the server. Is the API running?");
  }
  if (!response.ok) throw await toApiError(response);
  return response;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export async function register(username: string, password: string): Promise<User> {
  return (await request("/v1/auth/register", json({ username, password }))).json();
}

export async function login(
  username: string,
  password: string,
): Promise<{ access_token: string; expires_in: number }> {
  // OAuth2 password flow: a form, not JSON.
  const body = new URLSearchParams({ username, password });
  return (await request("/v1/auth/login", { method: "POST", body })).json();
}

export async function getMe(token: string): Promise<User> {
  return (await request("/v1/auth/me", { token })).json();
}

export async function getLimits(token: string): Promise<Limits> {
  return (await request("/v1/limits", { token })).json();
}

export async function getAppointments(token: string): Promise<Appointment[]> {
  return (await request("/v1/appointments", { token })).json();
}

export async function cancelAppointment(token: string, id: number): Promise<void> {
  await request(`/v1/appointments/${id}`, { method: "DELETE", token });
}

/** Turn one SSE event into a typed ChatEvent (unknown events are ignored). */
export function decodeEvent(event: string, raw: string): ChatEvent | null {
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  switch (event) {
    case "step":
      return { type: "step", node: String(data.node), label: String(data.label) };
    case "token":
      return { type: "token", text: String(data.text) };
    case "confirmation":
      return { type: "confirmation", confirmation: data as unknown as Confirmation };
    case "message":
      return {
        type: "message",
        text: String(data.text),
        kind: (data.kind as MessageKind | undefined) ?? "normal",
        appointmentId: typeof data.appointment_id === "number" ? data.appointment_id : undefined,
        booking: (data.booking as Booking | undefined) ?? undefined,
        doctors: Array.isArray(data.doctors) ? (data.doctors as Doctor[]) : undefined,
      };
    case "done":
      return {
        type: "done",
        conversationId: String(data.conversation_id),
        pending: Boolean(data.pending),
        usage: data.usage as Usage,
      };
    case "error":
      return { type: "error", code: String(data.code), message: String(data.message) };
    default:
      return null;
  }
}

async function* stream(path: string, init: RequestInit & { token: string }, signal?: AbortSignal) {
  const response = await request(path, { ...init, signal });
  for await (const { event, data } of readSse(response)) {
    const decoded = decodeEvent(event, data);
    if (decoded) yield decoded;
  }
}

export function sendMessage(
  token: string,
  message: string,
  conversationId: string | null,
  signal?: AbortSignal,
) {
  const body = conversationId ? { message, conversation_id: conversationId } : { message };
  return stream("/v1/chat", { ...json(body), token }, signal);
}

export function resumeChat(
  token: string,
  conversationId: string,
  confirmed: boolean,
  signal?: AbortSignal,
) {
  return stream(`/v1/chat/${conversationId}/resume`, { ...json({ confirmed }), token }, signal);
}

export interface History {
  conversation_id: string;
  messages: { role: "user" | "assistant"; content: string }[];
  pending: Confirmation | null;
}

export async function getHistory(token: string, conversationId: string): Promise<History> {
  return (await request(`/v1/chat/${conversationId}`, { token })).json();
}
