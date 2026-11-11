"""Detailed benchmark: OG Qwen2.5-14B vs the "new" scaffolded 14B engine (autoresearch_14b).

Both systems use the same GGUF and the same llama-server config. Only the harness differs:
  OG  : plain chat, "solve step by step ... Answer: <n>", one attempt.
  NEW : harness_scaffold.py as shipped. Math = write Python + run it in the venv
        sandbox. Code = same prompt as OG, plus one retry fed with the test error (k=2).
Token budgets are the same for both (math 1024, code 768), so truncation can't
decide the result.

Stages (each one writes results/<stage>.json and is skipped if that file already exists):
  speed     llama-bench pp512 / tg128 at several -ngl / flash-attn settings
  accuracy  16 original + 80 held-out math; 8 original + 164 HumanEval coding
  longctx   passkey retrieval up to 30k tokens; checks the dossier's "crash at 32k" claim
"""
import gzip
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

ROOT = r"D:\timepass"
HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
TMP = os.path.join(HERE, "tmp")
os.makedirs(RES, exist_ok=True)
os.makedirs(TMP, exist_ok=True)
os.environ["TEMP"] = TMP
os.environ["TMP"] = TMP
os.chdir(TMP)

# Frozen copies of autoresearch_14b/{eval_oracle,harness_scaffold}.py as the 14B run used them:
# another agent keeps editing the originals (14:15 today: datetime preamble), which would
# silently change the NEW condition between runs.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_oracle_frozen import MATH_PROBLEMS, CODING_TASKS  # noqa: E402
from scaffold_frozen import DeterministicTools, Guardrails  # noqa: E402

BIN = os.path.join(ROOT, "llama_cpp_bin")
SERVER = os.path.join(BIN, "llama-server.exe")
LBENCH = os.path.join(BIN, "llama-bench.exe")
MODEL = os.path.join(ROOT, "models", "qwen2.5-14b", "Qwen2.5-14B-Instruct-Q4_K_M.gguf")
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
PORT = 8093

OG_MATH_SYS = "Solve step by step. Conclude with 'Answer: <number>'."
NEW_MATH_SYS = (
    "You are an expert computational problem solver. "
    "Solve the following problem by writing a concise, self-contained Python script inside a ```python ``` block. "
    "Calculate the exact result and conclude with `print(ans)` (or print the exact numerical value). "
    "Do not write conversational preamble. Let Python compute the answer."
)
CODE_SYS = "You are an expert Python coder. Return the complete function in a ```python ``` block."
RETRY_MSG = "Code failed with: {err}. Carefully analyze boundary conditions, fix, and return complete ```python block."
MATH_BUDGET, CODE_BUDGET = 1024, 768


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def save(name, obj):
    json.dump(obj, open(os.path.join(RES, f"{name}.json"), "w", encoding="utf-8"), indent=1)


def done(name):
    return os.path.exists(os.path.join(RES, f"{name}.json"))


def vram_used():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip()
    return int(out.splitlines()[0]) if out else None


# ---------------------------------------------------------------- server

class Server:
    def __init__(self, tag, args):
        self.tag, self.args = tag, args
        self.log_path = os.path.join(RES, f"server_{tag}.log")

    def __enter__(self):
        try:  # never start next to a leftover server: requests would silently go to the old one
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2)
            raise RuntimeError(f"port {PORT} already has a server answering; stop it first")
        except OSError:  # connection refused / timeout = port is free
            pass
        self.vram_before = vram_used()
        self.log = open(self.log_path, "w", encoding="utf-8")
        cmd = [SERVER, "-m", MODEL, "--port", str(PORT), "--host", "127.0.0.1", "-np", "1"] + self.args
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT)
        self.ok = False
        for _ in range(240):
            if self.proc.poll() is not None:
                break
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2).status == 200:
                    self.ok = True
                    break
            except Exception:
                time.sleep(1)
        time.sleep(2)
        self.vram_loaded = vram_used()
        return self

    def __exit__(self, *exc):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except Exception:
                self.proc.kill()
        self.log.close()
        time.sleep(3)

    def info(self):
        text = open(self.log_path, encoding="utf-8", errors="replace").read()
        off = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", text)
        kv = re.findall(r"llama_kv_cache.*?size\s*=\s*([\d.]+) MiB", text)
        err = [l for l in text.splitlines() if re.search(r"out of memory|failed to allocate|error", l, re.I)][:5]
        return {"started": self.ok, "exit_code": self.proc.poll(), "offloaded": off[-1] if off else None,
                "kv_cache_mib": float(kv[-1]) if kv else None, "vram_before_mib": self.vram_before,
                "vram_loaded_mib": self.vram_loaded, "errors": err}


def chat(messages, max_tokens, timeout=900):
    body = json.dumps({"messages": messages, "temperature": 0.0, "max_tokens": max_tokens, "seed": 42}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        js = json.loads(r.read())
    tim = js.get("timings", {})
    return {"text": js["choices"][0]["message"].get("content") or "", "finish": js["choices"][0].get("finish_reason"),
            "n_gen": js.get("usage", {}).get("completion_tokens"), "n_prompt": js.get("usage", {}).get("prompt_tokens"),
            "decode_tok_s": tim.get("predicted_per_second"), "prompt_tok_s": tim.get("prompt_per_second"),
            "wall_s": round(time.time() - t0, 2)}


def tokenize(text):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/tokenize", data=json.dumps({"content": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return len(json.loads(r.read())["tokens"])


# ---------------------------------------------------------------- stage: speed

def stage_speed():
    rows = []
    for ngl, fa in [(35, "off"), (35, "on"), (38, "off"), (38, "on"), (40, "on"), (42, "on")]:
        cmd = [LBENCH, "-m", MODEL, "-ngl", str(ngl), "-fa", fa, "-p", "512", "-n", "128", "-r", "3", "-o", "json"]
        say("llama-bench", ngl, fa)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        try:
            for r in json.loads(p.stdout):
                rows.append({"ngl": ngl, "fa": fa, "test": "pp512" if r["n_prompt"] else "tg128",
                             "tok_s": round(r["avg_ts"], 2), "stdev": round(r["stddev_ts"], 2)})
        except Exception:
            rows.append({"ngl": ngl, "fa": fa, "error": (p.stderr or p.stdout)[-400:]})
        say(rows[-2:] if len(rows) > 1 else rows)
    save("speed", rows)


# ---------------------------------------------------------------- stage: accuracy

def math_items():
    out = [{"id": f"orig_{i:02d}", "kind": "original16", "question": q, "answer": a}
           for i, (q, a) in enumerate(MATH_PROBLEMS, 1)]
    out += json.load(open(os.path.join(HERE, "math_heldout.json"), encoding="utf-8"))
    return out


def number_from_og(text):
    m = re.findall(r"Answer:\s*\**\s*\$?\s*(-?[\d,]+(?:\.\d+)?)", text, re.I)
    if m:
        return float(m[-1].replace(",", "")), "Answer: line"
    g = Guardrails.extract_number(text)
    return g, "fallback"


def run_math_og(items):
    rows = []
    for it in items:
        r = chat([{"role": "system", "content": OG_MATH_SYS}, {"role": "user", "content": it["question"]}], MATH_BUDGET)
        got, how = number_from_og(r["text"])
        ok = got is not None and abs(got - it["answer"]) < 1e-6
        rows.append({**it, "got": got, "ok": ok, "how": how, **{k: r[k] for k in ("finish", "n_gen", "decode_tok_s", "wall_s")},
                     "tail": r["text"][-300:]})
        say("og  ", it["id"], "PASS" if ok else "FAIL", got, r["finish"], r["n_gen"])
    return rows


def run_math_new(items):
    rows = []
    for it in items:
        t0 = time.time()
        r = chat([{"role": "system", "content": NEW_MATH_SYS}, {"role": "user", "content": it["question"]}], MATH_BUDGET)
        m = re.search(r"```(?:python)?\s*(.*?)\s*```", r["text"], re.DOTALL)
        got, how, py_out = None, "no code", ""
        if m:
            ok_py, py_out = DeterministicTools.run_python_sandbox(m.group(1).strip())
            if ok_py:
                got, how = Guardrails.extract_number(py_out), "python"
            else:
                how = "python error"
        if got is None:
            got = Guardrails.extract_number(r["text"])
            how += "+fallback"
        ok = got is not None and abs(got - it["answer"]) < 1e-6
        rows.append({**it, "got": got, "ok": ok, "how": how, **{k: r[k] for k in ("finish", "n_gen", "decode_tok_s")},
                     "wall_s": round(time.time() - t0, 2), "code": (m.group(1)[:800] if m else r["text"][:400]),
                     "py_out": py_out[:200]})
        say("new ", it["id"], "PASS" if ok else "FAIL", got, how)
    return rows


def code_items():
    out = [{"id": f"orig_{t['entry_point']}", "set": "original8", "prompt": t["prompt"], "test": t["test"],
            "entry_point": t["entry_point"]} for t in CODING_TASKS]
    he = os.path.join(ROOT, "model_carving_lab", "HumanEval.jsonl.gz")
    for line in gzip.open(he, "rt", encoding="utf-8"):
        t = json.loads(line)
        out.append({"id": t["task_id"], "set": "humaneval", "prompt": t["prompt"], "test": t["test"],
                    "entry_point": t["entry_point"]})
    return out


def extract(text, it):
    """Same for OG and NEW. The task prompt always goes first, so its imports and helper
    functions exist; the model's own `def` then replaces the docstring-only stub."""
    m = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    code = max(m, key=len) if m else text
    if re.search(rf"def {re.escape(it['entry_point'])}\s*\(", code):
        return it["prompt"] + "\n    pass\n\n" + code
    return it["prompt"] + code


def run_tests(code, it, timeout=10):
    path = os.path.join(TMP, f"t_{abs(hash(it['id']))}_{time.time_ns()}.py")
    open(path, "w", encoding="utf-8").write(code + "\n\n" + it["test"] + f"\n\ncheck({it['entry_point']})\n")
    try:
        p = subprocess.run([PY, "-I", path], capture_output=True, text=True, timeout=timeout, cwd=TMP)
        if p.returncode == 0:
            return True, "PASSED"
        err = p.stderr.strip().splitlines()
        return False, err[-1][:200] if err else "error"
    except subprocess.TimeoutExpired:
        return False, f"Timeout (>{timeout}s)"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def run_code(items):
    rows = []
    for it in items:
        msgs = [{"role": "system", "content": CODE_SYS}, {"role": "user", "content": f"Complete this function:\n{it['prompt']}"}]
        r1 = chat(msgs, CODE_BUDGET)
        code1 = extract(r1["text"], it)
        ok1, err1 = run_tests(code1, it)
        row = {"id": it["id"], "set": it["set"], "og_ok": ok1, "og_err": err1, "finish": r1["finish"], "n_gen": r1["n_gen"],
               "decode_tok_s": r1["decode_tok_s"], "wall_s": r1["wall_s"], "new_ok": ok1, "new_round": 1 if ok1 else None}
        if not ok1:  # NEW harness: one retry with the failing test's error message
            msgs += [{"role": "assistant", "content": f"```python\n{code1}\n```"},
                     {"role": "user", "content": RETRY_MSG.format(err=err1)}]
            r2 = chat(msgs, CODE_BUDGET)
            ok2, err2 = run_tests(extract(r2["text"], it), it)
            row.update({"new_ok": ok2, "new_round": 2 if ok2 else None, "retry_err": err2, "retry_wall_s": r2["wall_s"],
                        "retry_finish": r2["finish"]})
        rows.append(row)
        say("code", it["id"], "og", "PASS" if ok1 else "FAIL", "new", "PASS" if row["new_ok"] else "FAIL")
    return rows


def stage_accuracy():
    with Server("accuracy", ["-ngl", "38", "-fa", "on", "-c", "8192"]) as s:
        info = s.info()
        say("server", info)
        if not s.ok:
            save("accuracy_error", info)
            return
        mi = math_items()
        if not done("math_og"):
            save("math_og", run_math_og(mi))
        if not done("math_new"):
            save("math_new", run_math_new(mi))
        if not done("code"):
            save("code", run_code(code_items()))
        save("accuracy_server", s.info())


# ---------------------------------------------------------------- stage: long context

WORDS = {
    "adj": "quiet amber distant crowded narrow ancient modern bright hollow gentle rapid silent rusty humid frozen tidy".split(),
    "noun": "harbour library orchard engine village river market lantern bridge garden factory valley tower ferry canal meadow".split(),
    "verb": "overlooks borders surrounds supplies shelters faces connects outlasts".split(),
    "place": ["north coast", "old quarter", "eastern hills", "main square", "southern plain", "western ridge", "river delta"],
}


def haystack(n_tokens, depth, key, rng):
    def sentence():
        return (f"The {rng.choice(WORDS['adj'])} {rng.choice(WORDS['noun'])} {rng.choice(WORDS['verb'])} the "
                f"{rng.choice(WORDS['adj'])} {rng.choice(WORDS['noun'])} near the {rng.choice(WORDS['place'])}.")
    sample = " ".join(sentence() for _ in range(200))
    per = tokenize(sample) / 200
    sents = [sentence() for _ in range(int(n_tokens / per))]
    pos = int(len(sents) * depth)
    needle = f"The pass key is {key}. Remember it. {key} is the pass key."
    body = " ".join(sents[:pos]) + f"\n{needle}\n" + " ".join(sents[pos:])
    return ("There is a pass key hidden inside a lot of irrelevant text. Find it and remember it.\n\n" + body +
            "\n\nWhat is the pass key? Answer with the number only.")


def run_passkeys(lengths, depths, rng):
    rows = []
    for n in lengths:
        for d in depths:
            key = str(rng.randrange(10000, 99999))
            prompt = haystack(n, d, key, rng)
            try:
                r = chat([{"role": "user", "content": prompt}], 16, timeout=1800)
                ok = key in r["text"]
                rows.append({"target_tokens": n, "depth": d, "key": key, "ok": ok, "answer": r["text"].strip()[:40],
                             "n_prompt": r["n_prompt"], "prompt_tok_s": r["prompt_tok_s"], "decode_tok_s": r["decode_tok_s"],
                             "wall_s": r["wall_s"]})
            except Exception as e:
                rows.append({"target_tokens": n, "depth": d, "ok": False, "error": repr(e)[:200]})
            say("passkey", rows[-1])
    return rows


def stage_longctx():
    rng = random.Random(7)
    out = {}
    # 1. The dossier's crash scenario: fp16 KV, 32k context, 38 layers forced onto the GPU.
    with Server("ctx32k_f16_ngl38", ["-ngl", "38", "-fa", "on", "-c", "32768"]) as s:
        out["f16_ngl38_32k"] = {"server": s.info()}
        if s.ok:
            out["f16_ngl38_32k"]["passkey"] = run_passkeys([30000], [0.5], rng)
    # 2. Stock llama.cpp, fp16 KV, 32k, let --fit choose the GPU layers.
    with Server("ctx32k_f16_fit", ["-fa", "on", "-c", "32768"]) as s:
        out["f16_fit_32k"] = {"server": s.info()}
        if s.ok:
            out["f16_fit_32k"]["passkey"] = run_passkeys([30000], [0.1, 0.5, 0.9], rng)
    # 3. Stock llama.cpp, q8_0 KV (half the memory), 32k, --fit.
    with Server("ctx32k_q8_fit", ["-fa", "on", "-c", "32768", "-ctk", "q8_0", "-ctv", "q8_0"]) as s:
        out["q8_fit_32k"] = {"server": s.info()}
        if s.ok:
            out["q8_fit_32k"]["passkey"] = run_passkeys([4000, 8000, 16000, 30000], [0.1, 0.5, 0.9], rng)
    save("longctx", out)


if __name__ == "__main__":
    stages = sys.argv[1:] or ["speed", "accuracy", "longctx"]
    for st in stages:
        if st == "accuracy" or not done(st):
            say("=== stage", st)
            globals()[f"stage_{st}"]()
    say("ALL DONE")
