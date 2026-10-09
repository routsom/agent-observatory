"""Within-user index (SPEC.md §5a).

Users have very different baselines, so a raw cross-user mean mixes level differences with drift.
The index re-expresses each user's value as an additive deviation from that user's own mean; the
label-aware helper then compares groups (e.g. CLI versions) with those baselines removed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean

from observatory.stats.aggregate import bootstrap_over_groups, mean_of_group_means


def within_user_index(values_by_user: dict[str, list[float]]) -> dict[str, list[float]]:
    """Subtract each user's own mean from their values (additive within-user index).

    Users with the same shape but different levels collapse onto the same deviations.
    """
    out: dict[str, list[float]] = {}
    for user, values in values_by_user.items():
        if not values:
            continue
        m = mean(values)
        out[user] = [v - m for v in values]
    return out


@dataclass(frozen=True)
class IndexedLabel:
    label: str
    value: float | None  # mean within-user deviation for this label
    ci_low: float | None
    ci_high: float | None
    method: str
    n_users: int


def indexed_label_means(
    per_client_label_values: dict[str, dict[str, list[float]]],
    *,
    n_resamples: int = 2000,
    seed: int = 0,
) -> dict[str, IndexedLabel]:
    """Per-label mean *net of each client's cross-label baseline*, with a user bootstrap CI.

    ``per_client_label_values[client][label]`` holds that client's value(s) for a label. Each
    client's grand mean across all their labels is removed before the label means are taken, so
    between-client level differences cannot drive the comparison.
    """
    # Remove each client's grand mean across every value they contributed.
    deviations: dict[str, dict[str, list[float]]] = {}
    for client, by_label in per_client_label_values.items():
        flat = [v for values in by_label.values() for v in values]
        if not flat:
            continue
        g = mean(flat)
        deviations[client] = {
            label: [v - g for v in values] for label, values in by_label.items() if values
        }

    # Regroup by label -> {client: [deviations]} and aggregate each label over clients.
    labels = {label for by_label in deviations.values() for label in by_label}
    result: dict[str, IndexedLabel] = {}
    for label in sorted(labels):
        by_client = {
            client: by_label[label] for client, by_label in deviations.items() if label in by_label
        }
        value = mean_of_group_means(by_client)
        ci_low, ci_high, method = bootstrap_over_groups(
            by_client, n_resamples=n_resamples, rng=random.Random(seed)
        )
        result[label] = IndexedLabel(
            label=label,
            value=value,
            ci_low=ci_low,
            ci_high=ci_high,
            method=method if value is not None else "none",
            n_users=len(by_client),
        )
    return result
