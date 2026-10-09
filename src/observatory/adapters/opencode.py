"""opencode adapter.

opencode stores all sessions in one SQLite database at
``~/.local/share/opencode/opencode.db``. The DB is opened **read-only** (``mode=ro``) per
invariant 3, and one DB yields many `Session`s (hence `parse_sessions`). Schema used (scrubbed
fixtures are built to match):

* ``session(id, version, directory, model, created)`` - ``version`` is the CLI version.
* ``message(id, session_id, role, created)`` - ``role`` is ``user`` / ``assistant``.
* ``part(message_id, type, text, tool, path, signature)`` - ``type`` in
  ``text`` / ``tool`` / ``reasoning`` / ``tool-result`` / ``interrupt``.

No opencode logs exist on the maintainer's machine, so this is fixture-driven against that schema;
it never raises on a malformed/absent DB (invariant 5).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from observatory.adapters.base import (
    classify_tool,
    fingerprint,
    language_from_paths,
    task_type_from_prompt,
)
from observatory.schema import Agent, Effort, Event, EventRole, Session, ToolCall


class OpenCodeAdapter:
    agent_name = "opencode"

    def default_log_root(self) -> Path:
        return Path.home() / ".local" / "share" / "opencode"

    def discover(self, root: Path | None = None) -> Iterator[Path]:
        base = root or self.default_log_root()
        if not base.exists():
            return
        if base.is_file():
            yield base
        else:
            yield from sorted(base.glob("**/*.db"))

    def parse_file(self, path: Path) -> Session:
        """Convenience single-session accessor (first session, or empty)."""
        return next(
            self.parse_sessions(path),
            Session(session_id=path.stem, agent=Agent.opencode),
        )

    def parse_sessions(self, path: Path) -> Iterator[Session]:
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error:
            return
        try:
            con.row_factory = sqlite3.Row
            try:
                sessions = con.execute(
                    "SELECT id, version, directory, model, created FROM session ORDER BY created"
                ).fetchall()
            except sqlite3.Error:
                return  # not an opencode DB / schema absent
            for srow in sessions:
                yield self._session(con, srow)
        finally:
            con.close()

    def _session(self, con: sqlite3.Connection, srow: sqlite3.Row) -> Session:
        session_id = str(srow["id"])
        started_at = _parse_ts(srow["created"])
        raw_targets: list[str] = []
        first_prompt: str | None = None
        events: list[Event] = []
        unknown_events = 0

        messages = con.execute(
            "SELECT id, role, created FROM message WHERE session_id = ? ORDER BY created, rowid",
            [session_id],
        ).fetchall()
        for mrow in messages:
            parts = con.execute(
                "SELECT type, text, tool, path, signature FROM part "
                "WHERE message_id = ? ORDER BY rowid",
                [mrow["id"]],
            ).fetchall()
            role = mrow["role"]
            if role == "user":
                ev, prompt = _user_event(parts)
                if prompt and first_prompt is None:
                    first_prompt = prompt
                events.append(ev)
            elif role == "assistant":
                events.append(_assistant_event(parts, raw_targets))
            else:
                unknown_events += 1

        local_hour = started_at.astimezone().hour if started_at else 0
        return Session(
            session_id=session_id,
            agent=Agent.opencode,
            cli_version=str(srow["version"] or "unknown"),
            model_id=str(srow["model"] or "unknown"),
            effort=Effort.unknown,
            project_fingerprint=fingerprint(srow["directory"]) or "unknown",
            language=language_from_paths(raw_targets),
            task_type=task_type_from_prompt(first_prompt),
            local_hour=local_hour,
            started_at=started_at.astimezone(UTC) if started_at else None,
            events=events,
            unknown_events=unknown_events,
        )


def _user_event(parts: list[sqlite3.Row]) -> tuple[Event, str | None]:
    types = {p["type"] for p in parts}
    if "interrupt" in types:
        return Event(role=EventRole.interrupt), None
    if "tool-result" in types:
        return Event(role=EventRole.tool_result), None
    texts = [p["text"] for p in parts if p["type"] == "text" and isinstance(p["text"], str)]
    if texts:
        text = "\n".join(texts)
        return Event(role=EventRole.user_turn, user_text_len=len(text)), text
    return Event(role=EventRole.other), None


def _assistant_event(parts: list[sqlite3.Row], raw_targets: list[str]) -> Event:
    tool_calls: list[ToolCall] = []
    sig_len = 0
    has_thinking = False
    text_len = 0
    has_code_fence = False
    for p in parts:
        ptype = p["type"]
        if ptype == "tool":
            name = str(p["tool"] or "")
            target = p["path"] if isinstance(p["path"], str) and p["path"] else None
            if target:
                raw_targets.append(target)
            tool_calls.append(
                ToolCall(name=name, kind=classify_tool(name), target=fingerprint(target))
            )
        elif ptype == "reasoning" and isinstance(p["signature"], str):
            has_thinking = True
            sig_len += len(p["signature"])
        elif ptype == "text" and isinstance(p["text"], str):
            text_len += len(p["text"])
            if "```" in p["text"]:
                has_code_fence = True
    return Event(
        role=EventRole.assistant_api_call,
        tool_calls=tool_calls,
        thinking_signature_len=sig_len if has_thinking else None,
        assistant_text_len=text_len,
        has_code_fence=has_code_fence,
    )


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
