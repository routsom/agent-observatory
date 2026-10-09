"""`observatory` command-line interface (typer).

Phase 1 commands:
  * ``ingest``  - read agent logs into the local DuckDB history (read-only on the logs).
  * ``report``  - print a personal drift report for a window (terminal or HTML).
  * ``share``   - ``--dry-run`` prints the exact numbers-only payload; sending is phase 2.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from observatory.adapters import discover_adapters
from observatory.report import build_report, render_html, render_terminal
from observatory.schema import Agent, Session
from observatory.share import build_payload
from observatory.store import History

app = typer.Typer(
    add_completion=False,
    help="Local, privacy-first quality-drift analyzer for coding agents.",
    no_args_is_help=True,
)
_console = Console()


def _load_sessions(agent: str | None, root: Path | None) -> list[Session]:
    sessions: list[Session] = []
    for adapter in discover_adapters():
        if agent and adapter.agent_name != agent:
            continue
        for path in adapter.discover(root):
            sessions.append(adapter.parse_file(path))
    return sessions


@app.command()
def ingest(
    agent: str | None = typer.Option(None, help="Only this agent (claude_code | codex)."),
    root: Path | None = typer.Option(None, help="Override the log root (for testing)."),
    db: Path | None = typer.Option(None, help="History DB path."),
) -> None:
    """Parse agent logs on disk and upsert them into local history (idempotent)."""
    sessions = _load_sessions(agent, root)
    with History(db) as history:
        n = history.upsert(sessions)
        total = history.count()
    _console.print(f"Ingested [cyan]{n}[/cyan] sessions; history now holds [cyan]{total}[/cyan].")


@app.command()
def report(
    window: str = typer.Option("30d", help="Window, e.g. 30d, 12h, 2w, or 'all'."),
    html_out: Path | None = typer.Option(
        None, "--html", help="Write a static HTML report to this path instead of the terminal."
    ),
    db: Path | None = typer.Option(None, help="History DB path."),
) -> None:
    """Show the personal drift report for a window."""
    with History(db) as history:
        sessions = history.query(window)
    rep = build_report(sessions, window=window)
    if html_out is not None:
        html_out.write_text(render_html(rep), encoding="utf-8")
        _console.print(f"Wrote HTML report to [cyan]{html_out}[/cyan].")
    else:
        _console.print(render_terminal(rep))


@app.command()
def share(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the exact payload that WOULD be sent; send nothing."
    ),
    agent: Agent = typer.Option(Agent.claude_code, help="Which agent's aggregates to package."),
    window: str = typer.Option("30d", help="Window, e.g. 30d, 12h, 2w, or 'all'."),
    db: Path | None = typer.Option(None, help="History DB path."),
) -> None:
    """Build the aggregate share payload. Phase 1 supports only --dry-run."""
    if not dry_run:
        _console.print(
            "[yellow]Sharing is off by default and not implemented in phase 1.[/yellow] "
            "Use [bold]--dry-run[/bold] to see exactly what would be sent."
        )
        raise typer.Exit(code=2)
    with History(db) as history:
        sessions = [s for s in history.query(window) if s.agent == agent]
    rep = build_report(sessions, window=window)
    payload = build_payload(rep, agent=agent)
    # Byte-for-byte what would be sent (invariant 2): stable key order, nothing else.
    typer.echo(json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
