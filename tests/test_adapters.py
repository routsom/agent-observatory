"""Adapter tests: multi-version fixture coverage (exit gate), robustness to garbage input
(invariant 5), assistant dedup, and read-only access (invariant 3)."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from observatory.adapters import ClaudeCodeAdapter, CodexAdapter
from observatory.adapters.base import Adapter
from observatory.schema import Agent


def _versions(agent_dir: Path) -> list[str]:
    return sorted(p.name for p in agent_dir.iterdir() if p.is_dir())


def test_three_cli_versions_per_agent(fixtures_dir: Path) -> None:
    """Exit gate: at least three CLI-version fixtures per agent."""
    assert len(_versions(fixtures_dir / "claude_code")) >= 3
    assert len(_versions(fixtures_dir / "codex")) >= 3


@pytest.mark.parametrize(
    "adapter,sub",
    [(ClaudeCodeAdapter(), "claude_code"), (CodexAdapter(), "codex")],
)
def test_every_fixture_parses_with_correct_version(
    adapter: Adapter, sub: str, fixtures_dir: Path
) -> None:
    root = fixtures_dir / sub
    for version_dir in root.iterdir():
        if not version_dir.is_dir():
            continue
        for jsonl in version_dir.glob("*.jsonl"):
            session = adapter.parse_file(jsonl)
            # Dir name is the CLI version (hand-authored dirs may carry a "synthetic-" prefix).
            assert version_dir.name.endswith(session.cli_version)
            assert session.unknown_events == 0  # known formats parse cleanly


def test_claude_dedup_drops_duplicate_assistant(fixtures_dir: Path) -> None:
    """The synthetic fixture contains a duplicated (message.id, requestId) line that must not be
    double-counted."""
    s = ClaudeCodeAdapter().parse_file(
        fixtures_dir / "claude_code" / "synthetic-1.0.0" / "basic.jsonl"
    )
    api_calls = sum(1 for e in s.events if e.role.value == "assistant_api_call")
    assert api_calls == 6  # seven assistant lines, one is a duplicate


def test_parsers_never_crash_on_garbage(tmp_path: Path) -> None:
    """Unknown/garbage lines are counted, not fatal (invariant 5)."""
    bad = tmp_path / "garbage.jsonl"
    bad.write_text(
        '{"_observatory_scrubbed": "9.9.9"}\n'
        "this is not json\n"
        "{}\n"
        '{"type": "totally-unknown-type", "foo": 1}\n'
        "[1, 2, 3]\n"
        '{"type": "assistant", "requestId": "r", "message": {"id": "m", "content": []}}\n',
        encoding="utf-8",
    )
    for adapter in (ClaudeCodeAdapter(), CodexAdapter()):
        s = adapter.parse_file(bad)
        assert s.unknown_events >= 2  # the non-json line and the unknown type at minimum


def test_claude_discover_filters_and_sorts(tmp_path: Path) -> None:
    proj = tmp_path / "projects" / "-encoded-path"
    proj.mkdir(parents=True)
    (proj / "b.jsonl").write_text("{}\n")
    (proj / "a.jsonl").write_text("{}\n")
    (proj / "note.txt").write_text("ignore me")
    found = list(ClaudeCodeAdapter().discover(tmp_path / "projects"))
    assert [p.name for p in found] == ["a.jsonl", "b.jsonl"]


def test_adapters_open_files_read_only(fixtures_dir: Path) -> None:
    """Parsing must not modify the log file (invariant 3): mtime is unchanged."""
    jsonl = fixtures_dir / "claude_code" / "synthetic-1.0.0" / "basic.jsonl"
    before = jsonl.stat().st_mtime_ns
    ClaudeCodeAdapter().parse_file(jsonl)
    assert jsonl.stat().st_mtime_ns == before
    # and the file is not world/owner-writable as a side effect
    assert not (jsonl.stat().st_mode & stat.S_IWOTH)


def test_agents_are_correct(fixtures_dir: Path) -> None:
    cc = ClaudeCodeAdapter().parse_file(
        fixtures_dir / "claude_code" / "synthetic-1.0.0" / "basic.jsonl"
    )
    cx = CodexAdapter().parse_file(fixtures_dir / "codex" / "0.5.0" / "basic.jsonl")
    assert cc.agent is Agent.claude_code
    assert cx.agent is Agent.codex
