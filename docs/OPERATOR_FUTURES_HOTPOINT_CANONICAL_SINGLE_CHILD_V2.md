# Operator Futures Hotpoint Canonical Single Child V2

Goal ID: `operator_futures_hotpoint_canonical_single_child_v2`.

This is independent Goal 13 in the authorized operator-workflow sequence. It
turns the existing Futures side of the routed Hotpoint workspace into one
backend-owned, explicitly operator-triggered, canonical US CFM child lifecycle.
This document is the implementation and operations contract; it does not by
itself grant exchange authority.

Status: completed independent Goal 13 — operator-ready Controlled-live closeout.
Implementation, generated-contract synchronization, focused and full
backend/frontend gates, installed deployment validation, independent safety
and blind-contextless audits, and persistent Controlled-live handoff pass.
The installed source-parent and inherited flat-position prerequisites fail
closed, so all ten eligibility cycles and every
Preview/Create/reconciliation/Cancel allowance remain unconsumed. No Goal 13
Coinbase call or live proof occurred. The terminal workflow does not
manufacture source provenance or transfer predecessor authority.

## Goal 9 preservation and isolation

The completed Goal 9 identity remains
`operator_hotpoint_control_and_single_placement_v1`. Every Goal 9 Spot or
Futures control row, command, claim, event, allowance, audit correlation, and
terminal result remains historical evidence and must not be migrated, rekeyed,
copied, merged, deleted, or reinterpreted as Goal 13 authority.

Goal 13 uses a separate PostgreSQL ledger, goal row, command/cycle identities,
idempotency namespace, candidate identity, and
Preview/Create/reconciliation/Cancel allowances. Its lifecycle transactions
reuse the canonical Futures lifecycle serialization lock; separation is
provided by the distinct durable goal and ledger identities, not by a claimed
dedicated advisory-lock identity. A Goal 9 claim never consumes or grants a
Goal 13 allowance, and a Goal 13 claim never mutates Goal 9.
Reusable pure policy and canonical exchange adapters may be shared, but
durable authority and call accounting may not be shared.

The existing Spot Goal 9 workflow stays on its current policy and executor.
Selecting `FUTURES` in `/hotpoint` resolves Goal 13; it must never fall back to
the Spot service, Spot portfolio, Spot caps, or the Goal 9 allowance.

## Installed source-parent prerequisite

Goal 13 may generate only its one-contract child. It has no authority to
manufacture the source parent required by the trigger. The installed routed
Futures proof workflows create exactly one contract and safely close that
proof; the Orders refresh can reconcile exchange truth but cannot infer
system ownership or create an `order_parent` provenance row. Consequently,
the current installed state has no legitimate path that can produce the
required nonterminal, backend-registered Default-profile AVP root with more
than three contracts of remaining capacity and reconciled fill-ledger
evidence. Goal 13 must show an empty eligible-parent state, cannot ARM or RUN,
and leaves Preview/Create/Cancel unconsumed unless such a root already exists
from an independently authorized canonical source.

The inherited exact-V3 eligibility rule also requires zero current AVP
position. Three BUY trigger fills are coherent with that rule only when they
flattened an existing short (or separately authorized, reconciled activity
returned the account to flat). A future predecessor must prove that coherent
post-fill state, or a separately authorized successor must replace the
zero-position rule with cap-safe current-position-plus-child exposure math.
Neither change is authorized by Goal 13.

## Fixed authorization boundary

The backend must enforce all of the following as literals or typed policy:

| Boundary | Goal 13 value |
| --- | --- |
| Domain | US CFM Futures |
| Credential/profile | credential-bound `Default` / `DEFAULT` profile |
| Product | `AVP-20DEC30-CDE` only |
| Trigger side and child side | `BUY` only |
| Child size | exactly one contract |
| Order | post-only `LIMIT_GTC` / `limit_limit_gtc` |
| SDK | `coinbase-advanced-py==1.8.4` |
| Opening reference notional | strictly `<100 USDC` |
| Maximum exposure reference notional | strictly `<150 USDC` |
| Buffered-close reference notional | strictly `<150 USDC` |
| Branch turnover reference notional | strictly `<300 USDC` |
| Close buffer | established `1.20` multiplier |
| Eligibility budget | at most ten goal-global cycles |
| Preview | at most one |
| Create | at most one, only after accepted Preview |
| Exact reconciliation | at most one later, one-page `list_orders` read |
| Cancel | at most one, only for the exact reconciled nonterminal child |

Opening is the canonical one-contract reference notional. Maximum exposure is
the canonical concurrent-exposure reference. Buffered close is maximum
exposure multiplied by `1.20`, and branch turnover is opening plus buffered
close. All four values must be recomputed and checked by the backend from the
same candidate evidence; the current Hotpoint order notional alone is not a
valid substitute for branch turnover.

There are zero retries, fallbacks, redirects, alternate credentials, alternate
profiles, alternate products, second candidates, second children, SELL
openings, fan-out, scheduler activation, automatic fill-triggered exchange
execution, Close, Reduce, funding, transfer, or other exchange mutations.
Unknown outcomes consume the applicable claimed allowance.

## Call-free navigation and controls

Page loading, ordinary navigation, changing the UI domain selector, polling
readback, listing eligible parents, reading mutation results, health checks,
startup, enable/disable, arm/disarm, and local trigger evaluation make no
Coinbase call. In particular, an eligible three-fill trigger never invokes an
exchange boundary merely because it exists or is displayed.

Only these explicit authenticated operator actions may reach Coinbase:

1. `RUN_ONCE`, after all local Hotpoint gates pass, may run one approved
   eligibility cycle and then the single-use Preview/conditional Create path.
2. `SAFE_CLOSEOUT`, after a Create accepted or became unknown, may run the one
   exact `list_orders` reconciliation and a conditional exact-child Cancel.

Generated frontend code only forwards the explicit action, expected revision,
idempotency key, correlation, fixed intent, and required acknowledgements.
The browser cannot provide or alter portfolio, product, side, size, price,
time in force, post-only policy, cap evidence, trigger evidence, candidate
identity, Preview identity, exchange identity, retry behavior, or fallback
behavior.

## BUY-only Hotpoint trigger

The operator first selects one eligible, system-owned Default-profile
`AVP-20DEC30-CDE` BUY parent by canonical `client_order_id`, enables the
Futures kill switch, and arms one bounded window. Arming starts an exact
60-second window. The backend may expose trigger readiness only after it finds
three qualifying durable fill-ledger rows within that window.

A qualifying row must:

- belong to the exact selected `client_order_id`;
- identify `AVP-20DEC30-CDE`;
- have side exactly `BUY`;
- have positive quantity and price;
- have `reconciliation_status=RECONCILED`;
- be recorded no earlier than the armed-window start and before its expiry;
  and
- fall in the same deterministic 0.5-percent log-spaced Hotpoint bucket as
  the other two qualifying rows.

Raw feed events, unreconciled rows, wrong-product rows, SELL rows, related but
different client identities, nonpositive quantities, and fills outside the
window do not count. The backend uses the earliest three qualifying rows in a
deterministically selected bucket and latches the trigger once, so later fills
cannot change already-qualified trigger evidence. Their prices, including their
mean, are trigger evidence only and must not become or modify the final
exchange price. A generated Goal 13 child is not eligible to trigger another
Goal 13 child, so the one-child boundary cannot cascade.

The trigger is durable local evidence, not trading eligibility. `RUN_ONCE`
must re-read it under the shared canonical Futures lifecycle serialization
lock and then establish fresh Coinbase eligibility before any Preview claim.

## Fresh six-category eligibility

One explicit `RUN_ONCE` may start one durably counted eligibility cycle after
the local trigger is ready. Across the goal there are at most ten cycles. Each
cycle binds one correlation, command identity, selected parent, trigger
evidence hash, Default portfolio hash, policy revision, and candidate revision.

Each category may be invoked at most once in a cycle, with no individual or
page retry:

1. API-key permissions.
2. Portfolio catalog.
3. Exact `AVP-20DEC30-CDE` product metadata.
4. Exact-product best bid/ask.
5. US Futures positions.
6. US Futures margin/collateral.

The margin/collateral category retains the established fixed expansion: one
balance-summary read, one intraday-margin-setting read, and one
current-margin-window read for each of
`MARGIN_PROFILE_TYPE_RETAIL_REGULAR` and
`MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1`. Thus a complete cycle has six
logical categories and nine authenticated GET boundaries. Every subread is
individually accounted and remains no-retry.

Eligibility must prove, from one coherent cycle:

- view and trade permissions;
- exactly one credential-bound catalog row whose alias/type are
  `Default`/`DEFAULT`;
- the same private portfolio binding as the Goal 13 configured binding,
  persisted publicly only as SHA-256;
- exact CFM product, venue, contract, expiry, increment, and risk-manager
  fields;
- a valid one-contract size;
- fresh, positive, uncrossed exact-product bid/ask evidence;
- no disallowed existing `AVP-20DEC30-CDE` exposure;
- the exact approved margin-window/profile state, positive available margin,
  and sufficient worst-case margin;
- the official session and maintenance gates below; and
- all strict `<100`, `<150`, and `<300 USDC` cap relationships.

Market and candidate evidence must remain no more than 30 seconds old at the
Preview claim. Future-dated, missing, ambiguous, cross-cycle, or stale
evidence fails closed. An unsuccessful, incomplete, stale, ineligible, or
unknown cycle consumes only that cycle. It creates no candidate and leaves
Preview/Create/reconciliation/Cancel unclaimed.

## Official session, maintenance, and time-in-force guard

The exact product response is authoritative for the immediate session gate.
Before candidate creation, the backend requires:

- `trading_disabled`, `view_only`, and `cancel_only` to be false;
- `future_product_details.twenty_four_by_seven` to explicitly prove the
  product's 24x7 session compatibility for this GTC proof;
- `fcm_trading_session_details.is_session_open` to be true;
- a documented and internally consistent session state;
- no current product maintenance interval;
- no documented closed or maintenance reason;
- a nonexpired contract; and
- positive, increment-valid product and book evidence.

Coinbase documents weekly, quarterly, and possible ad-hoc derivatives
maintenance windows. It also documents that GTC/GTD eligibility during
extended hours depends on 24x7 participation. Receipt time, local wall-clock
assumptions, a successful best-bid/ask read, or an unrelated product field may
not be substituted for documented session evidence. If maintenance, session
state, after-hours order-entry authority, or `GOOD_UNTIL_CANCELLED`
eligibility cannot be proved for the Default profile and exact product, the
cycle is ineligible before Preview is claimed.

The backend rechecks the stored session timestamp, candidate freshness,
execution lease, and fixed policy immediately before both Preview and Create.
It performs no extra unapproved refresh. If the evidence becomes stale after
Preview, Create remains unclaimed and the workflow stops; Preview is not
replayed.

## Immutable candidate, Preview, and identical Create

After all six categories pass, the backend derives one immutable BUY
candidate using the reused canonical product-ticket formula: the limit price
is the fresh exact-product best bid minus exactly one product price increment,
quantized to that increment and strictly positive. It is not the Hotpoint fill
mean. The backend owns the exact contract count, limit price, post-only flag,
`GOOD_UNTIL_CANCELLED` configuration, canonical `client_order_id`, trigger
binding, Default portfolio hash, product/session evidence, margin evidence,
cap calculations, and candidate SHA-256. The frontend supplies none of these
terms.

The backend then:

1. atomically persists the immutable candidate and claims the sole Preview
   allowance;
2. invokes `preview_order` once inside the canonical Futures Preview scope;
3. validates the pinned SDK's shallow raw envelope before recursive
   normalization;
4. accepts only a documented, error-free response whose economics and order
   terms match the immutable candidate;
5. retains the raw Preview identity only in process memory and persists only
   its SHA-256;
6. atomically claims the sole Create allowance only after accepted Preview;
   and
7. invokes `create_order` once with the identical product, BUY side, one
   contract, limit price, post-only `limit_limit_gtc`, canonical
   `client_order_id`, and ephemeral Preview identity.

A rejected or unknown Preview consumes Preview and leaves Create unconsumed.
No candidate term may change after the Preview claim. A Create rejection or
unknown consumes Create. An accepted Create stores fixed evidence and, when
available, the exchange-order-ID SHA-256, never the raw exchange ID.

The Preview and Create steps occur in the same `RUN_ONCE` process flow because
the raw Preview identity is intentionally not durable. A restart after Preview
acceptance but before Create is claimed cannot resume Create and cannot replay
Preview; it terminalizes with Create unconsumed.

## Later exact reconciliation and conditional Cancel

`SAFE_CLOSEOUT` is a separate, explicit operator command. It is available
after an accepted Create and after a claimed Create whose outcome is unknown,
because an unknown Create may still have produced the exact child.

The command claims the sole reconciliation allowance and performs exactly one
`list_orders` SDK call. The backend supplies all filters:

- `product_ids=[AVP-20DEC30-CDE]`;
- `product_type=FUTURE`;
- side `BUY`;
- order type `LIMIT`;
- time in force `GOOD_UNTIL_CANCELLED`; and
- a narrow inclusive/exclusive creation-time range derived from the durable
  Create/candidate timestamps.

Current CDP keys are credential-bound to their portfolio, and Coinbase
documents the order-level `retail_portfolio_id` field as deprecated. Goal 13
therefore does not send that field. Default-profile authority is instead
proven before the attempt by the canonical Default credential, the configured
UUID's exact portfolio-catalog match, catalog `type=DEFAULT`, and the durable
portfolio hash bound to the candidate and child. The configured raw UUID
exists only inside the backend process; only its SHA-256 may be durable or
public. The page limit must be large enough for the bounded scope, but exactly
one page is authorized. If Coinbase reports `has_next=true`, returns an
invalid envelope, or cannot prove
completeness, the reconciliation result is `UNKNOWN`; no second page or retry
is permitted. Coinbase may return a cursor on a complete final page. A cursor
is therefore allowed when `has_next=false`, is never followed, and does not by
itself make that final page ambiguous.

The backend scans that one page for the exact durable `client_order_id`.
Success requires exactly one match and exact agreement on product, BUY side,
one-contract size, limit price, LIMIT configuration, post-only evidence when
returned, `GOOD_UNTIL_CANCELLED`, and the candidate binding. If Create
persisted an exchange-ID SHA-256, the discovered raw ID must hash to it. If an
unknown Create persisted no exchange hash, the single exact match may
establish that hash. Zero matches, duplicate matches, conflicting terms,
unknown status, or a hash mismatch fail closed.

The raw exchange ID is kept only in the reconciliation call's process-local
result. If the exact child is already terminal, reconciliation records
`cancel_disposition=NOT_REQUIRED` and `Cancel=NOT_REQUIRED`. If it is in the
fixed documented cancelable
nonterminal allowlist, the repository atomically records successful
reconciliation and claims the sole Cancel allowance before the in-memory raw
ID can be used. The canonical Futures Cancel scope then invokes
`cancel_orders` once for only that raw ID. No other order may be included.

An unknown or incomplete reconciliation consumes reconciliation and leaves
Cancel unconsumed. A claimed Cancel that becomes rejected or unknown consumes
Cancel. No later `SAFE_CLOSEOUT` may repeat either claimed boundary.
Coinbase's per-order Cancel success reports that the cancel request was
initiated; it is not terminal cancellation evidence. Goal 13 records that
fixed accepted-request state and requires later authoritative order truth
before any terminal-cancel claim.

## Durable ledger, idempotency, and restart recovery

The separate Goal 13 PostgreSQL ledger must durably retain:

- the singleton control revision, kill switch, armed window, selected parent,
  trigger state, and fixed policy;
- append-only control and operator-command audit records;
- at most ten command/eligibility cycles with payload and idempotency hashes;
- one claim per eligibility category and each fixed margin subread;
- one immutable candidate and canonical child `client_order_id`;
- independent Preview, Create, reconciliation, and Cancel claim/state rows;
- exact call-boundary entry and fixed terminal outcome accounting;
- portfolio, trigger, candidate, Preview, and exchange identity hashes;
- fixed value-blind diagnostics, authenticated actor/roles, correlation, and
  audit IDs; and
- immutable terminal snapshots used for idempotent readback.

The `RUN_ONCE` idempotency identity must be bound to the actor, roles,
correlation, expected control revision, selected parent, armed window, fixed
operator intent, acknowledgements, and payload hash. `SAFE_CLOSEOUT` receives
its own equivalently bound identity. Exact completed replay reads the original
sanitized snapshot and makes no Coinbase call. A changed payload or actor
fails closed.

Every Coinbase boundary is durably `CLAIMED` immediately before the canonical
wrapper may enter the SDK. Restart recovery is conservative:

- an in-flight eligibility category becomes `UNKNOWN`; its cycle remains
  consumed and is never replayed;
- a claimed Preview becomes `UNKNOWN` and consumes Preview;
- a Preview whose accepted result was not atomically committed with the Create
  claim remains durably `CLAIMED`, recovers as Preview `UNKNOWN`, and leaves
  Create unconsumed because the raw Preview identity was withheld;
- a claimed Create becomes `UNKNOWN` and consumes Create, while the separate
  exact reconciliation allowance may remain available;
- a claimed reconciliation becomes `UNKNOWN` and consumes reconciliation,
  leaving Cancel unconsumed; and
- a claimed Cancel becomes `UNKNOWN` and consumes Cancel.

Recovery must first disable delegated execution authority and close any active
window. It may expose only the action justified by the recovered durable
state. It never creates a new claim, repeats an SDK call, substitutes another
identity, or borrows an allowance from Goal 9 or another goal.

## Privacy and public readback

The ledger and operator contract may retain only allowlisted public terms,
fixed states and diagnostics, exact counters, hashes, and audit evidence.
They must never persist, return, or log:

- raw Coinbase responses or response bodies;
- raw Preview IDs;
- raw exchange order IDs;
- raw private portfolio UUIDs;
- API keys, secrets, authorization material, or owner-only lease values;
- exception messages or withheld text; or
- rejected private field values.

SDK exception classification uses exception types, fixed boundary metadata,
and numeric HTTP status classes only. The UI may display the canonical
`client_order_id` and hashed exchange evidence. A raw exchange ID obtained by
Create or `list_orders` exists only long enough to complete the same
in-process validation or exact Cancel and is then discarded.

Public readback must show environment, `Default` profile label/type,
`AVP-20DEC30-CDE`, BUY, one contract, post-only LIMIT/GTC, all three caps,
trigger count/window, category/call counts, candidate freshness, session and
maintenance compatibility summary, allowance states, fixed terminal
diagnostic, allowed actions, and audit correlation. The immutable backend
candidate/hash retains the allowlisted contract-expiry, session-state, 24x7,
after-hours, closed-reason, and maintenance-boundary terms used by the atomic
rechecks; browser readback intentionally summarizes them as
`OPEN_24X7_GTC` plus fixed eligibility/freshness diagnostics. Button
visibility is never authority.

## Feature flags and installed posture

Goal 13 is available only when all of these independent gates pass:

- `COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED=1` exposes the routed Hotpoint
  workspace and local control contract;
- `COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED=1` enables the
  Goal 13 Futures runtime and exchange adapters;
- `COINBASE_EXECUTION_ENABLED=1` supplies the installed master Controlled-live
  opt-in and owner-generated execution lease;
- the canonical Default-profile credentials and private portfolio binding are
  configured;
- backend live-service posture admits the exact Futures Preview, Place, Read,
  and Cancel routes/scopes;
- the current actor holds the required backend RBAC; and
- the explicit command, revision, acknowledgements, policy, trigger,
  eligibility, allowance, and audit gates pass.

The review manager sets the dedicated Goal 13 flag only in Controlled-live
posture and sets it to `0` in explicit No-live posture. Missing, malformed, or
false flags fail closed before client construction or claim creation.
`COINBASE_EXECUTION_ENABLED=1` is necessary but never sufficient by itself.

## Operator sequence

1. Open `/hotpoint`, select `FUTURES`, and review the call-free Goal 13
   readback.
2. Select one backend-listed Default-profile `AVP-20DEC30-CDE` BUY parent by
   `client_order_id`.
3. Enable the Goal 13 kill switch with the exact one-window and
   unknown-consumption acknowledgements.
4. Arm the selected parent. The UI shows the 60-second window and reconciled
   fill count from PostgreSQL.
5. After three qualifying fills are latched, review profile, product, side,
   one-contract scope, strict caps, session posture, cycle budget, and unused
   call allowances.
6. Explicitly invoke `RUN_ONCE`. The backend performs one no-retry
   six-category cycle. If exact fresh eligibility fails, no Preview or
   mutation occurs.
7. If eligibility passes, the backend derives and displays the immutable
   candidate, consumes one Preview, and conditionally consumes one identical
   Create. The UI resolves the command only from durable correlation-bound
   readback.
8. If Create is accepted or unknown, review the exact child and explicitly
   invoke `SAFE_CLOSEOUT`.
9. The backend performs the one-page exact-client reconciliation. It cancels
   only the exact child if authoritatively cancelable and otherwise reports
   terminal, not-required, or unknown evidence.
10. Leave the kill switch disabled and retain the complete sanitized terminal
    audit record.

The frontend must use a session-persistent mutation freeze for `RUN_ONCE` and
`SAFE_CLOSEOUT`. It clears the freeze only after the exact correlation,
action, revision, and terminal backend snapshot agree. Refreshing the page
does not replay an action.

## Required validation

Focused TDD and closeout validation must cover at least:

- Goal 9 row, allowance, event, and terminal-evidence preservation;
- separate Goal 13 ledger, goal identity, idempotency, and restart recovery
  under canonical Futures lifecycle serialization;
- BUY-only parent selection and rejection of SELL or wrong-domain parents;
- exactly three reconciled same-parent/same-product/same-bucket fills inside
  60 seconds, including every exclusion and expiry boundary;
- call-free GET, navigation, enable/disable, arm/disarm, and trigger polling;
- ten-cycle limit, six-category/no-retry enforcement, four margin subreads,
  duplicate-call prevention, and stale/unknown recovery;
- exact Default/DEFAULT credential/catalog binding and portfolio privacy;
- CFM product, expiry, increments, BBO freshness, positions,
  margin/collateral, session, maintenance, after-hours, and GTC fail-closed
  cases;
- canonical one-contract economics and strict opening/exposure/buffered-close/
  turnover cap boundaries;
- shallow Preview-envelope validation, documented rejection, unknown
  consumption, Preview identity withholding, and identical Create terms;
- Create accepted, rejected, unknown, and restart boundaries;
- one-page exact Default-profile `list_orders` scope, rejection of
  `has_next=true`, acceptance without traversal of a final-page cursor when
  `has_next=false`, zero/one/duplicate exact client matches, exact term/hash
  comparison, terminal/nonterminal/unknown status handling, and no page
  retry;
- conditional exact-ID Cancel, no alternate ID, unknown consumption, and
  process-local raw-ID disposal;
- fixed diagnostics with no raw response, exception message, portfolio UUID,
  Preview ID, exchange ID, secret, or withheld text;
- RBAC, exact confirmations, feature flags, Controlled-live lease, route
  posture, OpenAPI/generated-client synchronization, and browser/BFF
  boundaries;
- authenticated operator and viewer UI tests, lost-response mutation freeze,
  restart readback, and installed review-stack behavior; and
- focused backend tests, full backend regression, frontend baseline/release
  gates, local deployed HTTP/browser proof, independent safety audit, and
  blind contextless audit before live use.

Synthetic tests and deployment validation must inject fake readers/executors
and prove zero Coinbase calls. A live proof may occur only under the separate
authorized Goal 13 allowances and after every gate above passes.

The focused policy, persistence, route, generated-contract, frontend readback,
source-blocker, and no-network tests are green. The canonical backend/frontend
gates, installed deployment validation, independent safety and
blind-contextless audits, and persistent Controlled-live handoff pass.
Focused validation passed 196 backend tests and 156 frontend tests. Canonical
regression passed 1,304 backend tests with 6 skipped in parallel and 976 with
150 skipped and 1,310 deselected in serial, plus 1,904 frontend
unit/component tests and 34 authenticated managed browser tests.

## Historical translation

The following `origin/prod` sources are reference material:

- `business/hotpoint_detector.py` for deterministic 0.5-percent bucket and
  three-fill/60-second trigger semantics;
- `business/hotpoint_rate_limiter.py` for restart-aware bounded-placement
  concepts;
- `business/hotpoint_placer.py` for same-side single-child and non-cascading
  placement concepts;
- `business/hotpoint_decay_sweeper.py` for historical Hotpoint lifecycle
  context;
- `dashboard_server.py` for the legacy operator controls; and
- `external/coinbase_client.py` for historical Futures/order wrapper usage.

The modern workflow does not restore the legacy dashboard WebSocket, direct
browser Coinbase access, in-memory authority, automatic placement on a fill
event, background sweeps, generic Spot/Futures placement, multi-order rate
capacity, retry/fallback behavior, client-ID-as-exchange-ID cancellation, raw
response display, or raw exception logging.

## Official Coinbase references

The current official contracts and `coinbase-advanced-py==1.8.4` signatures
show no published post-maintenance breaking change for these boundaries.
Current CDP credentials are portfolio-bound and the order-level
`retail_portfolio_id` field is deprecated, so Goal 13 omits it. This
documentation comparison is compatibility evidence, not a live-schema
guarantee; any returned divergence still fails closed under fixed sanitized
classification.

Eligibility and session:

- [Get API Key Permissions](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/data-api/get-api-key-permissions)
- [List Portfolios](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/portfolios/list-portfolios)
- [Get Product](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-product)
- [Get Best Bid/Ask](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-best-bid-ask)
- [List US Derivatives Positions](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/list-futures-positions)
- [Get US Derivatives Balance Summary](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-futures-balance-summary)
- [Get Intraday Margin Setting](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-intraday-margin-setting)
- [Get Current Margin Window](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-current-margin-window)
- [Advanced Trade Futures guide](https://docs.cdp.coinbase.com/coinbase-business/advanced-trade-apis/guides/futures)
- [Derivatives Market Hours and 24x7](https://docs.cdp.coinbase.com/derivatives/introduction/market-hours)

Lifecycle:

- [Preview Order](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders)
- [Create Order](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/create-order)
- [List Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/list-orders)
- [Cancel Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/cancel-order)
- [Advanced Trade API endpoints](https://docs.cdp.coinbase.com/coinbase-business/advanced-trade-apis/rest-api)
- [coinbase-advanced-py SDK](https://coinbase.github.io/coinbase-advanced-py/)
