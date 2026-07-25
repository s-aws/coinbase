# Operator Futures Position Close/Reduce V1

Goal ID:
`operator_futures_position_close_reduce_and_reconciliation_v1`.

## Operator outcome

An authenticated operator can select one backend-issued Futures
`position_key`, refresh exact Default-profile eligibility, review
margin/collateral and Close evidence, and explicitly choose one mutually
exclusive action: full Close or bounded one-contract Reduce. The same
coordinator reconciles the resulting exact order and exact position and may
Cancel only that exact order when authoritatively nonterminal.

## Backend authority

PostgreSQL owns a goal-global ten-cycle budget, one append-only claim for each
approved category per cycle, immutable selected-position evidence, exact
revision/idempotency, the single Close-or-Reduce claim, order and position
reconciliation claims, conditional Cancel, restart recovery, fixed sanitized
diagnostics, and audit correlation. Any claimed boundary recovered after
restart becomes unknown and cannot replay.

Each command idempotency key is durably bound to the exact selected position,
expected revision, action mode, actor/roles, operator intent, and fixed
confirmations. Reuse with any conflicting payload fails closed rather than
being represented as a successful replay.

Eligibility uses only:

- API-key permissions;
- Default portfolio catalog;
- Futures positions;
- selected product metadata;
- selected product best bid/ask;
- the established Futures margin/collateral snapshot.

Every category is invoked at most once per cycle with no retry or fallback.
The backend hashes private portfolio and exchange identities. Raw responses,
private identifiers, exception messages, and withheld text are never durable
or part of operator readback.

The production CFM positions SDK may omit portfolio identity from each
position row. In that documented shape, the public `position_key` uses the
credential-scoped Default-profile namespace while the configured Default
portfolio UUID is separately verified and SHA-256-bound. A returned private
portfolio identity that conflicts with that credential binding fails closed.

## Execution boundary

The backend derives closing side from authoritative LONG/SHORT position state.
Full Close invokes Coinbase Close Position with size omitted. Bounded Reduce
uses exact size `1` only when authoritative contracts exceed one. The accepted
Close acceptance requires Coinbase's documented success flag and nonblank
returned order identifier; the following exact-order reconciliation proves
the bound client identity, product, side, and terminal state. One exact-position
read must then prove the expected side and remaining integral contract count.
At most one Cancel is permitted solely when the exact order is
authoritatively nonterminal.

The browser forwards only the opaque selected position, `CLOSE_FULL` or
`REDUCE_ONE_CONTRACT`, exact revision, and fixed operator acknowledgements.
It cannot choose portfolio identity, product, side, size, exchange identity,
retry policy, or an alternate position.

## Current live boundary

The installed Default-profile credential/account currently returns the fixed
`operator_futures_manual_futures_positions_http_forbidden` classification for
the documented CFM positions category. No Goal 11 live selection exists, so
Close, Reduce, reconciliation, and Cancel allowances remain unconsumed. This
is an account/credential eligibility blocker and does not require broader
authorization.

## Historical and current sources

`origin/prod:dashboard_server.py` and
`origin/prod:external/coinbase_client.py` supplied historical refresh and
close-side context only. Coinbase's current documented Close Position, Get
Futures Position, and Cancel Orders endpoints and
`coinbase-advanced-py==1.8.4` define the current boundary. No legacy WebSocket
authority, generic Futures command path, background action, retry, fallback,
or raw-response surface is restored.
