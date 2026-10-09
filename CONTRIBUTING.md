# Contributing to Agent Observatory

Thanks for your interest in improving Agent Observatory. This project has a high bar for
**privacy** and **statistical honesty**, so most of the guidance below is about protecting those.

## Ground rules

Read [`SPEC.md`](SPEC.md) first - it is the source of truth for the schema, metrics, statistics,
and the share payload. If code and `SPEC.md` disagree, that is a bug; open an issue rather than
silently changing either. The invariants in [`CLAUDE.md`](CLAUDE.md) are enforced by tests and
must never be relaxed. In particular:

1. **Only numbers leave the machine.** `src/observatory/share/client.py` is the only module in
   `src/observatory` allowed to import an HTTP library. The share payload forbids free text.
2. **Sharing is off by default** and requires explicit opt-in consent.
3. **Never write to an agent's log directory.** Adapters open files read-only.
4. **Never commit raw logs.** Fixtures are produced by `tools/scrub.py` (or, for opencode, by
   `tools/make_opencode_fixture.py`) and carry a scrubber marker that a test checks for.
5. **Parsers never crash on unknown input** - unknown lines are counted, not fatal.
6. **No bare numbers** - every reported metric carries its window, counts, a CI, and the method.
7. **Every metric** has a definition in `SPEC.md`, a fixture test with a hand-checked value, and a
   synthetic-shift test.
8. **Every statistical method** has a simulation test proving its coverage or false-alarm rate.

## Development setup

```bash
uv sync --all-extras
```

The full local check (identical to CI) must pass before you open a PR:

```bash
uv run pytest -m "not live"                          # offline suite
uv run ruff check . && uv run ruff format --check .  # lint + format
uv run mypy src/observatory server                   # strict typing
```

`uv run pytest -m live` is opt-in and reads your real local agent logs; it never runs in CI.

## Adding a metric

1. Define it in `SPEC.md` (formula + direction of "worse").
2. Implement it as a pure function in `src/observatory/metrics/` and register it.
3. Add a fixture test with a hand-checked expected value, and a synthetic-shift test.
4. If (and only if) it is safe to share, make sure it flows through the allowlisted payload; if it
   is local-only, keep it in the `TEXT_METRICS` registry so it can never leak.

## Adding an agent adapter

Adapters live in `src/observatory/adapters/` and return normalised `schema.Session` objects -
nothing downstream knows which agent produced a session. Open files read-only, count unknown input
rather than raising, and add a scrubbed fixture per supported CLI version. See `codex.py` (jsonl),
`gemini.py` (json), and `opencode.py` (SQLite) for the three source shapes.

## Pull requests

- Keep PRs focused; match the surrounding code's style and comment density.
- Use plain dashes, not em dashes.
- Describe the change and how you verified it. CI runs the full gate on Python 3.11 and 3.12.
