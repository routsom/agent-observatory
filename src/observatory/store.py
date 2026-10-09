"""Local history in DuckDB at ``~/.observatory/history.duckdb``.

Sessions are upserted idempotently by ``session_id`` (re-ingesting the same log is a no-op), and
queried by time window. The full normalised `Session` is stored as JSON alongside a few indexed
columns for filtering. This is the only module that persists anything, and it writes only to the
observatory's own directory - never to an agent's log directory (invariant 3).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from observatory.schema import Session

_WINDOW_RE = re.compile(r"^(\d+)([hdw])$")
_UNIT_SECONDS = {"h": 3600, "d": 86400, "w": 604800}


def parse_window(window: str) -> timedelta | None:
    """Parse a window string like ``30d``/``12h``/``2w``. ``all`` -> None (no time filter)."""
    if window.lower() == "all":
        return None
    m = _WINDOW_RE.match(window.strip())
    if not m:
        raise ValueError(f"invalid window {window!r}; use e.g. 30d, 12h, 2w, or 'all'")
    return timedelta(seconds=int(m.group(1)) * _UNIT_SECONDS[m.group(2)])


def default_db_path() -> Path:
    home = Path(os.environ.get("OBSERVATORY_HOME", Path.home() / ".observatory"))
    return home / "history.duckdb"


class History:
    """Idempotent session history."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   VARCHAR PRIMARY KEY,
                agent        VARCHAR NOT NULL,
                cli_version  VARCHAR NOT NULL,
                model_id     VARCHAR NOT NULL,
                started_at   TIMESTAMPTZ,
                payload      VARCHAR NOT NULL
            )
            """
        )

    def upsert(self, sessions: Iterable[Session]) -> int:
        rows = [
            (
                s.session_id,
                s.agent.value,
                s.cli_version,
                s.model_id,
                s.started_at,
                s.model_dump_json(),
            )
            for s in sessions
        ]
        if not rows:
            return 0
        self._con.executemany(
            """
            INSERT INTO sessions (session_id, agent, cli_version, model_id, started_at, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                agent = excluded.agent,
                cli_version = excluded.cli_version,
                model_id = excluded.model_id,
                started_at = excluded.started_at,
                payload = excluded.payload
            """,
            rows,
        )
        return len(rows)

    def query(self, window: str = "all", *, now: datetime | None = None) -> list[Session]:
        """Return sessions whose ``started_at`` falls within the window (newest first).

        Sessions with no timestamp are included only for the ``all`` window.
        """
        delta = parse_window(window)
        if delta is None:
            result = self._con.execute(
                "SELECT payload FROM sessions ORDER BY started_at DESC NULLS LAST"
            ).fetchall()
        else:
            cutoff = (now or datetime.now(UTC)) - delta
            result = self._con.execute(
                "SELECT payload FROM sessions "
                "WHERE started_at IS NOT NULL AND started_at >= ? "
                "ORDER BY started_at DESC",
                [cutoff],
            ).fetchall()
        return [Session.model_validate_json(row[0]) for row in result]

    def count(self) -> int:
        row = self._con.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> History:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def ingest(sessions: Sequence[Session], db_path: Path | None = None) -> int:
    """Convenience: upsert sessions into the default (or given) history."""
    with History(db_path) as h:
        return h.upsert(sessions)
