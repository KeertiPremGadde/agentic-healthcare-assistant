# 0005 – RAG design: hybrid retrieval, local embeddings, and which sources we may ingest

Status: accepted (Phase 2)

## Context
The assistant must answer medical questions from a curated knowledge base, cite its sources, and
say "I don't know" when the evidence is weak. The repo is public and will be deployed as a live
demo, so every source we ingest must be one we are allowed to republish answers from.

## Decision

### Retrieval
- **Hybrid search in one Postgres** (ADR 0002): pgvector HNSW (cosine) for meaning, a generated
  `tsvector` + GIN index for exact terms (drug names, acronyms). Both return their top 20.
- **Reciprocal-rank fusion** (`score = Σ 1/(60 + rank)`) merges the two lists. Ranks are comparable
  across the lists; raw scores (cosine vs `ts_rank`) are not.
- **Full-text uses OR semantics** (`plainto_tsquery` with `&` replaced by `|`): a natural-language
  question rarely contains every word of one chunk, so AND matching returns nothing.
- **Reranker behind an interface** (`Reranker`). Today: `ScoreReranker`, a deterministic blend of
  cosine similarity (60 %) and normalised fused rank (40 %). Planned upgrade: a local cross-encoder
  (reads query and passage together; more accurate, heavier to ship) implementing the same interface.
- **Abstention:** if the best cosine similarity is below `RAG_MIN_SCORE` (0.70), we answer "I don't know"
  *without calling the LLM*. If the LLM itself reports `context_sufficient=false`, or cites no valid
  passage, we also refuse. Citation numbers returned by the LLM are validated against the passages
  actually supplied, so a hallucinated source can never appear.

### Embeddings
- **Local FastEmbed, `BAAI/bge-small-en-v1.5`, 384 dimensions**: ONNX runtime, no torch, no API key,
  free, reproducible. Behind an `Embedder` interface so a hosted provider can be swapped in.
- The dimension is fixed in the migration (`vector(384)`); changing the model means a new migration
  and a re-ingest. `EMBEDDING_DIM` in settings must match and is tested against the model.
- **Chunks are ~1200 characters (~300 tokens), 150 overlap**, not the ~800 tokens first planned:
  bge-small truncates at 512 tokens, so longer chunks would be silently cut off before embedding.
- The model is cached in CI (`FASTEMBED_CACHE_PATH`); unit tests use a fake embedder.

### Source-agnostic ingestion, licence travels with the data
Ingestion consumes `RawDocument`s from loaders (`PdfLoader`, `MedlinePlusLoader`). Each document
stores its `license`, `attribution`, `url` and an `is_public` flag; citations show the attribution.
Re-ingestion is idempotent: unchanged documents (content hash) are skipped, changed ones replace
their chunks in one transaction. `KB_PUBLIC_ONLY=true` (set in deployed environments) excludes every
source with `is_public = false` at query time.

### Corpus and licensing
| Source | Decision | Reason |
|---|---|---|
| **MedlinePlus Health Topics** (NLM) | **Public demo corpus** | Written by the US National Library of Medicine; US federal works are not copyrighted. NLM asks that MedlinePlus is acknowledged: done in citations and the README. |
| **`Medical_book.pdf`** (legacy project) | **Local development only** (`is_public=false`) | We do not hold a licence to republish it. It never reaches the public demo; `KB_PUBLIC_ONLY` enforces this. |
| **NHS Health A–Z** | **Not ingested** | See below. |

**Why not NHS Health A–Z.** The NHS website terms release content under the Open Government Licence
with conditions that do not fit a RAG demo cleanly:
1. **7-day refresh requirement.** Copies must be refreshed at least every 7 days (24 h recommended).
   A static ingest would breach the terms; complying means building and operating a scheduled
   re-sync with deletion of withdrawn pages.
2. **No explicit permission for AI use.** The terms don't mention scraping, LLM or RAG use, and
   §3.2 requires written permission for any use they do not describe. That is an open question,
   not a yes.
3. Further conditions: attribution on every appearance, no implied NHS endorsement (awkward when an
   LLM paraphrases clinical content), and a warning that adapted or stale content undermines its
   clinical approval.
We can revisit if NHS England confirms in writing that this use is permitted and we add the
refresh job. Until then MedlinePlus alone is the public corpus.

**Third-party content guard.** MedlinePlus also carries copyrighted material (A.D.A.M. encyclopedia,
ASHP drug monographs) that is *not* public domain. The Health Topics XML currently contains none
(checked: no A.D.A.M./ASHP/copyright markers in any ingested summary), and we ingest only the title,
the NLM-written `full-summary` and `also-called` synonyms, never the external `<site>` link records.
The loader additionally excludes and reports any topic carrying such a marker, so a future file
version cannot slip it in.

## Consequences
- Answers are only as good as ~1,000 consumer-level topics; no drug dosing, no clinical guidelines.
  Graceful refusal covers that gap.
- No API cost for embeddings and ingestion; the LLM is called only when evidence passes the threshold.
- Swapping the embedder, reranker or corpus touches one module each, not the pipeline.
- A relevance threshold on cosine similarity is model-specific and must be re-calibrated when the
  embedding model changes. Measured on the real corpus (2026-10-31, 10 in-scope and 8 off-topic
  questions): best similarity 0.74-0.87 in scope vs 0.43-0.65 off topic, hence 0.70. The sample is
  small and the margin narrow (an off-topic "joke about cats" reached 0.65), so the LLM's own
  `context_sufficient` check is a second line of defence, and Phase 7 should re-measure it properly.
