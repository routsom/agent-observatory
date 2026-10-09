"""Aggregation and uncertainty (SPEC.md §5).

Two rules that the tests enforce:

* **Users are weighted equally.** An aggregate is the mean of per-user means, never the mean of
  sessions, so one heavy user cannot dominate.
* **The bootstrap resamples users, not sessions.** With more than one user this is a user
  bootstrap (``method="user_bootstrap"``). With a single local user (phase 1) it degenerates to a
  session bootstrap, labelled ``method="session_bootstrap"`` so the report never overstates its
  precision.

No bare numbers leave here: every result carries window, counts, a CI, and the method name
(invariant 6).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from observatory.metrics import MetricFn
from observatory.schema import Session

UserKey = Callable[[Session], str]


def _default_user_key(_: Session) -> str:
    return "local"


@dataclass(frozen=True)
class AggregateResult:
    metric: str
    value: float | None
    ci_low: float | None
    ci_high: float | None
    method: str
    window: str
    n_sessions: int
    n_tool_calls: int
    n_users: int


@dataclass(frozen=True)
class DiffResult:
    metric: str
    split: str
    baseline_label: str
    current_label: str
    baseline: float | None
    current: float | None
    delta: float | None
    ci_low: float | None
    ci_high: float | None
    method: str
    n_baseline: int
    n_current: int


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _user_means(
    values_by_user: dict[str, list[float]],
) -> list[float]:
    return [_mean(v) for v in values_by_user.values() if v]


def mean_of_group_means(values_by_group: dict[str, list[float]]) -> float | None:
    """Point estimate that weights groups (users) equally: mean of per-group means. None if empty.

    Shared by the local `aggregate()` and the server's nightly job so both weight users the same.
    """
    means = _user_means(values_by_group)
    if not means:
        return None
    return _mean(means)


def percentile(sorted_xs: list[float], q: float) -> float:
    """Linear-interpolation percentile of an already-sorted sequence, q in [0, 1]."""
    if len(sorted_xs) == 1:
        return sorted_xs[0]
    pos = q * (len(sorted_xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_xs) - 1)
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def bootstrap_over_groups(
    values_by_group: dict[str, list[float]],
    *,
    n_resamples: int,
    rng: random.Random,
) -> tuple[float | None, float | None, str]:
    """Percentile CI for the mean-of-group-means, resampling groups (users), not sessions.

    With more than one group this is a user bootstrap (``method="user_bootstrap"``). With a single
    group it degenerates to resampling that group's values and is labelled ``session_bootstrap`` so
    precision is never overstated. Shared by the local report and the server's nightly job.
    """
    groups = [g for g, v in values_by_group.items() if v]
    if not groups:
        return None, None, "none"

    if len(groups) > 1:
        method = "user_bootstrap"
        samples: list[float] = []
        for _ in range(n_resamples):
            picked = [rng.choice(groups) for _ in groups]
            means = [_mean(values_by_group[g]) for g in picked]
            samples.append(_mean(means))
    else:
        # Single group: resample its values instead; widen honestly by labelling it.
        method = "session_bootstrap"
        values = values_by_group[groups[0]]
        if len(values) < 2:
            return None, None, method
        samples = []
        for _ in range(n_resamples):
            picked_vals = [rng.choice(values) for _ in values]
            samples.append(_mean(picked_vals))

    samples.sort()
    return percentile(samples, 0.025), percentile(samples, 0.975), method


def aggregate(
    sessions: Sequence[Session],
    metric: str,
    metric_fn: MetricFn,
    *,
    window: str,
    user_key: UserKey = _default_user_key,
    n_resamples: int = 2000,
    seed: int = 0,
) -> AggregateResult:
    """Aggregate one metric over sessions with user-equal weighting and a bootstrap CI."""
    values_by_user: dict[str, list[float]] = {}
    n_tool_calls = 0
    for s in sessions:
        n_tool_calls += len(s.tool_calls())
        v = metric_fn(s)
        if v is not None:
            values_by_user.setdefault(user_key(s), []).append(v)

    value = mean_of_group_means(values_by_user)
    ci_low, ci_high, method = bootstrap_over_groups(
        values_by_user, n_resamples=n_resamples, rng=random.Random(seed)
    )
    n_users = len({user_key(s) for s in sessions}) if sessions else 0
    return AggregateResult(
        metric=metric,
        value=value,
        ci_low=ci_low,
        ci_high=ci_high,
        method=method if value is not None else "none",
        window=window,
        n_sessions=len(sessions),
        n_tool_calls=n_tool_calls,
        n_users=n_users,
    )


def within_user_diff(
    baseline: Sequence[Session],
    current: Sequence[Session],
    metric: str,
    metric_fn: MetricFn,
    *,
    split: str,
    baseline_label: str,
    current_label: str,
    user_key: UserKey = _default_user_key,
    n_resamples: int = 2000,
    seed: int = 0,
) -> DiffResult:
    """Bootstrap difference (current - baseline) of a metric across a split dimension.

    The local analogue of the server's difference-in-differences: for each bootstrap resample we
    recompute both point estimates and take their difference, yielding a CI on the change.
    """
    rng = random.Random(seed)

    def grouped(sessions: Sequence[Session]) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for s in sessions:
            v = metric_fn(s)
            if v is not None:
                out.setdefault(user_key(s), []).append(v)
        return out

    b_groups = grouped(baseline)
    c_groups = grouped(current)
    base_pt = mean_of_group_means(b_groups)
    curr_pt = mean_of_group_means(c_groups)
    delta = None if base_pt is None or curr_pt is None else curr_pt - base_pt

    ci_low = ci_high = None
    method = "none"
    b_users = [u for u, v in b_groups.items() if v]
    c_users = [u for u, v in c_groups.items() if v]
    if base_pt is not None and curr_pt is not None:
        multi = len(b_users) > 1 and len(c_users) > 1
        method = "user_bootstrap_diff" if multi else "session_bootstrap_diff"
        deltas: list[float] = []
        for _ in range(n_resamples):
            if multi:
                bp = _mean([_mean(b_groups[rng.choice(b_users)]) for _ in b_users])
                cp = _mean([_mean(c_groups[rng.choice(c_users)]) for _ in c_users])
            else:
                bvals = b_groups[b_users[0]]
                cvals = c_groups[c_users[0]]
                bp = _mean([rng.choice(bvals) for _ in bvals])
                cp = _mean([rng.choice(cvals) for _ in cvals])
            deltas.append(cp - bp)
        deltas.sort()
        ci_low, ci_high = percentile(deltas, 0.025), percentile(deltas, 0.975)

    return DiffResult(
        metric=metric,
        split=split,
        baseline_label=baseline_label,
        current_label=current_label,
        baseline=base_pt,
        current=curr_pt,
        delta=delta,
        ci_low=ci_low,
        ci_high=ci_high,
        method=method,
        n_baseline=len(baseline),
        n_current=len(current),
    )
