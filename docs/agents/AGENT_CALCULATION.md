# Calculation Agent

## Owns

- `calculation/*`

## Canonical Path

Sizing, rounding, fee, product-type, price, and profitability helpers stay pure
or mostly pure and are consumed by lifecycle owners.

## Must Not Do

- Do not edit files outside the owned files listed in the Owns section. If a change requires editing files owned by another agent, route the change to that owner or coordinate through the architect.
- Do not place orders, write DB rows, or emit dashboard responses.
- Do not hard-code product increments, min sizes, or product types.
- Do not bypass enum-based policies.

## Focused Tests

```powershell
pytest tests/regression/test_size_validation.py tests/regression/test_quantize_to_increment.py tests/regression/test_maker_taker_fee_selection.py -v --tb=short
```

