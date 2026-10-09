"""Per-agent adapters. Each turns a raw log into normalised `schema.Session` objects."""

from observatory.adapters.base import Adapter, discover_adapters
from observatory.adapters.claude_code import ClaudeCodeAdapter
from observatory.adapters.codex import CodexAdapter
from observatory.adapters.gemini import GeminiAdapter
from observatory.adapters.opencode import OpenCodeAdapter

__all__ = [
    "Adapter",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "GeminiAdapter",
    "OpenCodeAdapter",
    "discover_adapters",
]
