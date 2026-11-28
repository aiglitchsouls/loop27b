"""Fresh problem set for the wrong-answer flag test: the 7 'need an idea' kinds from hard_bench, 20 each = 140.
Avoids every question in the hard_bench practice and locked sets. Seed 20261126.
  python -I make_set.py   ->  flag_set.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HB = os.path.join(os.path.dirname(HERE), "hard_bench")
sys.path.insert(0, HB)
import make_hard_math as M  # noqa: E402

HARD = ["incl_excl_big", "digit_dp_big", "power_sum_mod", "dioph_count", "recurrence_big", "seating_forbidden",
        "tilings_blocked"]
seen = set()
for f in ("math_hard_practice.json", "math_hard_locked.json"):
    seen |= {i["question"] for i in json.load(open(os.path.join(HB, f), encoding="utf-8"))}
M.selftest()
# Only the 7 hard kinds are generated (M.build would also loop forever on dice_prob, which has only 18 new questions).
M.items = []; M.R.seed(20261126)
for g in M.GENS:
    if g.__name__ not in HARD:
        continue
    while sum(i["kind"] == g.__name__ for i in M.items) < 20:
        before = len(M.items); g()
        if len(M.items) > before and M.items[-1]["question"] in seen:
            M.items.pop()
items = M.items
assert len(items) == 140 and not ({i["question"] for i in items} & seen)
json.dump(items, open(os.path.join(HERE, "flag_set.json"), "w", encoding="utf-8"), indent=1)
print("wrote flag_set.json:", len(items), "problems,", {k: sum(i["kind"] == k for i in items) for k in HARD})
