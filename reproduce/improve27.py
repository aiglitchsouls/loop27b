"""27B improvement loop: same weights, better setup around them.

Goal (agreed with the user 2026-11-05): the improved setup makes at most HALF as many mistakes as
the original 27B, on math and on coding separately, on problems the loop never tuned on.
"Original" = plain chat, thinking off, given room to finish (4096 tokens math, 2048 code) -- the
benchmark's 1024-token cap cut 16 of its answers off, which would make the target too easy.

Splits, fixed before any tuning:
  math dev  : math_dev.json (80: the benchmark's 10 kinds, new seed)
  code dev  : HumanEval tasks with even numbers (82)
  math test : benchmark 96 + math_test_new.json (40: 5 kinds never used in tuning)   LOCKED
  code test : HumanEval odd numbers (82) + the 8 original tasks                       LOCKED
The improved setup never sees hidden tests: coding self-checks use only the examples written in
the task's own docstring. Pass/fail always comes from the hidden tests.

Usage: python -I improve27.py JOB [JOB ...]        (jobs share one llama-server)
  examples-check                      parser check on canonical solutions (no server)
  dev-math:<variant>  dev-code:<variant>
  baseline                            original 27B, fair budgets, on the locked test
  baseline-think                      original 27B with thinking on (6144 tokens), whole locked test
  test:<math_variant>:<code_variant>  locked test (refuses after 2 uses)
"""
import ast
import gzip
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BENCH_DIR = os.path.join(ROOT, "bench_14b")
sys.path.insert(0, BENCH_DIR)
import bench  # noqa: E402  (prompts, code extraction, hidden-test runner, Server; frozen scaffold)

TMP = os.path.join(HERE, "tmp")
LOGS = os.path.join(HERE, "logs")
RUNS = os.path.join(HERE, "runs")
for d in (TMP, LOGS, RUNS):
    os.makedirs(d, exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = TMP
os.chdir(TMP)
bench.TMP = TMP
bench.RES = LOGS
bench.MODEL = os.path.join(ROOT, "models", "qwen3.8-27b", "Qwen3.8-27B-UD-Q4_K_M.gguf")
bench.PORT = 8095
SERVER_ARGS = ["-ngl", "26", "-fa", "on", "-c", "8192", "--spec-type", "draft-mtp"]  # = benchmark accuracy runs
BENCH27 = os.path.join(BENCH_DIR, "results_27b")
ROUNDS = os.path.join(HERE, "rounds.jsonl")
PY = bench.PY

MATH_BUDGET, MATH_THINK_BUDGET, OG_FAIR_MATH = 1024, 4096, 4096
CODE_BUDGET, CODE_THINK_BUDGET, OG_FAIR_CODE = 768, 4096, 2048
OG_THINK = 6144  # stronger baseline: the original with its thinking mode on (Qwen3 ships with it on)

MATH_VARIANTS = {
    "m0": {"retries": 0},                                   # = benchmark NEW: one script, no retry
    "m1": {"retries": 2},                                   # + fix-and-rerun when the script fails
    "m2": {"retries": 2, "verify": True},                   # + independent second method, thinking tie-break
    "m3": {"retries": 2, "think": True},                    # thinking on before writing the script
}
CODE_VARIANTS = {
    "c0": {},                                               # = original: one answer
    "c1": {"selftest": True, "retries": 2},                 # run the docstring examples, fix up to 2x
    "c2": {"selftest": True, "retries": 2, "think": True},  # same, thinking on
    "c3": {"think": True},                                  # thinking only
    "c4": {"selftest": True, "retries": 2, "budget": OG_FAIR_CODE, "cutoff_retry": True},  # c1 + same room as the
                                                            # fair baseline + "answer was cut off, be brief" retry
    "c5": {"selftest": True, "retries": 2, "think": True, "budget": OG_THINK, "cutoff_retry": True},  # c4 + thinking
    "c6": {"selftest": True, "retries": 2, "budget": OG_FAIR_CODE, "cutoff_retry": True, "keep_ok": True},  # c4 + the
                                                            # model may answer KEEP when a docstring example is wrong
}

FIX_MSG = ("Running your script failed: {err}\nFix it and return the complete corrected script in a ```python "
           "block. It must print only the final number.")
VERIFY_SYS = (bench.NEW_MATH_SYS + " Use a different method from a closed-form formula: brute-force enumeration "
              "or a step-by-step simulation, whenever that is feasible.")
SELFTEST_MSG = ("I ran the examples from the docstring against your function:\n{report}\n"
                "Fix the function and return the complete function in a ```python block.")
SELFTEST_KEEP_MSG = ("I ran the examples from the docstring against your function:\n{report}\n"
                     "Examples written in task descriptions are sometimes wrong. Work out each failing example by hand "
                     "from the written description. If the description clearly gives your function's result and the "
                     "example contradicts the description, end your reply with a line containing only KEEP and write "
                     "no code. Otherwise fix the function and return the complete function in a ```python block.")
CUTOFF_MSG = ("Your answer was cut off before the code was complete. Reply with only the complete function in one "
              "```python block: no explanation, no examples, no tests.")


def compiles(code):
    try:
        compile(code or "", "<answer>", "exec")
        return bool(code)
    except (SyntaxError, ValueError):
        return False


DENY = re.compile(r"\b(shutil|subprocess|socket|requests|urllib|ctypes|winreg|multiprocessing|"
                  r"os\.(remove|unlink|rmdir|removedirs|system|popen|startfile|rename|replace|kill|chmod|makedirs|mkdir))\b"
                  r"|open\s*\([^)]*['\"][wax]\+?b?['\"]")


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- model + sandbox

def chat(messages, max_tokens, think=False, timeout=3600):
    body = {"messages": messages, "temperature": 0.0, "max_tokens": max_tokens, "seed": 42,
            "chat_template_kwargs": {"enable_thinking": think}}
    req = urllib.request.Request(f"http://127.0.0.1:{bench.PORT}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        js = json.loads(r.read())
    msg = js["choices"][0]["message"]
    return {"text": msg.get("content") or "", "reasoning_chars": len(msg.get("reasoning_content") or ""),
            "finish": js["choices"][0].get("finish_reason"), "n_gen": js.get("usage", {}).get("completion_tokens") or 0,
            "decode_tok_s": js.get("timings", {}).get("predicted_per_second"), "wall_s": round(time.time() - t0, 2)}


def run_py(code, timeout=10):
    """Run model-written code with the venv Python in isolated mode, cwd and temp inside improve_27b/tmp.
    Code that touches files, processes or the network is refused before it runs."""
    m = DENY.search(code)
    if m:
        return False, "", f"refused to run: uses {m.group(0)!r} (file/process/network access is not allowed)"
    path = os.path.join(TMP, f"s_{time.time_ns()}.py")
    open(path, "w", encoding="utf-8").write(code)
    try:
        p = subprocess.run([PY, "-I", path], capture_output=True, text=True, timeout=timeout, cwd=TMP)
        if p.returncode == 0:
            return True, p.stdout.strip(), ""
        err = p.stderr.strip().splitlines()
        return False, p.stdout.strip(), err[-1][:300] if err else "error"
    except subprocess.TimeoutExpired:
        return False, "", f"timed out after {timeout} s"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def last_code(text):
    m = re.findall(r"```(?:python)?\s*\n?(.*?)```", text, re.DOTALL)
    return m[-1].strip() if m else None


def same(a, b):
    return a is not None and b is not None and abs(a - b) < 1e-6


# ---------------------------------------------------------------- math

def code_answer(sys_prompt, question, retries, think):
    msgs = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": question}]
    tries, gen, wall, r = [], 0, 0.0, None
    for _ in range(1 + retries):
        r = chat(msgs, MATH_THINK_BUDGET if think else MATH_BUDGET, think)
        gen, wall = gen + r["n_gen"], wall + r["wall_s"]
        code = last_code(r["text"])
        ok, out, err = run_py(code) if code else (False, "", "the reply has no ```python block")
        num = bench.Guardrails.extract_number(out) if ok and out else None
        if ok and num is None:
            err = f"the script printed no number (output: {out[:80]!r})"
        tries.append({"finish": r["finish"], "err": None if num is not None else err, "code": (code or "")[:600]})
        if num is not None:
            return num, tries, gen, wall
        msgs += [{"role": "assistant", "content": r["text"]}, {"role": "user", "content": FIX_MSG.format(err=err)}]
    return bench.Guardrails.extract_number(r["text"]), tries, gen, wall  # last resort, as in the benchmark


def solve_math(it, cfg):
    retries, think = cfg.get("retries", 0), cfg.get("think", False)
    a1, t1, gen, wall = code_answer(bench.NEW_MATH_SYS, it["question"], retries, think)
    row = {"a1": a1, "tries": t1}
    final = a1
    if cfg.get("verify"):
        a2, t2, g2, w2 = code_answer(VERIFY_SYS, it["question"], retries, False)
        gen, wall = gen + g2, wall + w2
        row.update(a2=a2, tries2=t2)
        if a1 is None:
            final = a2
        elif a2 is not None and not same(a1, a2):
            a3, t3, g3, w3 = code_answer(bench.NEW_MATH_SYS, it["question"], retries, True)
            gen, wall = gen + g3, wall + w3
            row.update(a3=a3, tries3=t3)
            final = a1 if same(a3, a1) else a2  # majority; with no majority trust the brute-force/simulation answer
    ok = same(final, it["answer"])
    return {"id": it["id"], "kind": it["kind"], "answer": it["answer"], "got": final, "ok": ok,
            "n_gen": gen, "wall_s": round(wall, 2), **row}


def og_math(it, budget=OG_FAIR_MATH, think=False):
    r = chat([{"role": "system", "content": bench.OG_MATH_SYS}, {"role": "user", "content": it["question"]}], budget, think)
    got, how = bench.number_from_og(r["text"])
    return {"id": it["id"], "kind": it["kind"], "answer": it["answer"], "got": got, "ok": same(got, it["answer"]),
            "how": how, "finish": r["finish"], "n_gen": r["n_gen"], "wall_s": r["wall_s"], "tail": r["text"][-300:]}


# ---------------------------------------------------------------- code: docstring examples

def _balanced_call(line, start):
    depth = 0
    for j in range(start, len(line)):
        if line[j] == "(":
            depth += 1
        elif line[j] == ")":
            depth -= 1
            if depth == 0:
                return j
    return None


def _literal(src):
    src = src.strip().rstrip(".,;")
    try:
        ast.literal_eval(src)
        return src
    except Exception:
        return None


def examples(prompt, entry):
    """(call, expected-literal) pairs written in the task's docstring. Formats: doctest '>>> f(x)' + next line,
    and 'f(x) => y' / '==>' / '->' / '==' / '➞' / 'should return'. Anything that does not parse is skipped."""
    out, lines = [], prompt.splitlines()
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith(">>>") and f"{entry}(" in s:
            call = s[3:].strip()
            exp = []
            for l2 in lines[i + 1:]:
                t = l2.strip()
                if not t or t.startswith(">>>") or t.startswith('"""') or t.startswith("'''"):
                    break
                exp.append(t)
            e = _literal(" ".join(exp)) if exp else None
            if e is not None:
                out.append((call, e))
    if out:
        return _parseable(out, prompt)
    for l in lines:
        idx = l.find(f"{entry}(")
        while idx != -1:
            if idx > 0 and (l[idx - 1].isalnum() or l[idx - 1] == "_"):
                idx = l.find(f"{entry}(", idx + 1)
                continue
            j = _balanced_call(l, idx + len(entry))
            if j is None:
                break
            call, rest = l[idx:j + 1], l[j + 1:].strip()
            m = re.match(r"^(==>|=>|->|➞|==|should return|returns)\s*(.+)$", rest)
            if m:
                val = m.group(2)
                e = _literal(val)
                if e is None and "=" in val:
                    e = _literal(val.split("=")[-1])
                if e is not None:
                    out.append((call, e))
            idx = l.find(f"{entry}(", j + 1)
    return _parseable(out, prompt)


def _parseable(pairs, prompt):
    """Keep examples whose call is valid Python and uses no undefined names (docstrings sometimes write
    is_happy(a) meaning the string 'a')."""
    import builtins
    keep = []
    for call, exp in pairs:
        try:
            tree = ast.parse(call, mode="eval")
        except SyntaxError:
            continue
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        free = [n for n in names if not hasattr(builtins, n) and not re.search(rf"(def|class)\s+{re.escape(n)}\b|^\s*{re.escape(n)}\s*=|import.*\b{re.escape(n)}\b", prompt, re.M)]
        if not free:
            keep.append((call, exp))
    return list(dict.fromkeys(keep))


RUNNER = '''
import json as __json
__EX = __json.loads({ex!r})
__res = []
for __call, __exp_src in __EX:
    try:
        __got = eval(__call)
        __exp = eval(__exp_src)
        __ok = __got == __exp or (isinstance(__got, float) and isinstance(__exp, (int, float)) and abs(__got - __exp) < 1e-6)
        __res.append([bool(__ok), repr(__got)[:150]])
    except Exception as __e:
        __res.append([False, "raised " + type(__e).__name__ + ": " + str(__e)[:120]])
print("__RESULTS__" + __json.dumps(__res))
'''


def run_examples(code, exs):
    ok, out, err = run_py(code + "\n\n" + RUNNER.format(ex=json.dumps(exs)), timeout=10)
    line = next((l for l in out.splitlines()[::-1] if l.startswith("__RESULTS__")), None)
    if line is None:
        return [[False, err or "no result"] for _ in exs]
    return json.loads(line[len("__RESULTS__"):])


def hidden_tests(code, it):
    m = DENY.search(code)
    if m:  # same guard for original and improved answers
        return False, f"refused to run: uses {m.group(0)!r}"
    return bench.run_tests(code, it)


def code_items_split(split):
    items = bench.code_items()
    num = lambda it: int(it["id"].split("/")[1]) if it["set"] == "humaneval" else None  # noqa: E731
    if split == "dev":
        return [it for it in items if it["set"] == "humaneval" and num(it) % 2 == 0]
    return [it for it in items if it["set"] == "original8" or num(it) % 2 == 1]


def solve_code(it, cfg):
    think, selftest = cfg.get("think", False), cfg.get("selftest", False)
    exs = examples(it["prompt"], it["entry_point"]) if selftest else []
    msgs = [{"role": "system", "content": bench.CODE_SYS},
            {"role": "user", "content": f"Complete this function:\n{it['prompt']}"}]
    attempts, gen, wall, kept = [], 0, 0.0, False
    budget = cfg.get("budget", CODE_THINK_BUDGET if think else CODE_BUDGET)
    cutoff_retry = cfg.get("cutoff_retry", False)
    n_try = 1 + (cfg.get("retries", 0) if (exs or cutoff_retry) else 0)
    for k in range(n_try):
        r = chat(msgs, budget, think)
        gen, wall = gen + r["n_gen"], wall + r["wall_s"]
        code = bench.extract(r["text"], it)
        if k and cfg.get("keep_ok") and "```" not in r["text"] and re.search(r"^\W*KEEP\W*$", r["text"], re.M):
            attempts[-1]["npass"] = len(exs)  # the model judged the example wrong: its previous answer stands
            kept = True
            break
        cut = cutoff_retry and r["finish"] == "length" and not compiles(code)
        res = run_examples(code, exs) if exs else []
        npass = -1 if cut else sum(1 for ok, _ in res if ok)  # a cut-off answer never wins the pick
        attempts.append({"k": k, "code": code, "npass": npass, "finish": r["finish"]})
        if not cut and npass == len(exs):
            break
        if cut:
            nxt = CUTOFF_MSG
        else:
            report = "\n".join(f"- {c}  -> got {g}, expected {e}" for (c, e), (ok, g) in zip(exs, res) if not ok)
            nxt = (SELFTEST_KEEP_MSG if cfg.get("keep_ok") else SELFTEST_MSG).format(report=report)
        msgs += [{"role": "assistant", "content": r["text"]}, {"role": "user", "content": nxt}]
    best = max(attempts, key=lambda a: (a["npass"], -a["k"]))  # most examples passed; ties -> earliest answer
    ok, err = hidden_tests(best["code"], it)  # scoring only, never shown to the model
    first_ok = ok if best["k"] == 0 else hidden_tests(attempts[0]["code"], it)[0]  # = the plain one-shot answer
    return {"id": it["id"], "set": it["set"], "ok": ok, "err": None if ok else err, "first_ok": first_ok, "n_examples": len(exs),
            "examples_passed": best["npass"], "attempts": len(attempts), "picked": best["k"], "kept": kept,
            "finish": attempts[0]["finish"], "n_gen": gen, "wall_s": round(wall, 2)}


def og_code(it, budget=OG_FAIR_CODE, think=False):
    r = chat([{"role": "system", "content": bench.CODE_SYS},
              {"role": "user", "content": f"Complete this function:\n{it['prompt']}"}], budget, think)
    ok, err = hidden_tests(bench.extract(r["text"], it), it)
    return {"id": it["id"], "set": it["set"], "ok": ok, "err": None if ok else err, "finish": r["finish"],
            "n_gen": r["n_gen"], "wall_s": r["wall_s"]}


# ---------------------------------------------------------------- bookkeeping

def run_items(name, items, one, label):
    part = os.path.join(RUNS, f"{name}.jsonl")
    prev = {}
    if os.path.exists(part):
        for line in open(part, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                prev[r["id"]] = r
    rows = []
    with open(part, "a", encoding="utf-8") as f:
        for it in items:
            if it["id"] in prev:
                rows.append(prev[it["id"]])
                continue
            r = one(it)
            f.write(json.dumps(r) + "\n")
            f.flush()
            rows.append(r)
            say(label, r["id"], "PASS" if r["ok"] else "FAIL", r.get("got", r.get("err", "")), f"{r['wall_s']}s")
    return rows


def record(job, rows, **extra):
    s = {"time": time.strftime("%Y-%m-%d %H:%M"), "job": job, "n": len(rows), "errors": sum(not r["ok"] for r in rows),
         "failed": [r["id"] for r in rows if not r["ok"]], "mean_wall_s": round(sum(r["wall_s"] for r in rows) / len(rows), 1),
         "mean_gen": round(sum(r["n_gen"] for r in rows) / len(rows)), **extra}
    open(ROUNDS, "a", encoding="utf-8").write(json.dumps(s) + "\n")
    say("RESULT", job, f"{s['errors']} errors / {s['n']}", f"mean {s['mean_wall_s']} s", extra or "")
    return s


def load(path):
    return json.load(open(path, encoding="utf-8"))


def math_test_items():
    return bench.math_items() + load(os.path.join(HERE, "math_test_new.json"))


def og_fair(kind):
    """Original 27B on the locked test with room to finish: the benchmark answer, replaced by the baseline rerun
    wherever the benchmark cut it off."""
    if kind == "math":
        base = {r["id"]: r for r in load(os.path.join(BENCH27, "math_og.json"))}
        items = math_test_items()
    else:
        base = {r["id"]: {**r, "ok": r["og_ok"]} for r in load(os.path.join(BENCH27, "code.json"))}
        items = code_items_split("test")
    for name in (f"baseline_{kind}_rerun", f"baseline_{kind}_new"):
        p = os.path.join(RUNS, f"{name}.jsonl")
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    base[r["id"]] = r
    return {it["id"]: base.get(it["id"]) for it in items}


# ---------------------------------------------------------------- jobs

def job_examples_check():
    """How good is the docstring parser? Canonical solutions should pass every extracted example."""
    rows = [json.loads(l) for l in gzip.open(os.path.join(ROOT, "model_carving_lab", "HumanEval.jsonl.gz"), "rt", encoding="utf-8")]
    tasks_with, n_ex, n_fail, bad = 0, 0, 0, []
    for t in rows:
        exs = examples(t["prompt"], t["entry_point"])
        if not exs:
            continue
        tasks_with += 1
        res = run_examples(t["prompt"] + t["canonical_solution"], exs)
        n_ex += len(exs)
        f = [(c, e, g) for (c, e), (ok, g) in zip(exs, res) if not ok]
        n_fail += len(f)
        if f:
            bad.append((t["task_id"], f[:2]))
    say(f"tasks with usable examples: {tasks_with}/164; examples: {n_ex}; canonical solution fails {n_fail}")
    for b in bad:
        say("  ", b)


def job_dev_math(variant):
    rows = run_items(f"dev_math_{variant}", load(os.path.join(HERE, "math_dev.json")),
                     lambda it: solve_math(it, MATH_VARIANTS[variant]), f"math {variant}")
    by = {}
    for r in rows:
        by.setdefault(r["kind"], [0, 0])
        by[r["kind"]][0] += not r["ok"]
        by[r["kind"]][1] += 1
    record(f"dev-math:{variant}", rows, by_kind={k: f"{e}/{n} wrong" for k, (e, n) in by.items()})


def job_dev_code(variant):
    items = code_items_split("dev")
    rows = run_items(f"dev_code_{variant}", items, lambda it: solve_code(it, CODE_VARIANTS[variant]), f"code {variant}")
    og = {r["id"]: r for r in load(os.path.join(BENCH27, "code.json"))}
    record(f"dev-code:{variant}", rows, og_errors_same_tasks=sum(not og[it["id"]]["og_ok"] for it in items),
           fixed=[r["id"] for r in rows if r["ok"] and not og[r["id"]]["og_ok"]],
           broke=[r["id"] for r in rows if not r["ok"] and og[r["id"]]["og_ok"]])


def job_baseline():
    og = {r["id"]: r for r in load(os.path.join(BENCH27, "math_og.json"))}
    cut = [it for it in bench.math_items() if og[it["id"]]["finish"] == "length"]
    say("baseline: math answers the benchmark cut off at 1024 tokens:", len(cut))
    run_items("baseline_math_rerun", cut, og_math, "og-math-4096")
    run_items("baseline_math_new", load(os.path.join(HERE, "math_test_new.json")), og_math, "og-math-new")
    code = {r["id"]: r for r in load(os.path.join(BENCH27, "code.json"))}
    cutc = [it for it in code_items_split("test") if code[it["id"]]["finish"] == "length"]
    say("baseline: code answers cut off at 768 tokens:", len(cutc))
    run_items("baseline_code_rerun", cutc, og_code, "og-code-2048")
    for kind in ("math", "code"):
        fair = og_fair(kind)
        missing = [k for k, v in fair.items() if v is None]
        assert not missing, missing
        record(f"baseline-{kind}", list(fair.values()))


def job_baseline_think():
    """Original 27B with thinking ON on the whole locked test. The benchmark showed thinking alone fixes its
    math (40/40 on the hardest 40), so a fair "2x" claim has to beat this too."""
    for kind, items, one in (("math", math_test_items(), lambda it: og_math(it, OG_THINK, True)),
                             ("code", code_items_split("test"), lambda it: og_code(it, OG_THINK, True))):
        rows = run_items(f"baseline_think_{kind}", items, one, f"og-think-{kind}")
        record(f"baseline-think-{kind}", rows, capped=sum(r["finish"] == "length" for r in rows))


def og_think_rows(kind):
    p = os.path.join(RUNS, f"baseline_think_{kind}.jsonl")
    if not os.path.exists(p):
        return {}
    return {r["id"]: r for r in (json.loads(l) for l in open(p, encoding="utf-8") if l.strip())}


def job_test(mv, cv):
    uses = [json.loads(l) for l in open(ROUNDS, encoding="utf-8")] if os.path.exists(ROUNDS) else []
    if sum(1 for u in uses if u["job"].startswith("test-math")) >= 2:
        raise SystemExit("locked test already used twice; not running it again")
    out = {}
    for kind, items, solve, variant in (("math", math_test_items(), lambda it: solve_math(it, MATH_VARIANTS[mv]), mv),
                                        ("code", code_items_split("test"), lambda it: solve_code(it, CODE_VARIANTS[cv]), cv)):
        rows = run_items(f"test_{kind}_{variant}", items, solve, f"TEST {kind} {variant}")
        fair = og_fair(kind)
        og_err = sum(not fair[r["id"]]["ok"] for r in rows)
        new_err = sum(not r["ok"] for r in rows)
        th = og_think_rows(kind)
        th_err = sum(not th[r["id"]]["ok"] for r in rows) if len(th) == len(rows) else None
        out[kind] = record(f"test-{kind}:{variant}", rows, og_errors=og_err,
                           target_met=new_err * 2 <= og_err, og_think_errors=th_err,
                           target_met_vs_think=None if th_err is None else new_err * 2 <= th_err,
                           og_mean_wall_s=round(sum(fair[r["id"]]["wall_s"] for r in rows) / len(rows), 1))
    say("TARGET", "MET" if all(o["target_met"] for o in out.values()) else "NOT MET",
        {k: f"{o['errors']} vs original {o['og_errors']}" for k, o in out.items()})


def no_other_llama():
    p = subprocess.run(["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"], capture_output=True, text=True)
    return "llama-server.exe" not in p.stdout


if __name__ == "__main__":
    jobs = sys.argv[1:]
    if jobs == ["examples-check"]:
        job_examples_check()
        raise SystemExit
    if not no_other_llama():
        raise SystemExit("another llama-server is running (the benchmark?); refusing to start a second 27B")
    with bench.Server("improve", SERVER_ARGS) as s:
        say("server", s.ok, SERVER_ARGS)
        if not s.ok:
            raise SystemExit("server failed to start; see logs/server_improve.log")
        for job in jobs:
            say("=== job", job)
            name, *args = job.split(":")
            {"dev-math": job_dev_math, "dev-code": job_dev_code, "baseline": job_baseline,
             "baseline-think": job_baseline_think, "test": job_test}[name](*args)
    say("ALL JOBS DONE")
