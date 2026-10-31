# Architecture Decision Records

One file per significant decision: `NNNN-short-title.md` with Context, Decision, Consequences.

| # | Decision |
|---|---|
| [0001](0001-langgraph-for-agent-orchestration.md) | LangGraph for agent orchestration |
| [0002](0002-postgres-pgvector-single-datastore.md) | PostgreSQL + pgvector as the single datastore |
| [0003](0003-fastapi-sse-api.md) | FastAPI with SSE streaming |
| [0004](0004-utc-storage-and-slot-integrity.md) | UTC storage, clinic-local schedules, DB-enforced slot uniqueness |
| [0005](0005-rag-retrieval-and-corpus-licensing.md) | RAG: hybrid retrieval, local embeddings, corpus licensing (MedlinePlus yes, NHS no) |
| [0006](0006-agent-safety-layers-and-checkpointer.md) | Agent graph: rules-first emergency safety, HITL booking, library-owned checkpointer |
| [0007](0007-mcp-tools-calendar-and-osm.md) | Clinic tools behind MCP, async graph, optional calendar, OpenStreetMap lookups |
