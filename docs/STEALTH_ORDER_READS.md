# Stealth Order Reads And Command-Suite Evidence

Stealth Admin API reads expose backend lifecycle evidence without mutating
stealth orders or exchange state. They are part of the enterprise admin
platform, not the legacy dashboard command plane.

## Read Routes

- `GET /api/v1/stealth/orders`
- `GET /api/v1/stealth/orders/{stealth_order_id}`
- `GET /api/v1/stealth/command-suite`

The list/detail routes read local stealth lifecycle rows and report active
placement evidence when present. The command-suite route reports M55 readiness
for stealth create, cancel, reveal, move, reprice, recovery, and reconciliation
workflows.

## Identity Rules

Use `stealth_order_id` as the command identity for stealth Admin API evidence.
Active placement client ids and exchange order ids may be displayed as
evidence, but they are not internal tracking keys and are not cancellation
authority for the enterprise Admin API.

## Command-Suite Semantics

`GET /api/v1/stealth/command-suite` is read-only evidence. It derives existing
command rows and gap rows from backend route inventory and live-enablement
evidence:

- `POST /api/v1/stealth/orders` is linked as a live-disabled create command
  draft and does not invoke `StealthOrderManager` or create local lifecycle
  state.
- `POST /api/v1/stealth/orders/{stealth_order_id}/reveal` is linked as a
  live-disabled reveal command draft and does not invoke `reveal_order_slice`,
  submit Coinbase orders, or mutate lifecycle state.
- `POST /api/v1/stealth/orders/{stealth_order_id}/cancel` is linked as a
  live-disabled command row.
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice` is
  linked as a live-disabled movement/repricing command row.
- Workflow gaps remain blocked until backend-owned contracts exist for create
  lifecycle writes, reveal trigger/exchange placement, cancel exchange
  handling, move revealed, reprice completion, recovery, and reconciliation.

Every command row remains `live_enabled=false` and `executable=false`. Required
gates include idempotency, operator intent, payload hash, approval snapshot,
approval-store contract, admission audit, cap/guard decision, reconciliation
plan, mutation claim, live execution adapter, live execution service, and
post-live reconciliation. Cancel and reprice additionally require
active-placement exchange truth; create and reveal drafts remain blocked on
lifecycle/trigger evidence before execution can be considered.

## Exchange-Truth Boundary

`HIDDEN`, `PENDING`, and `TRIGGERED` stealth orders must not have a live
Coinbase placement. `REVEALED` means a placement was submitted and may still be
live. A revealed order cannot become hidden, cancelled, moved, or repriced by
local mutation alone; the active placement must be cancelled, replaced, filled,
moved, or reconciled first through the existing backend path.

The command-suite route does not read Coinbase, submit orders, cancel orders,
reveal orders, execute reconciliation, mutate local state, or grant browser/BFF
authority.

## Verification

Focused backend coverage:

```powershell
python -m pytest tests\regression\test_admin_api_contract.py -v --tb=short
```

Full backend regression is still required for non-agent changes:

```powershell
python -m pytest tests\regression\ -v --tb=short
```
