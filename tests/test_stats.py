"""Statistical-method simulations (invariant 8).

Each method is exercised on data with a known answer:

* the user bootstrap CI *covers* the true mean close to 95% of the time;
* the within-user difference raises a *false alarm* close to 5% of the time when there is no real
  change, and *detects* a real injected shift.

The simulations are fully seeded, so these are exact, non-flaky numbers rather than random draws.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from observatory.schema import Agent, Session
from observatory.stats import aggregate, within_user_diff

UserKey = Callable[[Session], str]
MetricFn = Callable[[Session], float | None]

TRUE_MEAN = 0.5


def _split_user(s: Session) -> str:
    """User id is the part of a synthetic session id before the colon."""
    return s.session_id.split(":")[0]


def _lookup(mapping: dict[str, float]) -> MetricFn:
    """A metric_fn that reads a precomputed value by session id (bound, not a loop closure)."""

    def fn(s: Session) -> float | None:
        return mapping[s.session_id]

    return fn


def _sessions(values: dict[str, float]) -> tuple[list[Session], MetricFn]:
    sessions = [Session(session_id=sid, agent=Agent.claude_code) for sid in values]
    return sessions, _lookup(values)


def _draw(
    rng: random.Random, tag: str, users: int, per_user: int, shift: float = 0.0
) -> dict[str, float]:
    values: dict[str, float] = {}
    for u in range(users):
        user_mean = rng.gauss(TRUE_MEAN, 0.10)
        for i in range(per_user):
            values[f"{tag}{u}:{i}"] = user_mean + shift + rng.gauss(0, 0.05)
    return values


def test_user_bootstrap_ci_coverage() -> None:
    trials, users, per_user = 300, 30, 4
    hits = 0
    for t in range(trials):
        rng = random.Random(1000 + t)
        sessions, fn = _sessions(_draw(rng, "u", users, per_user))
        r = aggregate(
            sessions, "m", fn, window="all", user_key=_split_user, n_resamples=250, seed=123
        )
        assert r.method == "user_bootstrap"
        assert r.ci_low is not None and r.ci_high is not None
        if r.ci_low <= TRUE_MEAN <= r.ci_high:
            hits += 1
    coverage = hits / trials
    # Percentile bootstrap on 30 users slightly undercovers; nominal 0.95, observed ~0.91.
    assert 0.88 <= coverage <= 0.99, coverage


def test_within_user_diff_false_alarm_rate() -> None:
    trials, users, per_user = 300, 30, 4
    false_alarms = 0
    for t in range(trials):
        rng = random.Random(2000 + t)
        base = _draw(rng, "b", users, per_user)
        curr = _draw(rng, "c", users, per_user)  # same distribution, no real change
        fn = _lookup({**base, **curr})
        sb = [Session(session_id=s, agent=Agent.claude_code) for s in base]
        sc = [Session(session_id=s, agent=Agent.claude_code) for s in curr]
        d = within_user_diff(
            sb,
            sc,
            "m",
            fn,
            split="cli_version",
            baseline_label="x",
            current_label="y",
            user_key=_split_user,
            n_resamples=250,
            seed=7,
        )
        assert d.method == "user_bootstrap_diff"
        assert d.ci_low is not None and d.ci_high is not None
        if not (d.ci_low <= 0 <= d.ci_high):
            false_alarms += 1
    rate = false_alarms / trials
    assert rate <= 0.12, rate  # nominal 0.05, observed ~0.07


def test_within_user_diff_detects_real_shift() -> None:
    rng = random.Random(42)
    users, per_user = 30, 4
    base = _draw(rng, "b", users, per_user)
    curr = _draw(rng, "c", users, per_user, shift=0.2)  # a real +0.2 change
    fn = _lookup({**base, **curr})
    sb = [Session(session_id=s, agent=Agent.claude_code) for s in base]
    sc = [Session(session_id=s, agent=Agent.claude_code) for s in curr]
    d = within_user_diff(
        sb,
        sc,
        "m",
        fn,
        split="cli_version",
        baseline_label="x",
        current_label="y",
        user_key=_split_user,
        n_resamples=250,
        seed=7,
    )
    assert d.delta is not None and abs(d.delta - 0.2) < 0.05
    assert d.ci_low is not None and d.ci_low > 0  # CI excludes zero: shift detected


def test_single_user_falls_back_to_session_bootstrap() -> None:
    values = {f"local:{i}": 0.4 + 0.01 * i for i in range(8)}
    sessions, fn = _sessions(values)
    # default user_key maps everything to "local" -> one user
    r = aggregate(sessions, "m", fn, window="30d", n_resamples=200, seed=1)
    assert r.method == "session_bootstrap"
    assert r.n_users == 1
    assert r.ci_low is not None and r.ci_high is not None
