# Configuration Agent

## Owns

- `configuration.py`
- `products.json`
- `pyproject.toml`

## Canonical Path

Runtime configuration comes from environment variables, `products.json`, and
the package metadata in `pyproject.toml`.

## Must Not Do

- Do not edit files outside the owned files listed in the Owns section. If a change requires editing files owned by another agent, route the change to that owner or coordinate through the architect.
- Do not create parallel product catalogs.
- Do not duplicate per-order settings as global settings.
- Do not put secrets into tracked files.

## Focused Tests

```powershell
pytest tests/regression/test_size_validation.py tests/regression/test_fee_multiplier_by_product_type.py -v --tb=short
```

