"""Shared adapter machinery: the `Adapter` protocol plus pure helpers used by every adapter.

Nothing here does network I/O. File reads are read-only (invariant 3). Raw paths are turned into
salted fingerprints immediately and never persisted (invariant 1).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from observatory.schema import Language, Session, TaskType, ToolKind

# Tool-name -> kind classification. See SPEC.md §2. Lower-cased for matching. Covers Claude Code,
# Codex, Gemini CLI (`read_file`/`read_many_files`/`write_file`/`replace`), and opencode (`read`/
# `edit`/`write`).
_READ_TOOLS = {"read", "notebookread", "read_file", "read_many_files"}
_EDIT_TOOLS = {
    "edit",
    "multiedit",
    "write",
    "notebookedit",
    "apply_patch",
    "write_file",
    "replace",
}


def classify_tool(name: str) -> ToolKind:
    """Map a raw tool name to a normalised `ToolKind` (SPEC.md §2)."""
    key = name.strip().lower()
    if key in _READ_TOOLS:
        return ToolKind.read
    if key in _EDIT_TOOLS:
        return ToolKind.edit
    return ToolKind.other


def _salt() -> bytes:
    """Per-machine salt so fingerprints are stable locally but not reversible across machines.

    Stored at ~/.observatory/salt, created on first use. An env override keeps tests hermetic.
    """
    override = os.environ.get("OBSERVATORY_SALT")
    if override is not None:
        return override.encode()
    home = Path(os.environ.get("OBSERVATORY_HOME", Path.home() / ".observatory"))
    salt_path = home / "salt"
    if salt_path.exists():
        return salt_path.read_bytes()
    home.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16)
    salt_path.write_bytes(salt)
    return salt


def fingerprint(value: str | None) -> str | None:
    """Salted, truncated sha256 of a path-like string. `None` in, `None` out."""
    if value is None:
        return None
    digest = hashlib.sha256(_salt() + value.encode("utf-8", "replace")).hexdigest()
    return digest[:16]


# File-extension -> language, for the dominant-language heuristic.
_EXT_LANGUAGE = {
    ".py": Language.python,
    ".js": Language.javascript,
    ".jsx": Language.javascript,
    ".mjs": Language.javascript,
    ".ts": Language.typescript,
    ".tsx": Language.typescript,
    ".rs": Language.rust,
    ".go": Language.go,
    ".java": Language.java,
}


def language_from_paths(paths: Iterable[str]) -> Language:
    """Dominant language across the raw paths a session touched (best-effort heuristic)."""
    counts: dict[Language, int] = {}
    for p in paths:
        ext = Path(p).suffix.lower()
        lang = _EXT_LANGUAGE.get(ext)
        if lang is not None:
            counts[lang] = counts.get(lang, 0) + 1
        elif ext:
            counts[Language.other] = counts.get(Language.other, 0) + 1
    if not counts:
        return Language.unknown
    return max(counts, key=lambda k: counts[k])


# Keyword -> task type, matched against the (local-only) first user prompt. Order matters:
# the first matching bucket wins.
_TASK_KEYWORDS: list[tuple[TaskType, tuple[str, ...]]] = [
    (TaskType.bugfix, ("fix", "bug", "broken", "crash", "error", "regression")),
    (TaskType.refactor, ("refactor", "clean up", "cleanup", "rename", "simplify")),
    (TaskType.docs, ("document", "docs", "readme", "comment", "docstring")),
    (TaskType.feature, ("add", "implement", "build", "create", "support", "feature")),
]


def task_type_from_prompt(prompt: str | None) -> TaskType:
    """Classify a session from its first user prompt (heuristic; the text never leaves here)."""
    if not prompt:
        return TaskType.unknown
    low = prompt.lower()
    for task, keywords in _TASK_KEYWORDS:
        if any(k in low for k in keywords):
            return task
    return TaskType.other


@runtime_checkable
class Adapter(Protocol):
    """Reads one agent's logs. Implementations must open files read-only and never raise on
    unrecognised input (unknown lines are counted, not fatal)."""

    agent_name: str

    def default_log_root(self) -> Path:
        """Where this agent writes its logs on this machine."""
        ...

    def discover(self, root: Path | None = None) -> Iterator[Path]:
        """Yield session-log sources under `root` (or the default root)."""
        ...

    def parse_sessions(self, path: Path) -> Iterator[Session]:
        """Parse a source into one or more normalised `Session`s.

        Most agents write one session per file; opencode stores many sessions in one SQLite DB,
        hence the iterator. Single-session adapters yield exactly one.
        """
        ...


def discover_adapters() -> list[Adapter]:
    """All adapters available for local ingest."""
    from observatory.adapters.claude_code import ClaudeCodeAdapter
    from observatory.adapters.codex import CodexAdapter
    from observatory.adapters.gemini import GeminiAdapter
    from observatory.adapters.opencode import OpenCodeAdapter

    return [ClaudeCodeAdapter(), CodexAdapter(), GeminiAdapter(), OpenCodeAdapter()]
