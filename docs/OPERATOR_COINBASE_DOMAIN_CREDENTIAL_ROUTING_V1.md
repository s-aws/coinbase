# Operator Coinbase Domain Credential Routing V1

## Outcome

The installed Controlled-live operator runtime uses two independent,
backend-only Coinbase clients:

- Spot uses the approved Test-profile Secrets Manager binding
  `coinbase/Test`.
- Futures uses the Default-profile Secrets Manager binding `coinbase`.

The runtime rejects missing, changed, or conflated bindings before serving
Futures routes. Direct `COINBASE_API_KEY` and `COINBASE_API_SECRET` values are
not used to select either installed operator profile.

## Failure diagnosis and preservation

The bounded read-only diagnosis invoked API-key permissions, portfolio
catalog, CFM balance summary, and CFM positions exactly once each with the
canonical Default binding. All four calls returned. The former CFM positions
HTTP-forbidden result was therefore caused by the installed process routing
the Spot/Test credential into Futures, not by Default-profile CFM entitlement
or endpoint access.

The terminal predecessor
`operator_futures_manual_order_lifecycle_v1` remains unchanged and readable.
The installed manual-order route now uses the distinct successor
`operator_futures_manual_order_lifecycle_default_profile_v2`, whose cycle and
Preview/Create/reconciliation/Cancel accounting begins at zero. The successor
does not reinterpret, reset, or transfer any predecessor allowance.

## Runtime boundary

The operator launcher removes direct Coinbase credentials, installs the exact
Spot/Test and Futures/Default secret selections, and retains AWS credential
discovery only for the backend process. Spot credential hydration occurs
through the existing canonical runtime. Futures credential resolution uses a
controlled mapping that omits the hydrated Spot key and generic Spot secret
selection before constructing its independent pinned-SDK wrapper.

Both clients remain backend-only. The frontend receives neither credential
selection nor secret values. No-live startup removes generic and
domain-specific Coinbase credential variables. Linux starts the frontend with
an empty environment, and the Windows launcher clears every credential
selection before starting the frontend.

Startup, page loading, generated-contract validation, and ordinary readback
make no Coinbase call. An operator-triggered Futures eligibility refresh or
exchange action still requires backend RBAC, the current Controlled-live
lease and service decision, a durable revision/idempotency claim, the
Default-profile eligibility gates, fixed V3 policy and caps, explicit
confirmation, and the route's remaining call allowance.

## Historical comparison

`origin/prod:dashboard_server.py` and
`origin/prod:external/coinbase_client.py` were checked as historical account
and Futures call references. They do not contain a reusable multi-profile
operator credential boundary. The current implementation therefore keeps the
canonical backend wrapper while adding explicit domain client composition; it
does not restore the legacy WebSocket, browser authority, background loop, or
generic credential sharing.
