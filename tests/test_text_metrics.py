"""Local-only text metrics (SPEC.md §7, invariant 7): hand-checked fixture values + a
synthetic-shift test per metric."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from observatory.adapters import ClaudeCodeAdapter, CodexAdapter
from observatory.metrics import TEXT_METRICS
from observatory.schema import Agent, Event, EventRole, Session


@pytest.fixture
def claude_basic(fixtures_dir: Path) -> Session:
    return ClaudeCodeAdapter().parse_file(
        fixtures_dir / "claude_code" / "synthetic-1.0.0" / "basic.jsonl"
    )


@pytest.fixture
def codex_basic(fixtures_dir: Path) -> Session:
    return CodexAdapter().parse_file(fixtures_dir / "codex" / "0.5.0" / "basic.jsonl")


# Hand-checked: claude fixture has two user turns of 13 chars each; assistant blocks carry no text.
CLAUDE_EXPECTED = {
    "mean_user_turn_chars": 13.0,
    "mean_assistant_chars_per_api_call": 0.0,
    "code_fence_rate": 0.0,
}
# Codex fixture: one user turn "fix the bug" (11), one assistant message "scrubbed" (8).
CODEX_EXPECTED = {
    "mean_user_turn_chars": 11.0,
    "mean_assistant_chars_per_api_call": 8.0,
    "code_fence_rate": 0.0,
}


@pytest.mark.parametrize("name,expected", CLAUDE_EXPECTED.items())
def test_claude_text_values(claude_basic: Session, name: str, expected: float) -> None:
    got = TEXT_METRICS[name](claude_basic)
    assert got is not None and math.isclose(got, expected, rel_tol=1e-9)


@pytest.mark.parametrize("name,expected", CODEX_EXPECTED.items())
def test_codex_text_values(codex_basic: Session, name: str, expected: float) -> None:
    got = TEXT_METRICS[name](codex_basic)
    assert got is not None and math.isclose(got, expected, rel_tol=1e-9)


def test_text_metrics_none_on_empty() -> None:
    s = Session(session_id="e", agent=Agent.claude_code)
    for fn in TEXT_METRICS.values():
        assert fn(s) is None


def test_shift_mean_user_turn_chars() -> None:
    short = Session(
        session_id="a",
        agent=Agent.claude_code,
        events=[Event(role=EventRole.user_turn, user_text_len=10)],
    )
    long = Session(
        session_id="b",
        agent=Agent.claude_code,
        events=[Event(role=EventRole.user_turn, user_text_len=500)],
    )
    assert TEXT_METRICS["mean_user_turn_chars"](long) > TEXT_METRICS["mean_user_turn_chars"](short)


def test_shift_mean_assistant_chars() -> None:
    terse = Session(
        session_id="a",
        agent=Agent.claude_code,
        events=[Event(role=EventRole.assistant_api_call, assistant_text_len=20)],
    )
    verbose = Session(
        session_id="b",
        agent=Agent.claude_code,
        events=[Event(role=EventRole.assistant_api_call, assistant_text_len=2000)],
    )
    key = "mean_assistant_chars_per_api_call"
    assert TEXT_METRICS[key](verbose) > TEXT_METRICS[key](terse)


def test_shift_code_fence_rate() -> None:
    rare = Session(
        session_id="a",
        agent=Agent.claude_code,
        events=[
            Event(role=EventRole.assistant_api_call, has_code_fence=False),
            Event(role=EventRole.assistant_api_call, has_code_fence=False),
        ],
    )
    frequent = Session(
        session_id="b",
        agent=Agent.claude_code,
        events=[
            Event(role=EventRole.assistant_api_call, has_code_fence=True),
            Event(role=EventRole.assistant_api_call, has_code_fence=True),
        ],
    )
    assert TEXT_METRICS["code_fence_rate"](frequent) > TEXT_METRICS["code_fence_rate"](rare)
