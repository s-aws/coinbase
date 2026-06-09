"""Regression test pinning the v1 contract for "move REVEALED stealth order".

Feature design notes
--------------------
Coinbase exposes no order-edit endpoint, so a "move" of a REVEALED stealth
order is implemented as cancel-and-replace on the exchange while keeping the
same internal ``stealth_order_id``. The new placement uses the existing
:class:`RevealExecutionPlan` pricing path and resets the per-order anchor
repricing state and ``revealed_orders[]`` history. Flat hierarchy is
preserved via :func:`resolve_stealth_chain_root`.

This test file is the **failing v1 contract**. It is written before the
implementation exists; the symbols it imports (``ClaimLedger``,
``StealthMutationKind``, ``StealthMovePlan``, ``build_stealth_move_plan``,
``execute_stealth_move``, ``try_claim_mutation``, ``release_mutation``)
are introduced by the upcoming implementation work. Until then this file
is expected to fail collection, which is intentional — see TDD step 2 in
the design discussion.

Pinned invariants
-----------------
1. **ClaimLedger extraction** — three-state per-key ledger (absent /
   processing / done) is reusable infrastructure, not bolted onto
   :class:`OrderBook`. Existing follow-up claim semantics survive the
   refactor.
2. **StealthMutationKind** is a typed enum, never magic strings.
3. **Mutations are repeatable** — there is no ``complete_mutation`` API.
   ``release_mutation`` always returns the slot to ``absent``.
4. **Reprice loop respects the move claim** — a held ``"move"`` claim
   blocks ``process_anchor_repricing_for_product`` from acting on the
   same order.
5. **build_stealth_move_plan rejects partial fills** — ``executed_size > 0``
   must be rejected at plan-build time in v1.
6. **execute_stealth_move resets** ``anchor_repricing_state_json`` and
   ``revealed_orders[]`` to defaults; flat hierarchy preserved.
7. **Static-source guard** — every ``REST_CLIENT.cancel_orders`` call
   that targets a stealth-revealed exchange order id must live inside
   one of the sanctioned methods. New callers force an explicit
   allowlist update so the duplicated-rule pattern (see
   ``/memories/duplicated-rule-pattern.md``) cannot recur silently.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _enable_spot_capability(monkeypatch, capability):
    from core.enums import ProductCapabilityMode, ProductType

    monkeypatch.setattr(
        "configuration.PRODUCT_CAPABILITIES",
        {
            "product_type": {
                ProductType.SPOT.value: {
                    capability.value: ProductCapabilityMode.ENABLED.value,
                },
            },
        },
    )


def _revealed_spot_order(
    *,
    stealth_order_id="sid_spot_move",
    side="BUY",
    remaining_size=0.1,
    limit_price=100.0,
    executed_size=0.0,
):
    from core.enums import StealthOrderStatus

    return {
        "stealth_order_id": stealth_order_id,
        "parent_order_id": "root_spot_parent",
        "product_id": "BTC-USD",
        "side": side,
        "status": StealthOrderStatus.REVEALED.value,
        "executed_size": executed_size,
        "remaining_size": remaining_size,
        "total_size": remaining_size + executed_size,
        "limit_price": limit_price,
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": "old_spot_placement",
            "active_exchange_order_id": "old_spot_exchange",
            "active_exchange_price": limit_price,
        },
        "anchor_repricing_policy_json": {"enabled": True},
        "revealed_orders": [
            {
                "reveal_number": 1,
                "placed_order_id": "old_spot_placement",
            },
        ],
    }


# ---------------------------------------------------------------------------
# 1) ClaimLedger extraction preserves follow-up semantics
# ---------------------------------------------------------------------------


class TestClaimLedgerExtraction:
    """The follow-up claim mechanism is generic — extract it to a reusable
    ``ClaimLedger`` class and have ``OrderBook`` delegate to an instance.
    All existing follow-up tests must continue to pass; this just pins
    the new public API."""

    def test_claim_ledger_is_importable_from_orderbook_module(self):
        from core.orderbook import ClaimLedger  # noqa: F401

    def test_claim_ledger_three_state_lifecycle(self):
        from core.enums import FollowUpKind
        from core.orderbook import ClaimLedger

        ledger = ClaimLedger(FollowUpKind)
        assert ledger.try_claim(FollowUpKind.FILLED, "coid_1") is True
        # Re-claim while processing → False
        assert ledger.try_claim(FollowUpKind.FILLED, "coid_1") is False
        # Different kind same id → independent namespace
        assert ledger.try_claim(FollowUpKind.CANCELLED, "coid_1") is True
        # Release returns slot to absent → may be re-claimed
        ledger.release(FollowUpKind.FILLED, "coid_1")
        assert ledger.try_claim(FollowUpKind.FILLED, "coid_1") is True
        # Complete is terminal — re-claim forbidden forever
        ledger.complete(FollowUpKind.FILLED, "coid_1")
        assert ledger.try_claim(FollowUpKind.FILLED, "coid_1") is False

    def test_claim_ledger_validates_kind_at_boundary(self):
        from core.enums import FollowUpKind
        from core.orderbook import ClaimLedger

        ledger = ClaimLedger(FollowUpKind)
        with pytest.raises(ValueError):
            ledger.try_claim("not_a_real_kind", "coid_1")

    def test_orderbook_follow_up_api_still_works_after_extraction(self):
        """Smoke test — the existing OrderBook public API delegates to the
        new ledger but its observable behaviour is unchanged. The full
        follow-up contract is already pinned by the existing follow-up
        tests; this one just ensures the refactor preserves it."""
        from core.enums import FollowUpKind
        from core.orderbook import OrderBook

        ob = OrderBook()
        assert ob.try_claim_follow_up(FollowUpKind.FILLED, "x") is True
        assert ob.try_claim_follow_up(FollowUpKind.FILLED, "x") is False
        ob.release_follow_up(FollowUpKind.FILLED, "x")
        assert ob.try_claim_follow_up(FollowUpKind.FILLED, "x") is True
        ob.complete_follow_up(FollowUpKind.FILLED, "x")
        assert ob.try_claim_follow_up(FollowUpKind.FILLED, "x") is False


# ---------------------------------------------------------------------------
# 2) StealthMutationKind enum + StealthOrderManager mutation claim API
# ---------------------------------------------------------------------------


class TestStealthMutationKindEnum:

    def test_enum_values_are_stable(self):
        from core.enums import StealthMutationKind

        # Values are string-stable so they can appear safely in logs / DB.
        assert StealthMutationKind.MOVE.value == "move"
        assert StealthMutationKind.REPRICE.value == "reprice"
        assert StealthMutationKind.RETREAT.value == "retreat"

    def test_enum_is_used_at_boundary_not_magic_strings(self):
        """Builder/executor signatures must accept the enum, not bare strings."""
        from core.enums import StealthMutationKind

        # Sanity: members iterable; allows extension test below to enumerate.
        assert {k.value for k in StealthMutationKind} == {"move", "reprice", "retreat"}


class TestStealthMutationClaims:
    """``StealthOrderManager`` exposes a ``ClaimLedger``-backed mutation
    API. Mutations are *repeatable* — there is intentionally no
    ``complete_mutation`` method, because a stealth order can be moved
    or repriced any number of times during its life."""

    def _bare_manager(self):
        # Mirror the pattern used by tests/regression/test_repricing_policy.py
        # — bypass __init__ so we don't need a DB client.
        from core.stealth_order_manager import StealthOrderManager

        mgr = StealthOrderManager.__new__(StealthOrderManager)
        # Real implementation must initialise the ledger in __init__; for
        # the bare instance we mimic that here so the test isolates the
        # ledger contract from the rest of __init__.
        from core.enums import StealthMutationKind
        from core.orderbook import ClaimLedger

        mgr._mutation_claims = ClaimLedger(StealthMutationKind)
        return mgr

    def test_move_claim_is_exclusive(self):
        from core.enums import StealthMutationKind

        mgr = self._bare_manager()
        assert mgr.try_claim_mutation(StealthMutationKind.MOVE, "sid_1") is True
        assert mgr.try_claim_mutation(StealthMutationKind.MOVE, "sid_1") is False

    def test_release_makes_mutation_repeatable(self):
        from core.enums import StealthMutationKind

        mgr = self._bare_manager()
        assert mgr.try_claim_mutation(StealthMutationKind.MOVE, "sid_1") is True
        mgr.release_mutation(StealthMutationKind.MOVE, "sid_1")
        # Critical: a successful move must leave the slot free for a future move.
        assert mgr.try_claim_mutation(StealthMutationKind.MOVE, "sid_1") is True

    def test_no_complete_mutation_method_exists(self):
        """Mutations are repeatable — a terminal ``done`` state would be a
        bug. Pin this by asserting the API surface."""
        mgr = self._bare_manager()
        assert not hasattr(mgr, "complete_mutation"), (
            "complete_mutation must NOT exist: stealth mutations are repeatable. "
            "Use release_mutation in both success and failure paths."
        )

    def test_move_and_reprice_are_independent_namespaces(self):
        from core.enums import StealthMutationKind

        mgr = self._bare_manager()
        assert mgr.try_claim_mutation(StealthMutationKind.MOVE, "sid_1") is True
        # A held MOVE claim does NOT block REPRICE on a *different* order.
        assert mgr.try_claim_mutation(StealthMutationKind.REPRICE, "sid_2") is True

    def test_move_and_reprice_are_mutually_exclusive_for_same_sid(self):
        """Cross-kind exclusion per stealth_order_id.

        While a MOVE is in flight on ``sid_1``, no concurrent REPRICE on
        the same sid may proceed (and vice versa). Without this guarantee
        the ticker reprice loop could cancel-and-replace the same exchange
        order that the manual move is cancelling, double-billing the
        order and leaving phantom placements behind.
        """
        from core.enums import StealthMutationKind

        mgr = self._bare_manager()
        assert mgr.try_claim_mutation(StealthMutationKind.MOVE, "sid_1") is True
        # Same sid, different kind → must fail.
        assert mgr.try_claim_mutation(StealthMutationKind.REPRICE, "sid_1") is False
        # After release, the other kind may proceed.
        mgr.release_mutation(StealthMutationKind.MOVE, "sid_1")
        assert mgr.try_claim_mutation(StealthMutationKind.REPRICE, "sid_1") is True


# ---------------------------------------------------------------------------
# 3) Reprice loop respects the move claim
# ---------------------------------------------------------------------------


class TestRepricingSkipsHeldMoveClaim:
    """While a manual move holds the ``"move"`` claim on a stealth order,
    the ticker-driven reprice loop must skip that order.

    Two paired tests guard against vacuous-pass regressions:

    1. ``test_apply_called_without_move_claim`` (positive control) —
       proves the fixture is wired richly enough that the loop
       *would* reach ``_apply_revealed_anchor_reprice`` if the claim
       guard were removed.
    2. ``test_process_anchor_repricing_skips_when_move_claim_held`` —
       runs the same fixture with the MOVE claim held, asserts the
       apply call is suppressed.

    Without the positive control, a future refactor could short-circuit
    the loop earlier (e.g. add a new pre-check that always skips this
    fixture) and the negative test would silently degrade to vacuous."""

    def _build_reprice_loop_fixture(self):
        """Shared fixture: one REVEALED stealth order with a fully
        populated repricing policy + active state, where the loop will
        reach ``_apply_revealed_anchor_reprice``."""
        from core.enums import StealthMutationKind, StealthOrderStatus
        from core.orderbook import ClaimLedger
        from core.stealth_order_manager import StealthOrderManager

        mgr = StealthOrderManager.__new__(StealthOrderManager)
        mgr._mutation_claims = ClaimLedger(StealthMutationKind)
        mgr.in_memory_orders = {
            "sid_1": {
                "stealth_order_id": "sid_1",
                "product_id": "BIP-20DEC30-CDE",
                "side": "BUY",
                "status": StealthOrderStatus.REVEALED.value,
                "remaining_size": 1.0,
                "limit_price": 100.0,
                "anchor_repricing_policy_json": {
                    "enabled": True,
                    "allow_revealed_reprice": True,
                    "target_distance": 0.1,
                    "max_distance": 0.5,
                    "distance_type": "P",
                },
                # Active state with an exchange placement so the REVEALED
                # branch has a current_price to compare against.
                "anchor_repricing_state_json": {
                    "active_placement_client_order_id": "old_placement",
                    "active_exchange_order_id": "old_exchange",
                    "active_exchange_price": 100.0,
                    "next_reprice_at": None,
                },
            }
        }
        mgr._placed_order_index = {}
        mgr.log_callback = lambda *a, **k: None
        return mgr

    def _patched_loop(self, mgr):
        """Common patches for both tests: anchor enough of the
        downstream helpers that the loop reaches the apply branch
        without touching DB/REST."""
        return (
            patch.object(mgr, "_get_active_stealth_orders", return_value=["sid_1"]),
            patch.object(
                mgr,
                "_get_current_market_data",
                return_value={
                    "source": "ticker",
                    "bid": 99.5,
                    "ask": 100.5,
                    "price": 100.0,
                },
            ),
            # Force the profitability gate to allow the reprice so the
            # loop reaches the REVEALED apply branch deterministically.
            patch.object(
                mgr,
                "_validate_anchor_reprice_profitability",
                return_value=(True, "ok"),
            ),
            patch.object(mgr, "_update_stealth_order"),
        )

    def test_apply_called_without_move_claim(self):
        """Positive control: with no MOVE claim held, the same fixture
        MUST reach ``_apply_revealed_anchor_reprice``. If this test
        fails, the negative test below has degraded to vacuous and the
        fixture needs updating."""
        mgr = self._build_reprice_loop_fixture()
        patches = self._patched_loop(mgr)

        with patches[0], patches[1], patches[2], patches[3], patch.object(
            mgr, "_apply_revealed_anchor_reprice", return_value=True
        ) as apply_mock:
            mgr.process_anchor_repricing_for_product("BIP-20DEC30-CDE")

        assert apply_mock.called, (
            "Positive control failed: the reprice loop short-circuited "
            "before reaching _apply_revealed_anchor_reprice even with no "
            "MOVE claim held. The fixture is no longer rich enough; the "
            "negative test (test_process_anchor_repricing_skips_when_move_claim_held) "
            "is now VACUOUS — it would pass even if the move-claim guard "
            "were deleted. Update the fixture to restore non-vacuous coverage."
        )

    def test_process_anchor_repricing_skips_when_move_claim_held(self):
        """Negative test: holding the MOVE claim must suppress the
        reprice apply call for the same sid. Paired with the positive
        control above to guarantee non-vacuous coverage."""
        from core.enums import StealthMutationKind

        mgr = self._build_reprice_loop_fixture()

        # Hold the move claim: reprice for this sid must short-circuit.
        assert mgr.try_claim_mutation(StealthMutationKind.MOVE, "sid_1") is True

        patches = self._patched_loop(mgr)
        with patches[0], patches[1], patches[2], patches[3], patch.object(
            mgr, "_apply_revealed_anchor_reprice"
        ) as apply_mock:
            mgr.process_anchor_repricing_for_product("BIP-20DEC30-CDE")

        assert apply_mock.call_count == 0, (
            "process_anchor_repricing_for_product reached "
            "_apply_revealed_anchor_reprice for an order with a held MOVE claim. "
            "The loop must call try_claim_mutation(REPRICE, sid) and skip on False, "
            "OR check that no MOVE claim is held, before mutating exchange state."
        )


# ---------------------------------------------------------------------------
# 4) build_stealth_move_plan rejects partially-filled orders (v1 scope)
# ---------------------------------------------------------------------------


class TestBuildStealthMovePlanRejectsPartialFills:
    """v1 contract: moves are price-only and require the order to have
    zero executed size. Reduce-only replacement after partial fills is
    explicitly out of scope and tracked for v2."""

    def test_rejects_when_executed_size_positive(self):
        from core.stealth_order_manager import StealthOrderManager

        mgr = StealthOrderManager.__new__(StealthOrderManager)
        mgr.log_callback = lambda *a, **k: None
        with patch.object(
            mgr,
            "_get_stealth_order",
            return_value={
                "stealth_order_id": "sid_1",
                "status": "REVEALED",
                "executed_size": 0.25,
                "remaining_size": 0.75,
                "side": "BUY",
                "product_id": "BIP-20DEC30-CDE",
                "limit_price": 100.0,
            },
        ):
            with pytest.raises(Exception) as exc_info:
                mgr.build_stealth_move_plan(
                    stealth_order_id="sid_1",
                    new_limit_price=101.0,
                )
        # Implementation MAY raise a dedicated StealthMoveError; we
        # accept any subclass of Exception but require a clear message.
        assert "executed_size" in str(exc_info.value).lower() or \
               "partial" in str(exc_info.value).lower()

    def test_spot_rejects_partial_fill_when_move_capability_enabled(
        self,
        monkeypatch,
    ):
        from core.enums import ProductCapability
        from core.stealth_order_manager import StealthOrderManager

        _enable_spot_capability(monkeypatch, ProductCapability.MOVE_REVEALED)

        mgr = StealthOrderManager.__new__(StealthOrderManager)
        mgr.log_callback = lambda *a, **k: None
        mgr._get_account_wallets_for_action_guard = MagicMock()
        with patch.object(
            mgr,
            "_get_stealth_order",
            return_value=_revealed_spot_order(executed_size=0.01),
        ):
            with pytest.raises(Exception) as exc_info:
                mgr.build_stealth_move_plan(
                    stealth_order_id="sid_spot_move",
                    new_limit_price=101.0,
                )

        assert "executed_size" in str(exc_info.value).lower() or \
               "partial" in str(exc_info.value).lower()
        mgr._get_account_wallets_for_action_guard.assert_not_called()

    def test_rejects_when_status_not_revealed(self):
        from core.enums import StealthOrderStatus
        from core.stealth_order_manager import StealthOrderManager

        mgr = StealthOrderManager.__new__(StealthOrderManager)
        mgr.log_callback = lambda *a, **k: None
        with patch.object(
            mgr,
            "_get_stealth_order",
            return_value={
                "stealth_order_id": "sid_1",
                "status": StealthOrderStatus.HIDDEN.value,
                "executed_size": 0.0,
                "remaining_size": 1.0,
                "side": "BUY",
                "product_id": "BIP-20DEC30-CDE",
                "limit_price": 100.0,
            },
        ):
            with pytest.raises(Exception) as exc_info:
                mgr.build_stealth_move_plan(
                    stealth_order_id="sid_1",
                    new_limit_price=101.0,
                )
        assert "REVEALED" in str(exc_info.value) or \
               "status" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 5) spot move/reprice replacement guards use net wallet deltas
# ---------------------------------------------------------------------------


class TestSpotReplaceAwareActionGuard:
    def test_spot_move_plan_blocks_unfunded_replacement_delta(self, monkeypatch):
        from core.enums import ProductCapability
        from core.exceptions import StealthMoveError
        from core.stealth_order_manager import StealthOrderManager

        _enable_spot_capability(monkeypatch, ProductCapability.MOVE_REVEALED)

        mgr = StealthOrderManager(db_client=None, log_callback=MagicMock())
        mgr._rest_credentials_configured = MagicMock(return_value=True)
        mgr._get_account_wallets_for_action_guard = MagicMock(
            return_value={"USD": {"available_balance": {"value": "5.0"}}}
        )
        order = _revealed_spot_order(remaining_size=0.1, limit_price=100.0)
        mgr.in_memory_orders[order["stealth_order_id"]] = order

        with pytest.raises(StealthMoveError) as exc_info:
            mgr.build_stealth_move_plan(
                stealth_order_id=order["stealth_order_id"],
                new_limit_price=200.0,
            )

        assert exc_info.value.stage == "validate"
        assert "net replacement requirement" in str(exc_info.value)
        mgr._get_account_wallets_for_action_guard.assert_called_once()

    def test_spot_move_execute_rechecks_delta_before_cancel(self):
        from core.enums import StealthMutationKind, StealthOrderStatus
        from core.exceptions import StealthMoveError
        from core.models import StealthMovePlan
        from core.orderbook import ClaimLedger
        from core.stealth_order_manager import StealthOrderManager

        mgr = StealthOrderManager.__new__(StealthOrderManager)
        mgr._mutation_claims = ClaimLedger(StealthMutationKind)
        mgr._placed_order_index = {}
        mgr.in_memory_orders = {}
        mgr.log_callback = MagicMock()
        mgr._rest_credentials_configured = MagicMock(return_value=True)
        mgr._get_account_wallets_for_action_guard = MagicMock(
            return_value={"USD": {"available_balance": {"value": "5.0"}}}
        )

        order = _revealed_spot_order(remaining_size=0.1, limit_price=100.0)
        mgr.in_memory_orders[order["stealth_order_id"]] = order

        plan = MagicMock(spec=StealthMovePlan)
        plan.stealth_order_id = order["stealth_order_id"]
        plan.old_exchange_order_id = "old_spot_exchange"
        plan.old_submitted_price = 100.0
        plan.new_configured_limit_price = 200.0
        plan.reveal_plan = MagicMock(submitted_limit_price=200.0)
        plan.root_parent_client_order_id = "root_spot_parent"
        plan.reason = MagicMock(value="manual_user_move")
        plan.notes = None

        with patch.object(mgr, "_get_stealth_order", return_value=order), \
             patch("configuration.REST_CLIENT") as rest_mock:
            with pytest.raises(StealthMoveError) as exc_info:
                mgr.execute_stealth_move(plan)

        assert exc_info.value.stage == "validate"
        rest_mock.cancel_orders.assert_not_called()
        rest_mock.place_limit_order.assert_not_called()
        assert order["status"] == StealthOrderStatus.REVEALED.value

    def test_spot_revealed_anchor_reprice_blocks_delta_before_cancel(self):
        from core.stealth_order_manager import StealthOrderManager

        mgr = StealthOrderManager(db_client=None, log_callback=MagicMock())
        mgr._rest_credentials_configured = MagicMock(return_value=True)
        mgr._get_account_wallets_for_action_guard = MagicMock(
            return_value={"USD": {"available_balance": {"value": "5.0"}}}
        )
        mgr._update_stealth_order = MagicMock()
        order = _revealed_spot_order(remaining_size=0.1, limit_price=100.0)
        state = dict(order["anchor_repricing_state_json"])

        with patch("configuration.REST_CLIENT") as rest_mock:
            applied = mgr._apply_revealed_anchor_reprice(
                order,
                {
                    "enabled": True,
                    "allow_revealed_reprice": True,
                    "post_only_required": False,
                },
                state,
                {"source": "ticker", "bid": 99.0, "ask": 101.0, "price": 100.0},
                desired_price=200.0,
                target_price=200.0,
                max_boundary_price=200.0,
                reprice_reason="reference_price_updated",
            )

        assert applied is False
        rest_mock.cancel_orders.assert_not_called()
        rest_mock.place_limit_order.assert_not_called()
        mgr._update_stealth_order.assert_not_called()


# ---------------------------------------------------------------------------
# 6) execute_stealth_move resets state and preserves flat hierarchy
# ---------------------------------------------------------------------------


class TestExecuteStealthMoveResetsState:
    """After a successful move, the per-order repricing state and
    ``revealed_orders[]`` history must be reset using the canonical
    ``_normalize_anchor_repricing_state(None)`` path. Flat hierarchy
    is preserved via ``resolve_stealth_chain_root``."""

    def test_successful_move_resets_repricing_state_and_history(self):
        from core.enums import StealthMutationKind, StealthOrderStatus
        from core.models import StealthMovePlan
        from core.orderbook import ClaimLedger
        from core.stealth_order_manager import StealthOrderManager

        mgr = StealthOrderManager.__new__(StealthOrderManager)
        mgr._mutation_claims = ClaimLedger(StealthMutationKind)
        mgr._placed_order_index = {}
        mgr.log_callback = lambda *a, **k: None

        order = {
            "stealth_order_id": "sid_1",
            "parent_order_id": "root_parent_coid",
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "status": StealthOrderStatus.REVEALED.value,
            "executed_size": 0.0,
            "remaining_size": 1.0,
            "limit_price": 100.0,
            "anchor_repricing_state_json": {
                "active_placement_client_order_id": "old_placement",
                "active_exchange_order_id": "old_exchange",
                "active_exchange_price": 100.0,
                "reprice_history": [{"at": "x", "price": 99.5}],
            },
            "anchor_repricing_policy_json": {"enabled": True},
            "revealed_orders": [{"reveal_number": 1, "placed_order_id": "old_placement"}],
        }

        # Minimal plan stub — fields the executor must read.
        plan = MagicMock(spec=StealthMovePlan)
        plan.stealth_order_id = "sid_1"
        plan.old_exchange_order_id = "old_exchange"
        plan.old_submitted_price = 100.0
        plan.new_configured_limit_price = 101.0
        plan.reset_repricing_state = True
        plan.reset_reveal_counters = True
        plan.reveal_plan = MagicMock(
            submitted_limit_price=101.0,
            fallback_used=False,
            market_source=None,
        )
        plan.root_parent_client_order_id = "root_parent_coid"
        plan.reason = MagicMock(value="manual_user_move")
        plan.notes = None
        plan.new_target_movement = None
        plan.new_target_movement_type = None
        plan.market_bid = None
        plan.market_ask = None

        with patch.object(mgr, "_get_stealth_order", return_value=order), \
             patch.object(mgr, "_update_stealth_order") as update_mock, \
             patch.object(mgr, "_record_reveal_event"), \
             patch("configuration.REST_CLIENT") as rest_mock, \
             patch("core.stealth_order_manager.insert_order_parent"), \
             patch("core.stealth_order_manager.resolve_stealth_chain_root",
                   return_value="root_parent_coid"):
            rest_mock.cancel_orders.return_value = [{"success": True}]
            rest_mock.place_limit_order.return_value = {
                "success_response": {"order_id": "new_exchange"}
            }

            mgr.execute_stealth_move(plan)

        # The order dict passed to _update_stealth_order must show a reset.
        assert update_mock.called, "execute_stealth_move must persist via _update_stealth_order"
        updated = update_mock.call_args[0][0]
        repricing_state = updated.get("anchor_repricing_state_json", {})
        assert repricing_state.get("active_exchange_order_id") in (None, "new_exchange"), (
            "anchor_repricing_state_json was not reset/rebuilt; the move "
            "must call _normalize_anchor_repricing_state(None) before "
            "writing the new placement."
        )
        assert repricing_state.get("reprice_history", []) == [] or \
               repricing_state.get("reprice_history") is None, (
            "reprice_history must be cleared on move."
        )
        assert updated.get("limit_price") == 101.0, (
            "limit_price must reflect the new configured price."
        )

    def test_executor_releases_mutation_claim_on_success(self):
        from core.enums import StealthMutationKind
        from core.models import StealthMovePlan
        from core.orderbook import ClaimLedger
        from core.stealth_order_manager import StealthOrderManager

        mgr = StealthOrderManager.__new__(StealthOrderManager)
        mgr._mutation_claims = ClaimLedger(StealthMutationKind)
        mgr._placed_order_index = {}
        mgr.log_callback = lambda *a, **k: None

        order = {
            "stealth_order_id": "sid_1",
            "parent_order_id": "root_parent_coid",
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "status": "REVEALED",
            "executed_size": 0.0,
            "remaining_size": 1.0,
            "limit_price": 100.0,
            "anchor_repricing_state_json": {"active_exchange_order_id": "old_exchange"},
            "revealed_orders": [],
        }
        plan = MagicMock(spec=StealthMovePlan)
        plan.stealth_order_id = "sid_1"
        plan.old_exchange_order_id = "old_exchange"
        plan.old_submitted_price = 100.0
        plan.new_configured_limit_price = 101.0
        plan.reveal_plan = MagicMock(submitted_limit_price=101.0, market_source=None)
        plan.root_parent_client_order_id = "root_parent_coid"
        plan.reason = MagicMock(value="manual_user_move")
        plan.notes = None
        plan.reset_repricing_state = True
        plan.reset_reveal_counters = True
        plan.new_target_movement = None
        plan.new_target_movement_type = None
        plan.market_bid = None
        plan.market_ask = None

        with patch.object(mgr, "_get_stealth_order", return_value=order), \
             patch.object(mgr, "_update_stealth_order"), \
             patch.object(mgr, "_record_reveal_event"), \
             patch("configuration.REST_CLIENT") as rest_mock, \
             patch("core.stealth_order_manager.insert_order_parent"), \
             patch("core.stealth_order_manager.resolve_stealth_chain_root",
                   return_value="root_parent_coid"):
            rest_mock.cancel_orders.return_value = [{"success": True}]
            rest_mock.place_limit_order.return_value = {
                "success_response": {"order_id": "new_exchange"}
            }
            result = mgr.execute_stealth_move(plan)

        # Return contract: a StealthMoveResult exposing both the internal
        # placement client_order_id (tracking) and the exchange order_id
        # (operator cross-reference). If this contract changes, every
        # consumer (dashboard handler, future bridge callers) must be
        # audited \u2014 fail loudly here so they are.
        from core.models import StealthMoveResult
        assert isinstance(result, StealthMoveResult), (
            f"execute_stealth_move must return StealthMoveResult, got {type(result)!r}"
        )
        assert result.new_exchange_order_id == "new_exchange", (
            "exchange order id from the place response must propagate "
            "into the result (used by the WS payload for inline display)."
        )
        assert result.new_placement_client_order_id, (
            "internal placement_client_order_id must be present in the result."
        )
        assert result.new_submitted_price == 101.0

        # After successful move, the slot must be free for the next move.
        assert mgr.try_claim_mutation(StealthMutationKind.MOVE, "sid_1") is True, (
            "execute_stealth_move must release the MOVE claim on success "
            "(mutations are repeatable)."
        )


# ---------------------------------------------------------------------------
# 7) Static-source guard — REST_CLIENT.cancel_orders allowlist
# ---------------------------------------------------------------------------
#
# The duplicated-rule pattern (see /memories/duplicated-rule-pattern.md)
# bites when "cancel a revealed stealth order" sequences spread across
# the codebase. Pin the contract: the only sanctioned call sites for
# REST_CLIENT.cancel_orders inside core/stealth_order_manager.py are the
# repricing executor and the move executor. New call sites force an
# explicit allowlist update which surfaces in code review.

_SANCTIONED_CANCEL_CALLERS = (
    "_apply_revealed_anchor_reprice",
    "execute_stealth_move",
    # User-/dashboard-initiated cancel of a stealth order whose live
    # exchange placement must also be pulled. Best-effort, no
    # cancel-and-replace, no claim ledger interaction. Single source for
    # both single-order Cancel and bulk Clear All in dashboard_server.
    "_best_effort_cancel_active_exchange_order",
    # Ticker-driven cancel/re-entry policy intentionally cancels a revealed
    # unfilled exchange placement, then waits for hysteresis before re-entry.
    "_apply_cancel_reentry_cancel",
)


def test_no_inline_cancel_orders_outside_sanctioned_methods():
    """Catch new ``REST_CLIENT.cancel_orders(...)`` regressions in the
    stealth manager. Every such call must occur inside one of the
    sanctioned method bodies."""
    import ast

    repo_root = Path(__file__).resolve().parents[2]
    target = repo_root / "core" / "stealth_order_manager.py"
    src = target.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Map each line number to the enclosing function name.
    line_to_func: dict[int, str] = {}

    def _walk(node, current_func=None):
        new_func = current_func
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            new_func = node.name
        if hasattr(node, "lineno") and new_func is not None:
            line_to_func.setdefault(node.lineno, new_func)
        for child in ast.iter_child_nodes(node):
            _walk(child, new_func)

    _walk(tree)

    pattern = re.compile(r"REST_CLIENT\s*\.\s*cancel_orders\s*\(")
    offenders = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        if not pattern.search(line):
            continue
        func = line_to_func.get(lineno)
        # Walk backwards to find the nearest known function for the call.
        if func is None:
            for back in range(lineno, 0, -1):
                if back in line_to_func:
                    func = line_to_func[back]
                    break
        if func not in _SANCTIONED_CANCEL_CALLERS:
            offenders.append(
                f"core/stealth_order_manager.py:{lineno} "
                f"REST_CLIENT.cancel_orders called from {func!r} "
                f"(not in sanctioned set: {_SANCTIONED_CANCEL_CALLERS})"
            )

    assert not offenders, (
        "Unsanctioned REST_CLIENT.cancel_orders call in stealth manager. "
        "Route the cancel through _apply_revealed_anchor_reprice or "
        "execute_stealth_move, OR explicitly add the new caller to "
        "_SANCTIONED_CANCEL_CALLERS in this test after design review.\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 8) stealth_order_moves audit table
# ---------------------------------------------------------------------------


class TestStealthOrderMovesAuditTable:
    """The audit row is the on-disk record that operators read when a
    move silently failed (cancel-then-place-failed leaves the stealth
    order CANCELLED). The schema must contain the columns the executor
    writes, and ``execute_stealth_move`` must call the insert helper on
    every terminal path: success, post-cancel place failure, and
    cancel failure."""

    @pytest.mark.regression
    def test_schema_has_required_columns(self):
        """Mirror the schema-source-of-truth check used by
        ``test_reconciler_schema.py``: parse ``database/order.py`` and
        confirm the columns ``insert_stealth_order_move`` writes are
        actually defined."""
        import re as _re

        repo_root = Path(__file__).resolve().parents[2]
        src = (repo_root / "database" / "order.py").read_text(encoding="utf-8")
        # Locate the CREATE TABLE block.
        match = _re.search(
            r"CREATE TABLE IF NOT EXISTS stealth_order_moves\s*\((?P<body>.*?)\);",
            src,
            _re.DOTALL,
        )
        assert match, (
            "stealth_order_moves CREATE TABLE not found in database/order.py. "
            "If you renamed the table, update this test."
        )
        body = match.group("body")
        required = {
            "stealth_order_id",
            "old_placement_client_order_id",
            "old_exchange_order_id",
            "old_submitted_price",
            "new_placement_client_order_id",
            "new_exchange_order_id",
            "new_submitted_price",
            "reason",
            "notes",
            "status",
            "error_message",
            "market_bid",
            "market_ask",
            "moved_at",
        }
        missing = {col for col in required if col not in body}
        assert not missing, (
            f"stealth_order_moves schema missing required columns: {sorted(missing)}. "
            f"insert_stealth_order_move writes these so they MUST exist."
        )

    @pytest.mark.regression
    def test_table_creation_is_wired_into_recreation_script(self):
        """The danger-script must (re)create stealth_order_moves so a
        fresh dev DB has the table without manual migration."""
        repo_root = Path(__file__).resolve().parents[2]
        script_path = repo_root / "tools" / "diagnostics" / "__dangerous_delete_all_tables__.py"
        src = script_path.read_text(encoding="utf-8")
        assert "create_stealth_order_moves_table" in src, (
            "create_stealth_order_moves_table is not invoked by "
            "tools/diagnostics/__dangerous_delete_all_tables__.py; "
            "new dev DBs will be "
            "missing the audit table."
        )

    def _build_executor_fixture(self):
        """Shared scaffold for the two execute_stealth_move audit tests."""
        from core.enums import StealthMutationKind, StealthOrderStatus
        from core.models import StealthMovePlan
        from core.orderbook import ClaimLedger
        from core.stealth_order_manager import StealthOrderManager

        mgr = StealthOrderManager.__new__(StealthOrderManager)
        mgr._mutation_claims = ClaimLedger(StealthMutationKind)
        mgr._placed_order_index = {}
        mgr.log_callback = lambda *a, **k: None

        order = {
            "stealth_order_id": "sid_audit",
            "parent_order_id": "root_parent_coid",
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "status": StealthOrderStatus.REVEALED.value,
            "executed_size": 0.0,
            "remaining_size": 1.0,
            "limit_price": 100.0,
            "anchor_repricing_state_json": {
                "active_placement_client_order_id": "old_placement",
                "active_exchange_order_id": "old_exchange",
                "active_exchange_price": 100.0,
            },
            "anchor_repricing_policy_json": {"enabled": True},
            "revealed_orders": [],
        }

        plan = MagicMock(spec=StealthMovePlan)
        plan.stealth_order_id = "sid_audit"
        plan.old_exchange_order_id = "old_exchange"
        plan.old_submitted_price = 100.0
        plan.new_configured_limit_price = 101.0
        plan.reveal_plan = MagicMock(submitted_limit_price=101.0, market_source=None)
        plan.root_parent_client_order_id = "root_parent_coid"
        plan.reason = MagicMock(value="manual_user_move")
        plan.notes = "audit-test"
        plan.reset_repricing_state = True
        plan.reset_reveal_counters = True
        plan.new_target_movement = None
        plan.new_target_movement_type = None
        plan.market_bid = 99.5
        plan.market_ask = 100.5
        return mgr, order, plan

    def test_audit_row_inserted_on_successful_move(self):
        mgr, order, plan = self._build_executor_fixture()
        with patch.object(mgr, "_get_stealth_order", return_value=order), \
             patch.object(mgr, "_update_stealth_order"), \
             patch.object(mgr, "_record_reveal_event"), \
             patch("configuration.REST_CLIENT") as rest_mock, \
             patch("core.stealth_order_manager.insert_order_parent"), \
             patch("core.stealth_order_manager.resolve_stealth_chain_root",
                   return_value="root_parent_coid"), \
             patch("database.order.insert_stealth_order_move") as audit_mock:
            rest_mock.cancel_orders.return_value = [{"success": True}]
            rest_mock.place_limit_order.return_value = {
                "success_response": {"order_id": "new_exchange"}
            }
            mgr.execute_stealth_move(plan)

        assert audit_mock.called, "execute_stealth_move must insert an audit row on success"
        kwargs = audit_mock.call_args.kwargs
        assert kwargs["stealth_order_id"] == "sid_audit"
        assert kwargs["status"] == "completed"
        assert kwargs["old_exchange_order_id"] == "old_exchange"
        assert kwargs["new_exchange_order_id"] == "new_exchange"
        assert kwargs["old_submitted_price"] == 100.0
        assert kwargs["new_submitted_price"] == 101.0
        assert kwargs["reason"] == "manual_user_move"
        assert kwargs["notes"] == "audit-test"

    def test_audit_row_inserted_when_place_fails_after_cancel(self):
        from core.exceptions import StealthMoveError

        mgr, order, plan = self._build_executor_fixture()
        with patch.object(mgr, "_get_stealth_order", return_value=order), \
             patch.object(mgr, "_update_stealth_order"), \
             patch("configuration.REST_CLIENT") as rest_mock, \
             patch("core.stealth_order_manager.insert_order_parent"), \
             patch("core.stealth_order_manager.resolve_stealth_chain_root",
                   return_value="root_parent_coid"), \
             patch("database.order.insert_stealth_order_move") as audit_mock:
            rest_mock.cancel_orders.return_value = [{"success": True}]
            rest_mock.place_limit_order.side_effect = RuntimeError("simulated REST failure")

            with pytest.raises(StealthMoveError) as exc_info:
                mgr.execute_stealth_move(plan)
        assert exc_info.value.stage == "place"

        assert audit_mock.called, (
            "execute_stealth_move must insert an audit row when the place "
            "call fails AFTER the cancel succeeded — this row is the only "
            "on-disk forensic trail of the off-book exchange placement."
        )
        kwargs = audit_mock.call_args.kwargs
        assert kwargs["status"] == "place_failed_after_cancel"
        assert "simulated REST failure" in (kwargs.get("error_message") or "")

    def test_audit_row_inserted_when_cancel_fails(self):
        from core.enums import StealthOrderStatus
        from core.exceptions import StealthMoveError

        mgr, order, plan = self._build_executor_fixture()
        with patch.object(mgr, "_get_stealth_order", return_value=order), \
             patch.object(mgr, "_update_stealth_order") as update_mock, \
             patch("configuration.REST_CLIENT") as rest_mock, \
             patch("database.order.insert_stealth_order_move") as audit_mock:
            rest_mock.cancel_orders.side_effect = RuntimeError("cancel boom")
            with pytest.raises(StealthMoveError) as exc_info:
                mgr.execute_stealth_move(plan)
        assert exc_info.value.stage == "cancel"
        assert order["status"] == StealthOrderStatus.REVEALED.value
        update_mock.assert_not_called()

        assert audit_mock.called, (
            "execute_stealth_move must insert an audit row when the cancel "
            "call itself fails (no exchange state changed, but the operator "
            "needs to see the attempt)."
        )
        kwargs = audit_mock.call_args.kwargs
        assert kwargs["status"] == "cancel_failed"
        assert "cancel boom" in (kwargs.get("error_message") or "")
