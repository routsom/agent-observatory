"""Nightly cross-user aggregation.

For each (agent, cli_version, metric, window) cell it weights clients equally and bootstraps over
clients for the CI - reusing `observatory.stats.bootstrap_over_groups` so the server and the local
report compute intervals identically. Cells with fewer than `MIN_USERS` distinct clients are
suppressed entirely (k-anonymity).
"""

from __future__ import annotations

import random

from observatory.stats import bootstrap_over_groups, mean_of_group_means
from observatory_server import MIN_USERS
from observatory_server.store import PublishedCell, ServerStore


def run_aggregation(
    store: ServerStore, *, n_resamples: int = 2000, seed: int = 0
) -> list[PublishedCell]:
    """Recompute and persist the published aggregates; returns the k-anonymous cells."""
    published: list[PublishedCell] = []
    for agent, cli_version, metric, window in store.cells():
        values_by_client = store.values_by_client(agent, cli_version, metric, window)
        n_users = len(values_by_client)
        if n_users < MIN_USERS:
            continue  # suppressed: below the k-anonymity threshold
        value = mean_of_group_means(values_by_client)
        ci_low, ci_high, method = bootstrap_over_groups(
            values_by_client, n_resamples=n_resamples, rng=random.Random(seed)
        )
        published.append(
            PublishedCell(
                agent=agent,
                cli_version=cli_version,
                metric=metric,
                window=window,
                value=value,
                ci_low=ci_low,
                ci_high=ci_high,
                method=method if value is not None else "none",
                n_users=n_users,
            )
        )
    store.replace_published(published)
    return published
