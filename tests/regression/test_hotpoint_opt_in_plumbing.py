"""Regression: enable_hotpoint_replication is plumbed end-to-end.

The hotpoint dispatcher (``OrderEngine._maybe_dispatch_hotpoint``) gates on
``_get_parent_enable_hotpoint_replication(parent_root)``. That gate reads
the orderbook cache first, then falls back to ``get_parent_order(...)`` from
the DB. So the flag MUST land on the row written by
``insert_order_parent`` for the stealth root.

These tests pin the contract from the public API down to the DB call:

1. ``StealthOrderManager.create_stealth_order(enable_hotpoint_replication=True)``
   passes the flag to ``insert_order_parent`` for the ROOT branch
   (``parent_order_id is None``).
2. The same call with the default (``False``) writes ``False``.
3. Stealth child branch (``parent_order_id`` set) does NOT set the flag on
   the child row — children inherit at lookup time via chain-root resolution,
   and setting the flag on children would risk cascading auto-placements.
"""

from unittest.mock import MagicMock

from core.stealth_order_manager import StealthOrderManager


HOTPOINT_PRODUCT_ID = "BIP-20DEC30-CDE"


def _make_manager():
    mgr = StealthOrderManager(db_client=None, log_callback=MagicMock())
    mgr._save_stealth_order_to_db = MagicMock()
    mgr._update_stealth_order = MagicMock()
    return mgr


def _capture_insert(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **kwargs: calls.append(kwargs),
        raising=True,
    )
    return calls


def test_root_stealth_order_propagates_hotpoint_flag_true(monkeypatch):
    mgr = _make_manager()
    calls = _capture_insert(monkeypatch)

    mgr.create_stealth_order(
        product_id=HOTPOINT_PRODUCT_ID,
        side="BUY",
        total_size=1.0,
        limit_price=100000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
        enable_hotpoint_replication=True,
    )

    assert len(calls) == 1
    assert calls[0]["enable_hotpoint_replication"] is True
    assert calls[0].get("parent_order_id") in (None, "")


def test_root_stealth_order_default_is_opt_out(monkeypatch):
    mgr = _make_manager()
    calls = _capture_insert(monkeypatch)

    mgr.create_stealth_order(
        product_id=HOTPOINT_PRODUCT_ID,
        side="BUY",
        total_size=1.0,
        limit_price=100000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
    )

    assert len(calls) == 1
    assert calls[0]["enable_hotpoint_replication"] is False


def test_stealth_child_branch_does_not_set_hotpoint_flag(monkeypatch):
    """No-cascade rule: children inherit from chain root; their own row stays
    opt-out so the stealth child branch can never become a triggering source
    independent of the root's choice.
    """
    mgr = _make_manager()
    calls = _capture_insert(monkeypatch)

    # Even if the caller (somehow) tries to opt a CHILD in, the child branch
    # ignores the flag — only the root branch propagates it. This guards
    # against accidental cascade if a future caller passes the kwarg through
    # a follow-up creation path.
    mgr.create_stealth_order(
        product_id=HOTPOINT_PRODUCT_ID,
        side="SELL",
        total_size=1.0,
        limit_price=100000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
        parent_order_id="some-root-uuid",
        enable_hotpoint_replication=True,
    )

    assert len(calls) == 1
    # Child row keys do not include enable_hotpoint_replication — defaults
    # to False at the DB layer.
    assert "enable_hotpoint_replication" not in calls[0] or \
        calls[0]["enable_hotpoint_replication"] is False
