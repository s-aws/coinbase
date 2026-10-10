# GenAI Tools Directory

## Purpose

This directory contains debugging and utility source created to understand
system state during investigation and debugging.

Reviewed source is tracked so changes to investigative methods are visible and
revertible. Generated output, browser profiles, database/schema dumps, test
temporary files, captured account data, and credential helpers are ignored.

**Key Point**: These are not production code or design authority. A tracked
file may be historical, stale, destructive, or capable of live exchange or
database mutation. Read the specific file before running it; being tracked is
not approval to execute it.

## When to Create Tools Here

Create debugging tools in this directory when you need to:
- Inspect database state
- Trace data through the system
- Monitor WebSocket messages
- Verify calculations and math
- Check condition evaluation logic
- Validate data integrity

## Current investigation pattern

Status reviewed 2026-10-09. The runtime uses PostgreSQL, not a local SQLite
`coinbase.db` file. Build read-only probes around `database.database.PostgresDB`
and inspect the target identity before querying account or order state. In this
Windows/WSL workspace, set Windows environment variables in the process that
actually launches Windows Python; do not rely on Bash inline overrides crossing
that boundary.

Use narrowly scoped SELECT queries, internal `client_order_id` ownership, and
exact exchange IDs only for exchange evidence. Avoid printing credentials or
captured account data into versioned files. Read the named script before any
execution; the user's authorized scope controls whether a live/DB action may run.

## Source lifecycle

1. Create a focused `debug_<topic>.py` or inspect one relevant existing script.
2. Gather the minimum evidence needed under existing locks and safety boundaries.
3. Record conclusions in comments, current docs, or handoff evidence.
4. Retain/version reusable reviewed source; delete disposable probes.
5. Keep dumps, logs, captured data, credentials, browser profiles, and generated
   output ignored. Never productionize a tool directly from this directory.

Other Markdown files here are historical plans/reports unless their own status
and current source establish otherwise. Their commands are not authorization,
and proposed features may be absent from this checkout. Living navigation is
[genai_data/README.md](../genai_data/README.md); investigation policy is
[DEBUGGING_STRATEGY.md](../genai_data/DEBUGGING_STRATEGY.md).
