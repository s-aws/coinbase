# Movement And Repricing Examples

Start the local Admin API:

```powershell
python3.13 tools/run_admin_api.py --dev-token local-admin-token
```

List recent movement/repricing evidence:

```http
GET /api/v1/movement-repricing/evidence?limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Filter to one product and one evidence type:

```http
GET /api/v1/movement-repricing/evidence?product_id=BTC-USDC&evidence_type=stealth_repricing_state
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Read movement/repricing evidence linked to a placement or parent
`client_order_id`:

```http
GET /api/v1/movement-repricing/orders/{client_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Read movement/repricing evidence linked to a `stealth_order_id`:

```http
GET /api/v1/movement-repricing/stealth/{stealth_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Expected posture fields:

```json
{
  "type": "admin_movement_repricing_evidence",
  "read_only": true,
  "command_routes_mode": "live_disabled",
  "live_coinbase_orders_ran": false
}
```

Example evidence item:

```json
{
  "evidence_type": "stealth_repricing_state",
  "client_order_id": "placement-client-id",
  "stealth_order_id": "stealth-root-id",
  "active_placement_client_order_id": "placement-client-id",
  "active_exchange_order_id": "coinbase-order-evidence",
  "exchange_order_id_evidence_only": true,
  "mutation_claims": [
    {
      "kind": "reprice",
      "state": "processing",
      "runtime_observed": true,
      "source": "stealth_manager.snapshot_mutation_claims"
    }
  ]
}
```

Live-disabled reprice draft:

```http
POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: idem-movement-reprice-001
X-Correlation-Id: corr-movement-reprice-001
X-Operator-Intent: movement_reprice_review
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Content-Type: application/json

{"reason":"operator_requested_reprice"}
```

Expected command response posture:

```json
{
  "status": "not_implemented",
  "action_class": "live_exchange_cancel",
  "required_permission": "order:cancel",
  "service_method": "reprice_stealth_order_by_stealth_order_id",
  "stealth_order_id": "stealth-root-id",
  "client_order_id": null,
  "live_exchange_submitted": false,
  "data": {
    "identity_key": "stealth_order_id",
    "mutation_kind": "reprice",
    "cooldown_cleared": false,
    "stealth_manager_invoked": false,
    "exchange_order_id_evidence_only": true
  }
}
```

The `live_exchange_cancel` action class and `order:cancel` permission are
intentional. Approved live repricing would replace a revealed placement through
the existing cancel/replace/reconcile path, so there is no separate browser
repricing authority. For this module, dry-submit means preserving this
live-disabled `501` command evidence; it is not live repricing approval.

Do not send `client_order_id` or Coinbase `order_id` in the request body.
The current route writes audit/idempotency evidence and stops at the
live-disabled gate. `X-Operator-Intent` is persisted as audit evidence and is
part of the idempotency payload hash; changing it while reusing the same
`Idempotency-Key` returns conflict. The route does not clear repricing
cooldowns, invoke the live dashboard repricer, cancel placements, or call
Coinbase.
