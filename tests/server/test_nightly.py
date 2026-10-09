"""Nightly aggregation: user-equal mean, k-anonymity suppression, dashboard rendering."""

from __future__ import annotations

import math
import uuid
from datetime import date
from pathlib import Path

from observatory.schema import Agent
from observatory.share.payload import MetricAggregate, SharePayload
from observatory_server import MIN_USERS
from observatory_server.dashboard import render_dashboard
from observatory_server.nightly import run_aggregation
from observatory_server.store import ServerStore


def _submit(store: ServerStore, cli_version: str, value: float) -> None:
    store.ingest(
        SharePayload(
            client_id=str(uuid.uuid4()),
            submission_id=str(uuid.uuid4()),
            generated_on=date(2026, 1, 1),
            agent=Agent.claude_code,
            window="30d",
            aggregates=[
                MetricAggregate(
                    cli_version=cli_version,
                    model_id="claude-opus-4-8",
                    metric="read_edit_ratio",
                    value=value,
                    ci_low=None,
                    ci_high=None,
                    method="session_bootstrap",  # type: ignore[arg-type]
                    n_sessions=1,
                    n_tool_calls=10,
                    n_users=1,
                )
            ],
        )
    )


def test_user_equal_mean_and_k_anonymity(tmp_path: Path) -> None:
    with ServerStore(tmp_path / "srv.duckdb") as store:
        # Published cell: MIN_USERS distinct clients on cli_version 2.0.0.
        values = [0.1 * (i + 1) for i in range(MIN_USERS)]  # 0.1..0.5 for MIN_USERS=5
        for v in values:
            _submit(store, "2.0.0", v)
        # Suppressed cell: only 2 clients on cli_version 1.0.0 (< MIN_USERS).
        _submit(store, "1.0.0", 0.9)
        _submit(store, "1.0.0", 0.8)

        published = run_aggregation(store, n_resamples=200, seed=0)

    cells = {(c.cli_version, c.metric): c for c in published}
    assert ("1.0.0", "read_edit_ratio") not in cells  # suppressed
    cell = cells[("2.0.0", "read_edit_ratio")]
    assert cell.n_users == MIN_USERS
    assert cell.value is not None and math.isclose(cell.value, sum(values) / len(values))
    assert cell.ci_low is not None and cell.ci_high is not None
    assert cell.method == "user_bootstrap"  # many clients -> user bootstrap


def test_dashboard_renders_only_published_cells(tmp_path: Path) -> None:
    with ServerStore(tmp_path / "srv.duckdb") as store:
        for v in [0.2, 0.3, 0.4, 0.5, 0.6]:
            _submit(store, "2.0.0", v)
        _submit(store, "1.0.0", 0.99)  # single user -> must not appear
        published = run_aggregation(store, n_resamples=100, seed=0)
        html = render_dashboard(store.published())

    assert "read_edit_ratio" in html
    assert "2.0.0" in html
    assert "1.0.0" not in html  # suppressed cell never reaches the dashboard
    assert len(published) == 1


def test_empty_dashboard_is_safe() -> None:
    html = render_dashboard([])
    assert "No aggregates" in html
