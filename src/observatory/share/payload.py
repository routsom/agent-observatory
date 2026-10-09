"""The only thing allowed to leave the machine (SPEC.md §6).

Hard constraints, enforced by tests (invariant 1):

* ``extra="forbid"`` on every model - an unexpected field is a build error, not a silent leak.
* Every string-shaped field is an enum or a **pattern-constrained** value carrying no content.
  No free text: no prompts, code, paths, project names, thinking text, or tool arguments.
* Only numbers, those strings, and a coarsened date travel.

Aggregates are sliced by ``cli_version`` so the server can compare versions. This module performs
no I/O; building a payload is pure. Sending it is `client.py`.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from observatory.metrics import METRICS
from observatory.schema import Agent, Session
from observatory.stats import aggregate

# Pattern-constrained string shapes. None of these can carry free text.
_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_VERSION = r"^[A-Za-z0-9._-]{1,64}$"  # cli_version / model_id tokens
_METRIC = r"^[a-z0-9_]{1,64}$"
_WINDOW = r"^(all|\d+[hdw])$"


class Method(StrEnum):
    user_bootstrap = "user_bootstrap"
    session_bootstrap = "session_bootstrap"
    none = "none"


class MetricAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cli_version: str = Field(pattern=_VERSION)
    model_id: str = Field(pattern=_VERSION)
    metric: str = Field(pattern=_METRIC)
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
    client_id: str = Field(pattern=_UUID)
    submission_id: str = Field(pattern=_UUID)
    generated_on: date  # coarsened to a date on purpose (see SPEC.md §6)
    agent: Agent
    window: str = Field(pattern=_WINDOW)
    aggregates: list[MetricAggregate]


def _dominant_model(sessions: Sequence[Session]) -> str:
    counts: Counter[str] = Counter(s.model_id for s in sessions)
    return counts.most_common(1)[0][0] if counts else "unknown"


def build_payload(
    sessions: Sequence[Session],
    *,
    agent: Agent,
    window: str,
    client_id: str,
    submission_id: str | None = None,
    generated_on: date | None = None,
    seed: int = 0,
) -> SharePayload:
    """Project the window's sessions down to the allowlisted, version-sliced aggregate payload.

    Sessions are filtered to ``agent`` and grouped by ``cli_version``; each group contributes the
    six structural metrics. Local-only text metrics are intentionally never included.
    """
    mine = [s for s in sessions if s.agent == agent]
    by_version: dict[str, list[Session]] = {}
    for s in mine:
        by_version.setdefault(s.cli_version, []).append(s)

    aggregates: list[MetricAggregate] = []
    for version, group in sorted(by_version.items()):
        model_id = _dominant_model(group)
        for name, fn in METRICS.items():
            agg = aggregate(group, name, fn, window=window, seed=seed)
            aggregates.append(
                MetricAggregate(
                    cli_version=version,
                    model_id=model_id,
                    metric=name,
                    value=agg.value,
                    ci_low=agg.ci_low,
                    ci_high=agg.ci_high,
                    method=Method(agg.method),
                    n_sessions=agg.n_sessions,
                    n_tool_calls=agg.n_tool_calls,
                    n_users=agg.n_users,
                )
            )

    return SharePayload(
        client_id=client_id,
        submission_id=submission_id or str(uuid.uuid4()),
        generated_on=generated_on or date.today(),
        agent=agent,
        window=window,
        aggregates=aggregates,
    )
