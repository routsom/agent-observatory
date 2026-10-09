"""Server ingest API: validates against the shared payload model, idempotent on submission_id."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from observatory.schema import Agent
from observatory.share.payload import MetricAggregate, SharePayload
from observatory_server.app import create_app


def _payload(client_id: str, submission_id: str, value: float = 0.5) -> dict[str, object]:
    payload = SharePayload(
        client_id=client_id,
        submission_id=submission_id,
        generated_on=date(2026, 1, 1),
        agent=Agent.claude_code,
        window="30d",
        aggregates=[
            MetricAggregate(
                cli_version="2.0.0",
                model_id="claude-opus-4-8",
                metric="read_edit_ratio",
                value=value,
                ci_low=None,
                ci_high=None,
                method="session_bootstrap",  # type: ignore[arg-type]
                n_sessions=3,
                n_tool_calls=30,
                n_users=1,
            )
        ],
    )
    return payload.model_dump(mode="json")


def test_ingest_accepts_valid_payload(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "srv.duckdb"))
    res = client.post("/ingest", json=_payload(str(uuid.uuid4()), str(uuid.uuid4())))
    assert res.status_code == 200
    assert res.json()["accepted"] is True


def test_ingest_rejects_extra_fields(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "srv.duckdb"))
    body = _payload(str(uuid.uuid4()), str(uuid.uuid4()))
    body["prompt"] = "leaked free text"  # not on the allowlist
    res = client.post("/ingest", json=body)
    assert res.status_code == 422  # pydantic extra="forbid" rejects it before storage


def test_ingest_is_idempotent_on_submission_id(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "srv.duckdb"))
    sub = str(uuid.uuid4())
    body = _payload(str(uuid.uuid4()), sub)
    first = client.post("/ingest", json=body)
    second = client.post("/ingest", json=body)
    assert first.json()["accepted"] is True
    assert second.json()["accepted"] is False  # same submission_id ignored
