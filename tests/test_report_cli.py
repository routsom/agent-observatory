"""Report building/rendering and the end-to-end CLI flow (ingest -> report -> share --dry-run)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from observatory.cli import app
from observatory.report import build_report, render_html, render_svg, render_terminal
from observatory.schema import Agent, Event, EventRole, Session, ToolCall, ToolKind

runner = CliRunner()


def _edit_session(sid: str, *, blind: bool, version: str, days_ago: float) -> Session:
    # A "careful" session reads before editing; a "blind" one edits an unread file.
    calls = []
    if not blind:
        calls.append(ToolCall(name="Read", kind=ToolKind.read, target="f"))
    calls.append(ToolCall(name="Edit", kind=ToolKind.edit, target="f"))
    return Session(
        session_id=sid,
        agent=Agent.claude_code,
        cli_version=version,
        started_at=datetime.now(UTC) - timedelta(days=days_ago),
        events=[
            Event(role=EventRole.user_turn),
            Event(role=EventRole.assistant_api_call, tool_calls=calls),
        ],
    )


def test_build_report_has_all_metrics_and_counts() -> None:
    sessions = [_edit_session(f"s{i}", blind=False, version="1.0.0", days_ago=i) for i in range(3)]
    rep = build_report(sessions, window="30d")
    assert rep.n_sessions == 3
    assert rep.n_users == 1
    assert {a.metric for a in rep.aggregates} == {
        "read_edit_ratio",
        "blind_edit_rate",
        "interrupts_per_1k_tool_calls",
        "rewrite_share",
        "thinking_depth_proxy",
        "api_calls_per_user_turn",
    }
    for a in rep.aggregates:  # invariant 6: never a bare number
        assert a.window == "30d"
        assert a.method in {"session_bootstrap", "user_bootstrap", "none"}


def test_report_detects_cross_version_blind_edit_shift() -> None:
    # older version: careful; newer version: blind. blind_edit_rate should rise across the upgrade.
    old = [_edit_session(f"o{i}", blind=False, version="1.0.0", days_ago=40 + i) for i in range(4)]
    new = [_edit_session(f"n{i}", blind=True, version="2.0.0", days_ago=1 + i) for i in range(4)]
    rep = build_report(old + new, window="all")
    diffs = {d.metric: d for d in rep.version_diffs}
    be = diffs["blind_edit_rate"]
    assert be.baseline_label == "1.0.0" and be.current_label == "2.0.0"
    assert be.delta is not None and be.delta > 0  # upgrade made editing blinder


def test_renderers_smoke() -> None:
    sessions = [_edit_session("s0", blind=True, version="1.0.0", days_ago=1)]
    rep = build_report(sessions, window="7d")
    text = render_terminal(rep)
    assert "drift report" in text
    assert "blind_edit_rate" in text
    html = render_html(rep)
    assert html.startswith("<!doctype html>")
    assert "proxy" in html  # thinking_depth_proxy is flagged

    svg = render_svg(rep, title="demo")
    assert svg.lstrip().startswith("<svg")
    assert "blind_edit_rate" in svg

    empty = render_terminal(build_report([], window="7d"))
    assert "No sessions" in empty
    assert render_svg(build_report([], window="7d")).lstrip().startswith("<svg")


def test_cli_end_to_end(tmp_path: Path, fixtures_dir: Path) -> None:
    db = tmp_path / "h.duckdb"
    root = fixtures_dir / "claude_code"  # has 3 version dirs with *.jsonl

    res = runner.invoke(app, ["ingest", "--root", str(root), "--db", str(db)])
    assert res.exit_code == 0, res.output
    assert "Ingested" in res.output

    res = runner.invoke(app, ["report", "--window", "all", "--db", str(db)])
    assert res.exit_code == 0, res.output
    assert "drift report" in res.output

    res = runner.invoke(app, ["share", "--dry-run", "--window", "all", "--db", str(db)])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["agent"] == "claude_code"
    assert payload["schema_version"] == 1
    assert payload["client_id"]  # anonymous id from local config
    assert {a["metric"] for a in payload["aggregates"]}  # non-empty, numbers-only by construction


def test_cli_share_without_flags_refuses(tmp_path: Path) -> None:
    db = tmp_path / "h.duckdb"
    res = runner.invoke(app, ["share", "--db", str(db)])
    assert res.exit_code == 2
    assert "off by default" in res.output
