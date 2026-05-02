"""Regression: stealth placement COIDs are pre-registered in the engine
orderbook BEFORE the REST submit so a racing WS event resolves to LOCAL.

Production incident 2026-05-02: stealth orders with
``anchor_repricing_policy.should_reprice_revealed=True`` mint a fresh
placement UUID in :meth:`StealthOrderManager._placement_client_order_id_for_order`.
That UUID was only stored in the stealth manager's ``_placed_order_index``
(an in-memory dict), so when the WS user-channel event for the placement
returned almost simultaneously with the REST call, the engine's
``_resolve_ws_order_ownership_scope`` missed every cache, classified it as
``EXTERNAL``, and ``_ensure_order_parent_row_exists`` inserted a phantom
``order_parent`` row with ``parent_order_id=NULL`` and
``ownership_scope='external'``.  Subsequent status writes targeted the
phantom row; the stealth root sat at PENDING forever.

DB rows 5 (``305fce34``) and 8 (``38a55f71``) are the production audit
fingerprints — both placement COIDs ended FILLED with ``parent=None`` while
the stealth roots (rows 4 / 7) stayed PENDING despite their
``stealth_orders`` row showing ``status=EXECUTED``.

The fix wires a ``placement_register_callback`` into
:class:`StealthOrderManager` (set by :class:`StealthOrderBridge`) which
calls ``OrderEngine.register_child_order(placement_coid, chain_root_coid,
bypass_replacement_cap=True)`` BEFORE the REST submit. ``bypass_replacement_cap``
is correct: a placement is the completion of an existing stealth slice,
not new exposure, and must not consume a slot in
``max_order_replacement``.

This regression locks in three invariants:

1. The pre-register callback is invoked before ``REST_CLIENT.place_limit_order``
   on the anchor-reprice path (which is the path that mints fresh COIDs).
2. The callback is invoked with ``(placement_coid, chain_root_coid)``.
3. The callback is NOT invoked when the placement COID equals the stealth
   root (no-reprice policy reuses the stealth UUID and the WS handler
   resolves the chain via stealth_order_id directly — see
   ``_placement_client_order_id_for_order``).
"""

from unittest.mock import MagicMock

from core.stealth_order_manager import StealthOrderManager


def _make_manager():
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager._save_stealth_order_to_db = MagicMock()
    manager._update_stealth_order = MagicMock()
    manager._record_reveal_event = MagicMock()
    manager._apply_reveal_condition_price_tracking = MagicMock()
    manager._next_anchor_reprice_seconds = MagicMock(return_value=60)
    # The reprice-skip heuristic considers price tolerance / cooldowns. We
    # always want to exercise the placement path in these tests.
    manager._should_skip_anchor_reprice = MagicMock(return_value=False)
    return manager


def _patch_rest_and_db(monkeypatch, *, place_response=None):
    import configuration as _configuration

    rest_client = MagicMock()
    rest_client.place_limit_order = MagicMock(
        return_value=place_response
        or {"success": True, "success_response": {"order_id": "exch-new-1"}}
    )
    monkeypatch.setattr(_configuration, "REST_CLIENT", rest_client, raising=True)

    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **_: 1,
        raising=True,
    )
    return rest_client


def _build_order(stealth_id="stealth-1"):
    return {
        "stealth_order_id": stealth_id,
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "limit_price": 78500.0,
        "remaining_size": 1.0,
        "revealed_size": 1.0,
        "max_order_replacements": 5,
        "allow_partial_fills": False,
        "parent_order_id": None,  # root
        "anchor_repricing_policy_json": {
            "enabled": True,
            "post_only_required": False,
            "should_reprice_revealed": True,
        },
        "anchor_repricing_state_json": {},
        "revealed_orders": [],
    }


def _build_state():
    return {
        "active_exchange_order_id": "exch-old-1",
        "active_exchange_price": 78500.0,
        "active_placement_client_order_id": "old-placement-uuid",
        "current_logical_limit_price": 78500.0,
    }


def test_anchor_reprice_pre_registers_placement_before_rest(monkeypatch):
    """The pre-register callback must fire BEFORE place_limit_order so the
    inevitable WS event for the new placement COID resolves to LOCAL."""
    manager = _make_manager()
    rest_client = _patch_rest_and_db(monkeypatch)

    call_order = []

    def fake_register(placement_coid, chain_root_coid):
        call_order.append(("pre_register", placement_coid, chain_root_coid))

    def fake_place(**kwargs):
        call_order.append(("place_limit_order", kwargs.get("client_order_id")))
        return {"success": True, "success_response": {"order_id": "exch-new-1"}}

    manager.placement_register_callback = fake_register
    rest_client.place_limit_order.side_effect = fake_place

    order = _build_order("stealth-1")
    state = _build_state()

    result = manager._apply_revealed_anchor_reprice(
        order=order,
        policy=order["anchor_repricing_policy_json"],
        state=state,
        market_data={"bid": 78495.0, "ask": 78505.0, "price": 78500.0, "source": "ticker"},
        desired_price=78498.0,
        target_price=78498.0,
        max_boundary_price=78600.0,
        reprice_reason="reference_price_updated_slide_step",
    )

    assert result is True

    # Two events must have happened, in this order:
    #   1) pre_register(placement_uuid, "stealth-1")
    #   2) place_limit_order(client_order_id=placement_uuid)
    assert len(call_order) >= 2, f"expected register+place, got {call_order}"

    # Locate the first occurrence of each.
    pre_idx = next(i for i, e in enumerate(call_order) if e[0] == "pre_register")
    place_idx = next(i for i, e in enumerate(call_order) if e[0] == "place_limit_order")
    assert pre_idx < place_idx, (
        f"pre_register must run BEFORE place_limit_order; got {call_order}"
    )

    pre_event = call_order[pre_idx]
    place_event = call_order[place_idx]

    # The COID passed to register and the COID passed to REST must be the
    # same UUID (otherwise the WS event will still miss the cache).
    assert pre_event[1] == place_event[1], (
        f"placement COID mismatch: register={pre_event[1]!r}, "
        f"rest={place_event[1]!r}"
    )

    # The chain root passed to register must be the stealth_order_id (root
    # has parent_order_id=None — flat hierarchy).
    assert pre_event[2] == "stealth-1"


def test_anchor_reprice_no_callback_does_not_crash(monkeypatch):
    """Callback unset (e.g. in tests / before bridge wiring) must be a no-op,
    not a crash. Reprice still proceeds."""
    manager = _make_manager()
    rest_client = _patch_rest_and_db(monkeypatch)

    # No callback set.
    assert manager.placement_register_callback is None

    order = _build_order("stealth-2")
    state = _build_state()

    result = manager._apply_revealed_anchor_reprice(
        order=order,
        policy=order["anchor_repricing_policy_json"],
        state=state,
        market_data={"bid": 78495.0, "ask": 78505.0, "price": 78500.0, "source": "ticker"},
        desired_price=78498.0,
        target_price=78498.0,
        max_boundary_price=78600.0,
        reprice_reason="reference_price_updated_slide_step",
    )
    assert result is True
    rest_client.place_limit_order.assert_called_once()


def test_pre_register_helper_skips_when_placement_equals_root():
    """Helper must no-op when placement COID == chain root (no-reprice
    policy path: WS handler resolves chain via stealth_order_id directly)."""
    manager = _make_manager()
    invocations = []
    manager.placement_register_callback = lambda c, r: invocations.append((c, r))

    manager._pre_register_placement_in_orderbook("same-coid", "same-coid")
    assert invocations == []

    manager._pre_register_placement_in_orderbook("placement", "root")
    assert invocations == [("placement", "root")]


def test_pre_register_helper_swallows_callback_exceptions():
    """A buggy callback must not break the placement flow — the DB pre-insert
    is still authoritative. Exception is logged, not raised."""
    manager = _make_manager()
    log = MagicMock()
    manager.log_callback = log

    def boom(_c, _r):
        raise RuntimeError("downstream wired wrong")

    manager.placement_register_callback = boom

    # Must not raise.
    manager._pre_register_placement_in_orderbook("placement", "root")

    # Failure must be surfaced via log_callback (warn level).
    assert log.called
    level, payload = log.call_args.args
    assert level == "warning"
    assert isinstance(payload, dict)
    assert payload.get("event") == "stealth_placement_pre_register_failed"
    assert payload.get("placement_client_order_id") == "placement"
    assert payload.get("chain_root_client_order_id") == "root"
