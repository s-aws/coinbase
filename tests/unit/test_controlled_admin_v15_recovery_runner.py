"""No-live authority tests for the sealed V15R2 child-only recovery."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from tools import run_controlled_admin_spot_child_cancel_recovery as recovery


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _r1_fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    root_id = recovery.R1_ROOT_CLIENT_ORDER_ID
    child_id = recovery.R1_CHILD_CLIENT_ORDER_ID
    plan_path = tmp_path / "v15r1-plan.json"
    marker_path = tmp_path / "v15r1-marker.json"
    ledger_path = tmp_path / "v15r1-ledger.jsonl"
    sentinel_path = tmp_path / "v15r1-sentinel.json"
    audit_path = tmp_path / "v15r1-audit.jsonl"
    parent_loss_path = tmp_path / "v15r1-parent-loss.json"
    handoff_path = tmp_path / "v15r1-handoff.json"
    cancel_path = tmp_path / "v15r1-cancel.jsonl"
    backend_claim_path = tmp_path / "v15r1-backend-claims.jsonl"

    r1_plan = {
        "schema_version": "19",
        "authority_kind": "selected_chain_child_cancel_v15",
        "plan_sha256": recovery.R1_PLAN_SHA256,
        "batch_id": recovery.R1_BATCH_ID,
        "portfolio_id": recovery.TEST_PORTFOLIO_ID,
        "product_id": recovery.PRODUCT_ID,
        "root_reference_notional_usdc": "1.0103795104",
        "root": {
            "client_order_id": root_id,
            "order": {
                "client_order_id": root_id,
                "base_size": "0.00001583",
                "limit_price": "63826.88",
            },
        },
        "child": {
            "client_order_id": child_id,
            "parent_client_order_id": root_id,
        },
    }
    marker = {
        "authority": "selected_chain_child_cancel_v15",
        "plan_sha256": recovery.R1_PLAN_SHA256,
        "batch_id": recovery.R1_BATCH_ID,
        "root_client_order_id": root_id,
        "child_client_order_id": child_id,
        "placement_attempt_maximum": 2,
        "root_placement_maximum": 1,
        "child_placement_maximum": 1,
    }
    root_tuple = {
        "client_order_id": root_id,
        "base_size": "0.00001583",
        "limit_price": "63826.88",
    }
    child_tuple = {
        "batch_id": recovery.R1_BATCH_ID,
        "batch_slot": 1,
        "root_client_order_id": root_id,
        "client_order_id": child_id,
        "product_id": recovery.PRODUCT_ID,
        "side": "SELL",
        "base_size": "0.00001583",
        "limit_price": "108154.14",
        "post_only": False,
    }
    ledger = [
        {
            "schema_version": "1",
            "sequence": 1,
            "attempt_kind": "root",
            "batch_id": recovery.R1_BATCH_ID,
            "root_client_order_id": root_id,
            "client_order_id": root_id,
            "plan_sha256": recovery.R1_PLAN_SHA256,
            "exact_order_tuple": root_tuple,
        },
        {
            "schema_version": "1",
            "sequence": 2,
            "attempt_kind": "child",
            "batch_id": recovery.R1_BATCH_ID,
            "root_client_order_id": root_id,
            "client_order_id": child_id,
            "plan_sha256": recovery.R1_PLAN_SHA256,
            "exact_order_tuple": child_tuple,
        },
    ]
    sentinel = {
        "installed": True,
        "wrapper_identity_proven": True,
        "phase": "runtime_exited",
        "root_create_order_call_count": 1,
        "root_create_order_maximum": 1,
        "root_sdk_inflight": False,
        "child_place_limit_order_call_count": 0,
        "child_place_limit_order_maximum": 1,
        "child_sdk_inflight": False,
        "denied_call_count": 0,
        "critical_failure": False,
        "error": None,
    }
    fill_proof = {
        "collection": "spot_fill_readback_proofs",
        "key": recovery.R1_FILL_PROOF_KEY,
        "record": {
            "type": "admin_spot_order_fill_readback",
            "route": "/api/v1/orders/{client_order_id}/fill-readback",
            "client_order_id": root_id,
            "exchange_order_id": recovery.R1_ROOT_EXCHANGE_ORDER_ID,
            "order_status": "FILLED",
            "fill_read_status": "filled",
            "executed_notional_usdc": "1.0075796583",
            "fill_count": 1,
            "fill_order_id_matches_exchange_order_id": True,
            "fill_product_id_matches_order": True,
            "proof_recorded": True,
            "read_only": True,
            "live_coinbase_orders_ran": False,
        },
    }
    parent_loss = {
        "plan_sha256": recovery.R1_PLAN_SHA256,
        "status": "v15_parent_authority_lost_reconciliation_only",
        "authoritative_active_read_stable": True,
        "authoritative_active_orders": [],
        "new_sdk_placements_denied": True,
        "new_cancel_command_authorized": False,
        "root_create_order_call_count": 1,
        "child_place_limit_order_call_count": 0,
    }
    _write_json(plan_path, r1_plan)
    _write_json(marker_path, marker)
    _write_jsonl(ledger_path, ledger)
    _write_json(sentinel_path, sentinel)
    _write_jsonl(audit_path, [fill_proof])
    _write_json(parent_loss_path, parent_loss)
    cancel_path.touch(mode=0o600)
    backend_claim_path.touch(mode=0o600)

    paths = {
        "plan_path": str(plan_path),
        "marker_path": str(marker_path),
        "ledger_path": str(ledger_path),
        "sentinel_path": str(sentinel_path),
        "audit_path": str(audit_path),
        "parent_authority_loss_path": str(parent_loss_path),
        "handoff_path": str(handoff_path),
        "cancel_ledger_path": str(cancel_path),
        "backend_claim_log_path": str(backend_claim_path),
    }
    expected = {
        **paths,
        "plan_bytes_sha256": _sha256(plan_path),
        "marker_bytes_sha256": _sha256(marker_path),
        "ledger_bytes_sha256": _sha256(ledger_path),
        "sentinel_bytes_sha256": _sha256(sentinel_path),
        "audit_bytes_sha256": _sha256(audit_path),
        "parent_authority_loss_bytes_sha256": _sha256(parent_loss_path),
        "cancel_ledger_bytes_sha256": _sha256(cancel_path),
        "backend_claim_log_bytes_sha256": _sha256(backend_claim_path),
        "direct_fill_proof_canonical_sha256": recovery._canonical_json_sha256(
            fill_proof
        ),
    }
    return paths, expected


def _plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    paths, expected = _r1_fixture(tmp_path)
    monkeypatch.setattr(recovery, "R1_ARTIFACT_PATHS", paths)
    monkeypatch.setattr(recovery, "R1_EXPECTED_HASHES", expected)
    monkeypatch.setattr(recovery, "backend_commit", lambda: "a" * 40)
    monkeypatch.setattr(recovery, "frontend_commit", lambda: "b" * 40)
    monkeypatch.setattr(recovery, "runner_sha256", lambda: "c" * 64)
    binding = recovery.load_v15r1_recovery_binding()
    return recovery.build_v15r2_plan(
        binding,
        now=datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc),
        approval_id="controlled-child-cancel-v15r2-11111111-1111-4111-8111-111111111111",
    )


def test_v15r2_plan_is_child_only_disjoint_and_expires_in_120_minutes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)

    assert plan["authority_kind"] == recovery.AUTHORITY_KIND
    assert plan["placement_attempt_count"] == 1
    assert plan["placement_attempt_schedule"] == ["child"]
    assert plan["root_placement_maximum"] == 0
    assert plan["child_placement_maximum"] == 1
    assert plan["cancel_command_maximum"] == 1
    assert plan["root_placement_authorized"] is False
    assert "order" not in plan["root_evidence"]
    assert plan["root_evidence"]["client_order_id"] == recovery.R1_ROOT_CLIENT_ORDER_ID
    assert plan["child"]["client_order_id"] == recovery.R1_CHILD_CLIENT_ORDER_ID
    assert plan["cancel_command"]["identity_value"] == recovery.R1_ROOT_CLIENT_ORDER_ID
    assert plan["child_reveal_operator_intent"] == (
        "controlled_v15_test_profile_first_child_reveal"
    )
    assert plan["child_cancel_operator_intent"] == (
        "controlled_v15_test_profile_first_child_cancel"
    )
    assert plan["expires_at"] == "2026-07-13T04:00:00+00:00"
    assert Decimal(plan["child_submitted_cap_usdc"]) == Decimal("2.00")
    assert Decimal(plan["planned_reference_notional_usdc"]) < Decimal("12.00")
    assert Decimal(plan["conservative_reference_notional_usdc"]) < Decimal("12.00")
    assert plan["plan_sha256"] == recovery.plan_hash(plan)


def test_v15r2_binding_requires_exact_burned_plan_marker_two_rows_sentinel_and_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, expected = _r1_fixture(tmp_path)
    monkeypatch.setattr(recovery, "R1_ARTIFACT_PATHS", paths)
    monkeypatch.setattr(recovery, "R1_EXPECTED_HASHES", expected)

    binding = recovery.load_v15r1_recovery_binding()

    assert binding["r1_plan_sha256"] == recovery.R1_PLAN_SHA256
    assert binding["r1_attempt_count"] == 2
    assert binding["r1_root_sdk_call_count"] == 1
    assert binding["r1_child_sdk_call_count"] == 0
    assert binding["active_spot_order_count"] == 0
    assert binding["root_filled_size"] == "0.00001583"
    assert binding["root_filled_value"] == "1.0075796583"
    assert binding["handoff_absent"] is True
    assert binding["cancel_ledgers_empty"] is True

    marker = Path(paths["marker_path"])
    marker.write_text(marker.read_text() + " ", encoding="utf-8")
    with pytest.raises(recovery.ProofFailure, match="v15r1_artifact_hash_mismatch"):
        recovery.load_v15r1_recovery_binding()


def test_v15r2_plan_validation_rejects_root_authority_and_cap_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    recovery.validate_v15r2_plan(
        plan,
        expected_hash=plan["plan_sha256"],
        now=datetime(2026, 7, 13, 2, 1, tzinfo=timezone.utc),
    )

    broadened = deepcopy(plan)
    broadened["root_placement_maximum"] = 1
    broadened["plan_sha256"] = recovery.plan_hash(broadened)
    with pytest.raises(recovery.ProofFailure, match="v15r2_exact_scope_mismatch"):
        recovery.validate_v15r2_plan(
            broadened,
            expected_hash=broadened["plan_sha256"],
            now=datetime(2026, 7, 13, 2, 1, tzinfo=timezone.utc),
        )

    broader_cap = deepcopy(plan)
    broader_cap["child_submitted_cap_usdc"] = "2.01"
    broader_cap["plan_sha256"] = recovery.plan_hash(broader_cap)
    with pytest.raises(recovery.ProofFailure, match="v15r2_numeric_scope_mismatch"):
        recovery.validate_v15r2_plan(
            broader_cap,
            expected_hash=broader_cap["plan_sha256"],
            now=datetime(2026, 7, 13, 2, 1, tzinfo=timezone.utc),
        )


def test_v15r2_child_ledger_consumes_exactly_one_attempt_and_never_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    ledger = tmp_path / "r2-placements.jsonl"
    ledger.touch(mode=0o600)
    child_tuple = recovery.build_execution_child_order_tuple(
        plan,
        fresh_market={
            "best_bid": "63620.08",
            "observed_at": "2026-07-13T02:01:00+00:00",
        },
        price_increment=Decimal("0.01"),
    )

    row = recovery.consume_v15r2_child_attempt(
        ledger,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
        exact_order_tuple=child_tuple,
        consumed_at="2026-07-13T02:01:01+00:00",
        process_id=123,
    )

    assert row["sequence"] == 1
    assert row["attempt_kind"] == "child"
    assert row["client_order_id"] == recovery.R1_CHILD_CLIENT_ORDER_ID
    with pytest.raises(recovery.ProofFailure, match="v15r2_child_attempt_already_consumed"):
        recovery.consume_v15r2_child_attempt(
            ledger,
            plan=plan,
            plan_sha256=plan["plan_sha256"],
            exact_order_tuple=child_tuple,
            consumed_at="2026-07-13T02:01:02+00:00",
        )
    with pytest.raises(recovery.ProofFailure, match="v15r2_attempt_kind_not_child"):
        recovery.consume_v15r2_child_attempt(
            tmp_path / "another.jsonl",
            plan=plan,
            plan_sha256=plan["plan_sha256"],
            exact_order_tuple=child_tuple,
            attempt_kind="root",
        )


def test_v15r2_authorization_writes_only_disjoint_recovery_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    plan_path = tmp_path / "v15r2-plan.json"
    _write_json(plan_path, plan)
    marker = tmp_path / "v15r2-marker.json"
    ledger = tmp_path / "v15r2-placements.jsonl"
    cancel = tmp_path / "v15r2-cancel.jsonl"
    backend = tmp_path / "v15r2-backend.jsonl"
    handoff = tmp_path / "v15r2-handoff.json"

    authority = recovery.authorize_v15r2_execution(
        plan_path,
        expected_hash=plan["plan_sha256"],
        now=datetime(2026, 7, 13, 2, 1, tzinfo=timezone.utc),
        marker_path=marker,
        placement_ledger_path=ledger,
        cancel_ledger_path=cancel,
        backend_claim_log_path=backend,
        handoff_path=handoff,
    )

    assert authority["root_placement_maximum"] == 0
    assert authority["child_placement_maximum"] == 1
    assert authority["placement_attempt_maximum"] == 1
    assert marker.is_file()
    assert ledger.read_bytes() == cancel.read_bytes() == backend.read_bytes() == b""
    assert not handoff.exists()
    for path in (marker, ledger, cancel, backend):
        assert path.stat().st_mode & 0o077 == 0


def test_v15r2_execution_source_has_no_root_submission_and_handoff_precedes_child() -> None:
    import inspect

    source = inspect.getsource(recovery.execute_v15r2_plan)

    assert '"POST", "/orders"' not in source
    assert "create_order(" not in source
    assert "expected_root_create_order_calls={0}" in source
    assert 'attempt_kind="root"' not in source
    assert '"awaiting_operator_ui_root_scoped_cancel"' in source
    assert "claim_v15_cancel_command(" not in source
    assert "record_v15_cancel_outcome(" not in source
    assert source.index("write_v15r2_cancel_proof_handoff(") < source.index(
        "child_status, child_response, child_response_headers = runtime.request("
    )


def test_v15r2_cancel_context_uses_canonical_route_service_method(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)

    context, _ = recovery.build_v15r2_cancel_admission_context(
        plan, plan_sha256=plan["plan_sha256"]
    )

    assert context["identity_value"] == recovery.R1_ROOT_CLIENT_ORDER_ID
    assert context["service_method"] == (
        "cancel_order_fill_follow_up_child_by_root_client_order_id"
    )


def test_v15r2_monitor_requires_actual_single_child_row_and_exact_claim_triplet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    identity = recovery.v15r2_backend_claim_identity(
        plan, plan_sha256=plan["plan_sha256"]
    )
    placement = [{
        "sequence": 1,
        "attempt_kind": "child",
        "root_client_order_id": recovery.R1_ROOT_CLIENT_ORDER_ID,
        "client_order_id": recovery.R1_CHILD_CLIENT_ORDER_ID,
    }]
    rows = [
        {
            **identity,
            "event": "claim",
            "outcome": "claimed",
            "response": None,
            "reconciliation_required": False,
        },
        {
            **identity,
            "event": "exchange_boundary",
            "outcome": "unknown",
            "response": None,
            "reconciliation_required": True,
        },
        {
            **identity,
            "event": "outcome",
            "outcome": "accepted",
            "response": {"status": "accepted"},
            "reconciliation_required": False,
        },
    ]

    assert recovery.v15r2_operator_monitor_decision(
        placement,
        [],
        rows,
        expected_identity=identity,
        now=datetime(2026, 7, 13, 2, 1, tzinfo=timezone.utc),
        expires_at="2026-07-13T04:00:00+00:00",
    ) == "verify_terminal_closeout"
    with pytest.raises(
        recovery.ProofFailure, match="v15r2_monitor_placement_ledger_incomplete"
    ):
        recovery.v15r2_operator_monitor_decision(
            [{"sequence": 1, "attempt_kind": "root"}, *placement],
            [],
            rows,
            expected_identity=identity,
            now=datetime(2026, 7, 13, 2, 1, tzinfo=timezone.utc),
            expires_at="2026-07-13T04:00:00+00:00",
        )

    for prefix in (rows[:1], rows[:2]):
        assert recovery.v15r2_operator_monitor_decision(
            placement,
            [],
            prefix,
            expected_identity=identity,
            now=datetime(2026, 7, 13, 2, 1, tzinfo=timezone.utc),
            expires_at="2026-07-13T04:00:00+00:00",
        ) == "awaiting_operator_ui_root_scoped_cancel"


def test_v15r2_local_binding_queries_root_siblings_and_exact_child_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.index = -1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, params):
            self.calls.append((" ".join(query.split()), tuple(params)))
            self.index += 1

        def fetchone(self):
            return (
                ("FILLED", recovery.R1_ROOT_EXCHANGE_ORDER_ID, "corr", "audit"),
                ("PENDING", "0.00001583", None, "corr", "audit"),
                ("HIDDEN", "0", "0", [], {"reprice_history": []}),
            )[self.index]

        def fetchall(self):
            return []

    cursor = FakeCursor()

    class FakeConnection:
        def cursor(self):
            return cursor

        def close(self):
            return None

    monkeypatch.setattr(
        recovery.psycopg2,
        "connect",
        lambda **_kwargs: FakeConnection(),
    )

    binding = recovery.read_local_hidden_child_binding()

    assert binding["direct_child_client_order_ids"] == []
    assert binding["nested_child_client_order_ids"] == []
    direct_query, direct_params = cursor.calls[3]
    nested_query, nested_params = cursor.calls[4]
    assert "parent_order_id=%s AND client_order_id<>%s" in direct_query
    assert direct_params == (
        recovery.R1_ROOT_CLIENT_ORDER_ID,
        recovery.R1_CHILD_CLIENT_ORDER_ID,
    )
    assert "parent_order_id=%s" in nested_query
    assert nested_params == (recovery.R1_CHILD_CLIENT_ORDER_ID,)


def test_v15r2_exchange_identity_absence_requires_complete_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery.base,
        "read_failed_v6_v7_order_catalog",
        lambda _client: (
            [{"client_order_id": "unrelated"}],
            {"authoritative": True, "pagination_complete": True},
        ),
    )
    evidence = recovery.prove_v15r2_child_exchange_identity_absent(object())
    assert evidence["matching_orders"] == []

    monkeypatch.setattr(
        recovery.base,
        "read_failed_v6_v7_order_catalog",
        lambda _client: (
            [{"client_order_id": recovery.R1_CHILD_CLIENT_ORDER_ID}],
            {"authoritative": True, "pagination_complete": True},
        ),
    )
    with pytest.raises(
        recovery.ProofFailure,
        match="v15r2_child_exchange_identity_absence_unproven",
    ):
        recovery.prove_v15r2_child_exchange_identity_absent(object())


def test_v15r2_prepare_does_not_create_marker_ledger_runtime_or_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, expected = _r1_fixture(tmp_path)
    monkeypatch.setattr(recovery, "R1_ARTIFACT_PATHS", paths)
    monkeypatch.setattr(recovery, "R1_EXPECTED_HASHES", expected)
    monkeypatch.setattr(recovery, "backend_commit", lambda: "a" * 40)
    monkeypatch.setattr(recovery, "frontend_commit", lambda: "b" * 40)
    monkeypatch.setattr(recovery, "runner_sha256", lambda: "c" * 64)
    monkeypatch.setattr(
        recovery,
        "read_local_hidden_child_binding",
        lambda: recovery.validate_local_hidden_child_binding(
            {
                "root_client_order_id": recovery.R1_ROOT_CLIENT_ORDER_ID,
                "root_status": "FILLED",
                "root_exchange_order_id": recovery.R1_ROOT_EXCHANGE_ORDER_ID,
                "root_correlation_id": "sealed-root-correlation",
                "root_audit_id": "sealed-root-audit",
                "child_client_order_id": recovery.R1_CHILD_CLIENT_ORDER_ID,
                "child_parent_status": "PENDING",
                "child_size": "0.00001583",
                "child_exchange_order_id": None,
                "child_correlation_id": "sealed-root-correlation",
                "child_audit_id": "sealed-root-audit",
                "child_stealth_status": "HIDDEN",
                "revealed_size": "0",
                "executed_size": "0",
                "revealed_orders": [],
                "active_placement_client_order_id": None,
                "active_exchange_order_id": None,
                "preexisting_controlled_preparation_present": False,
                "direct_child_client_order_ids": [],
                "nested_child_client_order_ids": [],
            }
        ),
    )
    plan_path = tmp_path / "v15r2-plan.json"
    marker = tmp_path / "v15r2-marker.json"
    ledger = tmp_path / "v15r2-ledger.jsonl"
    handoff = tmp_path / "v15r2-handoff.json"

    result = recovery.prepare_v15r2_plan(
        plan_path=plan_path,
        marker_path=marker,
        placement_ledger_path=ledger,
        handoff_path=handoff,
        now=datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc),
        require_clean_environment=False,
    )

    assert result["status"] == "prepared"
    assert plan_path.is_file()
    assert plan_path.stat().st_mode & 0o077 == 0
    assert not marker.exists()
    assert not ledger.exists()
    assert not handoff.exists()
    assert result["live_coinbase_orders_ran"] is False
    assert result["live_coinbase_read_ran"] is False
    assert result["runtime_started"] is False
