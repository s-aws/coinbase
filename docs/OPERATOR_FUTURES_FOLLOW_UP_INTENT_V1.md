# Operator Futures Follow-Up Intent V1

Goal:
`operator_futures_follow_up_intent_attachment_v1`.

## Operator outcome

An authenticated operator can open one durable Default-profile Futures order
at `/futures/orders/{clientOrderId}`, review backend-owned attachment
eligibility, acknowledge the local-only boundary, and attach exactly one
follow-up intent. The backend derives the opposite side and fixes the size at
one contract. The attachment makes zero Coinbase calls, creates no child, and
does not authorize later materialization.

## Eligibility

The source is read from
`operator_futures_order_projection` by exact `client_order_id`. Attachment is
available only when all of the following are true:

- the source product is one of the configured Default-profile Futures
  products (`AVP-20DEC30-CDE` or `BIP-20DEC30-CDE`);
- its durable status is `OPEN`;
- it is authoritatively nonterminal;
- its source size is exactly one contract;
- its side is `BUY` or `SELL`;
- its observation and hashed exchange-identity binding are present; and
- no Futures follow-up intent already occupies the source slot.

The browser cannot provide a product, profile, side, size, price, child
identity, exchange identity, cap, or execution instruction.

## Durable authority

PostgreSQL stores one immutable intent and one immutable attachment event.
The source row is locked while eligibility and its evidence SHA-256 are
revalidated. A unique source constraint prevents duplicate attachment. The
idempotency record binds actor, roles, correlation, exact source observation,
source evidence SHA-256, fixed reason, and both acknowledgements. An exact
replay returns the original record; changed reuse conflicts.

The durable root and source identities are both the selected source
`client_order_id`. The reason is
`FULL_FILL_OPPOSITE_ONE_CONTRACT`. State is `ATTACHED`. UPDATE and DELETE are
rejected by database triggers.

## API and RBAC

- `GET /api/v1/futures/order-operations/{client_order_id}/follow-up-intent`
  requires `analytics:read` and performs only PostgreSQL reads.
- `POST /api/v1/futures/order-operations/{client_order_id}/follow-up-intent`
  requires `order:create`, an idempotency key, a correlation ID, fixed
  `attach_futures_follow_up_intent` operator intent, the exact source
  observation/hash binding, and both literal acknowledgements.

The installed local feature flag is
`COINBASE_ADMIN_API_OPERATOR_FUTURES_FOLLOW_UP_INTENT_ENABLED=1`. This
feature remains available in Controlled-live and explicitly requested No-live
postures because it has no Coinbase adapter and conveys no live authority.

## Safety boundary

Attachment does not inspect current fills, schedule work, react to fills,
Preview, Create, Cancel, Close, Reduce, reconcile Coinbase, or call any
exchange endpoint. Future fill-triggered activation and materialization belong
to the separately authorized successor goal and must freshly revalidate source
fill/terminal state, policy, caps, identity, claims, and live authority.

Raw Coinbase responses, raw exchange order IDs, portfolio UUIDs, exception
messages, secrets, private identifiers, and withheld text are neither stored
nor returned.

## Historical translation

Historical source material inspected:

- `origin/prod:core/order_engine.py`
- `origin/prod:dashboard_server.py`

Only the root/source linkage and opposite-side follow-up concept were
translated. The legacy WebSocket command surface, automatic order-engine
trigger, browser authority, implicit background execution, direct Coinbase
access, retry behavior, and raw exception handling were not copied.

## Focused validation

Focused validation covers pure eligibility/derivation, exact generated route
models, backend RBAC and feature gating, immutable PostgreSQL persistence,
payload-bound idempotency, source-change rejection, duplicate prevention,
generated frontend contracts, strict readback validation, explicit
acknowledgements, lifecycle-manager configuration, and the authenticated
Futures order-detail E2E workflow.

The E2E exchange client is synthetic and no-network. The attachment portion
asserts zero Coinbase calls and zero child creation.

Terminal closeout passed 116 focused frontend tests, the full frontend release
gate (122 files and 1,769 unit tests plus authenticated deployment/E2E), the
full backend regression (1,286 parallel-safe plus 890 serial tests), and both
independent audits. Current official CFM routes and pinned SDK signatures show
no established published maintenance-era break. The successor must still
perform a documented compatibility gate and fail closed on schema drift.
