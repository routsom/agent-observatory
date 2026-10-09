"""Network client - the ONLY module in ``src/observatory`` permitted to import an HTTP library
(invariant 1).

Sharing is off by default and gated on explicit consent (handled in the CLI); this module just
performs the upload once asked. It never raises on a network/HTTP failure - a failed share must
never crash the tool - and it sends exactly the bytes of the allowlisted `SharePayload`.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from observatory.share.payload import SharePayload

_TIMEOUT = 10.0


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status_code: int | None
    detail: str


def send(
    payload: SharePayload,
    *,
    endpoint: str,
    transport: httpx.BaseTransport | None = None,
) -> SendResult:
    """POST the payload's JSON to ``endpoint``. ``transport`` is injectable for tests.

    Returns a `SendResult`; it does not raise on connection or HTTP errors.
    """
    body = payload.model_dump(mode="json")
    try:
        with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
            response = client.post(endpoint, json=body)
    except httpx.HTTPError as exc:
        return SendResult(ok=False, status_code=None, detail=f"network error: {exc}")

    if response.is_success:
        return SendResult(ok=True, status_code=response.status_code, detail="shared")
    return SendResult(
        ok=False,
        status_code=response.status_code,
        detail=f"server rejected submission ({response.status_code})",
    )
