# Phase 7 (quality: observability and evaluation): interview Q&A

Sections are added as the phase's pull requests land. Decisions: [ADR 0012](../adr/0012-langfuse-tracing-and-privacy.md).

---

## Tracing

### What is a trace, a span, a generation, a session?
A **trace** is one end-to-end run (here: one turn). **Spans** (Langfuse calls them observations) are
the steps inside it: each graph node, each tool call. A **generation** is an LLM call, with model,
tokens and cost. A **session** groups traces: here, one conversation. The graph's nodes show up as
nested spans automatically, because LangGraph reports them through LangChain's callback system and
Langfuse's handler listens to it.

### How does it plug in?
One callback handler per turn, passed in the run config by `stream_turn`. The API, the dev CLI and
the evals all go through that function, so there is one place that knows about tracing. With no keys
it's a no-op object, like the calendar. Any failure in the SDK is caught and logged by type, so
tracing can't break a conversation.

### A medical chatbot sends data to a third party. How do you keep health text out?
By default nothing with content leaves the process. A redaction function replaces every string with
`[redacted: N chars]` and every number with `[redacted]`, except values under a short allow-list of
*shape* keys (route, node name, token counts, flags). It is default-deny: a new field in the state is
redacted until a person decides it is safe, and a test forbids obvious names on the list. What
remains is enough to debug with: structure, timings, token counts, route, cost.

### How did you know it worked?
Unit tests, a mutation check (make the function keep strings: nine tests fail), and, the one that
mattered, I ran a real conversation and read the traces back from Langfuse looking for the message
words, the username, the raw user id, the thread id and the doctor's name.

### What did that find?
A leak the first layer cannot see. The `mask` hook covers input, output and metadata, but the
LangChain handler also stores an exception's text as the observation's status message, and LangGraph
implements "pause and ask for confirmation" as an exception whose text contains the proposal: doctor,
time, question. So there is a second layer, an export-stage hook that scrubs the same attributes
(and the status message) just before sending. It keeps the exception's class name, which holds no
content.

### And the check itself had a hole?
Yes: I filtered by session id, and child spans created by the Anthropic SDK's own instrumentation
carry no session id, so my first leak check skipped them. They held no content, but they were a
second route into the trace that the redaction wasn't designed for, and a duplicate of each LLM call.
I re-read by trace id and restricted the export to spans the Langfuse SDK created itself.

### How is the user identified?
Not at all, in the clear: the user id is the same one-way hash the logs use, the session id is the
random conversation id, and the thread id (which contains the raw user id) is redacted.

### What does it cost on the free tier?
Langfuse counts traces, observations and scores as units: 50,000 a month on the free plan. Measured on
a real conversation: 17 to 19 units for a turn with an LLM call, 8 to 9 without. About 2,700 LLM turns
a month. Sampling is the lever; it is decided once per turn so a skipped turn sends no scores either.

### What would you do differently with real patient data?
Self-host Langfuse or use a plan with a BAA, keep content capture off, shorten retention, and treat the
trace store as part of the system's data protection scope. On the free plan, synthetic data and
metadata-only traces are the only defensible setup, and the ADR says so.
