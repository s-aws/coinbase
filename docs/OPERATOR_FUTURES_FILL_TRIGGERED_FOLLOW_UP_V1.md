# Operator Futures Fill-Triggered Follow-Up V1

Goal:
`operator_futures_fill_triggered_follow_up_activation_v1`.

Status: implementation, validation, and independent audits complete.

## Operator outcome

An authenticated operator opens a routed Default-profile Futures order,
attaches the backend-owned opposite-side one-contract intent, and can then
enable, disable, pause, resume, drain, or inspect its automatic activation.
Enable and resume require explicit acknowledgement of the single-use live
allowances and backend-owned child terms.

An enabled activation does not poll Coinbase and page loading is call-free.
When the operator runs exact reconciliation for the source
`client_order_id`, the order-operations service first persists the sanitized
Coinbase observation. Only a persisted `FILLED` observation with
`size=filled_size=1`, matching product, matching source side, a hash-bound
exchange identity, and non-cancelable terminal classification can claim the
one full-fill trigger.

## Default-profile execution policy

The trigger uses the independent Default-profile Futures client and a
separate Goal 5 PostgreSQL ledger. It does not use the Spot Test profile,
wallet rules, fill ledger, WebSocket, or browser terms.

One fresh six-category eligibility cycle reads each category no more than
once:

1. API-key permissions;
2. Default portfolio catalog;
3. configured Futures product;
4. best bid/ask;
5. Futures positions; and
6. CFM margin/collateral.

The backend proves the enabled product-policy revision, attached-intent
revision, full-fill evidence hash, current one-contract position, opposite
child side, fresh passive price, product increments, current margin evidence,
and strict `<100 / <150 / <300 USDC` caps. A long source exposure can produce
only one `SELL` child; a short source exposure can produce only one `BUY`
child. The child is post-only and one contract. There is no fan-out or
alternate identity.

After fresh exact eligibility, one durable claim permits at most:

- one Coinbase Preview;
- one identical Create only after an accepted error-free Preview;
- one exact-child reconciliation; and
- one Cancel only when that reconciliation proves the exact child
  authoritatively nonterminal.

There are no retries, redirects, fallbacks, second children, product
expansion, Spot calls, Close, Reduce, funding, transfer, or scheduler
activation. Unknown outcomes consume their applicable single-use allowance.

## Maintenance and schema compatibility

Coinbase Futures maintenance is treated as a hypothesis, not a diagnosis.
The current implementation remains pinned to
`coinbase-advanced-py==1.8.4` and the official Advanced Trade
[Futures](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures)
and [Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders)
contracts.

Eligibility categorizes HTTP authorization, forbidden access, not-found,
rate-limit, client/server, timeout, TLS, connection, and schema-invalid
boundaries using fixed value-blind diagnostics. A response-shape mismatch is
never reinterpreted as credentials, entitlement, V3 policy ineligibility, or
a trading rejection. Raw responses, rejected values, exception messages,
portfolio UUIDs, exchange IDs, Preview IDs, secrets, and withheld text are
not persisted or returned.

The absence of a published breaking change is negative evidence only. Focused
synthetic fixtures, the installed SDK contract checks, and the complete local
deployment gate passed against the documented shapes. Any later runtime shape
divergence still fails closed as schema-invalid evidence; it is not silently
accepted as maintenance compatibility.

## Durable authority and restart recovery

PostgreSQL stores:

- one activation row per immutable Futures follow-up intent;
- revision-bound enable, disable, pause, resume, and drain commands;
- payload-bound idempotency hashes and append-only command evidence;
- the single full-fill claim and source evidence SHA-256;
- a separate Goal 5 eligibility/call ledger;
- one backend-created child `client_order_id`; and
- fixed Preview/Create/reconciliation/Cancel outcomes.

Restart before a Coinbase boundary can recover locally. Restart after a
claimed or invoked boundary records `UNKNOWN` and does not retry. No raw
Coinbase identity is stored in the activation table.

## API and RBAC

- `GET /api/v1/futures/order-operations/{client_order_id}/follow-up-intent/fill-triggered-activation`
  requires `analytics:read` and performs only PostgreSQL reads.
- `POST /api/v1/futures/order-operations/{client_order_id}/follow-up-intent/fill-triggered-activation`
  requires `order:create`, exact revision, idempotency and correlation
  headers, and fixed
  `control_futures_fill_triggered_follow_up` operator intent.
- `ENABLE` and `RESUME` are available only in the installed Controlled-live
  posture to an actor with `order:cancel`, when backend execution authority,
  Default-profile credentials, live-runtime admission, policy, and exact
  confirmations are ready.

The frontend displays generated backend contracts and forwards only the
operator-selected control action. It never derives a side, price, size,
portfolio, child identity, exchange identity, cap, fill, or trading
eligibility.

## Historical translation

Historical source material inspected:

- `origin/prod:core/order_engine.py`
- `origin/prod:dashboard_server.py`

Only source/root/child linkage and the full-fill follow-up concept were
translated. Legacy partial-fill dispatch, WebSocket authority, implicit
background execution, direct browser-to-Coinbase behavior, retry behavior,
raw exception handling, and Spot semantics were not copied.

## Closeout evidence

- focused backend service, repository, route, OpenAPI, and generated-contract
  tests pass;
- the canonical backend regression passes with 1,286 parallel-safe tests and
  896 serial tests, with 6 and 150 skips respectively;
- the frontend release gate passes 1,774 unit/component tests plus the full
  authenticated deployment and browser workflow suite;
- independent safety and blind-contextless audits both pass after remediation
  of lifecycle diagnostic compatibility, fixed operator-intent/cap readback,
  and restart/idempotency coverage;
- validation made zero Coinbase calls and used zero notional; and
- no authoritative fully filled attached source intent existed at closeout,
  so Preview, Create, reconciliation, and Cancel allowances remain
  unconsumed.
