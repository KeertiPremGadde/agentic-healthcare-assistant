/**
 * A tiny stand-in for the MedAgent API, used by the Playwright smoke test and the screenshot
 * script. It speaks the real contract (docs/adr/0008): JWT-style bearer auth, SSE events with
 * live `step` events, a confirmation that is answered through /resume, error envelopes, CORS.
 * It makes no model calls, so the tests are free and deterministic. The replies are canned and
 * chosen by simple keywords: this is a test double, not part of the product.
 */
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

const PORT = Number(process.env.MOCK_API_PORT ?? 8765);
const START = "2030-03-04T08:00:00+00:00";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const EMERGENCY =
    "This could be a medical emergency. Call your local emergency number now (112 in the EU, 911 in the US) or go to the nearest emergency room. Don't wait for an online answer.";
const HARMFUL =
    "I can't help with that, but I'm concerned about you and I'm glad you reached out.\n\nIf you're thinking about ending your life, or you might hurt someone, please talk to someone now:\n- Germany: TelefonSeelsorge 0800 111 0 111 (free, 24/7)\n- Emergency: 112 (EU) or 911 (US), or 988 in the US\n- Poison control, if someone may have swallowed something harmful";
const MIGRAINE =
    "Migraines are recurring headaches, often with throbbing pain on one side, nausea and sensitivity to light and sound. Triggers vary: stress, lack of sleep, skipped meals, hormonal changes and some foods are common ones.\n\nSources:\n- MedlinePlus: Migraine <https://medlineplus.gov/migraine.html>\n- MedlinePlus: Headache <https://medlineplus.gov/headache.html>\n\nContent: MedlinePlus, National Library of Medicine (public domain)\n\nThis is general health information from the sources listed above, not medical advice or a diagnosis. Please consult a qualified healthcare professional. In an emergency, call your local emergency number (112 in the EU, 911 in the US).";
const DOCTORS =
    'For a skin rash a dermatologist is the right specialist. Here are some options:\n\n1. Dr. Anna Schmidt, Dermatology, Berlin (German, English)\n2. Dr. Jonas Weber, Dermatology, München (German, English)\n\nSay "book number 1" to pick a time.';
const HOSPITALS =
    "Hospitals near Berlin (from OpenStreetMap, not bookable here):\n- Charité Campus Mitte\n- Vivantes Klinikum im Friedrichshain";

// Like the real API, conversations belong to the user who created them.
let who = "";
const key = (id) => `${who}:${id}`;

const state = { users: new Map(), appointments: [], conversations: new Map(), nextId: 1 };

function cors(res, req) {
    res.setHeader("Access-Control-Allow-Origin", req.headers.origin ?? "*");
    res.setHeader("Access-Control-Allow-Headers", "authorization,content-type");
    res.setHeader("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS");
    res.setHeader("Access-Control-Expose-Headers", "Retry-After,X-Request-ID");
    res.setHeader("X-Request-ID", randomUUID().replaceAll("-", ""));
}

function sendJson(res, req, status, body, headers = {}) {
    cors(res, req);
    res.writeHead(status, { "Content-Type": "application/json", ...headers });
    res.end(body === undefined ? undefined : JSON.stringify(body));
}

const error = (res, req, status, code, message, headers) =>
    sendJson(res, req, status, { error: { code, message, request_id: "mock" } }, headers);

async function readBody(req) {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    return Buffer.concat(chunks).toString("utf8");
}

const event = (res, name, data) => res.write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
const USAGE = { input_tokens: 1200, output_tokens: 150, est_cost_usd: 0.0004 };

async function replayTokens(res, text) {
    for (const chunk of text.match(/\S+\s*/g) ?? []) {
        event(res, "token", { text: chunk });
        await sleep(15);
    }
}

async function finish(res, id, text, kind = "normal", extra = {}) {
    await replayTokens(res, text);
    event(res, "message", { text, kind, ...extra });
    event(res, "done", { conversation_id: id, pending: false, usage: USAGE });
    res.end();
}

function sseStart(res, req) {
    cors(res, req);
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-store" });
}

function remember(id, role, content) {
    const conversation = state.conversations.get(key(id)) ?? { messages: [], pending: null };
    conversation.messages.push({ role, content });
    state.conversations.set(key(id), conversation);
    return conversation;
}

async function chat(req, res) {
    const { message, conversation_id: given } = JSON.parse(await readBody(req));
    const id = given ?? randomUUID().replaceAll("-", "");
    const text = String(message).toLowerCase();
    if (text.includes("limit")) {
        return error(
            res,
            req,
            429,
            "demo_limit_reached",
            "You've reached today's message limit for this demo. Come back tomorrow.",
            { "Retry-After": "7200" },
        );
    }
    remember(id, "user", message);
    sseStart(res, req);

    if (text.includes("chest pain")) return finish(res, id, EMERGENCY, "emergency");
    if (text.includes("kill")) return finish(res, id, HARMFUL, "harmful_intent");

    event(res, "step", { node: "supervisor", label: "Understanding your request…" });
    await sleep(500);
    if (text.includes("book")) {
        event(res, "step", { node: "booking", label: "Checking availability…" });
        await sleep(500);
        const pending = {
            type: "confirm_booking",
            doctor: "Dr. Anna Schmidt",
            start: "Mon 4 Mar 2030, 09:00",
            question: "Shall I book Mon 4 Mar 2030, 09:00 with Dr. Anna Schmidt?",
        };
        remember(id, "assistant", "(waiting for confirmation)").pending = pending;
        event(res, "confirmation", pending);
        event(res, "done", { conversation_id: id, pending: true, usage: USAGE });
        return res.end();
    }
    if (text.includes("rash")) {
        event(res, "step", { node: "doctor_finder", label: "Looking for suitable doctors…" });
        await sleep(500);
        remember(id, "assistant", DOCTORS);
        return finish(res, id, DOCTORS);
    }
    if (text.includes("migraine")) {
        event(res, "step", { node: "medical_rag", label: "Searching the knowledge base…" });
        await sleep(500);
        remember(id, "assistant", MIGRAINE);
        return finish(res, id, MIGRAINE);
    }
    if (text.includes("hospital")) {
        event(res, "step", {
            node: "nearby_clinics",
            label: "Looking up clinics on OpenStreetMap…",
        });
        await sleep(500);
        remember(id, "assistant", HOSPITALS);
        return finish(res, id, HOSPITALS);
    }
    const hello =
        "Hello! I'm MedAgent. I can answer health questions, find doctors and book appointments.";
    remember(id, "assistant", hello);
    return finish(res, id, hello);
}

async function resume(req, res, id) {
    const { confirmed } = JSON.parse(await readBody(req));
    const conversation = state.conversations.get(key(id));
    if (!conversation) return error(res, req, 404, "not_found", "Conversation not found.");
    if (!conversation.pending)
        return error(
            res,
            req,
            409,
            "nothing_to_confirm",
            "This conversation isn't waiting for an answer.",
        );
    conversation.pending = null;
    sseStart(res, req);
    if (!confirmed) return finish(res, id, "No problem. Which other day or time would suit you?");
    event(res, "step", { node: "book_appointment", label: "Booking your appointment…" });
    await sleep(400);
    const appointment = {
        id: state.nextId++,
        doctor_id: 1,
        doctor_name: "Dr. Anna Schmidt",
        start: START,
        status: "booked",
    };
    state.appointments.push(appointment);
    const code = `#A-${String(appointment.id).padStart(4, "0")}`;
    const text = `Booked: Dr. Anna Schmidt, Mon 4 Mar 2030, 09:00 (Europe/Berlin). Confirmation ${code}.`;
    return finish(res, id, text, "booked", { appointment_id: appointment.id });
}

const server = createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://localhost:${PORT}`);
    const path = url.pathname;
    try {
        if (req.method === "OPTIONS") {
            cors(res, req);
            res.writeHead(204);
            return res.end();
        }
        if (path === "/__reset") {
            state.users.clear();
            state.appointments.length = 0;
            state.conversations.clear();
            state.nextId = 1;
            return sendJson(res, req, 200, { ok: true });
        }
        if (path === "/v1/auth/register" && req.method === "POST") {
            const { username } = JSON.parse(await readBody(req));
            if (state.users.has(username))
                return error(
                    res,
                    req,
                    409,
                    "username_taken",
                    "That username is taken. Pick another.",
                );
            state.users.set(username, { patient_id: state.users.size + 1 });
            return sendJson(res, req, 201, {
                username,
                patient_id: state.users.get(username).patient_id,
            });
        }
        if (path === "/v1/auth/login" && req.method === "POST") {
            const form = new URLSearchParams(await readBody(req));
            const username = form.get("username") ?? "";
            if (!state.users.has(username) || form.get("password") === "wrong-password") {
                return error(res, req, 401, "invalid_credentials", "Wrong username or password.", {
                    "WWW-Authenticate": "Bearer",
                });
            }
            return sendJson(res, req, 200, {
                access_token: `tok-${username}`,
                token_type: "bearer",
                expires_in: 3600,
            });
        }

        // Everything below needs a bearer token.
        const token = (req.headers.authorization ?? "").replace(/^Bearer /, "");
        const username = token.startsWith("tok-") ? token.slice(4) : null;
        if (!username || !state.users.has(username)) {
            return error(res, req, 401, "not_authenticated", "Please log in.", {
                "WWW-Authenticate": "Bearer",
            });
        }
        who = username;
        if (path === "/v1/auth/me")
            return sendJson(res, req, 200, {
                username,
                patient_id: state.users.get(username).patient_id,
            });
        if (path === "/v1/limits") {
            return sendJson(res, req, 200, {
                max_message_chars: 1000,
                daily_message_limit: 50,
                messages_used_today: state.conversations.size,
                demo_notice: "Demo with synthetic data.",
            });
        }
        if (path === "/v1/chat" && req.method === "POST") return await chat(req, res);
        const resumeMatch = /^\/v1\/chat\/([0-9a-f]{32})\/resume$/.exec(path);
        if (resumeMatch && req.method === "POST") return await resume(req, res, resumeMatch[1]);
        const historyMatch = /^\/v1\/chat\/([0-9a-f]{32})$/.exec(path);
        if (historyMatch && req.method === "GET") {
            const conversation = state.conversations.get(key(historyMatch[1]));
            if (!conversation) return error(res, req, 404, "not_found", "Conversation not found.");
            return sendJson(res, req, 200, {
                conversation_id: historyMatch[1],
                messages: conversation.messages.filter(
                    (m) => m.content !== "(waiting for confirmation)",
                ),
                pending: conversation.pending,
            });
        }
        if (path === "/v1/appointments" && req.method === "GET") {
            return sendJson(
                res,
                req,
                200,
                state.appointments.filter((a) => a.status === "booked"),
            );
        }
        const cancelMatch = /^\/v1\/appointments\/(\d+)$/.exec(path);
        if (cancelMatch && req.method === "DELETE") {
            const found = state.appointments.find((a) => a.id === Number(cancelMatch[1]));
            if (!found) return error(res, req, 404, "not_found", "Appointment not found.");
            found.status = "cancelled";
            return sendJson(res, req, 204, undefined);
        }
        return error(res, req, 404, "not_found", "Not found.");
    } catch (e) {
        console.error(e);
        if (!res.headersSent)
            error(res, req, 500, "internal_error", "Something went wrong on our side.");
        else res.end();
    }
});

server.listen(PORT, () => console.log(`mock MedAgent API on http://localhost:${PORT}`));
