# Exchange Integration Agent

## Owns

- `external/*`
- `websocket/*`
- `api_reference/*`
- `websocket_reference/*`

## Canonical Path

Exchange clients wrap REST/websocket APIs and translate payloads. Local
lifecycle semantics belong to lifecycle owners.

## Must Not Do

- Do not decide local parent linkage, stealth state, or fill ownership.
- Do not make external tests part of the default regression gate.
- Do not leak credentials into reference payloads.

## Focused Tests

```powershell
pytest tests/regression/test_place_limit_order_returns_dict.py tests/regression/test_list_fills_param_mapping.py -v --tb=short
```

