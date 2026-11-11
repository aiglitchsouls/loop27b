# loop27b

Qwen3.8-27B running on an 8 GB gaming GPU, with two loops around it that make it more accurate at maths and coding.

**It is not a trained model.** The weights are the stock `Qwen3.8-27B-UD-Q4_K_M.gguf`. Everything that improves it is in
`loop27b.py`: prompts, a Python sandbox, and fix-and-retry rules.

## Hardware it was tested on

RTX 4060 8 GB, i5-12400F, 32 GB RAM, Windows 11, llama.cpp. 26 of the model's 65 layers sit on the GPU, the rest in
system RAM (`-ngl 26 -fa on -c 8192`), and the model's own draft head (`--spec-type draft-mtp`) adds about 65% speed.
Temperature 0, seed 42.

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

Running now on the plain 27B with thinking on (not the loop), to compare against published model-card numbers:
`D:\timepass\contest_bench`. AIME 2026: 10 of 10 right so far (2026-11-11). One try per problem, 30 problems, so
one problem is 3.3 points.

## What it is not

- Not new: making a model write and run code for maths is known (PAL, Program-of-Thought, 2022).
- Not fast: minutes per problem on this card.
- Not a general improvement: it helps maths that can be computed and code with examples in the task.

## Folders

- `loop27b.py`: the tool, self-contained (needs only this venv and `D:\timepass\llama_cpp_bin`, `models\qwen3.8-27b`).
- `reproduce/`: frozen copies of the scripts that produced the results, as they were run. They use their original
  paths (`improve_27b`, `bench_14b`, `hard_bench`, `contest_bench`), so run them from there.
- `results/`: copies of the result rows and summaries (`locked_test_*`, `hard_bench_*`).
