# Order Movement and Rearm

Reconciled on 2026-10-09. The checkout has three distinct existing behaviors;
none permits reparenting a child beneath another child.

## Cancelled parent move

`business/move_manager.py::MoveManager` owns `can_move_order`, `move_order`,
`pre_mark_for_move`, `execute_pending_move_for_order`, and `get_move_history`.
A moved cancelled parent creates a new root with its own UUID client ID and an
`order_moves` audit relationship. The original row remains for audit; existing
children are not automatically moved or reparented.

Premarking records a pending move (`move_on_cancel=true`) before cancellation.
The engine cancellation handler checks that pending move before normal
replacement logic. `main.py` supplies the current engine/bridge wiring;
`dashboard_server.py` handles `move_order`, `premark_move`, and
`request_move_history`. This cancelled-parent mechanism is separate from a
revealed stealth placement move.

## Revealed stealth move

`core/stealth_order_manager.py::StealthOrderManager.build_stealth_move_plan` resolves the configured
logical price, actual submitted price, size, movement context, and placement
identity. `execute_stealth_move` performs the explicit move-revealed action and
writes `stealth_order_moves` evidence. The dashboard exposes
`move_revealed_stealth_order` through the bridge's per-SID mutation ownership.

The logical stealth identity and original flat root linkage remain stable;
replacement placements have their own `client_order_id` and exchange
`order_id`. Move/reprice/Rehide claims prevent conflicting concurrent mutations.
Do not infer final exchange closure from a non-raising REST call or erase live
identifiers to make local status appear consistent.

## Automatic repricing and manual Rehide

Automatic revealed anchor repricing and manual Rehide share
`_request_revealed_rearm`, persisted `anchor_repricing_state_json.pending_rearm`,
and `consume_anchor_rearm_cancellation`. They request cancellation and create
no replacement inline. Only exact zero-fill terminal confirmation returns the
same logical order to HIDDEN; its normal condition policy owns later reveals.

Manual Rehide preserves price, conditions, sizing, linkage, and repricing
metrics. It requires one fully accounted zero-fill placement, bridge readiness,
and atomic RUNNING admission. A successful request acknowledges persisted
intent, not a hidden state. Multi-live or partially filled exposure cannot use
this minimal rearm path. Confirmed rearm establishes `reveal_armed_at` and fresh
placement client IDs for later reveals.

Intentional project Cancel supersedes a pending rearm with
`return_to_hidden=false` and a durable `operator_cancel_requested_at` marker.
It stops source triggers/follow-ups immediately while exact withdrawal recovery
continues. External cancellation remains eligible for normal replacements.

## Validation and navigation

See `API_REFERENCE.md` for request/result fields, `DATA_MODELS.md` for pending
intent fields, and `ORDER_ID_HANDLING.md` for client/exchange ID boundaries.
Relevant checked-in tests include `tests/unit/test_order_moves.py`,
`tests/regression/test_stealth_move_revealed.py`,
`tests/regression/test_anchor_reprice_phantom_parent.py`, and manual Rehide /
operator-cancel regressions. Run the complete gate in `TESTING_STRATEGY.md`.
