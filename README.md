<div align="center">

# Agent Observatory

**A local, privacy-first analyzer for coding-agent session logs.**

Measure how your coding agents actually behave - and catch quality drift across agents, models,
and CLI versions - without a single prompt, path, or line of code ever leaving your machine.

[![CI](https://github.com/routsom/agent-observatory/actions/workflows/ci.yml/badge.svg)](https://github.com/routsom/agent-observatory/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Typed: mypy strict](https://img.shields.io/badge/mypy-strict-blue.svg)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

</div>

---

Coding agents (Claude Code, Codex, Gemini CLI, opencode) already write detailed session logs to
disk. Agent Observatory reads those logs **locally**, turns them into objective behaviour metrics,
and tracks how those metrics drift over time and across CLI/model versions. Sharing is entirely
opt-in, and the only thing that can ever be shared is a small bundle of **numeric aggregates** -
enforced by the type system and by tests.

## Table of contents

- [Why](#why)
- [Features](#features)
- [How it works](#how-it-works)
- [Install](#install)
- [Usage](#usage)
- [Metrics](#metrics)
- [Privacy and security](#privacy-and-security)
- [The optional server](#the-optional-server)
- [Architecture](#architecture)
- [Development](#development)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Why

Agents change under you. A CLI update, a new model, or a reasoning-effort tweak can quietly shift
how much an agent reads before it edits, how often you have to interrupt it, or how much it
rewrites its own work. Those shifts are hard to see one session at a time. Agent Observatory makes
them measurable - first for *you*, locally, and (optionally, anonymously) across everyone who opts
in, so regressions show up as a signal instead of a vibe.

## Features

- **Reads what's already there** - no wrappers, no instrumentation. Four adapters: Claude Code,
  Codex, Gemini CLI, and opencode (read-only SQLite).
- **Six objective structural metrics** plus local-only text metrics, each defined in `SPEC.md`.
- **Honest statistics** - users weighted equally, bootstrap confidence intervals, within-user
  upgrade comparisons, and (server-side) difference-in-differences and change-point detection.
  No bare numbers: every value ships with its window, counts, a CI, and the method name.
- **Local history** in DuckDB and a terminal or HTML drift report.
- **Privacy by construction** - see below. Sharing is off until you explicitly consent.

## How it works

```
agent logs on disk ──> adapters ──> normalised Session ──> metrics ──> DuckDB history
  (read-only)                                                               │
                                                                            ├─> observatory report   (terminal / HTML)
                                                                            └─> share payload (numbers only)
                                                                                     │  opt-in, consented
                                                                                     ▼
                                                               server: ingest ─> nightly aggregation (k-anonymous)
                                                                                     │
                                                                                     ▼
                                                               public dashboard + upgrade DiD + change points
```

## Install

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
git clone https://github.com/routsom/agent-observatory.git
cd agent-observatory
uv sync --all-extras
```

## Usage

```bash
uv run observatory ingest                 # read local agent logs into ~/.observatory history
uv run observatory report --window 30d    # personal drift report (incl. local-only text metrics)
uv run observatory report --window 30d --html report.html   # ... or a static HTML report

uv run observatory share --dry-run        # print the exact numbers-only payload (sends nothing)
uv run observatory share --send           # upload it (off by default; one-time consent prompt)
uv run observatory consent --revoke       # turn sharing back off
```

Logs are discovered automatically from each agent's default location; pass `--agent` to restrict
to one, or `--root` to point at a different directory.

## Metrics

Definitions and the exact formulas live in [`SPEC.md`](SPEC.md). Structural metrics (shareable):

| Metric | What it captures |
|---|---|
| `read_edit_ratio` | How much the agent reads relative to how much it edits |
| `blind_edit_rate` | Share of edits to files it never read first |
| `interrupts_per_1k_tool_calls` | How often you had to course-correct it |
| `rewrite_share` | Share of edits that rework a file it already edited |
| `thinking_depth_proxy` | Mean thinking-signature length (a **proxy**, not reasoning quality) |
| `api_calls_per_user_turn` | Model round-trips per human ask |

Local-only text metrics (`mean_user_turn_chars`, `mean_assistant_chars_per_api_call`,
`code_fence_rate`) are computed on your machine and **never** shared.

## Privacy and security

This is the whole point of the project, so it is enforced by tests, not just documentation
(see [`SECURITY.md`](SECURITY.md) and `tests/test_guards.py`):

- **Only numbers leave the machine.** `share/client.py` is the single module in `src/observatory`
  allowed to import an HTTP library. The payload model forbids unknown fields and every string is
  an enum or a pattern-constrained token - a test walks a built payload and rejects any free text.
- **Sharing is off by default** and requires explicit, informed consent. `--dry-run` prints
  byte-for-byte what would be sent.
- **Logs are read-only.** The tool never writes to an agent's directory; the opencode SQLite DB is
  opened `mode=ro`.
- **No raw logs in the repo.** Fixtures come from `tools/scrub.py` and carry a scrubber marker that
  a test requires.
- **Anonymous and k-anonymous.** Shared data is tagged with a random local `client_id` (no PII);
  the server publishes a cross-user cell only when at least 5 distinct clients contributed.

## The optional server

The public side that aggregates shared payloads is a separate FastAPI + DuckDB package in
[`server/`](server):

```bash
uv run observatory-server serve           # ingest API + public dashboard at http://127.0.0.1:8000
uv run observatory-server aggregate        # nightly cross-user aggregation (k-anonymous)
uv run observatory-server analyze          # upgrade difference-in-differences + change points
```

## Architecture

```
src/observatory/
  adapters/   one module per agent: claude_code, codex, gemini, opencode
  schema.py   normalised Session / Event models (pydantic v2)
  metrics/    structural.py (the core six) + text.py (local-only)
  stats/      aggregation, bootstrap CIs, within-user index, upgrade DiD, change-point detection
  store.py    local DuckDB history (~/.observatory/history.duckdb)
  report/     personal drift report (terminal + HTML)
  share/      payload.py (allowlisted aggregate schema) + client.py (the only network code)
  config.py   anonymous client id + consent
  cli.py
server/observatory_server/   FastAPI ingest API, nightly stats, public dashboard
tools/        scrub.py (structure-preserving scrubber) + make_opencode_fixture.py
tests/        offline suite + opt-in `live` tests; fixtures per agent and CLI version
```

See [`CLAUDE.md`](CLAUDE.md) for the build contract and invariants, and [`SPEC.md`](SPEC.md) for
the authoritative schema, metric, statistics, and payload definitions.

## Development

The full local check is identical to CI and must pass:

```bash
uv run pytest -m "not live"                          # offline suite (default)
uv run pytest -m live                                # opt-in, reads your real local logs
uv run ruff check . && uv run ruff format --check .  # lint + format
uv run mypy src/observatory server                   # strict typing
```

## Roadmap

- [x] **Phase 1** - local analyzer: adapters, six metrics, DuckDB history, `observatory report`.
- [x] **Phase 2** - opt-in sharing, FastAPI server with k-anonymous aggregation, local text metrics.
- [x] **Phase 3** - within-user index, upgrade difference-in-differences, change-point detection.
- [ ] Additional agents and richer dashboard views.

## Contributing

Contributions are very welcome - see [`CONTRIBUTING.md`](CONTRIBUTING.md). The privacy and
statistical invariants in `CLAUDE.md` are enforced by tests and must not be relaxed. By
participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[Apache 2.0](LICENSE).
