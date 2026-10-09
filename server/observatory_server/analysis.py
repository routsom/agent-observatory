"""Phase-3 server analysis: upgrade DiD (SPEC.md §5b) and change-point detection (§5c).

Assembles inputs from `submission_history`, applies the same `MIN_USERS` k-anonymity threshold as
the dashboard, and delegates the statistics to `observatory.stats` so the math lives in one place.
Results are computed on demand (small, low-traffic surface) rather than persisted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from observatory.stats import detect_change_point, upgrade_did
from observatory_server import MIN_USERS
from observatory_server.store import ServerStore


@dataclass(frozen=True)
class DidRow:
    agent: str
    metric: str
    window: str
    baseline: str  # cli_version A
    current: str  # cli_version B
    estimate: float | None
    ci_low: float | None
    ci_high: float | None
    method: str
    n_treated: int
    n_control: int


@dataclass(frozen=True)
class ChangePointRow:
    agent: str
    cli_version: str
    metric: str
    window: str
    change_date: str | None
    pre_mean: float | None
    post_mean: float | None
    p_value: float
    n_points: int


def run_upgrade_did(
    store: ServerStore,
    *,
    n_resamples: int = 2000,
    seed: int = 0,
    min_users: int = MIN_USERS,
) -> list[DidRow]:
    """DiD for each (agent, metric, window) across its two earliest-seen CLI versions."""
    rows: list[DidRow] = []
    for agent, metric, window in store.metric_keys():
        versions = store.versions_by_first_seen(agent, metric, window)
        if len(versions) < 2:
            continue
        a, b = versions[0], versions[1]
        latest_a = store.latest_value_by_client(agent, a, metric, window)
        latest_b = store.latest_value_by_client(agent, b, metric, window)
        treated = {c: (latest_a[c], latest_b[c]) for c in latest_a.keys() & latest_b.keys()}
        if len(treated) < min_users:  # k-anonymity on the treated (upgrader) group
            continue
        # Control = stayers: >= 2 dated A values and never upgraded to B. Keep only if itself
        # k-anonymous, else fall back to the paired first difference (empty control).
        control = {
            c: v
            for c, v in store.endpoints_by_client(agent, a, metric, window).items()
            if c not in latest_b
        }
        if len(control) < min_users:
            control = {}
        res = upgrade_did(treated, control, n_resamples=n_resamples, seed=seed)
        rows.append(
            DidRow(
                agent=agent,
                metric=metric,
                window=window,
                baseline=a,
                current=b,
                estimate=res.estimate,
                ci_low=res.ci_low,
                ci_high=res.ci_high,
                method=res.method,
                n_treated=res.n_treated,
                n_control=res.n_control,
            )
        )
    return rows


def run_change_points(
    store: ServerStore,
    *,
    n_permutations: int = 1000,
    seed: int = 0,
    min_users: int = MIN_USERS,
    min_points: int = 6,
) -> list[ChangePointRow]:
    """Change-point per (agent, cli_version, metric, window) series; k-anonymous dates only."""
    rows: list[ChangePointRow] = []
    for agent, metric, window in store.metric_keys():
        for version in store.versions_by_first_seen(agent, metric, window):
            series = store.date_series(agent, version, metric, window, min_users=min_users)
            if len(series) < min_points:
                continue
            dates = [d for d, _ in series]
            values = [v for _, v in series]
            cp = detect_change_point(values, n_permutations=n_permutations, seed=seed)
            if cp.index < 0:
                continue
            rows.append(
                ChangePointRow(
                    agent=agent,
                    cli_version=version,
                    metric=metric,
                    window=window,
                    change_date=dates[cp.index] if 0 <= cp.index < len(dates) else None,
                    pre_mean=cp.pre_mean,
                    post_mean=cp.post_mean,
                    p_value=cp.p_value,
                    n_points=cp.n_points,
                )
            )
    return rows


def as_dicts(rows: list[DidRow] | list[ChangePointRow]) -> list[dict[str, object]]:
    return [asdict(r) for r in rows]
