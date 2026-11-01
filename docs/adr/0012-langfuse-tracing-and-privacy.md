# 0012 – Langfuse tracing with content redacted by default

Status: accepted (Phase 7)

## Context
To debug and evaluate an agent you need to see what a run did: which nodes ran, how long each took,
what each LLM call cost. This project has a hard rule, **no PII in logs or traces**, and its users
type health questions into a public demo. A tracing service is a third party, so what it receives
has to be decided deliberately.

## Decision

### 1. Langfuse Cloud (EU, free Hobby plan), optional
Langfuse (MIT, SDK 5.x, OpenTelemetry based) traces LangChain and LangGraph through a callback
handler. With no keys, `NullTracer` does nothing, like the calendar integration. `LANGFUSE_ENABLED`
switches it off without removing the keys. The Hobby plan has 30 days of data, 50k units a month
(traces, observations and scores each count) and **no HIPAA/BAA**: acceptable only because the demo
holds synthetic data and the traces carry no content (below).

### 2. One trace per turn, session = conversation, user = hash
A turn (a message, or the answer to a confirmation) is one trace named `medagent.turn`. The
Langfuse *session* is the conversation id, a random id with no user information. The user is
`pseudonymise(user.id)`, the same hash the logs use. The handler is created per turn and passed in
the run config by `stream_turn`, so the API, the dev CLI and the evals share one code path. The
route, the kind of reply and the estimated cost are attached as scores, so traces can be filtered
without reading any content. Sampling (`LANGFUSE_SAMPLE_RATE`) is decided once per turn in our
code, so a skipped turn sends neither spans nor scores.

### 3. Content is redacted before it leaves the process (two layers)
By default `LANGFUSE_CAPTURE_CONTENT=false`:

- **Layer 1, `mask`** (the SDK hook on input, output and metadata): `redact` keeps the structure and
  replaces every string with `[redacted: N chars]` and every number with `[redacted]`, except values
  under an allow-list of *shape* keys (route, node name, token counts, flags). It is default-deny:
  a new field is redacted until someone decides it is safe. It is idempotent and fail-closed (if the
  hook ever raised, the SDK would hide the data entirely).
- **Layer 2, `mask_otel_spans`** (an export-stage hook): scrubs the same attributes again just before
  export, **including the observation's status message**. This layer exists because of a leak found
  by reading the real traces back: the LangChain handler stores an exception's text as the status
  message, and LangGraph's pause for a confirmation is an exception whose text holds the proposal
  (doctor, time, question). `mask` never sees that field. The exception class name (`GraphInterrupt`)
  is kept, the text is not.
- **Only SDK spans are exported** (`should_export_span=is_langfuse_span`). The Anthropic SDK emits
  its own span per call: a duplicate of the LangChain generation (about 10% more units) and a
  second route into the trace that neither hook was designed for.

`LANGFUSE_CAPTURE_CONTENT=true` turns all of this off. It is for local development and for eval runs
over synthetic questions, never for the public demo.

### 4. How the guarantee is tested
Unit tests cover `redact`, the scrubber (including the exact interrupt text above), idempotence and
failure isolation. A mutation check (making `redact` keep strings) fails nine tests. And a real
conversation (answer, doctor search, booking with confirmation, emergency) was read back from
Langfuse: the message words, the username, the raw user id, the thread id and the doctor names are
all absent, while the hashed user, the session id, the node spans, the token usage and the scores
are present. That check is what found the leak in layer 2.

### 5. Tracing never breaks a turn
Every SDK call is guarded; a failure logs only the error type. The tracer is shut down (flushed)
when the API stops.

## Measured cost in units (free tier: 50k a month)
A real conversation on Haiku: 17 units for a medical answer, 18 for a doctor search, 19 for a
booking request, 9 for the confirmation (no LLM call), 8 for an emergency (rules only). That is
about 14 units per turn on average and 17 to 19 per LLM turn, so roughly 2,700 LLM turns a month
before the free tier is used up. The demo's own limits (50 messages per user per day, a daily
budget) stay below that, and `LANGFUSE_SAMPLE_RATE` is the lever if they don't. Eval runs are not
traced by default for the same reason.

## Not done / limits
- The MCP server runs in its own process; its tool calls are traced as tool spans from the client
  side, not from inside the server.
- Trace-level tags and the trace name could not be read back through the API (v5 exposes
  observations); check them once in the Langfuse UI.
- Langfuse model-price tables don't know Haiku 5.5 / Sonnet 5.5 by id in every case; the estimated
  cost from `observability/cost.py` is stored as a score and is the number we trust.
- Retention is 30 days on Hobby: results that matter live in the repository, not in Langfuse.

## Consequences
- Every graph run can be inspected in the UI, with no health text and no patient or doctor details
  in the third party's hands.
- New fields that appear in graph state are redacted by default; adding to `SAFE_KEYS` is a reviewed
  change, and a test forbids the obvious dangerous names.
