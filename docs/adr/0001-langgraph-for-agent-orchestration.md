# ADR 0001 – LangGraph for agent orchestration

- **Status:** accepted
- **Date:** 2026-10-31

## Context
The legacy chatbot used `AgentExecutor`, `ConversationBufferMemory` and keyword / zero-shot intent
routing. These are deprecated or brittle, give no control over the flow, and cannot pause for
user confirmation before a side effect such as booking an appointment.

## Decision
Use **LangGraph**: an explicit `StateGraph` with a guardrail node, a supervisor that routes with
structured output, specialised sub-agents, `interrupt()` for human-in-the-loop confirmation and
a Postgres checkpointer for durable memory.

## Consequences
- Deterministic, testable control flow; each node is unit-testable with a fake LLM.
- Conversations survive restarts and HITL pauses.
- More code than a single ReAct agent; acceptable for a domain with safety requirements.
