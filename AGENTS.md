# AGENTS.md - Session Entry Point

This project runs on **Windows 11 + VS Code**. Linux/bash commands may not work as-is.

## Required Reading (in this order)

1. **[agent.md](agent.md)** - Project-specific constraints (flat hierarchy, never-edit files, testing commands, dashboard architecture)
2. **[docs/agents/README.md](docs/agents/README.md)** - Public agent contracts and ownership entry point
3. **[.agents/ownership.yaml](.agents/ownership.yaml)** - Machine-readable owner map for changed files
4. **[ai-context.md](ai-context.md)** - Index into expanded docs in `genai_data/` when present
5. **`genai_data/`** - Local expanded project docs (`README.md`, `ARCHITECTURE.md`, `ORDER_ID_HANDLING.md`, `TESTING_STRATEGY.md`, and related references) when present
6. **`genai_tools/`** - Temporary debugging scripts and scoped investigation notes

## Hard Constraints (non-negotiable)

- Use `client_order_id` for all internal tracking; use `order_id` only for exchange-native evidence and endpoints that require it. Coinbase cancellation is the explicit exception: use the project wrapper `cancel_order(client_order_id)` because Coinbase accepts our client id for that operation.
  Public rules: `docs/agents/INVARIANTS.md`. Expanded local rules: `genai_data/ORDER_ID_HANDLING.md` when present.
- Single code path per behavior; do not introduce parallel implementations.
- Use enums (`core/enums.py`), not magic strings.
- Respect existing module locks; never bypass thread-safety.
- Stealth order local state must reflect live exchange reality. Do not mark a revealed order hidden, cancelled, or moved unless the corresponding live Coinbase placement has been handled through the existing cancel/move/reconcile path.
- Cancel/re-entry is not general hide-again behavior. It is a narrower policy for no-fill revealed stealth placements: cancel the active placement, hold in policy-cancelled hidden state, then re-enter through the normal reveal path.
- Same-side post-fill retreat is a hidden-order policy only. It may retreat opted-in hidden orders and update their reveal/anchor state, but it must not locally mutate live revealed placements.

## Branch Discipline

- `main` is the primary working branch for this MVP. Do not create durable
  `codex/*`, phase-range, tightening, or continuation branches to carry work
  forward.
- Work directly from the current `origin/main` unless the user explicitly asks
  for a separate branch or pull request.
- If a temporary branch is required for an external workflow, branch from
  current `origin/main`, keep it scoped to the current MVP task, merge it back
  to `main`, push `main`, and delete the local and remote temporary branch as
  part of the same closeout.
- Do not use branches as a backlog, holding area, or place to continue
  non-MVP tightening. Capture follow-up work in the durable goal or an
  operator-visible blocker note instead.
- Before starting new work, if any `codex/*` branch is present locally or on
  origin, verify whether it is merged into `main`. Delete merged branches; if an
  unmerged branch exists, summarize its unique commits and get operator
  direction before building on it.

## Legacy Source Material

- The branch `origin/prod` may contain useful information about the legacy
  system, especially `dashboard_server.py`, `core/order_engine.py`,
  `core/stealth_order_manager.py`, Coinbase wrapper behavior, product/account/
  fill references, and historical regression tests.
- Treat `origin/prod` as source material, not as product authority. Do not
  restore direct dashboard/WebSocket trading authority or bypass Admin API
  authorization, caps, idempotency, audit, and local deployment evidence.
- When a current MVP behavior is unclear, compare the current branch with
  `origin/prod` using non-destructive reads such as `git show origin/prod:<path>`
  or a temporary worktree, then translate only MVP-aligned behavior into the
  backend Admin API/BFF path with focused tests.
- When available, also read
  `C:\coinbase-frontend\docs\ORIGIN_PROD_FEATURE_MVP_MAP.md` before translating
  legacy behavior into Admin MVP work.
- For backend-facing MVP work, record the `origin/prod` files or references
  inspected in the handoff/summary. If no legacy lookup was needed, state why it
  was not applicable.

## P0 - Honest Feedback, Not Engagement Optimization

The user has explicitly opted out of yes-man behavior and validation-seeking responses.
Apply to every non-trivial decision, design proposal, business idea, or "what do you think" question:

- **Lead with the disagreement, the risk, or the unflattering numbers.** Do not bury them under three paragraphs of qualifiers.
- **Compare against industry standards, named competitors, or known-better practices** when those exist.
- **Surface what the user did NOT ask** when it materially affects the answer (regulatory burden, hidden costs, distribution problems, second-order effects).
- **Recommend against** when the evidence supports it. "Don't" is a valid first word.
- **No empty validation** ("Great question!", "That's a really interesting idea!"). No softening preambles. No artificial enthusiasm.
- Honesty is **respect**, not rudeness. Stay professional, stay specific, skip the cushioning.

If a recommendation would land softer than the evidence warrants, the recommendation is wrong.


## Verification Gate Requirements

- Documentation, roadmap, prompt catalog metadata, or agent-instruction-only changes: validate formatting/links or targeted validators as applicable; regression may be skipped.
- Leaf validation scripts, isolated acceptance policies, or narrow tests: run the focused unit/regression tests and validator commands that cover the changed file.
- Workflow-local controller changes: run focused controller/regression tests and live prompt proof when runtime-facing.
- Shared controller, router, formatter, tool-selection, model-routing, mutation, fixture, or approval behavior: run focused tests that cover the changed behavior before completion.
- Runtime-facing behavior: run focused tests, live validation through the relevant localhost ports, AnythingLLM proof when applicable, and both frozen fixture checks when those surfaces are affected.
- Cross-cutting, release-candidate, model-portability, skill-library-scale, or unbounded-blast-radius changes: run the focused checks that cover the changed behavior before ordinary phase completion.
- Full `tests/regression/` is a durable milestone closeout gate, not an ordinary phase gate. The canonical policy is [docs/REGRESSION_PROCESS.md](docs/REGRESSION_PROCESS.md): run it before durable milestone closeout, public/release-candidate handoff, deployment approval/closeout, release-hardening closeout, Admin API/backend association closeout, or explicit user request. The canonical runner validates the regression serial-lane classification before running pytest; regression files that touch shared DB cursors, fixed service ports, process-global state, full FastAPI app imports, or other process-shared/memory-heavy resources must use `pytest.mark.serial`, while false positives require a `parallel-regression: serial-safe` comment with the reason.
- The canonical regression runner first fails before pytest when oversized repo-local runtime artifacts under `runtime_state/` exceed 1 GiB. A `runtime_artifact_preflight_failed` summary is a failed closeout gate; run `python tools/check_runtime_artifacts.py`, preserve evidence, and clean or archive artifacts only after explicit operator cleanup approval. Use `--disable-runtime-artifact-preflight` only for a scoped diagnostic run after preserving artifact evidence.
- The canonical regression runner uses quiet pytest output, short tracebacks, and a Windows memory-pressure guard. Keep quiet output enabled for normal closeout runs so terminal renderers and agent UIs do not retain thousands of test-result lines during long suites. It samples every 5 seconds and aborts on high absolute commit pressure, high commit percentage, high physical-memory pressure, or low available physical memory. Preserve the summary JSON because it includes per-lane peak memory samples and top-process `process_memory_snapshots` captured at each lane's observed peak when the guard is active. A `memory_guard_aborted` summary is a failed closeout gate; run the stale-process checker and the runtime artifact checker, preserve evidence, and split or reduce the offending regression surface before retrying. Do not use `--disable-memory-watch` for normal closeout.
- Use `process_memory_snapshots` from the summary as host attribution evidence. They distinguish pytest workers from Codex, VS Code, browsers, WSL, Docker, or unrelated host processes instead of guessing after terminated processes have disappeared.
- Before full closeout gates and after interrupted or timed-out backend/frontend test commands, run the stale test-process checker. It is report-only unless `--kill` is explicitly provided and must only target matched repo-owned test command lines that are stale or above the default high-memory threshold: `python tools/check_stale_test_processes.py --include-sibling-frontend`.
- After memory-guard aborts or unexpected regression memory spikes, run the report-only runtime artifact checker before retrying: `python tools/check_runtime_artifacts.py`. It identifies oversized `runtime_state/` test payloads such as stale Admin API idempotency response blobs; do not delete artifacts without explicit cleanup approval.

Canonical full regression closeout command:

```bash
python tools/run_parallel_regression.py --workers 4
```

Use the sequential fallback only when `pytest-xdist` is unavailable and the
fallback is intentional:

```bash
pytest tests/regression/ -v --tb=short
```

## Subagent Hygiene

- Phase-end cleanup is the canonical timing: close subagents that were spawned
  for that phase, plus any stale or previously unused subagents from earlier
  phases or milestones discovered during the sweep, after their findings have
  been consumed, remediated, or explicitly deferred.
- Durable milestone closeout is a final audit sweep, not the first cleanup
  point. Leave no completed, failed, superseded, stale, or unused subagents
  open unless they are part of an active handoff with recorded owner, purpose,
  and expected next action.
- Do not close a subagent that is still running required validation, producing required evidence, or awaiting a user decision.
- Record the phase-end or milestone-closeout sweep result in the phase evidence, handoff, or closeout summary before advancing.
