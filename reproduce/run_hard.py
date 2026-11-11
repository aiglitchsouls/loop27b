"""Run the local 27B on the hard math sets. Reuses improve_27b/improve27.py (server, sandbox, solvers).

  python run_hard.py practice:og practice:m1     plain model / Python loop on the 40 practice problems
  python run_hard.py locked:og locked:m1         same on the 80 locked problems (score only, never tune on these)

Rows are saved per problem in hard_bench/runs/*.jsonl (a re-run resumes); summaries go to hard_bench/rounds.jsonl.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "improve_27b"))
import improve27 as imp  # noqa: E402

imp.RUNS = os.path.join(HERE, "runs")
imp.ROUNDS = os.path.join(HERE, "rounds.jsonl")
os.makedirs(imp.RUNS, exist_ok=True)

SETS = {"practice": "math_hard_practice.json", "locked": "math_hard_locked.json"}
VARIANTS = {
    "og": lambda it: imp.og_math(it),                                  # plain model, 4096 tokens, thinking off
    "m1": lambda it: imp.solve_math(it, imp.MATH_VARIANTS["m1"]),      # writes Python, 2 fix-and-rerun tries
}


def job(split, variant):
    items = json.load(open(os.path.join(HERE, SETS[split]), encoding="utf-8"))
    rows = imp.run_items(f"{split}_{variant}", items, VARIANTS[variant], f"{split} {variant}")
    by = {}
    for r in rows:
        k = by.setdefault(r["kind"], [0, 0])
        k[0] += r["ok"]
        k[1] += 1
    imp.record(f"{split}:{variant}", rows, right=sum(r["ok"] for r in rows),
               by_kind={k: f"{a}/{b}" for k, (a, b) in by.items()})


if __name__ == "__main__":
    if not imp.no_other_llama():
        raise SystemExit("another llama-server is running; refusing to start a second 27B")
    with imp.bench.Server("hard", imp.SERVER_ARGS) as s:
        imp.say("server", s.ok, imp.SERVER_ARGS)
        if not s.ok:
            raise SystemExit("server failed to start")
        for j in sys.argv[1:]:
            imp.say("=== job", j)
            job(*j.split(":"))
    imp.say("ALL JOBS DONE")
