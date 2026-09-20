"""Pure scoring math. No network."""

from __future__ import annotations

import math


def softmax(logprobs: list[float]) -> list[float]:
    if not logprobs:
        raise ValueError("softmax requires at least one logprob")
    peak = max(logprobs)
    shifted = [math.exp(x - peak) for x in logprobs]
    total = sum(shifted)
    if total <= 0.0 or not math.isfinite(total):
        raise ValueError("softmax total is not finite")
    return [x / total for x in shifted]


def entropy_confidence(probs: list[float]) -> float:
    """1 - H/Hmax on a complete distribution. Uniform → 0, one-hot → 1."""
    n = len(probs)
    if n < 2:
        return 0.0
    h = 0.0
    for p in probs:
        if p < 0:
            raise ValueError("negative probability")
        if p > 0:
            h -= p * math.log(p)
    hmax = math.log(n)
    if hmax == 0.0:
        return 0.0
    conf = 1.0 - (h / hmax)
    return max(0.0, min(1.0, conf))


def mass_from_logprobs(logprobs: list[float]) -> float:
    """Sum of exp(lp) for full-vocab log-softmax entries (not renormalized)."""
    total = 0.0
    for lp in logprobs:
        total += math.exp(lp)
    return total
