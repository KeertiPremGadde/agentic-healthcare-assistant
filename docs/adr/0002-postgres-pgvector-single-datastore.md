# ADR 0002 – PostgreSQL + pgvector as the single datastore

- **Status:** accepted
- **Date:** 2026-10-31

## Context
The legacy app used SQLite for appointments and Pinecone for vectors: two systems, no migrations,
and SQLite cannot run in a multi-instance deployment.

## Decision
Use **PostgreSQL 16 with pgvector** for relational data, vector embeddings, full-text search
(hybrid retrieval) and LangGraph checkpoints. Schema managed by **Alembic**.

## Consequences
- One service to run locally (docker-compose) and in AWS (RDS).
- Transactions + a unique constraint prevent double-booking.
- Pinecone remains a drop-in option behind the retriever interface if scale demands it.
