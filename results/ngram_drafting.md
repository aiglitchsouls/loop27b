# N-gram drafting on the 27B fix loop — result (2026-11-23)

Test: 20 rewrite requests rebuilt from the IFEval loop (practice half) plus 8 checker-writing requests, on the same
llama-server flags as the contest/IFEval runs;
only `--spec-type` changes. A = `draft-mtp` (today), B = `draft-mtp,ngram-simple`. Thinking off, greedy, seed 42.

| Workload | A total | B total | Speedup | Mean tok/s A → B | Same text as A |
|---|---|---|---|---|---|
| 20 IFEval fix passes (first rewrite, practice half) | 1,332 s | 455 s | **2.93×** (median 2.14×, range 0.86–5.78) | 4.9 → 16.4 | 18/20 |
| 8 checker-writing calls (control, new code) | 649 s | 711 s | 0.91× (per token ≈ same) | 4.2 → 4.2 | 6/8 |

- Long rewrites gain most: 650–1,800 tokens → 4.4–5.8× (n-gram acceptance 87–95%). Replies under ~60 tokens gain nothing.
- A is deterministic: all 20 A outputs match the loop's own Nov 18 rewrites byte for byte. B changed 2/20 at a single
  near-tie word ("through the gates" → "through"; "COMPOSITION" → "composition"); official IFEval score is the same
  on both. The control's one slowdown (1021) came from a near-tie flip that made a longer checker.
- Pre-set bar: speed passes easily (≥1.5×), but "any output differs" was hit (2/20), so by the letter it fails.
- Whole-loop effect on IFEval: rewrites are ~19% of the loop's generated tokens, so the 10.9 h practice run would drop
  to roughly 9.5 h (~13%). Bigger effect where rewrites dominate (code fix loops, app_bench).

## Follow-up: loop27b's own math and code loops (2026-11-23)

loop27b's `solve_math` / `solve_code` were run on dev items, once with `--exact` (A) and once with the n-gram default
(B), with a warmed-up server. Every item was solved on the first try in both runs, so this measures the first-try
path with no rewrites.

| Loop | A total | B total | Speedup | Correct A / B | Same output |
|---|---|---|---|---|---|
| Maths, 20 problems (2 of each of 10 kinds) | 453 s | 492 s | **0.92×** (median 0.95×) | 20/20 / 20/20 | 20/20 |
| Code, 20 even-numbered HumanEval dev tasks (hidden tests) | 904 s | 763 s | **1.19×** (median 1.11×, up to 1.66×) | 20/20 / 20/20 | 17/20 |

- Maths scripts are short and new, so there is nothing to copy and n-gram only adds overhead. Since then,
  `loop27b.py math` always uses `draft-mtp` alone.
- Code gains grow with answer length: answers of 1,500–2,700 characters were 1.46–1.66× faster.
- The 3 differing code answers have reworded comments or a different correct implementation. All of them pass the
  hidden tests.
