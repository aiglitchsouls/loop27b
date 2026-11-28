# Wrong-answer flag (backlog #4): PASS, 2026-11-27

The run covered 140 fresh problems (7 hard kinds × 20). It finished at 08:32 on 2026-11-27, with stops on 11-26 at 10:51 and 16:50 that resumed cleanly.
Scorer: `score.py`, writing `score.json`. Rows are in `runs/flag.jsonl`.

m1 (the answer the user gets) was wrong on **18/140 = 12.9%** (95% CI 8.3–19.4), so the precision line is 2e = 25.7%.

| flag | fires | precision | recall | verdict |
|---|---|---|---|---|
| **F2: the second program disagrees, or has no number** | 21 (15%) | **17/21 = 81%** (CI 60–92) | **17/18 = 94%** | **PASS** |
| F3: m1 needed a fix-and-retry | 55 (39%) | 16/55 = 29% (CI 19–42) | 16/18 = 89% | pass (side result; CI crosses the line) |
| F2 or F3 | 59 (42%) | 18/59 = 31% (CI 20–43) | 18/18 = 100% | pass |

**Verdict per the plan: idea #4 PASSES** (F2 passes on its own). The flag fires on 15% of answers, and 81% of those are
really wrong. Of the unflagged answers, 118 of 119 are right (99.2%), against 87.1% for all answers.

## Details
- **The one miss** (`tilings_blocked_14`): both programs printed 0 against a true 5120. They failed the same way, which
  is the known blind spot of N-version checks.
- **The 4 false alarms:** in 3 of them the second program printed no number (`dioph_count_9`, `seating_forbidden_9`,
  `tilings_blocked_19`). Only 1 is a real disagreement (`recurrence_big_1`, 427 vs 218).
- **Concentration:** 11 of the 18 errors are from `tilings_blocked`. Leaving that kind out, there are 120 problems with 7 errors, and F2 fires 10
  times, catching all 7 (precision 70%, recall 100%). So the result does not depend on that one kind, though the sample
  outside it is small.
- **Exploratory:** when F2 fires, the second program is right on 12/21 and m1 on 4/21. Picking a2 on disagreement would
  have fixed some errors. This was not pre-registered, so it needs its own test.
- **Cost:** 6.5 min per problem against 3.5 for m1 alone. The second program roughly doubles the time on every problem.
- **Practice data (from the plan):** the backlog's literal form (direct answer vs loop) failed. The working flag uses two
  independent programs, not a direct answer.

## Next (needs the user's OK, per the plan)
Phase 2: use F2 to decide when to spend the expensive fix, and measure errors removed per extra minute against always running it.
A cheaper variant: run the second program only when m1 needed a retry (F3 fires on 39% and covers 16/18 errors), which would cut the extra cost by about 60%.

---

# Wrong-answer flag, Phase 2: PASS (2026-11-28)

Locked test: `phase2_set.json`, 105 fresh problems (7 hard kinds × 15, seed 20261127). The run went 2026-11-27 14:08 → 11-28 02:03.
It used the cheap rules only, because the thinking tie-break was dropped on cost (see the "Deviation" in PHASE2_PLAN.md). Scorer: `score2.py`,
writing `score2.json`. Rows are in `runs/phase2.jsonl`.

| policy | wrong | fixed | broke | min / problem |
|---|---|---|---|---|
| P0: m1 alone (today's loop) | 17/105 = 16.2% (CI 10–24) | – | – | 3.75 |
| P1: always run the second program, take its answer on disagreement | 7/105 = 6.7% (CI 3–13) | 15 | 5 | 6.76 |
| **P2: run the second program only when m1 needed a retry** | **8/105 = 7.6%** (CI 4–14) | 12 | 3 | **4.92** |

**Verdict per the plan: PASS.**
- P2 halves m1's errors (8 vs 17).
- It is within 2 of always-check (8 vs 7).
- It costs 39% of always-check's extra time (1.18 vs 3.02 extra min per problem; the line was 60%).
- It removes 0.073 errors per extra minute, against 0.032 for always-check, so it is 2.3× as efficient.

The Phase 1 flag also holds on these fresh problems. "The second program disagrees" fires on 23 of 105 and catches **17 of 17** errors, at
74% precision (Phase 1: 81% precision, 94% recall).

## Weak spots
- **Broke 3 right answers, above the plan's "more than 2 is a real cost" note.** All 3 are tilings_blocked problems where the second program
  printed **0** and m1 was right (1126, 3977, 136). A rule such as "never replace a nonzero answer with 0" would have kept all
  three (8 → 5 wrong). That rule was found after seeing the data, so it needs its own fresh test before it is used.
- **Misses that the gate never sees:** 3 errors had no retry (digit_dp_big_14, power_sum_mod_5, power_sum_mod_14). In all 3, the second program
  had the right answer, so always-check catches them and P2 does not. This is the price of the gate.
- **Both wrong:** dioph_count_14 (a2 gave no number) and tilings_blocked_14 (a1 gave no number, a2 = 142 against a true 7552).
- tilings_blocked is still the weakest kind: 7 of the 17 m1 errors, and 4 of P2's 8.

## What this means in practice
Over the 210 fresh hard problems from both phases, the loop's answer is wrong ~14% of the time. With P2, that drops to ~7% for ~1.2 extra
minutes per problem, and the disagreement flag still says "check this one" on most of the rest.

## Next (needs the user's OK)
1. Make P2 the default math loop in `improve_27b` (as m4).
2. Optionally, a small fresh test of the "don't take 0 over a nonzero answer" guard.
