#!/usr/bin/env python3
"""Structure-preserving log scrubber.

Turns a real agent log into a fixture safe to commit: it keeps everything the metrics need
(line/block ``type``s, tool ``name``s, model, version, ``usage``, timestamps, the *length* of
each thinking signature, the dedup relationships between ids, and whether two tool calls touched
the *same* file) while destroying everything sensitive (prompts, code, file paths, thinking text,
tool arguments, project names, git branches).

Guarantees that the test-suite relies on (invariant 4):
  * The first output line is a marker ``{"_observatory_scrubbed": "<version>"}``; a test rejects
    any fixture without it.
  * No raw free text survives: unknown string fields are replaced with ``"scrubbed"``.
  * Ids and paths are re-hashed with a random per-run salt, so equal-in/equal-out relationships
    are preserved without exposing the originals.

Usage:
    python tools/scrub.py <in.jsonl> <out.jsonl>
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any

MARKER_KEY = "_observatory_scrubbed"

# String values under these keys are kept verbatim: they are categorical, not sensitive.
_KEEP_STR_KEYS = {
    "type",
    "role",
    "model",
    "version",
    "cli_version",  # Codex session_meta version token (not sensitive)
    "name",  # tool name
    "stop_reason",
    "stop_sequence",
    "service_tier",
    "speed",
    "inference_geo",
    "userType",
    "entrypoint",
    "permissionMode",
    "mode",
    "promptSource",
    "origin",
    "subtype",
    "status",
    "caller_type",
    MARKER_KEY,
}
# Keys whose string value is an id: re-hash deterministically to preserve dedup relationships.
_ID_KEYS = {
    "id",
    "sessionId",
    "requestId",
    "messageId",
    "uuid",
    "parentUuid",
    "leafUuid",
    "tool_use_id",
    "call_id",
    "promptId",
    "sourceToolAssistantUUID",
    "message_id",
}
# Keys whose string value is a file path: re-hash so same-file comparisons still work.
_PATH_KEYS = {"file_path", "notebook_path", "path", "filePath", "cwd", "filename"}

_INTERRUPT_MARKER = "[request interrupted by user"


def _salt() -> bytes:
    override = os.environ.get("OBSERVATORY_SCRUB_SALT")
    return override.encode() if override else os.urandom(16)


_SALT = _salt()


def _hash(value: str, prefix: str) -> str:
    return prefix + hashlib.sha256(_SALT + value.encode("utf-8", "replace")).hexdigest()[:12]


def _scrub_str(key: str, value: str) -> str:
    if key in _KEEP_STR_KEYS:
        return value
    if key in _ID_KEYS:
        return _hash(value, "id_")
    if key in _PATH_KEYS:
        return _hash(value, "/scrubbed/")
    if key == "signature":
        # preserve only the length - the depth proxy - not the content
        return "x" * len(value)
    if key == "thinking":
        return ""
    # Any remaining free text (prompts, code, tool args, branches, titles): preserve interrupt
    # markers verbatim (a metric depends on them), drop everything else.
    if _INTERRUPT_MARKER in value.lower():
        return value
    return "scrubbed"


def _scrub(key: str, value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_str(key, value)
    if isinstance(value, dict):
        return {k: _scrub(k, v) for k, v in value.items()}
    if isinstance(value, list):
        # list items inherit their parent key's rules (e.g. content blocks)
        return [_scrub(key, item) for item in value]
    return value  # numbers, bools, null kept as-is


def scrub_obj(obj: dict[str, Any]) -> dict[str, Any]:
    return {k: _scrub(k, v) for k, v in obj.items()}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    in_path, out_path = argv[1], argv[2]
    version = "unknown"
    scrubbed: list[str] = []
    with open(in_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if version == "unknown" and isinstance(obj.get("version"), str):
                version = obj["version"]
            if version == "unknown":
                payload = obj.get("payload")
                if isinstance(payload, dict) and isinstance(payload.get("cli_version"), str):
                    version = payload["cli_version"]
            scrubbed.append(json.dumps(scrub_obj(obj), ensure_ascii=False))

    with open(out_path, "w", encoding="utf-8") as out:
        out.write(json.dumps({MARKER_KEY: version}) + "\n")
        for line in scrubbed:
            out.write(line + "\n")
    print(f"scrubbed {len(scrubbed)} lines (version {version}) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
