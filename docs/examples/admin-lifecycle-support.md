# Admin Lifecycle Support Example

```http
GET /api/v1/admin/enterprise-readiness
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Relevant lifecycle fields:

```json
{
  "type": "admin_enterprise_readiness",
  "approved_phase_range": "8001-8020",
  "lifecycle_support_count": 6,
  "lifecycle_supported_read_count": 5,
  "lifecycle_not_modeled_count": 0,
  "lifecycle_unsupported_count": 1,
  "lifecycle_support": [
    {
      "action": "status",
      "label": "Lifecycle status",
      "module_id": "admin_system_health",
      "support_status": "platform_ready",
      "exposure_status": "admin_exposed",
      "current_state_source": "core.runtime_controller.RuntimeController.state",
      "supported_route": "/api/v1/admin/health",
      "supported_method": "GET",
      "browser_authority": "display_only",
      "bff_execution_authority": "forward_only_no_execution",
      "dashboard_websocket_fallback_allowed": false,
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "action": "start",
      "label": "Start engine",
      "module_id": "admin_system_health",
      "support_status": "unsupported",
      "exposure_status": "admin_unsupported",
      "supported_route": null,
      "supported_method": null,
      "browser_authority": "display_only",
      "bff_execution_authority": "forward_only_no_execution",
      "dashboard_websocket_fallback_allowed": false,
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "action": "pause",
      "label": "Pause engine",
      "module_id": "admin_system_health",
      "support_status": "platform_ready",
      "exposure_status": "admin_exposed",
      "supported_route": "/api/v1/admin/lifecycle/pause",
      "supported_method": "POST",
      "browser_authority": "display_only",
      "bff_execution_authority": "forward_only_no_execution",
      "dashboard_websocket_fallback_allowed": false,
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "action": "stop",
      "label": "Stop engine",
      "module_id": "admin_system_health",
      "support_status": "platform_ready",
      "exposure_status": "admin_exposed",
      "supported_route": "/api/v1/admin/lifecycle/stop",
      "supported_method": "POST",
      "browser_authority": "display_only",
      "bff_execution_authority": "forward_only_no_execution",
      "dashboard_websocket_fallback_allowed": false,
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "action": "drain",
      "label": "Drain engine",
      "module_id": "admin_system_health",
      "support_status": "platform_ready",
      "exposure_status": "admin_exposed",
      "supported_route": "/api/v1/admin/lifecycle/drain",
      "supported_method": "POST",
      "browser_authority": "display_only",
      "bff_execution_authority": "forward_only_no_execution",
      "dashboard_websocket_fallback_allowed": false,
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    }
  ]
}
```

The omitted `resume` row uses the same backend-command authority shape as
`pause` with route `/api/v1/admin/lifecycle/resume`. `stop` is runtime
terminal-state control only; it does not terminate the OS process, cancel
Coinbase orders, or execute reconciliation.
