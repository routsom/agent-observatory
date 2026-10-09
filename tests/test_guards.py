"""Privacy/safety invariants (CLAUDE.md §Invariants). These are the tests the whole design exists
to protect; they must never be relaxed."""

from __future__ import annotations

import ast
import json
import re
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from observatory.report import build_report
from observatory.schema import Agent
from observatory.share import SharePayload, build_payload
from observatory.share.payload import MetricAggregate

SRC = Path(__file__).resolve().parents[1] / "src" / "observatory"
FIXTURES = Path(__file__).parent / "fixtures"

# Modules that can reach the network. `urllib.parse` is fine; `urllib.request`/`urllib.error`
# are not.
_NETWORK_MODULES = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "http.client",
    "urllib.request",
    "urllib.error",
    "socket",
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def test_only_client_may_import_http() -> None:
    """Invariant 1: `share/client.py` is the sole module allowed to import an HTTP library."""
    offenders: dict[str, set[str]] = {}
    for py in SRC.rglob("*.py"):
        if py.relative_to(SRC) == Path("share/client.py"):
            continue
        hits = _imported_modules(py) & _NETWORK_MODULES
        if hits:
            offenders[str(py.relative_to(SRC))] = hits
    assert not offenders, f"network imports outside share/client.py: {offenders}"


def test_every_fixture_carries_scrubber_marker() -> None:
    """Invariant 4: no fixture may exist without the scrubber's marker as its first line."""
    fixtures = list(FIXTURES.rglob("*.jsonl"))
    assert fixtures, "no fixtures found"
    for fx in fixtures:
        with fx.open(encoding="utf-8") as fh:
            first = fh.readline().strip()
        obj = json.loads(first)
        assert isinstance(obj, dict) and "_observatory_scrubbed" in obj, fx


def test_payload_forbids_unexpected_fields() -> None:
    """Invariant 1: the payload model rejects any field not on the allowlist."""
    with pytest.raises(ValidationError):
        SharePayload(
            agent=Agent.claude_code,
            window="30d",
            aggregates=[],
            prompt="leaked!",  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        MetricAggregate(
            metric="read_edit_ratio",
            value=1.0,
            ci_low=0.9,
            ci_high=1.1,
            method="user_bootstrap",  # type: ignore[arg-type]
            n_sessions=1,
            n_tool_calls=1,
            n_users=1,
            path="/secret/project",  # type: ignore[call-arg]
        )


_ALLOWED_STRING_RE = re.compile(r"^[a-z0-9_]+$")  # enum members, metric names
_WINDOW_RE = re.compile(r"^(all|\d+[hdw])$")


def test_payload_contains_only_numbers_and_enums() -> None:
    """Invariant 1: every string that travels is categorical - no free text can leak."""
    rep = build_report([], window="30d")
    payload = build_payload(rep, agent=Agent.claude_code)
    dumped = payload.model_dump(mode="json")

    def check(value: object) -> None:
        if isinstance(value, str):
            assert _ALLOWED_STRING_RE.match(value) or _WINDOW_RE.match(value), value
        elif isinstance(value, dict):
            for v in value.values():
                check(v)
        elif isinstance(value, list):
            for v in value:
                check(v)
        else:
            assert value is None or isinstance(value, (int, float, bool))

    check(dumped)


def test_analysis_pipeline_makes_no_network_calls(
    fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invariant 9: the offline analysis path never opens a socket."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline code attempted a network connection")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    from observatory.adapters import ClaudeCodeAdapter

    session = ClaudeCodeAdapter().parse_file(
        fixtures_dir / "claude_code" / "synthetic-1.0.0" / "basic.jsonl"
    )
    rep = build_report([session], window="all")
    payload = build_payload(rep, agent=Agent.claude_code)
    assert payload.aggregates  # pipeline ran end-to-end with sockets blocked
