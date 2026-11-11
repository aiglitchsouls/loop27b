"""Fresh math sets for the 27B improvement loop. Written once, before any tuning.

  math_dev.json      80 problems: the benchmark's 10 kinds x 8, new seed. Tuning happens here.
  math_test_new.json 40 problems: 5 kinds the loop never sees during tuning x 8. LOCKED test.

Every answer is computed twice (formula and brute force); the script refuses to write if they
disagree, if an answer is not an integer, or if a question repeats one in the benchmark set.
"""
import itertools
import json
import os
import random
from datetime import date, datetime, timedelta
from fractions import Fraction
from math import comb, lcm

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(os.path.dirname(HERE), "bench_14b", "math_heldout.json")
R = random.Random()
items = []


def add(kind, q, formula, brute):
    assert formula == brute, (kind, q, formula, brute)
    assert float(formula).is_integer(), (kind, q, formula)
    if any(i["question"] == q for i in items):
        return  # duplicate draw: the caller draws again
    items.append({"id": f"{kind}_{sum(1 for i in items if i['kind'] == kind) + 1}", "kind": kind,
                  "question": q, "answer": int(formula)})


# ---- the benchmark's 10 kinds (same generators as bench_14b/make_math_set.py)

def incl_excl():
    while True:
        n = R.randrange(300, 3001)
        a, b = R.sample([3, 4, 6, 7, 9, 11], 2)
        c = R.choice([5, 8, 10, 13])
        if c not in (a, b):
            break
    q = (f"How many integers from 1 to {n} inclusive are divisible by at least one of {a} and {b}, "
         f"and are not divisible by {c}?")

    def cnt(*ds):
        return n // lcm(*ds)
    f = cnt(a) + cnt(b) - cnt(a, b) - (cnt(a, c) + cnt(b, c) - cnt(a, b, c))
    add("incl_excl", q, f, sum(1 for x in range(1, n + 1) if (x % a == 0 or x % b == 0) and x % c != 0))


def sum_multiples():
    n = R.randrange(150, 1001)
    a, b = R.sample([3, 4, 5, 6, 7, 8], 2)

    def s(d):
        k = n // d
        return d * k * (k + 1) // 2
    q = f"What is the sum of all integers from 1 to {n} inclusive that are divisible by {a} or by {b}?"
    add("sum_multiples", q, s(a) + s(b) - s(lcm(a, b)), sum(x for x in range(1, n + 1) if x % a == 0 or x % b == 0))


def percent_chain():
    while True:
        p = R.randrange(40, 801, 20)
        d = R.choice([10, 15, 20, 25, 30, 35, 40])
        t = R.choice([5, 8, 10, 12, 20])
        c = R.choice([0, 5, 10])
        price = Fraction(p) * (100 - d) / 100 * (100 + t) / 100 - c
        if price.denominator == 1 and price > 0:
            break
    q = (f"A coat costs ${p}. It is discounted by {d}%, then {t}% sales tax is added to the discounted price"
         + (f", and finally a ${c} gift card is applied" if c else "") + ". What is the final price in dollars?")
    brute = Fraction(p)
    brute -= brute * d / 100
    brute += brute * t / 100
    brute -= c
    add("percent_chain", q, price, brute)


def work_rate():
    while True:
        a, b, c = R.randrange(2, 13), R.randrange(2, 13), R.randrange(4, 25)
        rate = Fraction(1, a) + Fraction(1, b) - Fraction(1, c)
        if rate > 0 and (Fraction(60) / rate).denominator == 1:
            break
    q = (f"Pipe A can fill a tank in {a} hours and pipe B can fill it in {b} hours. A drain can empty the full "
         f"tank in {c} hours. Starting with an empty tank and all three open, how many minutes does it take to fill the tank?")
    vol, m = Fraction(0), 0
    while vol < 1:
        vol += rate / 60
        m += 1
    add("work_rate", q, Fraction(60) / rate, m)


def meeting():
    while True:
        u, v = R.randrange(40, 121, 5), R.randrange(40, 121, 5)
        x = R.randrange(100, 901, 10)
        delay = R.choice([0, 30, 60])
        rem = Fraction(x) - Fraction(u * delay, 60)
        if rem <= 0:
            continue
        t = Fraction(delay) + rem / (u + v) * 60
        if t.denominator == 1:
            break
    q = (f"Two towns are {x} km apart. A train leaves the first town toward the second at {u} km/h. "
         + (f"{delay} minutes later, a" if delay else "At the same time, a")
         + f" second train leaves the second town toward the first at {v} km/h. How many minutes after the first train "
         f"leaves do the two trains meet?")
    gap, m = Fraction(x), 0
    while gap > 0:
        gap -= Fraction(u, 60) + (Fraction(v, 60) if m >= delay else 0)
        m += 1
    add("meeting", q, t, m)


def committee():
    m, w = R.randrange(4, 10), R.randrange(4, 10)
    k = R.randrange(3, 6)
    people = ["M"] * m + ["W"] * w
    brute = sum(1 for g in itertools.combinations(range(m + w), k)
                if any(people[i] == "M" for i in g) and any(people[i] == "W" for i in g))
    q = (f"A club has {m} men and {w} women. In how many ways can a committee of {k} people be chosen "
         f"so that it includes at least one man and at least one woman?")
    add("committee", q, comb(m + w, k) - comb(m, k) - comb(w, k), brute)


def seats():
    r, s, d = R.randrange(12, 41), R.randrange(10, 31), R.randrange(1, 5)
    q = (f"A theatre has {r} rows. The first row has {s} seats and each row after the first has {d} more "
         f"seats than the row in front of it. How many seats are there in total?")
    add("arith_series", q, r * s + d * r * (r - 1) // 2, sum(s + d * i for i in range(r)))


def growth():
    n0 = R.randrange(20, 301, 10)
    fct = R.choice([2, 3])
    h = R.choice([2, 3, 4, 5, 6])
    k = R.randrange(3, 8)
    T = h * k
    word = {2: "doubles", 3: "triples"}[fct]
    q = f"A bacteria culture starts with {n0} cells and {word} every {h} hours. How many cells are there after {T} hours?"
    x = n0
    for hour in range(1, T + 1):
        if hour % h == 0:
            x *= fct
    add("growth", q, n0 * fct ** k, x)


def shift():
    s = datetime(2026, 1, 1, R.randrange(18, 24), R.randrange(0, 60))
    e = datetime(2026, 1, 2, R.randrange(4, 10), R.randrange(0, 60))
    q = (f"A night shift starts at {s:%H:%M} and ends at {e:%H:%M} the next morning. "
         f"How many minutes long is the shift?")
    m, t = 0, s
    while t < e:
        t += timedelta(minutes=1)
        m += 1
    add("time_midnight", q, (24 * 60 - (s.hour * 60 + s.minute)) + e.hour * 60 + e.minute, m)


def ages():
    while True:
        k, j = R.randrange(3, 7), R.randrange(2, 4)
        y = R.randrange(4, 25)
        if k > j and (y * (j - 1)) % (k - j) == 0:
            b = y * (j - 1) // (k - j)
            if 2 <= b <= 30:
                break
    q = (f"Anna is {k} times as old as her nephew Ben. In {y} years, Anna will be {j} times as old as Ben. "
         f"How old is Anna now?")
    add("ages", q, k * b, [k * bb for bb in range(1, 200) if k * bb + y == j * (bb + y)][0])


# ---- 5 new kinds, used only in the locked test

def power_mod():
    a, e, m = R.randrange(3, 20), R.randrange(50, 400), R.choice([7, 11, 13, 17, 19, 23])
    if a % m == 0:
        a += 1
    x = 1
    for _ in range(e):
        x = x * a % m
    add("power_mod", f"What is the remainder when {a} raised to the power {e} is divided by {m}?", pow(a, e, m), x)


def digit_sum():
    n, s = R.randrange(500, 5001), R.randrange(5, 20)
    q = f"How many integers from 1 to {n} inclusive have digits that add up to exactly {s}?"
    # formula side: digit DP over the decimal string of n
    digits = list(map(int, str(n)))
    from functools import lru_cache

    @lru_cache(None)
    def dp(i, rem, tight):
        if rem < 0:
            return 0
        if i == len(digits):
            return 1 if rem == 0 else 0
        top = digits[i] if tight else 9
        return sum(dp(i + 1, rem - d, tight and d == top) for d in range(top + 1))
    add("digit_sum", q, dp(0, s, True), sum(1 for x in range(1, n + 1) if sum(map(int, str(x))) == s))


def depreciation():
    while True:
        pct = R.choice([10, 20, 25, 40, 50])
        yrs = R.randrange(2, 6)
        base = R.randrange(3, 40) * 1000
        v = Fraction(base) * Fraction(100 - pct, 100) ** yrs
        if v.denominator == 1:
            break
    q = (f"A machine bought for ${base} loses {pct}% of its value at the end of every year. "
         f"What is it worth in dollars after {yrs} years?")
    x = Fraction(base)
    for _ in range(yrs):
        x -= x * pct / 100
    add("depreciation", q, v, x)


def date_span():
    y = R.choice([2027, 2028, 2031, 2032])
    a = date(y, R.randrange(1, 7), R.randrange(1, 29))
    b = date(y, R.randrange(7, 13), R.randrange(1, 29))
    q = (f"How many days are there from {a:%B} {a.day}, {y} to {b:%B} {b.day}, {y}, "
         f"counting both the first and the last day?")
    n, d = 0, a
    while d <= b:
        n += 1
        d += timedelta(days=1)
    add("date_span", q, (b - a).days + 1, n)


def coin_ways():
    n = R.randrange(40, 201)
    coins = R.choice([(1, 5, 10, 25), (1, 2, 5, 10), (1, 5, 10, 20, 50)])
    ways = [1] + [0] * n
    for c in coins:
        for v in range(c, n + 1):
            ways[v] += ways[v - c]
    brute = 0
    for combo in itertools.product(*[range(n // c + 1) for c in coins[1:]]):
        rest = n - sum(k * c for k, c in zip(combo, coins[1:]))
        brute += rest >= 0  # the 1-unit coin fills any non-negative remainder in exactly one way
    names = ", ".join(str(c) for c in coins[:-1]) + f" and {coins[-1]}"
    add("coin_ways", f"In how many different ways can you make {n} cents using coins worth {names} cents? "
                     f"(Order does not matter.)", ways[n], brute)


def build(seed, gens, path):
    global items
    items = []
    R.seed(seed)
    for g in gens:
        start, tries = len(items), 0
        while len(items) - start < 8:
            g()
            tries += 1
            assert tries < 500, g.__name__
    bench_qs = {i["question"] for i in json.load(open(BENCH, encoding="utf-8"))}
    dup = [i["id"] for i in items if i["question"] in bench_qs]
    assert not dup, f"repeats a benchmark question: {dup}"
    assert len({i["question"] for i in items}) == len(items), "duplicate question inside the set"
    json.dump(items, open(path, "w", encoding="utf-8"), indent=1)
    print(len(items), "->", os.path.basename(path))
    for kind in dict.fromkeys(i["kind"] for i in items):
        ex = next(i for i in items if i["kind"] == kind)
        print(f"  [{kind}] {ex['question']}  -> {ex['answer']}")


if __name__ == "__main__":
    build(31, [incl_excl, sum_multiples, percent_chain, work_rate, meeting, committee, seats, growth, shift, ages],
          os.path.join(HERE, "math_dev.json"))
    build(97, [power_mod, digit_sum, depreciation, date_span, coin_ways], os.path.join(HERE, "math_test_new.json"))
