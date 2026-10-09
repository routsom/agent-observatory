"""The six core structural metrics (SPEC.md §3).

Every metric is a pure function ``Session -> float | None`` and returns ``None`` when its
denominator is zero (invariant 7: never raise on empty input). No metric performs I/O or inspects
anything agent-specific; it reads only the normalised timeline.
"""

from __future__ import annotations

from collections.abc import Callable

from observatory.schema import EventRole, Session, ToolKind

MetricFn = Callable[[Session], float | None]


def _edit_calls(session: Session) -> list[str | None]:
    """Ordered ``target`` fingerprints of every edit tool call."""
    return [c.target for c in session.tool_calls() if c.kind is ToolKind.edit]


def read_edit_ratio(session: Session) -> float | None:
    """count(read calls) / count(edit calls). None if the session made no edits."""
    reads = sum(1 for c in session.tool_calls() if c.kind is ToolKind.read)
    edits = sum(1 for c in session.tool_calls() if c.kind is ToolKind.edit)
    if edits == 0:
        return None
    return reads / edits


def blind_edit_rate(session: Session) -> float | None:
    """Fraction of edit calls whose target had no prior read/edit earlier in the session.

    A target with no fingerprint (path unknown) is treated as blind. None if no edits.
    """
    seen: set[str | None] = set()
    total = 0
    blind = 0
    for call in session.tool_calls():
        if call.kind is ToolKind.read:
            seen.add(call.target)
        elif call.kind is ToolKind.edit:
            total += 1
            if call.target is None or call.target not in seen:
                blind += 1
            seen.add(call.target)
    if total == 0:
        return None
    return blind / total


def interrupts_per_1k_tool_calls(session: Session) -> float | None:
    """1000 * interrupts / tool calls. None if the session made no tool calls."""
    tool_calls = len(session.tool_calls())
    if tool_calls == 0:
        return None
    interrupts = sum(1 for e in session.events if e.role is EventRole.interrupt)
    return 1000.0 * interrupts / tool_calls


def rewrite_share(session: Session) -> float | None:
    """Fraction of edit calls whose target was already edited earlier in the session.

    A target with no fingerprint cannot be matched, so it never counts as a rewrite. None if no
    edits.
    """
    edited: set[str] = set()
    total = 0
    rewrites = 0
    for target in _edit_calls(session):
        total += 1
        if target is not None and target in edited:
            rewrites += 1
        if target is not None:
            edited.add(target)
    if total == 0:
        return None
    return rewrites / total


def thinking_depth_proxy(session: Session) -> float | None:
    """Mean thinking-``signature`` length over assistant calls that had one. **Proxy only.**

    This measures the length of the opaque signature string, not reasoning quality. None if no
    assistant call carried a thinking signature (e.g. every Codex session).
    """
    lens = [
        e.thinking_signature_len for e in session.events if e.thinking_signature_len is not None
    ]
    if not lens:
        return None
    return sum(lens) / len(lens)


def api_calls_per_user_turn(session: Session) -> float | None:
    """count(assistant API calls) / count(user turns). None if there were no user turns."""
    user_turns = sum(1 for e in session.events if e.role is EventRole.user_turn)
    if user_turns == 0:
        return None
    api_calls = sum(1 for e in session.events if e.role is EventRole.assistant_api_call)
    return api_calls / user_turns


# Stable registry: name -> function. Used by the report and (future) payload so a metric is
# defined in exactly one place.
METRICS: dict[str, MetricFn] = {
    "read_edit_ratio": read_edit_ratio,
    "blind_edit_rate": blind_edit_rate,
    "interrupts_per_1k_tool_calls": interrupts_per_1k_tool_calls,
    "rewrite_share": rewrite_share,
    "thinking_depth_proxy": thinking_depth_proxy,
    "api_calls_per_user_turn": api_calls_per_user_turn,
}
