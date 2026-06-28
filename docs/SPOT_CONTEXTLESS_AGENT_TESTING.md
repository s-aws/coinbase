# Spot Contextless Agent Testing

This runbook verifies that spot trading behavior is understandable to a fresh
human or small local agent that has no session history.

## Purpose

Use this gate before treating new spot behavior as ready. The goal is not to
measure model quality. The goal is to find repo-context gaps: unclear entry
docs, ambiguous code ownership, hidden order paths, or safety rules that only
make sense to someone who participated in prior sessions.

The repeatable local harness prints this prompt and rubric without editing
files or calling Coinbase:

```powershell
py -3.13 -m tools.run_spot_contextless_agent_checklist --summary-only
py -3.13 -m tools.run_spot_contextless_agent_checklist
```

## Blind Prompt

Use a fresh agent with no forked conversation context and no extra guidance
beyond the repository path:

```text
You are in the local repository at c:\coinbase. You have no prior session
context. Do not edit files. Task: determine how a spot order is created in
this project and explain, from the code/docs you find, the intended flow for a
spot BUY or SELL order, including which modules own planning/admission, wallet
checks, live placement, campaign/sweep paths, and safety/reconciliation. Do not
ask for guidance and do not rely on this prompt for architecture beyond the
task itself. Report: (1) where a new human/small agent should start reading,
(2) the canonical code path, (3) any confusing or missing context you found,
and (4) whether you would be confident creating a spot order correctly from
repo context alone.
```

## Pass Criteria

The response passes only if it identifies:

- `README.spot-trading.md` and `docs/README.md` as appropriate entry points.
- The invariant that spot uses the existing order lifecycle, not a spot-only
  placement engine.
- Direct/dashboard spot order admission through the shared
  `ActionConditionGuard`.
- Direct dashboard spot placement hard gates:
  `manual_live_acknowledgement=true`, explicit planning-phase `max_notional`
  cap, enabled local `order_event_stream` publisher before REST, and
  `known_inventory_available` for direct spot `SELL`.
- Stealth planning and reveal wallet checks, including the reveal-time wallet
  recheck.
- USDC portfolio sweep and campaign paths:
  `business/spot_portfolio_sweep.py`, `tools/run_spot_portfolio_sweep_live.py`,
  `business/spot_campaign.py`, and `tools/run_spot_campaign.py`.
- The live approval boundary: campaign tools do not submit Coinbase orders;
  live sweep execution requires `--approved-live-orders`.
- Live USDC sweep `SELL` requires `--require-known-profitable-inventory`;
  wallet balance alone cannot authorize live SELL sweep execution.
- The distinction between wallet sellability and known profitable inventory.
- `client_order_id` as the internal tracking id and exchange `order_id` as
  exchange evidence only.
- Reconciliation/fill-backfill as the way local state is compared against
  Coinbase reality.
- Planned skips as audit rows, not failed Coinbase submissions.
- Which submission/audit evidence path applies to each supported placement
  surface: direct dashboard order, stealth reveal, and portfolio sweep live
  execution.
- That live USDC sweep placements use UUID `client_order_id` values and record
  sweep identity through the sweep ledger/event payloads rather than prefixed
  Coinbase-facing ids.
- That direct dashboard and live sweep placement publish
  `order_submitted` / `rest_submit` event-stream evidence when the local event
  stream is available.
- That direct-order audit output separates the read-only audit command fields
  from audited-order evidence fields such as
  `audited_order_live_submission_evidence`.
- That dashboard `create_parent_order` is local DB CRUD and does not submit a
  Coinbase order.
- That direct dashboard `place_order` is an immediate manual placement surface:
  it publishes submission evidence but does not pre-insert `order_parent` or
  opt the order into automated follow-up policy state before submission.
- That Hotpoint Manager `place_hotpoint_test_order` is also a live dashboard
  submission surface, is runtime-admission gated, requires
  `ProductCapability.HOTPOINT_AUTO_PLACEMENT`, runs size and action-condition
  checks, pre-inserts an opt-in parent row, submits through
  `REST_CLIENT.limit_order_gtc`, and publishes submission evidence when the
  local event stream is available. Spot products are blocked by default unless
  the hotpoint capability is explicitly enabled.
- That direct/stealth spot placement scope comes from `products.json`, while
  portfolio sweep and campaign scope is USDC-only.
- That failed stealth REST placement records failed reveal evidence without
  making local state claim a live revealed placement.
- The rule that new spot order-creation surfaces must not be added until they
  either reuse existing submission evidence paths or explicitly extend the
  canonical audit path.

## Failure Handling

If the blind response misses a required item, fix the repository rather than
coaching the agent. Prefer changes in this order:

1. Improve `README.spot-trading.md` or the relevant feature README.
2. Improve `docs/README.md` navigation.
3. Add or clarify examples in `docs/examples/`.
4. Rename or consolidate code paths only if documentation cannot make the
   canonical path clear.
5. Add implementation work to the roadmap when the failure exposes a real
   behavioral inconsistency rather than only a documentation gap.

After the fix, rerun the same blind prompt. Do not change the prompt to make
the test easier unless the spot architecture itself changes.

## Evidence To Record

Record the date, agent type, prompt version, pass/fail result, and the missing
items found. Roadmap phases that add spot order behavior should mention whether
this gate passed and which docs/code were changed if it did not.

## Recent Evidence

- 2026-06-10, explorer agent, Phase 157 prompt variant: first run passed the
  core workflow but flagged raw dashboard `place_order` as an insufficiently
  visible uncapped live surface. Fixed `README.spot-trading.md` and
  `docs/examples/spot-trading.md` with a manual direct-order checklist and the
  wallet-sellability versus known-profit SELL distinction.
- 2026-06-10, explorer agent, same prompt after docs fix: passed. The agent
  identified direct dashboard placement as manual-only, sweep/campaign as the
  automation path, strict versus Coinbase average-cost SELL authority,
  `client_order_id` tracking, direct-order audit command, and the Coinbase
  cancellation exception.
- 2026-06-10, explorer agent, Phase 193 prompt variant: first run failed on
  broken direct-order audit helper calls and stale/confusing Admin API wording.
  Fixed dashboard audit keyword calls, test coverage, and Admin API/OpenAPI
  wording.
- 2026-06-10, explorer agent, same Phase 193 prompt after audit/docs fix:
  passed discoverability but flagged raw direct spot as operationally risky
  because cap, known-profit SELL authority, and pre-REST audit were not hard
  defaults. Fixed code to require a planning-phase `max_notional` cap for
  direct spot, require `known_inventory_available` for direct spot `SELL`, and
  require an enabled local `order_event_stream` publisher before direct spot
  REST submission.
- 2026-06-10, explorer agent, same Phase 193 prompt after code hardening:
  failed on stale `docs/examples/spot-trading.md` wording that still described
  direct spot `SELL` known-profit guarding as optional. Fixed the example to
  show complete direct BUY/SELL guard setup and the durable audit requirement.
- 2026-06-10, explorer agent, same Phase 193 prompt after sweep/direct-audit
  hardening: failed because live USDC sweep `SELL` could still run without the
  known-profit policy, the API reference omitted audited-order evidence fields,
  and the checklist did not include the current direct spot hard gates. Fixed
  live sweep `SELL` to require `--require-known-profitable-inventory`, updated
  direct-audit API samples, and expanded the checklist criteria.
- 2026-06-10, explorer agent, same Phase 193 prompt after the above fixes:
  passed. The agent identified direct dashboard spot gates, cancellation by
  `client_order_id`, live sweep BUY/SELL boundaries, mandatory live SELL
  known-profit policy, then-current Admin HTTP live-disabled status,
  direct-audit `audited_order_*` evidence fields, and no remaining
  `--disable-safety-policy --approved-live-orders` path. Current Admin HTTP
  manual order/cancel posture is no-live by default with route-scoped
  configured live gates documented in `README.admin-api.md` and
  `docs/LIVE_ORDER_SURFACES.md`.
- 2026-06-11, explorer agent, Admin frontend spot-order flow prompt: passed.
  The agent identified backend OpenAPI as the contract source, frontend
  `CommandWorkflowShell` dry-submit wrappers, BFF mode, backend
  `POST /api/v1/orders`, `AdminApiCommandService`, then-current
  live-disabled HTTP command status, backend RBAC authority,
  `client_order_id` cancellation, and required gates. Current Admin HTTP
  manual order/cancel posture is no-live by default with route-scoped
  configured live gates. The review flagged missing full-gate proof commands
  in the frontend spot-order flow doc; the doc was fixed to include
  `npm run release:gate` and full backend regression.
