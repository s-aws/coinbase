"""Focused sealed-lineage and topology tests for the controlled v13 runner."""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import inspect
import json

import pytest

from tools import run_controlled_admin_spot_root_child_batch as runner


def _preflight() -> dict[str, object]:
    return {
        "portfolio_id": runner.TEST_PORTFOLIO_ID,
        "wallets": {"USDC": Decimal("985"), "BTC": Decimal("0.000105")},
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
            "observed_at": "2026-07-12T12:30:00+00:00",
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
        "v11_binding": runner.offline_v11_binding_fixture(),
        "v12_binding": runner.offline_v12_binding_fixture(),
    }


def _validated_v13_plan() -> tuple[dict[str, object], list[dict[str, object]]]:
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


def test_v12_failure_is_sealed_with_exact_terminal_recovery_boundary() -> None:
    binding = runner.load_v12_binding()

    assert binding == runner.offline_v12_binding_fixture()
    assert binding["runner_commit"] == (
        "c2360035adf5acb65416a36bc8ccc92c805ab391"
    )
    assert binding["production_parent_commit"] == runner.EXPECTED_COMMIT
    assert binding["runner_sha256"] == (
        "1de1d273f8b7c9004a7dfab0f3a7f2376dfe28f99a6369047c48e862f41b0a5e"
    )
    assert binding["plan_sha256"] == (
        "6e49fdb906d0dd6fa43834b858313adae0abfedbcdae23767f454aa791431db8"
    )
    assert binding["attempt_count"] == 1
    assert binding["root_sdk_call_count"] == 1
    assert binding["child_sdk_call_count"] == 0
    assert binding["all_transmitted_attempts_terminal"] is True
    assert binding["active_spot_orders_at_closeout"] == []
    assert binding["root_5_status"] == "FILLED"
    assert binding["child_5_account_wide_absent"] is True
    assert binding["recoverable_zero_sdk_child_client_order_id"] == (
        "1d90986f-f7fc-5a2c-abd3-896b38810aca"
    )
    assert Decimal(binding["completed_reference_notional_usdc"]) == Decimal(
        "12.7373136411"
    )
    assert binding["all_v12_authority_burned"] is True


def test_v12_operator_artifacts_and_every_bound_hash_are_immutable() -> None:
    binding = runner.offline_v12_binding_fixture()

    assert binding["plan_bytes_sha256"] == (
        "b53edcd82f168bc6d630def9832aba880880bf19cb0ff759e26ac4599a33de85"
    )
    assert binding["marker_bytes_sha256"] == (
        "3e16e4165ef9d9100a268b2b70cd36e97646ea83956e80f99550a0f8a6903de6"
    )
    assert binding["ledger_bytes_sha256"] == (
        "eec35a4b8bf468e57c5b807562eddbc020ace53ecfac9ad7a776e596bedd2fd9"
    )
    assert binding["failure_bytes_sha256"] == (
        "39a44552c6536c80e6024c2af39b1b57dc67c0ea31233a394c9e63d039e3cf58"
    )
    assert binding["cleanup_bytes_sha256"] == (
        "0c8aa6231ef9ccf43059244f7472c51c4eb2ac8f1ebf6fad23631cc302e567c4"
    )
    assert binding["parent_loss_bytes_sha256"] == (
        "fa528c7dba928475922d4bd9697409c9415355020ea9ee55aa446b2827a56b5b"
    )
    assert binding["sentinel_bytes_sha256"] == (
        "57952405bf0ede710fad90b8230dce3cccf58864a88049a0b9f08b4ce7a795e9"
    )
    assert binding["operator_exchange_readback_bytes_sha256"] == (
        "7e3007dd044616d09ceef75cffb287e90a5d2f66787860e0b56caa67f8ddbb25"
    )
    assert binding["operator_reconciliation_bytes_sha256"] == (
        "bd4eaac9040ea15777bf959145771a11f95364e4eb4bf122dced4f3d14779894"
    )
    assert set(binding["bound_artifact_bytes_sha256"]) == {
        "approvals_jsonl",
        "attempt_ledger_jsonl",
        "audit_jsonl",
        "cap_guard_jsonl",
        "cleanup_json",
        "failure_json",
        "idempotency_jsonl",
        "live_service_jsonl",
        "marker_json",
        "operator_exchange_readback_json",
        "parent_authority_loss_json",
        "reconciliation_jsonl",
        "runtime_authority_json",
        "runtime_authority_used_json",
        "runtime_log",
        "runtime_pid",
        "sentinel_json",
    }


def test_v13_authority_is_exactly_child_5_then_fresh_pairs_6_through_10() -> None:
    assert runner.V13_RUNNER_AUTHORITY_PARENT_COMMIT == (
        "c2360035adf5acb65416a36bc8ccc92c805ab391"
    )
    assert runner.PLAN_SCHEMA_VERSION == "17"
    assert runner.SUCCESSOR_ROOT_ORDER_MAXIMUM == 5
    assert runner.SUCCESSOR_CHILD_ORDER_MAXIMUM == 6
    assert runner.SUCCESSOR_ATTEMPT_COUNT == 11
    assert runner.successor_attempt_schedule() == [
        (5, "child"),
        *[
            item
            for slot in range(6, 11)
            for item in ((slot, "root"), (slot, "child"))
        ],
    ]
    assert runner.SUCCESSOR_V13_PLAN_PATH.name.endswith(
        "successor-v13-20260712.plan.json"
    )
    assert runner.GLOBAL_BATCH_MARKER_FILENAME.endswith(
        "successor-v13-20260712.authority.json"
    )
    assert runner.GLOBAL_BATCH_LEDGER_FILENAME.endswith(
        "successor-v13-20260712.attempts.jsonl"
    )


def test_v13_active_commit_scope_requires_only_the_six_changed_paths() -> None:
    source = inspect.getsource(runner.require_clean_commit)
    active_topology = source[
        source.index("topology = validate_runner_commit_topology(") :
        source.index("production_drift = subprocess.run(")
    ]

    assert "V11_RUNNER_TEST_PATH" not in active_topology
    assert all(
        path_name in active_topology
        for path_name in (
            "V9_RUNNER_TEST_PATH",
            "V10_RUNNER_TEST_PATH",
            "V12_RUNNER_TEST_PATH",
            "V13_RUNNER_TEST_PATH",
            "OWNERSHIP_MANIFEST_PATH",
        )
    )


def test_v13_plan_recovers_only_exact_zero_sdk_child_5() -> None:
    plan, roots = _validated_v13_plan()
    recovery = dict(plan["recovery_slot_5"])

    assert plan["continuation_kind"] == (
        "sealed_v12_root_5_fill_recover_child_then_fresh_slots_6_to_10_v13"
    )
    assert str(plan["approval_id"]).startswith(
        "controlled-root-child-successor-v13-"
    )
    assert plan["remaining_attempt_count"] == 11
    assert plan["new_root_order_maximum"] == 5
    assert plan["child_order_maximum"] == 6
    assert plan["v12_binding"] == runner.offline_v12_binding_fixture()
    assert [root["slot"] for root in roots] == list(range(6, 11))
    assert all(root["root_placement_authorized"] is True for root in roots)
    assert recovery["slot"] == 5
    assert recovery["root_placement_authorized"] is False
    assert recovery["child_recovery_authorized"] is True
    assert recovery["root_client_order_id"] == runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID
    assert recovery["child_client_order_id"] == runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID
    assert recovery["prior_child_sdk_call_occurred"] is False
    assert set(recovery["proof_approval_ids"]) == {
        "child_reveal",
        "child_cancel",
    }

    fresh_ids = {
        str(value)
        for root in roots
        for value in (
            root["root_client_order_id"],
            root["child_client_order_id"],
        )
    }
    burned_v12 = {
        *runner.FAILED_SUCCESSOR_V12_PLANNED_ROOT_CLIENT_ORDER_IDS,
        *runner.FAILED_SUCCESSOR_V12_PLANNED_CHILD_CLIENT_ORDER_IDS,
    }
    assert not fresh_ids & burned_v12
    assert recovery["child_client_order_id"] in burned_v12
    assert recovery["root_client_order_id"] in burned_v12


def test_v13_plan_cap_starts_at_exact_v12_completed_seed() -> None:
    plan, roots = _validated_v13_plan()
    recovery = dict(plan["recovery_slot_5"])
    planned_new_root = sum(
        Decimal(str(root["planned_notional_usdc"])) for root in roots
    )
    increment = Decimal(str(plan["child_price_increment"]))
    planned_bid = Decimal(str(plan["best_bid_at_plan"]))
    child_price = (
        (planned_bid * runner.CHILD_TARGET_BID_RATIO) / increment
    ).to_integral_value(rounding=ROUND_CEILING) * increment
    planned_new_child = Decimal(str(recovery["root_filled_size"])) * child_price
    planned_new_child += sum(
        Decimal(str(root["order"]["base_size"])) * child_price
        for root in roots
    )
    expected_total = (
        runner.V12_COMPLETED_REFERENCE_NOTIONAL
        + planned_new_root
        + planned_new_child
    )

    assert Decimal(str(plan["completed_reference_notional_usdc"])) == Decimal(
        "12.7373136411"
    )
    assert Decimal(str(plan["completed_root_reference_notional_usdc"])) == Decimal(
        "5.5016568219"
    )
    assert Decimal(str(plan["completed_child_reference_notional_usdc"])) == Decimal(
        "7.2356568192"
    )
    assert plan["reference_cap_scope"] == (
        "completed_roots_1_to_5_children_1_to_4_plus_v13_child_5_and_pairs_6_to_10"
    )
    assert Decimal(str(plan["planned_new_root_notional_usdc"])) == planned_new_root
    assert Decimal(str(plan["planned_new_child_reference_notional_usdc"])) == planned_new_child
    assert Decimal(str(plan["planned_total_root_child_reference_notional_usdc"])) == expected_total
    assert expected_total < Decimal("30.00")
    assert Decimal(str(recovery["root_filled_size"])) * child_price < Decimal("2.00")
    assert all(
        Decimal(str(root["order"]["base_size"])) * child_price < Decimal("2.00")
        for root in roots
    )


def test_v13_marker_and_ledger_start_with_recovery_child_5() -> None:
    plan, _ = _validated_v13_plan()
    recovery = dict(plan["recovery_slot_5"])
    marker = runner.build_global_batch_marker_payload(
        runner.SUCCESSOR_V13_PLAN_PATH,
        confirmed_plan=plan,
        expected_hash=str(plan["plan_sha256"]),
        expected_runner_sha256=runner.runner_sha256(),
        registered_at=datetime.now(timezone.utc).isoformat(),
        process_id=12345,
    )

    assert marker["schema_version"] == "13"
    assert marker["authority"] == (
        "controlled-admin-spot-root-child-successor-v13-batch"
    )
    assert marker["remaining_attempt_count"] == 11
    assert marker["root_order_maximum"] == 5
    assert marker["child_order_maximum"] == 6
    assert marker["recovery_slot_5_policy"]["root_placement_authorized"] is False
    assert marker["exact_child_client_order_ids"][0] == (
        runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID
    )

    child_tuple = runner.build_child_order_tuple(
        plan,
        recovery,
        filled_size=Decimal(str(recovery["root_filled_size"])),
        fresh_market={
            "best_bid": _preflight()["best_bid"],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        price_increment=Decimal(str(plan["child_price_increment"])),
    )
    record = runner.build_batch_attempt_record(
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        sequence=1,
        slot=5,
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
    assert record["batch_slot"] == 5
    assert record["attempt_kind"] == "child"
    assert record["client_order_id"] == runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID


def test_v13_recovery_scope_is_reproved_at_all_four_authority_boundaries() -> None:
    main_source = inspect.getsource(runner.main)
    execute_source = inspect.getsource(runner.execute_controlled_batch)

    assert main_source.count("prove_v12_slot_5_recovery_preconditions(") >= 2
    registration = main_source.index("initialize_global_batch_ledger")
    assert main_source.index("prove_v12_slot_5_recovery_preconditions(") < registration
    runtime_start = execute_source.index("v12_recovery_at_runtime_start")
    first_enable = execute_source.index("set_live_service(runtime, enabled=True)")
    assert runtime_start < first_enable
    assert "v12_recovery_before_first_live_enable" in execute_source
    assert execute_source.count("recovery_slot_5=recovery_slot_5") >= 8


@pytest.mark.parametrize(
    "helper_name",
    [
        "prove_failed_v5_root_2_absence",
        "prove_failed_v6_v7_client_ids_absent",
        "prove_failed_v9_fresh_client_ids_absent",
        "prove_failed_v10_unattempted_client_ids_absent",
        "prove_failed_v11_unused_client_ids_absent",
        "prove_failed_v12_unused_client_ids_absent",
    ],
)
def test_v13_recovery_scope_reaches_every_local_absence_gate(
    helper_name: str,
) -> None:
    helper = getattr(runner, helper_name)
    assert "recovery_slot_5" in inspect.signature(helper).parameters
    assert (
        "recovery_slot_5=recovery_slot_5"
        in inspect.getsource(helper)
    )


def test_v13_execution_has_no_recovery_root_call_and_exact_sdk_maxima() -> None:
    source = inspect.getsource(runner.execute_controlled_batch)

    assert "execution_rows = [recovery_slot_5, *roots]" in source
    assert "if slot >= 6:" in source
    assert "slot_5_recovery_preconditions" in source
    assert "root_calls_before = max(0, slot - 6)" in source
    assert "child_calls_before = slot - 5" in source
    assert "expected_root_create_order_calls={SUCCESSOR_ROOT_ORDER_MAXIMUM}" in source
    assert "expected_child_place_limit_order_calls={SUCCESSOR_CHILD_ORDER_MAXIMUM}" in source


def _child_preparation_fixture(
    plan: dict[str, object],
    root_plan: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    slot = int(root_plan["slot"])
    filled_size = (
        Decimal(str(root_plan["root_filled_size"]))
        if slot == 5
        else Decimal(str(dict(root_plan["order"])["base_size"]))
    )
    child_tuple = runner.build_child_order_tuple(
        plan,
        root_plan,
        filled_size=filled_size,
        fresh_market={
            "best_bid": _preflight()["best_bid"],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        price_increment=Decimal(str(plan["child_price_increment"])),
    )
    state = {
        "stealth_order_id": root_plan["child_client_order_id"],
        "status": "HIDDEN",
        "revealed_orders": [],
        "revealed_size": "0",
        "executed_size": "0",
        "anchor_repricing_state_json": {
            "controlled_admin_first_child_reveal_preparation": {
                "batch_id": plan["batch_id"],
                "batch_slot": slot,
                "root_client_order_id": root_plan["root_client_order_id"],
                "stealth_order_id": root_plan["child_client_order_id"],
                "portfolio_id": plan["portfolio_id"],
                "approval_snapshot_id": child_tuple["approval_snapshot_id"],
                "admission_audit_id": f"audit-{slot}",
                "cap_guard_decision_id": f"cap-{slot}",
                "reconciliation_plan_id": f"reconciliation-{slot}",
                "authority_id": f"authority-{slot}",
            }
        },
    }
    return child_tuple, state


@pytest.mark.parametrize(
    ("slot", "expected_mode"),
    [(5, "exact_v13_recovery_child"), (6, "fresh_v13_root_child")],
)
def test_v13_child_sdk_preparation_accepts_only_recovery_5_or_fresh_6_to_10(
    slot: int,
    expected_mode: str,
) -> None:
    plan, roots = _validated_v13_plan()
    root_plan = (
        dict(plan["recovery_slot_5"])
        if slot == 5
        else dict(roots[slot - 6])
    )
    child_tuple, state = _child_preparation_fixture(plan, root_plan)

    evidence = runner.validate_controlled_child_preparation_scope(
        confirmed_plan=plan,
        exact_tuple=child_tuple,
        state=state,
    )

    assert evidence["slot"] == slot
    assert evidence["preparation_mode"] == expected_mode
    assert evidence["supersession_present"] is False
    assert evidence["preparation_history_count"] == 0


def test_v13_recovery_child_preparation_rejects_supersession_or_broader_scope() -> None:
    plan, _ = _validated_v13_plan()
    recovery = dict(plan["recovery_slot_5"])
    child_tuple, state = _child_preparation_fixture(plan, recovery)

    superseded = deepcopy(state)
    preparation = superseded["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ]
    preparation["supersedes_batch_id"] = "forbidden"
    with pytest.raises(
        runner.ProofFailure,
        match="child_sdk_preparation_has_supersession",
    ):
        runner.validate_controlled_child_preparation_scope(
            confirmed_plan=plan,
            exact_tuple=child_tuple,
            state=superseded,
        )

    broadened_plan = deepcopy(plan)
    broadened_plan["recovery_slot_5"]["root_placement_authorized"] = True
    with pytest.raises(
        runner.ProofFailure,
        match=(
            "successor_plan_recovery_5_row_not_proof_only"
            "|child_sdk_recovery_scope_mismatch"
        ),
    ):
        runner.validate_controlled_child_preparation_scope(
            confirmed_plan=broadened_plan,
            exact_tuple=child_tuple,
            state=state,
        )


def test_v13_failure_attempt_scope_has_no_recovery_root_attempt_or_sdk_call() -> None:
    plan, roots = _validated_v13_plan()
    recovery = dict(plan["recovery_slot_5"])

    scope = runner.classify_failure_reconciliation_attempt_scope(
        root_plan=recovery,
        root_attempts=[],
        child_attempts=[],
        sdk_boundary_sentinel={
            "root_create_order_call_count": 0,
            "child_place_limit_order_call_count": 0,
        },
    )
    assert scope == {
        "slot": 5,
        "recovery_slot_5": True,
        "root_sdk_call_count": 0,
        "child_sdk_call_count": 0,
        "root_sdk_call_occurred": False,
        "child_sdk_call_occurred": False,
    }

    with pytest.raises(
        runner.ProofFailure,
        match="failure_recovery_root_attempt_present",
    ):
        runner.classify_failure_reconciliation_attempt_scope(
            root_plan=recovery,
            root_attempts=[{"attempt_kind": "root"}],
            child_attempts=[],
            sdk_boundary_sentinel={
                "root_create_order_call_count": 0,
                "child_place_limit_order_call_count": 0,
            },
        )
    with pytest.raises(
        runner.ProofFailure,
        match="failure_recovery_root_sdk_call_present",
    ):
        runner.classify_failure_reconciliation_attempt_scope(
            root_plan=recovery,
            root_attempts=[],
            child_attempts=[],
            sdk_boundary_sentinel={
                "root_create_order_call_count": 1,
                "child_place_limit_order_call_count": 0,
            },
        )

    fresh = dict(roots[0])
    fresh_scope = runner.classify_failure_reconciliation_attempt_scope(
        root_plan=fresh,
        root_attempts=[{"attempt_kind": "root"}],
        child_attempts=[],
        sdk_boundary_sentinel={
            "root_create_order_call_count": 1,
            # Recovery child 5 has already consumed the first child ordinal.
            "child_place_limit_order_call_count": 1,
        },
    )
    assert fresh_scope["slot"] == 6
    assert fresh_scope["recovery_slot_5"] is False
    assert fresh_scope["root_sdk_call_occurred"] is True
    assert fresh_scope["child_sdk_call_occurred"] is False


@pytest.mark.parametrize(
    (
        "child_attempt_count",
        "child_sdk_call_count",
        "child_exchange_state",
        "expected_safe",
    ),
    [
        (0, 0, "absent", True),
        (1, 0, "absent", True),
        (1, 1, "cancelled", True),
        (1, 1, "absent", False),
    ],
)
def test_v13_recovery_failure_reconciliation_is_exact_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    child_attempt_count: int,
    child_sdk_call_count: int,
    child_exchange_state: str,
    expected_safe: bool,
) -> None:
    plan, _ = _validated_v13_plan()
    recovery = dict(plan["recovery_slot_5"])
    child_tuple, _ = _child_preparation_fixture(plan, recovery)
    child_attempt = {
        "attempt_kind": "child",
        "root_client_order_id": runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID,
        "client_order_id": runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID,
        "exact_order_tuple": child_tuple,
    }
    ledger = [child_attempt] if child_attempt_count else []

    root_order = {
        "client_order_id": runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID,
        "order_id": runner.V12_SLOT_5_ROOT_EXCHANGE_ORDER_ID,
        "product_id": runner.PRODUCT_ID,
        "product_type": "SPOT",
        "retail_portfolio_id": runner.TEST_PORTFOLIO_ID,
        "side": "BUY",
        "order_type": "LIMIT",
        "time_in_force": "FILL_OR_KILL",
        "status": "FILLED",
        "filled_size": str(runner.V12_SLOT_5_ROOT_FILLED_SIZE),
        "filled_value": str(runner.V12_SLOT_5_ROOT_FILLED_VALUE),
        "total_fees": str(runner.V12_SLOT_5_ROOT_TOTAL_FEES),
    }
    root_readback = {
        "authoritative": True,
        "pagination_complete": True,
        "exact_identity_match": True,
        "confirmed_absent": False,
        "matched_order": root_order,
        "exchange_order_id": runner.V12_SLOT_5_ROOT_EXCHANGE_ORDER_ID,
        "authoritative_status": "FILLED",
    }
    absent_child = {
        "authoritative": True,
        "pagination_complete": True,
        "exact_identity_match": False,
        "confirmed_absent": True,
        "matched_order": None,
        "exchange_order_id": None,
        "authoritative_status": None,
    }
    cancelled_child_order = {
        **child_tuple,
        "order_id": "offline-v13-recovery-child-exchange-id",
        "status": "CANCELLED",
        "filled_size": "0",
    }
    cancelled_child = {
        "authoritative": True,
        "pagination_complete": True,
        "exact_identity_match": True,
        "confirmed_absent": False,
        "matched_order": cancelled_child_order,
        "exchange_order_id": "offline-v13-recovery-child-exchange-id",
        "authoritative_status": "CANCELLED",
    }

    hidden_chain = {
        "type": "admin_order_fill_follow_up_chain",
        "found": True,
        "client_order_id": runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID,
        "root_parent_client_order_id": runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID,
        "follow_up_child_count": 1,
        "follow_up_child_client_order_ids": [
            runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID
        ],
        "duplicate_child_client_order_ids": [],
        "nested_child_client_order_ids": [],
        "nested_parent_client_order_ids": [],
        "flat_hierarchy_violation_count": 0,
        "root_order": {
            "client_order_id": runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID,
            "status": "FILLED",
            "ownership_provenance": "ADMIN_MANUAL_ROOT",
            "retail_portfolio_id": runner.TEST_PORTFOLIO_ID,
            "exchange_order_id": runner.V12_SLOT_5_ROOT_EXCHANGE_ORDER_ID,
        },
        "follow_up_children": [
            {
                "client_order_id": runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID,
                "parent_client_order_id": runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID,
                "status": "PENDING",
                "ownership_provenance": "ADMIN_FILL_FOLLOW_UP",
                "retail_portfolio_id": runner.TEST_PORTFOLIO_ID,
                "exchange_order_id": None,
            }
        ],
        "portfolio_scope": {"scope_consistent": True, "status": "matched"},
        "read_only": True,
        "live_coinbase_orders_ran": False,
        "local_state_mutated": False,
        "exchange_state_mutated": False,
    }
    hidden_detail = {
        "found": True,
        "read_only": True,
        "live_coinbase_orders_ran": False,
        "order": {
            "stealth_order_id": runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID,
            "parent_stealth_order_id": runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID,
            "product_id": runner.PRODUCT_ID,
            "side": "SELL",
            "status": "HIDDEN",
            "total_size": str(runner.V12_SLOT_5_ROOT_FILLED_SIZE),
            "remaining_size": str(runner.V12_SLOT_5_ROOT_FILLED_SIZE),
            "revealed_size": "0",
            "executed_size": "0",
            "revealed_orders": [],
            "last_placement_at": None,
            "active_placement_client_order_id": None,
            "active_exchange_order_id": None,
        },
    }

    class FakeRuntime:
        confirmed_plan = plan
        confirmed_plan_hash = str(plan["plan_sha256"])
        attempt_ledger_path = runner.Path("/offline/v13.attempts.jsonl")
        portfolio_id = runner.TEST_PORTFOLIO_ID
        live_service_disable_proven = False
        exchange_safe_to_shutdown = False

        def sdk_boundary_sentinel(self) -> dict[str, object]:
            return {
                "root_create_order_call_count": 0,
                "child_place_limit_order_call_count": child_sdk_call_count,
                "denied_call_count": 0,
                "root_sdk_inflight": False,
                "child_sdk_inflight": False,
            }

        def headers(self, **_kwargs: object) -> dict[str, str]:
            return {}

        def request(
            self,
            _method: str,
            path: str,
            **_kwargs: object,
        ) -> tuple[int, dict[str, object], dict[str, str]]:
            if path == "/admin/runtime":
                return 200, {"total_inflight": 0}, {}
            if path.endswith("/fill-follow-up/chain"):
                return 200, hidden_chain, {}
            if path == f"/stealth/orders/{runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID}":
                return 200, hidden_detail, {}
            if path == f"/orders/{runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID}":
                return 200, {"found": True}, {}
            raise AssertionError(path)

    runtime = FakeRuntime()

    def disable_service(fake_runtime: FakeRuntime, *, enabled: bool) -> None:
        assert enabled is False
        fake_runtime.live_service_disable_proven = True

    def exact_readback(
        _client: object,
        *,
        client_order_id: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        if client_order_id == runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID:
            return root_readback
        return (
            cancelled_child
            if child_exchange_state == "cancelled"
            else absent_child
        )

    monkeypatch.setattr(runner, "set_live_service", disable_service)
    monkeypatch.setattr(
        runner,
        "read_batch_attempt_ledger",
        lambda *_args, **_kwargs: ledger,
    )
    monkeypatch.setattr(
        runner,
        "read_authoritative_spot_nonterminal_orders",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        runner,
        "_validate_exact_coinbase_gtc_child_order",
        lambda order, **_kwargs: dict(order),
    )
    monkeypatch.setattr(
        runner,
        "_validate_cancelled_child_chain",
        lambda *_args, **_kwargs: {"terminal": True},
    )
    monkeypatch.setattr(
        runner,
        "load_v12_binding",
        runner.offline_v12_binding_fixture,
    )
    from application.admin_api import command_service

    monkeypatch.setattr(
        command_service,
        "exact_coinbase_order_readback",
        exact_readback,
    )
    evidence = runner.reconcile_failure_state(
        runtime,
        rest_client=object(),
        summary={},
        current_root_client_order_id=runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID,
    )

    assert evidence["safe_to_shutdown"] is expected_safe
    assert evidence["retry_attempted"] is False
    assert evidence["substitution_attempted"] is False
    assert evidence["next_slot_authorized"] is False


def test_v13_serialized_authority_payloads_fit_reader_limits(
    tmp_path: runner.Path,
) -> None:
    plan, _ = _validated_v13_plan()
    marker = runner.build_global_batch_marker_payload(
        runner.SUCCESSOR_V13_PLAN_PATH,
        confirmed_plan=plan,
        expected_hash=str(plan["plan_sha256"]),
        expected_runner_sha256=runner.runner_sha256(),
        registered_at=datetime.now(timezone.utc).isoformat(),
        process_id=12345,
    )
    state_dir = tmp_path / "runtime-state"
    authority = runner.build_runtime_child_authority_payload(
        state_dir=state_dir,
        auth_file=state_dir / runner.RUNTIME_CHILD_AUTH_FILENAME,
        global_batch_marker=runner.Path(str(marker["marker_path"])),
        global_batch_marker_sha256="a" * 64,
        attempt_ledger_path=runner.Path(str(marker["attempt_ledger_path"])),
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        confirmed_runner_sha256=runner.runner_sha256(),
        parent_pid=12345,
        parent_start_identity="67890",
        nonce="offline-v13-size-proof",
    )

    sizes = {
        name: len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        for name, payload in (
            ("plan", plan),
            ("marker", marker),
            ("runtime_authority", authority),
        )
    }
    assert max(sizes.values()) < 100_000, sizes
