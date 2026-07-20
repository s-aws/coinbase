# Operator Spot Automation Single-Child Adapter v1

## Current status

Goal `operator_spot_automation_single_child_execution_adapter_v1` is at an
eligibility-coordinator-complete, source-gated checkpoint. It is not a
live-ready completion.

The PostgreSQL control plane can store one immutable `BTC-USDC` LIMIT/GTC
single-child plan, carry it across definition revisions, claim one explicit
operator run, derive one deterministic `client_order_id`, reserve one durable
Create allowance, and project backend-owned plan, eligibility, cap, child,
audit, and call-accounting evidence through generated contracts. The routed UI
can create and review the definition and displays the fixed blocker on the run.
The goal-wide plan-bearing definition slot is singleton and race-safe:
definition plus plan creation commits in one transaction, revision carry is
atomic, exact replay verifies the persisted plan, and any partial write rolls
back. Generic planless control-plane definitions remain unaffected.

The installed application adapter now includes a typed, route-owned eligibility
coordinator for the seven approved read categories: API-key permissions,
portfolio catalog, account/wallet balances, product metadata, best bid/ask,
fee summary, and exact-order reconciliation. An authenticated operator must
explicitly acknowledge both the approved reads and unknown-outcome cycle
consumption before starting a cycle. Ordinary page loading and navigation are
call-free. The coordinator claims a goal-global PostgreSQL cycle before it
constructs the strict Coinbase reader, invokes categories once in fixed order
with no application retry, fails short, persists only sanitized hashes and
fixed diagnostics, and replays terminal evidence without constructing a
reader. Up to ten cycles may be consumed across the goal; restart recovery and
idempotency cannot reopen a consumed category or cycle.

The adapter still exposes no gateway or boolean override that can enable
execution. An exact campaign claim therefore transitions locally from
`CLAIMED` through `PREPARING` to `BLOCKED` with
`automation_active_order_catalog_read_not_authorized`. Eligibility refresh may
update the same blocked run's sanitized evidence and actionability, but it
cannot create an invocation claim, compose the command runtime, read the
account-wide active-order catalog, call Create, or mutate the exchange.
Authorization of the blocked run continues to return the fixed source-gate
conflict before those boundaries. Its durable actor, payload, idempotency, and
correlation bindings remain fail-closed on drift.

The one-run boundary is goal-global and durable: the singleton goal row
serializes concurrent plan-bearing claims, and the first claim permanently
uses the run slot even when its source-gated terminal state is `BLOCKED`.
Definition readback removes `RUN_ONCE` for every plan-bearing definition after
that claim. Planless generic control-plane definitions retain their historical
per-definition behavior and receive no Spot execution authority.

`adapter_status=SOURCE_GATED` now means the typed plan/run contract, production
eligibility coordinator, strict reader, durable cycle ledger, and generated
operator readback are installed, but the account-wide active-order guard and
canonical application execution coordinator are not authorized or callable.
It is not an execution-ready domain boundary and must not be described as
available or operator-authorized. Earlier direct command-service and
injectable-gateway prototypes remain removed because they bypassed the
canonical route-owned admission and execution scope.

## Preserved invariants

- persistence stores only the configured portfolio's SHA-256 binding and
  revalidates current configuration before a future invocation boundary;
  readback says `CONFIGURED_UNVERIFIED` unless the latest eligibility cycle has
  exact successful portfolio-catalog evidence durably hash-bound to the same
  plan portfolio, and only then may it display `Test`; this binding is not a
  wall-clock freshness claim;
- product is exactly `BTC-USDC`, with one definition, one run, and at most one
  deterministic child;
- submitted notional is at most `3.10 USDC` and possible-execution notional is
  at most `1.00 USDC`;
- the browser cannot supply portfolio identity, child identity, cap decisions,
  eligibility, or exchange authority;
- local definition and run mutations retain RBAC, exact operator intent,
  idempotency, audit, revision binding, and duplicate prevention;
- eligibility categories are fixed, ordered, single-call/no-retry, freshness
  bound, plan/revision/portfolio bound, and persisted without raw Coinbase
  payloads or private identifiers;
- terminal cycle replay performs zero reader construction and zero Coinbase
  calls; changed operator reason, acknowledgements, plan, actor, or correlation
  identity cannot replay the same idempotency key;
- the single goal-global run slot cannot be reopened by a new definition,
  idempotency key, process, or restart after a blocked claim;
- unknown post-claim outcomes are never reported as exact zero and are never
  retried;
- an accepted active child survives restart; only an unresolved Create or a
  consumed-but-unfinalized Cancel boundary becomes unknown-consumed;
- no recurring scheduler, unattended activation, ladder, sweep, fan-out,
  Futures action, alternate product, or browser-side Coinbase path exists.

## Why the live proof did not run

The canonical domain-owned Spot placement service enforces zero active Test
portfolio orders by completing one account-wide paginated `OPEN` order read
immediately before Create. The current authorization enumerates exact-order
reconciliation but not this account-wide active-order catalog category.
Skipping the guard would weaken installed policy; relabeling it as exact-order
reconciliation would make endpoint accounting false.

The source gate therefore closes after the separately authorized eligibility
coordinator and before the account-wide active-order read, invocation claim,
Create, or exact-child Cancel. The implementation and validation work used
synthetic sanitized readers only and made no live eligibility reads. All
eligibility-cycle, Create, and exact-child Cancel allowances remain unconsumed.

## Validation evidence

The checkpoint passed backend full regression with `1170 passed, 6 skipped`
in the parallel partition and `651 passed, 150 skipped` in the serial
partition. Frontend validation passed 89 files and `1536` tests, browser E2E
passed `15/15`, and independent safety plus blind-contextless audits returned
`PASS` with no P0, P1, or P2 finding. Generated-contract, typecheck, lint,
build, command-security, and release-readiness checks passed. The managed
browser and regression runners reported no Coinbase execution and `0 USDC`
notional.

## Required successor work

A separately authorized continuation must remediate and validate the remaining
canonical admission and execution path together:

1. add exactly one account-wide active Spot order catalog read category, with
   required cursor pagination and no page retry, solely for the canonical
   zero-active-order guard;
2. resolve real typed approval, cap, admission-audit, and live-service evidence
   through the canonical domain service and enter its canonical Spot mutation
   scope only after the durable invocation claim; synthetic proof identifiers
   are forbidden;
3. reuse the installed eligibility coordinator without duplicate reads and
   account truthfully for every read,
   Create, reconciliation, and Cancel boundary;
4. prove the configured canonical portfolio UUID is the approved Test
   portfolio through coordinator-owned current portfolio-catalog evidence
   rather than relying on a display label or caller-finalized row; wire
   exact-child reconciliation and the one-use canonical Cancel safe closeout
   route; and
5. repeat focused/full validation, installed deployment checks, safety audit,
   and blind-contextless audit before considering one Create.

## Consolidated successor authorization wording

> I authorize one bounded continuation of
> `operator_spot_automation_single_child_execution_adapter_v1`. It preserves
> the exact approved Test portfolio, `BTC-USDC`, one definition, one run, one
> child, and the existing `3.10 USDC` submitted and `1.00 USDC`
> possible-execution caps. It may perform up to 10 combined offline,
> official-documentation-only, PostgreSQL migration, TDD, generated-contract,
> local deployment, safety-audit, blind-contextless-audit, remediation, and
> state-refresh cycles needed to finish canonical admission, execution,
> reconciliation, and exact-child safe-closeout identified by the source-gated
> checkpoint. The continuation must reuse the installed typed route-owned
> eligibility coordinator and must not reintroduce a bare
> enablement boolean, untyped gateway, or parallel Spot placement path. Each refresh cycle
> may invoke each existing approved category at most once with no individual or
> page retry: API-key permissions, portfolio catalog, account/wallet balances,
> product metadata, best bid/ask, fee summary, and exact-order reconciliation.
> It additionally permits exactly one logical account-wide active Spot order
> catalog read per cycle on the approved Test portfolio, including required
> cursor pages with no page retry, solely to enforce the canonical zero-active-
> order guard. The ten-cycle limit is goal-global, not per run. The backend must
> preserve the atomic definition-revision and immutable-plan binding, bind all
> evidence to the same plan revision and portfolio hash, prove the configured
> UUID is the approved Test portfolio, enforce
> freshness, use real typed approval/cap/admission/live-service evidence, enter
> only canonical Spot execution scopes, prevent duplicate reads, and account
> truthfully for every call. After all focused/full gates, installed deployment
> checks, independent safety audit, and blind-contextless audit pass, it permits
> exactly one operator-triggered Coinbase Spot Create for that exact child and,
> only if the exact child is authoritatively nonterminal, at most one Cancel for
> that child. It permits zero retries, fallbacks, redirects, alternate
> identities, second children, fan-out, product expansion, Futures actions,
> scheduler activation, or other exchange mutations. An unknown outcome
> consumes the applicable allowance. If any phase or terminal proof fails,
> continue bounded offline diagnosis and remediation without requesting another
> authorization. Preserve all immutable R1-R12 artifacts and documented hashes,
> keep R8 content and hash inaccessible, never expose raw responses, secrets,
> private identifiers, or withheld exception text, and leave the Controlled-live
> operator stack running. Stop only if proceeding would change the portfolio,
> product, caps, child count, enumerated endpoint set, or exchange-call limits.

The quoted continuation is a draft only. It grants no authority unless the
operator explicitly supplies it.

## Historical comparison

The implementation review compared the current backend with
`origin/prod` references including `dashboard_server.py`,
`business/hotpoint_placer.py`, and `core/order_engine.py`. Direct REST mutation,
WebSocket authority, in-memory-only claims, automatic workers, and fan-out were
not copied. Only acquire/commit/rollback, durable linkage, and restart-recovery
ideas were translated into the current backend-owned control plane.
