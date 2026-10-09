"""Build and render the personal drift report.

A report is (a) the current-window aggregate of each metric, and (b) a within-user comparison of
each metric across the two most recent CLI versions, so a maintainer can see whether an upgrade
moved their own behaviour. Every number is shown with its CI, counts, and method - never bare
(invariant 6).
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from observatory.metrics import METRICS, TEXT_METRICS
from observatory.schema import Session
from observatory.stats import AggregateResult, DiffResult, aggregate, within_user_diff

if TYPE_CHECKING:
    from rich.console import Console

# Metrics whose reported value is an opaque proxy, flagged everywhere they are shown.
_PROXY_METRICS = {"thinking_depth_proxy"}


@dataclass(frozen=True)
class DriftReport:
    window: str
    n_sessions: int
    n_users: int
    aggregates: list[AggregateResult]
    version_diffs: list[DiffResult]
    text_aggregates: list[AggregateResult]  # local-only (SPEC.md §7); never shared


def _two_most_recent_versions(sessions: Sequence[Session]) -> tuple[str, str] | None:
    """The two CLI versions with the most recent sessions, (older, newer)."""
    latest_by_version: dict[str, object] = {}
    for s in sessions:
        key = s.cli_version
        ts = s.started_at
        if ts is None:
            continue
        cur = latest_by_version.get(key)
        if cur is None or ts > cur:  # type: ignore[operator]
            latest_by_version[key] = ts
    ranked = sorted(latest_by_version.items(), key=lambda kv: kv[1], reverse=True)  # type: ignore[arg-type,return-value]
    if len(ranked) < 2:
        return None
    newer, older = ranked[0][0], ranked[1][0]
    return older, newer


def build_report(sessions: Sequence[Session], *, window: str, seed: int = 0) -> DriftReport:
    aggregates = [
        aggregate(sessions, name, fn, window=window, seed=seed) for name, fn in METRICS.items()
    ]

    version_diffs: list[DiffResult] = []
    pair = _two_most_recent_versions(sessions)
    if pair is not None:
        older, newer = pair
        baseline = [s for s in sessions if s.cli_version == older]
        current = [s for s in sessions if s.cli_version == newer]
        for name, fn in METRICS.items():
            version_diffs.append(
                within_user_diff(
                    baseline,
                    current,
                    name,
                    fn,
                    split="cli_version",
                    baseline_label=older,
                    current_label=newer,
                    seed=seed,
                )
            )

    text_aggregates = [
        aggregate(sessions, name, fn, window=window, seed=seed) for name, fn in TEXT_METRICS.items()
    ]

    # Phase 1 runs on a single local user's logs, so n_users is 1 whenever there are sessions.
    return DriftReport(
        window=window,
        n_sessions=len(sessions),
        n_users=1 if sessions else 0,
        aggregates=aggregates,
        version_diffs=version_diffs,
        text_aggregates=text_aggregates,
    )


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _ci(a: AggregateResult | DiffResult) -> str:
    if a.ci_low is None or a.ci_high is None:
        return "n/a"
    return f"[{_fmt(a.ci_low)}, {_fmt(a.ci_high)}]"


def render_terminal(report: DriftReport) -> str:
    """Render the report to a plain-text string (consumed by the CLI)."""
    return _build_console(report).export_text()


def render_svg(report: DriftReport, *, title: str = "observatory report") -> str:
    """Render the report as a terminal-styled SVG (used for docs/screenshots)."""
    return _build_console(report).export_svg(title=title)


def _build_console(report: DriftReport) -> Console:
    from rich.console import Console
    from rich.table import Table

    console = Console(record=True, width=100)
    console.print(
        f"[bold]Agent Observatory[/bold] - drift report  "
        f"window=[cyan]{report.window}[/cyan]  "
        f"n_sessions=[cyan]{report.n_sessions}[/cyan]  "
        f"n_users=[cyan]{report.n_users}[/cyan]"
    )

    if report.n_sessions == 0:
        console.print(
            "[yellow]No sessions in this window. Run `observatory ingest` first.[/yellow]"
        )
        return console

    table = Table(title="Current window", show_lines=False)
    table.add_column("metric")
    table.add_column("value", justify="right")
    table.add_column("95% CI", justify="right")
    table.add_column("method")
    table.add_column("n_sessions", justify="right")
    table.add_column("n_tool_calls", justify="right")
    for a in report.aggregates:
        label = a.metric + (" (proxy)" if a.metric in _PROXY_METRICS else "")
        table.add_row(
            label, _fmt(a.value), _ci(a), a.method, str(a.n_sessions), str(a.n_tool_calls)
        )
    console.print(table)

    if report.version_diffs:
        d0 = report.version_diffs[0]
        dtable = Table(
            title=f"CLI upgrade: {d0.baseline_label} → {d0.current_label} (within your own logs)"
        )
        dtable.add_column("metric")
        dtable.add_column("before", justify="right")
        dtable.add_column("after", justify="right")
        dtable.add_column("Δ", justify="right")
        dtable.add_column("95% CI (Δ)", justify="right")
        dtable.add_column("method")
        for d in report.version_diffs:
            label = d.metric + (" (proxy)" if d.metric in _PROXY_METRICS else "")
            moved = (
                d.ci_low is not None and d.ci_high is not None and (d.ci_low > 0 or d.ci_high < 0)
            )
            delta_str = _fmt(d.delta)
            if moved:
                delta_str = f"[bold]{delta_str}*[/bold]"
            dtable.add_row(label, _fmt(d.baseline), _fmt(d.current), delta_str, _ci(d), d.method)
        console.print(dtable)
        console.print(
            "[dim]* CI excludes zero: a detected shift between versions in your own usage.[/dim]"
        )

    ttable = Table(title="Local text metrics (never shared)")
    ttable.add_column("metric")
    ttable.add_column("value", justify="right")
    ttable.add_column("95% CI", justify="right")
    ttable.add_column("method")
    for a in report.text_aggregates:
        ttable.add_row(a.metric, _fmt(a.value, 1), _ci(a), a.method)
    console.print(ttable)

    return console


def render_html(report: DriftReport) -> str:
    """Render a self-contained static HTML report."""
    rows = "\n".join(
        f"<tr><td>{html.escape(a.metric)}"
        f"{' <span class=proxy>(proxy)</span>' if a.metric in _PROXY_METRICS else ''}</td>"
        f"<td class=num>{_fmt(a.value)}</td>"
        f"<td class=num>{html.escape(_ci(a))}</td>"
        f"<td>{html.escape(a.method)}</td>"
        f"<td class=num>{a.n_sessions}</td>"
        f"<td class=num>{a.n_tool_calls}</td></tr>"
        for a in report.aggregates
    )
    diff_section = ""
    if report.version_diffs:
        d0 = report.version_diffs[0]
        drows = "\n".join(
            f"<tr><td>{html.escape(d.metric)}</td>"
            f"<td class=num>{_fmt(d.baseline)}</td>"
            f"<td class=num>{_fmt(d.current)}</td>"
            f"<td class=num>{_fmt(d.delta)}</td>"
            f"<td class=num>{html.escape(_ci(d))}</td>"
            f"<td>{html.escape(d.method)}</td></tr>"
            for d in report.version_diffs
        )
        diff_section = f"""
        <h2>CLI upgrade: {html.escape(d0.baseline_label)} → {html.escape(d0.current_label)}</h2>
        <table>
          <tr><th>metric</th><th>before</th><th>after</th><th>Δ</th><th>95% CI (Δ)</th>
          <th>method</th></tr>
          {drows}
        </table>"""
    return f"""<!doctype html>
<html><head><meta charset=utf-8><title>Agent Observatory - drift report</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 900px;
        color: #1a1a1a; }}
 h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
 table {{ border-collapse: collapse; width: 100%; }}
 th, td {{ border-bottom: 1px solid #e3e3e3; padding: .4rem .6rem; text-align: left; }}
 td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
 .meta {{ color: #666; }} .proxy {{ color: #a60; font-size: .85em; }}
</style></head><body>
<h1>Agent Observatory - drift report</h1>
<p class=meta>window {html.escape(report.window)} · {report.n_sessions} sessions ·
 {report.n_users} user(s)</p>
<table>
 <tr><th>metric</th><th>value</th><th>95% CI</th><th>method</th><th>n_sessions</th>
 <th>n_tool_calls</th></tr>
 {rows}
</table>
{diff_section}
</body></html>"""
