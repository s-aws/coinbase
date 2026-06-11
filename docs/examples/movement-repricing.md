# Movement And Repricing Examples

Start the local Admin API:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
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
  "command_routes_mode": "not_modeled",
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
      "source": "stealth_manager._mutation_claims"
    }
  ]
}
```

Do not post to these paths. M2 intentionally exposes no enterprise
movement/repricing command route.
