"""loop27b: Qwen3.8-27B on an 8 GB GPU, made more accurate by two loops around it. No retraining: same weights.

  python -I loop27b.py math "How many integers from 1 to 10**12 are divisible by 3, 5 or 7 but not 11?"
  python -I loop27b.py code task.py            (a function stub with a docstring; examples in it are used)
  python -I loop27b.py selftest                (checks the sandbox and parsers; no model needed)

Options: --port N attaches to a llama-server already running on N instead of starting one.
         --model PATH (default: the 27B Q4 GGUF in D:\\timepass\\models).
         --exact uses the server flags of the published results (MTP drafting only), for byte-identical re-runs.
         code adds n-gram lookup drafting by default: ~1.2x faster first tries, ~2.9x faster rewrites, same
         answers except rare differences at near-ties. math always drafts with MTP only: its short new scripts
         have nothing to copy, and n-gram made them 8% slower.

Math loop ("m1" in the experiments): the model writes a Python script; the sandbox runs it; the printed number is
the answer. If the script crashes or prints no number, the error goes back with "fix it" (up to 2 times).
Check on retry (default; --no-check is plain m1): if a fix was needed, a second program with a different method solves
it again; on disagreement its answer is used and the output says CHECK THIS. 105 fresh hard problems: 17 -> 8 wrong.
Code loop ("c6"): the model writes the function; the examples written in the task are run against it; failures go
back with "fix it" (up to 2 times), or the model may reply KEEP when it judges the example itself wrong. The answer
that passes the most examples wins (ties: the earliest). A cut-off answer gets "resend only the code".

Everything here is copied from the tested code (D:\\timepass\\improve_27b\\improve27.py and
D:\\timepass\\bench_14b\\bench.py, frozen in reproduce/): prompts, token budgets, temperature 0, seed 42, server flags.

The sandbox is a blocklist, not a container: model code runs with this venv's Python in isolated mode, in tmp/, with
a 10 s limit, and code naming file-writing, process or network modules is refused before it runs.
"""
import argparse
import ast
import builtins
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = os.path.join(HERE, "tmp")
PY = sys.executable
LLAMA = os.path.join(ROOT, "llama_cpp_bin", "llama-server.exe")
MODEL = os.path.join(ROOT, "models", "qwen3.8-27b", "Qwen3.8-27B-UD-Q4_K_M.gguf")
SERVER_ARGS = ["-ngl", "26", "-fa", "on", "-c", "8192"]   # as tested on the RTX 4060
# Draft types for speculative decoding. The model's MTP head plus n-gram lookup (copies from earlier text) made
# fix-and-rewrite passes ~2.9x faster on 2026-11-23 (results/ngram_drafting.md), but greedy output
# can differ at near-ties (2/20 rewrites changed one word). EXACT_SPEC is what produced the published results.
# First tries (audit, 20 + 20 dev items): code 1.19x faster, math 0.92x (slower), so math always uses EXACT_SPEC.
SPEC = "draft-mtp,ngram-simple"
EXACT_SPEC = "draft-mtp"
DEFAULT_PORT = 8096

MATH_BUDGET, CODE_BUDGET, RETRIES = 1024, 2048, 2
MATH_SYS = (
    "You are an expert computational problem solver. "
    "Solve the following problem by writing a concise, self-contained Python script inside a ```python ``` block. "
    "Calculate the exact result and conclude with `print(ans)` (or print the exact numerical value). "
    "Do not write conversational preamble. Let Python compute the answer."
)
# Second method for the check-on-retry step (tested 2026-11-27/28 in D:\timepass\wrong_flag, results/wrong_flag.md).
VERIFY_SYS = (MATH_SYS + " Use a different method from a closed-form formula: brute-force enumeration "
              "or a step-by-step simulation, whenever that is feasible.")
CODE_SYS = "You are an expert Python coder. Return the complete function in a ```python ``` block."
FIX_MSG = ("Running your script failed: {err}\nFix it and return the complete corrected script in a ```python "
           "block. It must print only the final number.")
SELFTEST_KEEP_MSG = ("I ran the examples from the docstring against your function:\n{report}\n"
                     "Examples written in task descriptions are sometimes wrong. Work out each failing example by hand "
                     "from the written description. If the description clearly gives your function's result and the "
                     "example contradicts the description, end your reply with a line containing only KEEP and write "
                     "no code. Otherwise fix the function and return the complete function in a ```python block.")
CUTOFF_MSG = ("Your answer was cut off before the code was complete. Reply with only the complete function in one "
              "```python block: no explanation, no examples, no tests.")

DENY = re.compile(r"\b(shutil|subprocess|socket|requests|urllib|ctypes|winreg|multiprocessing|"
                  r"os\.(remove|unlink|rmdir|removedirs|system|popen|startfile|rename|replace|kill|chmod|makedirs|mkdir))\b"
                  r"|open\s*\([^)]*['\"][wax]\+?b?['\"]")


# ---------------------------------------------------------------- server
BENCH_SCRIPTS = ("run_contest.py", "chain.py", "run_hard.py", "improve27.py")


def gpu_busy():
    """Why the GPU should be left alone, or None. A benchmark runner counts even while it waits between servers."""
    busy = subprocess.run(["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"], capture_output=True, text=True)
    if "llama-server.exe" in busy.stdout:
        return "a llama-server is running"
    try:
        import psutil
    except ImportError:
        return None
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower().startswith("python") and any(
                    os.path.basename(a) in BENCH_SCRIPTS for a in (p.info["cmdline"] or [])[1:]):
                return f"benchmark {os.path.basename([a for a in p.info['cmdline'] if os.path.basename(a) in BENCH_SCRIPTS][0])} is running"
        except Exception:
            continue
    return None


class Server:
    """Starts llama-server for the 27B, or attaches to one already listening on `port`."""

    def __init__(self, port=None, model=MODEL, spec=SPEC):
        self.attach, self.port, self.model, self.proc = port is not None, port or DEFAULT_PORT, model, None
        self.spec = spec

    def __enter__(self):
        if self.attach:
            self._wait(30)
            return self
        why = gpu_busy()
        if why:
            raise SystemExit(f"The GPU is busy ({why}). Wait for it, or attach to a running server with --port.")
        os.makedirs(TMP, exist_ok=True)
        log = open(os.path.join(TMP, "server.log"), "a")
        self.proc = subprocess.Popen([LLAMA, "-m", self.model, "--port", str(self.port), "--host", "127.0.0.1"]
                                     + SERVER_ARGS + ["--spec-type", self.spec], stdout=log, stderr=subprocess.STDOUT, cwd=TMP)
        self._wait(600)
        return self

    def _wait(self, secs):
        for _ in range(secs // 2):
            if self.proc is not None and self.proc.poll() is not None:
                raise SystemExit("llama-server exited; see tmp/server.log")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=5) as r:
                    if b"ok" in r.read():
                        return
            except Exception:
                time.sleep(2)
        raise SystemExit(f"no llama-server answering on port {self.port}")

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(60)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def chat(self, messages, max_tokens):
        body = {"messages": messages, "temperature": 0.0, "max_tokens": max_tokens, "seed": 42,
                "chat_template_kwargs": {"enable_thinking": False}}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3600) as r:
            js = json.loads(r.read())
        return js["choices"][0]["message"].get("content") or "", js["choices"][0].get("finish_reason")


# ---------------------------------------------------------------- sandbox and parsing
def run_py(code, timeout=10):
    m = DENY.search(code)
    if m:
        return False, "", f"refused to run: uses {m.group(0)!r} (file/process/network access is not allowed)"
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, f"s_{time.time_ns()}.py")
    open(path, "w", encoding="utf-8").write(code)
    env = dict(os.environ, TEMP=TMP, TMP=TMP)
    try:
        p = subprocess.run([PY, "-I", path], capture_output=True, text=True, timeout=timeout, cwd=TMP, env=env)
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


def extract_number(text):
    """Boxed LaTeX, then 'Answer: n', then the last number on the last line (as in the tested scaffold)."""
    m = re.findall(r"\\boxed\{([^\}]+)\}", text)
    if m:
        try:
            return float(re.sub(r"[^\d\.\-]", "", m[-1]))
        except ValueError:
            pass
    m = re.findall(r"Answer:\s*\$?\s*(-?[\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
    if m:
        try:
            return float(m[-1].replace(",", ""))
        except ValueError:
            pass
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if lines:
        nums = re.findall(r"(-?[\d,]+(?:\.\d+)?)", lines[-1])
        if nums:
            try:
                return float(nums[-1].replace(",", ""))
            except ValueError:
                pass
    return None


def compiles(code):
    try:
        compile(code or "", "<answer>", "exec")
        return bool(code)
    except (SyntaxError, ValueError):
        return False


def extract(text, prompt, entry):
    """The task stub goes first so its imports and helpers exist; the model's own def then replaces the stub."""
    m = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    code = max(m, key=len) if m else text
    if re.search(rf"def {re.escape(entry)}\s*\(", code):
        return prompt + "\n    pass\n\n" + code
    return prompt + code


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


def _parseable(pairs, prompt):
    keep = []
    for call, exp in pairs:
        try:
            tree = ast.parse(call, mode="eval")
        except SyntaxError:
            continue
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        free = [n for n in names if not hasattr(builtins, n) and not re.search(
            rf"(def|class)\s+{re.escape(n)}\b|^\s*{re.escape(n)}\s*=|import.*\b{re.escape(n)}\b", prompt, re.M)]
        if not free:
            keep.append((call, exp))
    return list(dict.fromkeys(keep))


def examples(prompt, entry):
    """(call, expected) pairs written in the docstring: '>>> f(x)' + next line, or 'f(x) => y' / '->' / '==' etc."""
    out, lines = [], prompt.splitlines()
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith(">>>") and f"{entry}(" in s:
            exp = []
            for l2 in lines[i + 1:]:
                t = l2.strip()
                if not t or t.startswith(">>>") or t.startswith('"""') or t.startswith("'''"):
                    break
                exp.append(t)
            e = _literal(" ".join(exp)) if exp else None
            if e is not None:
                out.append((s[3:].strip(), e))
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
    ok, out, err = run_py(code + "\n\n" + RUNNER.format(ex=json.dumps(exs)))
    line = next((l for l in out.splitlines()[::-1] if l.startswith("__RESULTS__")), None)
    if line is None:
        return [[False, err or "no result"] for _ in exs]
    return json.loads(line[len("__RESULTS__"):])


# ---------------------------------------------------------------- the two loops
def script_answer(srv, sys_prompt, question, log=print, tag=""):
    """One script-writing loop: write, run, fix up to RETRIES times. This is m1 when sys_prompt is MATH_SYS."""
    msgs = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": question}]
    text, code = "", None
    for k in range(1 + RETRIES):
        text, _ = srv.chat(msgs, MATH_BUDGET)
        code = last_code(text)
        ok, out, err = run_py(code) if code else (False, "", "the reply has no ```python block")
        num = extract_number(out) if ok and out else None
        if ok and num is None:
            err = f"the script printed no number (output: {out[:80]!r})"
        if num is not None:
            return {"answer": num, "script": code, "tries": k + 1}
        log(f"{tag}try {k + 1} failed: {err}")
        msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": FIX_MSG.format(err=err)}]
    return {"answer": extract_number(text), "script": code, "tries": 1 + RETRIES, "note": "no script ran; number read from text"}


def same(a, b):
    return a is not None and b is not None and abs(a - b) < 1e-6


def solve_math(srv, question, log=print, check=True):
    """m1, plus check-on-retry (policy P2 in wrong_flag/): only when the first script needed a fix, a second program
    using a different method (VERIFY_SYS) solves it too. If both agree, keep the answer. If they disagree, take the second
    program's answer and say "check this". On 105 fresh hard problems this went from 17 to 8 wrong, for +1.2 min each.
    Problems whose first script runs cleanly are not touched."""
    r = script_answer(srv, MATH_SYS, question, log)
    r["check"] = "not needed (first script ran cleanly)"
    if not check or r["tries"] == 1:
        if not check:
            r["check"] = "off (--no-check)"
        return r
    log("first script needed a fix; solving again with a different method")
    v = script_answer(srv, VERIFY_SYS, question, log, tag="check ")
    r["second_answer"], r["second_script"] = v["answer"], v["script"]
    if same(r["answer"], v["answer"]):
        r["check"] = "passed (a second method gives the same answer)"
    elif v["answer"] is None:
        r["check"] = "CHECK THIS: the second method gave no number"
        r["flag"] = True
    else:
        first = r["answer"]
        r.update(answer=v["answer"], script=v["script"], first_answer=first, flag=True)
        r.pop("note", None)
        r["check"] = f"CHECK THIS: two methods disagreed (first got {fmt(first)}); using the second method's answer"
    return r


def fmt(n):
    try:
        return int(n) if n is not None and n == int(n) else n
    except (OverflowError, ValueError):
        return n


def solve_code(srv, prompt, entry, log=print):
    exs = examples(prompt, entry)
    log(f"{len(exs)} example(s) found in the docstring")
    msgs = [{"role": "system", "content": CODE_SYS}, {"role": "user", "content": f"Complete this function:\n{prompt}"}]
    attempts, kept = [], False
    for k in range(1 + RETRIES):
        text, finish = srv.chat(msgs, CODE_BUDGET)
        code = extract(text, prompt, entry)
        if k and "```" not in text and re.search(r"^\W*KEEP\W*$", text, re.M):
            attempts[-1]["npass"] = len(exs)
            kept = True
            log("model judged a docstring example wrong (KEEP); keeping its previous answer")
            break
        cut = finish == "length" and not compiles(code)
        res = run_examples(code, exs) if exs else []
        npass = -1 if cut else sum(1 for ok, _ in res if ok)
        attempts.append({"k": k, "code": code, "npass": npass})
        if not cut and npass == len(exs):
            break
        if cut:
            nxt = CUTOFF_MSG
        else:
            report = "\n".join(f"- {c}  -> got {g}, expected {e}" for (c, e), (ok, g) in zip(exs, res) if not ok)
            log(f"try {k + 1}: {npass}/{len(exs)} examples pass")
            nxt = SELFTEST_KEEP_MSG.format(report=report)
        msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": nxt}]
    best = max(attempts, key=lambda a: (a["npass"], -a["k"]))
    return {"code": best["code"], "examples_passed": max(best["npass"], 0), "examples": len(exs),
            "tries": len(attempts), "kept": kept}


# ---------------------------------------------------------------- selftest (no model)
def selftest():
    checks = []
    ok, out, _ = run_py("print(sum(range(10)))")
    checks.append(("sandbox runs code", ok and out == "45"))
    ok, _, err = run_py("import subprocess\nprint(1)")
    checks.append(("sandbox refuses subprocess", not ok and "refused" in err))
    ok, _, err = run_py("open('x.txt','w').write('a')")
    checks.append(("sandbox refuses file writes", not ok and "refused" in err))
    ok, _, err = run_py("while True: pass", timeout=2)
    checks.append(("sandbox time limit", not ok and "timed out" in err))
    checks.append(("number: boxed", extract_number("so \\boxed{1,234}") == 1234.0))
    checks.append(("number: last line", extract_number("x\n42\n") == 42.0))
    stub = 'def add(a, b):\n    """Add.\n    >>> add(2, 3)\n    5\n    """\n'
    exs = examples(stub, "add")
    checks.append(("docstring examples", exs == [("add(2, 3)", "5")]))
    good = extract("```python\ndef add(a, b):\n    return a + b\n```", stub, "add")
    bad = extract("```python\ndef add(a, b):\n    return a - b\n```", stub, "add")
    checks.append(("examples pass on right code", run_examples(good, exs)[0][0] is True))
    checks.append(("examples fail on wrong code", run_examples(bad, exs)[0][0] is False))

    class FakeSrv:  # replays canned replies: first the m1 loop, then the second method
        def __init__(s, replies): s.r = list(replies)
        def chat(s, msgs, n): return s.r.pop(0), "stop"
    py = lambda x: f"```python\nprint({x})\n```"  # noqa: E731
    quiet = lambda m: None  # noqa: E731
    r = solve_math(FakeSrv([py(7)]), "q", quiet)
    checks.append(("check skipped when the first script runs", r["answer"] == 7 and "flag" not in r))
    r = solve_math(FakeSrv(["no code", py(7), py(7)]), "q", quiet)
    checks.append(("check after a retry, agreeing", r["answer"] == 7 and "flag" not in r and r["check"].startswith("passed")))
    r = solve_math(FakeSrv(["no code", py(7), py(9)]), "q", quiet)
    checks.append(("check after a retry, disagreeing -> second answer + flag", r["answer"] == 9 and r["flag"] and r["first_answer"] == 7))
    r = solve_math(FakeSrv(["no code", py(7), "x", "x", "x"]), "q", quiet)
    checks.append(("second method no number -> keep first + flag", r["answer"] == 7 and r["flag"]))
    r = solve_math(FakeSrv(["no code", py(7)]), "q", quiet, check=False)
    checks.append(("--no-check is plain m1", r["answer"] == 7 and "second_answer" not in r))
    for name, passed in checks:
        print(("PASS " if passed else "FAIL ") + name)
    return all(p for _, p in checks)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", choices=["math", "code", "selftest"])
    ap.add_argument("input", nargs="?", help="math: the question; code: a .py file with the function stub")
    ap.add_argument("--entry", help="code: the function name (default: the last def in the file)")
    ap.add_argument("--port", type=int, help="attach to a llama-server already running on this port")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--exact", action="store_true",
                    help="code: draft with the MTP head only, as in the published results (math always does)")
    ap.add_argument("--no-check", action="store_true",
                    help="math: plain m1, no second-method check after a retry (as in the published locked test)")
    a = ap.parse_args()
    if a.mode == "selftest":
        raise SystemExit(0 if selftest() else 1)
    if not a.input:
        ap.error("input is required")
    log = lambda m: print("..", m, file=sys.stderr, flush=True)  # noqa: E731
    spec = EXACT_SPEC if a.exact or a.mode == "math" else SPEC
    with Server(a.port, a.model, spec) as srv:
        t0 = time.time()
        if a.mode == "math":
            r = solve_math(srv, a.input, log, check=not a.no_check)
            print(f"\nanswer: {fmt(r['answer'])}   ({r['tries']} tr{'y' if r['tries'] == 1 else 'ies'}, {time.time() - t0:.0f} s)")
            print(f"check: {r['check']}")
            print("\nscript that computed it:\n" + (r["script"] or "(none)"))
        else:
            prompt = open(a.input, encoding="utf-8").read()
            entry = a.entry or (re.findall(r"^def\s+(\w+)\s*\(", prompt, re.M) or [None])[-1]
            if not entry:
                raise SystemExit("no function found; pass --entry")
            r = solve_code(srv, prompt, entry, log)
            print(f"\n{r['examples_passed']}/{r['examples']} docstring examples pass   ({r['tries']} tries, "
                  f"{time.time() - t0:.0f} s{', KEEP used' if r['kept'] else ''})\n")
            print(r["code"])


if __name__ == "__main__":
    main()
