"""Hard math sets for the head-to-head (local 27B setups vs cloud models).

  math_hard_practice.json   10 kinds x 4  = 40   tuning / calibration happens here
  math_hard_locked.json     10 kinds x 8  = 80   LOCKED: scored only, never tuned on

Every answer is computed by two independent methods; the script refuses to write if they disagree,
if an answer is not a non-negative integer below 2**53, or if a question repeats.
Three kinds are easy once you write a script (lattice, coins, dice). Seven need an idea even with a
script, because the obvious loop is far too long for the 10-second sandbox.
"""
import itertools
import json
import os
import random
import sys
from collections import defaultdict
from fractions import Fraction
from functools import lru_cache
from math import comb, gcd, lcm

sys.setrecursionlimit(10000)
HERE = os.path.dirname(os.path.abspath(__file__))
R = random.Random()
items = []


def add(kind, q, m1, m2):
    assert m1 == m2, (kind, q, m1, m2)
    assert isinstance(m1, int) and 0 <= m1 < 2 ** 53, (kind, q, m1)
    if any(i["question"] == q for i in items):
        return
    items.append({"id": f"{kind}_{sum(1 for i in items if i['kind'] == kind) + 1}", "kind": kind,
                  "question": q, "answer": m1})


# ---------------------------------------------------------------- script-easy kinds

def lattice_blocked():
    a, b = R.randrange(12, 18), R.randrange(12, 18)
    k = R.choice([3, 4])
    pts = set()
    while len(pts) < k:
        pts.add((R.randrange(1, a), R.randrange(1, b)))
    pts = sorted(pts)
    q = (f"A robot walks on a grid from the point (0, 0) to the point ({a}, {b}). Each step moves it exactly one unit "
         f"to the right (x increases by 1) or one unit up (y increases by 1). It may not pass through any of these "
         f"points: {', '.join(str(p) for p in pts)}. How many different paths can it take?")
    ways = [[0] * (b + 1) for _ in range(a + 1)]
    for x in range(a + 1):
        for y in range(b + 1):
            if (x, y) in pts:
                continue
            ways[x][y] = 1 if x == y == 0 else (ways[x - 1][y] if x else 0) + (ways[x][y - 1] if y else 0)

    def paths(u, v):
        dx, dy = v[0] - u[0], v[1] - u[1]
        return comb(dx + dy, dx) if dx >= 0 and dy >= 0 else 0
    total = 0
    for r in range(k + 1):
        for s in itertools.combinations(pts, r):
            chain = [(0, 0), *s, (a, b)]
            prod = 1
            for u, v in zip(chain, chain[1:]):
                prod *= paths(u, v)
            total += (-1) ** r * prod
    if total > 0:
        add("lattice_blocked", q, ways[a][b], total)


def coin_big():
    coins = sorted(R.sample([2, 3, 5, 7, 10, 12, 15, 20, 25, 30, 50], 5))
    amount = R.randrange(1500, 4001)
    q = (f"In how many different ways can you make a total of exactly {amount} using coins with the values "
         f"{', '.join(map(str, coins[:-1]))} and {coins[-1]}? You may use any number of coins of each value, "
         f"and the order of the coins does not matter.")
    w = [1] + [0] * amount
    for c in coins:
        for v in range(c, amount + 1):
            w[v] += w[v - c]
    cur = [1] + [0] * amount  # second method: choose how many of each coin explicitly
    for c in coins:
        nxt = [0] * (amount + 1)
        for v, n in enumerate(cur):
            if n:
                for t in range(v, amount + 1, c):
                    nxt[t] += n
        cur = nxt
    if w[amount] > 0:
        add("coin_big", q, w[amount], cur[amount])


def dice_prob():
    n, s, k = R.randrange(4, 7), R.choice([6, 8]), R.randrange(3, 8)
    q = (f"You roll {n} fair {s}-sided dice, each with faces numbered 1 to {s}. What is the probability that the sum "
         f"of the dice is divisible by {k} and at least one die shows a {s}? Write the probability as a fraction p/q "
         f"in lowest terms. What is p + q?")
    good = sum(1 for roll in itertools.product(range(1, s + 1), repeat=n) if sum(roll) % k == 0 and s in roll)
    st = {(0, False): 1}
    for _ in range(n):
        new = defaultdict(int)
        for (r, seen), c in st.items():
            for face in range(1, s + 1):
                new[((r + face) % k, seen or face == s)] += c
        st = new
    f1, f2 = Fraction(good, s ** n), Fraction(st[(0, True)], s ** n)
    add("dice_prob", q, f1.numerator + f1.denominator, f2.numerator + f2.denominator)


# ---------------------------------------------------------------- kinds that need an idea

def incl_excl_big():
    while True:
        a, b, c = R.sample(range(6, 31), 3)
        d = R.choice([x for x in range(4, 26) if x not in (a, b, c)])
        big = lcm(a, b, c, d)
        if big <= 600_000:
            break
    n = R.randrange(10 ** 11, 10 ** 12)
    q = (f"How many integers from 1 to {n} inclusive are divisible by at least one of {a}, {b} and {c}, "
         f"but are not divisible by {d}?")

    def at_least(extra):
        t = 0
        for r in (1, 2, 3):
            for s in itertools.combinations((a, b, c), r):
                t += (-1) ** (r + 1) * (n // lcm(*s, *extra))
        return t

    def ok(x):
        return (x % a == 0 or x % b == 0 or x % c == 0) and x % d != 0
    per = sum(1 for x in range(1, big + 1) if ok(x))
    add("incl_excl_big", q, at_least(()) - at_least((d,)),
        (n // big) * per + sum(1 for x in range(1, n % big + 1) if ok(x)))


def digit_dp(n, s, m):
    digits = [int(ch) for ch in str(n)]
    nd = len(digits)

    @lru_cache(None)
    def go(pos, sm, md, tight):
        if sm > s:
            return 0
        if pos == nd:
            return 1 if sm == s and md == 0 else 0
        hi = digits[pos] if tight else 9
        return sum(go(pos + 1, sm + dg, (md * 10 + dg) % m, tight and dg == hi) for dg in range(hi + 1))
    return go(0, 0, 0, True)


def digit_table(n, s, m):
    digits = [int(ch) for ch in str(n)]
    nd = len(digits)
    free = [defaultdict(int) for _ in range(nd + 1)]  # free[len][(sum, value mod m)] over all digit strings
    free[0][(0, 0)] = 1
    for ln in range(nd):
        for (sm, md), c in free[ln].items():
            for dg in range(10):
                free[ln + 1][(sm + dg, (md * 10 + dg) % m)] += c
    count, psum, pmod = 0, 0, 0
    for pos, dn in enumerate(digits):
        rem = nd - pos - 1
        for dg in range(dn):
            need_mod = (-((pmod * 10 + dg) % m) * pow(10, rem, m)) % m
            count += free[rem].get((s - psum - dg, need_mod), 0)
        psum, pmod = psum + dn, (pmod * 10 + dn) % m
    return count + (1 if psum == s and pmod == 0 else 0)


def digit_dp_big():
    n = R.randrange(10 ** 13, 10 ** 15)
    m = R.choice([7, 11, 13])
    s = R.randrange(40, 9 * len(str(n)) - 30)
    q = (f"How many integers from 1 to {n} inclusive are divisible by {m} and have digits that add up to "
         f"exactly {s}?")
    add("digit_dp_big", q, digit_dp(n, s, m), digit_table(n, s, m))


def power_sum_period(n, k, m):
    per = [pow(x, k, m) for x in range(m)]
    return ((n // m) * sum(per) + sum(per[1:n % m + 1])) % m


def power_sum_exact(n, k):
    s = [Fraction(n)]  # s[j] = 1^j + ... + n^j, from (n+1)^(j+1) - 1 = sum_{i<=j} C(j+1, i) s[i]
    for j in range(1, k + 1):
        s.append((Fraction((n + 1) ** (j + 1) - 1) - sum(comb(j + 1, i) * s[i] for i in range(j))) / (j + 1))
    assert s[k].denominator == 1
    return s[k].numerator


def power_sum_mod():
    n, k, m = R.randrange(10 ** 11, 10 ** 12), R.randrange(3, 8), R.randrange(1000, 10000)
    q = (f"What is the remainder when the sum 1^{k} + 2^{k} + 3^{k} + ... + {n}^{k} is divided by {m}? "
         f"(The sum has {n} terms: every integer from 1 to {n}, each raised to the power {k}.)")
    add("power_sum_mod", q, power_sum_period(n, k, m), power_sum_exact(n, k) % m)


def count2(a, b, m):
    """Non-negative solutions of a*x + b*y = m."""
    if m < 0:
        return 0
    g = gcd(a, b)
    if m % g:
        return 0
    a, b, m = a // g, b // g, m // g
    x0 = (m * pow(a, -1, b)) % b if b > 1 else 0
    return 0 if a * x0 > m else (m - a * x0) // (a * b) + 1


def dioph_series(a, b, c, n):
    """Group z by its remainder mod a*b: inside a group the count falls by a fixed step, so sum the series."""
    t_mod, g = a * b, gcd(a, b)
    step = c * g
    total = 0
    for r in range(t_mod):
        if c * r > n:
            break
        tmax = (n - c * r) // (c * t_mod)
        c0 = count2(a, b, n - c * r)
        if c0 <= 0:
            continue
        terms = min(tmax, (c0 - 1) // step) + 1
        total += terms * c0 - step * terms * (terms - 1) // 2
    return total


def dioph_quasi(a, b, c, n):
    """The count is a quadratic in t along n = n0 + t*L (L = lcm). Fit it from a small table, check a 4th point."""
    big = lcm(a, b, c)
    n0 = n % big
    w = [1] + [0] * (n0 + 3 * big)
    for coin in (a, b, c):
        for v in range(coin, len(w)):
            w[v] += w[v - coin]
    v0, v1, v2, v3 = (w[n0 + i * big] for i in range(4))

    def f(t):
        return v0 + (v1 - v0) * t + (v2 - 2 * v1 + v0) * t * (t - 1) // 2
    assert f(3) == v3
    return f((n - n0) // big)


def dioph_count():
    while True:
        a, b, c = sorted(R.sample(range(3, 20), 3))
        if gcd(a, b, c) == 1 and a * b * c >= 200:
            break
    n = R.randrange(10 ** 8, 10 ** 9)
    q = (f"How many triples (x, y, z) of non-negative integers satisfy the equation "
         f"{a}x + {b}y + {c}z = {n}?")
    add("dioph_count", q, dioph_series(a, b, c, n), dioph_quasi(a, b, c, n))


def rec_matrix(a1, a2, p, q, r, m, n):
    def mul(x, y):
        return [[sum(x[i][k] * y[k][j] for k in range(3)) % m for j in range(3)] for i in range(3)]
    res, base, e = [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [[p, q, r], [1, 0, 0], [0, 0, 1]], n - 2
    while e:
        if e & 1:
            res = mul(res, base)
        base, e = mul(base, base), e >> 1
    return (res[0][0] * a2 + res[0][1] * a1 + res[0][2]) % m


def rec_cycle(a1, a2, p, q, r, m, n):
    seq, seen = [a1 % m, a2 % m], {}
    while True:
        state = (seq[-2], seq[-1])
        i = len(seq) - 1  # 0-based index of the last term
        if state in seen:
            j = seen[state]
            period = i - j
            return seq[j + (n - 1 - j) % period] if n - 1 > j else seq[n - 1]
        seen[state] = i
        seq.append((p * seq[-1] + q * seq[-2] + r) % m)


def recurrence_big():
    a1, a2, p, q, r = R.randrange(1, 10), R.randrange(1, 10), R.randrange(2, 10), R.randrange(2, 10), R.randrange(1, 10)
    m, n = R.randrange(100, 1000), R.randrange(10 ** 12, 10 ** 15)
    qn = (f"A sequence is defined by a(1) = {a1}, a(2) = {a2}, and a(n) = {p}*a(n-1) + {q}*a(n-2) + {r} for every "
          f"n >= 3. What is the remainder when a({n}) is divided by {m}?")
    add("recurrence_big", qn, rec_matrix(a1, a2, p, q, r, m, n), rec_cycle(a1, a2, p, q, r, m, n))


def seating_forbidden():
    n = R.randrange(11, 14)
    refuse = [sorted(R.sample(range(1, n + 1), R.choice([2, 3]))) for _ in range(n)]
    parts = "; ".join(f"person {i + 1} refuses chairs {', '.join(map(str, f[:-1]))} and {f[-1]}"
                      for i, f in enumerate(refuse))
    q = (f"{n} people, numbered 1 to {n}, must sit in a row of {n} chairs numbered 1 to {n}, one person per chair. "
         f"Some chairs are refused: {parts}. In how many ways can all {n} people be seated so that nobody sits in "
         f"a chair they refuse?")
    allowed = [sum(1 << ch for ch in range(n) if ch + 1 not in f) for f in refuse]
    dp = [0] * (1 << n)
    dp[0] = 1
    for mask in range(1 << n):
        if dp[mask]:
            free = allowed[bin(mask).count("1")] & ~mask if mask != (1 << n) - 1 else 0
            while free:
                bit = free & -free
                dp[mask | bit] += dp[mask]
                free ^= bit
    ryser = 0
    for s in range(1, 1 << n):
        prod = 1
        for row in allowed:
            prod *= bin(row & s).count("1")
            if not prod:
                break
        ryser += (-1) ** (n - bin(s).count("1")) * prod
    add("seating_forbidden", q, dp[-1], ryser)


def tilings_profile(rows, cols, removed):
    dp = {0: 1}  # bit j of the mask: is cell (current + j) already covered
    for r in range(rows):
        for c in range(cols):
            new = defaultdict(int)
            for mask, w in dp.items():
                cur, rest = mask & 1, mask >> 1
                if (r, c) in removed:
                    if not cur:
                        new[rest] += w
                elif cur:
                    new[rest] += w
                else:
                    if c + 1 < cols and (r, c + 1) not in removed and not rest & 1:
                        new[rest | 1] += w
                    if r + 1 < rows and (r + 1, c) not in removed:
                        new[rest | (1 << (cols - 1))] += w
            dp = new
    return dp.get(0, 0)


def tilings_backtrack(rows, cols, removed):
    used = [[(r, c) in removed for c in range(cols)] for r in range(rows)]

    def go(pos):
        while pos < rows * cols and used[pos // cols][pos % cols]:
            pos += 1
        if pos == rows * cols:
            return 1
        r, c = divmod(pos, cols)
        total = 0
        used[r][c] = True
        if c + 1 < cols and not used[r][c + 1]:
            used[r][c + 1] = True
            total += go(pos + 1)
            used[r][c + 1] = False
        if r + 1 < rows and not used[r + 1][c]:
            used[r + 1][c] = True
            total += go(pos + 1)
            used[r + 1][c] = False
        used[r][c] = False
        return total
    return go(0)


def tilings_blocked():
    rows, cols = R.choice([(4, 7), (4, 8), (4, 9), (4, 10), (5, 6), (5, 7), (5, 8), (6, 6), (6, 7), (6, 8)])
    k = R.choice([2, 4]) if rows * cols % 2 == 0 else R.choice([1, 3])
    cells = [(r, c) for r in range(rows) for c in range(cols)]
    removed = set(R.sample(cells, k))
    left = [x for x in cells if x not in removed]
    if sum((r + c) % 2 for r, c in left) * 2 != len(left):
        return
    shown = ", ".join(f"({r + 1}, {c + 1})" for r, c in sorted(removed))
    q = (f"A rectangular board has {rows} rows and {cols} columns of unit squares. The square{'s' if k > 1 else ''} at "
         f"(row, column) position{'s' if k > 1 else ''} {shown} {'have' if k > 1 else 'has'} been removed. In how many "
         f"ways can all the remaining squares be covered with 1x2 dominoes? Each domino covers two squares that share "
         f"a side, dominoes may not overlap or cover a removed square, and two coverings that differ only by a "
         f"rotation or reflection of the board count as different.")
    n = tilings_profile(rows, cols, removed)
    if n >= 100:
        add("tilings_blocked", q, n, tilings_backtrack(rows, cols, removed))


GENS = [lattice_blocked, coin_big, dice_prob, incl_excl_big, digit_dp_big, power_sum_mod, dioph_count,
        recurrence_big, seating_forbidden, tilings_blocked]


def selftest():
    """Both methods of the 'clever' kinds against a plain loop on small inputs."""
    rr = random.Random(7)
    for _ in range(200):
        n, m = rr.randrange(1, 5000), rr.choice([7, 11, 13])
        s = rr.randrange(1, 30)
        brute = sum(1 for x in range(1, n + 1) if x % m == 0 and sum(map(int, str(x))) == s)
        assert digit_dp(n, s, m) == digit_table(n, s, m) == brute, (n, s, m)
        n, k, m = rr.randrange(1, 3000), rr.randrange(1, 8), rr.randrange(2, 500)
        brute = sum(x ** k for x in range(1, n + 1))
        assert power_sum_exact(n, k) == brute and power_sum_period(n, k, m) == brute % m, (n, k, m)
        a, b, c = rr.sample(range(2, 20), 3)
        n = rr.randrange(0, 3000)
        brute = sum(count2(a, b, n - c * z) for z in range(n // c + 1))
        slow = sum(1 for x in range(n // a + 1) for y in range((n - a * x) // b + 1) if (n - a * x - b * y) % c == 0)
        assert dioph_series(a, b, c, n) == brute == slow == dioph_quasi(a, b, c, n), (a, b, c, n)
        a1, a2, p, q, r = (rr.randrange(1, 10) for _ in range(5))
        m, n = rr.randrange(2, 60), rr.randrange(3, 400)
        seq = [a1, a2]
        while len(seq) < n:
            seq.append(p * seq[-1] + q * seq[-2] + r)
        assert rec_matrix(a1, a2, p, q, r, m, n) == rec_cycle(a1, a2, p, q, r, m, n) == seq[n - 1] % m, (m, n)
    print("selftest ok")


def build(seed, per_kind, path, avoid=()):
    global items
    items = []
    R.seed(seed)
    for g in GENS:
        kind = g.__name__
        while sum(1 for i in items if i["kind"] == kind) < per_kind:
            before = len(items)
            g()
            if len(items) > before and items[-1]["question"] in avoid:
                items.pop()
    json.dump(items, open(path, "w", encoding="utf-8"), indent=1)
    print(f"wrote {path}: {len(items)} problems")
    for kind in dict.fromkeys(i["kind"] for i in items):
        ex = next(i for i in items if i["kind"] == kind)
        print(f"  [{kind}] {ex['question'][:150]}  -> {ex['answer']}")
    return {i["question"] for i in items}


if __name__ == "__main__":
    selftest()
    seen = build(20261110, 4, os.path.join(HERE, "math_hard_practice.json"))
    build(20261111, 8, os.path.join(HERE, "math_hard_locked.json"), avoid=seen)
