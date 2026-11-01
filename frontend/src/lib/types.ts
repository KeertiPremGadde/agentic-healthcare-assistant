/** Shapes of the MedAgent API (see docs/adr/0008 and src/medagent/api/schemas.py). */

export type MessageKind =
  | "normal"
  | "booked"
  | "emergency"
  | "harmful_intent"
  | "self_harm_support";

export interface Confirmation {
  type: "confirm_booking" | "confirm_cancel";
  doctor: string;
  start: string;
  question: string;
}

export interface Doctor {
  id: number;
  name: string;
  specialty: string;
  city: string;
  languages: string[];
}

/** Details of the appointment the turn just booked (the time as shown in the clinic's timezone). */
export interface Booking {
  appointment_id: number;
  doctor: string;
  start: string;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  est_cost_usd: number;
}

export interface Appointment {
  id: number;
  doctor_id: number;
  doctor_name: string;
  start: string; // ISO 8601, UTC
  status: string;
}

export interface Limits {
  max_message_chars: number;
  daily_message_limit: number;
  messages_used_today: number;
  demo_notice: string;
}

export interface User {
  username: string;
  patient_id: number;
}

/** What the chat stream tells the UI, already decoded from SSE events. */
export type ChatEvent =
  | { type: "step"; node: string; label: string }
  | { type: "token"; text: string }
  | { type: "confirmation"; confirmation: Confirmation }
  | {
      type: "message";
      text: string;
      kind: MessageKind;
      appointmentId?: number;
      booking?: Booking;
      doctors?: Doctor[];
    }
  | { type: "done"; conversationId: string; pending: boolean; usage: Usage }
  | { type: "error"; code: string; message: string };
