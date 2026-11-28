# Wrong-answer flag, Phase 2: use the flag to fix answers, not just mark them (plan written 2026-11-27, nothing run yet)

## The question
Phase 1 passed: when an independent second program (a2) disagrees with the loop's answer (a1, from m1), a1 is wrong 81% of the time.
Can we turn that into **fewer wrong answers per minute**? The key is to spend the extra work only where the cheap signals say
it is needed, and to compare that against always spending it.

## What the Phase 1 rows already show (dev data, offline, free; it is post-hoc, so it decides nothing)
Simulated on the 140 Phase-1 problems from the stored a1/a2/tries:

| policy | wrong | minutes per problem |
|---|---|---|
| P0: m1 alone (today's loop) | 18/140 | 3.48 |
| P1: always run a2; on disagreement take a2 (and a2 when a1 has no number) | 7/140 | 6.47 |
| P2: run a2 only when m1 needed a fix-and-retry; same rule | 7/140 | 5.02 |

P2 matches P1 for half the extra time, because 16 of the 18 errors had already needed a retry. Of the 7 left, 3 are disagreements where
both programs are wrong (dioph_count 1, 3, 13), 2 are a1 wrong with a2 printing no number (tilings_blocked 3, 9), 1 is a shared
error (tilings_blocked_14, both print 0), and 1 is broken by the rule (recurrence_big_1: a1 was right, a2 was wrong). Since these numbers were picked
after seeing the data, a fresh set is needed.

## Step 1, dev only: is a thinking tie-break worth adding? (about 4–6 h)
On the 21 Phase-1 disagreements, run a3 = m1 with thinking on (4,096-token budget, same retries). This is the existing `m2`
rule in `improve_27b/improve27.py`: take a1 if a3 agrees with it, otherwise take a2.
- **Adopt the tie-break** if, on those 21, it gives at least 2 more right answers than "take a2" (counting fixes and breaks).
  Otherwise drop it. This decision is final before Step 2 starts, and it sets the primary policy:
  P2 without the tie-break, or P2+T with it (P1+T is then reported too).

## Step 2, the locked test (fresh problems, about 15 h)
- **Set:** `phase2_set.json` covers the same 7 hard kinds × 15 = 105 problems, seed 20261127, with none of the hard_bench practice,
  hard_bench locked or `flag_set.json` questions. It is generated once and never used for tuning.
- **Run:** for every problem, a1 (m1) and a2 (VERIFY_SYS, same retries), as in Phase 1. If the tie-break was adopted,
  a3 runs on every problem where a1 and a2 disagree. Every policy is then computed from the same rows. A gated policy simply
  ignores a2 (and a3) when its gate did not fire, and only its own calls are counted in its time.
- Server and settings as Phase 1: -ngl 26, 8k context, draft-mtp, greedy, seed 42. It waits for any other GPU job, and it is
  resumable, as before.

## Pre-registered lines (primary = P2, or P2+T if adopted; compared with P0 and with always-check P1 / P1+T)
- **Pass:** the primary makes **at most half of m1's wrong answers**, **and** at most 2 more wrong than always-check,
  **and** costs at most 60% of always-check's extra minutes over m1.
- **Weak pass:** it halves m1's errors but fails the near-always-check or the cost line. The recommendation would then be
  always-check, since the gate isn't worth it.
- **Kill:** the primary does not halve m1's errors.
- **Reported alongside:** broken answers (right under m1, wrong under the policy; more than 2 is noted as a real cost),
  Wilson 95% intervals, errors removed per extra minute, how many answers are still flagged for a human, and per-kind
  errors. If m1 makes fewer than 10 errors on the 105, the result counts as underpowered, and 15 more problems each from
  dioph_count, seating_forbidden and tilings_blocked are added.

## Cost
Step 1 is about 4–6 h. Step 2 is about 105 × 6.5 min ≈ 11.5 h, plus a3 on about 15% of problems if adopted (≈ 3.5 h). That is about 20 h of GPU
in total. The work fits overnight runs, the 18:00 schedule, or stopping and resuming at any point.

## If it passes
Make the winning policy the default math loop in `improve_27b` (as m4), so that every math answer the user gets has
been through it, with flagged answers marked "check this".

## Addendum before Step 1 ran (2026-11-27, no a3 data seen)
The m2 rule as written (a1 if a3 agrees with a1, else a2) always returns a1 or a2, so it cannot fix a problem where both are
wrong. On the 21 dev disagreements that caps its gain over "take a2" at +1 (only recurrence_big_1), and the +2 adoption line
could never be met. The tie-break rule is therefore fixed now as **T: on a disagreement (including one side having no number),
run a3; take the majority of the non-empty answers among a1, a2, a3; with no majority, take a3 if it has a number, else a2,
else a1.** Both T and the old m2 rule are reported on all 21 problems. T is adopted if it gives at least 2 more right answers than
"take a2", with fixes and breaks netted against each other. "Take a2" gets 15 of the 21 right.

## Deviation: Step 1 stopped early on cost, and the tie-break was dropped (2026-11-27 14:10, the user's go)
After 3 of the 21 problems, the thinking tie-break a3 took 27, 53 and 78 min. On both dioph_count problems it used up the 4,096-token
thinking budget on all 3 tries and never wrote a ```python block, so it gave no number. Rule T and take-a2 were level at 1/3. At that pace
Step 1 alone would have needed another 15–24 h, and even if adopted, the tie-break would cost about an hour per disagreement
against about 1.5 min for take-a2. **The tie-break is dropped on cost.** This is a deviation decided before the remaining 18
dev problems were seen, and the partial rows are kept in runs/step1.jsonl. Step 2 runs with the cheap rules only: primary = P2
(check on retry), compared with P0 (m1) and P1 (always check). The lines are unchanged.
