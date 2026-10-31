# Phase 2 – RAG knowledge base: interview Q&A

What we built: an ingestion pipeline (loader → chunk → embed → pgvector), hybrid retrieval
(vector + full-text, fused with reciprocal-rank fusion, reranked), and cited answering with an
"I don't know" path. Code: `src/medagent/rag/`, `src/medagent/db/models/knowledge.py`,
`src/medagent/agents/prompts/rag.py`. Decisions: [ADR 0005](../adr/0005-rag-retrieval-and-corpus-licensing.md).

---

### What is RAG and why use it for a medical assistant?
Retrieval-augmented generation: instead of letting the LLM answer from memory, we first *retrieve*
relevant passages from a curated knowledge base and make the model answer *from those passages*.
For medicine this matters because answers must be traceable (citations), up to date (change the
corpus, not the model) and refusable (if nothing relevant is found, say so rather than guess).

### Walk me through the pipeline.
**Ingest:** loader produces `RawDocument`s (text per page + licence/attribution) → recursive splitter
makes ~1200-character chunks with 150 overlap, each keeping its page number → FastEmbed turns each
chunk into a 384-dim vector → rows go into `kb_chunks`. **Query:** embed the question → vector top-20
and full-text top-20 → reciprocal-rank fusion → rerank → top-5 passages → threshold check → Claude
answers with structured output (answer, used passages, sufficient?) → we attach citations and the
disclaimer.

### Why hybrid search instead of vectors only?
Embeddings are great at meaning ("high blood pressure" ≈ "hypertension") but can blur exact tokens:
drug names, acronyms, numbers. Full-text search is the opposite. Running both and fusing the results
is more robust than either alone. Test: the query "metformin" is found by full-text rank 1 even though
the sentence is mostly about something else.

### What is reciprocal-rank fusion and why not just add the scores?
`score(doc) = Σ 1 / (60 + rank)` over each result list. Cosine similarity and `ts_rank` are on
different scales and distributions, so adding them is meaningless; ranks are comparable. A document
that both lists rank highly wins; one that only one list likes still gets credit. The constant 60
(from the original paper) stops the top rank from dominating. `reciprocal_rank_fusion` is a pure
function with unit tests.

### Why OR semantics in the full-text query?
`plainto_tsquery` ANDs every word, and a natural question ("why does wheezing happen with allergens at
night in children") never has all its words in one chunk, so it matches nothing. I replace `&` with `|`
so any matching word counts and `ts_rank_cd` orders by how many and how close. Vector search covers
the semantic side. There is an integration test for exactly this.

### Why pgvector in Postgres, and why HNSW?
One datastore for relational data, vectors and full-text (ADR 0002): one backup, one transaction
boundary, SQL filters (`is_public`) in the same query. HNSW is an approximate nearest-neighbour graph
index: far faster than an exact scan as the corpus grows, at a small recall cost; `vector_cosine_ops`
matches how the embeddings are compared. The `tsvector` column is a Postgres *generated* column, so it
can never drift from the text.

### Why local FastEmbed with bge-small, and what is the catch?
No API key, no per-token cost, deterministic, runs on ONNX (no torch). It's behind an `Embedder`
interface so a hosted provider can be swapped in. The catches: (1) the vector dimension (384) is baked
into the table, so changing models needs a migration and a full re-ingest; (2) bge-small truncates at
512 tokens, which is why chunks are ~300 tokens rather than the 800 first planned; (3) the "is this
relevant?" threshold is specific to the model and must be re-calibrated if it changes.

### How did you pick the "I don't know" threshold?
By measuring, not guessing. I first guessed 0.35; running 10 in-scope and 8 off-topic questions against
the real index showed bge-small similarities are compressed into a high band: in scope 0.74-0.87, off
topic 0.43-0.65 ("a joke about cats" matched *Cat Scratch Disease* at 0.65). So 0.35 would have refused
nothing; 0.70 sits in the gap. Caveats I'd state in an interview: small sample, narrow margin, specific
to this model and corpus, so the LLM's `context_sufficient` flag is a second guard and Phase 7 evals
should re-measure with a proper labelled set.

### How do you stop the model making things up?
Layers, cheapest first: (1) if the best cosine similarity is below `RAG_MIN_SCORE`, refuse *without
calling the LLM*; (2) the prompt says "answer only from the numbered passages, otherwise say you don't
know" and treats the passages as data, not instructions; (3) structured output forces the model to say
`context_sufficient` and which passage numbers it used; (4) we drop any passage number that wasn't
supplied, so a hallucinated source can't appear; (5) citations are rebuilt from our own metadata, not
from model text; (6) the disclaimer is appended by code, not the model. Phase 7 measures faithfulness
with RAGAS.

### Why structured output instead of parsing the model's text?
Project rule: routing and extraction use Pydantic schemas, never string matching. `AnswerPayload` is
validated by LangChain/Claude tool calling, so malformed output fails loudly instead of silently
producing a wrong citation.

### How is ingestion idempotent?
Each document gets a SHA-256 of its text and metadata. On re-run: unchanged hash → skip (no embedding
work); changed → delete that document's chunks and write the new ones in one transaction; new → insert.
It commits per document, so a crash loses at most one document. Tested: a second run changes nothing
(same chunk ids), and one edited document replaces only its own chunks.

### What is a reranker, and what did you build?
Retrieval casts a wide net cheaply; a reranker re-orders the shortlist with a better (costlier)
signal. I built `ScoreReranker`: 60 % cosine similarity + 40 % normalised fusion rank, deterministic
and free, behind a `Reranker` interface. The planned upgrade is a cross-encoder, which reads query and
passage *together* and is more accurate but needs a heavier model; same interface, so it's a drop-in.

### Which data did you use, and what did you decide not to use?
The public demo uses **MedlinePlus Health Topics**: written by the US National Library of Medicine, so
a US federal work with no copyright; NLM only asks for acknowledgement, which appears in every citation
and the README. The legacy `Medical_book.pdf` stays **local-only**: I don't hold a licence to
republish it, so it is flagged `is_public=false` and `KB_PUBLIC_ONLY=true` removes it from retrieval
in deployed environments. I **declined NHS Health A–Z**: its terms require copies to be refreshed at
least every 7 days and say nothing about AI use (written permission is required for undescribed
uses). Respecting that means a sync job and an open legal question, so it's out until clarified.

### How did you check MedlinePlus wasn't hiding copyrighted content?
MedlinePlus mixes public-domain NLM text with third-party material (A.D.A.M. encyclopedia, ASHP drug
monographs). I searched the real XML for those markers: none in the Health Topics summaries; the only
"Merck" hits were external link records, which we never ingest. We use only the title, summary and
synonyms. The loader also *excludes and reports* any topic with such a marker, with a test using a
fixture that contains one, and a test that the name "Adam's apple" is not wrongly excluded.

### What bugs did testing against reality catch?
- A runtime `NameError` (an annotation referencing a type only imported under `TYPE_CHECKING`):
  mypy was happy, only running the real model found it.
- My assumption that the embedder adds a query instruction was wrong; I measured that `query_embed`
  equals `embed` for this model and fixed the comment.
- A fake embedder that counted stopwords ranked the wrong document first. It was a flaw in the test
  double, not the retriever; I fixed the fake instead of loosening the assertion.
- `.env` made settings fail to parse `API_CORS_ORIGINS` (a Phase 0 bug that only appeared once a real
  `.env` existed); added a test.

### How do you test RAG without an LLM or network?
A deterministic content-word hashing embedder and a scripted `FakeAnswerLLM` run the real pipeline
against real Postgres (ingest, hybrid search, filters, refusal paths). One test loads the real
FastEmbed model (cached in CI) to check dimension and that related text scores higher than unrelated.
Real Claude calls are marked `llm` and only run with `pytest -m llm`, so plain `pytest` never spends
money.

### What would you do next at scale?
Cross-encoder reranking; query rewriting for follow-up questions (Phase 3 adds conversation state);
section-aware chunking and metadata filters; a scheduled re-sync of the corpus; evaluation with RAGAS
and a faithfulness gate in CI (Phase 7); embedding-model versioning in the schema so two models can
coexist during a migration.
