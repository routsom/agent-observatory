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
    """Invariant 4: every fixture must carry the scrubber marker, whatever its format."""
    import sqlite3

    fixtures = (
        list(FIXTURES.rglob("*.jsonl"))
        + list(FIXTURES.rglob("*.json"))
        + list(FIXTURES.rglob("*.db"))
    )
    assert fixtures, "no fixtures found"
    for fx in fixtures:
        if fx.suffix == ".jsonl":  # first line is the marker object
            with fx.open(encoding="utf-8") as fh:
                obj = json.loads(fh.readline().strip())
            assert isinstance(obj, dict) and "_observatory_scrubbed" in obj, fx
        elif fx.suffix == ".json":  # top-level marker key
            obj = json.loads(fx.read_text(encoding="utf-8"))
            assert isinstance(obj, dict) and "_observatory_scrubbed" in obj, fx
        else:  # SQLite: a _meta marker row
            con = sqlite3.connect(f"file:{fx}?mode=ro", uri=True)
            try:
                row = con.execute(
                    "SELECT value FROM _meta WHERE key = '_observatory_scrubbed'"
                ).fetchone()
            finally:
                con.close()
            assert row is not None, fx


_CLIENT_ID = "11111111-1111-1111-1111-111111111111"


def _payload_from_fixture(fixtures_dir: Path):  # type: ignore[no-untyped-def]
    from observatory.adapters import ClaudeCodeAdapter

    session = ClaudeCodeAdapter().parse_file(
        fixtures_dir / "claude_code" / "synthetic-1.0.0" / "basic.jsonl"
    )
    return build_payload([session], agent=Agent.claude_code, window="all", client_id=_CLIENT_ID)


def test_payload_forbids_unexpected_fields() -> None:
    """Invariant 1: the payload model rejects any field not on the allowlist."""
    with pytest.raises(ValidationError):
        SharePayload(
            client_id=_CLIENT_ID,
            submission_id=_CLIENT_ID,
            generated_on="2026-01-01",  # type: ignore[arg-type]
            agent=Agent.claude_code,
            window="30d",
            aggregates=[],
            prompt="leaked!",  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        MetricAggregate(
            cli_version="1.0.0",
            model_id="claude-opus-4-8",
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


# Every string that may travel must match one of these content-free shapes (SPEC.md §6).
_ALLOWED_STRING_PATTERNS = [
    re.compile(r"^[a-z0-9_]+$"),  # enum members, metric names, method
    re.compile(r"^[A-Za-z0-9._-]{1,64}$"),  # cli_version / model_id tokens
    re.compile(r"^[0-9a-f-]{36}$"),  # client_id / submission_id (UUID)
    re.compile(r"^(all|\d+[hdw])$"),  # window
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),  # generated_on date
]


def test_payload_contains_only_numbers_and_constrained_strings(fixtures_dir: Path) -> None:
    """Invariant 1: every string that travels is categorical/constrained - no free text leaks."""
    payload = _payload_from_fixture(fixtures_dir)
    dumped = payload.model_dump(mode="json")

    def check(value: object) -> None:
        if isinstance(value, str):
            assert any(p.match(value) for p in _ALLOWED_STRING_PATTERNS), value
        elif isinstance(value, dict):
            for v in value.values():
                check(v)
        elif isinstance(value, list):
            for v in value:
                check(v)
        else:
            assert value is None or isinstance(value, (int, float, bool))

    check(dumped)


def test_text_metric_names_never_appear_in_payload(fixtures_dir: Path) -> None:
    """SPEC.md §7: local-only text metrics must never leak into the share payload."""
    from observatory.metrics import TEXT_METRICS

    payload = _payload_from_fixture(fixtures_dir)
    blob = json.dumps(payload.model_dump(mode="json"))
    for name in TEXT_METRICS:
        assert name not in blob, name


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
    payload = build_payload([session], agent=Agent.claude_code, window="all", client_id=_CLIENT_ID)
    assert rep.aggregates and payload.aggregates  # pipeline ran with sockets blocked
