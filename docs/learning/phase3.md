# Phase 3 – Multi-agent graph: interview Q&A

What we built: a LangGraph state machine that screens every message for emergencies, routes it with
one structured-output call, answers medical questions (Phase 2 RAG), recommends a specialist, and
books appointments only after an explicit human confirmation, with conversations persisted in
Postgres. Code: `src/medagent/agents/`, `src/medagent/guardrails/`. Decisions: [ADR 0006](../adr/0006-agent-safety-layers-and-checkpointer.md).
Diagram: [ARCHITECTURE](../ARCHITECTURE.md#2-agent-graph-langgraph), generated: [agent_graph.md](../diagrams/agent_graph.md).

---

### Why LangGraph instead of a single agent loop?
A booking flow is a *process*, not an open-ended task: screen → classify → act → confirm → write.
LangGraph makes that process explicit as a graph of small functions over a typed state, which gives
me control (the LLM classifies, code decides), testability (each node is a function), persistence
(checkpoints after every step) and pause/resume (`interrupt()`), which a free-running tool loop does
not give out of the box.

### Explain the core LangGraph concepts you used.
- **StateGraph + typed state:** nodes read `AgentState` and return partial updates.
- **Reducer:** `messages` uses `add_messages`, so nodes return *new* messages and they are appended;
  other keys are overwritten by the latest update.
- **Edges / conditional edges:** `after_guardrail` and `after_supervisor` pick the next node from state.
- **`Command(goto=..., update=...)`:** a node both updates state and chooses where to go (booking →
  confirm or output_guard). Gotcha I hit: a node without a static outgoing edge must *always* return
  a `Command`, otherwise the graph silently ends and the user gets no reply (`destinations=` only
  affects the diagram). Tests caught it.
- **Checkpointer + `thread_id`:** state is saved after every super-step, per conversation.
- **`interrupt()` / `Command(resume=...)`:** pause mid-node, hand a payload to the caller, continue
  later with the human's answer.

### How does human-in-the-loop confirmation work, and what's the main pitfall?
`booking` finds a valid free slot and stores a proposal; `confirm` calls `interrupt({question...})`;
the graph stops and the state is checkpointed. The caller shows "Shall I book Mon 2 Nov, 13:00 with
Dr. Johnson?" and later calls `invoke(Command(resume=True))`. **Pitfall:** on resume LangGraph re-runs
the interrupted node *from its first line*. Anything before `interrupt()` runs twice. So `confirm`
has no side effects; the insert is in `book_appointment`, which re-validates (the user may confirm an
hour later) and relies on the database's unique index for races. A lost slot loops back to `confirm`
with the next free slot (a fresh interrupt), not a free-text "shall I book that?".

### How does memory survive a restart? How did you prove it?
`PostgresSaver` writes a checkpoint per super-step keyed by `thread_id`, including a pending interrupt.
A new process with the same `thread_id` loads it. Proof: an integration test runs to the confirmation
with one checkpointer connection, deletes graph and connection, builds new ones, sees the pending
interrupt and the message history, resumes, and the appointment exists. I also did it with the real
CLI in two separate processes. The LLM only sees the last 10 messages; the checkpoint keeps everything.

### Why deterministic emergency rules if you have an LLM?
Safety must not depend on an API call. Rules run first: free, instant, testable, immune to prompt
injection, and they work when the LLM is down. The router's `is_emergency` flag is the second layer for
phrasings the rules miss. English plus common German phrasings (clinic in Germany), NFC-normalised so
"Lähmung" matches however the umlaut was typed. Tuned for recall: a false alarm costs one message.

### Didn't that break "What are the warning signs of a stroke?"
It would have, and I noticed before testing: health education about emergencies is core to the
product. A red flag in a *general question with no person involved* (starts with what/how/why..., no
I/my/he/she/someone) is answered normally with a safety notice in front; "I have chest pain" or "my dad
can't breathe" short-circuits. Tested both ways, in both languages. Known limitation: negation ("no
chest pain") still triggers; acceptable for recall.

### Why structured output everywhere, and why `json_schema`?
Project rule: the LLM fills Pydantic schemas (`RouteDecision`, `DoctorQuery` with a `Specialty` enum,
`BookingRequest`); code never string-matches model text. The legacy project asked for a specialty name
and string-compared it. LangChain's default structured-output method forces a tool call, which Claude
Sonnet 5.5 (the demo model) rejects, so I use `method="json_schema"` (native structured outputs); it
works on both Haiku and Sonnet.

### Can the model book for the wrong person?
No. The patient id comes from the run config (CLI `--patient` now, JWT in Phase 5), never from the
conversation. Prompt injection like "book this for patient 7" has nothing to act on. Without a patient
in config, booking is refused. Tested.

### What does a turn cost, and how do you know?
Every run logs input/output tokens, estimated USD and latency as one JSON line, with pseudonymised
thread/patient ids and no message text (a test asserts the user's text and raw ids never appear).
Measured on Claude Haiku 5.5: finding a doctor ~1.5k in / 46 out tokens ≈ $0.00017; a booking turn
~2.2k / 69 ≈ $0.00026; a cited medical answer ~3.5k / 257 ≈ $0.0005; confirming is free (no LLM call).
My plan estimate was ~10x higher because I assumed ~800 output tokens per call; at `effort="low"` Haiku
barely thinks on these short tasks. Lesson: measure, then budget.

### Why `effort="low"` and what else matters for Haiku 5.5?
Thinking is on by default on Haiku 5.5 and is billed as output, so effort is the cost/latency control.
Classification and extraction don't need deep reasoning; RAG answers use medium. `temperature` is no
longer accepted by the API, and `max_tokens` must leave room for thinking (I raised RAG's from 1024).

### What real bugs did the tests and real runs find?
- Booking returned plain updates with no outgoing edge → no reply (wiring bug, now always `Command`).
- After a lost race the code offered 08:00 although the user asked for the afternoon → search now
  starts *after* the lost slot.
- A broad `except` turned a programming error into a polite apology → nodes now log the error type.
- **Alembic autogenerate would have dropped LangGraph's checkpoint tables** (every conversation) →
  `include_name` filter in `migrations/env.py` plus an `alembic check` regression test.
- `.replace("  ", " ")` string hacks and a "Dr." name that searched for nothing → cleaned up, tested.

### How do you test an LLM agent without paying for every test run?
A `FakeStructuredLLM` returns scripted outputs per schema and *fails the test on any unscripted call*,
which is how I prove emergencies never reach the LLM. Offline: 134 tests (routing, safety layers,
output rules, booking happy path / no / past date / invalid time / missing patient / lost race,
restart-and-resume against real Postgres). `pytest -m llm` runs 11 real Haiku calls (router, specialty
enum, relative-date extraction, a full find-book-confirm conversation) for about a cent.

### What would you do next?
Query rewriting for follow-up questions ("what about type 2?") before RAG; cancellation and
rescheduling; streaming tokens and node events to the UI (Phase 5); Langfuse traces per run (Phase 7);
an eval set for routing accuracy; negation handling and more languages in the red-flag rules.
