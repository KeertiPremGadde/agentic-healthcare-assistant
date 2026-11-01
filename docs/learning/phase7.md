# Phase 7 (quality: observability and evaluation): interview Q&A

Sections are added as the phase's pull requests land. Decisions: [ADR 0012](../adr/0012-langfuse-tracing-and-privacy.md) (tracing), [ADR 0013](../adr/0013-evaluation-harness-and-gates.md) (evaluation), [ADR 0014](../adr/0014-rag-improvements.md) (RAG improvements).

---

## Tracing

### What is a trace, a span, a generation, a session?
A **trace** is one end-to-end run (here: one turn). **Spans** (Langfuse calls them observations) are
the steps inside it: each graph node, each tool call. A **generation** is an LLM call, with model,
tokens and cost. A **session** groups traces: here, one conversation. The graph's nodes show up as
nested spans automatically, because LangGraph reports them through LangChain's callback system and
Langfuse's handler listens to it.

### How does it plug in?
One callback handler per turn, passed in the run config by `stream_turn`. The API, the dev CLI and
the evals all go through that function, so there is one place that knows about tracing. With no keys
it's a no-op object, like the calendar. Any failure in the SDK is caught and logged by type, so
tracing can't break a conversation.

### A medical chatbot sends data to a third party. How do you keep health text out?
By default nothing with content leaves the process. A redaction function replaces every string with
`[redacted: N chars]` and every number with `[redacted]`, except values under a short allow-list of
*shape* keys (route, node name, token counts, flags). It is default-deny: a new field in the state is
redacted until a person decides it is safe, and a test forbids obvious names on the list. What
remains is enough to debug with: structure, timings, token counts, route, cost.

### How did you know it worked?
Unit tests, a mutation check (make the function keep strings: nine tests fail), and, the one that
mattered, I ran a real conversation and read the traces back from Langfuse looking for the message
words, the username, the raw user id, the thread id and the doctor's name.

### What did that find?
A leak the first layer cannot see. The `mask` hook covers input, output and metadata, but the
LangChain handler also stores an exception's text as the observation's status message, and LangGraph
implements "pause and ask for confirmation" as an exception whose text contains the proposal: doctor,
time, question. So there is a second layer, an export-stage hook that scrubs the same attributes
(and the status message) just before sending. It keeps the exception's class name, which holds no
content.

### And the check itself had a hole?
Yes: I filtered by session id, and child spans created by the Anthropic SDK's own instrumentation
carry no session id, so my first leak check skipped them. They held no content, but they were a
second route into the trace that the redaction wasn't designed for, and a duplicate of each LLM call.
I re-read by trace id and restricted the export to spans the Langfuse SDK created itself.

### How is the user identified?
Not at all, in the clear: the user id is the same one-way hash the logs use, the session id is the
random conversation id, and the thread id (which contains the raw user id) is redacted.

### What does it cost on the free tier?
Langfuse counts traces, observations and scores as units: 50,000 a month on the free plan. Measured on
a real conversation: 17 to 19 units for a turn with an LLM call, 8 to 9 without. About 2,700 LLM turns
a month. Sampling is the lever; it is decided once per turn so a skipped turn sends no scores either.

### What would you do differently with real patient data?
Self-host Langfuse or use a plan with a BAA, keep content capture off, shorten retention, and treat the
trace store as part of the system's data protection scope. On the free plan, synthetic data and
metadata-only traces are the only defensible setup, and the ADR says so.

---

## Evaluation

### What is a golden set and why freeze it?
A fixed list of inputs with the right outcome for each. If the list changes while you change the
system, you cannot tell which one moved the number. Mine is versioned (v1.0), hashed, and a test
fails if the files change without a new version; every result file records the hash it ran on.

### What is in it?
65 RAG questions (40 in scope, 10 near-miss the corpus cannot answer, 10 off-topic, 5 German), 100
routing messages run 3 times each, 27 booking scenarios. The references for the in-scope questions
are written only from the MedlinePlus text the system retrieves from, not from my own knowledge.

### Why are near-miss questions the interesting ones?
Because a RAG system is judged most by what it refuses. Three of mine are "hard negatives": retrieval
scores them above the similarity threshold (a related page exists), so only the model's own "this
context cannot answer it" check can refuse. I verified against the page text that the answer is not
there, otherwise the label would be wrong.

### How do you judge a booking agent?
By the database after the run, never by what the reply says. The expected appointments exist, the
forbidden ones (holiday, past, day off) do not, other patients' rows are untouched, and nothing was
written before the confirmation. A wrong reply that leaves the DB right is a UX bug; a right-sounding
reply that wrote the wrong row is a safety bug, and only the DB check sees the difference.

### Which metrics are gates and which are reported?
Safety metrics are exact: flag recall 100%, false positives 0, dose leaks 0, hard violations 0, with
no margin. Quality metrics gate on the baseline minus a margin of twice the spread between identical
runs. Everything noisy or immature (task completion, German) is reported but not gated.

### LLM-as-judge: what can go wrong?
It is noisy (faithfulness moved 0.045 between identical runs, one question went 0.86, 0.79, 0.20),
it can be starved of context (task completion could not verify "number 2" without the list), and it
can disagree with the literal task when the correct behaviour is to refuse (an impossible slot). So:
three runs, mean and spread, a missing-score rate that fails the run above 5%, and a judge's input
that is checked before its score is trusted. The judge here is the same small model that is being
graded; a stronger-judge cross-check on a sample is planned.

### What did the first real run teach?
That the harness has bugs too. My question-mark check marked a correct clarifying reply as a failure
because the last sentence was not a question. The 100% flag recall also needed a careful definition
of a false positive: a suicidal message is both harmful and an emergency, so flagging both is right.

### How big is the noise, and what does that mean for improvements?
About 0.02 to 0.05 on judged metrics. A change that moves faithfulness from 0.85 to 0.87 proves
nothing; one that moves German answers from 1 of 5 to 4 of 5 does. Deterministic metrics (hit@5,
answer rate) have no judge noise, so they carry the proof for retrieval changes.

### What did it cost?
About $0.75 for the whole harness and baseline on Haiku (routing $0.04, RAG $0.02 a run, booking
$0.008 a run, judged layer $0.155 a run). A spend cap stops a run before it can surprise anyone.

---

## RAG improvements

### How did you decide a change was an improvement?
Before changing anything I had a frozen baseline with its run-to-run spread, so every change got the
same test: does it beat that spread? Deterministic retrieval metrics (hit@k, MRR) have no judge
noise but small samples, so I asked for at least two more questions right and none lost. Judged
metrics (context precision, faithfulness) had to move by more than the spread between identical
runs. A change that did not clear the bar would have stayed out of the default and been recorded as
a negative result. Four changes, one commit each, results saved next to the baseline.

### What is a contextual chunk header and why did it help?
A chunk from the middle of a long page says nothing about which page it belongs to, so "symptoms of
diabetes" could match a risk-factors chunk of another topic. I prepend `Title (also called: ...)` to
each chunk before embedding and before the full-text index is built, but store the clean text, so
citations and what the judge sees do not change. The synonyms mattered most: the question "How can
influenza spread?" could not find the page called "Flu" because "Influenza" was only in the last
chunk. Honest result: hit@k moved by one question each (below my own bar), three ranks improved,
none got worse, and only context precision beat its spread (0.867 to 0.909).

### What is the difference between the embedding model and the cross-encoder?
The embedding model (bi-encoder) turns the query and every passage into vectors separately, so
passages can be indexed in advance and searched fast, but the two never "see" each other. A
cross-encoder reads query and passage together and outputs one relevance score, which is more
accurate but needs one model run per pair, so it can only rescore a short list. The usual design,
and mine: cheap hybrid search finds about 40 candidates, the cross-encoder reorders the best 10.

### How did you choose the reranker?
I compared four ONNX models from fastembed (already a dependency, so no torch): MiniLM-L-6 and
L-12, Jina tiny, and the smallest multilingual one (BGE-v2-m3, int8). On disk 88, 128, 128 and 561
MB; resident after load 218 to 910 MB; per query at 20 candidates roughly 1.4 to 2.3 s for the
smallest and 37 s for the multilingual one, on a slow 15 W laptop CPU. The 6-layer MiniLM was the
smallest, had no regressions and the best English result, so it won. Candidate count is the lever:
about 65 ms per candidate, so I use 10 (0.7 s, about 420 MB peak) and quality was identical down to 5.

### What did the multilingual reranker teach you?
That a reranker only reorders what retrieval found. For German the right topic was in the candidate
pool for 2 of 5 questions, so no reranker could lift German above 0.4, and the 561 MB model bought
exactly nothing. Measuring the ceiling first (is the answer in the pool at all?) would have saved
the download. The fix had to be earlier in the pipeline.

### How did you fix German on an English-only embedding model?
The router already makes one structured-output call per message. I added two fields to it:
`language` and `search_query_en`, a short English search query. Retrieval uses the English query;
the answer model still gets the user's own question and answers in German with the English
MedlinePlus labels. No extra LLM call. German went from 1 of 5 answered to 5 of 5, hit@5 from 0.4
to 1.0, with English and all safety gates unchanged.

### Isn't it dangerous to let an LLM rewrite the query in a medical app?
It would be if the safety checks used it, so there are three rules, each with a test. The
deterministic emergency and harmful rules run first, on the user's own text, before any router
call exists. The router's flags come from the same call and the original messages. And an alarming
phrase planted in `search_query_en` triggers nothing, while a harmless translation cannot hide a
flag. A tripwire test fails if a safety module ever mentions the query. I mutation-checked the
tests by breaking the code three ways and confirming each was caught. For English the router's
paraphrase is ignored by code, not by trust: retrieval always uses the original text.

### What is the known gap?
The German answer body is German, but the "I don't know" reply, the Sources and Content labels and
the disclaimer are fixed English strings, and the output guard looks for the English disclaimer.
It does not affect retrieval quality, so it is a small separate PR (localised texts chosen from the
router's language, guard accepts both).

### How do you pick a similarity threshold, and why two datasets?
The threshold decides "I don't know" before the model is called: if the best chunk's cosine
similarity is below it, refuse. Tune it on the same questions you score it on and you only learn
how well you memorised them. So I wrote a separate tuning set (34 questions, written from the
MedlinePlus text, locked and checked to share no question or topic with the golden set), fixed the
rule first, chose on the tuning set and confirmed on the golden set. The rule's pick (0.726)
failed the confirmation because one golden question scores 0.7226, so 0.70 stayed. The tuning
set's in-scope questions were easier, which is exactly the trap the confirmation set catches.

### What does a threshold plateau mean and why report it?
Between the highest negative the threshold can still refuse (0.69) and the lowest in-scope question
(0.72) every value gives the same outcomes, so 0.70 is not magic: it sits in a 0.03-wide band.
Because the band is narrow, every retrieval run now prints the margin to both edges, and a new gate
fails if in-scope questions start being refused. Some negatives (a knee-replacement question that
scores 0.79 because a page exists) can never be separated by any threshold; the model's own "the
context is not enough" check handles those, and it did in every run.

### What would you do differently?
Measure the ceiling before choosing a component (pool recall before the multilingual reranker),
label t20 as a hard negative when I wrote it, and run the latency measurements on an idle machine
the first time: the first pass ran while a download was going and gave numbers twice as bad. I
discarded it and kept every pass of the second one in a log file.

### What did it cost?
About $1.7 for the four changes (two paid runs of about $0.53 for headers and the reranker, $0.68
for the query translation including the safety re-runs, nothing for the threshold); about $2.5 for
Phase 7 so far.
