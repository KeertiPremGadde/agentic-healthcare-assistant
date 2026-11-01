# 0014 – RAG improvements, each measured against the frozen baseline

Status: in progress (Phase 7). Changes 1 and 2 are decided; 3 (query translation for German) and
4 (threshold) are added to this record when they are measured.

## Context
ADR 0013 froze the golden sets and recorded a Phase 2 baseline with its run-to-run spread. The rule
for this phase: one change per commit, run against that baseline, and keep it only if it beats the
noise. A change that does not is recorded here and not shipped. Result files for each change are in
`evals/results/<change>/`; the baseline in `evals/results/baseline-*` is never modified.

## 1. Contextual chunk headers: kept
Every chunk is embedded and full-text indexed as `Title (also called: ...)` + text. The stored text,
the citations and the judge's contexts are unchanged (`kb_chunks.context_header`; the generated
`tsv` covers header + content; the document hash includes a header version, so a format change
forces a re-ingest). Motivation: a mid-topic chunk says nothing about its topic, and the synonyms
sit at the end of the page (the question "How can influenza spread?" could not find the "Flu" page).

| Metric (EN unless noted) | Baseline | Headers |
|---|---|---|
| hit@1 / hit@5 / MRR | 0.900 / 0.975 / 0.926 | 0.925 / 1.000 / 0.956 |
| context precision (3 runs, spread) | 0.867 (0.030) | 0.909 (0.014) |
| faithfulness | 0.851 (0.045) | 0.879 (0.018) |
| German hit@5 | 0.4 | 0.4 |

hit@k moved by one question each (below the two-question bar), three ranks improved and none got
worse; only context precision beat its spread. The claim is limited to that.

## 2. Cross-encoder reranker: kept as the default
`CrossEncoderReranker` (fastembed, `Xenova/ms-marco-MiniLM-L-6-v2`, ONNX) reads the query and each
passage together and reorders the top `RERANKER_TOP_N` (10) candidates by fused rank. `RERANKER=score`
restores the previous blend of similarity and rank. The "I don't know" decision still compares raw
cosine similarity with `RAG_MIN_SCORE`, never the reranker's score; but the reranker changes which
five chunks are returned, so the best similarity among them moves slightly (off-topic questions
went down, which is the safe direction; abstain rates are unchanged at 0.70).

Models compared (`scripts/compare_rerankers.py`, `evals/results/reranker/`), on a 15 W laptop CPU
(i5-8265U) with 20 candidates:

| Model | Disk | RAM loaded / peak | p50 per query | EN hit@1 / MRR |
|---|---|---|---|---|
| ScoreReranker (before) | 0 | 0 | 0.01 ms | 0.925 / 0.956 |
| MiniLM-L-6 | 88 MB | 218 / 659 MB | 1.4-2.3 s | 0.975 / 0.9875 |
| MiniLM-L-12 | 128 MB | 261 / 703 MB | 2.8-5.5 s | 0.950 / 0.975 (two questions worse) |
| Jina tiny (en) | 128 MB | 302 / 680 MB | 1.2-2.3 s | 0.950 / 0.975 |
| BGE-v2-m3 int8 (multilingual) | 561 MB | 910 MB / 1.2-2.4 GB | 37 s (4 queries) | 0.975 / 0.9875 |

- **The multilingual model buys nothing for German:** the right topic is in the candidate pool for
  2 of 5 German questions, and a reranker only reorders the pool, so German stays at 0.4 for every
  model. It is also not viable on size, RAM and latency. German is the job of change 3.
- **Candidate count is the cost lever.** About 65 ms per query-passage pair, linear. Quality was
  identical at 20, 10 and 5 candidates on the golden set (which is easy: hit@5 = 1.0), so the default
  is 10 as a margin: 0.65-0.74 s and 416 MB peak instead of 1.4-2.3 s and 659 MB. Timing varied by
  up to 70% between passes on this machine, so ranges are given; every pass is in `latency.jsonl`.
  (The first timing pass ran on a busy machine and was discarded.)
- **Judged result (3 runs each, on top of headers):** context precision 0.909 (0.014) -> 0.929 (0.013),
  every reranker run (0.923, 0.929, 0.936) above every headers run (0.901-0.915). Faithfulness
  0.879 -> 0.870 (within noise), recall 0.971 -> 0.976, relevancy 0.912 -> 0.913. German faithfulness
  fell 0.911 -> 0.797 but that is one answered question out of five and spread 0.125: not a signal.
  Safety: dose leaks 0, personal advice on `refer` 0, judge NaN 0; all 15 gate checks pass.
- **The decision rule** (set before the run): default only if judged context precision or
  faithfulness beats the headers run by more than its spread. Context precision did (+0.020 vs 0.014),
  narrowly; the cost is latency and memory below. The code stays switchable.

### Phase 8 consequences (deployment)
- **Bake the model into the image.** fastembed downloads on first use into a temp folder (about 70 s
  here); a container must not do that per cold start. Download both ONNX models at build time and
  point `FASTEMBED_CACHE_PATH` at the baked folder. The reranker adds about 90 MB to the image.
- **Memory per request.** The model is 218 MB resident once, plus activation memory while scoring:
  about 200 MB extra at 10 candidates (416 MB peak), 440 MB at 20. That is on top of the embedder, so
  a 512 MB task is too small; plan 1 GB with headroom, and remember each concurrent request scoring
  at the same time adds its own activations (the node runs in a worker thread). A concurrency limit
  or a lock around scoring bounds it.
- **Latency.** +0.65-0.74 s per medical question on a slow laptop CPU, in addition to the LLM call
  (about 2-3 s). Measure on the real Fargate task size before fixing its CPU; threads beyond 2 helped
  little here. If it is too slow, lower `RERANKER_TOP_N` (5 candidates: 0.4-0.5 s, 297 MB, same
  quality on the golden set) or set `RERANKER=score`.
- **CI** caches only the bge-small model (`ci.yml`, key `fastembed-bge-small-en-v1.5-v1`). No unit
  test loads the reranker (they use a fake encoder); add its folder to that cache if one ever does.
