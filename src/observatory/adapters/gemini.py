"""Gemini CLI adapter.

Logs live at ``~/.gemini/tmp/<project>/chats/*.json``; each file is a single JSON object holding a
``messages`` array in Gemini's ``role``/``parts`` shape (``role`` is ``user`` or ``model``;
parts carry ``text``, ``functionCall``, ``functionResponse``, or a ``thoughtSignature``). The
thought *signature* length is the depth proxy, exactly as for Claude Code.

No Gemini logs exist on the maintainer's machine, so this adapter is fixture-driven against the
documented ``parts`` shape; it never raises on unexpected input (invariant 5) and opens files
read-only (invariant 3).
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
from observatory.schema import Agent, Effort, Event, EventRole, Session, ToolCall

_PATH_KEYS = ("absolute_path", "file_path", "path", "filename")
_INTERRUPT_TOKENS = ("cancel", "interrupt")


def _arg_target(args: object) -> str | None:
    if not isinstance(args, dict):
        return None
    for key in _PATH_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    parts = message.get("parts")
    return [p for p in parts if isinstance(p, dict)] if isinstance(parts, list) else []


class GeminiAdapter:
    agent_name = "gemini"

    def default_log_root(self) -> Path:
        return Path.home() / ".gemini" / "tmp"

    def discover(self, root: Path | None = None) -> Iterator[Path]:
        base = root or self.default_log_root()
        if not base.exists():
            return
        yield from sorted(base.glob("*/chats/*.json"))

    def parse_sessions(self, path: Path) -> Iterator[Session]:
        yield self.parse_file(path)

    def parse_file(self, path: Path) -> Session:
        try:
            doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            doc = {}
        if not isinstance(doc, dict):
            doc = {}

        cli_version = str(doc.get("cliVersion") or doc.get("version") or "unknown")
        cwd = doc.get("cwd") if isinstance(doc.get("cwd"), str) else None
        started_at = _parse_ts(doc.get("startTime"))

        raw_targets: list[str] = []
        first_prompt: str | None = None
        events: list[Event] = []
        unknown_events = 0

        messages = doc.get("messages")
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict):
                unknown_events += 1
                continue
            role = message.get("role")
            if started_at is None:
                started_at = _parse_ts(message.get("timestamp"))
            if role == "user":
                ev, prompt = self._user_event(message)
                if prompt and first_prompt is None:
                    first_prompt = prompt
                events.append(ev)
            elif role == "model":
                events.append(self._model_event(message, raw_targets))
            else:
                unknown_events += 1

        local_hour = started_at.astimezone().hour if started_at else 0
        return Session(
            session_id=str(doc.get("sessionId") or path.stem),
            agent=Agent.gemini,
            cli_version=cli_version,
            model_id=str(doc.get("model") or "unknown"),
            effort=Effort.unknown,
            project_fingerprint=fingerprint(cwd) or "unknown",
            language=language_from_paths(raw_targets),
            task_type=task_type_from_prompt(first_prompt),
            local_hour=local_hour,
            started_at=started_at.astimezone(UTC) if started_at else None,
            events=events,
            unknown_events=unknown_events,
        )

    def _user_event(self, message: dict[str, Any]) -> tuple[Event, str | None]:
        parts = _parts(message)
        texts = [p["text"] for p in parts if isinstance(p.get("text"), str)]
        text = "\n".join(texts) if texts else None
        is_interrupt = message.get("cancelled") is True or (
            text is not None and any(tok in text.lower() for tok in _INTERRUPT_TOKENS)
        )
        if is_interrupt:
            return Event(role=EventRole.interrupt), None
        if any("functionResponse" in p for p in parts):
            return Event(role=EventRole.tool_result), None
        if text is not None:
            return Event(role=EventRole.user_turn, user_text_len=len(text)), text
        return Event(role=EventRole.other), None

    def _model_event(self, message: dict[str, Any], raw_targets: list[str]) -> Event:
        tool_calls: list[ToolCall] = []
        sig_len = 0
        has_thinking = False
        text_len = 0
        has_code_fence = False
        for part in _parts(message):
            call = part.get("functionCall")
            sig = part.get("thoughtSignature")
            if isinstance(call, dict):
                name = str(call.get("name", ""))
                target = _arg_target(call.get("args"))
                if target:
                    raw_targets.append(target)
                tool_calls.append(
                    ToolCall(name=name, kind=classify_tool(name), target=fingerprint(target))
                )
            elif isinstance(sig, str):
                has_thinking = True
                sig_len += len(sig)
            elif isinstance(part.get("text"), str) and not part.get("thought"):
                text = part["text"]
                text_len += len(text)
                if "```" in text:
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
