"""Opt-in sharing: build the allowlisted aggregate payload and upload it. `client.py` is the sole
module in `src/observatory` permitted to touch the network."""

from observatory.share.client import SendResult, send
from observatory.share.payload import MetricAggregate, SharePayload, build_payload

__all__ = ["MetricAggregate", "SendResult", "SharePayload", "build_payload", "send"]
