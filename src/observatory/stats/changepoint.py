"""Single change-point detection (SPEC.md §5c).

Locates one level shift in a date-ordered series with a CUSUM statistic (max absolute cumulative
deviation from the series mean) and assesses it with a permutation test: the series is shuffled
many times and the p-value is the fraction of shuffles whose statistic meets or exceeds the
observed one. Assumption-light and directly testable for false-alarm rate and power.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True)
class ChangePoint:
    index: int  # last index of the "before" segment; -1 if undefined
    pre_mean: float | None
    post_mean: float | None
    statistic: float
    p_value: float
    n_points: int


def _cusum_stat(series: Sequence[float]) -> tuple[int, float]:
    """Return (best split index, max |cumulative deviation|). Split is after the index."""
    m = mean(series)
    cumulative = 0.0
    best_idx = 0
    best_stat = -1.0
    for i in range(len(series) - 1):  # valid splits keep both segments non-empty
        cumulative += series[i] - m
        if abs(cumulative) > best_stat:
            best_stat = abs(cumulative)
            best_idx = i
    return best_idx, max(best_stat, 0.0)


def detect_change_point(
    series: Sequence[float],
    *,
    n_permutations: int = 1000,
    seed: int = 0,
) -> ChangePoint:
    """Detect at most one level shift in ``series`` and give its permutation-test p-value."""
    n = len(series)
    if n < 2:
        return ChangePoint(-1, mean(series) if series else None, None, 0.0, 1.0, n)

    idx, stat = _cusum_stat(series)
    rng = random.Random(seed)
    shuffled = list(series)
    at_least = 0
    for _ in range(n_permutations):
        rng.shuffle(shuffled)
        _, perm_stat = _cusum_stat(shuffled)
        if perm_stat >= stat:
            at_least += 1
    p_value = (at_least + 1) / (n_permutations + 1)

    return ChangePoint(
        index=idx,
        pre_mean=mean(series[: idx + 1]),
        post_mean=mean(series[idx + 1 :]),
        statistic=stat,
        p_value=p_value,
        n_points=n,
    )
