"""Focused topology and sealed-artifact tests for the controlled v9 runner."""

import inspect
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

import pytest

from tools import run_controlled_admin_spot_root_child_batch as runner


EXPECTED_PRODUCTION_COMMIT = "8c2f0ad0474b24988bccda1862193690f897cd24"
EXPECTED_V9_AUTHORITY_PARENT = "47e812f6eaa5421a491fd3a7787e03ddab99c7a8"
V8_ROOT_ID = "12a52c06-e368-5c39-bfa0-6eb5880f3c64"
V8_CHILD_ID = "252b6389-d544-58db-a796-e9bc258f794f"
V8_PREPARATION_SHA256 = (
    "af16bf8f7867c3f8a385b0d0cef31371d4381289cc1fd7a58e81c29102d783a9"
)
V8_ROOT_EXCHANGE_ORDER_ID = "2ed7d436-b16e-4a7e-b0af-cb8f8bb86e68"
EXPECTED_V9_SCHEDULE = [
    (2, "child"),
    *[
        item
        for slot in range(3, 11)
        for item in ((slot, "root"), (slot, "child"))
    ],
]


def _preflight() -> dict:
    return {
        "portfolio_id": runner.TEST_PORTFOLIO_ID,
        "wallets": {"USDC": Decimal("993"), "BTC": Decimal("0.00005364")},
        "product": {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
        },
        "best_bid": Decimal("64143.89"),
        "best_ask": Decimal("64143.90"),
        "market": {
            "product_id": runner.PRODUCT_ID,
            "source": "coinbase_rest_get_best_bid_ask_exact_product",
            "observed_at": "2026-07-12T05:00:00+00:00",
        },
    }


def _bindings() -> dict:
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
    }


def _validated_v9_plan() -> tuple[dict[str, Any], list[dict[str, Any]]]:
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


def _client_order_ids(value: Any, *, key: str = "") -> set[str]:
    """Collect every v8 client-order identity, including burned arrays."""

    if isinstance(value, Mapping):
        collected: set[str] = set()
        for child_key, child_value in value.items():
            collected |= _client_order_ids(child_value, key=str(child_key))
        return collected
    if isinstance(value, (list, tuple)):
        collected = set()
        for child_value in value:
            collected |= _client_order_ids(child_value, key=key)
        return collected
    if "client_order_id" in key and value:
        return {str(value)}
    return set()


def test_v9_fixed_authority_and_attempt_schedule() -> None:
    assert runner.EXPECTED_COMMIT == EXPECTED_PRODUCTION_COMMIT
    assert (
        runner.V9_RUNNER_AUTHORITY_PARENT_COMMIT
        == EXPECTED_V9_AUTHORITY_PARENT
    )
    assert runner.PLAN_SCHEMA_VERSION == "13"
    assert runner.SUCCESSOR_V9_PLAN_PATH.name.endswith(
        "successor-v9-20260712.plan.json"
    )
    assert runner.GLOBAL_BATCH_MARKER_FILENAME.endswith(
        "successor-v9-20260712.authority.json"
    )
    assert runner.GLOBAL_BATCH_LEDGER_FILENAME.endswith(
        "successor-v9-20260712.attempts.jsonl"
    )
    assert runner.SUCCESSOR_ROOT_ORDER_MAXIMUM == 8
    assert runner.SUCCESSOR_CHILD_ORDER_MAXIMUM == 9
    assert runner.SUCCESSOR_ATTEMPT_COUNT == 17
    schedule = runner.successor_attempt_schedule()
    assert schedule == EXPECTED_V9_SCHEDULE
    assert len(schedule) == runner.SUCCESSOR_ATTEMPT_COUNT == 17
    assert [slot for slot, kind in schedule if kind == "root"] == list(
        range(3, 11)
    )
    assert [slot for slot, kind in schedule if kind == "child"] == list(
        range(2, 11)
    )
    assert len({attempt for attempt in schedule}) == len(schedule)
    assert runner.FAILED_SUCCESSOR_V8_APPROVAL_ID in (
        runner.prior_authority_approval_ids()
    )
    assert runner.FAILED_SUCCESSOR_V8_BATCH_ID in (
        runner.prior_authority_batch_ids()
    )


def test_v8_consumed_artifacts_are_exactly_sealed() -> None:
    expected = runner.offline_v8_binding_fixture()
    observed = runner.load_v8_binding()

    assert observed == expected
    assert observed["plan_sha256"] == (
        "815a2e2ad8210cebc370bc2bf29852be20862a5602c6e37c68513ed89f4f80bf"
    )
    assert observed["attempt_count"] == 2
    assert observed["root_sdk_call_count"] == 1
    assert observed["child_sdk_call_count"] == 0
    assert observed["slot_2_root_client_order_id"] == V8_ROOT_ID
    assert observed["slot_2_child_client_order_id"] == V8_CHILD_ID
    assert observed["slot_2_root_exchange_order_id"] == (
        V8_ROOT_EXCHANGE_ORDER_ID
    )
    assert observed["slot_2_prior_preparation_sha256"] == (
        V8_PREPARATION_SHA256
    )
    assert len(observed["burned_root_client_order_ids"]) == 8
    assert len(observed["burned_child_client_order_ids"]) == 8
    assert observed["planned_root_client_order_ids"][0] == V8_ROOT_ID
    assert observed["planned_child_client_order_ids"][0] == V8_CHILD_ID
    assert observed["burned_root_client_order_ids"] == (
        observed["planned_root_client_order_ids"][1:]
    )
    assert observed["burned_child_client_order_ids"] == (
        observed["planned_child_client_order_ids"][1:]
    )


def test_v9_plan_carries_only_v8_root_two_and_fresh_slots_three_to_ten() -> None:
    plan, roots = _validated_v9_plan()

    assert [root["slot"] for root in roots] == list(range(3, 11))
    assert plan["remaining_attempt_count"] == 17
    assert plan["new_root_order_maximum"] == 8
    assert plan["child_order_maximum"] == 9
    assert len(roots) == runner.SUCCESSOR_ROOT_ORDER_MAXIMUM
    carried = plan["recovery_slot_2"]
    assert carried["slot"] == 2
    assert carried["root_client_order_id"] == V8_ROOT_ID
    assert carried["child_client_order_id"] == V8_CHILD_ID
    assert carried["root_exchange_order_id"] == V8_ROOT_EXCHANGE_ORDER_ID
    assert carried["root_placement_authorized"] is False
    assert carried["child_recovery_authorized"] is True
    assert carried["controlled_prior_preparation_sha256"] == (
        V8_PREPARATION_SHA256
    )
    assert set(carried["proof_approval_ids"]) == {
        "child_reveal",
        "child_cancel",
    }
    assert "order" not in carried
    assert "root_place" not in carried["proof_approval_ids"]
    assert "root_cancel" not in carried["proof_approval_ids"]
    with pytest.raises(runner.ProofFailure):
        runner.approved_exact_successor_root_tuple(plan, carried)
    assert all(root["root_placement_authorized"] is True for root in roots)
    assert all("controlled_prior_preparation_sha256" not in root for root in roots)
    assert all(
        "controlled_prior_preparation_sha256" not in root["order"]
        for root in roots
    )
    fresh_ids = {
        value
        for root in roots
        for value in (
            root["root_client_order_id"],
            root["child_client_order_id"],
        )
    }
    assert len(fresh_ids) == 2 * runner.SUCCESSOR_ROOT_ORDER_MAXIMUM == 16
    v8 = plan["v8_binding"]
    all_v8_client_order_ids = _client_order_ids(v8)
    assert V8_ROOT_ID in all_v8_client_order_ids
    assert V8_CHILD_ID in all_v8_client_order_ids
    assert not fresh_ids & all_v8_client_order_ids
    assert not fresh_ids & {V8_ROOT_ID, V8_CHILD_ID}
    assert plan["v8_inherited_root_reference_notional_usdc"] == "1.1001110618"
    assert plan["completed_inherited_reference_notional_usdc"] == "2.8571692621"
    assert plan["total_inherited_reference_notional_usdc"] == "3.9572803239"
    assert Decimal(plan["planned_total_root_child_reference_notional_usdc"]) < 30


def test_v9_execution_binds_recovery_hash_before_first_child_ledger_and_http() -> None:
    source = inspect.getsource(runner.execute_controlled_batch)

    child_body_start = source.index("child_reveal_body = {")
    child_body_end = source.index("\n            }", child_body_start)
    assert (
        "controlled_prior_preparation_sha256"
        not in source[child_body_start:child_body_end]
    )

    recovery_gate = source.index("if slot == 2:", child_body_end)
    recovery_hash = source.index(
        '"controlled_prior_preparation_sha256": '
        "V8_SLOT_2_PRIOR_PREPARATION_SHA256"
    )
    fresh_root_gate = source.index("if slot >= 3:", recovery_hash)
    compact_fresh_gate = "".join(
        source[fresh_root_gate:].split()
    )
    assert (
        '"controlled_prior_preparation_sha256"notinchild_reveal_body'
        in compact_fresh_gate
    )
    child_ledger = source.index("child_attempt = consume_batch_attempt(")
    child_http = source.index(
        "child_status_code, child_response, child_headers = runtime.request("
    )

    assert (
        child_body_end
        < recovery_gate
        < recovery_hash
        < fresh_root_gate
        < child_ledger
        < child_http
    )


def test_v9_sdk_ordinals_start_with_recovery_child_not_root_two() -> None:
    assert runner.successor_sdk_call_occurred(
        slot=2,
        attempt_kind="child",
        sdk_call_count=1,
    )
    assert not runner.successor_sdk_call_occurred(
        slot=3,
        attempt_kind="root",
        sdk_call_count=0,
    )
    assert runner.successor_sdk_call_occurred(
        slot=3,
        attempt_kind="root",
        sdk_call_count=1,
    )
    with pytest.raises(runner.ProofFailure):
        runner.successor_sdk_call_occurred(
            slot=2,
            attempt_kind="root",
            sdk_call_count=0,
        )


def test_child_failure_cleanup_never_cancels_authoritative_absence() -> None:
    absent = {
        "authoritative": True,
        "pagination_complete": True,
        "confirmed_absent": True,
        "exact_identity_match": False,
        "matched_order": None,
        "exchange_order_id": None,
        "authoritative_status": None,
    }
    assert runner.recovery_child_cleanup_decision(
        child_sdk_call_occurred=False,
        authoritative_readback=absent,
    ) == "cancel_not_required_preplacement_absence"
    assert runner.recovery_child_cleanup_decision(
        child_sdk_call_occurred=True,
        authoritative_readback=absent,
    ) == "preserve_runtime_sdk_call_absence_ambiguous"


def test_child_failure_cleanup_cancels_only_exact_active_identity() -> None:
    active = {
        "authoritative": True,
        "pagination_complete": True,
        "confirmed_absent": False,
        "exact_identity_match": True,
        "matched_order": {"order_id": "exchange-child"},
        "exchange_order_id": "exchange-child",
        "authoritative_status": "OPEN",
    }
    terminal = {**active, "authoritative_status": "CANCELLED"}
    assert runner.recovery_child_cleanup_decision(
        child_sdk_call_occurred=True,
        authoritative_readback=active,
    ) == "issue_same_idempotent_exact_child_cancel"
    assert runner.recovery_child_cleanup_decision(
        child_sdk_call_occurred=True,
        authoritative_readback=terminal,
    ) == "cancel_not_required_already_terminal"


def test_v9_commit_scope_allows_only_runner_and_focused_test() -> None:
    production = "a" * 40
    head = "b" * 40
    runner_path = "tools/run_controlled_admin_spot_root_child_batch.py"
    digest = "c" * 64
    topology = runner.validate_runner_commit_topology(
        production_commit=production,
        head_commit=head,
        head_parents=[production],
        changed_paths=[runner.V9_RUNNER_TEST_PATH, runner_path],
        runner_path=runner_path,
        committed_runner_sha256=digest,
        working_runner_sha256=digest,
        additional_allowed_paths=(runner.V9_RUNNER_TEST_PATH,),
    )
    assert topology["scoped_commit_proven"] is True
    assert topology["runner_only_commit_proven"] is False
    with pytest.raises(runner.ProofFailure):
        runner.validate_runner_commit_topology(
            production_commit=production,
            head_commit=head,
            head_parents=[production],
            changed_paths=[runner.V9_RUNNER_TEST_PATH, runner_path, "other.py"],
            runner_path=runner_path,
            committed_runner_sha256=digest,
            working_runner_sha256=digest,
            additional_allowed_paths=(runner.V9_RUNNER_TEST_PATH,),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("root_client_order_id", "00000000-0000-0000-0000-000000000001"),
        ("child_client_order_id", "00000000-0000-0000-0000-000000000002"),
        ("root_exchange_order_id", "00000000-0000-0000-0000-000000000003"),
        ("controlled_prior_preparation_sha256", "0" * 64),
        ("root_placement_authorized", True),
        ("recovery_batch_id", "00000000-0000-0000-0000-000000000004"),
    ],
)
def test_v9_plan_rejects_every_recovery_authority_tamper(
    field: str,
    value: Any,
) -> None:
    preflight = _preflight()
    bindings = _bindings()
    plan = runner.build_successor_live_plan(preflight, **bindings)
    tampered = json.loads(json.dumps(plan))
    tampered["recovery_slot_2"][field] = value
    tampered["plan_sha256"] = runner.plan_hash(tampered)
    with pytest.raises(runner.ProofFailure):
        runner.validate_successor_live_plan(
            tampered,
            expected_hash=str(tampered["plan_sha256"]),
            preflight=preflight,
            **bindings,
        )


def test_v9_ledger_first_record_is_recovery_child_and_root_two_is_denied() -> None:
    plan, _ = _validated_v9_plan()
    recovery = plan["recovery_slot_2"]
    child_tuple = runner.build_child_order_tuple(
        plan,
        recovery,
        filled_size=runner.V8_SLOT_2_ROOT_FILLED_SIZE,
        fresh_market={
            "best_bid": Decimal("64143.89"),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        price_increment=Decimal("0.01"),
    )
    record = runner.build_batch_attempt_record(
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        sequence=1,
        slot=2,
        attempt_kind="child",
        exact_order_tuple=child_tuple,
        consumed_at=datetime.now(timezone.utc).isoformat(),
        process_id=1,
    )
    assert (record["sequence"], record["batch_slot"], record["attempt_kind"]) == (
        1,
        2,
        "child",
    )
    assert record["client_order_id"] == V8_CHILD_ID
    with pytest.raises(runner.ProofFailure):
        runner.build_batch_attempt_record(
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
            sequence=1,
            slot=2,
            attempt_kind="root",
            exact_order_tuple=child_tuple,
            consumed_at=datetime.now(timezone.utc).isoformat(),
            process_id=1,
        )


@pytest.mark.parametrize(
    (
        "child_sdk_calls",
        "child_exchange_state",
        "local_phase",
        "expected_safe",
    ),
    [
        (0, "absent", "v8_prepared_hidden", True),
        (1, "absent", "v9_superseded_preplacement_hidden", False),
        (1, "active", "v9_superseded_preplacement_hidden", False),
        (1, "cancelled", "v9_recovered_zero_fill_cancelled", True),
    ],
)
def test_recovery_failure_reconciliation_is_fail_closed_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
    child_sdk_calls: int,
    child_exchange_state: str,
    local_phase: str,
    expected_safe: bool,
) -> None:
    plan, _ = _validated_v9_plan()
    recovery = plan["recovery_slot_2"]
    child_tuple = runner.build_child_order_tuple(
        plan,
        recovery,
        filled_size=runner.V8_SLOT_2_ROOT_FILLED_SIZE,
        fresh_market={
            "best_bid": Decimal("64143.89"),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        price_increment=Decimal("0.01"),
    )
    ledger = [
        {
            "attempt_kind": "child",
            "root_client_order_id": V8_ROOT_ID,
            "client_order_id": V8_CHILD_ID,
            "exact_order_tuple": child_tuple,
        }
    ]

    class FakeRuntime:
        confirmed_plan = plan
        confirmed_plan_hash = str(plan["plan_sha256"])
        attempt_ledger_path = runner.Path("/offline/v9.attempts.jsonl")
        portfolio_id = runner.TEST_PORTFOLIO_ID
        live_service_disable_proven = False
        exchange_safe_to_shutdown = False

        def sdk_boundary_sentinel(self) -> dict[str, Any]:
            return {
                "root_create_order_call_count": 0,
                "child_place_limit_order_call_count": child_sdk_calls,
                "denied_call_count": 0,
                "root_sdk_inflight": False,
                "child_sdk_inflight": False,
            }

        def headers(self, **_kwargs: Any) -> dict[str, str]:
            return {}

        def request(self, *_args: Any, **_kwargs: Any) -> tuple[int, dict, dict]:
            return 200, {"total_inflight": 0}, {}

    runtime = FakeRuntime()

    def disable_service(fake_runtime: FakeRuntime, *, enabled: bool) -> None:
        assert enabled is False
        fake_runtime.live_service_disable_proven = True

    root_order = {
        "client_order_id": V8_ROOT_ID,
        "order_id": V8_ROOT_EXCHANGE_ORDER_ID,
        "status": "FILLED",
        "filled_size": str(runner.V8_SLOT_2_ROOT_FILLED_SIZE),
    }
    root_readback = {
        "authoritative": True,
        "pagination_complete": True,
        "exact_identity_match": True,
        "confirmed_absent": False,
        "authoritative_status": "FILLED",
        "matched_order": root_order,
        "exchange_order_id": V8_ROOT_EXCHANGE_ORDER_ID,
    }
    if child_exchange_state == "absent":
        child_readback = {
            "authoritative": True,
            "pagination_complete": True,
            "exact_identity_match": False,
            "confirmed_absent": True,
            "authoritative_status": None,
            "matched_order": None,
            "exchange_order_id": None,
        }
    else:
        status = "OPEN" if child_exchange_state == "active" else "CANCELLED"
        child_order = {
            "client_order_id": V8_CHILD_ID,
            "order_id": "exchange-child-v9",
            "status": status,
            "filled_size": "0",
        }
        child_readback = {
            "authoritative": True,
            "pagination_complete": True,
            "exact_identity_match": True,
            "confirmed_absent": False,
            "authoritative_status": status,
            "matched_order": child_order,
            "exchange_order_id": "exchange-child-v9",
        }

    def exact_readback(_client: Any, *, client_order_id: str, **_kwargs: Any) -> dict:
        return root_readback if client_order_id == V8_ROOT_ID else child_readback

    monkeypatch.setattr(runner, "set_live_service", disable_service)
    monkeypatch.setattr(runner, "read_batch_attempt_ledger", lambda *_a, **_k: ledger)
    monkeypatch.setattr(
        runner,
        "read_authoritative_spot_nonterminal_orders",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        runner,
        "prove_local_scope_with_historical_hidden_child",
        lambda **_kwargs: {
            "recovery_slot_2_chain": {"phase": local_phase}
        },
    )
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
    from application.admin_api import command_service

    monkeypatch.setattr(command_service, "exact_coinbase_order_readback", exact_readback)
    summary: dict[str, Any] = {}
    evidence = runner.reconcile_failure_state(
        runtime,
        rest_client=object(),
        summary=summary,
        current_root_client_order_id=V8_ROOT_ID,
    )
    assert evidence["safe_to_shutdown"] is expected_safe
    assert runtime.exchange_safe_to_shutdown is expected_safe
    if child_sdk_calls == 1 and child_exchange_state == "absent":
        assert evidence["recovery_child_cleanup_decision"] == (
            "preserve_runtime_sdk_call_absence_ambiguous"
        )


def test_inherited_absence_helpers_forward_exact_recovery_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _ = _validated_v9_plan()
    recovery = plan["recovery_slot_2"]
    observed: list[Mapping[str, Any] | None] = []

    def local_scope(**kwargs: Any) -> dict[str, Any]:
        observed.append(kwargs.get("recovery_slot_2"))
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
    from application.admin_api import command_service

    monkeypatch.setattr(
        command_service,
        "exact_coinbase_order_readback",
        lambda *_args, **_kwargs: {
            "authoritative": True,
            "pagination_complete": True,
            "confirmed_absent": True,
            "exact_identity_match": False,
            "exchange_order_id": None,
            "matched_order": None,
        },
    )
    runner.prove_failed_v5_root_2_absence(
        object(),
        recovery_slot_2=recovery,
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
    runner.prove_failed_v6_v7_client_ids_absent(
        object(),
        recovery_slot_2=recovery,
    )
    assert observed == [recovery, recovery]
