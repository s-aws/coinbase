# Change Validation Checklist

Reconciled on 2026-10-09. A local test pass is implementation evidence, not
permission to deploy or proof of live Coinbase behavior.

1. Confirm the branch, HEAD, and existing worktree changes; read `AGENTS.md`,
   `agent.md`, and task-relevant context via `ai-context.md`.
2. Review the canonical behavior path and its ID, flat-hierarchy, enum, and lock
   constraints. Preserve existing operator changes.
3. Update living docs, comments, and affected graph semantic evidence to match
   any intentional behavior change. Historical records remain dated history.
4. Run the complete local non-external suite sequentially:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -c tests/pytest.ini tests -m "not external" -v --tb=short
   ```

5. Require exit 0. Report failures honestly; no narrowed selection or unexplained
   retry counts as a pass. The only skip exception is the exact agent/context
   file allowlist in `AGENTS.md`; ordinary documentation changes need the gate.
6. Rebuild/check the graph using `codex_repo_graph/ENTRYPOINT.md`. Review changed
   evidence before updating fingerprints; a successful older report does not
   validate a failed current attempt.
7. Inspect the final diff for unintended behavior, generated artifacts,
   credentials, and unresolved assumptions. Record validation in the handoff.
8. Perform external or live validation only within separately authorized scope
   and verified routing/DB identity; follow `docs/EXTERNAL_TESTING_RUNBOOK.md`.

Focused pytest selections require an explicit user request. Deployment itself
is a separate operator action.
