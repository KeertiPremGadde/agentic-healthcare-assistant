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

---

## German fixed texts

### Why not let the model write the disclaimer in the user's language?
The disclaimer, the refusal and the dose referral are safety statements, so I keep them as reviewed
text rather than generated text: the exact wording is fixed, testable and the same every time. The
model only writes the answer body. There is one set per language in one module, and the language is
picked by the router (it already reports the message's language).

### What breaks if you translate only the strings?
Everything that looks for them. The output guard treated a reply without the English "Sources:" as
uncited and swapped in the English refusal, and the frontend parser found the sources block and the
disclaimer by their English text. So the guard now checks against the texts of every language and adds
the one for the turn's language, and the parser mirrors the labels. Two places that must agree is a
contract, so it is written down in both and tested on both sides.

### How do you stop a stale language leaking from the previous turn?
The supervisor sets `reply_language` on every routed turn, and a test sends a German then an English
message in one conversation and checks each reply. Unknown languages fall back to English instead of a
guessed translation.

### What did you learn about the dose guard?
That it has to follow the languages the answers are in. German answers started flowing with the
query-translation change, but the dose regex knew only a few German forms. I added the common ones
(Teelöffel, Zäpfchen, Hübe, Spritze, ...), and left "i.e." out of the unit list on purpose because it
would flag English sentences. Negative tests matter as much as positive ones for a guard that replaces
the whole answer.

---

## German safety replies

### How can the emergency reply be German if the rules run before any model?
The rules cannot ask the router what language the message is in, because the whole point is that
no model is involved. So each pattern knows its own language: the German patterns are marked, and the
reply is German only if every pattern that matched is German. A German sentence that also contains
an English match, like "stroke", gets the English reply, which is the safe default and also carries
112. When only the router's flag caught a message, the router's language is used.

### How did you know you had not changed what the rules detect?
I loaded the old rules from `main` next to the new ones and ran both on all 247 messages in the
repository (the red-team set, routing, RAG and threshold sets) and compared category and kind: zero
differences. The only new thing is the language, which the tests pin.

### Where do the phone numbers come from?
Not from memory. The poison centre numbers are read from the official directory of the federal
risk-assessment institute (BfR), both the page and the PDF. That caught that a third-party list still
had an old number for one centre. The directory gives no opening hours, so the reply does not claim
any for them; the TelefonSeelsorge's own page says it is reachable day and night, so that reply does.
A test lists the seven numbers independently of the code that holds them.

### Why is 116 117 in one reply and not the other?
It is the on-call doctor service for things that are not acute. In the emergency reply's "if this is
not acute" line it helps; in the crisis reply it would send someone in distress to the wrong place.
Small wording decisions like this are made by a person and written down, then pinned by tests.

### What did the frontend need?
The cards are picked by message kind, so German replies already got them, but the emergency card only
made a fixed list of numbers tappable. I extended that list (not a general regex, which would turn
dates and ids into links) and added look-alike numbers to the tests.

---

## German rule inflections

### How did you find out the German rules were weak?
I wrote the phrases first. 79 sentences the way people actually type them: "er hat einen allergischen
Schock", "bekommt kaum noch Luft", "ich bringe mich um", "Krampfanfälle", "Alkoholvergiftung". Then I
ran the existing rules without changing anything: 47 of the 79 were missed. The rules had been written
in dictionary form, and German changes the form of a word with its grammatical role.

### Why is widening a safety rule risky?
Every widening is a new chance to flag an ordinary message. "Ich bringe mich um." is a threat, but
"Ich bringe meinen Vater um 9 Uhr zum Arzt" is an appointment, and a clinic assistant sees the second
one all day. So each widening came with benign look-alikes written first, guards where the form is
ambiguous (the separable verb only counts when "um" ends the clause), and a rule that inflected
person nouns are only accepted next to first-person intent, never next to a bare infinitive.

### What did the mutation check teach?
That a guard can look tested and not be. Removing the "protective wording" guard changed no result,
because my benign phrases had commas that already stopped the pattern. People type on phones without
commas, so I added "Wie kann ich verhindern dass Kinder sich verletzen", and then the mutation was
caught. A test that passes with the guard removed does not test the guard.

### What is the difference between an inflection gap and a vocabulary gap?
An inflection gap is the same concept in another form (a rule for "allergischer Schock" that misses
"allergischen Schock"). A vocabulary gap is a concept with no rule ("Herzstillstand"). The first is a
bug; the second is a policy decision about recall and false alarms. I fixed the first and wrote the
second down as strict xfails, so closing one later is a deliberate, visible step.

### What did the sweep find besides misses?
A worse failure than silence: "Ich will meinen Nachbarn vergiften" got the *poisoning emergency* reply
because the word "vergift-" matched the emergency rule while the harm rule missed "Nachbarn". And a
language bug: the English anaphylaxis rule matched the stem that German shares, so a German sentence
got the English reply. Both are fixed and pinned.

---

## Suicidal statements and missing concepts

### Why did you pay for a router measurement if the rules are the fix?
To find out what the rules are for. The router flags nearly everything (53 of 57 phrases in 3 of 3
calls), so a reader could conclude the rules do not matter. The three it flagged only 1 time in 3 were
all non-acute self-harm statements ("I've been cutting myself"), because its flag means "acute danger
right now". That is the evidence for the design rule: a phrase is covered only if the deterministic
rules catch it, and the router is the second layer. The measurement cost $0.034.

### What is the difference between precision and recall when you widen a safety rule?
Every new pattern can miss less (recall) or flag more by mistake (precision). Both directions were in
this change: the new rules catch 47 more phrases, and two old English patterns got narrower because
they flagged "I don't want to live in Berlin anymore" and "I hurt myself playing football" as a crisis.
For a safety message the cheaper mistake is the extra warning, so ambiguous cases lean towards
warning ("a bare 'I hurt myself' still counts"), but an obviously ordinary sentence should not.

### What did the mutation check find this time?
Four guards that looked tested and were not. I had written a benign phrase for each, but several never
reached the guard they were meant to test: a "Kind reagiert nicht auf das Medikament" test used the word
"Patient", which is not in the pattern's list; a swollen-glands test had two words between "Hals" and
"schwillt" where the pattern allows one. The mutation (remove the guard) changed nothing, which is how
I knew. A guard without a test that fails when it is removed is decoration.

### What does it mean that a test file pins known false alarms?
Two general questions ("How can I recognise self-harm in teenagers?", "Woran erkennt man
Selbstverletzung bei Jugendlichen?") are still read as a live crisis, for reasons that belong to the next
change. They are in a list that a test asserts is *still flagged*. The day someone fixes them, that test
fails and tells them to move the phrases to the benign list, so a known problem cannot be forgotten or
silently re-introduced.
