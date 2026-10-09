"""Phase-3 server analysis over submission_history: DiD + change-point, k-anonymity, dashboard."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from observatory.schema import Agent
from observatory.share.payload import MetricAggregate, SharePayload
from observatory_server import MIN_USERS
from observatory_server.analysis import run_change_points, run_upgrade_did
from observatory_server.app import create_app
from observatory_server.dashboard import render_dashboard
from observatory_server.store import ServerStore

METRIC = "read_edit_ratio"
WINDOW = "30d"


def _cid(name: str) -> str:
    """Stable UUID for a logical client name (payload requires a UUID-shaped client_id)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


def _submit(store: ServerStore, client_id: str, cli_version: str, value: float, on: date) -> None:
    store.ingest(
        SharePayload(
            client_id=_cid(client_id),
            submission_id=str(uuid.uuid4()),
            generated_on=on,
            agent=Agent.claude_code,
            window=WINDOW,
            aggregates=[
                MetricAggregate(
                    cli_version=cli_version,
                    model_id="claude-opus-4-8",
                    metric=METRIC,
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


def test_upgrade_did_recovers_effect_with_k_anonymity(tmp_path: Path) -> None:
    early, late = date(2026, 1, 1), date(2026, 2, 1)
    with ServerStore(tmp_path / "srv.duckdb") as store:
        # Upgraders (treated): value rises by ~0.3 from 1.0.0 to 2.0.0 (plus secular 0.1).
        for i in range(MIN_USERS):
            base = 0.5 + 0.01 * i
            _submit(store, f"up{i}", "1.0.0", base, early)
            _submit(store, f"up{i}", "2.0.0", base + 0.1 + 0.3, late)
        # Stayers (control): only 1.0.0, at two dates, secular +0.1.
        for i in range(MIN_USERS):
            base = 0.5 + 0.01 * i
            _submit(store, f"stay{i}", "1.0.0", base, early)
            _submit(store, f"stay{i}", "1.0.0", base + 0.1, late)

        dids = run_upgrade_did(store, n_resamples=300, seed=0)

    assert len(dids) == 1
    d = dids[0]
    assert (d.baseline, d.current) == ("1.0.0", "2.0.0")
    assert d.method == "did" and d.n_treated == MIN_USERS and d.n_control == MIN_USERS
    assert d.estimate is not None and abs(d.estimate - 0.3) < 0.1  # secular drift subtracted


def test_did_suppressed_below_threshold(tmp_path: Path) -> None:
    with ServerStore(tmp_path / "srv.duckdb") as store:
        for i in range(MIN_USERS - 1):  # too few upgraders
            _submit(store, f"up{i}", "1.0.0", 0.5, date(2026, 1, 1))
            _submit(store, f"up{i}", "2.0.0", 0.8, date(2026, 2, 1))
        assert run_upgrade_did(store, n_resamples=100) == []  # k-anonymity suppresses it


def test_change_point_detected_over_dates(tmp_path: Path) -> None:
    with ServerStore(tmp_path / "srv.duckdb") as store:
        # 10 dates; cross-user level jumps from ~0.2 to ~0.9 after day 5. Each date has MIN_USERS.
        for day in range(1, 11):
            level = 0.2 if day <= 5 else 0.9
            for i in range(MIN_USERS):
                _submit(store, f"c{i}", "1.0.0", level + 0.001 * i, date(2026, 1, day))
        changes = run_change_points(store, n_permutations=300, seed=0, min_points=6)

    assert changes
    cp = next(c for c in changes if c.metric == METRIC)
    assert cp.p_value < 0.05
    assert cp.pre_mean is not None and cp.post_mean is not None
    assert cp.post_mean - cp.pre_mean > 0.5  # the jump is recovered
    assert cp.change_date == "2026-01-05"  # last "before" date


def test_endpoints_and_dashboard(tmp_path: Path) -> None:
    db = tmp_path / "srv.duckdb"
    with ServerStore(db) as store:
        for i in range(MIN_USERS):
            _submit(store, f"up{i}", "1.0.0", 0.5 + 0.01 * i, date(2026, 1, 1))
            _submit(store, f"up{i}", "2.0.0", 0.9 + 0.01 * i, date(2026, 2, 1))

    client = TestClient(create_app(db))
    client.post("/aggregate")
    upgrades = client.get("/upgrades").json()
    assert upgrades and upgrades[0]["current"] == "2.0.0"
    assert client.get("/changepoints").status_code == 200
    assert "<table>" in client.get("/").text


def test_dashboard_sections_render() -> None:
    from observatory_server.analysis import ChangePointRow, DidRow

    did = DidRow("claude_code", METRIC, WINDOW, "1.0.0", "2.0.0", 0.3, 0.1, 0.5, "did", 5, 5)
    cp = ChangePointRow("claude_code", "1.0.0", METRIC, WINDOW, "2026-01-05", 0.2, 0.9, 0.01, 10)
    html = render_dashboard([], [did], [cp])
    assert "difference-in-differences" in html
    assert "change points" in html.lower()
    assert "2026-01-05" in html
