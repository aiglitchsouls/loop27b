"""Bigger thinking budget rerun (diagnostic, NOT a new score).

Question it answers: the misses that ran out of the 28,000-token thinking budget in the main run - would the
model have got them right with more room to think?

  * Waits for the main chain (chain.pid) to finish and the GPU to be free (--after-chain).
  * Picks every AIME/HMMT row that is wrong AND hit the thinking budget. Rows already shown to be right by
    hand are skipped (HMMT 7: same value as the key, written another way; checked numerically 2026-11-13).
  * Reruns each one, one try, same settings as the main run (temp 0.6, top_p 0.95, top_k 20, seed 42)
    except: thinking budget 48,000 tokens, 53,248-token context. Falls back to 40,000 / 45,056 if the
    bigger context does not load.
  * Runs until every target is done (no deadline; the user asked for it to finish).
  * After every problem, rewrites FULL_PICTURE.md: official scores + this rerun + caveats.

The official score stays the main run. Rerunning only the failures with extra help would inflate a score.

  python -I budget_rerun.py --after-chain        (unattended)
  python -I budget_rerun.py --summary            (just rewrite FULL_PICTURE.md)
  python -I budget_rerun.py --smoke              (0.8B on CPU, port 8098, 1 item, tiny budget: plumbing only)
"""
import ctypes
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_contest as rc  # noqa: E402

rc.LOG = os.path.join(HERE, "budget_log.txt")          # keep server messages out of the main run_log.txt

OUT = os.path.join(HERE, "runs_budget")
RLOG = os.path.join(HERE, "budget_log.txt")
PICTURE = os.path.join(HERE, "FULL_PICTURE.md")
CONFIGS = [(53248, 48000, 51000), (45056, 40000, 43000)]          # (context, thinking budget, max tokens)
SKIP = {("hmmt_feb_2026", "7"): "same value as the key, written in another form (checked numerically)"}
LABEL = {"aime_2026": "AIME 2026", "hmmt_feb_2026": "HMMT Feb 2026"}


def say(msg):
    line = time.strftime("%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with open(RLOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def awake():
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    except Exception:
        pass


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def targets():
    out = []
    for s in rc.MATH_SETS:
        for r in rows(os.path.join(rc.RUNS, s + ".jsonl")):
            if not r["ok"] and r.get("budget_hit") and (s, r["id"]) not in SKIP:
                out.append((s, r))
    return out


def chain_alive():
    try:
        import psutil
        pid = int(open(os.path.join(HERE, "chain.pid")).read().strip())
        return psutil.pid_exists(pid)
    except Exception:
        return False


def llama_running():
    import psutil
    return any((p.info["name"] or "").lower().startswith("llama-server") for p in psutil.process_iter(["name"]))


def chat(port, prompt, max_tokens):
    body = {"messages": [{"role": "user", "content": prompt + rc.MATH_SUFFIX}], "max_tokens": max_tokens,
            "seed": 42, "temperature": 0.6, "top_p": 0.95, "top_k": 20,
            "chat_template_kwargs": {"enable_thinking": True}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=10 * 3600) as r:
        js = json.loads(r.read())
    m = js["choices"][0]["message"]
    text, reasoning = m.get("content") or "", m.get("reasoning_content") or ""
    return {"text": text, "reasoning": reasoning, "finish": js["choices"][0].get("finish_reason"),
            "n_gen": js.get("usage", {}).get("completion_tokens") or 0,
            "tok_s": js.get("timings", {}).get("predicted_per_second"), "wall_s": round(time.time() - t0, 1)}


def start_server(cpu=False):
    for ctx, budget, mx in ([(8192, 300, 600)] if cpu else CONFIGS):
        rc.CTX, rc.THINK_BUDGET = ctx, budget
        srv = rc.Server(cpu)
        if cpu:
            srv.port = 8098
        try:
            srv.start()
            say(f"server up: context {ctx}, thinking budget {budget}")
            return srv, budget, mx
        except Exception as e:
            say(f"context {ctx} did not load ({e!r}); trying smaller")
            srv.stop()
            time.sleep(20)
    raise RuntimeError("no config loaded")


# ---------------------------------------------------------------- summary
def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "-"


def write_picture():
    L = ["# 27B contest run: the full picture", "",
         f"_Written {time.strftime('%Y-%m-%d %H:%M')} by budget_rerun.py. Model: Qwen3.8-27B, Q4_K_M, on the "
         "RTX 4060 (8 GB) with llama.cpp. One try per problem._", "",
         "## Official scores (main run, 28,000-token thinking budget)", "",
         "| Test | Score | Notes |", "|---|---|---|"]
    misses = {}
    for s in rc.MATH_SETS:
        rs = rows(os.path.join(rc.RUNS, s + ".jsonl"))
        if not rs:
            continue
        ok = sum(r["ok"] for r in rs)
        extra = sum(1 for r in rs if not r["ok"] and (s, r["id"]) in SKIP)
        note = f"{len(rs)}/{len(rc.load(s))} done"
        if extra:
            note += f"; {ok + extra}/{len(rs)} = {pct(ok + extra, len(rs))} counting answers equal in value to the key"
        L.append(f"| {LABEL[s]} | **{ok}/{len(rs)} = {pct(ok, len(rs))}** | {note} |")
        misses[s] = [r for r in rs if not r["ok"]]
        # user asked (2026-11-16) to count the problems the bigger-budget rerun got right; shown as its own row,
        # the official row above stays as the main run scored it
        wins = [r["id"] for r in rows(os.path.join(OUT, s + ".jsonl")) if r["ok"]]
        if wins:
            w = ok + len(wins)
            L.append(f"| {LABEL[s]}, counting the bigger-budget rerun wins ({', '.join(wins)}) | "
                     f"**{w}/{len(rs)} = {pct(w, len(rs))}** | {w + extra}/{len(rs)} = {pct(w + extra, len(rs))} "
                     f"also counting answers equal in value to the key. Mixed setup: only the misses got the "
                     f"48k budget, so this is an upper estimate, not a clean score |")
    ifr = rows(os.path.join(rc.RUNS, "ifeval.jsonl"))
    if ifr:
        n = len(ifr)
        ins = sum(len(r["strict"]) for r in ifr)
        L.append(f"| IFEval (thinking off) | **{pct(sum(all(r['strict']) for r in ifr), n)} prompt-strict** | "
                 f"{n}/541 done; prompt-loose {pct(sum(all(r['loose']) for r in ifr), n)}, instruction-strict "
                 f"{pct(sum(sum(r['strict']) for r in ifr), ins)}, instruction-loose "
                 f"{pct(sum(sum(r['loose']) for r in ifr), ins)} |")
    L += ["", "### Every math miss", "", "| Test | # | Model said | Key | Ran out of thinking budget? |", "|---|---|---|---|---|"]
    for s, ms in misses.items():
        for r in ms:
            said = (r["pred"] or "(none)").replace("\n", " ").replace("|", "\\|")
            said = said if len(said) < 60 else said[:57] + "..."
            tag = " (same value as key)" if (s, r["id"]) in SKIP else ""
            L.append(f"| {LABEL[s]} | {r['id']}{tag} | `{said}` | `{r['gold']}` | {'yes' if r.get('budget_hit') else 'no'} |")

    L += ["", "## Bigger thinking budget rerun (diagnostic, not a score)", "",
          "Only the misses that ran out of thinking budget, rerun once with a bigger budget. "
          "This tells us whether they were short of thinking room. It must **not** be added to the score: "
          "rerunning only the failures with extra help would inflate it.", ""]
    tg = targets()
    done = {(r["set"], r["id"]): r for s in rc.MATH_SETS for r in rows(os.path.join(OUT, s + ".jsonl"))}
    if not tg:
        L.append("_No budget-limited misses to rerun (or the main run has not finished yet)._")
    else:
        L += ["| Test | # | Key | Old answer | New answer | Right now? | Tokens | Ran out again? | Time |",
              "|---|---|---|---|---|---|---|---|---|"]
        for s, r in tg:
            d = done.get((s, r["id"]))
            old = (r["pred"] or "(none)")[:30]
            if d:
                new = (d["pred"] or "(none)").replace("\n", " ")[:30]
                L.append(f"| {LABEL[s]} | {r['id']} | `{r['gold']}` | `{old}` | `{new}` | {'**yes**' if d['ok'] else 'no'} | "
                         f"{d['n_gen']:,} of {d['budget']:,} | {'yes' if d['budget_hit'] else 'no'} | {d['wall_s'] / 3600:.1f} h |")
            else:
                L.append(f"| {LABEL[s]} | {r['id']} | `{r['gold']}` | `{old}` | not run yet | | | | |")
        fixed = sum(d["ok"] for d in done.values())
        L += ["", f"**Fixed by more thinking: {fixed} of {len(done)} rerun so far ({len(tg)} to rerun in total).**"]
    L += ["", "## How to read this", "",
          "- **Published numbers are not like-for-like.** The benchlm.ai AIME 2026 list (34 models, all lab-reported) "
          "typically uses several tries averaged and 64k-128k thinking. We used one try, 28k thinking, and a "
          "compressed (Q4) model on an 8 GB card. For reference there: Qwen3.6-27B 94.1%, Kimi K2.6 96.4%, "
          "GLM-5.2 99.2% (top).",
          "- **One problem is 3.3 points on AIME (30 problems) and 3.0 on HMMT (33).** A rerun could easily move "
          "the score by a problem either way.",
          "- **The answer checker is strict about form.** HMMT 7 was marked wrong but its answer equals the key's "
          "value to 15 decimal places; it is shown both ways above.",
          "- **The rerun is a diagnosis.** If misses turn right with more room, the 28k cap cost points; if not, "
          "the model was simply wrong on those."]
    with open(PICTURE, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


# ---------------------------------------------------------------- main
def run(cpu=False, limit=None):
    awake()
    tg = targets()[:limit]
    os.makedirs(OUT, exist_ok=True)
    done = {(r["set"], r["id"]) for s in rc.MATH_SETS for r in rows(os.path.join(OUT, s + ".jsonl"))}
    todo = [(s, r) for s, r in tg if (s, r["id"]) not in done]
    say(f"budget rerun: {len(tg)} budget-limited misses, {len(todo)} to do")
    write_picture()
    if not todo:
        return
    prompts = {(s, it["id"]): it["prompt"] for s in rc.MATH_SETS for it in rc.load(s)}
    srv, budget, mx = start_server(cpu)
    errors = 0
    try:
        i = 0
        while i < len(todo):
            s, r = todo[i]
            awake()
            if srv.proc is None:
                if rc.others_running():
                    say("another 27B job is running; waiting")
                rc.wait_for_gpu()
                srv, budget, mx = start_server(cpu)
            say(f"{s} {r['id']}: start (old answer {r['pred']!r}, key {r['gold']!r})")
            try:
                res = chat(srv.port, prompts[(s, r["id"])], mx)
            except Exception as e:
                errors += 1
                say(f"{s} {r['id']} ERROR {e!r}; restarting server")
                srv.stop()
                time.sleep(10)
                if errors >= 2:
                    say(f"{s} {r['id']}: failed twice, skipping")
                    errors, i = 0, i + 1
                continue
            pred = rc.last_boxed(res["text"]) or rc.last_boxed(res["reasoning"])
            rec = {"set": s, "id": r["id"], "gold": r["gold"], "old_pred": r["pred"], "pred": pred,
                   "ok": rc.math_ok(r["gold"], pred), "budget": budget, "finish": res["finish"],
                   "n_gen": res["n_gen"], "budget_hit": rc.BUDGET_MSG.strip()[:30] in res["reasoning"] + res["text"],
                   "tok_s": res["tok_s"], "wall_s": res["wall_s"], "text": res["text"],
                   "reasoning_chars": len(res["reasoning"])}
            with open(os.path.join(OUT if not cpu else os.path.join(HERE, "smoke"), s + ".jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            say(f"{s} {r['id']}: {'RIGHT' if rec['ok'] else 'wrong'} got {pred!r} key {r['gold']!r} "
                f"{rec['n_gen']} tok {res['wall_s'] / 3600:.1f} h" + (" [budget hit again]" if rec["budget_hit"] else ""))
            if not cpu:
                write_picture()
            errors, i = 0, i + 1
    finally:
        srv.stop()
    say("budget rerun finished")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--summary" in a:
        write_picture()
    elif "--smoke" in a:
        run(cpu=True, limit=1)
    elif "--after-chain" in a:
        with open(os.path.join(HERE, "budget_rerun.pid"), "w") as f:
            f.write(str(os.getpid()))
        say("waiting for the main chain to finish")
        while chain_alive():
            awake()
            time.sleep(120)
        for _ in range(60):                     # up to 10 min for its server to exit
            if not llama_running():
                break
            time.sleep(10)
        say("main chain finished; starting")
        try:
            run()
        except Exception as e:
            say(f"budget rerun crashed: {e!r}")
            write_picture()
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
