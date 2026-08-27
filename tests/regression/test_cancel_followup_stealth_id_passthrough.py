"""Regression: 2026-05-04 phantom-child / stranded-exposure incident.

Background
==========

Sequence in production:

1. SELL 10 BIP-20DEC30-CDE stealth root ``a853db8e`` configured with
   ``max_order_replacement = 1`` (re-anchor budget = 1).
2. Reveal placed exchange child ``78f22189`` (a fresh placement uuid;
   distinct from the stealth_order_id).
3. The exchange CANCELLED ``78f22189`` immediately after placement.
4. ``OrderEngine.handle_cancelled_order`` ran the stealth follow-up
   branch.

Bug
---

The cancel branch passed the *placement uuid* into
``create_follow_up_stealth_order(original_stealth_order_id=...)``
instead of the *stealth_order_id* of the resolved
``original_stealth_order``. Inside the manager
``_get_stealth_order(<placement_uuid>)`` returned ``None`` (placement
uuids are NOT keys in the stealth table), so the function silently
returned ``None``.

That ``None`` was then handed straight to
``register_child_order(None, root)`` which:

* appended ``None`` into the parent's ``orders`` list,
* burned the only replacement slot (``current_order_replacement``
  0 -> 1),
* persisted the bump to the DB.

Net result: the parent row was CANCELLED with replacement budget
exhausted by a phantom, no real follow-up was created, and the
intended SELL 10 exposure was stranded with zero recovery path.

Fix (three layers)
==================

1. Pass ``original_stealth_order["stealth_order_id"]`` (not the bare
   ``client_order_id``) at the call site.
2. If ``create_follow_up_stealth_order`` returns ``None``, log an
   error and do NOT register a phantom child; release the follow-up
   processing flag for retry.
3. ``register_child_order`` rejects ``child_client_order_id is None``
   at the contract boundary so any future drift cannot burn cap on a
   phantom.

These tests pin all three layers.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from tests.unit.test_partial_fill_followups import (
    _build_engine_for_partial_fill_tests,
)


# ---------------------------------------------------------------------------
# Layer 3: register_child_order contract guard
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_register_child_order_rejects_none_child_without_burning_slot():
    """Passing ``None`` must not consume a replacement slot, must not
    pollute ``orders``/``child_order_ids``, and must not call into the
    DB increment helper."""
    engine = _build_engine_for_partial_fill_tests()
    parent_id = "p-guard"
    engine.orderbook.parent_order_ids[parent_id] = {
        "allow_partial_fills": False,
        "orders": [],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": 1,
        "current_order_replacement": 0,
    }

    with patch(
        "database.order.increment_order_parent_replacement_count"
    ) as mock_inc:
        engine.register_child_order(None, parent_id)

    parent = engine.orderbook.parent_order_ids[parent_id]
    assert parent["current_order_replacement"] == 0, (
        "register_child_order(None, ...) burned a replacement slot â€” "
        "the 2026-05-04 phantom-child bug regressed."
    )
    assert parent["orders"] == [], (
        "register_child_order(None, ...) appended None into orders list."
    )
    assert None not in engine.orderbook.child_order_ids
    mock_inc.assert_not_called()


# ---------------------------------------------------------------------------
# Layer 1+2: handle_cancelled_order â€” stealth_id pass-through + None guard
# ---------------------------------------------------------------------------


def _wire_cancel_path(
    engine,
    *,
    placement_uuid: str,
    stealth_root_id: str,
    parent_db_row: dict,
):
    """Stub the collaborators of ``handle_cancelled_order`` enough to
    exercise the stealth follow-up branch end-to-end."""
    # Mark the placement uuid as a child of the root in the in-memory
    # orderbook so _is_external_order returns False.
    engine.orderbook.child_order_ids[placement_uuid] = stealth_root_id
    engine.orderbook.parent_order_ids[stealth_root_id] = {
        "allow_partial_fills": False,
        "orders": [placement_uuid],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": 1,
        # Cap already consumed by the original placement â€” exact prod scenario.
        "current_order_replacement": 1,
        "externally_created": False,
    }
    engine.orderbook.should_replace = {"FILLED": True, "CANCELLED": True}

    # Stealth bridge / manager: find_stealth_order_by_placed_order_id
    # must return a dict that carries the REAL stealth_order_id.
    stealth_record = {
        "stealth_order_id": stealth_root_id,
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "parent_order_id": None,
    }
    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = stealth_record
    stealth_manager.update_execution = Mock()
    stealth_bridge = Mock()
    stealth_bridge.stealth_manager = stealth_manager
    engine.stealth_order_bridge = stealth_bridge

    # compute_order_template / child_order_already_exists / etc.
    engine.compute_order_template = Mock(return_value={
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "order_base_size": 10.0,
        "start_price": 80355.0,
    })
    engine.child_order_already_exists = Mock(return_value=False)
    engine.resolve_parent_client_order_id = Mock(
        return_value=(stealth_root_id, stealth_root_id)
    )
    engine.register_child_order = Mock()

    # DB lookups used in the branch.
    engine.db_module.get_parent_order = Mock(return_value=parent_db_row)

    return stealth_bridge, stealth_record


@pytest.mark.regression
def test_cancel_followup_passes_stealth_order_id_not_placement_uuid():
    """The cancel branch must look up the stealth chain by its
    ``stealth_order_id``, never by the placement uuid that was just
    cancelled. Pre-fix, the placement uuid leaked through and caused
    silent ``None`` returns."""
    engine = _build_engine_for_partial_fill_tests()
    placement_uuid = "78f22189-eb33-4768-91c7-6da14cd3116b"
    stealth_root_id = "a853db8e-b3bc-43c4-8901-d0a80e0f7179"

    stealth_bridge, stealth_record = _wire_cancel_path(
        engine,
        placement_uuid=placement_uuid,
        stealth_root_id=stealth_root_id,
        parent_db_row={
            "target_movement": 0.001,
            "target_movement_type": "P",
        },
    )
    # Make the manager return a real follow-up id so the success branch runs.
    stealth_bridge.create_follow_up_stealth_order = Mock(
        return_value="new-follow-up-id"
    )

    # has_pending_move is imported lazily inside the method.
    with patch("database.order.has_pending_move", return_value=False), patch(
        "database.order.get_parent_order",
        return_value={
            "target_movement": 0.001,
            "target_movement_type": "P",
        },
    ):
        engine.handle_cancelled_order({
            "client_order_id": placement_uuid,
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "status": "CANCELLED",
            "price": 80355.0,
        })

    stealth_bridge.create_follow_up_stealth_order.assert_called_once()
    kwargs = stealth_bridge.create_follow_up_stealth_order.call_args.kwargs
    assert kwargs["original_stealth_order_id"] == stealth_root_id, (
        f"Cancel-path leaked the placement uuid into "
        f"create_follow_up_stealth_order(original_stealth_order_id=...). "
        f"Expected stealth_order_id={stealth_root_id!r}, got "
        f"{kwargs['original_stealth_order_id']!r}. This is the 2026-05-04 "
        f"phantom-child bug regressing."
    )

    # And the real follow-up id must be the child registered (not None).
    engine.register_child_order.assert_called_once_with(
        "new-follow-up-id", stealth_root_id
    )


@pytest.mark.regression
def test_cancel_followup_none_return_does_not_register_phantom_child():
    """If ``create_follow_up_stealth_order`` returns ``None``, the
    cancel branch must NOT call ``register_child_order`` (which would
    burn a replacement slot on a phantom). The follow-up processing
    flag must be released so a retry path stays open."""
    engine = _build_engine_for_partial_fill_tests()
    placement_uuid = "placement-xyz"
    stealth_root_id = "root-xyz"

    stealth_bridge, _ = _wire_cancel_path(
        engine,
        placement_uuid=placement_uuid,
        stealth_root_id=stealth_root_id,
        parent_db_row={
            "target_movement": 0.001,
            "target_movement_type": "P",
        },
    )
    stealth_bridge.create_follow_up_stealth_order = Mock(return_value=None)

    # Spy on the processing-flag lifecycle.
    engine.release_follow_up_processing = Mock(
        wraps=engine.release_follow_up_processing
    )
    engine.complete_follow_up_processing = Mock(
        wraps=engine.complete_follow_up_processing
    )

    with patch("database.order.has_pending_move", return_value=False), patch(
        "database.order.get_parent_order",
        return_value={
            "target_movement": 0.001,
            "target_movement_type": "P",
        },
    ):
        engine.handle_cancelled_order({
            "client_order_id": placement_uuid,
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "status": "CANCELLED",
            "price": 80355.0,
        })

    engine.register_child_order.assert_not_called()
    # Flag released (not completed) so a future event can retry.
    engine.release_follow_up_processing.assert_called_once_with(
        "cancelled", placement_uuid
    )
    engine.complete_follow_up_processing.assert_not_called()
