# Hard math practice set: 40 problems, 10 kinds x 4

Answers are exact integers, each checked by two independent methods. Opus = current Opus run as a Claude Code subagent (not Opus 4.5, not a clean API call).

| Kind | Local 27B, plain | Local 27B + Python loop | Opus, no tools | Opus + Python |
|---|---|---|---|---|
| coin_big | 0/4 | 4/4 | 4/4 | 4/4 |
| dice_prob | 2/4 | 4/4 | 4/4 | 4/4 |
| digit_dp_big | 0/4 | 4/4 | 0/4 | 4/4 |
| dioph_count | 1/4 | 3/4 | 4/4 | 4/4 |
| incl_excl_big | 0/4 | 4/4 | 4/4 | 4/4 |
| lattice_blocked | 2/4 | 4/4 | 4/4 | 4/4 |
| power_sum_mod | 2/4 | 4/4 | 4/4 | 4/4 |
| recurrence_big | 0/4 | 4/4 | 4/4 | 4/4 |
| seating_forbidden | 0/4 | 3/4 | 0/4 | 4/4 |
| tilings_blocked | 0/4 | 2/4 | 3/4 | 4/4 |
| **Total** | **7/40** | **36/40** | **31/40** | **40/40** |
| Time | 13.5 min/problem | 2.8 min/problem | 14 min total (one subagent) | 52 s total (one subagent) |
