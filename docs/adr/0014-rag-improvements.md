# 0014 – RAG improvements, each measured against the frozen baseline

Status: accepted (Phase 7). All four changes are decided and measured.

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

## 3. English search query for non-English questions: kept
The router's structured output gained two fields, `language` and `search_query_en`, filled in the
call it already makes (no extra LLM call). Retrieval uses the English query for a non-English
medical question; the answer model still receives the user's own question, and the RAG prompt now
says to answer in the user's language and keep citation labels exactly as shown (English).

Three rules, each with a test (`tests/unit/test_query_translation.py`, mutation-checked):
- **The safety checks only see the user's words.** The deterministic rules run before any router
  call (no query exists yet); the router's flags come from the same call and the original messages;
  an alarming phrase placed in `search_query_en` triggers nothing and a harmless one cannot hide a
  flag; a spy shows the guardrail receives only the original text; a source tripwire fails if a
  safety module ever mentions the query. The state key is set (or cleared) by the supervisor on
  every routed turn, so an old query is never reused.
- **English is retrieved with the original text, never a paraphrase.** One rule,
  `RouteDecision.english_search_query()`: a query exists only if `language` is not English and the
  model gave one; even if the model fills in a paraphrase for an English message, it is ignored.
- **The eval applies the same rule** (`_english_query`), so it measures the app's path.

| German in-scope set (n=5) | Before | After |
|---|---|---|
| hit@1 / hit@5 / MRR (5 questions x 3 router calls) | 0.4 / 0.4 / 0.4 | 1.0 / 1.0 / 1.0 |
| false abstain at 0.70 | 0.8 | 0.0 (also 0.0 at 0.76) |
| answered end to end (3 runs) | 1 of 5 | 5 of 5 each run |
| right source cited / answered in German | 0.2 / n/a | 1.0 / 1.0 |

The queries were stable (14 of 15 calls identical, the other differed in wording only). n=5 is low
power, but the effect is large and the same in every repeat; the answers were read, not only
scored by the language heuristic. German judged metrics (faithfulness 0.873, context precision
0.879) are reported only: five answers, spread up to 0.1.

Checks that the change did not hurt anything else (3 runs each unless noted):
- Flags: emergency and harmful recall 100%, false positives 0. Red-team router: 28 of 28 attacks
  caught by rules and router combined, 0 false positives (two cases flipped a router flag between
  runs in opposite directions: router non-determinism). Booking: 27 of 27, 0 hard violations.
- Routing strict accuracy 0.963 -> 0.953 (gate min 0.93), lenient 0.98 -> 1.0. All of the strict
  change is in emergency and harmful rows (r090-r098), whose route is irrelevant once the flag
  fires and all of which are in `accept`; no ordinary medical question changed route.
- English: answer rate and citation hit 1.0, near-miss / hard-negative / off-topic 1.0, dose leaks
  0. Judged, against the reranker run: faithfulness 0.870 -> 0.884, context precision 0.929 ->
  0.932, recall 0.976 -> 0.982 (all within noise); NaN rate 0. Gate: 24 of 24.
- Cost: $0.155 for retrieval, routing, red-team, booking and RAG runs, plus $0.522 for the three
  judged runs.

### Known gap: German replies still carry English fixed text
The answer body is German with English MedlinePlus labels, as intended, but the "I don't know"
reply, the `Sources:` and `Content:` labels and the disclaimer are English, and the output guard
looks for the English disclaimer. A German user therefore sees an English refusal and an English
disclaimer. Planned as a small separate PR: localised fixed texts chosen from the router's
`language`, with the output guard accepting both the English and the German disclaimer. Not part of
this change because it does not affect retrieval quality and needs its own tests.

## 4. `RAG_MIN_SCORE`: re-measured, 0.70 confirmed (no change)
The threshold is specific to the embedding model, the chunk text and the corpus, and the first three
changes altered the last two, so it was re-measured on the full pipeline. To avoid tuning on the
set that confirms it, a separate tuning set was written first (`evals/datasets/threshold_dev.json`,
v1.0, locked, 34 items: 20 in scope incl. four terse or colloquial queries, 8 near-miss, 6 off-topic;
a test keeps it disjoint from the golden set). Rule fixed before looking at the result: choose on
the tuning set the threshold with zero in-scope refusals and the best abstain recall (middle of any
tie range; `refer` items and items no threshold can refuse are excluded), then confirm on the golden
set; move only if golden in-scope false abstain stays 0 and abstain recall does not fall.

Similarity of the best returned chunk, per class:

| Class | Tuning set | Golden set |
|---|---|---|
| in scope | 0.762 - 0.921 (n=20) | 0.723 - 0.897 (n=40) |
| near-miss to abstain / off-topic | 0.423 - 0.790 (n=12) | 0.454 - 0.778 (n=18) |

Every threshold from 0.691 to 0.722 gives identical outcomes on both sets (in-scope refused 0 of 60;
every refusable negative refused on both sets: 11 of 11 on the tuning set, all 16 on the golden set). Applying the rule:
the tuning set alone allows 0.69-0.76 (middle 0.726), but 0.726 would refuse golden q28 (0.7226), so
the confirmation fails and **0.70 stays**. The tuning set's in-scope questions are easier (lowest
0.762 vs 0.723), which is exactly what the confirmation set is for: "the highest threshold with no
in-scope refusal on the tuning set" (0.76) would refuse 3 of 40 golden questions.

- **Margins are thin on the negative side:** 0.0095 (golden, to n07 at 0.6905) and 0.0107 (tuning, to
  t24 at 0.6893); 0.0226 and 0.062 to the lowest in-scope question. The plateau is about 0.03 wide, so
  a different embedder, header format or corpus needs a fresh sweep.
- **New guards:** `retrieval` gate `en_false_abstain_at_threshold <= 0.025` (one of 40; it was not
  gated before), and every retrieval run now reports `plateau_margin_to_in_scope`,
  `plateau_margin_to_negative` and the list of negatives no threshold can refuse
  (`threshold_plateau`, informational; a margin <= 0 means the current value misclassifies
  something on that set). `retrieval --dataset threshold_dev` runs the tuning set (suite
  `retrieval_dev`, never mixed into the golden-set gate).
- **Negatives only the LLM can refuse:** golden n04 (0.778) and n05 (0.737), and tuning t20 (0.790,
  "recovery time after a knee replacement at the Charite": a Knee Replacement page exists). They
  score above the lowest in-scope question, so no threshold separates them; the answer model's
  `context_sufficient` check does (hard-negative abstain rate 1.0 in every run).
- **For dataset v1.1:** label tuning item t20 as a hard negative (it was written as a plain
  near-miss); the locked v1.0 file is not edited.
- No paid run was needed: nothing that reaches the answer model changed.

## Summary of the four changes (against the frozen Phase 2 baseline)

| | EN hit@1 | EN MRR | Context precision | Faithfulness | German answered |
|---|---|---|---|---|---|
| Baseline | 0.900 | 0.926 | 0.867 | 0.851 | 1 of 5 |
| + headers | 0.925 | 0.956 | 0.909 | 0.879 | 1 of 5 |
| + reranker | 0.975 | 0.9875 | 0.929 | 0.870 | 1 of 5 |
| + English query | 0.975 | 0.9875 | 0.932 | 0.884 | **5 of 5** |
| + threshold | unchanged (0.70 confirmed) | | | | |

Judged columns are means of three runs; the baseline spread is 0.045 (faithfulness) and 0.030
(context precision), so only context precision's rise (+0.065 in total) and the German result are
beyond noise. Spend for the four changes: $0.53 (headers) + $0.53 (reranker) + $0.68 (query
translation incl. safety re-runs) + $0 (threshold) = about $1.7; Phase 7 in total about $2.5 of $10.
