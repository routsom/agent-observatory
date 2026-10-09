# Agent Observatory

A local, privacy-first analyzer for coding-agent session logs. It reads the logs agents already
write to disk (Claude Code, Codex), computes objective behaviour metrics **on your machine**, and
tracks quality drift across agents, models, and CLI versions. Nothing leaves your machine unless
you explicitly opt in - and even then, only numeric aggregates.

See `CLAUDE.md` for the build contract and `SPEC.md` for metric and schema definitions.

## Quickstart

```bash
uv sync --all-extras
uv run observatory ingest                 # read local agent logs into ~/.observatory history
uv run observatory report --window 30d    # personal drift report
uv run observatory share --dry-run        # print the exact numbers-only payload (sends nothing)
```

## Development

```bash
uv run pytest -m "not live"               # offline suite (default) - must always pass
uv run pytest -m live                     # opt-in, reads your real local logs
uv run ruff check . && uv run ruff format --check .
uv run mypy src/observatory
```

## Metrics

`read_edit_ratio`, `blind_edit_rate`, `interrupts_per_1k_tool_calls`, `rewrite_share`,
`thinking_depth_proxy` (a proxy - signature length, not reasoning quality), and
`api_calls_per_user_turn`. Definitions live in `SPEC.md`.

## Privacy

- Only numbers ever leave the machine; the share payload forbids free text by construction.
- Sharing is off by default; `--dry-run` prints byte-for-byte what would be sent.
- Logs are opened read-only; the tool never writes to an agent's directory.

Apache-2.0.
