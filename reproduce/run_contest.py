"""Run the local Qwen3.8-27B on AIME 2026, HMMT Feb 2026 and IFEval (the TwIL-8B chart's tests).

Settings (fixed before any run):
  math    thinking ON, Qwen's recommended sampling (temp 0.6, top_p 0.95, top_k 20, seed 42), one try per problem
          (pass@1, n=1). Thinking budget 28,000 tokens; when it runs out llama.cpp injects a short "time is up"
          message and closes the thinking so the model still gives an answer. Answer = last \\boxed{} in the reply,
          checked against the official answer with math-verify (symbolic), exact match as fallback.
  ifeval  thinking OFF, greedy, 3,072 tokens. Scored with Google's own IFEval checker (strict and loose).
Server: llama.cpp, 32k context, q8_0 KV cache, --fit on, MTP self-speculation, one slot.

GPU manners: another session (hard_bench run_hard.py / improve27.py) has priority. The runner waits until none of
those run, and a watchdog kills our server within seconds if one starts; the interrupted item is retried later.

  python -I run_contest.py run aime_2026 hmmt_feb_2026 ifeval      (resumable; results in runs/<set>.jsonl)
  python -I run_contest.py report
  python -I run_contest.py smoke                                   (0.8B on CPU, 2 items per set, port 8099)
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "ifeval_lib"))
os.environ.setdefault("NLTK_DATA", os.path.join(HERE, "nltk_data"))
for v in ("TEMP", "TMP"):
    os.environ[v] = os.path.join(HERE, "tmp")
os.makedirs(os.environ["TEMP"], exist_ok=True)

LLAMA = os.path.join(ROOT, "llama_cpp_bin", "llama-server.exe")
BIG = os.path.join(ROOT, "models", "qwen3.8-27b", "Qwen3.8-27B-UD-Q4_K_M.gguf")
SMALL = os.path.join(ROOT, "models", "qwen3.5-0.8b-gguf", "Qwen3.5-0.8B-Q8_0.gguf")
RUNS = os.path.join(HERE, "runs")
LOG = os.path.join(HERE, "run_log.txt")
CTX, THINK_BUDGET, MATH_MAX, IF_MAX = 32768, 28000, 31000, 3072
BUDGET_MSG = "\n\nI am out of thinking time. I will now give my best final answer.\n"
MATH_SUFFIX = "\n\nPlease reason step by step, and put your final answer within \\boxed{}."
OTHERS = ("run_hard.py", "improve27.py")
MATH_SETS = ("aime_2026", "hmmt_feb_2026")


def say(msg):
    line = time.strftime("%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def keep_awake():
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:
        pass


# ---------------------------------------------------------------- GPU manners
def others_running(my_pid=None):
    found = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            argv = p.info["cmdline"] or []
            name = (p.info["name"] or "").lower()
        except Exception:
            continue
        if p.info["pid"] in (os.getpid(), my_pid):
            continue
        # only a Python process actually running one of those scripts counts (a shell command that merely
        # mentions the file name, e.g. `cp improve27.py ...`, stopped the run once on 2026-11-11)
        script_run = name.startswith("python") and any(os.path.basename(a) in OTHERS for a in argv[1:])
        if script_run or (name.startswith("llama-server") and "--port" in argv
                          and argv[argv.index("--port") + 1:argv.index("--port") + 2] == ["8095"]):
            found.append(p.info["pid"])
    return found


class Server:
    def __init__(self, cpu=False):
        self.cpu, self.proc, self.port = cpu, None, 8099 if cpu else 8097
        self.evicted = threading.Event()

    def start(self):
        if self.cpu:
            args = ["-m", SMALL, "-ngl", "0", "-t", "4", "-c", str(CTX)]
        else:
            args = ["-m", BIG, "-fit", "on", "-fa", "on", "-c", str(CTX), "-ctk", "q8_0", "-ctv", "q8_0",
                    "--spec-type", "draft-mtp"]
        args += ["--port", str(self.port), "--host", "127.0.0.1", "-np", "1",
                 "--reasoning-budget", str(THINK_BUDGET), "--reasoning-budget-message", BUDGET_MSG]
        log = open(os.path.join(HERE, "server.log"), "a")
        self.proc = subprocess.Popen([LLAMA] + args, stdout=log, stderr=subprocess.STDOUT, cwd=HERE)
        self.evicted.clear()
        for _ in range(300):
            if self.proc.poll() is not None:
                raise RuntimeError("server exited, see server.log")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=5) as r:
                    if b"ok" in r.read():
                        say(f"server up on {self.port} ({'0.8B CPU' if self.cpu else '27B GPU'})")
                        break
            except Exception:
                time.sleep(2)
        else:
            raise RuntimeError("server did not come up")
        if not self.cpu:
            threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        proc = self.proc
        while proc.poll() is None:
            if others_running(proc.pid):
                say("another 27B job started: stopping our server and yielding the GPU")
                self.evicted.set()
                self.stop()
                return
            time.sleep(3)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(60)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def chat(self, messages, max_tokens, think, **samp):
        body = {"messages": messages, "max_tokens": max_tokens, "seed": 42,
                "chat_template_kwargs": {"enable_thinking": think}, **samp}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=4 * 3600) as r:
            js = json.loads(r.read())
        msg = js["choices"][0]["message"]
        return {"text": msg.get("content") or "", "reasoning": msg.get("reasoning_content") or "",
                "finish": js["choices"][0].get("finish_reason"),
                "n_gen": js.get("usage", {}).get("completion_tokens") or 0,
                "tok_s": js.get("timings", {}).get("predicted_per_second"), "wall_s": round(time.time() - t0, 1)}


def wait_for_gpu():
    quiet = 0
    while quiet < 2:                      # two clear checks 5 minutes apart
        if others_running():
            quiet = 0
        else:
            quiet += 1
        if quiet < 2:
            time.sleep(300)
            keep_awake()


# ---------------------------------------------------------------- scoring
def last_boxed(s):
    i = s.rfind("\\boxed")
    if i < 0:
        return None
    j = s.find("{", i)
    if j < 0:
        return None
    depth, k = 0, j
    while k < len(s):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                return s[j + 1:k]
        k += 1
    return None


def norm(s):
    return re.sub(r"\s+|\\[,;! ]|\\left|\\right|\$|\^\\circ|°|\\text\{[^}]*\}", "", s or "")


def math_ok(gold, pred):
    if pred is None or len(pred) > 300:          # long junk could stall sympy (no timeout on Windows)
        return False
    if norm(gold) == norm(pred):
        return True
    try:
        from math_verify import parse, verify
        # timeouts off: math-verify's timeout uses a subprocess that breaks on Windows
        g = parse("$" + gold + "$", parsing_timeout=None)
        p = parse("$" + pred + "$", parsing_timeout=None)
        return bool(verify(g, p, timeout_seconds=None))
    except Exception:
        return False


def load(name):
    rows = json.load(open(os.path.join(HERE, name + ".json"), encoding="utf-8"))
    if name == "ifeval":
        return [{"id": str(r["key"]), "prompt": r["prompt"], "ids": r["instruction_id_list"],
                 "kwargs": [{k: v for k, v in kw.items() if v is not None} for kw in r["kwargs"]]} for r in rows]
    return [{"id": str(r["problem_idx"]), "prompt": r["problem"], "gold": str(r["answer"])} for r in rows]


def ifeval_check(item, response):
    from instruction_following_eval import evaluation_lib as ev
    inp = ev.InputExample(key=item["id"], instruction_id_list=item["ids"], prompt=item["prompt"], kwargs=item["kwargs"])
    s = ev.test_instruction_following_strict(inp, {item["prompt"]: response})
    l = ev.test_instruction_following_loose(inp, {item["prompt"]: response})
    return s.follow_instruction_list, l.follow_instruction_list


def do_item(srv, name, item):
    if name in MATH_SETS:
        r = srv.chat([{"role": "user", "content": item["prompt"] + MATH_SUFFIX}], MATH_MAX, True,
                     temperature=0.6, top_p=0.95, top_k=20)
        pred = last_boxed(r["text"]) or last_boxed(r["reasoning"])
        return {"id": item["id"], "gold": item["gold"], "pred": pred, "ok": math_ok(item["gold"], pred),
                "finish": r["finish"], "n_gen": r["n_gen"], "budget_hit": BUDGET_MSG.strip()[:30] in r["reasoning"] + r["text"],
                "tok_s": r["tok_s"], "wall_s": r["wall_s"], "text": r["text"], "reasoning_chars": len(r["reasoning"])}
    r = srv.chat([{"role": "user", "content": item["prompt"]}], IF_MAX, False, temperature=0.0, top_k=1)
    strict, loose = ifeval_check(item, r["text"])
    return {"id": item["id"], "strict": strict, "loose": loose, "finish": r["finish"], "n_gen": r["n_gen"],
            "tok_s": r["tok_s"], "wall_s": r["wall_s"], "text": r["text"]}


# ---------------------------------------------------------------- commands
def cmd_run(sets, cpu=False, limit=None, out_dir=RUNS):
    os.makedirs(out_dir, exist_ok=True)
    keep_awake()
    srv = Server(cpu)
    try:
        for name in sets:
            out = os.path.join(out_dir, name + ".jsonl")
            done = {json.loads(l)["id"] for l in open(out, encoding="utf-8")} if os.path.exists(out) else set()
            todo = [it for it in load(name) if it["id"] not in done][:limit]
            say(f"=== {name}: {len(todo)} to do ({len(done)} done)")
            i = 0
            while i < len(todo):
                if srv.proc is None:
                    if not cpu:
                        if others_running():
                            say("waiting for the other 27B jobs to finish")
                        wait_for_gpu()
                    srv.start()
                keep_awake()
                try:
                    rec = do_item(srv, name, todo[i])
                except Exception as e:
                    if srv.evicted.is_set() or srv.proc is None:
                        say(f"{name} {todo[i]['id']} interrupted (GPU yielded); will retry")
                        srv.stop()
                        continue
                    say(f"{name} {todo[i]['id']} ERROR {e!r}; restarting server")
                    srv.stop()
                    time.sleep(10)
                    continue
                with open(out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if name in MATH_SETS:
                    say(f"{name} {rec['id']:>3} {'PASS' if rec['ok'] else 'FAIL'} gold {rec['gold']!r} got {rec['pred']!r} "
                        f"{rec['n_gen']} tok {rec['tok_s'] and round(rec['tok_s'], 1)} tok/s {rec['wall_s']} s"
                        + (" [budget hit]" if rec["budget_hit"] else ""))
                elif (i + 1) % 20 == 0 or i + 1 == len(todo):
                    say(f"{name} {i + 1}/{len(todo)} ({rec['tok_s'] and round(rec['tok_s'], 1)} tok/s)")
                i += 1
    finally:
        srv.stop()
    say("all done")


def cmd_report(out_dir=RUNS):
    print("Qwen3.8-27B (local, Q4_K_M, RTX 4060 8 GB), pass@1 with one try per problem\n")
    for name in MATH_SETS:
        p = os.path.join(out_dir, name + ".jsonl")
        if not os.path.exists(p):
            continue
        rs = [json.loads(l) for l in open(p, encoding="utf-8")]
        n, ok = len(rs), sum(r["ok"] for r in rs)
        hit = sum(r.get("budget_hit", False) for r in rs)
        none = sum(r["pred"] is None for r in rs)
        mins = sum(r["wall_s"] for r in rs) / 60
        print(f"{name}: {ok}/{n} = {100 * ok / max(n, 1):.1f}%   (thinking budget hit {hit}, no answer {none}, "
              f"{mins / max(n, 1):.0f} min per problem)")
        wrong = [f"{r['id']}: {r['pred']!r} vs {r['gold']!r}" for r in rs if not r["ok"]]
        if wrong:
            print("   wrong: " + "; ".join(wrong))
    p = os.path.join(out_dir, "ifeval.jsonl")
    if os.path.exists(p):
        rs = [json.loads(l) for l in open(p, encoding="utf-8")]
        n = len(rs)
        ps = sum(all(r["strict"]) for r in rs); pl = sum(all(r["loose"]) for r in rs)
        ins = sum(len(r["strict"]) for r in rs)
        is_ = sum(sum(r["strict"]) for r in rs); il = sum(sum(r["loose"]) for r in rs)
        print(f"ifeval ({n} prompts, thinking off): prompt-strict {100 * ps / n:.1f}%, prompt-loose {100 * pl / n:.1f}%, "
              f"instruction-strict {100 * is_ / ins:.1f}%, instruction-loose {100 * il / ins:.1f}%   "
              f"(cut off {sum(r['finish'] == 'length' for r in rs)})")


def cmd_smoke():
    global THINK_BUDGET, MATH_MAX
    THINK_BUDGET, MATH_MAX = 1500, 2500          # plumbing check only; the 0.8B can't solve these anyway
    d = os.path.join(HERE, "smoke")
    cmd_run(["aime_2026", "hmmt_feb_2026", "ifeval"], cpu=True, limit=2, out_dir=d)
    cmd_report(d)


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "run":
        cmd_run(sys.argv[2:])
    elif c == "report":
        cmd_report()
    elif c == "smoke":
        cmd_smoke()
