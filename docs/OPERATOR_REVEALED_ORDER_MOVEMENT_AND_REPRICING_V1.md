# Operator Revealed Order Movement and Repricing V1

Goal ID: `operator_revealed_order_movement_and_repricing_v1`.

## Outcome

An authenticated operator can select one exact system-owned Stealth definition
whose canonical runtime placement is `REVEALED`, zero-fill, and nonterminal;
prepare one immutable replacement plan; review the quantized post-only terms;
and explicitly authorize one exact Cancel followed, only after authoritative
`CANCELLED` readback, by one replacement Create.

The routed Admin UI is `/movement-repricing`. It displays generated backend
authority and forwards explicit intent only.

## Backend authority

PostgreSQL owns:

- the single non-transferable Goal 7 identity;
- definition revision/hash and approved Test-portfolio hash;
- source, root, and replacement `client_order_id` linkage;
- source and replacement exchange-identity hashes, never raw identities;
- the immutable price, size, product, side, post-only, profitability, and cap
  evidence;
- exact idempotency replay and command-cycle evidence;
- fixed allowlisted operator intent inside the durable command payload hash;
- every bounded read plus single-use Cancel and Create claim and result;
- unknown-outcome consumption and restart recovery.

Plan preparation makes no Coinbase call. It revalidates the exact canonical
runtime row, Product Catalog metadata and increments, exhausted hidden
remaining size, zero fill, the canonical `order_parent` movement target,
strict profitability, and direct submitted/possible execution ceilings of
`3.10/1.00 USDC`. Because
`stealth_orders.remaining_size` is the still-hidden quantity and is zero for a
real `REVEALED` placement, replacement size comes only from the exact active
placement's durable `order_parent.size`. The backend also proves that row's
source/root linkage, nonterminal status, product, side, price, exchange
identity, portfolio scope, partial-fill policy, and system-owned root
provenance at plan and execution boundaries. The root provenance must be the
exact Goal 6 `ADMIN_MANUAL_ROOT`; automation and fill-follow-up roots are not
accepted. For a Goal 6 root placement, `order_parent.price` remains its
configured definition price while the protected anchor owns the possibly
different TOP_OF_BOOK/MIDPOINT submitted price. Derived child placements must
instead match parent-row and anchor price exactly. A missing or changed
placement or canonical parent target fails closed; runtime-row size/target
values are not accepted as a fallback. Planning does not run the legacy
replacement-delta wallet guard. Both planning and execution require the
source's `allow_partial_fills` policy to be exactly false.

After authoritative source cancellation and before Create, the backend runs a
non-configurable, fail-closed full current-wallet guard without crediting the
cancelled source hold. Any additional installed policy is evaluated against
the same cached wallet snapshot and cannot disable or weaken the mandatory
guard. That wallet read has its own durable `WALLET_PRE_CREATE` claim and fixed
`RETURNED`/`UNKNOWN` result. The PostgreSQL Create claim independently requires
a same-cycle `RETURNED` wallet result. An interrupted or unknown wallet read
closes the goal without consuming Create and cannot be retried.

## Exchange sequence

Execution is strictly ordered:

1. exact authoritative source-order read;
2. durable placement-level pending/automatic-mutation fence;
3. at most one typed manager Cancel;
4. exact authoritative source-order read;
5. one full current-wallet read with no cancelled-hold credit;
6. only when all local admission remains valid, at most one typed manager
   post-only replacement Create;
7. exact authoritative replacement read proving the frozen side, size, limit
   price, and post-only terms.

Both source reads require documented fill indicators that prove exactly zero;
missing, malformed, negative, or conflicting evidence fails closed. An
unsuccessful or unknown Cancel prohibits Create. The pre-Cancel fence must
persist before the Coinbase invocation boundary, and an unknown Cancel retains
the durable automatic-mutation block. A post-Cancel nonzero-fill result is
race-ambiguous and is classified unknown after the consumed Cancel boundary.
Unknown Create or a replacement readback that cannot prove the exact frozen
terms consumes the replacement allowance and retains reconciliation fencing.
There are no retries, fallbacks, redirects, alternate identities, second
children, partial-fill moves, automatic repricing, or scheduler activation.

The replacement remains fenced from automatic repricing and cancel/reentry
while exact post-Create reconciliation is pending. After reconciliation, a
durable placement-level block continues to prohibit those background mutation
paths; Goal 7 never silently hands the child to legacy automatic repricing.
The Order Engine's `CANCELLED`, `FILLED`, and partial-fill handlers honor this
block before registration, carry claims, pending-move lookup, or automatic
follow-up creation, so an exchange event racing Goal 7 cannot create a second
child. The final follow-up creation boundary also owns a typed `FOLLOW_UP`
mutation claim that is mutually exclusive with Goal 7's `MOVE` claim. This
closes the check-then-act window: either follow-up creation owns the claim
first and Goal 7 cannot cross Cancel, or Goal 7 owns it first, persists the
fence, and follow-up creation cannot enter.

Every required Stealth-row and reveal-history write reports success only when
PostgreSQL confirms exactly one affected row. A missing row or write exception
is an observable fixed unknown boundary; exception text remains withheld.

When exact readback or a local manager guard fails before its durable call
claim, the command closes with fixed terminal evidence while the corresponding
Cancel or Create allowance remains unconsumed. It does not wait for restart,
reinterpret the local failure as a Coinbase call, or expose a replay action.

## Privacy and operator evidence

Raw Coinbase responses, response bodies, exception messages, private portfolio
identity, and raw exchange order IDs are neither persisted nor returned.
Operator readback contains only canonical client identities, hashes, fixed
diagnostic codes, direct caps, allowance/call counts, command-cycle evidence,
the approved portfolio-scope hash, fixed operator-intent label, and backend
`allowed_actions`. Both mutating routes require `order:cancel` and
`order:create`; route inventory and mutation taxonomy report both permissions.
Analytics-only users may receive an empty `allowed_actions` list while still
viewing the same verified authority and backend-supplied operator-intent label.

The browser persists an unknown/unverifiable outcome freeze across remounts.
It accepts a successful mutation only when the HTTP response correlation,
body/cycle correlation, phase, backend service method, fixed operator intent,
and SHA-256 of the exact sent idempotency key all agree. It may clear a freeze
only after the same exact completed command-cycle bindings are present in
call-free backend readback. Historical V1 freezes are migrated without
weakening this proof: that UI used the correlation UUID as its exact
idempotency key, so the browser deterministically derives the expected hash
and fixed phase-specific intent/service method before allowing acknowledgment.

## Historical translation

The implementation inspected `origin/prod:dashboard_server.py` movement
handlers and `origin/prod:core/stealth_order_manager.py` movement,
cancellation, replacement, and repricing behavior. The current design retains
the canonical manager and flat order linkage while replacing legacy dashboard
WebSocket authority, browser-owned terms, broad exception display, and
automatic repricing with authenticated Admin API routes, PostgreSQL claims,
generated contracts, explicit operator confirmation, exact reconciliation,
and fixed sanitized evidence.

## Focused validation

Focused backend coverage includes repository, service, runtime, manager, and
route tests, including realistic `REVEALED` state with zero hidden remaining
size and canonical active-placement size evidence. Focused frontend coverage
includes strict runtime validation, request/response correlation and
idempotency binding, operator workflow behavior, generated route coverage,
persistent unknown-outcome quarantine, and installed review-stack feature
configuration.

Terminal closeout passed `65` focused backend tests and `92` focused frontend
tests. The canonical backend regression passed `1,294` tests with `6` skipped
in its parallel lane and `908` tests with `150` skipped in its serial lane.
The canonical frontend release gate passed all `1,786` unit/component tests,
all `32` managed Playwright operator scenarios, generated-contract checks,
installed deployment validation, and both Controlled-live and explicit
No-live launcher checks. Independent safety and blind-contextless audits both
returned `PASS`. All validation used synthetic no-network exchange boundaries
and made zero Coinbase calls or exchange mutations.
