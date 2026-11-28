"""Phase 2 Step 2, the locked test (PHASE2_PLAN.md + addendum). For each problem in phase2_set.json: a1 = m1, a2 = the
second program (VERIFY_SYS); if Step 1 adopted the tie-break T, a3 = m1 with thinking on, run on every disagreement.
  python -I step2.py     rows in runs/phase2.jsonl (resumable); scored by score2.py
Waits for Step 1 (step1.py) and any other GPU job to finish first.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wrong_flag as W  # noqa: E402
from step1 import same  # noqa: E402

imp, bench = W.imp, W.bench


def step1_running():
    cmd = ("(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
           "Where-Object { $_.CommandLine -like '*step1.py*' }).Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True).stdout.strip()
    return out not in ("", "0")


def adopted():
    rows = [json.loads(l) for l in open(os.path.join(HERE, "runs", "step1.jsonl"), encoding="utf-8") if l.strip()]
    if len(rows) != 21:
        raise SystemExit(f"Step 1 has {len(rows)}/21 rows; finish it first")
    nT, nA = sum(r["T_ok"] for r in rows), sum(r["a2rule_ok"] for r in rows)
    return nT - nA >= 2, nT, nA


if __name__ == "__main__":
    while step1_running() or W.gpu_busy():  # still guards against overlap
        imp.say("waiting for Step 1 / another GPU job"); W.awake(); time.sleep(120)
    use_T = False   # tie-break dropped on cost after 3/21 Step-1 problems (PHASE2_PLAN.md, "Deviation"); adopted() unused
    imp.say("Step 1 stopped early: tie-break dropped on cost -> cheap rules only (a1 + a2)")
    if not imp.no_other_llama():
        raise SystemExit("another llama-server is running; refusing to start a second 27B")
    items = json.load(open(os.path.join(HERE, "phase2_set.json"), encoding="utf-8"))

    def one(it):
        W.awake(); q = it["question"]
        a1, t1, g1, w1 = imp.code_answer(bench.NEW_MATH_SYS, q, 2, False)
        a2, t2, g2, w2 = imp.code_answer(imp.VERIFY_SYS, q, 2, False)
        a3 = t3 = None; g3 = w3 = 0
        if use_T and not same(a1, a2):
            a3, t3, g3, w3 = imp.code_answer(bench.NEW_MATH_SYS, q, 2, True)
        return {"id": it["id"], "kind": it["kind"], "answer": it["answer"], "got": a1, "ok": same(a1, it["answer"]),
                "a2": a2, "a3": a3, "tries": t1, "tries2": t2, "tries3": t3, "use_T": use_T,
                "n_gen": g1 + g2 + g3, "wall1": round(w1, 2), "wall2": round(w2, 2), "wall3": round(w3, 2),
                "wall_s": round(w1 + w2 + w3, 2)}

    with bench.Server("phase2", imp.SERVER_ARGS) as s:
        imp.say("server", s.ok, imp.SERVER_ARGS)
        if not s.ok:
            raise SystemExit("server failed to start")
        rows = imp.run_items("phase2", items, one, "phase2")
    imp.say("ALL DONE", len(rows), "rows; score with: python -I score2.py")
