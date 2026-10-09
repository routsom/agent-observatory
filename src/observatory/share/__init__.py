"""Opt-in sharing. Phase 1 builds the payload and the --dry-run path only; `client.py` (the sole
module permitted to touch the network) is a stub until phase 2."""

from observatory.share.payload import MetricAggregate, SharePayload, build_payload

__all__ = ["MetricAggregate", "SharePayload", "build_payload"]
