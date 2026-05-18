# Fill and Audit Agent

## Owns

- `business/fill_ledger.py`
- `business/fill_reconciler.py`
- `business/order_event_stream.py`
- `business/post_fill_hook.py`

## Canonical Path

WS-derived fills use `derived_trade_key`; REST reconciliation stamps exchange
ids later. Ownership is resolved through submission evidence, not raw exchange
events.

## Must Not Do

- Do not edit files outside the owned files listed in the Owns section. If a change requires editing files owned by another agent, route the change to that owner or coordinate through the architect.
- Do not replace `derived_trade_key` with exchange ids in live WS ingestion.
- Do not treat exchange `order_id` as local ownership proof.
- Do not mutate order lifecycle directly from audit helpers.

## Focused Tests

```powershell
pytest tests/regression/test_cross_source_reconciliation.py tests/unit/test_fill_reconciler.py tests/unit/test_fill_ledger_append_derived.py -v --tb=short
```

