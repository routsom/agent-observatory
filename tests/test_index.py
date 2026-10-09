"""Within-user index (SPEC.md §5a): removes per-user baseline; label means recover a known effect.

See `stats/index.py`.
"""

from __future__ import annotations

import math

from observatory.stats import indexed_label_means, within_user_index


def test_within_user_index_removes_offset() -> None:
    # Two users, same shape, different level -> identical deviations.
    out = within_user_index({"A": [1.0, 3.0], "B": [11.0, 13.0]})
    assert out["A"] == [-1.0, 1.0]
    assert out["B"] == [-1.0, 1.0]


def test_within_user_index_skips_empty() -> None:
    out = within_user_index({"A": [], "B": [5.0]})
    assert "A" not in out
    assert out["B"] == [0.0]


def test_indexed_label_means_recovers_effect_despite_offsets() -> None:
    # Each client has a large per-client offset; label Y is +0.5 above label X for everyone.
    per_client = {f"c{i}": {"X": [float(i)], "Y": [i + 0.5]} for i in range(6)}
    labels = indexed_label_means(per_client, n_resamples=300, seed=0)
    # Offsets are removed; symmetric two-label design -> X at -0.25, Y at +0.25, gap 0.5.
    assert labels["Y"].value is not None and labels["X"].value is not None
    assert math.isclose(labels["Y"].value - labels["X"].value, 0.5, abs_tol=1e-9)
    assert labels["Y"].n_users == 6
    assert labels["Y"].method == "user_bootstrap"


def test_indexed_label_shift_is_detected() -> None:
    small = {f"c{i}": {"X": [float(i)], "Y": [i + 0.1]} for i in range(6)}
    big = {f"c{i}": {"X": [float(i)], "Y": [i + 2.0]} for i in range(6)}
    gap_small = indexed_label_means(small, n_resamples=200)["Y"].value
    gap_big = indexed_label_means(big, n_resamples=200)["Y"].value
    assert gap_small is not None and gap_big is not None and gap_big > gap_small
