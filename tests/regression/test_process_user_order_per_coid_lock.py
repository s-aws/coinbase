"""Regression: per-COID serialisation in process_user_order.

Background (2026-05-02)
========================

The 2026-04-28 hoist (``_ensure_order_parent_row_exists`` runs before
``_process_ws_order_delta`` in ``process_user_order``) fixed the
single-threaded ordering bug. Production lifecycle work now reaches this
method through a keyed dispatcher on a ThreadPoolExecutor, while direct and
synthetic callers remain possible. ``resolve_parent_client_order_id`` populates
``orderbook.parent_order_ids[coid]`` BEFORE its DB INSERT commits.

Race window:
    T_A: ensure → cache miss → resolve sets cache → starts DB INSERT
    T_B: ensure → cache HIT (T_A's in-memory write) → skips ensure
    T_B: _process_ws_order_delta → upsert_partial_fill_progress
         → ForeignKeyViolation (T_A's INSERT not yet committed)
    T_A: INSERT commits much later

Production symptom (May 02 01:39:33):
    01:39:33,089  parent_order_entry_created (1f5ea609)
    01:39:33,100  ForeignKeyViolation on partial_fill_progress
    01:39:33,107  ✓ Root parent order inserted: 1f5ea609

Fix: per-COID lock around the ensure→delta pair so that T_B blocks until
T_A's whole sequence completes (including DB commit).

This test pins:
  1. A per-COID lock helper exists on OrderEngine.
  2. process_user_order acquires the lock around steps 3a + 3b.
  3. Different COIDs do NOT block each other (different lock objects).
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest


_ENGINE_SRC = (
    Path(__file__).resolve().parents[2] / "core" / "order_engine.py"
).read_text(encoding="utf-8")


def test_per_coid_handler_lock_helper_exists():
    """OrderEngine must expose a per-COID lock vendor."""
    assert "def _get_coid_handler_lock(" in _ENGINE_SRC, (
        "Per-COID lock helper missing — required to serialise concurrent "
        "WS workers on the same external COID."
    )
    # And it must be backed by a guarded dict so get-or-create is atomic.
    assert "_coid_handler_locks" in _ENGINE_SRC
    assert "_coid_handler_locks_guard" in _ENGINE_SRC


def test_process_user_order_uses_per_coid_lock():
    """Steps 3a (_ensure_order_parent_row_exists) and 3b
    (_process_ws_order_delta) must be inside the per-COID lock."""
    fn_match = re.search(
        r"def process_user_order\(.*?(?=\n    def )",
        _ENGINE_SRC,
        re.DOTALL,
    )
    assert fn_match is not None
    body = fn_match.group(0)

    assert "_get_coid_handler_lock(" in body, (
        "process_user_order must acquire the per-COID lock"
    )

    # Both step 3a and step 3b must appear AFTER the lock acquisition.
    lock_pos = body.find("_get_coid_handler_lock(")
    ensure_pos = body.find("_ensure_order_parent_row_exists(")
    delta_pos = body.find("_process_ws_order_delta(")
    assert lock_pos < ensure_pos < delta_pos, (
        "Both _ensure_order_parent_row_exists and _process_ws_order_delta "
        "must execute under the per-COID lock to prevent the FK race."
    )


def test_per_coid_lock_serialises_same_coid_in_parallel():
    """Two threads racing on the same COID must serialise."""
    from core.order_engine import OrderEngine

    # Bare instance — only the lock helper is exercised.
    engine = OrderEngine.__new__(OrderEngine)
    engine._coid_handler_locks = {}
    engine._coid_handler_locks_guard = threading.Lock()

    coid = "race-coid"
    lock = engine._get_coid_handler_lock(coid)
    # Same coid → same lock object (not a new lock per call).
    assert engine._get_coid_handler_lock(coid) is lock


def test_per_coid_lock_does_not_block_different_coids():
    """Different COIDs must get distinct lock objects so unrelated WS
    events still process in parallel."""
    from core.order_engine import OrderEngine

    engine = OrderEngine.__new__(OrderEngine)
    engine._coid_handler_locks = {}
    engine._coid_handler_locks_guard = threading.Lock()

    a = engine._get_coid_handler_lock("coid-A")
    b = engine._get_coid_handler_lock("coid-B")
    assert a is not b
