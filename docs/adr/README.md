# Architecture Decision Records

One file per significant decision: `NNNN-short-title.md` with Context, Decision, Consequences.

The project was built in stages, and some records mention them: 1 data layer, 2 RAG, 3 agent graph,
4 MCP tools, 5 API, 6 frontend, 7 evaluations and safety hardening, 8 deployment (not done yet).

| # | Decision |
|---|---|
| [0001](0001-langgraph-for-agent-orchestration.md) | LangGraph for agent orchestration |
| [0002](0002-postgres-pgvector-single-datastore.md) | PostgreSQL + pgvector as the single datastore |
| [0003](0003-fastapi-sse-api.md) | FastAPI with SSE streaming |
| [0004](0004-utc-storage-and-slot-integrity.md) | UTC storage, clinic-local schedules, DB-enforced slot uniqueness |
| [0005](0005-rag-retrieval-and-corpus-licensing.md) | RAG: hybrid retrieval, local embeddings, corpus licensing (MedlinePlus yes, NHS no) |
| [0006](0006-agent-safety-layers-and-checkpointer.md) | Agent graph: rule-based emergency check first, HITL booking, checkpointer |
| [0007](0007-mcp-tools-calendar-and-osm.md) | Clinic tools behind MCP, async graph, optional calendar, OpenStreetMap lookups |
| [0008](0008-api-auth-streaming-and-demo-protection.md) | API: JWT auth, SSE streaming, per-user isolation, demo cost protection |
| [0009](0009-harmful-intent-guardrail-and-dose-guard.md) | Harmful-intent guardrail, router flag and dose guard |
| [0010](0010-public-holidays-per-city.md) | Public holidays per doctor's city |
| [0011](0011-frontend.md) | Frontend: custom stream reader, token storage, one user per tab |
| [0012](0012-langfuse-tracing-and-privacy.md) | Langfuse tracing with content redacted by default |
| [0013](0013-evaluation-harness-and-gates.md) | Evaluation harness: frozen golden sets, DB-state judging, exact safety gates |
| [0014](0014-rag-improvements.md) | RAG improvements: chunk headers, reranker, English query, threshold |
| [0015](0015-localised-fixed-texts.md) | German fixed texts |
| [0016](0016-german-safety-replies.md) | German emergency and harmful-intent replies |
| [0017](0017-german-rule-inflections.md) | German inflected forms in the safety rules |
| [0018](0018-safety-rule-vocabulary.md) | More vocabulary in the safety rules |
| [0019](0019-informational-emergency-questions.md) | General questions about emergency topics |
| [0020](0020-red-team-evals-whole-bot.md) | End-to-end red-team evals and known gaps |
| [0021](0021-non-acute-self-harm.md) | Supportive reply for non-acute self-harm |
| [0022](0022-dose-guard-units.md) | Dose guard units |
| [0023](0023-align-self-harm-replies.md) | Aligning the self-harm replies |
| [0024](0024-passive-ideation-wake-up.md) | Passive wishes not to wake up |
| [0025](0025-dataset-v1-1.md) | Routing dataset v1.1 |
| [0026](0026-character-normalisation.md) | Character normalisation before the safety rules |
| [0027](0027-final-red-team-run.md) | Final red-team run |
| [0028](0028-ci-eval-gate.md) | Eval gate in CI |
