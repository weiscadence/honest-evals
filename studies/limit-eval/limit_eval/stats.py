from __future__ import annotations
import math


def wilson(k: int, n: int, z: float = 1.959964):
    """Wilson score 95% interval for k successes in n trials. n=0 -> (None, None)."""
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def fmt_rate(k: int, n: int) -> str:
    if n == 0:
        return "n/a (0/0)"
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.3f} [{lo:.3f}, {hi:.3f}]"
