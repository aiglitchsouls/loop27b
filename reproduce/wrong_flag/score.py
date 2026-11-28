"""Score the wrong-answer flags against the lines in PLAN.md.  python -I score.py [runs/flag.jsonl]"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "runs", "flag.jsonl")
rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def same(a, b):
    try:
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return False


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 2
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


FLAGS = {
    "F2 second method disagrees": lambda r: not same(r["got"], r["a2"]),
    "F3 loop needed a fix-and-retry": lambda r: len(r["tries"]) > 1,
    "F2 or F3": lambda r: (not same(r["got"], r["a2"])) or len(r["tries"]) > 1,
}
n = len(rows); E = sum(not r["ok"] for r in rows); base = E / n
lo, hi = wilson(E, n)
print(f"{n} problems, m1 wrong on {E} = {100*base:.1f}% (95% CI {100*lo:.1f}-{100*hi:.1f})")
if E < 10:
    print("UNDERPOWERED: fewer than 10 errors (PLAN.md: extend with the 3 hardest kinds before scoring)")
out = {"n": n, "errors": E, "base": base, "flags": {}}
for name, f in FLAGS.items():
    fl = [r for r in rows if f(r)]; tp = sum(not r["ok"] for r in fl)
    prec = tp / len(fl) if fl else float("nan"); rec = tp / E if E else float("nan")
    plo, phi = wilson(tp, len(fl))
    ok = len(fl) > 0 and prec >= 2 * base and rec >= 0.5
    out["flags"][name] = {"fires": len(fl), "caught": tp, "precision": prec, "recall": rec, "pass": ok}
    print(f"{name:34s} fires {len(fl):3d} ({100*len(fl)/n:4.1f}%)  precision {tp}/{len(fl)} = {100*prec:5.1f}% "
          f"(CI {100*plo:.0f}-{100*phi:.0f}, line {200*base:.1f}%)  recall {tp}/{E} = {100*rec:5.1f}%  "
          f"{'PASS' if ok else 'fail'}")
by = {}
for r in rows:
    k = by.setdefault(r["kind"], [0, 0, 0]); k[0] += 1; k[1] += not r["ok"]; k[2] += not same(r["got"], r["a2"])
print("by kind (n, m1 wrong, F2 fires):", {k: tuple(v) for k, v in by.items()})
fl = [r for r in rows if not same(r["got"], r["a2"])]
print(f"exploratory: when F2 fires, a2 is right on {sum(r['a2_ok'] for r in fl)}/{len(fl)}, a1 right on "
      f"{sum(r['ok'] for r in fl)}/{len(fl)}")
print(f"time: {sum(r['wall_s'] for r in rows)/n/60:.1f} min per problem (m1 alone {sum(r['wall1'] for r in rows)/n/60:.1f})")
json.dump(out, open(os.path.join(HERE, "score.json"), "w"), indent=1)
