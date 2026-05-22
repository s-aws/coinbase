# Stealth Lifecycle Agent

## Owns

- `core/stealth_order_manager.py`
- `business/stealth_condition_evaluator.py`
- `business/stealth_reveal_strategy.py`
- `business/cancel_reentry_policy.py`

## Canonical Path

Stealth behavior flows through `StealthOrderManager`; bridge loops may trigger
evaluation, but lifecycle truth lives in the manager.

## Must Not Do

- Do not edit files outside the owned files listed in the Owns section. If a change requires editing files owned by another agent, route the change to that owner or coordinate through the architect.
- Do not mark a revealed stealth order hidden, cancelled, or moved without
  cancelling, replacing, filling, moving, or reconciling the active Coinbase
  placement.
- Do not create a second active-placement pointer outside
  `anchor_repricing_state_json`.
- Do not treat cancel/re-entry as general hide-again behavior.
- Do not implement same-side post-fill retreat as a generic cross-order rules
  engine. The implemented scope is an opt-in hidden-order policy that retreats
  one nearest same-product/same-side hidden order and stores anchor offset in
  `anchor_repricing_state_json`.

## Focused Tests

```powershell
pytest tests/regression/test_stealth_cancel_reentry.py tests/regression/test_stealth_move_revealed.py tests/regression/test_repricing_policy.py -v --tb=short
```
