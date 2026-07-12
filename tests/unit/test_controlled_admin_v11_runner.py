"""Focused sealed-lineage, recovery, and pricing tests for v11 evidence."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import inspect

import pytest

from tools import run_controlled_admin_spot_root_child_batch as runner


def test_burned_v10_lineage_is_exactly_sealed() -> None:
    binding = runner.load_v10_binding()

    assert binding == runner.offline_v10_binding_fixture()
    assert binding["plan_sha256"] == (
        "115b238c7dbbee51b8250a375bd1079872ab014b82e8abbae27e4caf8ea1d588"
    )
    assert binding["attempt_count"] == 3
    assert binding["root_sdk_call_count"] == 1
    assert binding["child_sdk_call_count"] == 1
    assert binding["slot_2_child_status"] == "CANCELLED"
    assert binding["slot_3_root_status"] == "FILLED"
    assert binding["slot_3_child_sdk_call_occurred"] is False
    assert binding["transmitted_attempt_count"] == 2
    assert binding["terminal_transmitted_attempt_count"] == 2
    assert binding["operator_reconciliation_required"] is False
    assert binding["runtime_shutdown_proven"] is True
    assert binding["all_v10_authority_burned"] is True
    assert binding["all_v10_attempt_authority_burned"] is True
    assert binding["burned_child_attempt_authority_client_order_ids"] == (
        [
            runner.V8_SLOT_2_CHILD_CLIENT_ORDER_ID,
            *runner.FAILED_SUCCESSOR_V10_PLANNED_CHILD_CLIENT_ORDER_IDS,
        ]
    )
    assert binding["recoverable_zero_sdk_child_client_order_id"] == (
        runner.V10_SLOT_3_CHILD_CLIENT_ORDER_ID
    )
    assert binding["recoverable_zero_sdk_child_requires_fresh_absence"] is True


@pytest.mark.parametrize(
    ("constant_name", "blocker"),
    [
        (
            "V10_SLOT_3_ROOT_PLANNED_NOTIONAL",
            "failed_v10_slot_3_root_planned_notional_mismatch",
        ),
        (
            "V10_COMPLETED_REFERENCE_NOTIONAL",
            "failed_v10_completed_reference_notional_mismatch",
        ),
    ],
)
def test_v10_artifact_validator_rejects_cap_seed_constant_drift(
    monkeypatch: pytest.MonkeyPatch,
    constant_name: str,
    blocker: str,
) -> None:
    monkeypatch.setattr(runner, constant_name, Decimal("0"))

    with pytest.raises(runner.ProofFailure, match=blocker):
        runner.load_v10_binding()


def test_completed_slot_2_child_is_freshly_proven_cancelled_zero_fill() -> None:
    order = {
        "order_id": runner.V10_SLOT_2_CHILD_EXCHANGE_ORDER_ID,
        "client_order_id": runner.V8_SLOT_2_CHILD_CLIENT_ORDER_ID,
        "product_id": runner.PRODUCT_ID,
        "product_type": "SPOT",
        "retail_portfolio_id": runner.TEST_PORTFOLIO_ID,
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "status": "CANCELLED",
        "filled_size": "0",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": "0",
        "post_only": False,
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": str(runner.V8_SLOT_2_ROOT_FILLED_SIZE),
                "currency_size": None,
                "limit_price": str(runner.V10_SLOT_2_CHILD_LIMIT_PRICE),
                "post_only": False,
                "reduce_only": False,
                "rfq_disabled": False,
            }
        },
    }

    class RestClient:
        def get_order(self, order_id: str) -> dict[str, object]:
            assert order_id == runner.V10_SLOT_2_CHILD_EXCHANGE_ORDER_ID
            return {"order": order}

    proof = runner.prove_completed_slot_2_exchange_terminal(RestClient())

    assert proof["slot"] == 2
    assert proof["status"] == "CANCELLED"
    assert proof["filled_size"] == "0"
    assert proof["fresh_exact_rest_read"] is True


def test_v11_child_absence_read_uses_bounded_timeout_and_restores_it() -> None:
    class RestClient:
        timeout = runner.COINBASE_SDK_TIMEOUT_SECONDS

        def list_orders(self, **kwargs: object) -> dict[str, object]:
            assert self.timeout == runner.COINBASE_CATALOG_TIMEOUT_SECONDS
            assert kwargs == {"limit": 100}
            return {"orders": [], "has_next": False}

    rest_client = RestClient()

    proof = runner.read_v11_recovery_child_account_wide_absence(rest_client)

    assert proof["authoritative"] is True
    assert proof["pagination_complete"] is True
    assert proof["confirmed_absent"] is True
    assert proof["exact_identity_match"] is False
    assert proof["matched_order"] is None
    assert proof["client_order_id"] == runner.V10_SLOT_3_CHILD_CLIENT_ORDER_ID
    assert rest_client.timeout == runner.COINBASE_SDK_TIMEOUT_SECONDS


def test_v11_reuses_only_the_exact_reconciled_v10_root_3_fill() -> None:
    row = {
        "client_order_id": runner.V10_SLOT_3_ROOT_CLIENT_ORDER_ID,
        "derived_trade_key": runner.V10_SLOT_3_ROOT_DERIVED_TRADE_KEY,
        "reconciliation_status": "RECONCILED",
        "exchange_trade_id": runner.V10_SLOT_3_ROOT_EXCHANGE_TRADE_ID,
        "exchange_entry_id": runner.V10_SLOT_3_ROOT_EXCHANGE_ENTRY_ID,
        "reconciled_at": "2026-07-12T07:54:52+00:00",
    }

    assert runner._classify_fill_ledger_reconciliation_mode(
        [row],
        client_order_id=runner.V10_SLOT_3_ROOT_CLIENT_ORDER_ID,
        exchange_order_id=runner.V10_SLOT_3_ROOT_EXCHANGE_ORDER_ID,
        portfolio_id=runner.TEST_PORTFOLIO_ID,
        expected_filled_size=runner.V10_SLOT_3_ROOT_FILLED_SIZE,
        expected_filled_value=runner.V10_SLOT_3_ROOT_FILLED_VALUE,
        expected_total_fees=runner.V10_SLOT_3_ROOT_TOTAL_FEES,
        expected_identity_pairs={
            runner.V10_SLOT_3_ROOT_DERIVED_TRADE_KEY: (
                runner.V10_SLOT_3_ROOT_EXCHANGE_TRADE_ID,
                runner.V10_SLOT_3_ROOT_EXCHANGE_ENTRY_ID,
            )
        },
    ) == "exact_v10_slot_3_root_already_reconciled"


def test_v11_child_attempt_is_prepared_and_ledgered_while_live_disabled() -> None:
    source = inspect.getsource(runner.execute_controlled_batch)
    disabled = source.index(
        'f"slot_{slot}_child_preparation_not_live_disabled"'
    )
    guard = source.index('slot_result["child_pre_enable_fresh_bid_guard"]')
    ledger = source.index("child_attempt = consume_batch_attempt")
    enabled = source.index("set_live_service(runtime, enabled=True)", ledger)
    preview = source.index(
        "preview_admission(runtime, child_reveal_context)",
        enabled,
    )
    submitted = source.index("child_reveal_http_attempted = True", preview)

    assert disabled < guard < ledger < enabled < preview < submitted


def test_v11_root_attempts_start_disabled_and_enable_only_after_ledger() -> None:
    source = inspect.getsource(runner.execute_controlled_batch)
    loop = source.index("for root_plan in execution_rows:")
    disabled = source.index(
        'f"slot_{slot}_root_preparation_not_live_disabled"',
        loop,
    )
    proofs = source.index("place_proofs = write_proof_chain", disabled)
    ledger = source.index("root_attempt = consume_batch_attempt", proofs)
    enabled = source.index("set_live_service(runtime, enabled=True)", ledger)
    preview = source.index(
        "root_place_preview = preview_admission",
        enabled,
    )
    submitted = source.index("root_place_http_attempted = True", preview)
    terminal_child = source.index(
        '"stop_child_fill_detected_after_terminal_read"',
        submitted,
    )
    disabled_after_pair = source.index(
        "set_live_service(runtime, enabled=False)",
        terminal_child,
    )
    chain_readback = source.index(
        'slot_result["cancelled_child_chain"]',
        disabled_after_pair,
    )

    assert disabled < proofs < ledger < enabled < preview < submitted
    assert terminal_child < disabled_after_pair < chain_readback


def test_parent_loss_durable_rejected_cancel_requires_direct_reconciliation() -> None:
    result = {
        "http_status": 400,
        "payload": {
            "status": "rejected",
            "message": "Controlled first-child state read failed",
        },
    }

    outcome = runner._classify_parent_loss_cancel_response(result)

    assert outcome == "durable_rejected"
    assert runner._parent_loss_cancel_retry_decision(
        exact_order_active=True,
        stable_active_scope_proven=True,
        prior_cancel_outcome=outcome,
    ) == "require_operator_direct_reconciliation"
    retry_pending, direct_reconciliation_ids = (
        runner._parent_loss_cancel_pending_state(
            exact_active_client_order_ids=["exact-child-id"],
            cancel_outcomes={"exact-child-id": outcome},
        )
    )
    assert retry_pending is False
    assert direct_reconciliation_ids == ["exact-child-id"]
    assert runner._parent_loss_cancel_pending_state(
        exact_active_client_order_ids=[],
        cancel_outcomes={"exact-child-id": outcome},
    ) == (False, ["exact-child-id"])


def test_parent_loss_timeout_retains_only_same_idempotent_cancel_retry() -> None:
    outcome = "timeout_or_exception"

    assert runner._parent_loss_cancel_retry_decision(
        exact_order_active=True,
        stable_active_scope_proven=True,
        prior_cancel_outcome=outcome,
    ) == "issue_same_idempotent_exact_cancel"
    retry_pending, direct_reconciliation_ids = (
        runner._parent_loss_cancel_pending_state(
            exact_active_client_order_ids=["exact-child-id"],
            cancel_outcomes={"exact-child-id": outcome},
        )
    )
    assert retry_pending is True
    assert direct_reconciliation_ids == []


def test_child_tuple_uses_v11_target_170_ratio_and_survives_six_percent_bid_drift() -> None:
    reference_bid = Decimal("63817.30")
    increment = Decimal("0.01")
    plan = {
        "batch_id": "v11-offline-batch",
        "child_target_bid_ratio": "1.70",
        "child_price_increment": "0.01",
    }
    root = {
        "slot": 3,
        "root_client_order_id": "00000000-0000-0000-0000-000000000001",
        "child_client_order_id": "00000000-0000-0000-0000-000000000002",
        "proof_approval_ids": {
            "child_reveal": "00000000-0000-0000-0000-000000000003",
        },
    }

    child = runner.build_child_order_tuple(
        plan,
        root,
        filled_size=Decimal("0.00001720"),
        fresh_market={
            "best_bid": reference_bid,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        price_increment=increment,
    )

    assert runner.CHILD_MINIMUM_BID_RATIO == Decimal("1.60")
    assert runner.CHILD_TARGET_BID_RATIO == Decimal("1.70")
    expected_price = (
        (reference_bid * runner.CHILD_TARGET_BID_RATIO) / increment
    ).to_integral_value(rounding=ROUND_CEILING) * increment
    assert Decimal(child["limit_price"]) == expected_price
    assert Decimal(child["minimum_bid_ratio"]) == Decimal("1.60")
    assert Decimal(child["target_bid_ratio"]) == Decimal("1.70")
    assert Decimal(child["price_increment"]) == increment
    assert expected_price >= reference_bid * Decimal("1.06") * Decimal("1.60")


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("limit_price", "108489.40"),
        ("limit_price", "108489.42"),
        ("target_bid_ratio", "1.69"),
        ("price_increment", "0.10"),
        ("reference_bid", "63817.300"),
        ("minimum_bid_ratio", "1.600"),
        ("target_bid_ratio", "1.700"),
        ("price_increment", "0.010"),
        ("strict_max_notional_usdc", "2.0"),
    ],
)
def test_child_tuple_rejects_every_target_formula_tamper(
    field: str,
    replacement: str,
) -> None:
    plan = {
        "batch_id": "v11-offline-batch",
        "child_target_bid_ratio": "1.70",
        "child_price_increment": "0.01",
    }
    root = {
        "slot": 3,
        "root_client_order_id": "00000000-0000-0000-0000-000000000001",
        "child_client_order_id": "00000000-0000-0000-0000-000000000002",
        "proof_approval_ids": {
            "child_reveal": "00000000-0000-0000-0000-000000000003",
        },
    }
    child = runner.build_child_order_tuple(
        plan,
        root,
        filled_size=Decimal("0.00001720"),
        fresh_market={
            "best_bid": Decimal("63817.30"),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        price_increment=Decimal("0.01"),
    )
    child[field] = replacement

    with pytest.raises(runner.ProofFailure):
        runner._validate_authorized_child_tuple(plan, root, child)


def test_child_tuple_rejects_coordinated_price_increment_and_price_tamper() -> None:
    plan = {
        "batch_id": "v11-offline-batch",
        "child_target_bid_ratio": "1.70",
        "child_price_increment": "0.01",
    }
    root = {
        "slot": 3,
        "root_client_order_id": "00000000-0000-0000-0000-000000000001",
        "child_client_order_id": "00000000-0000-0000-0000-000000000002",
        "proof_approval_ids": {
            "child_reveal": "00000000-0000-0000-0000-000000000003",
        },
    }
    child = runner.build_child_order_tuple(
        plan,
        root,
        filled_size=Decimal("0.00001720"),
        fresh_market={
            "best_bid": Decimal("63817.30"),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        price_increment=Decimal("0.01"),
    )
    child["price_increment"] = "0.10"
    child["limit_price"] = "108489.50"

    with pytest.raises(runner.ProofFailure):
        runner._validate_authorized_child_tuple(plan, root, child)


def test_exact_child_price_fresh_bid_helper_allows_tick_drift_and_denies_large_jump() -> None:
    child = {
        "limit_price": "108489.41",
        "minimum_bid_ratio": "1.60",
    }
    evidence = runner.validate_exact_child_price_against_fresh_bid(
        child,
        {
            "best_bid": Decimal("63817.31"),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        blocker="child_price_below_160_percent_test_bid",
    )
    assert evidence["authorized_price"] == "108489.41"
    assert evidence["fresh_bid"] == "63817.31"
    assert Decimal(evidence["headroom_ratio"]) > Decimal("1")

    with pytest.raises(
        runner.ProofFailure,
        match="child_price_below_160_percent_test_bid",
    ):
        runner.validate_exact_child_price_against_fresh_bid(
            child,
            {
                "best_bid": Decimal("67840.00"),
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
            blocker="child_price_below_160_percent_test_bid",
        )
