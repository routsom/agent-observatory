"""Change-point detection (SPEC.md §5c, invariant 8).

Simulations: the false-alarm rate on a stationary series is near the nominal 5%, and an injected
level shift is detected with high power at roughly the right date.
"""

from __future__ import annotations

import random
import statistics

from observatory.stats import detect_change_point


def test_false_alarm_rate_on_stationary_series() -> None:
    flags = 0
    for t in range(300):
        rng = random.Random(2000 + t)
        series = [rng.gauss(0, 1) for _ in range(40)]
        if detect_change_point(series, n_permutations=200, seed=1).p_value < 0.05:
            flags += 1
    assert flags / 300 <= 0.10  # nominal 0.05, observed ~0.06


def test_detects_injected_shift_with_power_and_location() -> None:
    detected = 0
    indices = []
    for t in range(200):
        rng = random.Random(3000 + t)
        series = [rng.gauss(0.0, 1) for _ in range(20)] + [rng.gauss(2.0, 1) for _ in range(20)]
        cp = detect_change_point(series, n_permutations=200, seed=1)
        if cp.p_value < 0.05:
            detected += 1
            indices.append(cp.index)
    assert detected / 200 >= 0.9  # observed 1.0
    # True shift is between index 19 and 20; estimated split index should land right around there.
    assert 17 <= statistics.median(indices) <= 21


def test_pre_post_means_bracket_the_shift() -> None:
    series = [0.0] * 10 + [5.0] * 10
    cp = detect_change_point(series, n_permutations=200, seed=1)
    assert cp.index == 9  # last index of the "before" segment
    assert cp.pre_mean == 0.0 and cp.post_mean == 5.0
    assert cp.p_value < 0.05


def test_short_series_is_safe() -> None:
    cp = detect_change_point([3.0], n_permutations=50)
    assert cp.index == -1 and cp.p_value == 1.0 and cp.n_points == 1
