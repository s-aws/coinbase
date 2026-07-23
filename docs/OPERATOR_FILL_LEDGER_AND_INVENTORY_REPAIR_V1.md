# Operator Fill Ledger and Inventory Repair V1

Goal `operator_fill_ledger_and_inventory_repair_v1` is independent Goal 2 of
the authorized operator-functionality sequence.

## Closeout status

Goal 2 is complete. The canonical backend gate passed `1,213` tests with `6`
skipped in the four-worker partition and `747` tests with `150` skipped in the
serial partition. The canonical frontend gate passed `1,621/1,621` tests,
`20/20` Playwright checks, generated-contract coverage for `182` paths, the
installed deployment smokes, and the complete release gate. Independent
safety and blind-contextless audits both passed after their findings were
remediated.

Validation and deployment made zero Coinbase calls and zero exchange
mutations. The goal-global ten-cycle fill-read allowance remains unconsumed.

## Operator outcome

The authenticated Admin UI can create one durable repair case using exactly
one of these backend-owned selectors:

- one system-owned `client_order_id`;
- the approved `BTC-USDC` product; or
- a `BTC-USDC` UTC time window no wider than 24 hours.

An explicit refresh atomically claims one of the goal-global ten cycles before
invoking one logical Coinbase fill-catalog read. The same singleton PostgreSQL
ledger is shown on every case, so creating another case cannot multiply the
allowance. Required cursor pages may complete that
logical read, but every page call is durably claimed before invocation and no
page is retried. The workflow can then:

- classify existing, missing, and unmatched fills;
- build one immutable missing-fill import plan;
- project FIFO lots, open quantity, average and remaining cost basis, fees,
  and realized operational P&L;
- atomically import only missing hashed fill identities into PostgreSQL; and
- roll back only the exact rows owned by that import batch while restoring the
  prior projection.

Apply and rollback make no Coinbase call. The entire goal permits zero Coinbase
order Create, Cancel, Close, Reduce, or other exchange mutation.

## Authority and privacy

The backend owns authentication, RBAC, configured approved-Test-portfolio
binding, selector validation, system-order resolution, cycle/page claims,
idempotency, revision conflicts, duplicate-fill prevention, restart recovery,
audit, and authoritative readback. The browser renders generated OpenAPI
contracts and forwards explicit operator intent.

Exchange fill and order identifiers are one-way SHA-256 evidence before
persistence in this repair workflow. All documented fill identity aliases
(`entry_id` and `trade_id`) are atomically persisted as unique hashed claims,
so a legacy or newly imported ledger identity cannot be imported again under
an alternate alias. Public diagnostics, service methods, messages,
correlation evidence, and the withheld event actor are exact allowlisted
contract values; PostgreSQL rejects an unallowlisted durable diagnostic.
Public models contain only allowlisted
fill values, fixed diagnostic codes, bounded counts, projection values, hashes,
and sanitized events. Raw Coinbase responses, response bodies, exception
messages, private portfolio identity, and operator reasons are never public
readback.

## PostgreSQL durability

Durable state includes the repair case, the singleton goal budget, immutable
internal plan, cycle and page-call claims, event history, exact import-batch
linkage, fill identity claims, product projection, and FIFO lots. Page claims
distinguish `UNKNOWN_AFTER_PAGE_CLAIM` from a response that returned before
normalization. Startup converts interrupted `REFRESHING` cases to a fixed
blocked state without releasing or replaying their already claimed allowance.
The projection includes only fills linked to system-owned orders in the exact
approved portfolio. Apply hashes and rechecks the scoped ledger baseline before
writing. Catalog timestamps are normalized to UTC and values must be exactly
representable by the installed `DECIMAL(16,8)` quantity/fee and
`DECIMAL(24,12)` price columns; the workflow never relies on PostgreSQL
rounding. Rollback requires the same reviewed plan hash, verifies the locked
current projection bytes, the complete post-apply scoped-ledger hash, and
exact fill/alias ownership-set hashes. It refuses a same-count identity
substitution or any later non-batch ledger drift, then restores both the prior
projection bytes and its prior source case only after verifying their
combined saved-snapshot hash and when the remaining ledger exactly matches the
reviewed baseline. Apply also verifies the existing projection's own stored
hash before capturing that snapshot. A pre-binding legacy import-batch row is
marked unverified during migration rather than having its mutable values
silently sealed; its rollback fails closed without deleting any imported row.
Every production fill insert and
fill-ledger update participates in the same PostgreSQL product advisory lock,
so a concurrent writer cannot commit between the final ledger check and the
repair transaction commit.
Revision, state, plan-hash, portfolio-hash, baseline-hash, and exact-batch
preconditions are enforced in one transaction.

## Historical source translation

The implementation inspected:

- `origin/prod:business/fill_ledger.py`;
- `origin/prod:business/position_lot.py`; and
- the fill pipeline in `origin/prod:core/order_engine.py`.

The useful legacy behavior was fill-driven inventory reconstruction. The MVP
replaces JSONL/tool-only repair and implicit engine behavior with explicit
operator selection, PostgreSQL claims, fixed privacy-safe evidence, generated
Admin API contracts, RBAC, idempotency, restart recovery, and reversible exact
batch mutations.

## Coinbase documentation boundary

The pinned `coinbase-advanced-py==1.8.4` canonical
`CoinbaseRestClient.get_fills` adapter invokes `RESTClient.get_fills` exactly
once per claimed page and follows the official Advanced Trade List Fills
contract for
`order_ids`, `product_ids`, `start_sequence_timestamp`,
`end_sequence_timestamp`, `retail_portfolio_id`, `cursor`, and `limit`.
The configured adapter is verified before a cycle is claimed. Fill catalog
access is view-only. Product or time-window results are admitted only when they
resolve to system-owned local orders in the configured portfolio.

Official reference:
<https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/list-fills>

## Goal-local call allowances

- up to ten refresh cycles across the entire independent Goal 2;
- one logical fill catalog per claimed cycle;
- required cursor pages with no page retry;
- zero Coinbase order mutations.

No Goal 1 allowance is transferred. Goal 1 remains complete and its optional
Cancel allowance remains unconsumed.
