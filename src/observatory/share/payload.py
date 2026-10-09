"""The only thing allowed to leave the machine (SPEC.md §6).

Hard constraints, enforced by tests (invariant 1):

* ``extra="forbid"`` on every model - an unexpected field is a build error, not a silent leak.
* Every string-shaped field is an enum or a constrained value. No free text: no prompts, code,
  paths, project names, thinking text, or tool arguments ever appear here.
* Only numbers and those enums travel.

This module performs no I/O. Building a payload is pure; sending it is phase-2 `client.py`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from observatory.report.drift import DriftReport
from observatory.schema import Agent


class Method(StrEnum):
    user_bootstrap = "user_bootstrap"
    session_bootstrap = "session_bootstrap"
    none = "none"


class MetricAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str  # drawn from the fixed metric registry; validated on build
    value: float | None
    ci_low: float | None
    ci_high: float | None
    method: Method
    n_sessions: int = Field(ge=0)
    n_tool_calls: int = Field(ge=0)
    n_users: int = Field(ge=0)


class SharePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    agent: Agent
    window: str
    aggregates: list[MetricAggregate]


def build_payload(report: DriftReport, *, agent: Agent) -> SharePayload:
    """Project a local report down to the allowlisted aggregate payload.

    Only the current-window aggregates travel. The within-user version diffs stay local in phase 1.
    """
    aggregates = [
        MetricAggregate(
            metric=a.metric,
            value=a.value,
            ci_low=a.ci_low,
            ci_high=a.ci_high,
            method=Method(a.method),
            n_sessions=a.n_sessions,
            n_tool_calls=a.n_tool_calls,
            n_users=a.n_users,
        )
        for a in report.aggregates
    ]
    return SharePayload(agent=agent, window=report.window, aggregates=aggregates)
