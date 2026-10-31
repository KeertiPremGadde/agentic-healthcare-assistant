# MedAgent – Architecture & Flows

All diagrams are Mermaid. They render on GitHub and in VS Code (Markdown Preview, or the
"Markdown Preview Mermaid Support" extension).

---

## 1. System context

```mermaid
flowchart LR
    U([Patient / User]) -->|HTTPS| FE[Next.js Chat UI<br/>Vercel AI SDK]
    FE -->|REST + SSE stream| API[FastAPI service<br/>auth · rate limit · sessions]
    API --> G[[LangGraph<br/>multi-agent graph]]
    G -->|tool calls| MCP[MCP server<br/>scheduling + calendar tools]
    G -->|retrieve| VEC[(Postgres + pgvector<br/>medical knowledge chunks)]
    G -->|checkpoints / memory| CK[(Postgres<br/>LangGraph checkpointer)]
    MCP --> DB[(Postgres<br/>doctors · patients · appointments)]
    MCP --> GC[Google Calendar API]
    G -->|LLM calls| LLM{{LLM provider<br/>OpenAI / Anthropic}}
    G -. traces .-> OBS[Langfuse / LangSmith]
    ING[Ingestion job<br/>PDF → chunks → embeddings] --> VEC
```

## 2. Agent graph (LangGraph)

```mermaid
flowchart TD
    START((START)) --> GR[guardrail<br/>deterministic red-flag rules EN/DE<br/>no LLM call]
    GR -->|acute red flag| OUT
    GR -->|ok, or general question<br/>+ safety notice| SUP{supervisor<br/>structured-output router<br/>+ is_emergency flag}
    SUP -->|is_emergency| OUT
    SUP -->|medical_question| RAG[medical_rag<br/>Phase 2 hybrid RAG · citations]
    SUP -->|find_doctor| DF[doctor_finder<br/>Specialty enum · DB lookup]
    SUP -->|book| BK[booking<br/>extract doctor/day/time · find a valid free slot]
    SUP -->|smalltalk / out_of_scope| RS[respond<br/>fixed replies]
    BK -->|proposal| HITL{{confirm<br/>interrupt&#40;&#41;: Book this slot?}}
    BK -->|question / refusal| OUT
    HITL -->|yes| BOOK[book_appointment<br/>re-validate · insert · unique index]
    HITL -->|no| OUT
    BOOK -->|slot lost| HITL
    BOOK -->|booked| OUT
    RAG --> OUT[output_guard<br/>disclaimer · citation check · safety notice]
    DF --> OUT
    RS --> OUT
    OUT --> END((END))
```

The exact compiled graph is generated into [docs/diagrams/agent_graph.md](diagrams/agent_graph.md)
by `scripts/export_graph.py`. State (`AgentState`) is persisted by the Postgres checkpointer per
`thread_id`, so each conversation keeps its memory and a paused confirmation can be answered after a
restart. The patient being booked comes from the run config (login), never from the conversation.

## 3. Booking flow (sequence)

```mermaid
sequenceDiagram
    actor P as Patient
    participant UI as Chat UI
    participant API as FastAPI
    participant G as LangGraph
    participant T as MCP tools
    participant DB as Postgres
    participant C as Google Calendar

    P->>UI: "I have chest pain when climbing stairs, book a doctor"
    UI->>API: POST /chat (SSE)
    API->>G: invoke(thread_id, message)
    G->>G: guardrail → not acute emergency → supervisor → doctor_finder
    G-->>UI: stream: "A Cardiologist is advised. Dr. Johnson or Dr. Wilson?"
    P->>UI: "Dr. Wilson, next Tuesday afternoon"
    G->>T: check_availability(doctor, date)
    T->>DB: query free slots
    T-->>G: [14:00, 14:30, 15:00]
    G-->>UI: interrupt: "Confirm Tue 14:00 with Dr. Wilson?"
    P->>UI: "Yes"
    API->>G: resume(thread_id, Command(resume="yes"))
    G->>T: book_appointment(...)
    T->>DB: insert appointment (transaction, unique slot)
    T->>C: create event
    G-->>UI: "Booked ✔ Confirmation #A-1042"
```

## 4. RAG pipeline

```mermaid
flowchart LR
    PDF[Medical PDFs<br/>data/raw] --> L[Loader] --> CH[Chunker<br/>recursive, ~800 tokens, overlap]
    CH --> MD[Metadata<br/>source, page, section]
    MD --> EMB[Embeddings] --> PG[(pgvector)]
    Q[User question] --> QR[Query rewrite] --> HY[Hybrid search<br/>vector + full-text]
    PG --> HY --> RR[Reranker] --> CTX[Top-k context] --> ANS[LLM answer<br/>with citations]
```

## 5. Delivery pipeline (CI/CD)

```mermaid
flowchart LR
    DEV[feature branch] -->|push| PR[Pull request]
    PR --> CI[GitHub Actions CI<br/>ruff · mypy · pytest · gitleaks]
    CI --> EV[Eval gate<br/>RAGAS / DeepEval thresholds]
    EV -->|merge| MAIN[main]
    MAIN -->|tag vX.Y.Z| CD[CD workflow]
    CD --> IMG[Build Docker image] --> ECR[(AWS ECR)]
    ECR --> ECS[AWS ECS Fargate / App Runner]
    TF[Terraform<br/>infra/terraform] --> ECS
    ECS --> LIVE([Live URL])
```

## 6. Repository layout

```
agentic-healthcare-assistant/
├── src/medagent/
│   ├── main.py              FastAPI app factory
│   ├── core/                settings, logging, security
│   ├── api/routes/          health, chat (SSE), auth, appointments
│   ├── agents/              state.py, graph.py, nodes/, prompts/
│   ├── tools/               typed LangChain tools
│   ├── rag/                 ingestion, retrieval, reranking
│   ├── db/                  engine, session, models/
│   ├── services/            pure domain logic (availability, validation)
│   ├── schemas/             shared Pydantic models
│   ├── guardrails/          emergency, PII, disclaimer
│   ├── mcp_server/          MCP tool server
│   └── observability/       tracing
├── tests/unit · tests/integration
├── evals/                   datasets + eval scripts + results
├── migrations/              Alembic
├── frontend/                Next.js app (Phase 6)
├── infra/docker · infra/terraform
├── data/raw · data/processed  (git-ignored)
├── docs/                    PLAN, ARCHITECTURE, SETUP, adr/
└── .github/                 workflows, templates, dependabot
```
