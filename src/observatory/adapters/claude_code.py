"""Claude Code adapter.

Logs live at ``~/.claude/projects/<encoded-path>/<uuid>.jsonl``, one JSON object per line, in an
undocumented format. Key realities handled here (verified against real logs):

* Assistant messages are deduped on ``(message.id, requestId)`` - resumed/branched sessions
  duplicate them.
* ``thinking`` blocks are redacted; only the ``signature`` length survives as a depth *proxy*.
* Interrupts appear as literal user-message markers ``[Request interrupted by user ...]``.

Unknown line types are counted (``unknown_events``) and skipped - the parser never raises on
unexpected input (invariant 5). Files are opened read-only (invariant 3).
"""

from __future__ import annotations

import json
from collections import Counter
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

# Line ``type`` values we understand and deliberately ignore (not counted as unknown).
_IGNORED_TYPES = {
    "mode",
    "permission-mode",
    "file-history-snapshot",
    "attachment",
    "last-prompt",
    "ai-title",
    "system",
    "agent-name",
    "queue-operation",
    "bridge-session",
    "summary",
}

_INTERRUPT_MARKER = "[request interrupted by user"
_PATH_KEYS = ("file_path", "notebook_path", "path", "filePath")


def _tool_target(tool_input: object) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in _PATH_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _user_text(content: object) -> tuple[str | None, bool]:
    """Return (plain text, is_tool_result) for a user message's content."""
    if isinstance(content, str):
        return content, False
    if isinstance(content, list):
        texts: list[str] = []
        is_tool_result = False
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_result":
                is_tool_result = True
            elif btype == "text":
                text = block.get("text")
                if isinstance(text, str):
                    texts.append(text)
        return ("\n".join(texts) if texts else None), is_tool_result
    return None, False


class ClaudeCodeAdapter:
    agent_name = "claude_code"

    def default_log_root(self) -> Path:
        return Path.home() / ".claude" / "projects"

    def discover(self, root: Path | None = None) -> Iterator[Path]:
        base = root or self.default_log_root()
        if not base.exists():
            return
        yield from sorted(base.glob("*/*.jsonl"))

    def parse_file(self, path: Path) -> Session:
        session_id = path.stem
        cli_version = "unknown"
        cwd: str | None = None
        started_at: datetime | None = None
        unknown_events = 0

        model_counts: Counter[str] = Counter()
        raw_targets: list[str] = []
        first_prompt: str | None = None
        seen_api_calls: set[tuple[str, str]] = set()
        events: list[Event] = []

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

                if obj.get("version") and cli_version == "unknown":
                    cli_version = str(obj["version"])
                if cwd is None and isinstance(obj.get("cwd"), str):
                    cwd = obj["cwd"]
                if started_at is None:
                    started_at = _parse_ts(obj.get("timestamp"))

                ltype = obj.get("type")
                if ltype == "assistant":
                    ev = self._assistant_event(obj, seen_api_calls, model_counts, raw_targets)
                    if ev is not None:
                        events.append(ev)
                elif ltype == "user":
                    ev, prompt = self._user_event(obj)
                    if prompt and first_prompt is None:
                        first_prompt = prompt
                    if ev is not None:
                        events.append(ev)
                elif ltype in _IGNORED_TYPES:
                    continue
                else:
                    unknown_events += 1

        local_hour = started_at.astimezone().hour if started_at else 0
        model_id = model_counts.most_common(1)[0][0] if model_counts else "unknown"

        return Session(
            session_id=session_id,
            agent=Agent.claude_code,
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

    def _assistant_event(
        self,
        obj: dict[str, Any],
        seen: set[tuple[str, str]],
        model_counts: Counter[str],
        raw_targets: list[str],
    ) -> Event | None:
        message = obj.get("message")
        if not isinstance(message, dict):
            return None
        dedup_key = (str(message.get("id", "")), str(obj.get("requestId", "")))
        if dedup_key in seen:
            return None
        seen.add(dedup_key)

        model = message.get("model")
        if isinstance(model, str) and model:
            model_counts[model] += 1

        tool_calls: list[ToolCall] = []
        sig_len = 0
        has_thinking = False
        text_len = 0
        has_code_fence = False
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    name = str(block.get("name", ""))
                    target = _tool_target(block.get("input"))
                    if target:
                        raw_targets.append(target)
                    tool_calls.append(
                        ToolCall(
                            name=name,
                            kind=classify_tool(name),
                            target=fingerprint(target),
                        )
                    )
                elif btype == "thinking":
                    has_thinking = True
                    sig = block.get("signature")
                    if isinstance(sig, str):
                        sig_len += len(sig)
                elif btype == "text":
                    text = block.get("text")
                    if isinstance(text, str):
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

    def _user_event(self, obj: dict[str, Any]) -> tuple[Event | None, str | None]:
        if obj.get("isMeta"):
            return Event(role=EventRole.other), None
        message = obj.get("message")
        if not isinstance(message, dict):
            return Event(role=EventRole.other), None
        text, is_tool_result = _user_text(message.get("content"))
        if text and _INTERRUPT_MARKER in text.lower():
            return Event(role=EventRole.interrupt), None
        if is_tool_result:
            return Event(role=EventRole.tool_result), None
        if text is not None:
            return Event(role=EventRole.user_turn, user_text_len=len(text)), text
        return Event(role=EventRole.other), None


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
