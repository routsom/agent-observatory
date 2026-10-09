"""Agent Observatory server: ingest API, nightly cross-user aggregation, public dashboard.

Separate package from `observatory` so it may import FastAPI/HTTP freely - the "only client.py
imports HTTP" guard scans `src/observatory` only. It reuses `observatory.share.payload` as the
single source of truth for the ingest contract and `observatory.stats` for identical CIs.
"""

MIN_USERS = 5  # k-anonymity threshold: a cell is published only with >= this many distinct users
