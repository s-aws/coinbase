# Spot Trading

This document is domain behavior reference; it grants no exchange authority.
Campaign, sweep, fan-out, scheduler, retry, and wallet-ledger expansion remain
parked.

Current execution boundary: the product is the operator review stack and its
installed default is Controlled-live, which fails closed without exact backend
authority. The six installed Controlled-live mutation routes are manual root
place/cancel, explicit attached-intent materialization/exact-child
safe-closeout, and operator Hotpoint run-once/exact-child safe-closeout.
Follow-up intent attachment is completed but local-only and its
acknowledgement never becomes materialization authority. Materialization and
safe-closeout each require a fresh, separate explicit operator acknowledgement;
the backend revalidates exact source/root/child identity, authoritative fill or
terminal state, approved Test portfolio, wallet/caps, RBAC, idempotency,
exactly-once claiming, audit, reconciliation, and duplicate prevention. Legacy
dashboard, hotpoint, stealth/engine, smoke, sweep, campaign, batch, and
automatic follow-up mutation paths are source-disabled and cannot mint the
canonical request scope.

Spot trading uses the same order lifecycle, stealth lifecycle, sizing, fee,
dashboard, and reconciliation paths as futures. There is no separate spot
engine.

## When To Use

Use spot products when the trade should settle against the spot wallet balance
instead of a Coinbase Derivatives position. Spot orders use base-asset size
increments and quote-notional minimums from `products.json`.

## Key Concepts

- `products.json` is the product catalog. Add spot products under `spot` and
  keep metadata under `metadata`.
- Product type must resolve to `ProductType.SPOT` through
  `configuration.normalize_product_type`.
- `ticker_to_trading` is only for products where ticker and tradable product IDs
  are genuinely different. Do not map `BTC-USD` to `BTC-USDC` unless the target
  product is live and tradable in Coinbase product metadata.
- Spot profitability uses the spot fee multiplier in `calculation/fee_manager.py`
  and does not apply derivatives per-contract fees.
- Spot wallet/action-condition helpers remain available for offline planning
  and historical compatibility tests. They do not authorize dashboard,
  stealth, or sweep exchange submission.
- Local planned-budget accounting subtracts HIDDEN, PENDING, and TRIGGERED spot
  stealth commitments from wallet availability before admitting another spot
  action. REVEALED orders are not counted locally because Coinbase wallet
  availability should already reflect the live exchange hold.
- Product capability policy keeps offline/local feature availability explicit,
  but cannot mint Controlled-live authority. Legacy direct placement, stealth
  reveal/replacement, cancel/re-entry, and hotpoint mutation paths are
  source-disabled.
- Spot follow-ups are classified before creation. BUY-fill to SELL is treated
  as an `exit`; SELL-fill to BUY is treated as `rebuy` and is blocked unless
  `SPOT_FOLLOW_UP_POLICY_JSON` or `products.json::spot_follow_up_policy`
  explicitly enables it.
- Spot inventory authority separates wallet sellability from known profitable
  inventory. `SPOT_INVENTORY_BASELINES_JSON` or
  `products.json::spot_inventory_baselines` can import pre-existing inventory;
  baseline lots without positive known entry price are marked unknown cost
  basis and cannot satisfy known-profit checks. Imported baselines are also
  audited for source freshness metadata such as `source_updated_at`.
- Coinbase portfolio average cost basis can be read as a separate operational
  authority source for USDC spot coverage, P/L, drift review, and optional SELL
  admission. It is asset-level portfolio data mapped to eligible `BASE-USDC`
  products, not exact local FIFO lot evidence. When it is the actual SELL
  authority source, stale average-cost records or stale local-vs-Coinbase drift
  block that product.
- `known_inventory_available` is an optional action-condition guard. When
  enabled, spot `SELL` admission can require known profitable lots in addition
  to wallet availability. It is disabled by default.
- Dashboard spot readiness feedback is available through the
  `request_spot_readiness` websocket message and the Spot Readiness panel in
  `ui_stealth_orders_manager.html`. The panel shows capability reasons,
  guard phase coverage, wallet snapshot balances, planned local spot budget,
  and imported baseline inventory split between known and unknown cost basis.
- USDC-only portfolio sweep planning and durable P/L reporting live in
  [Spot Portfolio Sweep](README.spot-portfolio-sweep.md). That feature also
  owns sweep automation status, inventory coverage, fill-backfill recovery, and
  sweep recovery gates. USD pairs remain out of scope for that feature.
- Reusable campaign intake, dry-run matrices, release gates, durable campaign
  P/L snapshots, and dashboard campaign status live in
  [Spot Campaigns](README.spot-campaign.md). Rendered configs are offline
  evidence; campaign/sweep mutation modes are source-disabled.
- Historical partial campaign records can generate targeted retry configs for
  products that were not submitted. Retry configs are offline review artifacts
  and cannot enable order placement.
- Planned skips, such as below-minimum quote-size products, are offline audit
  rows rather than failed Coinbase submissions. They are not execution or retry
  authority.
- Spot-specific feature requests should pass the local feature-intake gate
  before implementation. The gate requires exact USDC product scope, order
  sides, order policies, automation cadence, live approval rule, notional caps,
  inventory retention policy, and required audit evidence.
- Internal order tracking uses `client_order_id`; Coinbase `order_id` remains
  exchange evidence only. Dashboard cancel is source-disabled. Authenticated
  Admin API cancel preserves this identity rule and uses exchange evidence only
  at its guarded final boundary.
- The current boundary between legacy live WebSocket commands, read-only HTTP
  routes, and sweep/campaign execution is maintained in
  [Live Order Surfaces](docs/LIVE_ORDER_SURFACES.md).

## Supported Controlled-Live Surface

Spot Coinbase mutation is limited to six installed Controlled-live mutation
routes: manual root place/cancel, explicit attached-intent
materialization/exact-child safe-closeout, and operator Hotpoint
run-once/exact-child safe-closeout under the exact backend admission chain.
Intent attachment itself is local-only. No other source may add or reuse
a REST placement/cancel path, and no installed scheduler materializes intents.

Scope note: offline dashboard/stealth compatibility fixtures use products
configured in `products.json`; the portfolio sweep and campaign planning
features are intentionally USDC-only even if `products.json` also contains
USD-quoted spot products.
The checked-in `products.json` is intentionally a minimal local catalog and
does not represent all Coinbase spot products. Do not infer USDC sweep or
campaign coverage from that file.

Automation note: sweep/campaign/stealth paths may be used for offline planning,
durable JSONL evidence, and reconciliation review only. They are not current
exchange execution surfaces.

### Spot Order Lifecycle Audit Matrix

| Surface | Planning/admission | Live exchange call | Durable evidence |
| --- | --- | --- | --- |
| Authenticated Admin API manual place | Exact flag/lease, current service decision, RBAC, intent, idempotency, acknowledgement, LIMIT/GTC, caps, Test portfolio/wallet, audit, reconciliation | canonical wrapper `create_order` under route-minted place scope | `client_order_id`, exchange evidence, audit/correlation, durable root and terminal readback |
| Authenticated Admin API manual cancel | Same backend admission family plus exact local/exchange identity and cancellation quarantine | canonical wrapper cancel under route-minted cancel scope | audit/correlation, cancellation result and authoritative terminal readback |
| Authenticated Admin API follow-up intent attachment | Exact eligible system-owned nonterminal source, RBAC, idempotency, duplicate prevention, explicit local acknowledgement | none; local-only and grants no live authority | durable attached intent, canonical audit, backend eligibility/readback |
| Authenticated Admin API attached-intent materialization | Fresh explicit acknowledgement plus authoritative source fill, exact root/child tuple, Test portfolio, product/wallet/caps, RBAC, exactly-once claim, audit, reconciliation | one-use canonical wrapper `create_order` under route-minted materialization scope | durable child identity/linkage, exchange evidence, audit/correlation, authoritative readback |
| Authenticated Admin API exact-child safe-closeout | Fresh separate acknowledgement plus exact linked child identity and authoritative nonterminal state | one-use exact-ID canonical wrapper cancel under route-minted safe-closeout scope | durable cancel outcome, child linkage, audit/correlation, authoritative terminal readback |
| Dashboard place/cancel/hotpoint | source-disabled before runtime lookup | none | fixed source-disabled response |
| Legacy stealth/engine | compatibility/read-only only; no canonical route scope | none | historical/local evidence only |
| Sweep/campaign | offline planning, ledger, P/L, and reconciliation review | none | JSONL/read-only evidence |

- Raw dashboard mutation messages are not a direct-order alternative. Use the
  installed Admin UI/API manual order workflow for Controlled-live testing.
  Direct orders can be inspected with:
  `python3.13 tools/run_spot_direct_order_audit.py --client-order-id <client_order_id>`.
  The dashboard can return the same local audit with
  `request_spot_direct_order_audit` and `params.client_order_id`.
  These are read-only local evidence audits, not retry or automation wrappers.
  In direct-audit output, `live_coinbase_orders_ran` and
  `audit_command_live_coinbase_orders_ran` mean the audit command itself did
  not submit orders. Use `audited_order_live_submission_evidence`,
  `audited_order_estimated_submitted_notional_usdc`, and
  `audited_order_fill_notional_usdc` for evidence about the already-submitted
  order being audited.
  Controlled-live manual orders rely on the authenticated Admin API response,
  `order_event_stream` submission evidence, websocket/order lifecycle handling,
  fill-ledger rows, and the shared reconciliation/fill-audit paths keyed by
  `client_order_id`.
  Read-only recovery evidence for audited direct orders is available through
  `GET /api/v1/spot/recovery/preview?client_order_id=<client_order_id>`,
  `GET /api/v1/spot/recovery/apply-review?client_order_id=<client_order_id>`,
  `GET /api/v1/spot/recovery/rollback-plan?client_order_id=<client_order_id>`,
  and
  `GET /api/v1/spot/recovery/reconciliation-proof?client_order_id=<client_order_id>`.
  Those Admin API routes report candidates, gate dependencies, rollback
  prerequisites, and proof-field requirements; they do not apply repair rows,
  roll back local state, write proof/snapshot records, execute reconciliation,
  mutate order or exchange state, call Coinbase, or authorize browser/BFF
  recovery. Backend-owned proof and snapshot POST contracts are separate
  local-state evidence routes and remain no-live.
  Campaign and sweep tools remain useful for read-only planning, status,
  ledger, P/L, and reconciliation review; their mutation modes are
  source-disabled.
- All four supported Controlled-live mutations enter through authenticated
  Admin API routes. The backend requires exact flag and manager lease, a fresh
  lease-bound service decision, RBAC, operator intent, idempotency, a fresh
  route-specific acknowledgement, exact route identity/input, caps,
  Test-portfolio/wallet evidence, audit, reconciliation, duplicate prevention,
  and a route-minted final SDK scope. The attached intent's earlier local
  acknowledgement is never reused.
- Dashboard `place_order`, `cancel_order`, and `place_hotpoint_test_order`
  return fixed source-disabled responses before runtime lookup.
- Legacy stealth/hotpoint/engine code remains historical source material and
  cannot mint the canonical Admin API request scope.

`create_parent_order` is not live exchange placement. It is dashboard/local DB
CRUD that creates an `order_parent` row for operator-managed local state.

## Disabled And Conditional Spot Features

Spot is not a blanket futures/perpetual equivalent. The current supported
Controlled-live surface is the four authenticated Admin API manual-root and
attached-intent mutation routes described above; other paths are read-only,
local-evidence, or source-disabled.

Source-disabled for spot exchange mutation:

- Move/reprice replacement. Product capability and guard calculations remain
  offline regression/reference inputs and cannot mint exchange authority.
- Cancel/re-entry. Policy calculations may model the no-fill lifecycle, but
  the exchange mutation path is not an installed operator surface.
- Hotpoint auto-placement. `HOTPOINT_AUTO_PLACEMENT` cannot override the fixed
  dashboard/hotpoint source-disable or mint canonical Admin API request scope.

Conditional local/offline behavior for spot:

- BUY-fill to SELL follow-up is classified as an exit and may create local
  follow-up evidence when profitability and action guards pass; it grants no
  Coinbase submission authority.
- SELL-fill to BUY follow-up is a rebuy and is blocked unless
  `SPOT_FOLLOW_UP_POLICY_JSON` or `products.json::spot_follow_up_policy`
  explicitly enables rebuy intent.
- Same-side replacement or retreat remains local/offline policy evidence even
  when the relevant capability and guard admit the modeled replacement.

Not disabled:

- Authenticated Admin API manual Spot LIMIT/GTC root place/cancel under exact
  Controlled-live backend admission.
- Explicit attached-intent materialization and exact-child safe-closeout under
  their separate acknowledgements and exact backend-owned eligibility,
  identity, claim, audit, reconciliation, and duplicate-prevention gates.
- Local-only follow-up intent attachment and authoritative readback; attachment
  grants no Coinbase-call authority.
- Read-only sweep/campaign planning, status, ledger, P/L, and reconciliation
  review.

## Outputs And Artifacts

- Orders are still persisted in `order_parent`.
- Stealth plans are still persisted in `stealth_orders`.
- Product precision and minimums come from `products.json::metadata`.
- Admin API and dashboard product refresh are source-disabled before any
  Coinbase read or `products.json` write. Metadata updates require a future
  separately authorized, durable refresh authority chain.
- Direct manual order audit is available through
  `request_spot_direct_order_audit` and
  `tools/run_spot_direct_order_audit.py`.

## Safety Constraints

- Do not add a spot-only placement path.
- Do not hard-code spot product IDs, increments, or fee rules in strategy code.
- Do not bypass `core.product_capability.evaluate_product_capability` from new
  order-entry, replacement, or strategy surfaces.
- Validate base-sized orders with
  `calculation.size_validation.validate_and_quantize_size` before placement.
  Validate quote-sized market BUYs with
  `calculation.size_validation.validate_quote_size`.
- Do not treat a synthetic planning wallet pass as exchange authority. External
  Coinbase orders can consume wallet balance after the observation.
- Do not add mutable spot reservation state unless derived planned-budget
  accounting from stealth order status and remaining size is proven insufficient.
- Do not let spot follow-ups inherit futures short/close semantics. Route new
  follow-up behavior through `core.spot_follow_up_policy`.
- Keep synthetic no-fill replacement checks hold-aware so regression evidence
  credits the modeled Coinbase hold and leaves local state conservative after a
  modeled cancel failure. This calculation does not enable exchange mutation.
- Do not treat wallet inventory as profitable inventory. Wallet balance proves
  sellability; only fill-ledger or imported known-cost lots can prove known
  profitable inventory by default. Coinbase average cost can satisfy SELL
  authority only through an explicit opt-in path with an extra profit buffer.
- Dashboard `cancel_order` is source-disabled. Authenticated Admin API cancel
  remains operator-keyed by `client_order_id`; exchange-native `order_id` is
  evidence used only at the guarded backend boundary required by Coinbase.
- Run focused tests for ordinary spot changes. Run full `tests/regression/`
  only before durable milestone closeout, public/release-candidate handoff, or
  explicit request; prefer `python3.13 tools/run_parallel_regression.py --workers 4`.

## Examples

See [Spot Trading Examples](docs/examples/spot-trading.md).
For USDC-only portfolio sweep dry runs, see
[Spot Portfolio Sweep Examples](docs/examples/spot-portfolio-sweep.md).
For reusable campaign gates, see
[Spot Campaign Examples](docs/examples/spot-campaign.md).
For account-level guard configuration, see
[Action Condition Guards](README.action-condition-guards.md).
For spot feature intake, see
[Spot Feature Intake Examples](docs/examples/spot-feature-intake.md).

Validate a proposed spot-specific feature with:

```powershell
python3.13 tools/run_spot_feature_intake_gate.py --request-file runtime_state/spot_feature_request.json --summary-only
```

## Test Gate

Run the focused spot readiness gate with:

```powershell
python3.13 tools/run_spot_readiness_regression.py
```

Run the optional browser smoke gate with:

```powershell
python3.13 tools/run_spot_readiness_browser_smoke.py
```

The browser gate uses `pytest-playwright` and installed Chromium to open
`ui_stealth_orders_manager.html`, verify the readiness request is sent, and
verify a dashboard-shaped readiness payload renders in the panel.

Run the manual contextless blind-agent readability gate before treating new spot
order behavior as ready. The prompt and pass/fail rubric are in
[Spot Contextless Agent Testing](docs/SPOT_CONTEXTLESS_AGENT_TESTING.md). If a
fresh agent cannot explain the canonical spot order path from repo context
alone, fix the docs or code organization and rerun the same blind prompt.

This does not replace the required full regression closeout gate when a durable
milestone, public/release candidate, or deployment approval is being marked
complete: `python3.13 tools/run_parallel_regression.py --workers 4`.

Run the read-only spot release wrapper with:

```powershell
python3.13 tools/run_spot_release_gate.py
```

The historical raw live-smoke command (now source-disabled) was:

```powershell
python3.13 tools/run_live_spot_usdc_smoke.py --approved-live-orders
```

The historical matrix/reconciliation combination (also source-disabled) was:

```powershell
python3.13 tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate
```

These commands now exit before SDK construction with a fixed source-disabled
diagnostic. Historical smoke artifacts remain evidence only.

## Roadmap

Spot trading is not yet treated as a blanket equivalent to futures/perpetuals.
Before adding spot-specific strategy features, follow the tracked
[Spot Readiness Roadmap](docs/SPOT_READINESS_ROADMAP.md).
