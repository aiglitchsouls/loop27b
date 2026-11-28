"""Score Phase 2 (PHASE2_PLAN.md lines).  python -I score2.py [runs/phase2.jsonl]"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "runs", "phase2.jsonl")
sys.path.insert(0, HERE)
from step1 import same, rule_T, take_a2  # noqa: E402  (importing step1 chdirs into improve_27b/tmp)
R = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
use_T = bool(R and R[0].get("use_T"))


def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return 100 * (c - h) / d, 100 * (c + h) / d


def policy(r, gate, tie):
    if not gate(r):
        return r["got"], r["wall1"]
    t = r["wall1"] + r["wall2"]
    if same(r["got"], r["a2"]):
        return r["got"], t
    if tie:
        return rule_T(r["got"], r["a2"], r["a3"]), t + r["wall3"]
    return take_a2(r["got"], r["a2"]), t


always = lambda r: True
retry = lambda r: len(r["tries"]) > 1
P = {"P0 m1 alone": (lambda r: False, False), "P1 always check": (always, False), "P2 check on retry": (retry, False)}
if use_T:
    P.update({"P1+T always check + tie-break": (always, True), "P2+T check on retry + tie-break": (retry, True)})
n = len(R); res = {}
for name, (gate, tie) in P.items():
    out = [policy(r, gate, tie) for r in R]
    wrong = sum(not same(a, r["answer"]) for (a, _), r in zip(out, R))
    broke = sum(same(r["got"], r["answer"]) and not same(a, r["answer"]) for (a, _), r in zip(out, R))
    fixed = sum(not same(r["got"], r["answer"]) and same(a, r["answer"]) for (a, _), r in zip(out, R))
    mins = sum(t for _, t in out) / n / 60
    res[name] = {"wrong": wrong, "fixed": fixed, "broke": broke, "min": mins}
    lo, hi = wilson(wrong, n)
    print(f"{name:32s} wrong {wrong:3d}/{n} ({100*wrong/n:.1f}%, CI {lo:.0f}-{hi:.0f})  fixed {fixed:2d} broke {broke}  "
          f"{mins:.2f} min/problem")
m1 = res["P0 m1 alone"]
prim, alw = ("P2+T check on retry + tie-break", "P1+T always check + tie-break") if use_T else ("P2 check on retry", "P1 always check")
p, a = res[prim], res[alw]
extra_p, extra_a = p["min"] - m1["min"], a["min"] - m1["min"]
halves = p["wrong"] <= m1["wrong"] / 2
near = p["wrong"] <= a["wrong"] + 2
cheap = extra_a > 0 and extra_p <= 0.6 * extra_a
verdict = "PASS" if halves and near and cheap else ("WEAK PASS" if halves else "KILL")
print(f"\nprimary {prim}: {p['wrong']} wrong vs m1 {m1['wrong']} (halves: {halves}); vs always-check {a['wrong']} "
      f"(within 2: {near}); extra {extra_p:.2f} vs {extra_a:.2f} min = {100*extra_p/max(extra_a,1e-9):.0f}% (line 60%: {cheap})")
if m1["wrong"] < 10: print("UNDERPOWERED: m1 made fewer than 10 errors; add 15 each of dioph_count, seating_forbidden, tilings_blocked")
print("errors removed per extra minute (per problem):", {k: round((m1['wrong'] - v['wrong']) / max(v['min'] - m1['min'], 1e-9) / n, 3)
                                                     for k, v in res.items() if k != "P0 m1 alone"})
print("by kind (n, m1 wrong, primary wrong):", {k: (sum(r['kind'] == k for r in R), sum(r['kind'] == k and not r['ok'] for r in R),
      sum(r['kind'] == k and not same(policy(r, *P[prim])[0], r['answer']) for r in R)) for k in dict.fromkeys(r['kind'] for r in R)})
print("Verdict:", verdict)
json.dump({"policies": res, "primary": prim, "verdict": verdict}, open(os.path.join(HERE, "score2.json"), "w"), indent=1)
