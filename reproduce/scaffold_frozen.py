"""Frozen copy of autoresearch_14b/harness_scaffold.py as the 14B benchmark ran it (read 2026-11-05 05:17).

The original file is edited by another agent (at 14:15 it gained a preamble that pre-imports
datetime/timedelta). Benchmarks import this copy so 14B and 27B runs use the same scaffold.
Only the two classes bench.py needs are kept; their code is unchanged.
"""
import os
import re
import subprocess
import sys
import tempfile


class DeterministicTools:
    @staticmethod
    def run_python_sandbox(code: str, timeout: int = 5) -> tuple[bool, str]:
        py_bin = r"D:\timepass\.venv\Scripts\python.exe"
        if not os.path.exists(py_bin):
            py_bin = sys.executable
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            temp_path = f.name
        try:
            p = subprocess.run([py_bin, temp_path], capture_output=True, text=True, timeout=timeout)
            if p.returncode == 0:
                return True, p.stdout.strip()
            err = p.stderr.strip().splitlines()
            return False, err[-1] if err else "Execution Error"
        except subprocess.TimeoutExpired:
            return False, "TimeoutExpired (>5s)"
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass


class Guardrails:
    @staticmethod
    def extract_number(text: str) -> float | None:
        # Boxed LaTeX
        m = re.findall(r"\\boxed\{([^\}]+)\}", text)
        if m:
            clean = re.sub(r"[^\d\.\-]", "", m[-1])
            try:
                return float(clean)
            except ValueError:
                pass
        # Answer: <number>
        m = re.findall(r"Answer:\s*\$?\s*(-?[\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
        if m:
            clean = m[-1].replace(",", "")
            try:
                return float(clean)
            except ValueError:
                pass
        # Standalone number in tail
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if lines:
            nums = re.findall(r"(-?[\d,]+(?:\.\d+)?)", lines[-1])
            if nums:
                try:
                    return float(nums[-1].replace(",", ""))
                except ValueError:
                    pass
        return None

    @staticmethod
    def extract_code(text: str, entry_point: str, prompt: str) -> str:
        m = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
        code = m.group(1).strip() if m else text.strip()
        if f"def {entry_point}" not in code:
            code = prompt + "\n" + code
        return code
