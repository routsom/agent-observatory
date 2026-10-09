"""Local-only text metrics (SPEC.md §7).

These read text-derived features the adapters retain locally (message lengths, code-fence
presence). They are **never** shared: `build_payload` draws only from the structural `METRICS`
registry, and a test asserts these names never appear in a payload. Like the structural metrics,
each is a pure function returning ``None`` on an empty denominator.
"""

from __future__ import annotations

from collections.abc import Callable

from observatory.schema import EventRole, Session

TextMetricFn = Callable[[Session], float | None]


def mean_user_turn_chars(session: Session) -> float | None:
    """Mean character length of user turns. None if there were no user turns."""
    lens = [
        e.user_text_len
        for e in session.events
        if e.role is EventRole.user_turn and e.user_text_len is not None
    ]
    if not lens:
        return None
    return sum(lens) / len(lens)


def mean_assistant_chars_per_api_call(session: Session) -> float | None:
    """Mean assistant text length per API call. None if no assistant call carried text."""
    lens = [
        e.assistant_text_len
        for e in session.events
        if e.role is EventRole.assistant_api_call and e.assistant_text_len is not None
    ]
    if not lens:
        return None
    return sum(lens) / len(lens)


def code_fence_rate(session: Session) -> float | None:
    """Fraction of assistant API calls whose text contains a ``` code fence. None if none known."""
    flags = [
        e.has_code_fence
        for e in session.events
        if e.role is EventRole.assistant_api_call and e.has_code_fence is not None
    ]
    if not flags:
        return None
    return sum(1 for f in flags if f) / len(flags)


# Separate registry from the structural METRICS so text metrics cannot leak into the payload.
TEXT_METRICS: dict[str, TextMetricFn] = {
    "mean_user_turn_chars": mean_user_turn_chars,
    "mean_assistant_chars_per_api_call": mean_assistant_chars_per_api_call,
    "code_fence_rate": code_fence_rate,
}
