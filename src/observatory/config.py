"""Local configuration at ``~/.observatory/config.json``.

Holds the anonymous ``client_id`` (a random UUIDv4 created on first use - no personal information;
see SPEC.md §6), whether the user has consented to sharing (off by default), and the share
endpoint. This module does file I/O only; it never touches the network.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENDPOINT = "https://observatory.example/ingest"


def config_path() -> Path:
    home = Path(os.environ.get("OBSERVATORY_HOME", Path.home() / ".observatory"))
    return home / "config.json"


@dataclass
class Config:
    client_id: str
    sharing_consented: bool = False
    endpoint: str = DEFAULT_ENDPOINT

    def to_dict(self) -> dict[str, object]:
        return {
            "client_id": self.client_id,
            "sharing": {"consented": self.sharing_consented, "endpoint": self.endpoint},
        }


def load_config() -> Config:
    """Load the config, creating it (with a fresh anonymous client_id) on first use."""
    path = config_path()
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        sharing = raw.get("sharing", {})
        cfg = Config(
            client_id=str(raw.get("client_id") or uuid.uuid4()),
            sharing_consented=bool(sharing.get("consented", False)),
            endpoint=str(sharing.get("endpoint", DEFAULT_ENDPOINT)),
        )
        if not raw.get("client_id"):
            save_config(cfg)  # backfill a missing id
        return cfg
    cfg = Config(client_id=str(uuid.uuid4()))
    save_config(cfg)
    return cfg


def save_config(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")


def set_consent(consented: bool) -> Config:
    cfg = load_config()
    cfg.sharing_consented = consented
    save_config(cfg)
    return cfg
