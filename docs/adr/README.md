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
| [0008](0008-api-auth-streaming-and-demo-protection.md) | API: JWT auth, SSE streaming, per-user isolation, demo cost protection |
| [0009](0009-harmful-intent-guardrail-and-dose-guard.md) | Harmful-intent guardrail, router flag and dose guard |
| [0010](0010-public-holidays-per-city.md) | Public holidays per doctor's city |
| [0011](0011-frontend.md) | Frontend: custom stream reader, token storage, one user per tab |
| [0012](0012-langfuse-tracing-and-privacy.md) | Langfuse tracing with content redacted by default |
| [0013](0013-evaluation-harness-and-gates.md) | Evaluation harness: frozen golden sets, DB-state judging, exact safety gates |
| [0014](0014-rag-improvements.md) | RAG improvements measured against the frozen baseline (headers, reranker, ...) |
| [0015](0015-localised-fixed-texts.md) | Fixed medical-answer texts in German, chosen per turn |
| [0016](0016-german-safety-replies.md) | German emergency and harmful-intent replies, chosen by the rule that matched |
| [0017](0017-german-rule-inflections.md) | German emergency and harmful-intent rules: inflected forms |
| [0018](0018-safety-rule-vocabulary.md) | Safety rules: suicidal statements and other concepts the rules did not have |
| [0019](0019-informational-emergency-questions.md) | General questions about a red-flag topic are answered, not treated as an emergency |
| [0020](0020-red-team-evals-whole-bot.md) | Red-team evals on the whole bot, with a strict list of known gaps |
| [0021](0021-non-acute-self-harm.md) | Non-acute self-harm and passive ideation get a supportive reply |
| [0022](0022-dose-guard-units.md) | Dose guard: amounts per kilogram and per day, and grams |
| [0023](0023-align-self-harm-replies.md) | Habitual self-harm statements get the support reply, not the emergency reply |
| [0024](0024-passive-ideation-wake-up.md) | A wish not to wake up gets the support reply, never the refusal |
