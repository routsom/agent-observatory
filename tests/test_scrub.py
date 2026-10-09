"""tools/scrub.py: proves the scrubber removes free text while preserving the structure metrics
need (signature length, same-file identity, dedup id relationships)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRUB_PATH = Path(__file__).resolve().parents[1] / "tools" / "scrub.py"
_spec = importlib.util.spec_from_file_location("scrub", _SCRUB_PATH)
assert _spec and _spec.loader
scrub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scrub)


RAW = [
    {
        "type": "user",
        "version": "1.2.3",
        "cwd": "/Users/secret/project",
        "message": {"content": "my secret prompt about ACME Corp"},
    },
    {
        "type": "assistant",
        "requestId": "req-123",
        "message": {
            "id": "msg-1",
            "model": "claude-opus-4-8",
            "content": [
                {
                    "type": "thinking",
                    "thinking": "secret private reasoning",
                    "signature": "abcdefghij",
                },
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Edit",
                    "input": {
                        "file_path": "/Users/secret/project/app.py",
                        "old_string": "password=123",
                        "new_string": "password=456",
                    },
                },
            ],
        },
    },
    {"type": "user", "message": {"content": "[Request interrupted by user]"}},
]

SECRETS = ("secret prompt", "ACME", "private reasoning", "password", "app.py", "/Users/secret")


def test_scrub_preserves_structure_and_removes_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OBSERVATORY_SCRUB_SALT", "unit-salt")
    raw = tmp_path / "raw.jsonl"
    raw.write_text("\n".join(json.dumps(o) for o in RAW), encoding="utf-8")
    out = tmp_path / "scrubbed.jsonl"

    # re-import module-level salt by re-execing is overkill; scrub reads env per call site at
    # import. Call main in a subprocess-free way by resetting its salt.
    scrub._SALT = b"unit-salt"  # noqa: SLF001

    assert scrub.main(["scrub.py", str(raw), str(out)]) == 0
    lines = out.read_text(encoding="utf-8").splitlines()

    marker = json.loads(lines[0])
    assert marker == {"_observatory_scrubbed": "1.2.3"}

    blob = "\n".join(lines)
    for secret in SECRETS:
        assert secret not in blob, secret

    assistant = json.loads(lines[2])
    blocks = assistant["message"]["content"]
    thinking = next(b for b in blocks if b["type"] == "thinking")
    assert len(thinking["signature"]) == 10  # length preserved
    assert set(thinking["signature"]) == {"x"}
    assert thinking["thinking"] == ""

    tool = next(b for b in blocks if b["type"] == "tool_use")
    assert tool["name"] == "Edit"  # tool name kept
    assert tool["input"]["file_path"].startswith("/scrubbed/")  # path hashed, not raw

    # categorical fields survive; interrupt marker survives verbatim
    assert assistant["message"]["model"] == "claude-opus-4-8"
    assert "[Request interrupted by user]" in blob


def test_scrub_same_path_hashes_identically(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OBSERVATORY_SCRUB_SALT", "unit-salt")
    scrub._SALT = b"unit-salt"  # noqa: SLF001
    raw = tmp_path / "raw.jsonl"
    raw.write_text(
        "\n".join(
            json.dumps(o)
            for o in [
                {"type": "x", "version": "1.0.0", "a": {"file_path": "/p/a.py"}},
                {"type": "x", "b": {"file_path": "/p/a.py"}},
                {"type": "x", "c": {"file_path": "/p/b.py"}},
            ]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.jsonl"
    scrub.main(["scrub.py", str(raw), str(out)])
    rows = [json.loads(line) for line in out.read_text().splitlines()[1:]]
    assert rows[0]["a"]["file_path"] == rows[1]["b"]["file_path"]  # same file -> same token
    assert rows[0]["a"]["file_path"] != rows[2]["c"]["file_path"]  # different file -> different
