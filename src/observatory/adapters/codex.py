"""Codex CLI adapter.

Logs live at ``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl``. The first line is a
``session_meta`` object carrying ``cli_version``. Subsequent lines are ``response_item`` entries
(``message`` / ``reasoning`` / ``function_call`` / ``function_call_output``) and ``event_msg``
entries; ``turn_aborted`` marks a user interrupt. Tool calls pair on ``call_id``. Codex has no
thinking *signature*, so ``thinking_depth_proxy`` is always ``None`` for Codex sessions.

No Codex logs exist on the maintainer's machine, so this adapter is driven by authored fixtures
and against the documented rollout shape. The mapping of response items to "API calls" is a
documented approximation (see ``_flush``) pending validation on real logs; it never raises on
unexpected input (invariant 5) and opens files read-only (invariant 3).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from observatory.adapters.base import (
    classify_tool,
    fingerprint,
    language_from_paths,
    task_type_from_prompt,
)
from observatory.schema import (
    Agent,
    Effort,
    Event,
    EventRole,
    Session,
    ToolCall,
)

_PATH_KEYS = ("path", "file_path", "filename")


def _item_text(content: object) -> str | None:
    """Join the text segments of a Codex message's content array."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            seg["text"]
            for seg in content
            if isinstance(seg, dict) and isinstance(seg.get("text"), str)
        ]
        return "\n".join(parts) if parts else None
    return None


def _call_target(arguments: object) -> str | None:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    if not isinstance(arguments, dict):
        return None
    for key in _PATH_KEYS:
        val = arguments.get(key)
        if isinstance(val, str) and val:
            return val
    return None


class CodexAdapter:
    agent_name = "codex"

    def default_log_root(self) -> Path:
        return Path.home() / ".codex" / "sessions"

    def discover(self, root: Path | None = None) -> Iterator[Path]:
        base = root or self.default_log_root()
        if not base.exists():
            return
        yield from sorted(base.glob("**/rollout-*.jsonl"))

    def parse_file(self, path: Path) -> Session:
        session_id = path.stem
        cli_version = "unknown"
        cwd: str | None = None
        model_id = "unknown"
        started_at: datetime | None = None
        unknown_events = 0

        raw_targets: list[str] = []
        first_prompt: str | None = None
        events: list[Event] = []
        pending_calls: list[ToolCall] = []  # tool calls awaiting their closing assistant message

        def flush() -> None:
            """Emit one assistant_api_call for the current group of tool calls.

            Approximation: a model "round" is a run of function_calls optionally closed by an
            assistant message. We emit one API call per such round. Documented in the module
            docstring pending real-log validation.
            """
            if pending_calls:
                events.append(
                    Event(role=EventRole.assistant_api_call, tool_calls=list(pending_calls))
                )
                pending_calls.clear()

        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    unknown_events += 1
                    continue
                if not isinstance(obj, dict):
                    unknown_events += 1
                    continue
                if "_observatory_scrubbed" in obj:
                    continue  # fixture marker line (see tools/scrub.py), not an event

                if started_at is None:
                    started_at = _parse_ts(obj.get("timestamp"))
                ltype = obj.get("type")
                payload = obj.get("payload")
                payload = payload if isinstance(payload, dict) else {}

                if ltype == "session_meta":
                    cli_version = str(payload.get("cli_version", cli_version))
                    if isinstance(payload.get("cwd"), str):
                        cwd = payload["cwd"]
                    if isinstance(payload.get("model"), str):
                        model_id = payload["model"]
                elif ltype == "response_item":
                    ptype = payload.get("type")
                    if ptype == "message":
                        role = payload.get("role")
                        text = _item_text(payload.get("content"))
                        if role == "user":
                            flush()
                            if first_prompt is None and text:
                                first_prompt = text
                            events.append(
                                Event(
                                    role=EventRole.user_turn,
                                    user_text_len=len(text) if text else 0,
                                )
                            )
                        elif role == "assistant":
                            # closing message of a model round
                            events.append(
                                Event(
                                    role=EventRole.assistant_api_call,
                                    tool_calls=list(pending_calls),
                                    assistant_text_len=len(text) if text else 0,
                                    has_code_fence=("```" in text) if text else False,
                                )
                            )
                            pending_calls.clear()
                    elif ptype == "function_call":
                        name = str(payload.get("name", ""))
                        target = _call_target(payload.get("arguments"))
                        if target:
                            raw_targets.append(target)
                        pending_calls.append(
                            ToolCall(
                                name=name,
                                kind=classify_tool(name),
                                target=fingerprint(target),
                            )
                        )
                    elif ptype in ("reasoning", "function_call_output"):
                        continue
                    else:
                        unknown_events += 1
                elif ltype == "event_msg":
                    if payload.get("type") == "turn_aborted":
                        flush()
                        events.append(Event(role=EventRole.interrupt))
                    # other event_msg kinds (token_count, task_started, ...) are ignored
                elif ltype in ("turn_context", "compacted"):
                    continue
                else:
                    unknown_events += 1

        flush()

        local_hour = started_at.astimezone().hour if started_at else 0

        return Session(
            session_id=session_id,
            agent=Agent.codex,
            cli_version=cli_version,
            model_id=model_id,
            effort=Effort.unknown,
            project_fingerprint=fingerprint(cwd) or "unknown",
            language=language_from_paths(raw_targets),
            task_type=task_type_from_prompt(first_prompt),
            local_hour=local_hour,
            started_at=started_at.astimezone(UTC) if started_at else None,
            events=events,
            unknown_events=unknown_events,
        )


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
