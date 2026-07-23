# Operator Spot Automation Transport Explainability V13-V15

Goal:
`operator_spot_automation_transport_explainability_and_successor_proof_v13_v15`.

Status: implementation complete and validation in progress. No V13-V15
network-readiness probe, Coinbase eligibility read, Preview, Create, or Cancel
has run. All V13-V15 allowances and the separate 10-cycle budget remain
unconsumed.

## Preserved predecessor boundary

R1-R12 and every V1-V12 artifact, identity, event, allowance, call record, and
documented hash remain unchanged. R8 content and its hash remain inaccessible.
The three prior `TRANSPORT_UNKNOWN` results are not reclassified. V13-V15 use
new goal rows, candidate identities, idempotency keys, call allowances, and a
separate PostgreSQL cycle ledger.

## Fixed Preview invocation classification

The future Preview boundary uses only the caller-owned stage, exception type,
and returned HTTP status integer. It never reads exception messages, nested
exception text, response bodies, raw responses, raw Preview identifiers,
secrets, or private identifiers.

Fixed prospective classes cover request composition, unknown SDK invocation,
direct DNS resolution failure, direct TCP connection failure, connect timeout,
TLS or certificate failure, proxy failure, read timeout, connection reset,
returned HTTP client/server/redirect response, response decoding, response
schema validation, and otherwise unknown transport. Generic Requests
`ConnectionError` remains `TRANSPORT_UNKNOWN` because its type alone cannot
prove whether DNS, TCP, or TLS failed. This conservative rule is prospective;
it does not reinterpret V10-V12.

The installed `coinbase-advanced-py==1.8.4` path performs one
`requests.Session.request`, raises returned HTTP errors, and decodes JSON. The
canonical wrapper requires a bounded timeout, zero configured retries, zero
followed redirects, direct transport with environment proxies disabled, TLS
verification, and value-blind SDK logging.

## No-HTTP network readiness

The authorization request must carry the backend-enforced literal
`confirm_one_no_http_transport_readiness_sequence: true`. The operator reason
and fixed operator-intent header identify the same V13-V15 transport proof;
an older V10-V12 request shape is rejected before any probe. The active route
selects only the separate V13-V15 ledger and never falls back to or consumes
an actionable V10-V12 predecessor allowance.

Before a V13-V15 eligibility cycle, the backend durably claims one separate
goal-global cycle. It may then perform exactly one logical DNS resolution, one
TCP connection to one selected resolved address, and one TLS handshake with
SNI for `api.coinbase.com`. The same connected socket is used for TCP and TLS.
No application bytes are sent, so the probe cannot issue an HTTP or Coinbase
API request. Only fixed stage statuses, fixed failure class, exact per-stage
counts, and a hash of those public/fixed fields are persisted.

A failed readiness sequence closes the cycle with zero Coinbase API calls,
creates no definition, run, plan, child, candidate, or Preview claim, and
leaves every live allowance unconsumed. A restart while a probe or post-probe
pre-materialization cycle is in progress closes that cycle as unknown; it does
not replay the probe or approved reads.

## Candidate and live boundaries

After readiness passes, the existing policy-revision-5 atomic market-snapshot
coordinator remains authoritative. It may read each approved category once per
cycle without individual or page retry: API-key permissions, portfolio
catalog, account/wallet balances, product metadata, documented Get Market
Trades with same-response bid/ask, fee summary, exact-order reconciliation,
and the account-wide active Spot-order catalog.

The backend atomically persists final price, size, fee-reserved cap, evidence,
candidate identity, immutable plan, and one-use Preview claim from that fresh
snapshot. BTC-USDC, the approved Test portfolio, one BUY child, post-only best
bid, and submitted plus possible-execution notional strictly below 3.10 USDC
remain unchanged. Create must be identical to the first accepted error-free
Preview; only that exact authoritatively nonterminal child may be cancelled.

V13 is initially available. V14 and V15 are fail-closed in backend selection
until a post-terminal remediation adds a reviewed official-documentation-backed
correction for that exact version. A rejection or unknown result alone cannot
unlock a speculative successor.

Official contract references:

- Coinbase Advanced Trade base endpoint and authentication:
  <https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api>
- Coinbase Preview Order:
  <https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders>
- Coinbase Advanced Python SDK Preview helpers:
  <https://coinbase.github.io/coinbase-advanced-py/>
- Requests exception hierarchy:
  <https://requests.readthedocs.io/en/latest/_modules/requests/exceptions/>

There is no same-candidate replay, retry, fallback, redirect, alternate child,
second Create, fan-out, scheduler, sweep, ladder, Futures action, funding or
transfer action, product expansion, unrelated order, or parallel placement
path.

Historical `origin/prod` references remain `core/order_engine.py` and
`core/stealth_order_manager.py`. They contain no analogous Preview transport
contract; the implementation therefore extends the current canonical Admin
API and Coinbase wrapper rather than translating legacy dashboard behavior.
