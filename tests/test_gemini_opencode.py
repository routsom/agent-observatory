"""Gemini and opencode adapters: hand-checked fixture values, multi-session DB, robustness."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from observatory.adapters import GeminiAdapter, OpenCodeAdapter
from observatory.metrics import METRICS, TEXT_METRICS
from observatory.schema import Agent

GEMINI_EXPECTED = {
    "read_edit_ratio": 1.0,
    "blind_edit_rate": 0.0,
    "interrupts_per_1k_tool_calls": 500.0,
    "rewrite_share": 0.0,
    "thinking_depth_proxy": 10.0,
    "api_calls_per_user_turn": 3.0,
}
OPENCODE_EXPECTED = {
    "read_edit_ratio": 0.5,
    "blind_edit_rate": 0.0,
    "interrupts_per_1k_tool_calls": 1000 / 3,
    "rewrite_share": 0.5,
    "thinking_depth_proxy": 20.0,
    "api_calls_per_user_turn": 3.0,
}


@pytest.fixture
def gemini_session(fixtures_dir: Path):  # type: ignore[no-untyped-def]
    return GeminiAdapter().parse_file(fixtures_dir / "gemini" / "0.4.1" / "chat.json")


@pytest.fixture
def opencode_sessions(fixtures_dir: Path):  # type: ignore[no-untyped-def]
    return list(
        OpenCodeAdapter().parse_sessions(fixtures_dir / "opencode" / "0.3.0" / "opencode.db")
    )


@pytest.mark.parametrize("name,expected", GEMINI_EXPECTED.items())
def test_gemini_metric_values(gemini_session, name: str, expected: float) -> None:  # type: ignore[no-untyped-def]
    got = METRICS[name](gemini_session)
    assert got is not None and math.isclose(got, expected, rel_tol=1e-9)


def test_gemini_context(gemini_session) -> None:  # type: ignore[no-untyped-def]
    assert gemini_session.agent is Agent.gemini
    assert gemini_session.cli_version == "0.4.1"
    assert gemini_session.task_type.value == "bugfix"
    assert gemini_session.language.value == "python"
    assert gemini_session.unknown_events == 0
    assert math.isclose(TEXT_METRICS["mean_user_turn_chars"](gemini_session), 11.0)


@pytest.mark.parametrize("name,expected", OPENCODE_EXPECTED.items())
def test_opencode_metric_values(opencode_sessions, name: str, expected: float) -> None:  # type: ignore[no-untyped-def]
    s1 = next(s for s in opencode_sessions if s.session_id == "s1")
    got = METRICS[name](s1)
    assert got is not None and math.isclose(got, expected, rel_tol=1e-9)


def test_opencode_db_yields_multiple_sessions(opencode_sessions) -> None:  # type: ignore[no-untyped-def]
    assert {s.session_id for s in opencode_sessions} == {"s1", "s2"}
    for s in opencode_sessions:
        assert s.agent is Agent.opencode
        assert s.cli_version == "0.3.0"
        assert s.unknown_events == 0


def test_opencode_opens_read_only(fixtures_dir: Path) -> None:
    db = fixtures_dir / "opencode" / "0.3.0" / "opencode.db"
    before = db.stat().st_mtime_ns
    list(OpenCodeAdapter().parse_sessions(db))
    assert db.stat().st_mtime_ns == before  # invariant 3: never writes to the log source


def test_gemini_never_crashes_on_bad_json(tmp_path: Path) -> None:
    bad = tmp_path / "chat.json"
    bad.write_text("not valid json", encoding="utf-8")
    s = GeminiAdapter().parse_file(bad)
    assert s.agent is Agent.gemini and s.events == []


def test_gemini_counts_unknown_roles(tmp_path: Path) -> None:
    bad = tmp_path / "chat.json"
    bad.write_text(
        '{"cliVersion": "9.9.9", "messages": ['
        '{"role": "user", "parts": [{"text": "hi"}]},'
        '{"role": "system", "parts": []}]}',
        encoding="utf-8",
    )
    s = GeminiAdapter().parse_file(bad)
    assert s.unknown_events == 1  # the unknown "system" role


def test_opencode_never_crashes_on_non_db(tmp_path: Path) -> None:
    junk = tmp_path / "opencode.db"
    junk.write_text("this is not a sqlite database", encoding="utf-8")
    assert list(OpenCodeAdapter().parse_sessions(junk)) == []
