# CLAUDE.md

**Read [AGENTS.md](AGENTS.md) first** — it is the authoritative contributor and agent guide.

Essentials:

- Read-only MCP server over the CIViC GraphQL API: molecular profiles, variants, evidence
  items, assertions. Live calls only; no data snapshot.
- One fixed GraphQL document per tool (`civic_link/queries.py`); callers never send GraphQL.
- Data plane returns plain dicts and raises typed errors; `run_mcp_tool` owns the envelope.
- CIViC errors arrive as HTTP 200 + `errors[]`; pages silently cap at 100 nodes.
- Every upstream call goes through the process-wide `RateLimiter` — respect it in live tests.
- FastMCP 4.x is post-training-cutoff: verify symbols against this repo's own `.venv`.
- Gate: `make ci-local` (serialize it on shared machines). Never `gh release create`.
