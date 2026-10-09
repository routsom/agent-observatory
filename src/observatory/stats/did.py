"""Upgrade difference-in-differences (SPEC.md §5b).

Estimates a CLI upgrade's effect while subtracting secular drift: the mean paired change among
clients who upgraded A->B, minus the mean same-period change among clients who stayed on A. The CI
bootstraps over clients (treated and control resampled independently). With no usable control arm
it falls back to the paired within-upgrader difference and says so in ``method``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean

from observatory.stats.aggregate import percentile

# Paired measurements per client: (before, after) for treated; (early, late) for control.
Paired = dict[str, tuple[float, float]]


@dataclass(frozen=True)
class DidResult:
    estimate: float | None
    ci_low: float | None
    ci_high: float | None
    method: str  # "did" | "paired_first_difference" | "none"
    n_treated: int
    n_control: int


def _deltas(paired: Paired) -> list[float]:
    return [after - before for before, after in paired.values()]


def upgrade_did(
    treated: Paired,
    control: Paired,
    *,
    n_resamples: int = 2000,
    seed: int = 0,
) -> DidResult:
    """Difference-in-differences of a metric across an upgrade, bootstrapped over clients."""
    treated_deltas = _deltas(treated)
    control_deltas = _deltas(control)
    rng = random.Random(seed)

    if not treated_deltas:
        return DidResult(None, None, None, "none", 0, len(control_deltas))

    if not control_deltas:
        # Fallback: paired within-upgrader first difference (no secular-trend control).
        estimate = mean(treated_deltas)
        samples = sorted(
            mean([rng.choice(treated_deltas) for _ in treated_deltas]) for _ in range(n_resamples)
        )
        return DidResult(
            estimate,
            percentile(samples, 0.025),
            percentile(samples, 0.975),
            "paired_first_difference",
            len(treated_deltas),
            0,
        )

    estimate = mean(treated_deltas) - mean(control_deltas)
    did_samples: list[float] = []
    for _ in range(n_resamples):
        t = mean([rng.choice(treated_deltas) for _ in treated_deltas])
        c = mean([rng.choice(control_deltas) for _ in control_deltas])
        did_samples.append(t - c)
    samples = sorted(did_samples)
    return DidResult(
        estimate,
        percentile(samples, 0.025),
        percentile(samples, 0.975),
        "did",
        len(treated_deltas),
        len(control_deltas),
    )
