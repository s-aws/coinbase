"""Focused recovery and pricing tests for the controlled v11 runner."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import json
import inspect

import pytest

from tools import run_controlled_admin_spot_root_child_batch as runner


def _preflight() -> dict[str, object]:
    return {
        "portfolio_id": runner.TEST_PORTFOLIO_ID,
        "wallets": {"USDC": Decimal("990"), "BTC": Decimal("0.00007084")},
        "product": {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
        },
        "best_bid": Decimal("63817.31"),
        "best_ask": Decimal("63817.32"),
        "market": {
            "product_id": runner.PRODUCT_ID,
            "source": "coinbase_rest_get_best_bid_ask_exact_product",
            "observed_at": "2026-07-12T08:30:00+00:00",
        },
    }


def _bindings() -> dict[str, dict[str, object]]:
    return {
        "predecessor_binding": runner.offline_predecessor_binding_fixture(),
        "failed_successor_binding": (
            runner.offline_failed_successor_binding_fixture()
        ),
        "failed_v2_binding": runner.offline_failed_v2_binding_fixture(),
        "failed_v3_binding": runner.offline_failed_v3_binding_fixture(),
        "failed_v4_binding": runner.offline_failed_v4_binding_fixture(),
        "failed_v5_binding": runner.offline_failed_v5_binding_fixture(),
        "failed_v6_binding": runner.offline_failed_v6_binding_fixture(),
        "failed_v7_binding": runner.offline_failed_v7_binding_fixture(),
        "v8_binding": runner.offline_v8_binding_fixture(),
        "v9_binding": runner.offline_v9_binding_fixture(),
        "v10_binding": runner.offline_v10_binding_fixture(),
    }


def _validated_v11_plan() -> tuple[dict[str, object], list[dict[str, object]]]:
    preflight = _preflight()
    bindings = _bindings()
    plan = runner.build_successor_live_plan(preflight, **bindings)
    roots, _ = runner.validate_successor_live_plan(
        plan,
        expected_hash=str(plan["plan_sha256"]),
        preflight=preflight,
        **bindings,
    )
    return plan, roots


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


def test_v11_authority_is_exactly_child_3_then_pairs_4_through_10() -> None:
    assert runner.PLAN_SCHEMA_VERSION == "15"
    assert runner.SUCCESSOR_ROOT_ORDER_MAXIMUM == 7
    assert runner.SUCCESSOR_CHILD_ORDER_MAXIMUM == 8
    assert runner.SUCCESSOR_ATTEMPT_COUNT == 15
    assert runner.successor_attempt_schedule() == [
        (3, "child"),
        *[
            item
            for slot in range(4, 11)
            for item in ((slot, "root"), (slot, "child"))
        ],
    ]
    assert runner.SUCCESSOR_V11_PLAN_PATH.name.endswith(
        "successor-v11-20260712.plan.json"
    )
    assert runner.GLOBAL_BATCH_MARKER_FILENAME.endswith(
        "successor-v11-20260712.authority.json"
    )
    assert runner.GLOBAL_BATCH_LEDGER_FILENAME.endswith(
        "successor-v11-20260712.attempts.jsonl"
    )


def test_v11_plan_recovers_only_child_3_and_uses_fresh_slots_4_to_10() -> None:
    plan, roots = _validated_v11_plan()

    assert plan["continuation_kind"] == (
        "sealed_v10_root_3_fill_recover_child_then_fresh_slots_4_to_10_v11"
    )
    assert str(plan["approval_id"]).startswith(
        "controlled-root-child-successor-v11-"
    )
    assert plan["remaining_attempt_count"] == 15
    assert plan["new_root_order_maximum"] == 7
    assert plan["child_order_maximum"] == 8
    assert plan["v10_binding"] == runner.offline_v10_binding_fixture()
    assert [root["slot"] for root in roots] == list(range(4, 11))

    recovery = plan["recovery_slot_3"]
    assert recovery["slot"] == 3
    assert recovery["root_placement_authorized"] is False
    assert recovery["child_recovery_authorized"] is True
    assert recovery["root_client_order_id"] == runner.V10_SLOT_3_ROOT_CLIENT_ORDER_ID
    assert recovery["child_client_order_id"] == runner.V10_SLOT_3_CHILD_CLIENT_ORDER_ID
    assert recovery["root_exchange_order_id"] == runner.V10_SLOT_3_ROOT_EXCHANGE_ORDER_ID
    assert recovery["prior_child_attempt_tuple_sha256"] == (
        runner.V10_SLOT_3_CHILD_TUPLE_SHA256
    )
    assert recovery["prior_child_sdk_call_occurred"] is False

    fresh_ids = {
        str(value)
        for root in roots
        for value in (
            root["root_client_order_id"],
            root["child_client_order_id"],
        )
    }
    burned_v10_ids = set(
        runner.FAILED_SUCCESSOR_V10_PLANNED_ROOT_CLIENT_ORDER_IDS
    ) | set(runner.FAILED_SUCCESSOR_V10_PLANNED_CHILD_CLIENT_ORDER_IDS)
    assert not fresh_ids & burned_v10_ids


def test_v11_plan_cap_starts_after_exact_v10_completed_reference() -> None:
    plan, roots = _validated_v11_plan()
    planned_new_root = sum(
        Decimal(str(root["planned_notional_usdc"])) for root in roots
    )
    increment = Decimal(str(plan["child_price_increment"]))
    planned_bid = Decimal(str(plan["best_bid_at_plan"]))
    child_price = (
        (planned_bid * runner.CHILD_TARGET_BID_RATIO) / increment
    ).to_integral_value(rounding=ROUND_CEILING) * increment
    planned_new_child = (
        runner.V10_SLOT_3_ROOT_FILLED_SIZE
        + sum(Decimal(str(root["order"]["base_size"])) for root in roots)
    ) * child_price
    expected_total = (
        runner.V10_COMPLETED_REFERENCE_NOTIONAL
        + planned_new_root
        + planned_new_child
    )

    assert Decimal(str(plan["completed_reference_notional_usdc"])) == (
        runner.V10_COMPLETED_REFERENCE_NOTIONAL
    )
    assert plan["reference_cap_scope"] == (
        "completed_pairs_1_to_2_plus_v10_root_3_plus_"
        "v11_child_3_and_pairs_4_to_10"
    )
    assert Decimal(str(plan["planned_new_root_notional_usdc"])) == planned_new_root
    assert Decimal(
        str(plan["planned_new_child_reference_notional_usdc"])
    ) == planned_new_child
    assert Decimal(
        str(plan["planned_total_root_child_reference_notional_usdc"])
    ) == expected_total
    assert expected_total < Decimal("30.00")
    assert all(
        Decimal(str(root["order"]["base_size"])) * child_price
        < Decimal("2.00")
        for root in roots
    )
    assert runner.V10_SLOT_3_ROOT_FILLED_SIZE * child_price < Decimal("2.00")


@pytest.mark.parametrize(
    ("field", "replacement"),
    [("child_target_bid_ratio", "1.71"), ("child_price_increment", "0.10")],
)
def test_v11_rehashed_plan_rejects_price_policy_tamper(
    field: str,
    replacement: str,
) -> None:
    preflight = _preflight()
    bindings = _bindings()
    plan = runner.build_successor_live_plan(preflight, **bindings)
    plan[field] = replacement
    plan["plan_sha256"] = runner.plan_hash(plan)

    with pytest.raises(runner.ProofFailure, match="successor_plan_cap_policy_mismatch"):
        runner.validate_successor_live_plan(
            plan,
            expected_hash=str(plan["plan_sha256"]),
            preflight=preflight,
            **bindings,
        )


def test_v11_marker_exposes_exact_recovery_price_and_cap_authority() -> None:
    plan, roots = _validated_v11_plan()
    marker = runner.build_global_batch_marker_payload(
        runner.SUCCESSOR_V11_PLAN_PATH,
        confirmed_plan=plan,
        expected_hash=str(plan["plan_sha256"]),
        expected_runner_sha256=runner.runner_sha256(),
        registered_at=datetime.now(timezone.utc).isoformat(),
        process_id=12345,
    )

    assert marker["schema_version"] == "11"
    assert marker["authority"] == (
        "controlled-admin-spot-root-child-successor-v11-batch"
    )
    assert marker["remaining_attempt_count"] == 15
    assert marker["root_order_maximum"] == 7
    assert marker["child_order_maximum"] == 8
    assert marker["reference_cap_scope"] == plan["reference_cap_scope"]
    assert Decimal(str(marker["inherited_reference_notional_usdc"])) == (
        runner.V10_COMPLETED_REFERENCE_NOTIONAL
    )
    assert marker["v10_binding"] == runner.offline_v10_binding_fixture()
    assert marker["recovery_slot_3_policy"] == {
        "batch_slot": 3,
        "root_client_order_id": runner.V10_SLOT_3_ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": runner.V10_SLOT_3_CHILD_CLIENT_ORDER_ID,
        "root_exchange_order_id": runner.V10_SLOT_3_ROOT_EXCHANGE_ORDER_ID,
        "root_placement_authorized": False,
        "child_recovery_authorized": True,
        "prior_child_attempt_tuple_sha256": runner.V10_SLOT_3_CHILD_TUPLE_SHA256,
        "prior_child_sdk_call_occurred": False,
    }
    assert marker["exact_child_client_order_ids"] == [
        runner.V10_SLOT_3_CHILD_CLIENT_ORDER_ID,
        *[str(root["child_client_order_id"]) for root in roots],
    ]
    assert marker["child_policy"]["minimum_fresh_bid_ratio"] == "1.60"
    assert marker["child_policy"]["target_fresh_bid_ratio"] == "1.70"
    assert marker["child_policy"]["price_increment"] == "0.01"


def test_v11_ledger_first_attempt_is_exact_recovery_child_3() -> None:
    plan, _ = _validated_v11_plan()
    rows = runner.successor_plan_rows_by_slot(plan)
    recovery = rows[3]
    child_tuple = runner.build_child_order_tuple(
        plan,
        recovery,
        filled_size=runner.V10_SLOT_3_ROOT_FILLED_SIZE,
        fresh_market={
            "best_bid": Decimal("63817.31"),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        price_increment=Decimal("0.01"),
    )
    record = runner.build_batch_attempt_record(
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        sequence=1,
        slot=3,
        attempt_kind="child",
        exact_order_tuple=child_tuple,
        consumed_at=datetime.now(timezone.utc).isoformat(),
        process_id=12345,
    )
    raw = (json.dumps(record, sort_keys=True) + "\n").encode()

    assert runner._parse_and_validate_attempt_ledger(
        raw,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
    ) == [record]
    assert record["client_order_id"] == runner.V10_SLOT_3_CHILD_CLIENT_ORDER_ID
    assert record["root_client_order_id"] == runner.V10_SLOT_3_ROOT_CLIENT_ORDER_ID
    assert record["exact_order_tuple_sha256"] == runner._canonical_json_sha256(
        child_tuple
    )


def test_v11_ledger_cap_seed_includes_every_v10_completed_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _ = _validated_v11_plan()
    recovery = runner.successor_plan_rows_by_slot(plan)[3]
    child_tuple = runner.build_child_order_tuple(
        plan,
        recovery,
        filled_size=runner.V10_SLOT_3_ROOT_FILLED_SIZE,
        fresh_market={
            "best_bid": Decimal("63817.31"),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        price_increment=Decimal("0.01"),
    )
    record = runner.build_batch_attempt_record(
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        sequence=1,
        slot=3,
        attempt_kind="child",
        exact_order_tuple=child_tuple,
        consumed_at=datetime.now(timezone.utc).isoformat(),
        process_id=12345,
    )
    tuple_notional = Decimal(child_tuple["base_size"]) * Decimal(
        child_tuple["limit_price"]
    )
    monkeypatch.setattr(
        runner,
        "BATCH_TOTAL_REFERENCE_CAP_USDC",
        runner.V10_COMPLETED_REFERENCE_NOTIONAL + tuple_notional,
    )

    with pytest.raises(
        runner.ProofFailure,
        match="global_batch_attempt_cumulative_reference_cap_exceeded",
    ):
        runner._parse_and_validate_attempt_ledger(
            (json.dumps(record, sort_keys=True) + "\n").encode(),
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
        )


def test_v11_runtime_authority_accepts_only_the_new_plan_structure() -> None:
    plan, _ = _validated_v11_plan()

    runner._validate_authority_plan_structure(
        plan,
        expected_plan_hash=str(plan["plan_sha256"]),
    )


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
