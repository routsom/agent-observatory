# CLAUDE.md — Agent Observatory

Open-source tool that reads the session logs coding agents write to disk, computes objective
behaviour metrics locally, and (opt-in) shares only numeric aggregates to a public dashboard
that detects quality drift across agents, models and CLI versions.

Design source of truth: `SPEC.md` (schema, metric definitions, payload format). If code and
SPEC.md disagree, stop and ask; do not silently change either.

## Commands

```
uv sync --all-extras
uv run pytest -m "not live"            # offline suite, must always pass
uv run pytest -m live                  # opt-in, touches real local logs
uv run ruff check . && uv run ruff format --check .
uv run mypy src/observatory            # strict
uv run observatory report --window 30d # personal drift report
uv run observatory share --dry-run     # print the exact payload, send nothing
uv run python tools/scrub.py <in.jsonl> <out.jsonl>   # make a fixture from a real log
```

Before saying a task is done: offline tests, ruff and mypy all pass.

## Layout

```
src/observatory/
  adapters/      one module per agent: claude_code.py, codex.py (later gemini.py, opencode.py)
  schema.py      normalised Session / Event models (pydantic)
  metrics/       structural.py (core six), text.py (phase 2, local-only)
  store.py       local DuckDB history (~/.observatory/history.duckdb)
  report/        personal drift report (terminal + HTML)
  share/         payload.py (allowlisted aggregate schema), client.py (only network code)
  stats/         within-user index, upgrade DiD, change-point detection (phase 3)
  cli.py
server/          ingest API + nightly stats job (phase 2+), separate package
tests/fixtures/<agent>/<cli_version>/*.jsonl   scrubbed fixtures only
tools/scrub.py   structure-preserving log scrubber
```

## Log sources (read-only, undocumented formats)

- Claude Code: `~/.claude/projects/<encoded-path>/*.jsonl`. Dedupe assistant messages on
  `(message.id, requestId)` — resumed/branched sessions duplicate them. Thinking text is
  redacted; depth comes from `signature` length (a proxy, always label it as one).
- Codex CLI: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. First line is `session_meta`
  (has `cli_version`). Tool calls pair on `call_id`. Token counts are cumulative per session.
  `turn_aborted` = user interrupt.
- Gemini CLI (`~/.gemini/tmp/<project>/chats/`) and opencode (`~/.local/share/opencode/opencode.db`,
  open read-only) come later.

## Invariants — enforced by tests, never relax them

1. **Only numbers leave the machine.** `share/client.py` is the only module allowed to import an
   HTTP library (a test checks imports). The payload model uses `extra="forbid"`; every string
   field is an enum (agent, cli_version, model_id, effort, task_type, language). No prompts,
   code, paths, project names, thinking text or tool arguments — ever.
2. **Sharing is off by default.** Nothing is sent without explicit opt-in; `--dry-run` must print
   byte-for-byte what would be sent.
3. **Never write to agent directories.** Adapters open files read-only; SQLite in `mode=ro`.
4. **Never commit raw logs.** Fixtures only come from `tools/scrub.py`; a test rejects fixtures
   without the scrubber's marker line.
5. **Parsers never crash on unknown input.** Unknown event types are counted
   (`unknown_events`) and skipped. Each supported CLI version has a fixture.
6. **No bare numbers.** Every reported metric carries its window, n_sessions, n_tool_calls
   (and n_users on the server), a CI, and the method name.
7. **Every metric** has a definition in SPEC.md, a fixture test with a hand-checked expected
   value, and a synthetic-shift test (inject a known change, assert it is detected).
8. **Every statistical method** has a simulation test proving its coverage or false-alarm rate
   on data with a known answer. Aggregates weight users equally; bootstrap resamples users,
   not sessions.
9. **Offline tests never touch the network or real logs.** Real-log tests use the `live` marker.

## Core metrics (definitions live in SPEC.md)

read_edit_ratio · blind_edit_rate · interrupts_per_1k_tool_calls · rewrite_share ·
thinking_depth_proxy · api_calls_per_user_turn. Session context recorded alongside: agent,
cli_version, model_id, effort, session length, salted project fingerprint, language,
task_type (local heuristic), local hour.

## Conventions

- Python 3.11+, uv, pydantic v2, DuckDB, typer for the CLI. Strict typing, no `Any` in public APIs.
- Small pure functions for metrics: events in, number out. No I/O inside metric code.
- Adapters return `schema.Session` objects; nothing downstream knows which agent produced them.
- Prefer adding a fixture over adding a special case.

## Working style

- Use plan mode for anything touching SPEC.md, the payload, or `stats/`.
- Independent adapters can be built in parallel git worktrees.
- When unsure whether something could leak user data, treat it as a leak and ask.

## Current phase: 1 — local analyzer

Scope: Claude Code + Codex adapters, the six core metrics, DuckDB history, `observatory report`.
No network code yet. Exit gate: on the maintainer's own logs, the report reproduces the
direction of the spring-2026 shifts described in anthropics/claude-code#42796, and fixture tests
pass for at least three CLI versions per agent.
