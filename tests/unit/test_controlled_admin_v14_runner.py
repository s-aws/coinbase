"""Focused sealed-lineage and authority tests for the controlled v14 runner."""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import inspect
import json

import pytest

from tools import run_controlled_admin_spot_root_child_batch as runner


def _preflight() -> dict[str, object]:
    return {
        "portfolio_id": runner.TEST_PORTFOLIO_ID,
        "wallets": {"USDC": Decimal("985"), "BTC": Decimal("0.000156")},
        "product": {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
        },
        "best_bid": Decimal("64129.52"),
        "best_ask": Decimal("64129.53"),
        "market": {
            "product_id": runner.PRODUCT_ID,
            "source": "coinbase_rest_get_best_bid_ask_exact_product",
            "observed_at": "2026-07-12T15:30:00+00:00",
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
        "v13_binding": runner.offline_v13_binding_fixture(),
    }


def _validated_v14_plan() -> tuple[dict[str, object], list[dict[str, object]]]:
    preflight = _preflight()
    bindings = _bindings()
    plan = runner.build_v14_successor_live_plan(preflight, **bindings)
    roots, _ = runner.validate_v14_successor_live_plan(
        plan,
        expected_hash=str(plan["plan_sha256"]),
        preflight=preflight,
        **bindings,
    )
    return plan, roots


def test_v13_failure_is_hash_bound_and_burned_at_exact_terminal_slot_7() -> None:
    binding = runner.load_v13_binding()

    assert binding == runner.offline_v13_binding_fixture()
    assert binding["runner_commit"] == (
        "161954c2f187a750cd731db410890b3b4808ed66"
    )
    assert binding["production_parent_commit"] == (
        "6f4812e9ffdcaace9c4d3aae6d3a074c320d3f96"
    )
    assert binding["plan_sha256"] == (
        "94f3e70655837b75d0a688884504bef706cd5251bb9d7c4f8e426d8a0ce8c017"
    )
    assert binding["marker_bytes_sha256"] == (
        "ecc4ace378869718f9929390b1b3f8b827491fefe66bdcff3a508dfe056a7272"
    )
    assert binding["ledger_bytes_sha256"] == (
        "582d6d19ad8abd78f37590ab678052db836f53c06b80c13ac51b185b3d1fd8ad"
    )
    assert binding["attempt_count"] == 5
    assert binding["attempt_schedule"] == [
        [5, "child"],
        [6, "root"],
        [6, "child"],
        [7, "root"],
        [7, "child"],
    ]
    assert binding["root_sdk_call_count"] == 2
    assert binding["child_sdk_call_count"] == 3
    assert binding["failure_reason"] == "child_cancel_http_failed:400"
    assert binding["failure_stage"] == "cancellation_status_persistence"
    assert binding["failure_cause"] == "controlled_child_active_placement_mismatch"
    assert binding["slot_7_root_status"] == "FILLED"
    assert binding["slot_7_child_status"] == "CANCELLED"
    assert binding["slot_7_child_filled_size"] == "0"
    assert binding["slot_7_local_flat_chain_proven"] is True
    assert binding["slot_7_active_placement_cleared"] is True
    assert binding["stable_authoritative_active_spot_zero"] is True
    assert binding["safe_to_shutdown"] is True
    assert binding["retry_authorized"] is False
    assert binding["substitution_authorized"] is False
    assert binding["untransmitted_approval_reusable"] is False
    assert binding["all_v13_authority_burned"] is True
    assert Decimal(binding["completed_reference_notional_usdc"]) == Decimal(
        "20.5480093663"
    )


@pytest.mark.parametrize(
    "field",
    [
        "plan_bytes_sha256",
        "marker_bytes_sha256",
        "ledger_bytes_sha256",
        "failure_bytes_sha256",
        "audit_bytes_sha256",
        "idempotency_bytes_sha256",
        "sentinel_bytes_sha256",
    ],
)
def test_v13_binding_hashes_every_decisive_artifact(field: str) -> None:
    binding = runner.offline_v13_binding_fixture()

    assert len(str(binding[field])) == 64
    assert str(binding[field]) in set(binding["bound_artifact_bytes_sha256"].values())


def test_v14_authority_is_exactly_three_fresh_root_child_pairs() -> None:
    assert runner.V14_EXPECTED_COMMIT == (
        "f8fd86310954d78da29dc5e45853d19c2453ee22"
    )
    assert runner.FAILED_SUCCESSOR_V13_RUNNER_COMMIT == (
        "161954c2f187a750cd731db410890b3b4808ed66"
    )
    assert runner.V14_RUNNER_AUTHORITY_PARENT_COMMIT == runner.V14_EXPECTED_COMMIT
    assert runner.V14_PLAN_SCHEMA_VERSION == "18"
    assert runner.ACTIVE_PLAN_SCHEMA_VERSION == runner.V14_PLAN_SCHEMA_VERSION
    assert runner.V14_ROOT_ORDER_MAXIMUM == 3
    assert runner.V14_CHILD_ORDER_MAXIMUM == 3
    assert runner.V14_ATTEMPT_COUNT == 6
    assert runner.v14_attempt_schedule() == [
        (8, "root"),
        (8, "child"),
        (9, "root"),
        (9, "child"),
        (10, "root"),
        (10, "child"),
    ]
    assert runner.SUCCESSOR_V14_PLAN_PATH.name.endswith(
        "successor-v14-20260712.plan.json"
    )
    assert runner.V14_GLOBAL_BATCH_MARKER_FILENAME.endswith(
        "successor-v14-20260712.authority.json"
    )
    assert runner.V14_GLOBAL_BATCH_LEDGER_FILENAME.endswith(
        "successor-v14-20260712.attempts.jsonl"
    )


def test_v14_plan_uses_only_fresh_slots_8_to_10_and_exact_seed() -> None:
    plan, roots = _validated_v14_plan()
    v13 = runner.offline_v13_binding_fixture()

    assert plan["continuation_kind"] == (
        "sealed_v13_terminal_slot_7_fresh_pairs_slots_8_to_10_v14"
    )
    assert plan["v13_binding"] == v13
    assert "recovery_slot_5" not in plan
    assert plan["remaining_attempt_count"] == 6
    assert plan["new_root_order_maximum"] == 3
    assert plan["child_order_maximum"] == 3
    assert plan["completed_root_order_count"] == 7
    assert plan["completed_child_order_count"] == 7
    assert plan["proof_set_root_exchange_target_after_success"] == 10
    assert plan["proof_set_child_exchange_target_after_success"] == 10
    assert [root["slot"] for root in roots] == [8, 9, 10]
    assert Decimal(str(plan["completed_reference_notional_usdc"])) == Decimal(
        "20.5480093663"
    )
    assert Decimal(
        str(plan["planned_total_root_child_reference_notional_usdc"])
    ) < Decimal("30.00")

    fresh_ids = {
        str(value)
        for root in roots
        for value in (
            root["root_client_order_id"],
            root["child_client_order_id"],
        )
    }
    burned_v13_ids = {
        *v13["planned_root_client_order_ids"],
        *v13["planned_child_client_order_ids"],
    }
    assert len(fresh_ids) == 6
    assert not fresh_ids & burned_v13_ids


def test_v14_execution_rows_never_enter_v13_recovery_scope() -> None:
    plan, roots = _validated_v14_plan()

    assert runner.current_execution_rows(plan) == roots
    assert [row["slot"] for row in runner.current_execution_rows(plan)] == [
        8,
        9,
        10,
    ]
    with_recovery = deepcopy(plan)
    with_recovery["recovery_slot_5"] = {"slot": 5}
    with pytest.raises(
        runner.ProofFailure,
        match="v14_recovery_or_execution_rows_present",
    ):
        runner.current_execution_rows(with_recovery)


def test_v14_sdk_ordinals_start_fresh_at_root_and_child_eight() -> None:
    plan, _ = _validated_v14_plan()

    assert not runner.successor_sdk_call_occurred(
        slot=8,
        attempt_kind="root",
        sdk_call_count=0,
        confirmed_plan=plan,
    )
    assert runner.successor_sdk_call_occurred(
        slot=8,
        attempt_kind="root",
        sdk_call_count=1,
        confirmed_plan=plan,
    )
    assert not runner.successor_sdk_call_occurred(
        slot=8,
        attempt_kind="child",
        sdk_call_count=0,
        confirmed_plan=plan,
    )
    assert runner.successor_sdk_call_occurred(
        slot=8,
        attempt_kind="child",
        sdk_call_count=1,
        confirmed_plan=plan,
    )


@pytest.mark.parametrize("attempt_kind", ["root", "child"])
def test_v14_cancel_handoff_accepts_only_exact_current_identity(
    attempt_kind: str,
) -> None:
    plan, roots = _validated_v14_plan()
    root = roots[0]
    client_order_id = str(
        root[
            "root_client_order_id"
            if attempt_kind == "root"
            else "child_client_order_id"
        ]
    )

    identity = runner._parent_cancel_handoff_identity(
        plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        slot=8,
        attempt_kind=attempt_kind,
        client_order_id=client_order_id,
    )

    assert identity["slot"] == 8
    assert identity["client_order_id"] == client_order_id
    assert identity["idempotency_key"] == (
        f"{plan['batch_id']}-{attempt_kind}-8-cancel"
    )
    with pytest.raises(runner.ProofFailure):
        runner._parent_cancel_handoff_identity(
            plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
            slot=7,
            attempt_kind=attempt_kind,
            client_order_id=client_order_id,
        )


def test_v14_plan_rejects_reuse_of_any_untransmitted_v13_suffix_identity() -> None:
    plan, _ = _validated_v14_plan()
    reused = deepcopy(plan)
    reused_id = runner.FAILED_SUCCESSOR_V13_PLANNED_ROOT_CLIENT_ORDER_IDS[2]
    reused["roots"][0]["root_client_order_id"] = reused_id
    reused["roots"][0]["order"]["client_order_id"] = reused_id
    reused["plan_sha256"] = runner.plan_hash(reused)

    with pytest.raises(runner.ProofFailure):
        runner.validate_v14_successor_live_plan(
            reused,
            expected_hash=str(reused["plan_sha256"]),
            preflight=_preflight(),
            **_bindings(),
        )


def test_v14_marker_carries_burned_v13_binding_and_exact_success_targets() -> None:
    plan, _ = _validated_v14_plan()
    marker = runner.build_v14_global_batch_marker_payload(
        runner.SUCCESSOR_V14_PLAN_PATH,
        confirmed_plan=plan,
        expected_hash=str(plan["plan_sha256"]),
        expected_runner_sha256=str(plan["runner_sha256"]),
        registered_at="2026-07-12T15:31:00+00:00",
        process_id=1,
    )

    assert marker["schema_version"] == "14"
    assert marker["authority"] == (
        "controlled-admin-spot-root-child-successor-v14-batch"
    )
    assert marker["remaining_attempt_count"] == 6
    assert marker["root_order_maximum"] == 3
    assert marker["child_order_maximum"] == 3
    assert marker["completed_root_order_count"] == 7
    assert marker["completed_child_order_count"] == 7
    assert marker["proof_set_root_exchange_target_after_success"] == 10
    assert marker["proof_set_child_exchange_target_after_success"] == 10
    assert marker["v13_binding"] == runner.offline_v13_binding_fixture()


def test_v14_registration_creates_owner_only_empty_ledger_once(
    tmp_path,
    monkeypatch,
) -> None:
    plan, _ = _validated_v14_plan()
    registry = tmp_path / "v14-registry"
    monkeypatch.setattr(runner, "GLOBAL_BATCH_REGISTRY_DIR", registry)

    marker_path, ledger_path = runner.initialize_global_batch_ledger(
        runner.SUCCESSOR_V14_PLAN_PATH,
        confirmed_plan=plan,
        expected_hash=str(plan["plan_sha256"]),
        expected_runner_sha256=str(plan["runner_sha256"]),
    )

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["authority"] == (
        "controlled-admin-spot-root-child-successor-v14-batch"
    )
    assert marker["attempt_ledger_path"] == str(ledger_path)
    assert ledger_path.read_bytes() == b""
    assert marker_path.stat().st_mode & 0o077 == 0
    assert ledger_path.stat().st_mode & 0o077 == 0
    with pytest.raises(
        runner.ProofFailure,
        match="global_batch_already_registered",
    ):
        runner.initialize_global_batch_ledger(
            runner.SUCCESSOR_V14_PLAN_PATH,
            confirmed_plan=plan,
            expected_hash=str(plan["plan_sha256"]),
            expected_runner_sha256=str(plan["runner_sha256"]),
        )


def test_v14_exact_six_entry_ledger_round_trips_without_writes() -> None:
    plan, roots = _validated_v14_plan()
    now = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, object]] = []
    for root in roots:
        slot = int(root["slot"])
        root_tuple = runner.approved_exact_root_tuple(plan, root)
        records.append(
            runner.build_batch_attempt_record(
                confirmed_plan=plan,
                confirmed_plan_hash=str(plan["plan_sha256"]),
                sequence=len(records) + 1,
                slot=slot,
                attempt_kind="root",
                exact_order_tuple=root_tuple,
                consumed_at=now,
                process_id=1,
            )
        )
        child_tuple = runner.build_child_order_tuple(
            plan,
            root,
            filled_size=Decimal(str(root["order"]["base_size"])),
            fresh_market={"best_bid": Decimal("64129.52"), "observed_at": now},
            price_increment=Decimal("0.01"),
        )
        records.append(
            runner.build_batch_attempt_record(
                confirmed_plan=plan,
                confirmed_plan_hash=str(plan["plan_sha256"]),
                sequence=len(records) + 1,
                slot=slot,
                attempt_kind="child",
                exact_order_tuple=child_tuple,
                consumed_at=now,
                process_id=1,
            )
        )

    raw = b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for record in records
    )
    validated = runner._parse_and_validate_attempt_ledger(
        raw,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
    )

    assert len(validated) == 6
    assert [
        (record["batch_slot"], record["attempt_kind"]) for record in validated
    ] == runner.v14_attempt_schedule()
    for attempt_kind in ("root", "child"):
        with pytest.raises(
            runner.ProofFailure,
            match=f"{attempt_kind}_sdk_call_maximum_exceeded",
        ):
            runner.authorized_sdk_tuple_for_call(
                validated,
                attempt_kind=attempt_kind,
                prior_call_count=3,
                confirmed_plan=plan,
            )
    with pytest.raises(runner.ProofFailure, match="attempt_count_exceeded"):
        runner._parse_and_validate_attempt_ledger(
            raw + raw.splitlines(keepends=True)[-1],
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
        )


def test_v14_runtime_authority_round_trips_complete_plan_without_io() -> None:
    plan, _ = _validated_v14_plan()
    state_dir = runner.Path("/offline/v14")
    auth_file = state_dir / runner.RUNTIME_CHILD_AUTH_FILENAME
    marker_path, ledger_path = runner.v14_batch_registry_paths(str(plan["batch_id"]))
    payload = runner.build_runtime_child_authority_payload(
        state_dir=state_dir,
        auth_file=auth_file,
        global_batch_marker=marker_path,
        global_batch_marker_sha256="a" * 64,
        attempt_ledger_path=ledger_path,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        confirmed_runner_sha256=str(plan["runner_sha256"]),
        parent_pid=123,
        parent_start_identity="456",
        nonce="nonce",
    )

    validated = runner.validate_runtime_child_authority_payload(
        payload,
        state_dir=state_dir,
        auth_file=auth_file,
        supplied_nonce="nonce",
        actual_parent_pid=123,
        actual_parent_start_identity="456",
    )

    assert validated == plan
    assert payload["backend_commit"] == runner.V14_EXPECTED_COMMIT
    assert len(json.dumps(payload, sort_keys=True).encode()) < 100_000

    tampered = deepcopy(payload)
    tampered_plan = deepcopy(plan)
    tampered_plan["roots"][0]["order"]["side"] = "SELL"
    tampered_plan["plan_sha256"] = runner.plan_hash(tampered_plan)
    tampered["confirmed_plan"] = tampered_plan
    tampered["plan_sha256"] = tampered_plan["plan_sha256"]
    with pytest.raises(
        runner.ProofFailure,
        match="runtime_child_v14_root_identity_mismatch",
    ):
        runner.validate_runtime_child_authority_payload(
            tampered,
            state_dir=state_dir,
            auth_file=auth_file,
            supplied_nonce="nonce",
            actual_parent_pid=123,
            actual_parent_start_identity="456",
        )


def test_v14_runtime_sentinel_binds_exact_generation_maxima() -> None:
    source = inspect.getsource(runner.AdminRuntime.sdk_boundary_sentinel)

    assert 'evidence.get("root_create_order_maximum")' in source
    assert "== self.root_order_maximum" in source
    assert 'evidence.get("child_place_limit_order_maximum")' in source
    assert "== self.child_order_maximum" in source
    assert "sdk_boundary_sentinel_generation_maximum_mismatch" in source


def test_v14_registration_and_cli_use_only_fixed_v14_paths() -> None:
    registration = inspect.getsource(runner.initialize_global_batch_ledger)
    main_source = inspect.getsource(runner.main)

    assert "SUCCESSOR_V14_PLAN_PATH" in registration
    assert "build_v14_global_batch_marker_payload" in registration
    assert "v14_batch_registry_paths" in registration
    assert "build_v14_successor_live_plan" in main_source
    assert "validate_v14_successor_live_plan" in main_source
    assert "execute_v14_controlled_batch" in main_source
    assert "SUCCESSOR_V14_PLAN_PATH" in main_source


def test_v14_keeps_child_cancel_http_200_as_the_only_success_path() -> None:
    source = inspect.getsource(runner.execute_controlled_batch)
    wrapper = inspect.getsource(runner.execute_v14_controlled_batch)

    assert "require(child_cancel_status == 200" in source
    assert "child_cancel_http_failed" in source
    assert "child_cancel_non_200_reconciliation" not in source
    assert "_validate_controlled_child_cancel_response" in source
    assert "return execute_controlled_batch(" in wrapper


def test_v14_offline_self_test_exposes_no_live_six_attempt_boundary() -> None:
    result = runner.run_offline_self_test()

    assert result["v14_attempt_schedule"] == runner.v14_attempt_schedule()
    assert result["v14_attempt_count"] == 6
    assert result["v14_root_order_maximum"] == 3
    assert result["v14_child_order_maximum"] == 3
    assert result["v14_completed_reference_notional_usdc"] == "20.5480093663"
    assert result["v14_all_v13_authority_burned"] is True
    assert result["live_coinbase_orders_ran"] is False
