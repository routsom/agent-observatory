#!/usr/bin/env python3
"""Build the scrubbed opencode SQLite fixture.

opencode stores sessions in a SQLite DB; there is no real one to scrub on this machine, so this
builds a small *synthetic, already-scrubbed* database matching the schema the adapter reads. A
``_meta`` row carries the scrubber marker that the fixture test requires (invariant 4). Re-run to
regenerate:

    python tools/make_opencode_fixture.py tests/fixtures/opencode/0.3.0/opencode.db 0.3.0
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SCHEMA = [
    "CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE session (id TEXT PRIMARY KEY, version TEXT, directory TEXT, model TEXT, "
    "created TEXT)",
    "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, role TEXT, created TEXT)",
    "CREATE TABLE part (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT, type TEXT, "
    "text TEXT, tool TEXT, path TEXT, signature TEXT)",
]


def build(path: Path, version: str) -> None:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        for stmt in SCHEMA:
            con.execute(stmt)
        con.execute("INSERT INTO _meta VALUES ('_observatory_scrubbed', ?)", [version])

        # Session s1: a hand-checkable refactor session (read, edit, edit-again, text, interrupt).
        con.execute(
            "INSERT INTO session VALUES ('s1', ?, '/scrubbed/proj', 'claude-sonnet-5', "
            "'2026-03-03T14:00:00Z')",
            [version],
        )
        messages = [
            ("s1-m1", "s1", "user", "2026-03-03T14:00:00Z"),
            ("s1-m2", "s1", "assistant", "2026-03-03T14:00:01Z"),
            ("s1-m3", "s1", "user", "2026-03-03T14:00:02Z"),
            ("s1-m4", "s1", "assistant", "2026-03-03T14:00:03Z"),
            ("s1-m5", "s1", "assistant", "2026-03-03T14:00:04Z"),
            ("s1-m6", "s1", "user", "2026-03-03T14:00:05Z"),
        ]
        con.executemany("INSERT INTO message VALUES (?, ?, ?, ?)", messages)
        parts = [
            ("s1-m1", "text", "refactor module", None, None, None),
            ("s1-m2", "reasoning", None, None, None, "x" * 20),
            ("s1-m2", "tool", None, "read", "/scrubbed/y.py", None),
            ("s1-m3", "tool-result", None, None, None, None),
            ("s1-m4", "tool", None, "edit", "/scrubbed/y.py", None),
            ("s1-m4", "tool", None, "edit", "/scrubbed/y.py", None),
            ("s1-m5", "text", "see ```patch```", None, None, None),
            ("s1-m6", "interrupt", None, None, None, None),
        ]
        con.executemany(
            "INSERT INTO part (message_id, type, text, tool, path, signature) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            parts,
        )

        # Session s2: a second, minimal session to prove one DB yields many sessions.
        con.execute(
            "INSERT INTO session VALUES ('s2', ?, '/scrubbed/proj2', 'claude-sonnet-5', "
            "'2026-03-04T10:00:00Z')",
            [version],
        )
        con.execute("INSERT INTO message VALUES ('s2-m1', 's2', 'user', '2026-03-04T10:00:00Z')")
        con.execute(
            "INSERT INTO part (message_id, type, text, tool, path, signature) "
            "VALUES ('s2-m1', 'text', 'add a feature', NULL, NULL, NULL)"
        )
        con.commit()
    finally:
        con.close()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    build(Path(argv[1]), argv[2])
    print(f"wrote opencode fixture {argv[1]} (version {argv[2]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
