"""Opt-in live tests (``pytest -m live``). These read the maintainer's REAL local agent logs, so
they are never part of the offline suite and never run in CI (invariant 9)."""

from __future__ import annotations

import pytest

from observatory.adapters import discover_adapters
from observatory.report import build_report

pytestmark = pytest.mark.live


def test_real_logs_parse_without_crashing() -> None:
    sessions = []
    for adapter in discover_adapters():
        for path in list(adapter.discover())[:25]:  # cap for speed
            sessions.append(adapter.parse_file(path))
    if not sessions:
        pytest.skip("no local agent logs found on this machine")
    # The parser must never crash and should recognise the vast majority of each log.
    for s in sessions:
        assert s.session_id
        total_lines = len(s.events) + s.unknown_events
        if total_lines:
            assert s.unknown_events / total_lines < 0.2  # <20% unrecognised


def test_report_on_real_logs() -> None:
    sessions = []
    for adapter in discover_adapters():
        for path in adapter.discover():
            sessions.append(adapter.parse_file(path))
    if not sessions:
        pytest.skip("no local agent logs found on this machine")
    rep = build_report(sessions, window="all")
    assert rep.n_sessions == len(sessions)
    assert len(rep.aggregates) == 6
