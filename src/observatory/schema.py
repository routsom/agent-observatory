"""Normalised, agent-agnostic session schema.

Adapters turn each agent's raw log into these models; everything downstream (metrics, store,
report) operates only on them and never learns which agent produced a session. See SPEC.md §1.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Agent(StrEnum):
    claude_code = "claude_code"
    codex = "codex"
    gemini = "gemini"
    opencode = "opencode"


class Effort(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    unknown = "unknown"


class Language(StrEnum):
    python = "python"
    javascript = "javascript"
    typescript = "typescript"
    rust = "rust"
    go = "go"
    java = "java"
    other = "other"
    unknown = "unknown"


class TaskType(StrEnum):
    feature = "feature"
    bugfix = "bugfix"
    refactor = "refactor"
    docs = "docs"
    other = "other"
    unknown = "unknown"


class ToolKind(StrEnum):
    read = "read"
    edit = "edit"
    other = "other"


class EventRole(StrEnum):
    user_turn = "user_turn"
    assistant_api_call = "assistant_api_call"
    interrupt = "interrupt"
    tool_result = "tool_result"
    other = "other"


class ToolCall(BaseModel):
    """A single tool invocation. `target` is a salted fingerprint, never a raw path."""

    name: str
    kind: ToolKind
    target: str | None = None


class Event(BaseModel):
    """A dedup-collapsed point in the session timeline."""

    role: EventRole
    tool_calls: list[ToolCall] = Field(default_factory=list)
    thinking_signature_len: int | None = None


class Session(BaseModel):
    """One normalised agent session."""

    session_id: str
    agent: Agent
    cli_version: str = "unknown"
    model_id: str = "unknown"
    effort: Effort = Effort.unknown
    project_fingerprint: str = "unknown"
    language: Language = Language.unknown
    task_type: TaskType = TaskType.unknown
    local_hour: int = 0
    started_at: datetime | None = None
    events: list[Event] = Field(default_factory=list)
    unknown_events: int = 0

    def tool_calls(self) -> list[ToolCall]:
        """Every tool call across all assistant API calls, in order."""
        calls: list[ToolCall] = []
        for ev in self.events:
            calls.extend(ev.tool_calls)
        return calls
