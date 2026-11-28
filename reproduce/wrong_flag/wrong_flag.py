"""Wrong-answer flag test (backlog idea #4), see PLAN.md.

For each problem in flag_set.json, the local 27B answers twice with the existing improve_27b tools:
  a1 = the deployed loop m1 (writes Python, up to 2 fix-and-rerun tries)       <- the answer a user would get
  a2 = an independent second program (VERIFY_SYS: brute force / simulation where feasible, same retries)
Flags are scored afterwards by score.py; nothing here looks at the answer key except to store 'ok'.

  python -I wrong_flag.py            full run (resumable, rows in runs/flag.jsonl)
  python -I wrong_flag.py --smoke    first 2 problems, rows in runs/smoke.jsonl
Waits until no Stage D training process (stage_d.py) is running, so the GPU holds one job only.
"""
import ctypes
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "improve_27b"))
import improve27 as imp  # noqa: E402  (sets TEMP/TMP under D:\timepass and chdirs to improve_27b/tmp)

imp.RUNS = os.path.join(HERE, "runs")
imp.ROUNDS = os.path.join(HERE, "rounds.jsonl")
os.makedirs(imp.RUNS, exist_ok=True)
bench = imp.bench


def awake():
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)


def gpu_busy():
    cmd = ("(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
           "Where-Object { $_.CommandLine -like '*stage_d.py*' -or $_.CommandLine -like '*tag_capture.py*' -or $_.CommandLine -like '*tail.py*' }).Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True).stdout.strip()
    return out not in ("", "0")


def one(it):
    awake()
    a1, t1, g1, w1 = imp.code_answer(bench.NEW_MATH_SYS, it["question"], 2, False)   # = m1
    a2, t2, g2, w2 = imp.code_answer(imp.VERIFY_SYS, it["question"], 2, False)       # second method
    return {"id": it["id"], "kind": it["kind"], "answer": it["answer"], "got": a1, "ok": imp.same(a1, it["answer"]),
            "a2": a2, "a2_ok": imp.same(a2, it["answer"]), "tries": t1, "tries2": t2,
            "n_gen": g1 + g2, "gen1": g1, "wall_s": round(w1 + w2, 2), "wall1": round(w1, 2)}


if __name__ == "__main__":
    smoke = "--smoke" in sys.argv
    items = json.load(open(os.path.join(HERE, "flag_set.json"), encoding="utf-8"))
    if smoke:
        items = items[:2]
    while gpu_busy():
        imp.say("waiting for Stage D training to finish")
        awake()
        time.sleep(120)
    if not imp.no_other_llama():
        raise SystemExit("another llama-server is running; refusing to start a second 27B")
    with bench.Server("flag", imp.SERVER_ARGS) as s:
        imp.say("server", s.ok, imp.SERVER_ARGS)
        if not s.ok:
            raise SystemExit("server failed to start")
        rows = imp.run_items("smoke" if smoke else "flag", items, one, "flag")
        imp.record("smoke" if smoke else "flag", rows, right=sum(r["ok"] for r in rows))
    imp.say("ALL DONE")
