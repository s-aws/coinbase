"""Focused sealed-lineage and topology tests for the controlled v12 runner."""

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
        "wallets": {"USDC": Decimal("990"), "BTC": Decimal("0.000088")},
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
            "observed_at": "2026-07-12T10:40:00+00:00",
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


def _validated_active_plan() -> tuple[dict[str, object], list[dict[str, object]]]:
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


def test_v11_failure_is_exactly_sealed_and_every_identity_is_burned() -> None:
    binding = runner.load_v11_binding()

    assert binding == runner.offline_v11_binding_fixture()
    assert binding["plan_sha256"] == (
        "abb803bf89697f9d3fe77554359cc053b70f3517fc32677786cee1a068071419"
    )
    assert binding["attempt_count"] == 3
    assert binding["root_sdk_call_count"] == 1
    assert binding["child_sdk_call_count"] == 2
    assert binding["transmitted_attempt_count"] == 3
    assert binding["terminal_transmitted_attempt_count"] == 3
    assert binding["all_transmitted_attempts_terminal"] is True
    assert binding["active_spot_orders_at_closeout"] == []
    assert binding["service_disabled_at_closeout"] is True
    assert binding["runtime_shutdown_proven"] is True
    assert binding["operator_reconciliation_status"] == (
        "operator_reconciled_terminal"
    )
    assert Decimal(binding["completed_reference_notional_usdc"]) == Decimal(
        "11.6368999839"
    )
    assert [chain["slot"] for chain in binding["completed_flat_chains"]] == [
        1,
        2,
        3,
        4,
    ]
    assert set(binding["burned_root_client_order_ids"]) == set(
        runner.FAILED_SUCCESSOR_V11_PLANNED_ROOT_CLIENT_ORDER_IDS
    )
    assert set(binding["burned_child_client_order_ids"]) == {
        runner.V10_SLOT_3_CHILD_CLIENT_ORDER_ID,
        *runner.FAILED_SUCCESSOR_V11_PLANNED_CHILD_CLIENT_ORDER_IDS,
    }
    assert binding["untransmitted_approval_reusable"] is False
    assert binding["all_v11_authority_burned"] is True


def test_v11_operator_reconciliation_hash_is_bound() -> None:
    binding = runner.offline_v11_binding_fixture()

    assert binding["operator_reconciliation_bytes_sha256"] == (
        "ee17801a279f0e7117677a6118cfb4a0ac0b4d956b439d669821a07a54de2116"
    )
    assert binding["operator_reconciliation_path"].endswith(
        "operator-reconciliation.json"
    )


def test_v11_artifact_validator_rejects_cap_seed_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "V11_COMPLETED_REFERENCE_NOTIONAL",
        Decimal("0"),
    )

    with pytest.raises(
        runner.ProofFailure,
        match="failed_v11_completed_reference_notional_mismatch",
    ):
        runner.load_v11_binding()


def test_active_v13_authority_is_child_5_then_fresh_pairs_6_through_10() -> None:
    assert runner.EXPECTED_COMMIT == (
        "6f4812e9ffdcaace9c4d3aae6d3a074c320d3f96"
    )
    assert runner.V13_RUNNER_AUTHORITY_PARENT_COMMIT == (
        runner.FAILED_SUCCESSOR_V12_RUNNER_COMMIT
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


def test_active_v13_plan_has_exact_recovery_and_fresh_slots_6_to_10() -> None:
    plan, roots = _validated_active_plan()

    assert plan["continuation_kind"] == (
        "sealed_v12_root_5_fill_recover_child_then_fresh_slots_6_to_10_v13"
    )
    assert str(plan["approval_id"]).startswith(
        "controlled-root-child-successor-v13-"
    )
    assert plan["remaining_attempt_count"] == 11
    assert plan["new_root_order_maximum"] == 5
    assert plan["child_order_maximum"] == 6
    assert plan["v11_binding"] == runner.offline_v11_binding_fixture()
    assert plan["v12_binding"] == runner.offline_v12_binding_fixture()
    assert "recovery_slot_3" not in plan
    assert [root["slot"] for root in roots] == list(range(6, 11))
    assert all(root["root_placement_authorized"] is True for root in roots)
    recovery = plan["recovery_slot_5"]
    assert recovery["root_placement_authorized"] is False
    assert recovery["child_recovery_authorized"] is True
    assert recovery["root_client_order_id"] == (
        runner.V12_SLOT_5_ROOT_CLIENT_ORDER_ID
    )
    assert recovery["child_client_order_id"] == (
        runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID
    )

    fresh_ids = {
        str(value)
        for root in roots
        for value in (
            root["root_client_order_id"],
            root["child_client_order_id"],
        )
    }
    burned_historical_ids = {
        runner.V10_SLOT_3_CHILD_CLIENT_ORDER_ID,
        *runner.FAILED_SUCCESSOR_V11_PLANNED_ROOT_CLIENT_ORDER_IDS,
        *runner.FAILED_SUCCESSOR_V11_PLANNED_CHILD_CLIENT_ORDER_IDS,
        *runner.FAILED_SUCCESSOR_V12_PLANNED_ROOT_CLIENT_ORDER_IDS,
        *runner.FAILED_SUCCESSOR_V12_PLANNED_CHILD_CLIENT_ORDER_IDS,
    }
    assert not fresh_ids & burned_historical_ids


def test_active_v13_plan_cap_starts_at_exact_v12_lifetime_seed() -> None:
    plan, roots = _validated_active_plan()
    recovery = plan["recovery_slot_5"]
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
    assert plan["reference_cap_scope"] == runner.V13_REFERENCE_CAP_SCOPE
    assert Decimal(str(plan["planned_new_root_notional_usdc"])) == (
        planned_new_root
    )
    assert Decimal(str(plan["planned_new_child_reference_notional_usdc"])) == (
        planned_new_child
    )
    assert Decimal(
        str(plan["planned_total_root_child_reference_notional_usdc"])
    ) == expected_total
    assert expected_total < Decimal("30.00")
    assert all(
        Decimal(str(root["order"]["base_size"])) * child_price
        < Decimal("2.00")
        for root in roots
    )


def test_active_v13_marker_binds_exact_recovery_authority() -> None:
    plan, roots = _validated_active_plan()
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
    assert marker["v11_binding"] == runner.offline_v11_binding_fixture()
    assert marker["v12_binding"] == runner.offline_v12_binding_fixture()
    assert "recovery_slot_3_policy" not in marker
    assert marker["recovery_slot_5_policy"]["root_placement_authorized"] is False
    assert marker["exact_child_client_order_ids"] == [
        runner.V12_SLOT_5_CHILD_CLIENT_ORDER_ID,
        *[
        str(root["child_client_order_id"]) for root in roots
        ],
    ]


def test_active_v13_ledger_starts_with_child_5_and_seeds_v12_reference() -> None:
    plan, _ = _validated_active_plan()
    recovery = plan["recovery_slot_5"]
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
    assert record["client_order_id"] == recovery["child_client_order_id"]

    tuple_notional = Decimal(child_tuple["base_size"]) * Decimal(
        child_tuple["limit_price"]
    )
    original_cap = runner.BATCH_TOTAL_REFERENCE_CAP_USDC
    try:
        runner.BATCH_TOTAL_REFERENCE_CAP_USDC = (
            runner.V12_COMPLETED_REFERENCE_NOTIONAL + tuple_notional
        )
        with pytest.raises(
            runner.ProofFailure,
            match="global_batch_attempt_cumulative_reference_cap_exceeded",
        ):
            runner._parse_and_validate_attempt_ledger(
                raw,
                confirmed_plan=plan,
                confirmed_plan_hash=str(plan["plan_sha256"]),
            )
    finally:
        runner.BATCH_TOTAL_REFERENCE_CAP_USDC = original_cap


def test_active_v13_runtime_authority_accepts_only_exact_recovery_plan() -> None:
    plan, _ = _validated_active_plan()

    runner._validate_authority_plan_structure(
        plan,
        expected_plan_hash=str(plan["plan_sha256"]),
    )


def test_active_v13_serialized_authority_payloads_fit_reader_limits(
    tmp_path: runner.Path,
) -> None:
    plan, _ = _validated_active_plan()
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

    encoded_sizes = {
        name: len(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        for name, payload in (
            ("plan", plan),
            ("marker", marker),
            ("runtime_authority", authority),
        )
    }
    assert max(encoded_sizes.values()) < 100_000, encoded_sizes


def test_active_v13_execution_has_only_exact_child_5_recovery_branch() -> None:
    source = inspect.getsource(runner.execute_controlled_batch)
    module_source = runner.Path(runner.__file__).read_text(encoding="utf-8")

    assert "execution_rows = [recovery_slot_5, *roots]" in source
    assert "recovery_slot_3" not in source
    assert "for root_plan in execution_rows:" in source
    assert "if slot >= 6:" in source
    assert "root_calls_before = max(0, slot - 6)" in source
    assert "child_calls_before = slot - 5" in source
    assert '"interrupted_after_recovery"' not in module_source
    assert '"interrupted_after_reconciliation"' in module_source


def test_active_v13_recovery_absence_and_active_zero_precede_registration_and_enable() -> None:
    main_source = inspect.getsource(runner.main)
    v12_absence = main_source.index("prove_failed_v12_unused_client_ids_absent")
    active_zero = main_source.index(
        "prove_stable_authoritative_active_zero",
        v12_absence,
    )
    registration = main_source.index("initialize_global_batch_ledger")
    recovery = main_source.index("prove_v12_slot_5_recovery_preconditions")
    assert recovery < v12_absence < active_zero < registration

    execute_source = inspect.getsource(runner.execute_controlled_batch)
    runtime_absence = execute_source.index(
        "prove_failed_v12_unused_client_ids_absent"
    )
    runtime_zero = execute_source.index("prove_stable_authoritative_active_zero")
    first_enable = execute_source.index("set_live_service(runtime, enabled=True)")
    runtime_recovery = execute_source.index("v12_recovery_at_runtime_start")
    assert runtime_absence < runtime_zero < runtime_recovery < first_enable


@pytest.mark.parametrize("attempt_kind", ["root", "child"])
def test_v12_parent_durable_cancel_rejection_handoff_prevents_watchdog_replay(
    tmp_path: runner.Path,
    attempt_kind: str,
) -> None:
    plan, roots = _validated_active_plan()
    root = roots[0]
    slot = int(root["slot"])
    client_order_id = str(
        root[
            "root_client_order_id"
            if attempt_kind == "root"
            else "child_client_order_id"
        ]
    )
    route = (
        f"/orders/{client_order_id}/cancel"
        if attempt_kind == "root"
        else f"/stealth/orders/{client_order_id}/cancel"
    )
    idempotency_key = (
        f"{plan['batch_id']}-{attempt_kind}-{slot}-cancel"
    )

    class ParentRuntime:
        state_dir = tmp_path
        cancel_http_calls = 0

        def request(
            self,
            method: str,
            path: str,
            *,
            headers: dict[str, str],
            body: dict[str, object],
            expected: object,
        ) -> tuple[int, dict[str, str], dict[str, str]]:
            assert method == "POST"
            assert path == route
            assert headers["Idempotency-Key"] == idempotency_key
            assert body["manual_live_acknowledgement"] is True
            assert expected is None
            self.cancel_http_calls += 1
            return 400, {"status": "rejected"}, {}

    runtime = ParentRuntime()
    status, payload, _ = runner._request_exact_cancel_with_handoff(
        runtime,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        slot=slot,
        attempt_kind=attempt_kind,
        client_order_id=client_order_id,
        path=route,
        headers={"Idempotency-Key": idempotency_key},
        body={"manual_live_acknowledgement": True},
    )

    handoff_path = tmp_path / runner.PARENT_CANCEL_OUTCOME_FILENAME
    assert status == 400
    assert payload["status"] == "rejected"
    assert handoff_path.stat().st_mode & 0o777 == 0o600
    assert handoff_path.stat().st_size <= runner.PARENT_CANCEL_OUTCOME_MAXIMUM_BYTES
    seeded_outcomes = runner._load_parent_cancel_outcome_handoff(
        tmp_path,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
    )
    assert seeded_outcomes == {client_order_id: "durable_rejected"}

    watchdog_decision = runner._parent_loss_cancel_retry_decision(
        exact_order_active=True,
        stable_active_scope_proven=True,
        prior_cancel_outcome=seeded_outcomes[client_order_id],
    )
    if watchdog_decision == "issue_same_idempotent_exact_cancel":
        runtime.request(
            "POST",
            route,
            headers={"Idempotency-Key": idempotency_key},
            body={"manual_live_acknowledgement": True},
            expected=None,
        )

    assert watchdog_decision == "require_operator_direct_reconciliation"
    assert runtime.cancel_http_calls == 1


@pytest.mark.parametrize(
    ("delivery", "expected_outcome"),
    [
        ("timeout", "timeout_or_exception"),
        ("non_200", "non_200_or_unaccepted"),
    ],
)
def test_v12_parent_ambiguous_cancel_handoff_retains_same_idempotent_retry(
    tmp_path: runner.Path,
    delivery: str,
    expected_outcome: str,
) -> None:
    plan, roots = _validated_active_plan()
    root = roots[0]
    slot = int(root["slot"])
    client_order_id = str(root["child_client_order_id"])
    route = f"/stealth/orders/{client_order_id}/cancel"
    idempotency_key = f"{plan['batch_id']}-child-{slot}-cancel"

    class ParentRuntime:
        state_dir = tmp_path

        def request(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> tuple[int, dict[str, str], dict[str, str]]:
            if delivery == "timeout":
                raise TimeoutError("offline-parent-cancel-timeout")
            return 503, {"status": "error"}, {}

    def issue_parent_cancel() -> object:
        return runner._request_exact_cancel_with_handoff(
            ParentRuntime(),
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
            slot=slot,
            attempt_kind="child",
            client_order_id=client_order_id,
            path=route,
            headers={"Idempotency-Key": idempotency_key},
            body={"manual_live_acknowledgement": True},
        )

    if delivery == "timeout":
        with pytest.raises(
            TimeoutError,
            match="offline-parent-cancel-timeout",
        ):
            issue_parent_cancel()
    else:
        status, _, _ = issue_parent_cancel()
        assert status == 503

    seeded_outcomes = runner._load_parent_cancel_outcome_handoff(
        tmp_path,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
    )

    assert seeded_outcomes[client_order_id] == expected_outcome
    assert runner._parent_loss_cancel_retry_decision(
        exact_order_active=True,
        stable_active_scope_proven=True,
        prior_cancel_outcome=seeded_outcomes[client_order_id],
    ) == "issue_same_idempotent_exact_cancel"


def test_v12_parent_cancel_handoff_rejects_plan_tamper(
    tmp_path: runner.Path,
) -> None:
    plan, roots = _validated_active_plan()
    root = roots[0]
    client_order_id = str(root["root_client_order_id"])
    runner._write_parent_cancel_outcome_handoff(
        tmp_path,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        slot=int(root["slot"]),
        attempt_kind="root",
        client_order_id=client_order_id,
        outcome="durable_rejected",
    )
    path = tmp_path / runner.PARENT_CANCEL_OUTCOME_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["plan_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        runner.ProofFailure,
        match="parent_cancel_handoff_envelope_mismatch",
    ):
        runner._load_parent_cancel_outcome_handoff(
            tmp_path,
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
        )


def test_v12_parent_cancel_handoff_rejects_wrong_exact_identity(
    tmp_path: runner.Path,
) -> None:
    plan, roots = _validated_active_plan()
    root = roots[0]

    with pytest.raises(
        runner.ProofFailure,
        match="parent_cancel_handoff_client_order_id_mismatch",
    ):
        runner._write_parent_cancel_outcome_handoff(
            tmp_path,
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
            slot=int(root["slot"]),
            attempt_kind="root",
            client_order_id=str(root["child_client_order_id"]),
            outcome="durable_rejected",
        )

    assert not (tmp_path / runner.PARENT_CANCEL_OUTCOME_FILENAME).exists()


def test_v12_parent_cancel_handoff_is_wired_into_parent_and_watchdog() -> None:
    execution_source = inspect.getsource(runner.execute_controlled_batch)
    runtime_child_source = inspect.getsource(runner.run_embedded_runtime_child)

    assert execution_source.count("_request_exact_cancel_with_handoff(") == 5
    load_index = runtime_child_source.index(
        "cancel_outcomes = _load_parent_cancel_outcome_handoff("
    )
    decision_index = runtime_child_source.index(
        "prior_outcome = cancel_outcomes.get(active_client_id)"
    )
    cancel_http_index = runtime_child_source.index(
        "result = post_exact_parent_loss_cancel("
    )
    assert load_index < decision_index < cancel_http_index
    assert "cancel_handoff_valid = False" in runtime_child_source
    assert (
        'else "require_operator_direct_reconciliation"'
        in runtime_child_source
    )
    assert "or not cancel_handoff_valid" in runtime_child_source


def _v12_in_progress_chain_fixtures() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    plan = json.loads(
        runner.FAILED_SUCCESSOR_V12_PLAN_PATH.read_text(encoding="utf-8")
    )
    roots = runner._validate_frozen_v12_plan_structure(plan)
    root_plan = roots[0]
    root_id = str(root_plan["root_client_order_id"])
    child_id = str(root_plan["child_client_order_id"])
    filled_size = str(dict(root_plan["order"])["base_size"])
    correlation_id = runner.V12_SLOT_5_ROOT_CORRELATION_ID
    audit_id = runner.V12_SLOT_5_ROOT_ADMISSION_AUDIT_ID
    exchange_order_id = runner.V12_SLOT_5_ROOT_EXCHANGE_ORDER_ID
    scope = runner.build_v12_in_progress_chain_scope(
        confirmed_plan=plan,
        root_plan=root_plan,
        root_exchange_order_id=exchange_order_id,
        root_correlation_id=correlation_id,
        root_audit_id=audit_id,
        filled_size=filled_size,
        portfolio_id=runner.TEST_PORTFOLIO_ID,
    )
    root = {
        "client_order_id": root_id,
        "parent_order_id": None,
        "product_id": runner.PRODUCT_ID,
        "side": "BUY",
        "size": filled_size,
        "status": "FILLED",
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
        "retail_portfolio_id": runner.TEST_PORTFOLIO_ID,
        "correlation_id": correlation_id,
        "audit_id": audit_id,
        "exchange_order_id": exchange_order_id,
    }
    child = {
        "client_order_id": child_id,
        "parent_order_id": root_id,
        "product_id": runner.PRODUCT_ID,
        "side": "SELL",
        "size": filled_size,
        "status": "PENDING",
        "ownership_provenance": "ADMIN_FILL_FOLLOW_UP",
        "retail_portfolio_id": runner.TEST_PORTFOLIO_ID,
        "correlation_id": correlation_id,
        "audit_id": audit_id,
        "exchange_order_id": None,
    }
    stealth = {
        "stealth_order_id": child_id,
        "parent_order_id": root_id,
        "product_id": runner.PRODUCT_ID,
        "side": "SELL",
        "total_size": filled_size,
        "remaining_size": filled_size,
        "revealed_size": "0",
        "executed_size": "0",
        "status": "HIDDEN",
        "revealed_orders": [],
        "last_placement_at": None,
        "condition_first_met_at": None,
        "condition_confirmed_at": None,
        "anchor_repricing_state_json": {},
    }
    return scope, root, child, stealth


def test_v12_slot_5_post_root_scope_allows_only_exact_unsubmitted_child() -> None:
    scope, root, child, stealth = _v12_in_progress_chain_fixtures()

    evidence = runner.validate_v12_in_progress_local_chain(
        scope=scope,
        root_row=root,
        child_row=child,
        stealth_row=stealth,
        direct_child_client_order_ids=[child["client_order_id"]],
        grandchild_client_order_ids=[],
    )

    assert evidence == {
        "slot": 5,
        "root_client_order_id": root["client_order_id"],
        "child_client_order_id": child["client_order_id"],
        "root_status": "FILLED",
        "child_parent_status": "PENDING",
        "child_stealth_status": "HIDDEN",
        "child_wholly_unsubmitted": True,
        "flat_chain_proven": True,
        "exception_is_read_only": True,
        "root_placement_authorized": False,
        "child_placement_authorized": False,
        "recovery_authorized": False,
        "retry_authorized": False,
        "substitution_authorized": False,
    }


def test_v12_burned_id_recheck_forwards_exact_in_progress_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope, _, _, _ = _v12_in_progress_chain_fixtures()
    observed: dict[str, object] = {}

    def local_scope(**kwargs: object) -> dict[str, bool]:
        observed.update(kwargs)
        return {
            "planned_ids_absent_from_order_parent": True,
            "planned_ids_absent_from_stealth_orders": True,
            "planned_ids_absent_from_fill_ledger": True,
            "planned_ids_absent_from_order_match_audit": True,
        }

    monkeypatch.setattr(
        runner,
        "prove_local_scope_with_historical_hidden_child",
        local_scope,
    )
    monkeypatch.setattr(
        runner,
        "prove_completed_v11_flat_chains_local",
        lambda: {"chain_count": 4},
    )
    monkeypatch.setattr(
        runner,
        "read_failed_v6_v7_order_catalog",
        lambda _client: (
            [],
            {
                "authoritative": True,
                "pagination_complete": True,
                "page_count": 1,
                "order_count": 0,
            },
        ),
    )

    evidence = runner.prove_failed_v11_unused_client_ids_absent(
        object(),
        current_plan_in_progress_chain=scope,
    )

    assert evidence["fresh_read"] is True
    assert observed["current_plan_in_progress_chain"] == scope


@pytest.mark.parametrize(
    ("target", "field", "value", "blocker"),
    [
        ("root", "status", "CANCELLED", "v12_in_progress_root_evidence_mismatch"),
        ("child", "status", "CANCELLED", "v12_in_progress_child_evidence_mismatch"),
        ("child", "exchange_order_id", "exchange-child", "v12_in_progress_child_evidence_mismatch"),
        ("stealth", "product_id", "ETH-USDC", "v12_in_progress_stealth_identity_mismatch"),
        ("stealth", "executed_size", "0.00000001", "v12_in_progress_child_not_wholly_unsubmitted"),
        ("stealth", "revealed_size", "0.00000001", "v12_in_progress_child_not_wholly_unsubmitted"),
        ("stealth", "revealed_orders", ["placement"], "v12_in_progress_child_not_wholly_unsubmitted"),
        ("stealth", "last_placement_at", "2026-07-12T12:00:00Z", "v12_in_progress_child_not_wholly_unsubmitted"),
        ("stealth", "anchor_repricing_state_json", {"active_placement_client_order_id": "placement"}, "v12_in_progress_child_not_wholly_unsubmitted"),
        ("root", "retail_portfolio_id", "default-profile", "v12_in_progress_root_evidence_mismatch"),
    ],
)
def test_v12_in_progress_scope_rejects_terminal_placement_or_wrong_scope(
    target: str,
    field: str,
    value: object,
    blocker: str,
) -> None:
    scope, root, child, stealth = _v12_in_progress_chain_fixtures()
    rows = {"root": root, "child": child, "stealth": stealth}
    rows[target][field] = value

    with pytest.raises(runner.ProofFailure, match=blocker):
        runner.validate_v12_in_progress_local_chain(
            scope=scope,
            root_row=root,
            child_row=child,
            stealth_row=stealth,
            direct_child_client_order_ids=[child["client_order_id"]],
            grandchild_client_order_ids=[],
        )


@pytest.mark.parametrize(
    ("direct_children", "grandchildren", "blocker"),
    [
        (["expected", "second"], [], "v12_in_progress_multiple_children_present"),
        (["expected"], ["grandchild"], "v12_in_progress_grandchild_present"),
    ],
)
def test_v12_in_progress_scope_rejects_multiple_children_and_grandchildren(
    direct_children: list[str],
    grandchildren: list[str],
    blocker: str,
) -> None:
    scope, root, child, stealth = _v12_in_progress_chain_fixtures()
    expected_child_id = str(child["client_order_id"])
    normalized_children = [
        expected_child_id if value == "expected" else value
        for value in direct_children
    ]

    with pytest.raises(runner.ProofFailure, match=blocker):
        runner.validate_v12_in_progress_local_chain(
            scope=scope,
            root_row=root,
            child_row=child,
            stealth_row=stealth,
            direct_child_client_order_ids=normalized_children,
            grandchild_client_order_ids=grandchildren,
        )


def test_v12_in_progress_scope_is_exactly_bound_to_current_plan_slot_5() -> None:
    plan = json.loads(
        runner.FAILED_SUCCESSOR_V12_PLAN_PATH.read_text(encoding="utf-8")
    )
    roots = runner._validate_frozen_v12_plan_structure(plan)
    root_plan = roots[0]
    kwargs = {
        "confirmed_plan": plan,
        "root_plan": root_plan,
        "root_exchange_order_id": runner.V12_SLOT_5_ROOT_EXCHANGE_ORDER_ID,
        "root_correlation_id": runner.V12_SLOT_5_ROOT_CORRELATION_ID,
        "root_audit_id": runner.V12_SLOT_5_ROOT_ADMISSION_AUDIT_ID,
        "filled_size": dict(root_plan["order"])["base_size"],
        "portfolio_id": runner.TEST_PORTFOLIO_ID,
    }

    exact = runner.build_v12_in_progress_chain_scope(**kwargs)
    assert exact["slot"] == 5
    assert exact["plan_sha256"] == plan["plan_sha256"]
    assert exact["exception_is_read_only"] is True
    assert exact["recovery_authorized"] is False
    assert exact["retry_authorized"] is False
    assert exact["substitution_authorized"] is False

    arbitrary_root = deepcopy(root_plan)
    arbitrary_root["root_client_order_id"] = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(
        runner.ProofFailure,
        match="v12_in_progress_root_plan_not_exact_confirmed_slot_5",
    ):
        runner.build_v12_in_progress_chain_scope(
            **{**kwargs, "root_plan": arbitrary_root}
        )

    with pytest.raises(
        runner.ProofFailure,
        match="v12_in_progress_portfolio_scope_mismatch",
    ):
        runner.build_v12_in_progress_chain_scope(
            **{**kwargs, "portfolio_id": "default-profile"}
        )


def test_active_v13_uses_only_recovery_slot_5_not_v12_in_progress_scope() -> None:
    execute_source = inspect.getsource(runner.execute_controlled_batch)
    main_source = inspect.getsource(runner.main)

    assert "current_plan_in_progress_chain=" not in execute_source
    assert "current_plan_in_progress_chain=" not in main_source
    assert execute_source.count("recovery_slot_5=recovery_slot_5") >= 8
    assert "v12_recovery_before_first_live_enable" in execute_source


@pytest.mark.parametrize(
    "helper_name",
    [
        "prove_failed_v6_v7_client_ids_absent",
        "prove_failed_v9_fresh_client_ids_absent",
        "prove_failed_v10_unattempted_client_ids_absent",
        "prove_failed_v11_unused_client_ids_absent",
    ],
)
def test_v12_in_progress_scope_reaches_every_burned_id_local_gate(
    helper_name: str,
) -> None:
    helper_source = inspect.getsource(getattr(runner, helper_name))
    execute_source = inspect.getsource(runner.execute_controlled_batch)
    assert "current_plan_in_progress_chain" in inspect.signature(
        getattr(runner, helper_name)
    ).parameters
    assert (
        "current_plan_in_progress_chain=current_plan_in_progress_chain"
        in helper_source
    )
    assert "current_plan_in_progress_chain=" not in execute_source
    first_enable_scope = execute_source[
        execute_source.index("failed_v6_v7_ids_before_first_enable") :
        execute_source.index("slot_result[\"child_reveal_proofs\"]")
    ]
    helper_call = first_enable_scope[
        first_enable_scope.index(f"{helper_name}(") :
    ]
    assert "recovery_slot_5=recovery_slot_5" in helper_call
