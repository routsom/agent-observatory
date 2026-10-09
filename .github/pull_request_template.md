## Summary

<!-- What does this change and why? Link any issue. -->

## How I verified

<!-- Commands run and their result. -->

- [ ] `uv run pytest -m "not live"` passes
- [ ] `uv run ruff check . && uv run ruff format --check .` clean
- [ ] `uv run mypy src/observatory server` clean

## Invariants

- [ ] No new network imports outside `share/client.py`
- [ ] Share payload still carries only numbers + enums (no free text)
- [ ] New metrics/methods have a hand-checked fixture test and a shift/simulation test
- [ ] No raw logs committed (fixtures carry the scrubber marker)
