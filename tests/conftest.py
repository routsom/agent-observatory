"""Shared test configuration.

A fixed salt makes path fingerprints deterministic across a run, and pointing OBSERVATORY_HOME at
a temp dir guarantees the offline suite never reads or writes the real ~/.observatory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Must be set before any adapter imports compute a fingerprint.
os.environ["OBSERVATORY_SALT"] = "test-salt"

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSERVATORY_HOME", str(tmp_path / "observatory_home"))
    monkeypatch.setenv("OBSERVATORY_SALT", "test-salt")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
