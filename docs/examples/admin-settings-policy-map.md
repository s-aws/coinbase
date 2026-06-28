# Admin Settings Policy Map Examples

Read the settings and policy classification map:

```http
GET /api/v1/admin/settings-policy-map
Authorization: Bearer <admin token>
```

Representative response shape:

```json
{
  "editable_count": 0,
  "read_only_count": 5,
  "secret_count": 2,
  "unsupported_count": 1,
  "not_modeled_count": 2,
  "secret_values_exposed": false,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "coinbase_authority": "not_run",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "live_coinbase_orders_ran": false,
  "items": [
    {
      "surface_id": "guard_risk_policy",
      "label": "Guard/Risk Policy",
      "category": "guard_risk_policy",
      "status": "read_only",
      "secret_value_exposed": false,
      "read_route": "/api/v1/admin/guard-risk-policy",
      "write_route": null,
      "coinbase_authority": "not_run",
      "notional_usdc": "0"
    },
    {
      "surface_id": "coinbase_api_credentials",
      "label": "Coinbase API Credentials",
      "category": "coinbase_secrets",
      "status": "secret",
      "secret_value_exposed": false,
      "read_route": null,
      "write_route": null,
      "coinbase_authority": "not_run",
      "notional_usdc": "0"
    }
  ]
}
```

Operator interpretation:

- `editable_count = 0` means no enterprise settings edit route exists yet.
- `secret` rows may be shown as masked surfaces, never as secret values.
- `read_only` rows may link to their backend read route.
- `not_modeled` and `unsupported` rows should be displayed as blocked, not
  filled in by frontend logic.
