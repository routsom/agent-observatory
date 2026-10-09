"""History store: idempotent upsert and time-window queries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from observatory.schema import Agent, Session
from observatory.store import History, parse_window


def _session(sid: str, *, days_ago: float, version: str = "1.0.0") -> Session:
    return Session(
        session_id=sid,
        agent=Agent.claude_code,
        cli_version=version,
        started_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def test_upsert_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "h.duckdb"
    with History(db) as h:
        h.upsert([_session("s1", days_ago=1)])
        h.upsert([_session("s1", days_ago=1)])  # same id again
        assert h.count() == 1


def test_upsert_updates_existing(tmp_path: Path) -> None:
    db = tmp_path / "h.duckdb"
    with History(db) as h:
        h.upsert([_session("s1", days_ago=1, version="1.0.0")])
        h.upsert([_session("s1", days_ago=1, version="2.0.0")])
        assert h.count() == 1
        assert h.query("all")[0].cli_version == "2.0.0"


def test_window_filtering(tmp_path: Path) -> None:
    db = tmp_path / "h.duckdb"
    with History(db) as h:
        h.upsert(
            [
                _session("recent", days_ago=2),
                _session("old", days_ago=45),
            ]
        )
        recent = h.query("30d")
        assert {s.session_id for s in recent} == {"recent"}
        assert len(h.query("all")) == 2


def test_round_trip_preserves_session(tmp_path: Path) -> None:
    db = tmp_path / "h.duckdb"
    original = _session("s1", days_ago=1)
    with History(db) as h:
        h.upsert([original])
        restored = h.query("all")[0]
    assert restored.model_dump() == original.model_dump()


def test_parse_window() -> None:
    assert parse_window("all") is None
    assert parse_window("30d") == timedelta(days=30)
    assert parse_window("12h") == timedelta(hours=12)
    assert parse_window("2w") == timedelta(weeks=2)
    with pytest.raises(ValueError):
        parse_window("nonsense")
