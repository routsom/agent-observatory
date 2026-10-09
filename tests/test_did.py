"""Upgrade difference-in-differences (SPEC.md §5b, invariant 8).

Simulations with a known injected effect and secular trend: DiD recovers the effect and its CI
covers it; with no real effect the CI contains 0 near the nominal rate; the no-control fallback is
labelled honestly.
"""

from __future__ import annotations

import random

from observatory.stats import upgrade_did
from observatory.stats.did import Paired

TRUE_EFFECT = 0.3
SECULAR = 0.2


def _trial(t: int, effect: float, *, with_control: bool = True) -> tuple[Paired, Paired]:
    rng = random.Random(1000 + t)
    treated: Paired = {}
    control: Paired = {}
    for c in range(25):
        base = rng.gauss(0.5, 0.1)
        treated[f"t{c}"] = (
            base + rng.gauss(0, 0.05),
            base + SECULAR + effect + rng.gauss(0, 0.05),
        )
    if with_control:
        for c in range(25):
            base = rng.gauss(0.5, 0.1)
            control[f"k{c}"] = (base + rng.gauss(0, 0.05), base + SECULAR + rng.gauss(0, 0.05))
    return treated, control


def test_did_recovers_known_effect() -> None:
    treated, control = _trial(0, TRUE_EFFECT)
    r = upgrade_did(treated, control, n_resamples=500, seed=7)
    assert r.method == "did"
    assert r.estimate is not None and abs(r.estimate - TRUE_EFFECT) < 0.1
    # CI is a valid interval bracketing the point estimate (coverage of the *true* effect is
    # asserted over many trials in test_did_coverage_of_true_effect, not from a single draw).
    assert r.ci_low is not None and r.ci_low <= r.estimate <= r.ci_high  # type: ignore[operator]
    assert r.n_treated == 25 and r.n_control == 25


def test_did_coverage_of_true_effect() -> None:
    hits = 0
    for t in range(300):
        treated, control = _trial(t, TRUE_EFFECT)
        r = upgrade_did(treated, control, n_resamples=300, seed=7)
        assert r.ci_low is not None and r.ci_high is not None
        if r.ci_low <= TRUE_EFFECT <= r.ci_high:
            hits += 1
    assert 0.88 <= hits / 300 <= 0.99  # observed ~0.92


def test_did_false_alarm_when_no_effect() -> None:
    false_alarms = 0
    for t in range(300):
        treated, control = _trial(t, 0.0)
        r = upgrade_did(treated, control, n_resamples=300, seed=7)
        assert r.ci_low is not None and r.ci_high is not None
        if not (r.ci_low <= 0 <= r.ci_high):
            false_alarms += 1
    assert false_alarms / 300 <= 0.12  # observed ~0.08


def test_did_fallback_without_control() -> None:
    treated, _ = _trial(0, TRUE_EFFECT, with_control=False)
    r = upgrade_did(treated, {}, n_resamples=300, seed=7)
    assert r.method == "paired_first_difference"
    assert r.n_control == 0
    # Without a control arm the estimate still contains the secular trend (effect + SECULAR).
    assert r.estimate is not None and r.estimate > TRUE_EFFECT
    assert r.ci_low is not None and r.ci_low > 0  # a real change is detected


def test_did_empty_treated_is_none() -> None:
    r = upgrade_did({}, {}, n_resamples=10)
    assert r.method == "none" and r.estimate is None
