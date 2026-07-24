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
runtime row, Product Catalog metadata and increments, remaining size, zero
fill, the canonical `order_parent` movement target, strict profitability, and
direct submitted/possible execution ceilings of `3.10/1.00 USDC`. A missing or
changed canonical parent target fails closed; runtime-row target values are not
accepted as a fallback. Planning does not run the legacy replacement-delta
wallet guard. Both planning and execution require the source's
`allow_partial_fills` policy to be exactly false.

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
It may clear that freeze only after exact completed command-cycle correlation
evidence is present in call-free backend readback.

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
route tests. Focused frontend coverage includes strict runtime validation,
operator workflow behavior, generated route coverage, persistent unknown
outcome quarantine, and installed review-stack feature configuration. Full
regression, release/deployment gates, independent safety audit, and blind
contextless audit remain required before MVP closeout.
