#!/usr/bin/env python3
"""Render a drift report to a terminal-styled SVG for the docs.

Discovers whatever agent logs are on this machine, builds an all-time report, and writes an SVG.
The committed `docs/report.svg` is a sample produced this way; run it on your own logs to refresh.

    python tools/make_report_screenshot.py docs/report.svg [agent]

Pass an optional agent name (e.g. claude_code) to scope the report to one agent, so the CLI-upgrade
comparison stays within a single agent's versions.
"""

from __future__ import annotations

import sys
from pathlib import Path

from observatory.adapters import discover_adapters
from observatory.report import build_report, render_svg


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    only_agent = argv[2] if len(argv) == 3 else None
    sessions = []
    for adapter in discover_adapters():
        if only_agent and adapter.agent_name != only_agent:
            continue
        for path in adapter.discover():
            sessions.extend(adapter.parse_sessions(path))
    if not sessions:
        print("no local agent logs found; nothing to render")
        return 1
    report = build_report(sessions, window="all")
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_svg(report, title="observatory report --window 30d"), encoding="utf-8")
    print(f"wrote {out} ({report.n_sessions} sessions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
