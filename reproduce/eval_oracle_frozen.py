import os
import sys
import json
import time
import re
import subprocess
import urllib.request
import tempfile
import hashlib

# 16 Multi-Step Math Problems (Exact Integer Ground Truth)
MATH_PROBLEMS = [
    ("A shop sells pens at 3 for $4. How many dollars do 27 pens cost?", 36),
    ("Maria has 5 boxes with 12 eggs each. She uses 18 eggs, then gives away a third of the eggs that remain. How many eggs does she keep?", 28),
    ("A train leaves at 9:40 and arrives at 13:15 the same day. How many minutes does the trip take?", 215),
    ("Tom is 3 times as old as his son. In 12 years Tom will be twice as old as his son. How old is Tom now?", 36),
    ("A rectangle has a perimeter of 50 cm and a length of 15 cm. What is its area in square cm?", 150),
    ("A school has 240 students. 35% walk to school, a quarter of the rest take the bus, and everyone else is driven. How many students are driven?", 117),
    ("A car uses 6 litres of fuel per 100 km. Fuel costs $2 per litre. How many dollars does the fuel for a 450 km trip cost?", 54),
    ("What is the sum of all integers from 1 to 100 inclusive that are divisible by 3 or by 5?", 2418),
    ("A worker earns $18 per hour for the first 40 hours in a week and 1.5 times that rate for every hour beyond 40. How many dollars does she earn for 46 hours?", 882),
    ("Pipe A fills a tank in 6 hours and pipe B fills it in 3 hours. With both pipes open, how many minutes does it take to fill the tank?", 120),
    ("The sequence 4, 9, 16, 25, ... continues in the same pattern. What is the 10th term?", 121),
    ("A jacket costs $80. It is discounted by 25%, then a 10% tax is added to the discounted price. What is the final price in dollars?", 66),
    ("Jenny reads 14 pages on Monday and each day reads 3 more pages than the day before. How many pages has she read in total from Monday to Friday?", 100),
    ("How many seconds are there in 2.5 hours?", 9000),
    ("Three consecutive even numbers add up to 78. What is the largest of them?", 28),
    ("A box holds 7 red, 5 blue and 8 green marbles. Ali removes all the blue marbles and half of the green marbles. How many marbles are left in the box?", 11),
]

# 8 Novel Unseen Coding Tasks (Executed in Isolated Python Subprocesses)
CODING_TASKS = [
    {
        "entry_point": "is_leap_year",
        "prompt": 'def is_leap_year(year):\n    """Return True if year is a leap year in the Gregorian calendar."""\n',
        "test": "def check(candidate):\n    assert candidate(2024) is True\n    assert candidate(1900) is False\n    assert candidate(2000) is True\n    assert candidate(2023) is False\n"
    },
    {
        "entry_point": "celsius_to_fahrenheit",
        "prompt": 'def celsius_to_fahrenheit(c):\n    """Convert temperature c from Celsius to Fahrenheit."""\n',
        "test": "def check(candidate):\n    assert candidate(0) == 32\n    assert candidate(100) == 212\n    assert abs(candidate(-40) - (-40)) < 1e-9\n"
    },
    {
        "entry_point": "clamp",
        "prompt": 'def clamp(val, low, high):\n    """Clamp val so it is at least low and at most high (low <= high)."""\n',
        "test": "def check(candidate):\n    assert candidate(5, 0, 10) == 5\n    assert candidate(-2, 0, 10) == 0\n    assert candidate(15, 0, 10) == 10\n"
    },
    {
        "entry_point": "word_count",
        "prompt": 'def word_count(s):\n    """Return the number of whitespace-separated words in string s."""\n',
        "test": "def check(candidate):\n    assert candidate('hello world') == 2\n    assert candidate('   single   ') == 1\n    assert candidate('') == 0\n"
    },
    {
        "entry_point": "first_duplicate",
        "prompt": 'def first_duplicate(lst):\n    """Return the first element that appears more than once, scanning left to right. Return None if all unique."""\n',
        "test": "def check(candidate):\n    assert candidate([2, 1, 3, 5, 3, 2]) == 3\n    assert candidate([1, 2, 3]) is None\n    assert candidate([]) is None\n"
    },
    {
        "entry_point": "valid_brackets",
        "prompt": 'def valid_brackets(s):\n    """Return True if the brackets in s are balanced. Brackets are (), [], {}. Other characters are ignored."""\n',
        "test": "def check(candidate):\n    assert candidate('()') is True\n    assert candidate('([{}])') is True\n    assert candidate('([)]') is False\n    assert candidate('(') is False\n    assert candidate('a(b[c]d)e') is True\n"
    },
    {
        "entry_point": "two_sum",
        "prompt": 'def two_sum(nums, target):\n    """Return the indices [i, j] of two numbers in nums that add to target, with i < j. Assume exactly one solution."""\n',
        "test": "def check(candidate):\n    assert candidate([2, 7, 11, 15], 9) == [0, 1]\n    assert candidate([3, 2, 4], 6) == [1, 2]\n    assert candidate([3, 3], 6) == [0, 1]\n"
    },
    {
        "entry_point": "roman_to_int",
        "prompt": 'def roman_to_int(s):\n    """Convert a Roman numeral string s to an integer. Handles I, V, X, L, C, D, M and subtractive forms."""\n',
        "test": "def check(candidate):\n    assert candidate('III') == 3\n    assert candidate('LVIII') == 58\n    assert candidate('MCMXCIV') == 1994\n"
    }
]

def verify_code_in_sandbox(code: str, test_code: str, entry_point: str, timeout: int = 5) -> tuple[bool, str]:
    full_prog = code + "\n\n" + test_code + f"\n\ncheck({entry_point})\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(full_prog)
        temp_path = f.name
    try:
        p = subprocess.run([sys.executable, "-I", temp_path], capture_output=True, text=True, timeout=timeout)
        if p.returncode == 0:
            return True, "PASSED"
        err = p.stderr.strip().splitlines()
        return False, err[-1] if err else "Execution Error"
    except subprocess.TimeoutExpired:
        return False, "Timeout (>5s)"
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

def compute_sovereign_score(math_passed: int, code_passed: int, memory_passed: bool, gen_speed: float, vram_mb: float) -> float:
    """
    Computes holistic Sovereign Score (0 to 100):
    - Math Accuracy (35%)
    - Code Accuracy (35%)
    - Memory Needle Retention (15%)
    - Generation Speed bonus (15%)
    """
    math_score = (math_passed / 16.0) * 35.0
    code_score = (code_passed / 8.0) * 35.0
    mem_score = 15.0 if memory_passed else 0.0
    
    # Speed bonus: baseline 13.5 tok/s = 7.5 pts, 25 tok/s = 15.0 pts
    speed_ratio = min(2.0, max(0.0, gen_speed / 13.5))
    speed_score = (speed_ratio / 2.0) * 15.0
    
    return round(math_score + code_score + mem_score + speed_score, 2)
