# ADR 0003 – FastAPI with SSE streaming

- **Status:** accepted
- **Date:** 2026-10-31

## Context
The legacy app used synchronous Flask with server-rendered templates. Agent responses need token
streaming, tool-progress events and a separate resume call for human-in-the-loop steps.

## Decision
Use **FastAPI** (async, Pydantic v2, OpenAPI out of the box) with **Server-Sent Events** for
streaming. The frontend is a separate Next.js app.

## Consequences
- Typed request/response contracts shared with the agent layer.
- Backend and frontend deploy independently.
