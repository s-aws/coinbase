# Operator Stealth Reveal and Exact Closeout V1

Goal `operator_stealth_reveal_and_exact_closeout_v1` is independent Goal 6 in
the authorized eleven-goal sequence. It turns one eligible Goal 5 definition
into a normal authenticated operator reveal workflow and binds any later safe
closeout to that exact placement.

## Operator workflow

The routed `/stealth` workspace loads the durable definition and a separate
Goal 6 execution record. The backend alone decides whether `REVEAL`,
`RESUME_ACCEPTED_CREATE`, or `CLOSEOUT` is available for the authenticated
actor. The browser displays the environment, hashed Test
portfolio scope, canonical `client_order_id`, definition revision/hash,
frozen plan, submitted-notional and possible-execution caps, admission hash,
single-use allowances, exact call counts, fixed diagnostic, and audit
correlation. It forwards only an explicit reason and confirmation.

`REVEAL` performs these backend-owned steps:

1. Claim the one Goal 6 definition identity and exact Goal 5 revision/hash.
2. Claim and invoke the API-key-permission and portfolio-catalog SDK reads
   separately, proving the configured UUID and `Test` label.
3. Atomically materialize the definition UUID as both the canonical root
   `client_order_id` and `stealth_order_id`.
4. Evaluate the definition condition only in the explicit operator command.
   Background bridge evaluation is suppressed for operator-materialized rows.
5. Freeze product, side, full fixed size, configured/submitted limit prices,
   reveal-pricing/source/fallback evidence, same-observation market evidence,
   target-movement/type/source profitability terms, and post-only policy.
   The complete object is canonical-hashed and revalidated at authority
   consumption.
6. Claim one complete wallet read and bind its cap/admission proof to that
   frozen plan.
7. Consume one durable Preview claim at the exact SDK invocation boundary.
8. Only after an accepted, error-free Preview, consume one Create claim at
   the exact SDK invocation boundary and
   submit the identical product, side, size, price, post-only flag, and
   `client_order_id`.

If the Test-portfolio binding or reveal condition is not ready, the command
returns fixed durable readback without consuming Preview or Create. A later
explicit operator command may claim another combined goal cycle. Exact
idempotency replay is call-free.

The backend directly rejects any frozen plan whose submitted notional exceeds
either the `3.10 USDC` submitted ceiling or the stricter `1.00 USDC`
possible-execution ceiling. This check runs before wallet or Preview and is
repeated immediately before the Create claim; displaying the cap is not
treated as enforcement.

If the process restarts after Preview acceptance and before the Create claim,
the durable state remains `PREVIEW_ACCEPTED`. An operator with `order:create`
may explicitly invoke `RESUME_ACCEPTED_CREATE` with a new request-bound
idempotency identity. The backend revalidates the immutable plan, accepted
Preview evidence, current execution lease, transport policy, caps, portfolio,
definition revision, and unconsumed Create allowance. It neither replays
Preview nor changes any candidate term. An interrupted resume command may be
followed by another bounded command cycle only while Create remains
unconsumed; a claimed or unknown Create is never retried.

`CLOSEOUT` revalidates the same hashed Test portfolio, resolves the internally
retained exchange identity only when its SHA-256 matches the durable Goal 6
evidence, and performs one authoritative `get_order` read bound to the exact
`client_order_id`, exchange identity, product, and portfolio. It passes that
verified exchange identity in memory to the canonical Cancel boundary and
consumes the one Cancel claim only immediately before the SDK invocation.
Local terminal state is deferred until authoritative post-Cancel readback
proves `CANCELLED` or `FILLED`; FILLED quantity remains owned by the canonical
fill reconciler rather than stale local cache.

## Durable authority and recovery

PostgreSQL stores:

- one `operator_stealth_reveal_goal` row with non-transferable
  Preview/Create/Cancel allowances and exact definition, portfolio, plan, and
  placement bindings;
- at most ten combined
  `operator_stealth_reveal_command_cycle` rows across reveal, accepted-Create
  resume, and closeout. Each cycle begins `IN_FLIGHT` and may become
  `COMPLETED` only after no live call is claimed and no read remains started.
  Completion stores the exact phase, correlation, hashed idempotency identity,
  payload hash, goal state/diagnostic, call-count snapshot, completion time,
  and canonical evidence hash;
- one no-retry read claim per category and cycle in
  `operator_stealth_reveal_read_call`;
- the canonical `order_parent` and `stealth_orders` root rows in one
  transaction.

The definition repository and canonical runtime table share an advisory
identity lock. A database trigger permits the reserved definition UUID to
enter the runtime only while the exact Goal 6 materialization claim is active.
Interrupted Preview, claimed Create, Cancel, or read claims become fixed
`UNKNOWN` evidence on startup and are never replayed. An accepted Preview with
an unclaimed Create remains explicitly resumable instead of being stranded.
Projection readback binds the current command correlation to a hashed
idempotency identity. The UI may clear a lost-response mutation freeze only
from a matching `COMPLETED` cycle whose state, fixed diagnostic, and all call
counts still match current goal readback. An `IN_FLIGHT` cycle remains frozen.
For `MATERIALIZING` or `MATERIALIZED`, recovery additionally requires a reveal
cycle with zero Preview/Create/Cancel claims and all three allowances
unconsumed.

The maximum wire-read accounting is 31 calls. Every reveal cycle contains
separately claimed API-key-permission, portfolio-catalog, and wallet-admission
SDK boundaries. Every closeout cycle contains separately claimed API-key-
permission, portfolio-catalog, and exact-order SDK boundaries, with one
possible post-Cancel exact-order read after the sole Cancel. The ten-cycle budget is
goal-global. No category or exchange mutation is retried.

## Exact Preview/Create boundary

The canonical REST wrapper owns the last pre-SDK claim hook for every Coinbase
read, Preview, Create, and Cancel. It validates timeout/TLS hardening before
the hook, invokes the durable claim callback, then validates transport
hardening again and performs the final execution-authority check immediately
before the raw SDK method. Failure before the claim leaves the allowance
unconsumed. Failure during or after the claim callback is durably unknown and
cannot be retried.

The Coinbase Preview request uses a `limit_limit_gtc` configuration. Preview
validation binds documented `base_size` and `quote_size`, where the expected
quote amount is the frozen base size multiplied by the frozen limit price.
The raw SDK envelope is not persisted or exposed.

After Preview acceptance:

- no later market-data read is made;
- pre-submission hooks may not change any exchange field;
- post-only retry/repricing is disabled;
- product, side, base size, limit price, post-only policy, plan hash, Preview
  claim, portfolio, definition revision/hash, and canonical
  `client_order_id` remain exact;
- the full reveal plan object is copied into the typed authority, hashed, and
  revalidated at consumption so a valid scalar plan hash cannot authorize a
  substituted object;
- an exception or ambiguous boundary consumes its already-claimed allowance
  and produces only a fixed diagnostic.

Preview identity is withheld. Exchange-native order identity is retained only
inside the protected exact-child anchor needed for closeout. Goal 6 operator
readback exposes only its SHA-256 digest, and operator hooks, logs, lifecycle
events, and reveal events receive value-blind snapshots without the raw
identity. Raw responses, exception messages, private portfolio identity,
secrets, and withheld text are not persisted or displayed.

Official contract references:

- [Coinbase Preview Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders)
- [Coinbase Advanced Trade order guide](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/orders)
- [coinbase-advanced-py SDK documentation](https://coinbase.github.io/coinbase-advanced-py/)

## RBAC and deployment

The read route requires `analytics:read`. Reveal and accepted-Create resume
require `order:create`; closeout requires `order:cancel`. `allowed_actions`
are actor-aware and require the same backend role plus full fixed-policy,
revision, allowance, cap, and terminal-state eligibility. Live commands additionally require the
installed Controlled-live execution lease, `COINBASE_EXECUTION_ENABLED=1`,
the approved Test portfolio configuration, the exact Goal 6 feature flag,
explicit operator intent, and canonical backend execution scopes. Button
visibility is never treated as authority.

The GET execution readback initializes neither the Coinbase SDK nor the
stealth runtime and makes no Coinbase call. Page loading and ordinary
navigation are call-free.

## Historical translation

The current and historical paths were inspected side by side:

- `origin/prod:core/stealth_order_manager.py`
- `origin/prod:business/stealth_reveal_strategy.py`
- `origin/prod:bridges/stealth_order_bridge.py`
- `origin/prod:dashboard_server.py`
- `origin/prod:external/coinbase_client.py`

The legacy manager supplied reveal-plan, condition, placement, and closeout
semantics. The current workflow does not restore legacy dashboard WebSocket
authority, automatic reveal, multi-slice execution, post-only retry/repricing,
browser-owned eligibility, alternate orders, raw exception display, or direct
browser Coinbase access.

## Authorization boundary

This goal may use the route-required no-retry eligibility reads, exactly one
Preview, exactly one identical Create only after accepted Preview, and at most
one exact-placement Cancel if authoritative evidence proves it nonterminal.
Unknown outcomes consume the applicable allowance. It grants no automatic
reveal, second slice, alternate order, fan-out, scheduler, Futures action, or
allowance transfer to another goal.

R1–R12 and V1–V15 remain immutable. R8 content and hash remain inaccessible.
