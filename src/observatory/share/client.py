"""Network client - the ONLY module permitted to import an HTTP library (invariant 1).

Phase 1 ships no network code. This module is a deliberate, empty home so the import-guard test
has exactly one allowed location to point at; the real uploader arrives in phase 2.
"""

from __future__ import annotations

from observatory.share.payload import SharePayload


def send(payload: SharePayload, *, endpoint: str) -> None:  # pragma: no cover - phase 2
    """Upload a payload. Not implemented until phase 2."""
    raise NotImplementedError(
        "Sharing is not implemented in phase 1. Use `observatory share --dry-run` to inspect the "
        "exact payload; nothing leaves your machine."
    )
