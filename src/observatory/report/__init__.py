"""Personal drift report: compute aggregates + within-user comparisons, render them."""

from observatory.report.drift import (
    DriftReport,
    build_report,
    render_html,
    render_svg,
    render_terminal,
)

__all__ = ["DriftReport", "build_report", "render_html", "render_svg", "render_terminal"]
