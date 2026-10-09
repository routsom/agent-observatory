"""Server-side DuckDB storage for ingested submissions and published aggregates.

Each submission row is one (client_id, agent, cli_version, metric, window) measurement. Ingest is
idempotent on submission_id, and only a user's latest submission per key is retained, so repeat
uploads neither double-count nor let a heavy user dominate (users are weighted equally downstream).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from observatory.share.payload import SharePayload


@dataclass(frozen=True)
class SubmissionRow:
    client_id: str
    agent: str
    cli_version: str
    model_id: str
    metric: str
    window: str
    value: float | None
    n_sessions: int
    n_tool_calls: int
    generated_on: date


@dataclass(frozen=True)
class PublishedCell:
    agent: str
    cli_version: str
    metric: str
    window: str
    value: float | None
    ci_low: float | None
    ci_high: float | None
    method: str
    n_users: int


def default_db_path() -> Path:
    home = Path(os.environ.get("OBSERVATORY_SERVER_HOME", Path.home() / ".observatory-server"))
    return home / "ingest.duckdb"


class ServerStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                submission_id VARCHAR,
                client_id     VARCHAR NOT NULL,
                agent         VARCHAR NOT NULL,
                cli_version   VARCHAR NOT NULL,
                model_id      VARCHAR NOT NULL,
                metric        VARCHAR NOT NULL,
                "window"      VARCHAR NOT NULL,
                value         DOUBLE,
                n_sessions    INTEGER NOT NULL,
                n_tool_calls  INTEGER NOT NULL,
                generated_on  DATE NOT NULL,
                PRIMARY KEY (client_id, agent, cli_version, metric, "window")
            )
            """
        )
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_submissions (submission_id VARCHAR PRIMARY KEY)
            """
        )
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS published (
                agent       VARCHAR NOT NULL,
                cli_version VARCHAR NOT NULL,
                metric      VARCHAR NOT NULL,
                "window"    VARCHAR NOT NULL,
                value       DOUBLE,
                ci_low      DOUBLE,
                ci_high     DOUBLE,
                method      VARCHAR NOT NULL,
                n_users     INTEGER NOT NULL,
                PRIMARY KEY (agent, cli_version, metric, "window")
            )
            """
        )
        # Phase 3: dated history for DiD + change-point (one row per client/cell/date).
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS submission_history (
                client_id    VARCHAR NOT NULL,
                agent        VARCHAR NOT NULL,
                cli_version  VARCHAR NOT NULL,
                metric       VARCHAR NOT NULL,
                "window"     VARCHAR NOT NULL,
                value        DOUBLE,
                generated_on DATE NOT NULL,
                PRIMARY KEY (client_id, agent, cli_version, metric, "window", generated_on)
            )
            """
        )

    def ingest(self, payload: SharePayload) -> bool:
        """Store a submission. Returns False if this submission_id was already ingested."""
        seen = self._con.execute(
            "SELECT 1 FROM seen_submissions WHERE submission_id = ?", [payload.submission_id]
        ).fetchone()
        if seen is not None:
            return False
        self._con.execute("INSERT INTO seen_submissions VALUES (?)", [payload.submission_id])
        rows = [
            (
                payload.submission_id,
                payload.client_id,
                payload.agent.value,
                a.cli_version,
                a.model_id,
                a.metric,
                payload.window,
                a.value,
                a.n_sessions,
                a.n_tool_calls,
                payload.generated_on,
            )
            for a in payload.aggregates
        ]
        self._con.executemany(
            """
            INSERT INTO submissions
                (submission_id, client_id, agent, cli_version, model_id, metric, "window",
                 value, n_sessions, n_tool_calls, generated_on)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (client_id, agent, cli_version, metric, "window") DO UPDATE SET
                submission_id = excluded.submission_id,
                model_id = excluded.model_id,
                value = excluded.value,
                n_sessions = excluded.n_sessions,
                n_tool_calls = excluded.n_tool_calls,
                generated_on = excluded.generated_on
            """,
            rows,
        )
        history_rows = [
            (
                payload.client_id,
                payload.agent.value,
                a.cli_version,
                a.metric,
                payload.window,
                a.value,
                payload.generated_on,
            )
            for a in payload.aggregates
        ]
        self._con.executemany(
            """
            INSERT INTO submission_history
                (client_id, agent, cli_version, metric, "window", value, generated_on)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (client_id, agent, cli_version, metric, "window", generated_on)
                DO UPDATE SET value = excluded.value
            """,
            history_rows,
        )
        return True

    def values_by_client(
        self, agent: str, cli_version: str, metric: str, window: str
    ) -> dict[str, list[float]]:
        """Each distinct client's non-null value for a cell (one value per client here)."""
        result = self._con.execute(
            "SELECT client_id, value FROM submissions "
            'WHERE agent = ? AND cli_version = ? AND metric = ? AND "window" = ? '
            "AND value IS NOT NULL",
            [agent, cli_version, metric, window],
        ).fetchall()
        out: dict[str, list[float]] = {}
        for client_id, value in result:
            out.setdefault(client_id, []).append(float(value))
        return out

    def cells(self) -> list[tuple[str, str, str, str]]:
        """Distinct (agent, cli_version, metric, window) keys present in submissions."""
        rows = self._con.execute(
            'SELECT DISTINCT agent, cli_version, metric, "window" FROM submissions'
        ).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def replace_published(self, cells: Iterable[PublishedCell]) -> int:
        self._con.execute("DELETE FROM published")
        rows = [
            (
                c.agent,
                c.cli_version,
                c.metric,
                c.window,
                c.value,
                c.ci_low,
                c.ci_high,
                c.method,
                c.n_users,
            )
            for c in cells
        ]
        if rows:
            self._con.executemany("INSERT INTO published VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def published(self) -> list[PublishedCell]:
        rows = self._con.execute(
            'SELECT agent, cli_version, metric, "window", value, ci_low, ci_high, method, n_users '
            "FROM published ORDER BY agent, cli_version, metric"
        ).fetchall()
        return [
            PublishedCell(
                agent=r[0],
                cli_version=r[1],
                metric=r[2],
                window=r[3],
                value=r[4],
                ci_low=r[5],
                ci_high=r[6],
                method=r[7],
                n_users=r[8],
            )
            for r in rows
        ]

    # --- phase-3 readers over submission_history ---

    def metric_keys(self) -> list[tuple[str, str, str]]:
        """Distinct (agent, metric, window) keys present in history."""
        rows = self._con.execute(
            'SELECT DISTINCT agent, metric, "window" FROM submission_history'
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def versions_by_first_seen(self, agent: str, metric: str, window: str) -> list[str]:
        """CLI versions for a cell, ordered by when they were first submitted (earliest first)."""
        rows = self._con.execute(
            "SELECT cli_version, MIN(generated_on) AS first_seen FROM submission_history "
            'WHERE agent = ? AND metric = ? AND "window" = ? '
            "GROUP BY cli_version ORDER BY first_seen, cli_version",
            [agent, metric, window],
        ).fetchall()
        return [r[0] for r in rows]

    def latest_value_by_client(
        self, agent: str, cli_version: str, metric: str, window: str
    ) -> dict[str, float]:
        """Each client's latest non-null value for a cell."""
        rows = self._con.execute(
            "SELECT client_id, value FROM submission_history h "
            'WHERE agent = ? AND cli_version = ? AND metric = ? AND "window" = ? '
            "AND value IS NOT NULL "
            "AND generated_on = (SELECT MAX(generated_on) FROM submission_history h2 "
            "  WHERE h2.client_id = h.client_id AND h2.agent = h.agent "
            "  AND h2.cli_version = h.cli_version AND h2.metric = h.metric "
            '  AND h2."window" = h."window")',
            [agent, cli_version, metric, window],
        ).fetchall()
        return {r[0]: float(r[1]) for r in rows}

    def endpoints_by_client(
        self, agent: str, cli_version: str, metric: str, window: str
    ) -> dict[str, tuple[float, float]]:
        """Clients with >= 2 dated values for a cell -> (earliest value, latest value)."""
        rows = self._con.execute(
            "SELECT client_id, value, generated_on FROM submission_history "
            'WHERE agent = ? AND cli_version = ? AND metric = ? AND "window" = ? '
            "AND value IS NOT NULL ORDER BY client_id, generated_on",
            [agent, cli_version, metric, window],
        ).fetchall()
        by_client: dict[str, list[float]] = {}
        for client_id, value, _ in rows:
            by_client.setdefault(client_id, []).append(float(value))
        return {c: (v[0], v[-1]) for c, v in by_client.items() if len(v) >= 2}

    def date_series(
        self, agent: str, cli_version: str, metric: str, window: str, *, min_users: int
    ) -> list[tuple[str, float]]:
        """Per-date user-equal mean for a cell, keeping only dates with >= min_users clients."""
        rows = self._con.execute(
            "SELECT generated_on, AVG(value) AS m, COUNT(DISTINCT client_id) AS n "
            "FROM submission_history "
            'WHERE agent = ? AND cli_version = ? AND metric = ? AND "window" = ? '
            "AND value IS NOT NULL GROUP BY generated_on ORDER BY generated_on",
            [agent, cli_version, metric, window],
        ).fetchall()
        return [(str(r[0]), float(r[1])) for r in rows if r[2] >= min_users]

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> ServerStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
