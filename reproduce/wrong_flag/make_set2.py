"""Phase 2 locked set: the same 7 hard kinds x 15 = 105, seed 20261127. Avoids the hard_bench practice and locked sets
and every Phase-1 question (flag_set.json).  python -I make_set2.py -> phase2_set.json
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
N = 15
seen = set()
for f in (os.path.join(HB, "math_hard_practice.json"), os.path.join(HB, "math_hard_locked.json"), os.path.join(HERE, "flag_set.json")):
    seen |= {i["question"] for i in json.load(open(f, encoding="utf-8"))}
M.selftest()
M.items = []; M.R.seed(20261127)
for g in M.GENS:
    if g.__name__ not in HARD:
        continue
    tries = 0
    while sum(i["kind"] == g.__name__ for i in M.items) < N:
        tries += 1
        if tries > 5000: raise SystemExit(f"{g.__name__}: cannot find {N} new questions")
        before = len(M.items); g()
        if len(M.items) > before and (M.items[-1]["question"] in seen or
                                      M.items[-1]["question"] in {i["question"] for i in M.items[:-1]}):
            M.items.pop()
items = M.items
for i in items: i["id"] = "p2_" + i["id"]
assert len(items) == 7 * N and not ({i["question"] for i in items} & seen)
json.dump(items, open(os.path.join(HERE, "phase2_set.json"), "w", encoding="utf-8"), indent=1)
print("wrote phase2_set.json:", len(items), "problems,", {k: sum(i["kind"] == k for i in items) for k in HARD})
