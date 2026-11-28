# Wrong-answer flag test (backlog idea #4), plan written 2026-11-26 before any fresh-set run

## The question
Can the deployed local setup (Qwen3.8-27B + Python loop "m1", from `improve_27b/`) tell **when its own answer is
probably wrong**, cheaply and without the answer key? A flag that works lets a user trust unflagged answers and
re-check flagged ones. This is the calibration bottleneck. Every fix that works today is an external checker; the
question is whether a cheap internal signal can decide when to call one.

Prior art (no novelty claim): self-consistency (Wang 2022), semantic entropy (Farquhar 2024) and N-version programming
all use disagreement between independent answers as an error signal. The test is about practical value on our own loop.

## Already seen on the practice set (tuning data, 40 problems, existing rows from 2026-11-10)
- m1 wrong on 4/40 (10%). All 4 errors had needed a fix-and-retry, and the number printed after the fix was wrong.
- **Backlog's literal form (direct answer vs loop disagree): fails.** It fires on 33/40 with 12% precision against a 10%
  base rate, because the plain 27B's direct answer is wrong on 83% of these problems. Disagreement with a mostly
  wrong reference carries almost no information. A direct answer with 4,096 tokens costs about 13 minutes per problem, so
  it is not rerun on the fresh set. It is reported as failed on the practice data, with that reason.
- "Loop needed a fix-and-retry" fires on 11/40, catching 4/4 errors (36% precision).

## Fresh set
`flag_set.json`: 140 new problems, the 7 hard kinds of `hard_bench` × 20, seed 20261126. No overlap with the
practice or locked sets. Every answer is checked by two independent methods (`make_hard_math.py`). The 3 easy kinds
are left out because m1 gets them all right, so they add cost and no errors. The hard_bench locked set stays unused.

## Run (`wrong_flag.py`, same server and settings as improve_27b: -ngl 26, 8k context, draft-mtp, greedy, seed 42)
Per problem: a1 = m1 (the answer the user gets) and a2 = an independent second program from the existing VERIFY_SYS
prompt (brute force or simulation where feasible, same retries). Expected time: about 5–6 min per problem, about 13 h.

## Pre-registered flags and lines (`score.py`)
- **F2:** the second program disagrees with a1, or either has no number. This is the primary flag.
- **F3:** m1 needed at least one fix-and-retry. This costs nothing extra.
- **F2 or F3.**
- Base error rate e = share of problems where a1 is wrong.
- A flag **passes** if its precision (share of flagged answers that are wrong) is ≥ 2e **and** its recall (share of
  errors it flags) is ≥ 50%. Idea #4 **passes** if F2 or F2-or-F3 passes. F3 alone is reported, but it is a
  side result: it is not the idea being tested.
- **Kill:** neither F2 nor F2-or-F3 passes.
- **Underpowered:** if m1 makes fewer than 10 errors, add 20 more problems each from dioph_count,
  seating_forbidden and tilings_blocked (where m1 failed on practice) and score all of them together.
- Reported alongside: Wilson 95% intervals, fire rate (how many answers a user would have to re-check), time cost,
  and (exploratory) how often a2 is right when F2 fires.

## If it passes
Phase 2 (not run without the user's OK): use the flag to decide when to spend the expensive fix (thinking tie-break,
about 4k tokens), and measure errors removed per extra minute against always running it.
