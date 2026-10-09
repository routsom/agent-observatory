"""`observatory-server` CLI: run the API or the nightly aggregation."""

from __future__ import annotations

from pathlib import Path

import typer

from observatory_server.nightly import run_aggregation
from observatory_server.store import ServerStore

app = typer.Typer(add_completion=False, help="Agent Observatory server.", no_args_is_help=True)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
) -> None:
    """Run the ingest API + dashboard with uvicorn."""
    import uvicorn

    uvicorn.run("observatory_server.app:app", host=host, port=port)


@app.command()
def aggregate(
    db: Path | None = typer.Option(None, help="Server DB path."),
) -> None:
    """Run the nightly cross-user aggregation (k-anonymous publishing)."""
    with ServerStore(db) as store:
        cells = run_aggregation(store)
    typer.echo(f"Published {len(cells)} k-anonymous cells.")


if __name__ == "__main__":
    app()
