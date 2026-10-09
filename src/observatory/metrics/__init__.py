"""Structural behaviour metrics. Pure functions: a `Session` in, a number out, no I/O."""

from observatory.metrics.structural import (
    METRICS,
    MetricFn,
    api_calls_per_user_turn,
    blind_edit_rate,
    interrupts_per_1k_tool_calls,
    read_edit_ratio,
    rewrite_share,
    thinking_depth_proxy,
)
from observatory.metrics.text import TEXT_METRICS, TextMetricFn

__all__ = [
    "METRICS",
    "TEXT_METRICS",
    "MetricFn",
    "TextMetricFn",
    "api_calls_per_user_turn",
    "blind_edit_rate",
    "interrupts_per_1k_tool_calls",
    "read_edit_ratio",
    "rewrite_share",
    "thinking_depth_proxy",
]
