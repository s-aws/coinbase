# Change and Deployment Checklist

Reconciled on 2026-11-26. Automation covers deterministic checks and the
non-destructive launch path. It does not grant deployment authority, perform
code review, reset data, resume trading, or prove live Coinbase behavior.

## 1. Human review boundary

Before invoking automation:

1. Read `AGENTS.md`, `agent.md`, and task-relevant context routed by
   `ai-context.md`.
2. Review the canonical behavior path and its ID, flat-hierarchy, enum, and
   locking constraints.
3. Review the final diff, living documentation, and repository-graph evidence.
4. Commit the reviewed change. Deployment automation requires a clean worktree
   and never commits or pushes Git state.

## 2. Automated release validation

Run:

```bash
./scripts/validate_release.sh
```

The validator:

- reports branch, exact `HEAD`, and local upstream divergence;
- refuses tracked or untracked worktree changes;
- runs the complete local non-external suite through `scripts/run_tests.sh`;
- checks the repository graph without rebuilding or rewriting evidence;
- runs `git diff --check`; and
- proves the worktree remained clean after validation.

It does not run external tests, contact Coinbase, mutate the runtime database,
push commits, or deploy the engine.

## 3. Runtime deployment prerequisites

Set all runtime database and Coinbase credential variables explicitly:

```bash
export COINBASE_DB_HOST="..."
export COINBASE_DB_PORT="..."
export COINBASE_DB_NAME="..."
export COINBASE_DB_USER="..."
export COINBASE_DB_PASSWORD="..."
export COINBASE_API_KEY="..."
export COINBASE_API_SECRET="..."
```

The selected database must be a fresh trading instance. Required runtime
tables may be absent or already provisioned for a retry, but every existing
runtime table must contain zero rows. `market_candle_1m` and `market_tick` are
the only additional public tables allowed; their telemetry rows may be
preserved. Unknown public tables or existing trading state fail closed.

`DISABLE_RECONCILER` must be unset or explicitly false. Deployment always sets
`ENGINE_START_PAUSED=true`. If `DASHBOARD_SERVER_HOST` is absent, the launcher
defaults it to `127.0.0.1`.

## 4. Automated runtime deployment

Run the foreground deployment entry point:

```bash
./scripts/deploy_runtime.sh
```

The launcher:

1. prevents overlapping deployment launchers and refuses an already responding
   engine dashboard;
2. runs `scripts/validate_release.sh`;
3. runs `scripts/bootstrap_runtime_database.sh`, which requires every
   `COINBASE_DB_*` value, verifies connected database/user identity, enforces
   fresh trading state, applies `database.schema`, and verifies all required
   tables;
4. starts the single canonical runtime entry point, `python -m main`, with
   startup admission paused;
5. polls `admin_status` until it proves `PAUSED`, admission closed, no stop in
   progress, no pending startup-pause transition, and zero in-flight work; and
6. remains attached to the engine process and forwards launcher termination to
   the engine's graceful signal path.

The default health endpoint is `ws://127.0.0.1:8765`. Override it when listener
or proxy routing differs:

```bash
export DEPLOYMENT_HEALTHCHECK_URL="ws://127.0.0.1:9000"
export DEPLOYMENT_HEALTH_TIMEOUT_SECONDS="90"
./scripts/deploy_runtime.sh
```

The launcher deliberately does not daemonize. Run it under systemd, a container
runtime, or another foreground-process supervisor for a durable deployment.

For database preparation without launching the engine, use:

```bash
./scripts/bootstrap_runtime_database.sh
```

## 5. Explicitly manual or excluded actions

- `__dangerous_delete_all_tables__.py` is an operator-only destructive reset
  utility. It is never called by deployment automation.
- Resuming from `PAUSED` remains an explicit operator action through the
  existing runtime-admin API/UI after reconciliation evidence is reviewed.
- External or live validation requires separate authorization and verified
  account/routing scope; follow `docs/EXTERNAL_TESTING_RUNBOOK.md`.
- Git commit, push, rollback, database provisioning, DNS/TLS, and service-unit
  installation remain outside these scripts.
- Candle backfill is not part of normal deployment. It remains a best-effort
  post-recreation step of the operator-only destructive reset workflow.

Focused pytest selections require an explicit user request. The automated
release validator always runs the complete local non-external suite.
