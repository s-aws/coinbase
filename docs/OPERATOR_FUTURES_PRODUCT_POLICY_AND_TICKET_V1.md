# Operator Futures Product Policy And Ticket V1

Goal `operator_futures_product_policy_and_ticket_expansion_v1` turns
configured Default-profile CFM product scope into an authenticated operator
workflow. It is independent from the completed fixed-product manual lifecycle.

## Operator workflow

The Admin UI reads `GET /api/v1/futures/product-ticket` from PostgreSQL. An
administrator may approve, enable, disable, retire, or select exactly one of:

- `AVP-20DEC30-CDE`
- `BIP-20DEC30-CDE`

Each policy command binds the expected policy revision, exact product,
authenticated actor and roles, fixed operator intent, idempotency key,
correlation, explicit confirmation, and a SHA-256 of the operator reason.
Enablement is local policy only and never establishes exchange eligibility.
Policy revision, command, and event history are protected by PostgreSQL
append-only triggers. The fixed intent and explicit confirmation are included
in the command payload hash and retained as minimized audit evidence.

After one enabled product is selected, a trader may request one of ten
goal-global, no-retry eligibility cycles. The backend resolves the selection
before any Coinbase read and invokes each Default-profile category at most
once:

1. API-key permissions
2. portfolio catalog
3. exact selected product
4. exact selected-product best bid/ask
5. Futures positions
6. Futures margin/collateral

The backend derives one BUY contract, increments, contract size, expiry,
fresh post-only limit, product margin rates, required margin, and strict
opening/exposure/turnover evidence. The browser supplies none of those terms.
The UI requires separate acknowledgement of the no-retry cycle, goal-global
ten-cycle limit, and fail-closed unknown/unsuccessful result before forwarding
the generated request.

## Single-use execution

Only a fresh, exact, policy-bound candidate may atomically claim the execution
allowance. The route permits:

- one Preview;
- one identical Create only after an accepted, error-free Preview;
- one exact reconciliation;
- at most one Cancel solely when that exact child is authoritatively
  nonterminal.

There are zero retries, fallbacks, redirects, alternate identities, second
children, product expansion, or Spot/Futures authority transfer. Every
applicable call boundary is claimed before invocation. Unknown outcomes consume
the applicable allowance.

The selected candidate remains under strict `<100`, `<150`, and `<300` USDC
opening, exposure, and branch-turnover ceilings. PostgreSQL persists only fixed
diagnostics, call accounting, hashes, public contract terms, correlation, and
audit evidence. Raw responses, exception messages, credentials, private
portfolio identity, and raw Preview or exchange identifiers are excluded.
Lifecycle idempotency is goal- and request-bound. Completed eligibility
responses are stored as append-only sanitized snapshots so a lost-response
retry returns the exact original result even if a later cycle has advanced the
current goal row.

The local policy/ticket read is available without resolving Coinbase
credentials. Default-profile client resolution is deferred until an authorized
eligibility or execution boundary, while readback exposes a fixed blocked
execution-posture diagnostic when credentials or live admission are absent.

## Maintenance compatibility checkpoint

Coinbase Futures maintenance ended before this goal's validation. Current
official Advanced Trade documentation was checked for Preview Order, List/Get
Products, Futures trading, current margin windows, and intraday margin
settings. Post-maintenance Default-profile read evidence continued to match
the documented shapes. No breaking API change was established.

The implementation nevertheless fails closed on schema drift. Product
increments, contract details, session state, FCM venue/risk ownership, margin
rates, and Preview response acceptance are validated from documented fields;
receipt time and unrelated proxy fields are not substituted.

The installed terminal proof used four of ten no-retry eligibility cycles.
Every cycle invoked each of the six approved Default-profile read categories
exactly once. Value-blind remediation separated margin envelope, balance,
setting, window, kill-switch, and available-margin boundaries without
persisting a field value or exception message. The fourth cycle established
`operator_futures_product_ticket_margin_window_documented_but_v3_ineligible`:
Coinbase returned a documented current-margin-window state that did not match
the exact operator-defined V3 profile/state pair. This is not evidence of an
API schema change.

The backend therefore stopped with six cycles unused, no eligible candidate,
and Preview, Create, reconciliation, and Cancel all `NOT_RUN`. Proceeding
would require changing the exact V3 policy rather than correcting documented
schema compatibility, which is outside this goal.

## Historical translation

`origin/prod:dashboard_server.py` and
`origin/prod:external/coinbase_client.py` were inspected for historical product
selection and manual-order concepts. Their browser/WebSocket payload authority,
direct Coinbase invocation, retry behavior, and unsanitized exception handling
were not copied. The current Admin API, PostgreSQL policy, canonical
Default-profile client, generated contract, and backend executor remain the
only authority.
