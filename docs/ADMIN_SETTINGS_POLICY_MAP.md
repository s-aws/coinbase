# Admin Settings Policy Map

`GET /api/v1/admin/settings-policy-map` is the backend-owned inventory of
settings and policy surfaces that the enterprise admin frontend may render.
It is a read-only Admin API route. It does not expose secrets, create edit
authority, approve live execution, or call Coinbase.

## When To Use It

Use this route when an operator UI needs to explain which settings or policy
areas are safe to show and which ones are intentionally unavailable. The route
classifies each surface with one of the shared enum-backed statuses:

- `editable`
- `read_only`
- `secret`
- `unsupported`
- `not_modeled`

The current Release 0.1 contract intentionally reports
`editable_count = 0`. No settings edit route is modeled yet.

## Backend Contract

The route is served by `AdminApiReadService.build_settings_policy_map()` and
returns `AdminSettingsPolicyMapResponse`.

Current rows include:

- capability registry as `read_only`
- guard/risk policy as `read_only`
- OIDC readiness as `read_only`
- CSRF contract as `read_only`
- live enablement as `read_only`
- Coinbase API credentials as `secret`
- OIDC client secret as `secret`
- guard/risk policy edits as `not_modeled`
- frontend display preferences as `not_modeled`
- legacy dashboard settings as `unsupported`

Every item sets `secret_value_exposed = false`,
`coinbase_authority = not_run`, and `notional_usdc = "0"`.
Non-editable rows do not include a `write_route`.

## Safety Constraints

- The browser is display-only for this map.
- The BFF, if present, may forward the backend response only.
- Secret rows identify the existence of a secret-backed surface without
  returning secret values.
- `not_modeled` means the backend does not currently have an enterprise
  settings workflow for that surface.
- `unsupported` means the surface is intentionally outside the enterprise
  frontend path.
- This route must not be treated as permission to add browser-side settings
  mutation or a second policy engine.

## Validation

Focused Admin API validation:

```powershell
pytest tests\regression\test_admin_api_contract.py -q -k "admin_read_routes_return_backend_contracts or route_inventory_names_required_shared_methods_and_doc or admin_api_openapi_schema_file_matches_generated_contract" --tb=short
```

Generated contract refresh:

```powershell
python tools\generate_admin_api_openapi.py
python tools\export_admin_api_route_inventory.py
```
