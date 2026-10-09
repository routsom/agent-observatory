"""Share client + consent gating. No real network: uploads go through an httpx MockTransport."""

from __future__ import annotations

import json
import socket
from datetime import date
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from observatory.cli import app
from observatory.config import load_config
from observatory.schema import Agent, Session
from observatory.share import build_payload, send

runner = CliRunner()
_CLIENT_ID = "22222222-2222-2222-2222-222222222222"


def _payload() -> object:
    sessions = [Session(session_id="s", agent=Agent.claude_code, cli_version="1.0.0")]
    return build_payload(
        sessions,
        agent=Agent.claude_code,
        window="all",
        client_id=_CLIENT_ID,
        generated_on=date(2026, 1, 1),
    )


def test_send_posts_payload_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"accepted": True})

    result = send(_payload(), endpoint="https://x/ingest", transport=httpx.MockTransport(handler))
    assert result.ok and result.status_code == 200
    assert captured["url"] == "https://x/ingest"
    body = captured["body"]
    assert body["client_id"] == _CLIENT_ID  # type: ignore[index]
    assert body["agent"] == "claude_code"  # type: ignore[index]


def test_send_is_graceful_on_network_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    result = send(_payload(), endpoint="https://x/ingest", transport=httpx.MockTransport(boom))
    assert not result.ok and result.status_code is None
    assert "network error" in result.detail


def test_send_reports_server_rejection() -> None:
    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "bad"})

    result = send(_payload(), endpoint="https://x/ingest", transport=httpx.MockTransport(reject))
    assert not result.ok and result.status_code == 422


def test_cli_share_send_requires_consent(tmp_path: Path) -> None:
    """--send without prior consent and answering 'no' to the prompt shares nothing."""
    db = tmp_path / "h.duckdb"
    res = runner.invoke(app, ["share", "--send", "--db", str(db)], input="n\n")
    assert res.exit_code == 1
    assert "Consent not granted" in res.output
    assert load_config().sharing_consented is False


def test_dry_run_opens_no_socket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _blocked(*a: object, **k: object) -> None:
        raise AssertionError("dry-run must not touch the network")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    db = tmp_path / "h.duckdb"
    res = runner.invoke(app, ["share", "--dry-run", "--db", str(db)])
    assert res.exit_code == 0
    json.loads(res.output)  # valid payload printed, no socket touched
