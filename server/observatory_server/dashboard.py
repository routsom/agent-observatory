"""Render published aggregates to a self-contained static HTML dashboard.

Only k-anonymous published cells are shown (every row carries its n_users and CI), so no
individual user's data is ever exposed. Styling mirrors the local report for consistency.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from observatory_server.analysis import ChangePointRow, DidRow
from observatory_server.store import PublishedCell

_PROXY_METRICS = {"thinking_depth_proxy"}


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _ci_pair(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "n/a"
    return f"[{_fmt(low)}, {_fmt(high)}]"


def _ci(cell: PublishedCell) -> str:
    return _ci_pair(cell.ci_low, cell.ci_high)


def _did_section(dids: Sequence[DidRow]) -> str:
    if not dids:
        return ""
    rows = "\n".join(
        f"<tr><td>{html.escape(d.agent)}</td>"
        f"<td>{html.escape(d.baseline)} &rarr; {html.escape(d.current)}</td>"
        f"<td>{html.escape(d.metric)}</td>"
        f"<td class=num>{_fmt(d.estimate)}</td>"
        f"<td class=num>{html.escape(_ci_pair(d.ci_low, d.ci_high))}</td>"
        f"<td>{html.escape(d.method)}</td>"
        f"<td class=num>{d.n_treated}</td><td class=num>{d.n_control}</td></tr>"
        for d in dids
    )
    return f"""<h2>Upgrade effects (difference-in-differences)</h2>
<table>
 <tr><th>agent</th><th>upgrade</th><th>metric</th><th>effect</th><th>95% CI</th>
 <th>method</th><th>n_treated</th><th>n_control</th></tr>
 {rows}
</table>"""


def _changepoint_section(changes: Sequence[ChangePointRow]) -> str:
    significant = [c for c in changes if c.p_value < 0.05]
    if not significant:
        return ""
    rows = "\n".join(
        f"<tr><td>{html.escape(c.agent)}</td>"
        f"<td>{html.escape(c.cli_version)}</td>"
        f"<td>{html.escape(c.metric)}</td>"
        f"<td>{html.escape(c.change_date or '-')}</td>"
        f"<td class=num>{_fmt(c.pre_mean)} &rarr; {_fmt(c.post_mean)}</td>"
        f"<td class=num>{c.p_value:.3f}</td></tr>"
        for c in significant
    )
    return f"""<h2>Detected change points (p &lt; 0.05)</h2>
<table>
 <tr><th>agent</th><th>cli_version</th><th>metric</th><th>change date</th>
 <th>before &rarr; after</th><th>p</th></tr>
 {rows}
</table>"""


def render_dashboard(
    cells: Sequence[PublishedCell],
    dids: Sequence[DidRow] = (),
    changes: Sequence[ChangePointRow] = (),
) -> str:
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
 h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
 table {{ border-collapse: collapse; width: 100%; }}
 th, td {{ border-bottom: 1px solid #e3e3e3; padding: .4rem .6rem; text-align: left; }}
 td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
 .meta {{ color: #666; }} .proxy {{ color: #a60; font-size: .85em; }}
</style></head><body>
<h1>Agent Observatory - public dashboard</h1>
<p class=meta>Cross-user behaviour metrics, users weighted equally.
 Only k-anonymous cells shown.</p>
{body}
{_did_section(dids)}
{_changepoint_section(changes)}
</body></html>"""
