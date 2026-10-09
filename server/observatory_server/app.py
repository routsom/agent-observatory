"""FastAPI ingest API + public dashboard.

`POST /ingest` validates against the same `SharePayload` model the client builds (single source of
truth), so any field outside the allowlist is rejected before it is ever stored. `GET /` serves
the static dashboard; `GET /aggregates` returns the published cells as JSON.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from observatory.share.payload import SharePayload
from observatory_server.dashboard import render_dashboard
from observatory_server.nightly import run_aggregation
from observatory_server.store import ServerStore


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Agent Observatory", version="0.2.0")

    def store() -> ServerStore:
        return ServerStore(db_path)

    @app.post("/ingest")
    def ingest(payload: SharePayload) -> dict[str, object]:
        with store() as s:
            accepted = s.ingest(payload)
        return {"accepted": accepted, "submission_id": payload.submission_id}

    @app.post("/aggregate")
    def aggregate() -> dict[str, int]:
        """Trigger the nightly aggregation on demand (also runnable from the CLI)."""
        with store() as s:
            cells = run_aggregation(s)
        return {"published_cells": len(cells)}

    @app.get("/aggregates")
    def aggregates() -> list[dict[str, object]]:
        with store() as s:
            cells = s.published()
        return [cell.__dict__ for cell in cells]

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        with store() as s:
            cells = s.published()
        return render_dashboard(cells)

    return app


app = create_app()
