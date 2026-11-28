"""Phase 2 Step 1 (see PHASE2_PLAN.md + addendum): thinking tie-break a3 on the 21 Phase-1 disagreements.
  python -I step1.py      rows in runs/step1.jsonl (resumable), decision printed at the end
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wrong_flag as W  # noqa: E402  (sets up improve27 paths, gpu_busy, awake)

imp, bench = W.imp, W.bench


def same(a, b):
    try:
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return False


def rule_T(a1, a2, a3):
    vals = [v for v in (a1, a2, a3) if v is not None]
    for v in vals:
        if sum(same(v, w) for w in vals) >= 2:
            return v
    return a3 if a3 is not None else (a2 if a2 is not None else a1)


def rule_m2(a1, a2, a3):
    if a1 is None: return a2
    if a2 is None: return a1
    return a1 if same(a3, a1) else a2


def take_a2(a1, a2):
    return a2 if a2 is not None else a1


if __name__ == "__main__":
    flag = [json.loads(l) for l in open(os.path.join(HERE, "runs", "flag.jsonl"), encoding="utf-8") if l.strip()]
    dis = {r["id"]: r for r in flag if not same(r["got"], r["a2"])}
    qs = {i["id"]: i for i in json.load(open(os.path.join(HERE, "flag_set.json"), encoding="utf-8"))}
    items = [qs[i] for i in dis]
    assert len(items) == 21, len(items)
    while W.gpu_busy():
        imp.say("waiting for another GPU job"); W.awake(); time.sleep(120)
    if not imp.no_other_llama():
        raise SystemExit("another llama-server is running; refusing to start a second 27B")

    def one(it):
        W.awake(); p = dis[it["id"]]
        a3, t3, g3, w3 = imp.code_answer(bench.NEW_MATH_SYS, it["question"], 2, True)
        T, M2, A2 = rule_T(p["got"], p["a2"], a3), rule_m2(p["got"], p["a2"], a3), take_a2(p["got"], p["a2"])
        return {"id": it["id"], "kind": it["kind"], "answer": it["answer"], "a1": p["got"], "a2": p["a2"], "got": a3,
                "ok": same(a3, it["answer"]), "T": T, "T_ok": same(T, it["answer"]), "m2_ok": same(M2, it["answer"]),
                "a2rule_ok": same(A2, it["answer"]), "tries3": t3, "n_gen": g3, "wall_s": round(w3, 2)}

    with bench.Server("step1", imp.SERVER_ARGS) as s:
        imp.say("server", s.ok, imp.SERVER_ARGS)
        if not s.ok:
            raise SystemExit("server failed to start")
        rows = imp.run_items("step1", items, one, "step1")
    nT, nM, nA = (sum(r[k] for r in rows) for k in ("T_ok", "m2_ok", "a2rule_ok"))
    imp.say(f"RESULT step1: a3 alone {sum(r['ok'] for r in rows)}/21, rule T {nT}/21, old m2 rule {nM}/21, take-a2 {nA}/21; "
            f"T {'ADOPTED' if nT - nA >= 2 else 'NOT adopted'} (net {nT - nA:+d}, line +2); "
            f"mean {sum(r['wall_s'] for r in rows)/len(rows)/60:.1f} min per a3")
    imp.say("ALL DONE")
