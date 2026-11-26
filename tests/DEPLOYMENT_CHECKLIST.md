# Change and Deployment Checklist

Reconciled on 2026-11-26. A local test pass is implementation evidence, not
permission to deploy or proof of live Coinbase behavior. Deployment itself is
a separate operator action.

1. Confirm the branch, HEAD, and existing worktree changes; read `AGENTS.md`,
   `agent.md`, and task-relevant context via `ai-context.md`.
2. Review the canonical behavior path and its ID, flat-hierarchy, enum, and lock
   constraints. Preserve existing operator changes.
3. Update living docs, comments, and affected graph semantic evidence to match
   any intentional behavior change. Remove superseded documentation.
4. Run the complete local non-external suite sequentially:

   ```bash
   ./scripts/run_tests.sh
   ```

5. Require exit 0. Report failures honestly; no narrowed selection or
   unexplained retry counts as a pass. The only skip exception is the exact
   agent/context file allowlist in `AGENTS.md`; ordinary documentation changes
   need the gate.
6. Rebuild/check the graph using `codex_repo_graph/ENTRYPOINT.md`. Review
   changed evidence before updating fingerprints; a successful older report
   does not validate a failed current attempt.
7. Inspect the final diff for unintended behavior, generated artifacts,
   credentials, and unresolved assumptions. Record validation in the handoff.
8. Set every runtime `COINBASE_DB_*` value in the launch environment, then
   verify the resolved database target and server identity with a read-only
   query. Do not rely on the local defaults for a deployment.
9. Run the supported additive schema bootstrap against that verified target:

   ```bash
   runtime_db_target="${COINBASE_DB_HOST}:${COINBASE_DB_PORT}/${COINBASE_DB_NAME}"
   ./scripts/bootstrap_runtime_database.sh --confirm-target "${runtime_db_target}"
   ```

   This guarded entry point requires every database variable, verifies the
   connected database identity read-only, invokes `database.schema`, and
   verifies the required tables. It is required for fresh and existing
   databases and must succeed before `main` starts. `main.py` does not create
   or migrate the full schema.
10. Never substitute `__dangerous_delete_all_tables__.py` for step 9. That
    script irreversibly drops every public table and is only for an explicitly
    intended manual reset. After the drop it reuses `database.schema`; it does
    run the existing best-effort Coinbase candle backfill next. Backfill errors
    may leave optional candle history incomplete and do not replace verification
    of the required runtime schema.
11. Start the engine only after the schema bootstrap succeeds:

    ```bash
    ./.venv/bin/python3.14 -m main
    ```

    Confirm the expected `STARTING` to `PAUSED` readiness progression before
    permitting new originating work.
12. Perform external or live validation only within separately authorized
    scope and verified routing/database identity; follow
    `docs/EXTERNAL_TESTING_RUNBOOK.md`.

Focused pytest selections require an explicit user request. Candle backfill is
not part of normal additive schema deployment; it remains a post-recreation
step of the explicitly destructive reset workflow.
