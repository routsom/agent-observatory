# Security & Privacy Policy

Agent Observatory is built around a single promise: **only numbers leave your machine, and only
if you opt in.** Privacy issues are treated as security issues.

## Reporting a vulnerability

Please report suspected vulnerabilities - especially anything that could cause user data to leak
off the machine - privately via GitHub's [security advisories](https://github.com/routsom/agent-observatory/security/advisories/new)
rather than a public issue. We aim to acknowledge reports within a few days.

Examples of what we consider a privacy/security bug:

- Any path by which prompts, code, file paths, project names, thinking text, or tool arguments
  could reach the network or the share payload.
- The analyzer writing to an agent's log directory, or opening logs non-read-only.
- A fixture committed to the repository that contains unscrubbed real log content.
- A statistical result published by the server below the k-anonymity threshold.

## Guarantees enforced by tests

These are verified in CI and must never be weakened (see `tests/test_guards.py`):

- `src/observatory/share/client.py` is the **only** module in `src/observatory` permitted to
  import an HTTP library.
- The share payload model uses `extra="forbid"`; every string field is an enum or a
  pattern-constrained token. A test walks a built payload and rejects any free text.
- Local-only text metrics can never appear in the payload.
- Sharing is off by default; `observatory share --dry-run` prints byte-for-byte what would be sent.
- The server publishes a cross-user cell only when at least `MIN_USERS` (5) distinct, anonymous
  clients contributed.

## Anonymity model

Shared payloads carry a random `client_id` (UUIDv4, generated once and stored locally) with no
personal information; its only purpose is to weight users equally and deduplicate submissions.
See `SPEC.md` §6.
