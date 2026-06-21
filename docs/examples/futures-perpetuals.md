# Futures/Perpetuals Examples

These examples use the enterprise Admin API. They are read-only examples and
do not place, close, cancel, or modify Coinbase orders.

Start the local Admin API:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

## Command-Suite Contract Evidence

The active 5181-5200 range adds read-only M57 futures/perpetual request-field
contract metadata to the existing command-suite evidence. It is not a command
route and does not make command drafts available.

```http
GET /api/v1/futures/command-suite
Authorization: Bearer local-admin-token
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected response posture:

```json
{
  "type": "admin_futures_command_suite",
  "module_id": "futures_perpetuals",
  "approved_phase_range": "5181-5200",
  "status": "blocked",
  "command_count": 4,
  "blocked_command_count": 4,
  "executable_command_count": 0,
  "command_route_count": 0,
  "command_draft_allowed_count": 0,
  "request_field_count": 22,
  "required_request_field_count": 22,
  "blocking_request_field_count": 22,
  "forbidden_spot_assumptions": [
    "spot_wallet_available",
    "spot_no_shorting",
    "spot_usdc_quote_required",
    "spot_average_cost_basis",
    "spot_inventory_lot_authority"
  ],
  "commands": [
    {
      "command": "futures_place",
      "status": "blocked",
      "action_class": "live_exchange_place",
      "route": null,
      "service_method": "place_futures_order_contract_required",
      "identity_key": "product_id",
      "request_field_count": 7,
      "blocking_request_field_count": 7,
      "request_fields": [
        {
          "field": "product_id",
          "status": "blocked",
          "identity_field": true,
          "risk_field": false,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "field": "size",
          "status": "blocked",
          "identity_field": false,
          "risk_field": true,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        },
        {
          "field": "client_order_id",
          "status": "blocked",
          "identity_field": true,
          "risk_field": false,
          "spot_rule_authority": false,
          "browser_authority": "display_only"
        }
      ],
      "command_route_registered": false,
      "command_draft_allowed": false,
      "execution_allowed": false
    },
    {
      "command": "futures_close_reduce",
      "status": "blocked",
      "action_class": "live_exchange_place",
      "route": null,
      "service_method": "close_or_reduce_futures_position_contract_required",
      "identity_key": "position_key",
      "command_route_registered": false,
      "command_draft_allowed": false,
      "execution_allowed": false
    },
    {
      "command": "futures_cancel",
      "status": "blocked",
      "action_class": "live_exchange_cancel",
      "route": null,
      "service_method": "cancel_futures_order_contract_required",
      "identity_key": "client_order_id",
      "request_fields": [
        {
          "field": "client_order_id",
          "status": "blocked",
          "identity_field": true,
          "detail": "Futures cancel must call the project wrapper with client_order_id; exchange order_id is exchange evidence only."
        },
        {
          "field": "product_id",
          "status": "blocked",
          "identity_field": false
        },
        {
          "field": "operator_notes",
          "status": "blocked",
          "identity_field": false
        }
      ],
      "command_route_registered": false,
      "command_draft_allowed": false,
      "execution_allowed": false
    },
    {
      "command": "futures_reconcile",
      "status": "blocked",
      "action_class": "local_state_mutation",
      "route": null,
      "service_method": "record_futures_reconciliation_contract_required",
      "identity_key": "position_key",
      "command_route_registered": false,
      "command_draft_allowed": false,
      "execution_allowed": false
    }
  ],
  "spot_rule_authority": false,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "live_coinbase_orders_ran": false,
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0"
}
```

Spot wallet, no-shorting, USDC, cost-basis, and inventory-lot rules are forbidden
as futures/perpetual command authority.

## Account Evidence

```http
GET /api/v1/futures/account
Authorization: Bearer local-admin-token
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected response posture:

```json
{
  "type": "admin_futures_account",
  "configured_product_scope": ["BIP-20DEC30-CDE"],
  "observed_position_scope": ["BIP-20DEC30-CDE"],
  "collateral": {
    "name": "collateral",
    "status": "unavailable",
    "source": "runtime_unavailable"
  },
  "margin": {
    "name": "margin",
    "status": "observed",
    "source": "fee_manager",
    "value": {"margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"}
  },
  "funding": {
    "name": "funding",
    "status": "not_modeled",
    "source": "backend_contract"
  },
  "liquidation": {
    "name": "liquidation",
    "status": "unavailable",
    "source": "runtime_unavailable"
  },
  "reduce_only_close_only": {
    "name": "reduce_only_close_only",
    "status": "observed",
    "source": "position_side_derivation"
  },
  "position_pnl": {
    "name": "position_pnl",
    "status": "observed",
    "source": "runtime_positions"
  },
  "position_count": 1,
  "read_only": true,
  "command_routes_mode": "not_modeled",
  "live_coinbase_orders_ran": false
}
```

## Position List

```http
GET /api/v1/futures/positions?product_id=BIP-20DEC30-CDE&position_side=LONG&limit=50&offset=0
Authorization: Bearer local-admin-token
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Rows are keyed by `position_key`:

```json
{
  "type": "admin_futures_positions",
  "filters": {
    "product_id": "BIP-20DEC30-CDE",
    "position_side": "LONG",
    "limit": 50,
    "offset": 0
  },
  "count": 1,
  "pagination": {
    "limit": 50,
    "offset": 0,
    "returned_count": 1,
    "total_matching_count": 1,
    "next_offset": null,
    "has_more": false
  },
  "items": [
    {
      "position_key": "futures_position:runtime:BIP-20DEC30-CDE",
      "product_id": "BIP-20DEC30-CDE",
      "product_type": "FUTURE",
      "position_side": "LONG",
      "close_order_side": "SELL",
      "source": "runtime_orderbook"
    }
  ],
  "read_only": true,
  "command_routes_mode": "not_modeled",
  "live_coinbase_orders_ran": false
}
```

## Position Detail

```http
GET /api/v1/futures/positions/futures_position%3Aruntime%3ABIP-20DEC30-CDE
Authorization: Bearer local-admin-token
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

The path uses `position_key`. Do not replace it with `client_order_id` or
Coinbase `order_id`.

## Operator Rules

- Treat `configured_product_scope` as configured metadata coverage.
- Treat `observed_position_scope` as observed runtime position coverage.
- Treat close/reduce sides as backend-derived from position side, not as
  exchange-observed order flags.
- Treat `funding.status="not_modeled"` as unsupported until the backend
  contract is extended.
- Live Coinbase execution for these examples: not run; notional `$0`.
