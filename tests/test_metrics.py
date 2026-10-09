"""Per-metric tests (invariant 7): a hand-checked value on a fixture, plus a synthetic-shift test
that injects a known change and asserts the metric moves in the right direction."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from observatory.adapters import ClaudeCodeAdapter, CodexAdapter
from observatory.metrics import METRICS
from observatory.schema import (
    Agent,
    Event,
    EventRole,
    Session,
    ToolCall,
    ToolKind,
)


@pytest.fixture
def claude_basic(fixtures_dir: Path) -> Session:
    return ClaudeCodeAdapter().parse_file(
        fixtures_dir / "claude_code" / "synthetic-1.0.0" / "basic.jsonl"
    )


@pytest.fixture
def codex_basic(fixtures_dir: Path) -> Session:
    return CodexAdapter().parse_file(fixtures_dir / "codex" / "0.5.0" / "basic.jsonl")


# --- hand-checked values (computed by hand from the fixtures; see SPEC.md §3) ---

CLAUDE_EXPECTED = {
    "read_edit_ratio": 2 / 3,
    "blind_edit_rate": 1 / 3,
    "interrupts_per_1k_tool_calls": 1000 / 6,
    "rewrite_share": 1 / 3,
    "thinking_depth_proxy": 15.0,
    "api_calls_per_user_turn": 3.0,
}

CODEX_EXPECTED = {
    "read_edit_ratio": 1.0,
    "blind_edit_rate": 0.0,
    "interrupts_per_1k_tool_calls": 500.0,
    "rewrite_share": 0.0,
    "thinking_depth_proxy": None,
    "api_calls_per_user_turn": 1.0,
}


@pytest.mark.parametrize("name,expected", CLAUDE_EXPECTED.items())
def test_claude_fixture_values(claude_basic: Session, name: str, expected: float) -> None:
    got = METRICS[name](claude_basic)
    assert got is not None
    assert math.isclose(got, expected, rel_tol=1e-9)


@pytest.mark.parametrize("name,expected", CODEX_EXPECTED.items())
def test_codex_fixture_values(codex_basic: Session, name: str, expected: float | None) -> None:
    got = METRICS[name](codex_basic)
    if expected is None:
        assert got is None
    else:
        assert got is not None and math.isclose(got, expected, rel_tol=1e-9)


def test_empty_session_metrics_are_none() -> None:
    """A session with no tool calls / edits / turns yields None, never a crash (invariant 7)."""
    s = Session(session_id="empty", agent=Agent.claude_code)
    for fn in METRICS.values():
        assert fn(s) is None


# --- synthetic-shift tests: inject a known change, assert it is detected ---


def _call(kind: ToolKind, target: str | None) -> ToolCall:
    return ToolCall(name=kind.value, kind=kind, target=target)


def _assistant(calls: list[ToolCall], sig: int | None = None) -> Event:
    return Event(role=EventRole.assistant_api_call, tool_calls=calls, thinking_signature_len=sig)


def test_shift_read_edit_ratio() -> None:
    low = Session(
        session_id="a",
        agent=Agent.claude_code,
        events=[
            _assistant([_call(ToolKind.read, "f"), _call(ToolKind.edit, "f")]),
        ],
    )
    high = Session(
        session_id="b",
        agent=Agent.claude_code,
        events=[
            _assistant([_call(ToolKind.read, "f")] * 5 + [_call(ToolKind.edit, "f")]),
        ],
    )
    assert METRICS["read_edit_ratio"](high) > METRICS["read_edit_ratio"](low)


def test_shift_blind_edit_rate() -> None:
    careful = Session(
        session_id="a",
        agent=Agent.claude_code,
        events=[
            _assistant([_call(ToolKind.read, "f"), _call(ToolKind.edit, "f")]),
        ],
    )
    blind = Session(
        session_id="b",
        agent=Agent.claude_code,
        events=[
            _assistant([_call(ToolKind.edit, "g")]),
        ],
    )
    assert METRICS["blind_edit_rate"](blind) > METRICS["blind_edit_rate"](careful)


def test_shift_interrupts() -> None:
    calm = Session(
        session_id="a",
        agent=Agent.claude_code,
        events=[
            _assistant([_call(ToolKind.other, None)] * 10),
        ],
    )
    interrupted = Session(
        session_id="b",
        agent=Agent.claude_code,
        events=[
            _assistant([_call(ToolKind.other, None)] * 10),
            Event(role=EventRole.interrupt),
            Event(role=EventRole.interrupt),
        ],
    )
    assert METRICS["interrupts_per_1k_tool_calls"](interrupted) > METRICS[
        "interrupts_per_1k_tool_calls"
    ](calm)


def test_shift_rewrite_share() -> None:
    fresh = Session(
        session_id="a",
        agent=Agent.claude_code,
        events=[
            _assistant([_call(ToolKind.edit, "f"), _call(ToolKind.edit, "g")]),
        ],
    )
    churny = Session(
        session_id="b",
        agent=Agent.claude_code,
        events=[
            _assistant([_call(ToolKind.edit, "f")] * 4),
        ],
    )
    assert METRICS["rewrite_share"](churny) > METRICS["rewrite_share"](fresh)


def test_shift_thinking_depth_proxy() -> None:
    shallow = Session(session_id="a", agent=Agent.claude_code, events=[_assistant([], sig=100)])
    deep = Session(session_id="b", agent=Agent.claude_code, events=[_assistant([], sig=900)])
    assert METRICS["thinking_depth_proxy"](deep) > METRICS["thinking_depth_proxy"](shallow)


def test_shift_api_calls_per_user_turn() -> None:
    efficient = Session(
        session_id="a",
        agent=Agent.claude_code,
        events=[
            Event(role=EventRole.user_turn),
            _assistant([]),
        ],
    )
    chatty = Session(
        session_id="b",
        agent=Agent.claude_code,
        events=[
            Event(role=EventRole.user_turn),
            _assistant([]),
            _assistant([]),
            _assistant([]),
            _assistant([]),
        ],
    )
    assert METRICS["api_calls_per_user_turn"](chatty) > METRICS["api_calls_per_user_turn"](
        efficient
    )
