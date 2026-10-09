"""Per-agent adapters. Each turns a raw log into normalised `schema.Session` objects."""

from observatory.adapters.base import Adapter, discover_adapters
from observatory.adapters.claude_code import ClaudeCodeAdapter
from observatory.adapters.codex import CodexAdapter

__all__ = ["Adapter", "ClaudeCodeAdapter", "CodexAdapter", "discover_adapters"]
