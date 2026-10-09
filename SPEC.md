# SPEC.md - Agent Observatory

This is the design source of truth. If code and SPEC disagree, stop and reconcile here first
(see `CLAUDE.md`). It defines the normalised schema, the six core metrics, the statistical
methods, and the (phase-2) share payload.

## 1. Normalised schema

Adapters turn each agent's raw session log into a single `Session`. Nothing downstream knows
which agent produced it.

### `ToolCall`
A single tool invocation inside a session.

| field | type | notes |
|---|---|---|
| `name` | `str` | tool name, normalised (e.g. `Read`, `Edit`, `Write`, `Bash`) |
| `kind` | `ToolKind` enum | `read` / `edit` / `other`, derived from `name` (see §2) |
| `target` | `str \| None` | **salted fingerprint** of the file path the call touched, never the raw path |

The raw file path is used only transiently, in-process, to compute `blind_edit_rate` and
`rewrite_share`; it is fingerprinted before it is stored and never persisted or shared.

### `Event`
The dedup-collapsed timeline used by metrics.

| field | type | notes |
|---|---|---|
| `role` | `EventRole` enum | `user_turn` / `assistant_api_call` / `interrupt` / `tool_result` / `other` |
| `tool_calls` | `list[ToolCall]` | tool calls emitted by an `assistant_api_call` |
| `thinking_signature_len` | `int \| None` | summed signature length of thinking blocks on this call (proxy) |

### `Session`
| field | type | notes |
|---|---|---|
| `session_id` | `str` | stable id from the log (dedup/idempotency key) |
| `agent` | `Agent` enum | `claude_code` / `codex` / `gemini` / `opencode` |
| `cli_version` | `str` | reported by the log; `unknown` if absent |
| `model_id` | `str` | normalised model id; `unknown` if mixed/absent |
| `effort` | `Effort` enum | `low`/`medium`/`high`/`unknown` (reasoning effort if the log states it) |
| `project_fingerprint` | `str` | sha256(cwd + per-machine salt), 16 hex chars |
| `language` | `Language` enum | dominant language heuristic from tool targets; `unknown` |
| `task_type` | `TaskType` enum | local heuristic: `feature`/`bugfix`/`refactor`/`docs`/`other`/`unknown` |
| `local_hour` | `int` | 0-23, start of session in local time |
| `started_at` | `datetime` | first event timestamp (UTC) |
| `events` | `list[Event]` | ordered, deduped |
| `unknown_events` | `int` | count of log lines whose type the adapter did not recognise (invariant 5) |

## 2. Tool classification

| `ToolKind` | member tool names |
|---|---|
| `read` | `Read`, `NotebookRead`, Codex `read_file` |
| `edit` | `Edit`, `MultiEdit`, `Write`, `NotebookEdit`, Codex `apply_patch` / `write_file` |
| `other` | everything else (`Bash`, `Grep`, `Glob`, `Task`, ...) |

`tool_calls` on a session = every `ToolCall` across all `assistant_api_call` events.

## 3. Core metrics

All metrics are **pure functions**: a `Session` (or a list of them) in, a number out. No I/O.
Each returns `None` when its denominator is zero rather than raising. Per invariant 7 every
metric has (a) a definition here, (b) a fixture test with a hand-checked value, and (c) a
synthetic-shift test.

| metric | per-session definition | direction of "worse" |
|---|---|---|
| `read_edit_ratio` | `count(read tool calls) / count(edit tool calls)`; `None` if no edits | lower = edits with less reading |
| `blind_edit_rate` | fraction of edit calls whose `target` had **no** prior `read` or `edit` of the same target earlier in the session; `None` if no edits | higher = more editing blind |
| `interrupts_per_1k_tool_calls` | `1000 * count(interrupt events) / count(tool calls)`; `None` if no tool calls | higher = more user course-correction |
| `rewrite_share` | fraction of edit calls whose `target` was **already edited** earlier in the session; `None` if no edits | higher = more churn/rework |
| `thinking_depth_proxy` | mean `thinking_signature_len` over assistant calls that have one; `None` if none | **proxy only** - signature length, not reasoning quality |
| `api_calls_per_user_turn` | `count(assistant_api_call events) / count(user_turn events)`; `None` if no user turns | higher = more model round-trips per human ask |

`thinking_depth_proxy` is always reported with the word "proxy": it measures the length of the
opaque `signature` string on thinking blocks, which correlates loosely with thinking length but
is **not** a measure of reasoning quality. Codex has no thinking signatures, so it is `None` there.

## 4. Session context (recorded, not a metric)

Captured for slicing and for the within-user index: `agent`, `cli_version`, `model_id`, `effort`,
session length (`len(events)`, `count(tool calls)`), `project_fingerprint`, `language`,
`task_type`, `local_hour`. `task_type` and `language` are best-effort local heuristics and are
labelled as such; they are enums so they can live in the (future) payload without leaking text.

## 5. Statistical methods

Reported numbers never stand bare (invariant 6): every reported metric carries its `window`,
`n_sessions`, `n_tool_calls`, a confidence interval, and the `method` name.

- **Aggregation weights users equally.** A metric over many sessions is the mean of per-user
  means, not the mean of sessions, so a heavy user cannot dominate.
- **Bootstrap CI resamples users, not sessions** (invariant 8). `method = "user_bootstrap"`, 2000
  resamples, percentile interval. In phase 1 there is a single local user, so the CI degenerates
  to a per-session bootstrap and is labelled `method = "session_bootstrap"` and widened
  accordingly; the report states n_users = 1.
- **Within-user upgrade comparison** (phase 1, local): for a metric and a split dimension
  (`cli_version` or `model_id`), compare the two most recent values with a bootstrap difference
  CI. This is the local analogue of the server-side difference-in-differences.
- Every method has a simulation test proving its coverage / false-alarm rate on data with a known
  answer (invariant 8).

### 5a. Within-user index (phase 3)

Users have very different baselines (one reads a lot, another edits blind by habit), so a raw
cross-user mean mixes level differences with drift. The **within-user index** re-expresses each
user's value as an *additive deviation from that user's own mean*: `indexed = value - user_mean`.
Aggregating the deviations (again weighting users equally, bootstrapping over users) isolates
change from baseline. Additive, not ratio, so it is stable when a user's mean is near zero.

### 5b. Upgrade difference-in-differences (phase 3, server)

Estimates the effect of a CLI upgrade A->B while subtracting secular drift:

- **Treated** = clients with the metric on *both* A and B; each contributes a paired delta `B - A`.
- **Control** = clients seen on A at two dates straddling the upgrade; each contributes `A_late - A_early`.
- **Estimate** = mean(treated deltas) - mean(control deltas); CI by bootstrapping **over clients**
  (treated and control resampled independently), `method = "did"`.
- **Fallback**: with no usable control arm, report the paired within-upgrader difference and label
  it `method = "paired_first_difference"` so the weaker claim is explicit.

### 5c. Change-point detection (phase 3, server)

Given a date-ordered series of a metric's cross-user aggregate, locate a single level shift with a
**CUSUM** statistic (max absolute cumulative deviation from the series mean) and assess it with a
**permutation test** (the series is shuffled `B` times; p = fraction of shuffles whose statistic
meets or exceeds the observed one). Returns the change index/date, pre/post means, statistic, and p.
Assumption-light and directly testable for false-alarm rate (stationary series) and power (injected
shift).

## 6. Share payload

`share/payload.py` defines the only thing allowed to leave the machine. Constraints enforced by
tests (invariant 1):

- Model uses `extra="forbid"`.
- Every string field is either an enum (`agent`, `effort`, `task_type`, `language`, `method`) or
  a **pattern-constrained** string that carries no content: `cli_version`/`model_id` (version-like
  tokens), `client_id`/`submission_id` (UUIDv4), and `window` (`all` or `\d+[hdw]`). No free text.
- Only numbers and those strings: metric value, CI low/high, n_sessions, n_tool_calls, n_users,
  `generated_on` (a **date**, not a precise timestamp - deliberately coarsened so submission timing
  cannot fingerprint a user). No prompts, code, paths, project names, thinking text, tool args.
- Local-only text metrics (§8) are **never** included; a test asserts their names never appear in
  a built payload.
- Sharing is off by default (§9); `observatory share --dry-run` prints the exact JSON bytes and
  sends nothing. `share/client.py` is the only module in `src/observatory` permitted to import an
  HTTP library.

### Anonymous identity

`client_id` is a random UUIDv4 generated once per machine and stored in
`~/.observatory/config.json`. It contains no personal information; its only purpose is to let the
server weight each user equally and keep only a user's latest submission per
`(agent, cli_version, metric, window)`. `submission_id` is a fresh UUIDv4 per upload, used for
idempotent ingest.

## 7. Local text metrics (local-only, never shared)

Computed on the machine from text the adapters retain locally (user/assistant message lengths,
code-fence presence). They are **never** placed in the share payload and live in their own
`TEXT_METRICS` registry so they cannot leak by construction.

| metric | per-session definition |
|---|---|
| `mean_user_turn_chars` | mean character length of user turns; `None` if no user turns |
| `mean_assistant_chars_per_api_call` | mean assistant text length per API call; `None` if none |
| `code_fence_rate` | fraction of assistant API calls whose text contains a ``` code fence; `None` if none |

Each still follows invariant 7: a definition here, a fixture test with a hand-checked value, and a
synthetic-shift test.

## 8. Server (ingest + nightly aggregation + dashboard)

`server/observatory_server/` is a separate package (it may import FastAPI/HTTP freely; the
"only client.py imports HTTP" guard scans `src/observatory` only).

- **Ingest.** `POST /ingest` validates the body against the *same* `SharePayload` model (single
  source of truth), stores rows in a server DuckDB, is idempotent on `submission_id`, and keeps
  only the latest submission per `(client_id, agent, cli_version, metric, window)`.
- **Nightly aggregation.** For each `(agent, cli_version, metric, window)`: weight clients equally
  (mean of per-client values) and bootstrap **over clients** for the CI, reusing
  `stats.aggregate.bootstrap_over_groups` so client and server compute CIs identically.
- **k-anonymity.** A cell is published only when at least `MIN_USERS = 5` distinct `client_id`s
  contributed; otherwise it is suppressed entirely. The same threshold gates every phase-3 result.
- **Dashboard.** `GET /` serves static HTML rendered from the published aggregates; `GET
  /aggregates` returns them as JSON. No per-user data is ever exposed - only k-anonymous cells.
- **History (phase 3).** Ingest also appends every dated submission to a `submission_history`
  table keyed by `(client_id, agent, cli_version, metric, window, generated_on)` (dedup on
  `submission_id`). Only the phase-3 analysis jobs read it; the dashboard aggregation is unchanged.
- **Analysis (phase 3).** `observatory-server analyze` computes upgrade DiD (§5b) and change points
  (§5c) from history, suppresses any result below `MIN_USERS`, and exposes them at `GET /upgrades`
  and `GET /changepoints`; the dashboard shows a compact section for each.

## 9. Phasing

- **Phase 1 (done):** local analyzer - Claude Code + Codex adapters, the six metrics, DuckDB
  history, `observatory report`, `observatory share --dry-run`. No network client.
- **Phase 2 (done):** opt-in `share/client.py` uploader + consent, the server (§8), and local text
  metrics (§7).
- **Phase 3 (now):** `stats/` within-user index (§5a), upgrade DiD (§5b), and change-point
  detection (§5c), wired into the server over `submission_history`.
