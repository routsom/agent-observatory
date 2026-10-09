"""Statistical methods: user-equal aggregation, bootstrap CIs, within-user comparison.

Phase 1 ships the local pieces the report needs. Server-side change-point detection is phase 3.
"""

from observatory.stats.aggregate import (
    AggregateResult,
    DiffResult,
    aggregate,
    bootstrap_over_groups,
    mean_of_group_means,
    percentile,
    within_user_diff,
)
from observatory.stats.changepoint import ChangePoint, detect_change_point
from observatory.stats.did import DidResult, Paired, upgrade_did
from observatory.stats.index import IndexedLabel, indexed_label_means, within_user_index

__all__ = [
    "AggregateResult",
    "ChangePoint",
    "DidResult",
    "DiffResult",
    "IndexedLabel",
    "Paired",
    "aggregate",
    "bootstrap_over_groups",
    "detect_change_point",
    "indexed_label_means",
    "mean_of_group_means",
    "percentile",
    "upgrade_did",
    "within_user_diff",
    "within_user_index",
]
