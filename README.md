# loop27b

Qwen3.8-27B running on an 8 GB gaming GPU, with two loops around it that make it more accurate at maths and coding.

**It is not a trained model.** The weights are the stock `Qwen3.8-27B-UD-Q4_K_M.gguf`. Everything that improves it is in
`loop27b.py`: prompts, a Python sandbox, and fix-and-retry rules.

## Hardware it was tested on

RTX 4060 8 GB, i5-12400F, 32 GB RAM, Windows 11, llama.cpp. 26 of the model's 65 layers sit on the GPU, the rest in
system RAM (`-ngl 26 -fa on -c 8192`), and the model's own draft head (`--spec-type draft-mtp`) adds about 65% speed.
Temperature 0, seed 42.

## Run the server yourself

Tested with llama.cpp build 12094 (commit `6b9c0cf`) on Windows; the same flags work on Linux.

**Loops (maths, code), 26 of 65 layers on the GPU.** This is what `loop27b.py` starts:

```
llama-server -m Qwen3.8-27B-UD-Q4_K_M.gguf --host 127.0.0.1 --port 8096 \
  -ngl 26 -fa on -c 8192 --spec-type draft-mtp
```

Requests: `temperature 0`, `seed 42`, thinking off via `"chat_template_kwargs": {"enable_thinking": false}`.

**Contest runs (AIME 2026, HMMT Feb 2026), 32k context, layers placed automatically:**

```
llama-server -m Qwen3.8-27B-UD-Q4_K_M.gguf --host 127.0.0.1 --port 8097 -np 1 \
  -fit on -fa on -c 32768 -ctk q8_0 -ctv q8_0 --spec-type draft-mtp \
  --reasoning-budget 28000 \
  --reasoning-budget-message $'\n\nI am out of thinking time. I will now give my best final answer.\n'
```

Requests: `temperature 0.6`, `top_p 0.95`, `top_k 20`, `seed 42`, thinking on, `max_tokens 31000`. IFEval used the
same server with thinking off, greedy, `max_tokens 3072`.

`--spec-type draft-mtp` uses the model's built-in multi-token-prediction head as the draft model: about 3.5 → 5.7
tokens/s here.

## Use

```
python -I loop27b.py selftest
python -I loop27b.py math "How many integers from 1 to 10**12 are divisible by 3, 5 or 7?"
python -I loop27b.py code task.py          # a function stub with a docstring
python -I loop27b.py math "..." --port 8097   # attach to a server that is already running
```

It refuses to start its own 27B while another llama-server or one of the benchmark runners in `D:\timepass` is using
the GPU.

## How it works

**Maths (variant m1):** the model writes a Python script instead of counting in its head. The sandbox runs it; the
printed number is the answer. If the script crashes or prints nothing, the error goes back with "fix it", up to 2
times. 1,024 tokens per reply.

**Coding (variant c6):** the model writes the function. The examples written in the task's docstring are run against
it. Failures go back with "fix it", up to 2 times. The model may instead answer KEEP when it judges the example itself
wrong (HumanEval has a few wrong examples). The answer that passes the most examples wins; a cut-off answer gets
"resend only the code". 2,048 tokens per reply.

**Sandbox:** this venv's Python in isolated mode, working folder `tmp/`, 10 s limit. Code that names file-writing,
process or network modules is refused before it runs. It is a blocklist, not a container.

## Results

### Locked test (the target: make at most half the original model's mistakes)

Practice and locked sets were split before any tuning; the locked set was run twice in total, enforced in code.

| | Original 27B | loop27b |
|---|---|---|
| Maths, 136 problems | 9 wrong | **0 wrong** |
| Coding, 90 tasks (odd HumanEval + 8 originals) | 2 wrong | **1 wrong** |

Caveats: the KEEP rule was written after seeing locked task HumanEval/47 fail, so the coding result is not fully
blind, and the margin is one task. The original was run with thinking off (thinking on was never measured).
These sets are close to saturated for both models.

### Hard maths set (40 practice problems, 10 kinds, answers checked two ways)

| | 27B plain | loop27b | Opus, no tools | Opus + Python |
|---|---|---|---|---|
| Right | 7/40 | **36/40** | 31/40 | 40/40 |
| Time | 13.5 min/problem | 2.8 min/problem | 14 min total | 52 s total |

I built this set, and its problems are ones where code helps, so it favours the method. "Opus" is the current
Opus run as a Claude Code subagent, not Opus 4.5 and not a clean API call. Breakdown: `results/hard_bench_practice.md`.

### Contest maths (AIME 2026, HMMT Feb 2026) and IFEval

The **plain 27B** (no loop, no tools), thinking on, one try per problem, run 2026-11-11 to 11-15 on the same card
(`-fit on -fa on -c 32768`, q8_0 KV cache, MTP draft head, about 3.5 tok/s). Maths: temp 0.6, top_p 0.95, top_k 20,
seed 42, 28,000-token thinking budget, answer = last `\boxed{}` checked with math-verify. IFEval: thinking off,
greedy, scored with Google's own checker.

| Test | Score | Notes |
|---|---|---|
| AIME 2026 (30) | **29/30 = 96.7%** | only #20 wrong (answered 277285, not even a valid AIME answer) |
| HMMT Feb 2026 (33) | **28/33 = 84.8%** | 29/33 = 87.9% counting #7, whose answer equals the key's value to 15 digits in another form |
| IFEval (541) | **80.2% prompt-strict** | prompt-loose 84.3%, instruction-strict 86.3%, instruction-loose 89.6% |

**Bigger thinking budget (diagnostic).** All four real HMMT misses had run out of the 28k budget. Rerun once with
48,000 tokens: #8 and #18 became right, #17 answered 1572 (key 1574), #20 gave the same wrong answer. Counting those
two wins, HMMT is **30/33 = 90.9%** (31/33 with #7), but that is a mixed setup: only the misses got the bigger
budget, so treat it as an upper estimate, not a clean score.

How to compare: benchlm.ai's AIME 2026 list (34 models, all lab-reported, usually several tries averaged and
64k-128k thinking) has Qwen3.6-27B at 94.1%, Kimi K2.6 at 96.4%, GLM-5.2 at 99.2%. Our 96.7% is from one try with
28k thinking on a Q4 model, so it is roughly level with that group, not proof of beating any of them; one problem
is 3.3 points. This measures the stock model, not the loop.

Rows and summaries: `results/contest/` (`FULL_PICTURE.md` is the write-up). Scripts: `reproduce/run_contest.py`,
`reproduce/chain.py`, `reproduce/budget_rerun.py`.

## What it is not

- Not new: making a model write and run code for maths is known (PAL, Program-of-Thought, 2022).
- Not fast: minutes per problem on this card.
- Not a general improvement: it helps maths that can be computed and code with examples in the task.

## Folders

- `loop27b.py`: the tool, self-contained (needs only this venv and `D:\timepass\llama_cpp_bin`, `models\qwen3.8-27b`).
- `reproduce/`: frozen copies of the scripts that produced the results, as they were run. They use their original
  paths (`improve_27b`, `bench_14b`, `hard_bench`, `contest_bench`), so run them from there.
- `results/`: copies of the result rows and summaries (`locked_test_*`, `hard_bench_*`, `contest/`).
