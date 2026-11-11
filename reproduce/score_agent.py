"""Score a cloud-model answer file against a hard set.

  python score_agent.py practice opus_plain agent_out/practice_opus_plain.json

The answer file is {"q01": 123, ...} using the neutral ids from agent_in/<split>_questions.json.
Appends a summary line to hard_bench/rounds.jsonl and writes per-problem rows to runs/<split>_<label>.jsonl.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
split, label, path = sys.argv[1:4]
items = {i["id"]: i for i in json.load(open(os.path.join(HERE, f"math_hard_{split}.json"), encoding="utf-8"))}
idmap = json.load(open(os.path.join(HERE, f"{split}_idmap.json"), encoding="utf-8"))
ans = json.load(open(os.path.join(HERE, path), encoding="utf-8"))

rows, by = [], {}
for qid, real in idmap.items():
    it, got = items[real], ans.get(qid)
    try:
        ok = got is not None and int(str(got).replace(",", "")) == it["answer"]
    except ValueError:
        ok = False
    rows.append({"id": real, "kind": it["kind"], "answer": it["answer"], "got": got, "ok": ok})
    k = by.setdefault(it["kind"], [0, 0])
    k[0] += ok
    k[1] += 1
os.makedirs(os.path.join(HERE, "runs"), exist_ok=True)
with open(os.path.join(HERE, "runs", f"{split}_{label}.jsonl"), "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")
s = {"time": time.strftime("%Y-%m-%d %H:%M"), "job": f"{split}:{label}", "n": len(rows),
     "errors": sum(not r["ok"] for r in rows), "right": sum(r["ok"] for r in rows),
     "missing": sum(r["got"] is None for r in rows), "by_kind": {k: f"{a}/{b}" for k, (a, b) in by.items()}}
open(os.path.join(HERE, "rounds.jsonl"), "a", encoding="utf-8").write(json.dumps(s) + "\n")
print(json.dumps(s, indent=1))
