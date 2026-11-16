"""Unattended chain (the user is away): finish the hard-bench practice run, then the contest tests.

  1. hard_bench/run_hard.py practice:m1 practice:og   (resumable; m1 is already complete)
  2. hard_bench/practice_report.py                     -> hard_bench/PRACTICE_RESULTS.md
  3. contest_bench/run_contest.py run aime_2026 hmmt_feb_2026 ifeval   (resumable)
  4. contest_bench/run_contest.py report               -> contest_bench/REPORT.txt

Each step is retried up to 3 times if it crashes (every runner resumes from its saved rows).
Keeps Windows awake for its whole life (SetThreadExecutionState; no power setting is changed).
Everything stays under D:\\timepass. Log: contest_bench/chain_log.txt
"""
import ctypes
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
HB = os.path.join(ROOT, "hard_bench")
LOG = os.path.join(HERE, "chain_log.txt")


def say(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%m-%d %H:%M:%S ") + msg + "\n")


def llama_running():
    p = subprocess.run(["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"], capture_output=True, text=True)
    return "llama-server.exe" in p.stdout


def step(name, args, cwd, out, tmp, tries=3, need_free_gpu=False):
    env = dict(os.environ, TEMP=tmp, TMP=tmp, PYTHONIOENCODING="utf-8")
    os.makedirs(tmp, exist_ok=True)
    for t in range(1, tries + 1):
        if need_free_gpu:
            for _ in range(60):                     # up to 10 min for an old server to exit
                if not llama_running():
                    break
                time.sleep(10)
        say(f"start {name} (try {t})")
        with open(out, "a", encoding="utf-8") as f:
            rc = subprocess.run([PY, "-I"] + args, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT).returncode
        say(f"end {name}: exit {rc}")
        if rc == 0:
            return True
        time.sleep(60)
    return False


if __name__ == "__main__":
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    say("chain started")
    imp_tmp = os.path.join(ROOT, "improve_27b", "tmp")
    if "--contest-only" not in sys.argv:
        step("hard bench practice", ["run_hard.py", "practice:m1", "practice:og"], HB,
             os.path.join(HB, "practice_stdout.txt"), imp_tmp, need_free_gpu=True)
        step("practice report", ["practice_report.py"], HB, os.path.join(HB, "practice_report_stdout.txt"), imp_tmp,
             tries=1)
    step("contest tests", ["run_contest.py", "run", "aime_2026", "hmmt_feb_2026", "ifeval"], HERE,
         os.path.join(HERE, "run_stdout.txt"), os.path.join(HERE, "tmp"), need_free_gpu=True)
    step("contest report", ["run_contest.py", "report"], HERE, os.path.join(HERE, "REPORT.txt"),
         os.path.join(HERE, "tmp"), tries=1)
    say("chain finished")
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
