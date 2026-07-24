# Operator Hotpoint Control and Single Placement V1

Goal ID: `operator_hotpoint_control_and_single_placement_v1`.

## Operator workflow

The authenticated Admin UI route `/hotpoint` reads backend-owned Spot or
Futures control state, eligible system-owned parents, the one goal-global
Create allowance, recent placement evidence, and exact-child safe-closeout
authority. The operator may explicitly enable, disable, arm, disarm, run one
bounded evaluation, or close out the exact accepted child when the backend
returns that action.

Any terminal or restart-unknown Create outcome atomically disables the
persisted kill switch and delegated Create authority. The terminal
goal-global claim independently prevents either domain from creating another
child.

The browser supplies no price, size, cap, portfolio, trigger evidence, child
identity, retry, fallback, or Coinbase request. It forwards only the generated
domain-bound request, literal confirmation, fixed operator intent,
idempotency key, and correlation ID.

## Durable authority

PostgreSQL stores separate Spot and Futures singleton control rows and
append-only control commands. A shared `operator_hotpoint_goal_allowance` row
is claimed before any exchange-facing Create boundary. The shared advisory
lock and unique goal row permit at most one child claim total even if both
domain controls are armed concurrently. An unknown post-claim result consumes
the allowance and restart recovery terminalizes it without replay.

Spot policy is the approved Test portfolio, `BTC-USDC`, and maximum
`3.10 USDC` submitted plus `1.00 USDC` possible-execution notional. Futures
policy is the Default Futures profile, `AVP-20DEC30-CDE`, exactly one
contract, and strict opening/exposure/turnover caps below `100`, `150`, and
`300 USDC`. Product metadata, parent evidence, cap validation, claims, and
execution adapters never cross domains.

The current Futures placement and cancellation adapters remain visibly
unavailable and fail before claim creation. Goal 10 owns activation and proof
of the canonical Futures lifecycle; the Spot executor is never a fallback.

When the installed runtime has no verified private Default-profile portfolio
binding, Futures still returns a fixed, call-free operator readback containing
the approved product, one-contract limits, zero eligible parents, no allowed
actions, and
`operator_futures_hotpoint_portfolio_not_configured`. The backend does not
invent a portfolio identifier, initialize actionable Futures state, or grant
control authority. A verified binding is required before PostgreSQL-backed
Futures controls can become available.

## Historical translation

Reviewed `origin/prod` sources:

- `business/hotpoint_detector.py`
- `business/hotpoint_rate_limiter.py`
- `business/hotpoint_placer.py`
- `business/hotpoint_decay_sweeper.py`
- the dashboard Hotpoint kill-switch and test-placement handlers

The MVP retains bounded detector/control semantics but replaces browser or
WebSocket authority, in-memory-only rate state, background fan-out,
domain-generic placement, and raw exception logging with authenticated
contracts, durable claims, fixed diagnostics, and backend-owned policy.
