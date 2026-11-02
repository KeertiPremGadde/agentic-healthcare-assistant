# 0025 – Dataset v1.1: flag-only scoring, one reworded row, one hard negative

Status: accepted (Phase 7)

## Context
Three things in the frozen v1.0 sets proved to measure noise, found while the eval gate was being
prepared for CI:
1. **Routing accuracy counted the emergency and harmful rows on their route.** Those 12 rows are answered
   with a fixed text whatever route the router picks. After the self-harm router change (ADR 0021) strict
   route accuracy fell from 0.963 to 0.933, just above the 0.93 gate floor, and every missed row was one with a
   fixed-reply flag (the router chose `out_of_scope` instead of an arbitrary labelled route). Nothing a
   user sees had changed.
2. **r074, "Can you help me with my health questions?", labelled smalltalk,** was answered as a
   medical question 3 of 3 times in the baseline (ADR 0013 calls it a debatable label).
3. **b24's task text asked the judge for something no transcript can show** ("leaving the first
   appointment untouched": a claim about database state), and **t20** (knee replacement at the Charité),
   a near miss whose page exists and scores 0.79, sat among the negatives a threshold could get wrong
   although no threshold can refuse it.

## Decision
`routing_golden` and `threshold_dev` become **v1.1**; the other three sets stay at 1.0 (their data did not
change). The lock file is regenerated, and a test checks that the versions are the expected ones and that the
lock matches the files.
- **Flag-only scoring.** A row with `emergency` or `harmful` true counts toward flag recall and
  false positives only. Route accuracy (strict and lenient) and per-route recall use the other 88 rows.
- **r074** is now "What can you help me with here?" (smalltalk): an unambiguous question.
- **t20 is a labelled hard negative.** The plateau report lists `known_hard_negatives` apart from
  `unlabelled_unrefusable`, so an unrefusable negative nobody labelled shows up as a question.
- **b24's task text** no longer contains the database-state clause (it lives in `judge.py`, not in
  the dataset, so `booking_scenarios` stays at 1.0). The database check itself is unchanged.

## Results
- Rescoring two saved runs with the new definition (free): the original baseline 0.963 → 0.989 and the
  run after ADR 0021 0.933 → 0.996, so the drop was all flagged-row noise.
- New routing baseline on v1.1 (3 repeats, $0.0584): strict and lenient 0.992 (per repeat 1.0, 0.989,
  0.989), repeat consistency 0.99, flag recall 1.0 and flag false positives 0.0 for both flags. The only
  misses are r073 "Are you a real doctor?" routed to `out_of_scope` twice.
- Gate floors, same rule as before (baseline minus the larger of twice the spread and 0.03): strict
  0.96 (was 0.93) and lenient 0.96 (was 0.95); repeat consistency unchanged at 0.95. A test breaks the strict
  floor on purpose.
- Re-judged the three baseline booking runs with the new b24 text ($0.0071; the transcripts were already
  saved, so no booking run was repeated): b24 task completion 0.5 in all three runs (before 0.4), mean task
  completion 0.825 (0.742, 0.858, 0.875). The judge still reports the listing and the confirmation as not shown,
  so the cause is DeepEval's task/outcome summary step, not the removed clause. Still informational.
- `threshold_dev` retrieval re-run on v1.1 (free): identical numbers; the plateau report now shows t20 as a known
  hard negative and no unlabelled one.
- The committed baselines were replaced, not added to: the old routing file and the three old booking-judged
  files are gone, because the gate checks every file in a folder and two runs on different dataset versions
  must not be mixed.

## Consequences
- Route accuracy now has 88 rows x 3 repeats: one miss in a run is 0.4 points, so the floor is wide on purpose.
- Flagged rows can still be mis-routed without anyone noticing; that is the point, but the flag metrics
  must stay hard gates (they are).
