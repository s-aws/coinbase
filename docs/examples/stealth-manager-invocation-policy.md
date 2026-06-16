# Stealth Manager-Invocation Policy Examples

Read manager-invocation policy evidence for a stealth order:

```http
GET /api/v1/stealth/orders/stlth_123/manager-invocation-policy
```

Expected behavior:

- return backend `proof_records` and latest-proof status as evidence
- show no-live, no-manager, no-Coinbase, no-cancel/replace, and
  no-reconciliation flags
- keep manager invocation and live command controls disabled unless a separate
  backend live-enabled contract explicitly allows execution
- never compute manager-policy safety in the browser or BFF

Record manager-invocation policy proof evidence:

```http
POST /api/v1/stealth/orders/stlth_123/manager-invocation-policy-proofs
Idempotency-Key: example-idempotency-key
X-Correlation-Id: example-correlation-id
X-Operator-Intent: record manager policy evidence only
```

The request must include the exact guarded command context required by the
backend. A successful response is append-only local evidence. It is not manager
invocation, Coinbase read, Coinbase submit/cancel, active-placement
cancel/replace, reconciliation, order/lifecycle/exchange mutation, or browser
proof approval.
