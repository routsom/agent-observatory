"""Statistical methods: user-equal aggregation, bootstrap CIs, within-user comparison.

Phase 1 ships the local pieces the report needs. Server-side change-point detection is phase 3.
"""

from observatory.stats.aggregate import (
    AggregateResult,
    DiffResult,
    aggregate,
    within_user_diff,
)

__all__ = ["AggregateResult", "DiffResult", "aggregate", "within_user_diff"]
