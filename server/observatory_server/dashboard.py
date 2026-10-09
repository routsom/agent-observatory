"""Render published aggregates to a self-contained static HTML dashboard.

Only k-anonymous published cells are shown (every row carries its n_users and CI), so no
individual user's data is ever exposed. Styling mirrors the local report for consistency.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from observatory_server.store import PublishedCell

_PROXY_METRICS = {"thinking_depth_proxy"}


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _ci(cell: PublishedCell) -> str:
    if cell.ci_low is None or cell.ci_high is None:
        return "n/a"
    return f"[{_fmt(cell.ci_low)}, {_fmt(cell.ci_high)}]"


def render_dashboard(cells: Sequence[PublishedCell]) -> str:
    if not cells:
        body = (
            "<p class=meta>No aggregates have met the k-anonymity threshold yet. "
            "Cells are published only once enough distinct users contribute.</p>"
        )
    else:
        rows = "\n".join(
            f"<tr><td>{html.escape(c.agent)}</td>"
            f"<td>{html.escape(c.cli_version)}</td>"
            f"<td>{html.escape(c.metric)}"
            f"{' <span class=proxy>(proxy)</span>' if c.metric in _PROXY_METRICS else ''}</td>"
            f"<td class=num>{_fmt(c.value)}</td>"
            f"<td class=num>{html.escape(_ci(c))}</td>"
            f"<td class=num>{c.n_users}</td>"
            f"<td>{html.escape(c.method)}</td></tr>"
            for c in cells
        )
        body = f"""<table>
 <tr><th>agent</th><th>cli_version</th><th>metric</th><th>value</th><th>95% CI</th>
 <th>n_users</th><th>method</th></tr>
 {rows}
</table>"""
    return f"""<!doctype html>
<html><head><meta charset=utf-8><title>Agent Observatory - public dashboard</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 960px;
        color: #1a1a1a; }}
 h1 {{ font-size: 1.4rem; }}
 table {{ border-collapse: collapse; width: 100%; }}
 th, td {{ border-bottom: 1px solid #e3e3e3; padding: .4rem .6rem; text-align: left; }}
 td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
 .meta {{ color: #666; }} .proxy {{ color: #a60; font-size: .85em; }}
</style></head><body>
<h1>Agent Observatory - public dashboard</h1>
<p class=meta>Cross-user behaviour metrics, users weighted equally.
 Only k-anonymous cells shown.</p>
{body}
</body></html>"""
