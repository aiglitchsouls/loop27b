"""Side-by-side table of the four setups on the 40 hard practice problems -> PRACTICE_RESULTS.md.

  python -I practice_report.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETUPS = [("og", "Local 27B, plain"), ("m1", "Local 27B + Python loop"),
          ("opus_plain", "Opus, no tools"), ("opus_tools", "Opus + Python")]
NOTES = {"opus_plain": "14 min total (one subagent)", "opus_tools": "52 s total (one subagent)"}

rows = {}
for key, _ in SETUPS:
    p = os.path.join(HERE, "runs", f"practice_{key}.jsonl")
    rows[key] = [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []

kinds = sorted({r["kind"] for rs in rows.values() for r in rs})
out = ["# Hard math practice set: 40 problems, 10 kinds x 4", "",
       "Answers are exact integers, each checked by two independent methods. Opus = current Opus run as a "
       "Claude Code subagent (not Opus 4.5, not a clean API call).", "",
       "| Kind | " + " | ".join(n for _, n in SETUPS) + " |", "|---|" + "---|" * len(SETUPS)]
for k in kinds:
    cells = []
    for key, _ in SETUPS:
        rs = [r for r in rows[key] if r["kind"] == k]
        cells.append(f"{sum(r['ok'] for r in rs)}/{len(rs)}" if rs else "-")
    out.append(f"| {k} | " + " | ".join(cells) + " |")
tot, times = [], []
for key, _ in SETUPS:
    rs = rows[key]
    tot.append(f"**{sum(r['ok'] for r in rs)}/{len(rs)}**" if rs else "-")
    w = [r["wall_s"] for r in rs if "wall_s" in r]
    times.append(f"{sum(w) / len(w) / 60:.1f} min/problem" if w else NOTES.get(key, "-"))
out += ["| **Total** | " + " | ".join(tot) + " |", "| Time | " + " | ".join(times) + " |", ""]
open(os.path.join(HERE, "PRACTICE_RESULTS.md"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
