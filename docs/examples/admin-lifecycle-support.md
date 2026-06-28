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
  "approved_phase_range": "7981-8000",
  "lifecycle_support_count": 6,
  "lifecycle_supported_read_count": 3,
  "lifecycle_not_modeled_count": 2,
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
    }
  ]
}
```

The omitted `resume` row uses the same backend-command authority shape as
`pause` with route `/api/v1/admin/lifecycle/resume`. The omitted `stop` and
`drain` rows remain `not_modeled` until backend command contracts exist.
