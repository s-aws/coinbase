"""No-live authority tests for the sealed V15R3 cancel-only recovery."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import signal
from pathlib import Path

import pytest

from application.admin_api import root_child_cancel as cancel_authority
from tools import run_controlled_admin_spot_child_cancel_recovery_v15r4 as recovery


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


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _active_binding() -> dict[str, object]:
    return {
        "root_client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        "root_status": "FILLED",
        "root_exchange_order_id": recovery.ROOT_EXCHANGE_ORDER_ID,
        "root_correlation_id": "d85733d6-51af-5fd9-b287-6bddc4e547a4",
        "root_audit_id": "6089e672-8c15-4b9b-9645-41a78170d4d5",
        "child_client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "child_parent_status": "OPEN",
        "child_size": "0.00001583",
        "child_limit_price": "107702.14",
        "child_exchange_order_id": recovery.CHILD_EXCHANGE_ORDER_ID,
        "child_correlation_id": "d85733d6-51af-5fd9-b287-6bddc4e547a4",
        "child_audit_id": "6089e672-8c15-4b9b-9645-41a78170d4d5",
        "child_stealth_status": "REVEALED",
        "revealed_size": "0.00001583",
        "executed_size": "0",
        "remaining_size": "0",
        "active_placement_client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "active_exchange_order_id": recovery.CHILD_EXCHANGE_ORDER_ID,
        "active_exchange_price": "107702.14",
        "controlled_plan_sha256": recovery.R2_PLAN_SHA256,
        "controlled_batch_id": recovery.R2_BATCH_ID,
        "reference_notional_usdc": "1.7049248762",
        "direct_child_client_order_ids": [],
        "nested_child_client_order_ids": [],
    }


def _fake_process_identity(process_id: int) -> dict[str, object]:
    return {
        "process_id": process_id,
        "start_identity": "111" if process_id == 1234 else "222",
        "uid": os.getuid(),
        "cwd": str(recovery.ROOT),
        "cwd_sha256": hashlib.sha256(str(recovery.ROOT).encode()).hexdigest(),
        "cmdline_sha256": ("a" if process_id == 1234 else "b") * 64,
    }


def _r2_fixture(tmp_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    plan_path = tmp_path / "v15r2-plan.json"
    marker_path = tmp_path / "v15r2-marker.json"
    placement_path = tmp_path / "v15r2-placement.jsonl"
    cancel_path = tmp_path / "v15r2-cancel.jsonl"
    claim_path = tmp_path / "v15r2-claims.jsonl"
    handoff_path = tmp_path / "v15r2-handoff.json"
    sentinel_path = tmp_path / "v15r2-sentinel.json"
    progress_path = tmp_path / "v15r2-progress.json"
    idempotency_path = tmp_path / "v15r2-idempotency.jsonl"
    audit_path = tmp_path / "v15r2-audit.jsonl"
    runtime_authority_path = tmp_path / "runtime-child-authority.json"
    runtime_authority_used_path = tmp_path / "runtime-child-authority.used.json"
    runtime_pid_path = tmp_path / "embedded-runtime.pid"

    old_cancel = {
        "idempotency_key": recovery.R2_CANCEL_IDEMPOTENCY_KEY,
        "payload_hash": recovery.R2_FAILED_CANCEL_PAYLOAD_HASH,
        "client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        "stealth_order_id": None,
        "status": "not_implemented",
        "response": {
            "status": "not_implemented",
            "message": "Root-scoped first-child cancel admission is blocked.",
            "client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
            "idempotency_key": recovery.R2_CANCEL_IDEMPOTENCY_KEY,
            "audit_id": recovery.R2_FAILED_CANCEL_AUDIT_ID,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "failure_stage": "approval",
            "admission_decision": {
                "payload_hash": recovery.R2_FAILED_CANCEL_PAYLOAD_HASH,
                "allowed": False,
                "blockers": ["approval_snapshot_missing"],
            },
        },
        "actor_id": recovery.ACTOR_ID,
        "endpoint": recovery.R2_CONCRETE_CANCEL_ENDPOINT,
    }
    old_audit = {
        "audit_id": recovery.R2_FAILED_CANCEL_AUDIT_ID,
        "recorded_at": "2026-07-13T02:28:40.703927+00:00",
        "actor_id": recovery.ACTOR_ID,
        "endpoint": recovery.R2_CONCRETE_CANCEL_ENDPOINT,
        "operator_intent": recovery.CANCEL_OPERATOR_INTENT,
        "idempotency_key": recovery.R2_CANCEL_IDEMPOTENCY_KEY,
        "status": "not_implemented",
        "failure_stage": "approval",
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "admission_decision": {
            "payload_hash": recovery.R2_FAILED_CANCEL_PAYLOAD_HASH,
            "allowed": False,
        },
    }
    successful_child = {
        "idempotency_key": "de6ee9e1-c8a6-5972-9d31-955b5d0422f9",
        "payload_hash": "ba2c3c7e6adf8c027c590d498185dc661b670f1b1420f06245892dafafa93538",
        "status": "accepted",
        "response": {
            "status": "accepted",
            "audit_id": "c08ead60-0436-40a7-8a99-1eff0e48dbb0",
            "live_exchange_submitted": True,
            "live_coinbase_orders_ran": True,
            "data": {
                "submission_attempt": {
                    "placed_client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
                    "exchange_order_id": recovery.CHILD_EXCHANGE_ORDER_ID,
                    "reference_notional_usdc": "1.7049248762",
                    "controlled_plan_sha256": recovery.R2_PLAN_SHA256,
                },
                "submission_readback": {
                    "authoritative": True,
                    "exact_identity_match": True,
                    "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
                    "exchange_order_id": recovery.CHILD_EXCHANGE_ORDER_ID,
                    "authoritative_status": "OPEN",
                    "matched_order": {
                        "filled_size": "0",
                        "filled_value": "0",
                        "number_of_fills": "0",
                    },
                },
            },
        },
        "actor_id": recovery.ACTOR_ID,
        "endpoint": (
            "POST /api/v1/stealth/orders/"
            f"{recovery.CHILD_CLIENT_ORDER_ID}/reveal"
        ),
    }
    plan = {
        "schema_version": "20",
        "authority_kind": "selected_chain_child_cancel_recovery_v15r2",
        "plan_sha256": recovery.R2_PLAN_SHA256,
        "batch_id": recovery.R2_BATCH_ID,
        "portfolio_id": recovery.TEST_PORTFOLIO_ID,
        "product_id": recovery.PRODUCT_ID,
        "placement_attempt_count": 1,
        "placement_attempt_schedule": ["child"],
        "root_placement_maximum": 0,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "root_actual_reference_notional_usdc": "1.0075796583",
        "planned_reference_notional_usdc": "3.0075796583",
        "slice_reference_cap_usdc": "12.00",
        "root_evidence": {
            "client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
            "exchange_order_id": recovery.ROOT_EXCHANGE_ORDER_ID,
            "status": "FILLED",
            "filled_value": "1.0075796583",
        },
        "child": {
            "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
            "parent_client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        },
        "cancel_command": {
            "idempotency_key": recovery.R2_CANCEL_IDEMPOTENCY_KEY,
            "correlation_id": recovery.R2_CANCEL_CORRELATION_ID,
            "claim_id": recovery.R2_CANCEL_CLAIM_ID,
            "approval_snapshot_id": recovery.R2_CANCEL_APPROVAL_ID,
            "cap_guard_decision_id": recovery.R2_CANCEL_CAP_ID,
            "reconciliation_plan_id": recovery.R2_CANCEL_RECONCILIATION_ID,
        },
    }
    marker = {
        "authority": "selected_chain_child_cancel_recovery_v15r2",
        "plan_sha256": recovery.R2_PLAN_SHA256,
        "batch_id": recovery.R2_BATCH_ID,
        "root_client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "placement_attempt_maximum": 1,
        "root_placement_maximum": 0,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "process_id": 1234,
    }
    child_tuple = {
        "batch_id": recovery.R2_BATCH_ID,
        "batch_slot": 1,
        "root_client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "product_id": recovery.PRODUCT_ID,
        "base_size": "0.00001583",
        "limit_price": "107702.14",
    }
    placement = [{
        "sequence": 1,
        "attempt_kind": "child",
        "batch_id": recovery.R2_BATCH_ID,
        "root_client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "plan_sha256": recovery.R2_PLAN_SHA256,
        "exact_order_tuple": child_tuple,
    }]
    handoff = {
        "authority": "selected_chain_child_cancel_recovery_v15r2",
        "plan_sha256": recovery.R2_PLAN_SHA256,
        "batch_id": recovery.R2_BATCH_ID,
        "actor_id": recovery.ACTOR_ID,
        "root_client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "idempotency_key": recovery.R2_CANCEL_IDEMPOTENCY_KEY,
        "correlation_id": recovery.R2_CANCEL_CORRELATION_ID,
        "payload_hash": recovery.R2_PROOF_PAYLOAD_HASH,
    }
    sentinel = {
        "installed": True,
        "wrapper_identity_proven": True,
        "phase": "child_place_limit_order_returned",
        "root_create_order_call_count": 0,
        "root_create_order_maximum": 0,
        "root_sdk_inflight": False,
        "child_place_limit_order_call_count": 1,
        "child_place_limit_order_maximum": 1,
        "child_sdk_inflight": False,
        "denied_call_count": 0,
        "critical_failure": False,
        "error": None,
    }
    progress = {
        "status": "awaiting_operator_ui_root_scoped_cancel",
        "root_client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "controlled_plan_sha256": recovery.R2_PLAN_SHA256,
        "idempotency_key": recovery.R2_CANCEL_IDEMPOTENCY_KEY,
        "correlation_id": recovery.R2_CANCEL_CORRELATION_ID,
        "runner_cancel_post_submitted": False,
        "runner_cancel_claim_acquired": False,
        "root_placement_authorized": False,
        "runtime_pid": 5678,
    }
    runtime_authority = {
        "plan_sha256": recovery.R2_PLAN_SHA256,
        "batch_id": recovery.R2_BATCH_ID,
        "parent_pid": 1234,
        "parent_start_identity": "111",
        "state_dir": str(recovery.R2_STATE_DIR),
    }
    runtime_authority_used = {
        "plan_sha256": recovery.R2_PLAN_SHA256,
        "batch_id": recovery.R2_BATCH_ID,
        "parent_pid": 1234,
        "child_pid": 5678,
    }

    _write_json(plan_path, plan)
    _write_json(marker_path, marker)
    _write_jsonl(placement_path, placement)
    cancel_path.touch(mode=0o600)
    claim_path.touch(mode=0o600)
    _write_json(handoff_path, handoff)
    _write_json(sentinel_path, sentinel)
    _write_json(progress_path, progress)
    _write_jsonl(idempotency_path, [successful_child, old_cancel])
    _write_jsonl(audit_path, [old_audit])
    _write_json(runtime_authority_path, runtime_authority)
    _write_json(runtime_authority_used_path, runtime_authority_used)
    runtime_pid_path.write_text("5678\n", encoding="utf-8")
    runtime_pid_path.chmod(0o600)

    paths = {
        "plan_path": str(plan_path),
        "marker_path": str(marker_path),
        "placement_ledger_path": str(placement_path),
        "cancel_ledger_path": str(cancel_path),
        "backend_claim_log_path": str(claim_path),
        "handoff_path": str(handoff_path),
        "sentinel_path": str(sentinel_path),
        "progress_path": str(progress_path),
        "idempotency_path": str(idempotency_path),
        "audit_path": str(audit_path),
        "runtime_authority_path": str(runtime_authority_path),
        "runtime_authority_used_path": str(runtime_authority_used_path),
        "runtime_pid_path": str(runtime_pid_path),
    }
    hashes = {
        "plan_bytes_sha256": _sha256(plan_path),
        "marker_bytes_sha256": _sha256(marker_path),
        "placement_ledger_bytes_sha256": _sha256(placement_path),
        "cancel_ledger_bytes_sha256": _sha256(cancel_path),
        "backend_claim_log_bytes_sha256": _sha256(claim_path),
        "handoff_bytes_sha256": _sha256(handoff_path),
        "sentinel_bytes_sha256": _sha256(sentinel_path),
        "progress_bytes_sha256": _sha256(progress_path),
        "successful_child_record_canonical_sha256": _canonical_sha256(successful_child),
        "failed_cancel_record_canonical_sha256": _canonical_sha256(old_cancel),
        "failed_cancel_audit_canonical_sha256": _canonical_sha256(old_audit),
        "runtime_authority_bytes_sha256": _sha256(runtime_authority_path),
        "runtime_authority_used_bytes_sha256": _sha256(runtime_authority_used_path),
        "runtime_pid_bytes_sha256": _sha256(runtime_pid_path),
    }
    return paths, hashes


def _plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    paths, hashes = _r2_fixture(tmp_path)
    monkeypatch.setattr(recovery, "R2_ARTIFACT_PATHS", paths)
    monkeypatch.setattr(recovery, "R2_EXPECTED_HASHES", hashes)
    monkeypatch.setattr(recovery, "backend_commit", lambda: "a" * 40)
    monkeypatch.setattr(recovery, "frontend_commit", lambda: "b" * 40)
    monkeypatch.setattr(recovery, "runner_sha256", lambda: "c" * 64)
    monkeypatch.setattr(recovery, "_read_process_identity", _fake_process_identity)
    binding = recovery.load_v15r2_failed_cancel_binding()
    completed = {
        "r2_source_binding": binding,
        "local_active_child_binding": _active_binding(),
        "failed_v15r3_execution_binding": (
            recovery.expected_failed_v15r3_execution_binding()
        ),
    }
    monkeypatch.setattr(
        recovery,
        "load_current_v15r3_source_binding",
        lambda: (binding, completed),
    )
    return recovery.build_v15r3_plan(
        binding,
        local_active_child=_active_binding(),
        now=datetime(2026, 7, 13, 3, 0, tzinfo=timezone.utc),
        approval_id="controlled-child-cancel-v15r4-11111111-1111-4111-8111-111111111111",
    )


def _recovered_transition(
    plan: dict[str, object], *, successor: bool = True
) -> dict[str, object]:
    source = dict(plan["v15r2_active_child_binding"])
    child = {
        "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "exchange_order_id": recovery.CHILD_EXCHANGE_ORDER_ID,
        "status": "OPEN",
        "filled_size": "0",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": 0,
        "reference_notional_usdc": "1.7049248762",
    }
    transition: dict[str, object] = {
        "schema_version": "3" if successor else "2",
        "status": (
            "v15r3_to_v15r4_no_overlap_proven"
            if successor
            else "v15r2_to_v15r3_no_overlap_proven"
        ),
        "recovery_status": (
            "failed_v15r3_proof_runtime_bound_no_live_cancel"
            if successor
            else "v15r2_shutdown_bound_no_overlap_proven"
        ),
        "transition_mode": (
            "bind_completed_predecessor_shutdowns_no_signals"
            if successor
            else "bind_completed_predecessor_shutdown_no_signals"
        ),
        "controlled_plan_sha256": plan["plan_sha256"],
        "failed_plan_sha256": recovery.FAILED_V15R3_PLAN_SHA256,
        "failed_plan_bytes_sha256": recovery.FAILED_V15R3_PLAN_BYTES_SHA256,
        "failed_batch_id": recovery.FAILED_V15R3_BATCH_ID,
        "failed_backend_commit": recovery.FAILED_V15R3_BACKEND_COMMIT,
        "failed_runner_sha256": recovery.FAILED_V15R3_RUNNER_SHA256,
        "r2_plan_sha256": recovery.R2_PLAN_SHA256,
        "r2_parent_process_identity": dict(source["r2_parent_process_identity"]),
        "r2_runtime_process_identity": dict(source["r2_runtime_process_identity"]),
        "predecessor_signal_attempt_count": 0,
        "predecessor_signal_authorized": False,
        "predecessor_restart_authorized": False,
        "both_predecessor_processes_absent": True,
        "both_predecessor_exact_identities_absent": True,
        "terminal_artifact_paths": {
            key: str(value)
            for key, value in recovery.COMPLETED_SHUTDOWN_ARTIFACT_PATHS.items()
        },
        "terminal_artifact_hashes": dict(
            recovery.COMPLETED_SHUTDOWN_ARTIFACT_HASHES
        ),
        "transition_disable_record_hashes": dict(
            recovery.COMPLETED_SHUTDOWN_RECORD_HASHES
        ),
        "admin_port_8787_free": True,
        "competitor_pid": None,
        "exact_child_open_zero_fill": True,
        "child_readback": child,
        "recorded_at": "2026-07-13T03:00:30+00:00",
    }
    if successor:
        transition["failed_v15r3_execution_binding"] = (
            recovery.expected_failed_v15r3_execution_binding()
        )
    transition["transition_sha256"] = recovery.transition_hash(transition)
    return transition


def test_v15r3_plan_is_cancel_only_exact_actor_fresh_and_120_minutes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)

    assert plan["schema_version"] == "22"
    assert plan["authority_kind"] == recovery.AUTHORITY_KIND
    assert plan["placement_attempt_count"] == 0
    assert plan["placement_attempt_schedule"] == []
    assert plan["root_placement_maximum"] == 0
    assert plan["child_placement_maximum"] == 0
    assert plan["cancel_command_maximum"] == 1
    assert plan["root_placement_authorized"] is False
    assert plan["child_placement_authorized"] is False
    assert plan["root_reference_cap_usdc"] == "9.99"
    assert plan["child_reference_cap_usdc"] == "2.00"
    assert plan["slice_reference_cap_usdc"] == "12.00"
    assert plan["actor_id"] == "operator-controlled-spot-proof"
    assert plan["actor_roles"] == ["trader"]
    assert plan["expires_at"] == "2026-07-13T05:00:00+00:00"
    assert Decimal(plan["active_child_reference_notional_usdc"]) == Decimal(
        "1.7049248762"
    )
    assert Decimal(plan["aggregate_reference_notional_usdc"]) == Decimal(
        "2.7125045345"
    )
    assert plan["planned_reference_notional_usdc"] == "2.7125045345"
    assert Decimal(plan["aggregate_reference_notional_usdc"]) < Decimal("12.00")
    assert plan["child_evidence"]["exchange_order_id"] == (
        recovery.CHILD_EXCHANGE_ORDER_ID
    )
    assert plan["child_evidence"]["product_id"] == "BTC-USDC"
    assert plan["child_evidence"]["side"] == "SELL"
    assert plan["child_evidence"]["total_fees"] == "0"
    assert plan["cancel_command"]["identity_value"] == recovery.ROOT_CLIENT_ORDER_ID
    assert plan["cancel_command"]["child_client_order_id"] == (
        recovery.CHILD_CLIENT_ORDER_ID
    )
    assert plan["cancel_command"]["actor_roles"] == ["trader"]
    assert plan["cancel_command"]["admission_audit_id_source"] == (
        "route_bound_runtime_proof"
    )
    assert recovery.FAILED_V15R3_CANCEL_IDS <= recovery.R2_USED_IDS
    assert recovery.FAILED_V15R3_CANCEL_IDS <= (
        cancel_authority.CONTROLLED_V15R2_USED_CANCEL_IDS
    )
    assert set(recovery.cancel_command_ids(plan)).isdisjoint(recovery.R2_USED_IDS)
    assert plan["plan_sha256"] == recovery.plan_hash(plan)


def test_v15r3_successor_paths_and_ids_do_not_reuse_consumed_189c_authority() -> None:
    current_paths = {
        recovery.PLAN_PATH,
        recovery.MARKER_PATH,
        recovery.PLACEMENT_LEDGER_PATH,
        recovery.CANCEL_LEDGER_PATH,
        recovery.BACKEND_CLAIM_LOG_PATH,
        recovery.HANDOFF_PATH,
        recovery.RUNTIME_PATH,
    }
    consumed_paths = set(recovery.FAILED_PROOF_ARTIFACT_PATHS.values())

    assert recovery.FAILED_PROOF_PLAN_SHA256 == (
        "189c338ebd49afb1013a0c2e54e6a228dc6e4e57707b5f0ef7487f63b5cf2302"
    )
    assert recovery.FAILED_PROOF_BATCH_ID == (
        "12613395-b8d6-5fdd-9dc7-de3086de1a26"
    )
    assert current_paths.isdisjoint(consumed_paths)
    assert recovery.FAILED_PROOF_BATCH_ID in recovery.R2_USED_IDS
    assert recovery.FAILED_PROOF_CANCEL_IDS <= recovery.R2_USED_IDS
    assert recovery.FAILED_PROOF_BATCH_ID in (
        cancel_authority.CONTROLLED_V15R2_USED_CANCEL_IDS
    )
    assert recovery.FAILED_PROOF_CANCEL_IDS <= (
        cancel_authority.CONTROLLED_V15R2_USED_CANCEL_IDS
    )


def test_v15r4_plan_is_self_describing_about_the_failed_v15r3_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)

    assert plan["schema_version"] == "22"
    assert plan["authority_kind"] == (
        "selected_chain_child_cancel_recovery_v15r4"
    )
    assert plan["approval_id"].startswith("controlled-child-cancel-v15r4-")
    assert plan["failed_v15r3_execution_binding"] == (
        recovery.expected_failed_v15r3_execution_binding()
    )
    assert plan["failed_v15r3_execution_binding"] == (
        cancel_authority.CONTROLLED_V15R4_FAILED_EXECUTION_BINDING
    )
    assert plan["failed_v15r3_execution_binding"]["plan_sha256"] == (
        recovery.FAILED_PROOF_PLAN_SHA256
    )
    assert plan["failed_v15r3_execution_binding"][
        "cancel_route_call_count"
    ] == 0
    assert plan["failed_v15r3_execution_binding"][
        "semantic_claim_count"
    ] == 0
    assert plan["failed_v15r3_execution_binding"][
        "exchange_cancel_boundary_call_count"
    ] == 0
    assert plan["failed_v15r3_execution_binding"][
        "successor_binder_signal_attempt_count"
    ] == 0
    assert plan["retry_authorized"] is False


def test_v15r4_failed_v15r3_runtime_binding_proves_zero_command_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_plan = deepcopy(_plan(tmp_path, monkeypatch))
    failed_plan.pop("failed_v15r3_execution_binding")
    failed_plan.update(
        {
            "schema_version": "21",
            "authority_kind": "selected_chain_child_cancel_recovery_v15r3",
            "approval_id": recovery.FAILED_PROOF_APPROVAL_ID,
            "batch_id": recovery.FAILED_PROOF_BATCH_ID,
            "backend_commit": recovery.FAILED_PROOF_BACKEND_COMMIT,
            "runner_sha256": recovery.FAILED_PROOF_RUNNER_SHA256,
        }
    )
    failed_plan["cancel_command"].update(
        recovery.expected_failed_v15r3_execution_binding()["cancel_command_ids"]
    )
    failed_plan["cancel_command"]["semantic_retry_policy"] = (
        "fresh_v15r3_idempotency_key_exactly_once"
    )
    failed_plan["plan_sha256"] = recovery.FAILED_PROOF_PLAN_SHA256
    marker = {
        "authority": "selected_chain_child_cancel_recovery_v15r3",
        "approval_id": recovery.FAILED_PROOF_APPROVAL_ID,
        "batch_id": recovery.FAILED_PROOF_BATCH_ID,
        "plan_file": str(recovery.FAILED_PROOF_ARTIFACT_PATHS["plan"]),
        "plan_sha256": recovery.FAILED_PROOF_PLAN_SHA256,
        "backend_commit": recovery.FAILED_PROOF_BACKEND_COMMIT,
        "runner_sha256": recovery.FAILED_PROOF_RUNNER_SHA256,
        "root_client_order_id": recovery.ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "placement_attempt_maximum": 0,
        "root_placement_maximum": 0,
        "child_placement_maximum": 0,
        "cancel_command_maximum": 1,
        "placement_ledger_path": str(
            recovery.FAILED_PROOF_ARTIFACT_PATHS["placement_ledger"]
        ),
        "cancel_ledger_path": str(
            recovery.FAILED_PROOF_ARTIFACT_PATHS["cancel_ledger"]
        ),
        "backend_claim_log_path": str(
            recovery.FAILED_PROOF_ARTIFACT_PATHS["backend_claim_log"]
        ),
        "handoff_path": str(
            recovery.FAILED_PROOF_ABSENT_ARTIFACT_PATHS["handoff"]
        ),
        "process_id": recovery.FAILED_PROOF_PARENT_PROCESS_ID,
    }
    transition = _recovered_transition(failed_plan, successor=False)
    transition["controlled_plan_sha256"] = recovery.FAILED_PROOF_PLAN_SHA256
    transition["transition_sha256"] = recovery.FAILED_PROOF_TRANSITION_SHA256
    runtime_authority = {
        "plan_sha256": recovery.FAILED_PROOF_PLAN_SHA256,
        "batch_id": recovery.FAILED_PROOF_BATCH_ID,
        "parent_pid": recovery.FAILED_PROOF_PARENT_PROCESS_ID,
        "state_dir": str(recovery.FAILED_PROOF_STATE_DIR),
        "global_batch_marker": str(
            recovery.FAILED_PROOF_ARTIFACT_PATHS["marker"]
        ),
    }
    runtime_authority_used = {
        "plan_sha256": recovery.FAILED_PROOF_PLAN_SHA256,
        "batch_id": recovery.FAILED_PROOF_BATCH_ID,
        "parent_pid": recovery.FAILED_PROOF_PARENT_PROCESS_ID,
        "child_pid": recovery.FAILED_PROOF_RUNTIME_PROCESS_ID,
        "global_batch_marker": str(
            recovery.FAILED_PROOF_ARTIFACT_PATHS["marker"]
        ),
    }
    sentinel = {
        "installed": True,
        "wrapper_identity_proven": True,
        "phase": "runtime_exited",
        "process_id": recovery.FAILED_PROOF_RUNTIME_PROCESS_ID,
        "root_create_order_call_count": 0,
        "root_create_order_maximum": 0,
        "root_sdk_inflight": False,
        "child_place_limit_order_call_count": 0,
        "child_place_limit_order_maximum": 0,
        "child_sdk_inflight": False,
        "denied_call_count": 0,
        "critical_failure": False,
        "error": None,
    }
    live_service = {
        "status": "blocked",
        "requested_service_status": "live_disabled",
        "service_enabled": False,
        "live_coinbase_execution_approved": False,
        "max_submitted_notional_usdc": "0",
        "max_executed_notional_usdc": "0",
        "deployment_ref": recovery.FAILED_PROOF_BACKEND_COMMIT,
        "runtime_configuration_ref": str(recovery.FAILED_PROOF_STATE_DIR),
    }
    idempotency = {
        "status": "accepted",
        "endpoint": "POST /api/v1/admin/live-execution/service-decisions",
        "response": {
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
        },
    }
    audit = {
        "status": "accepted",
        "endpoint": "POST /api/v1/admin/live-execution/service-decisions",
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }
    monkeypatch.setattr(
        recovery,
        "FAILED_PROOF_RECORD_HASHES",
        {
            "live_service": _canonical_sha256(live_service),
            "idempotency": _canonical_sha256(idempotency),
            "audit": _canonical_sha256(audit),
        },
    )
    json_values = {
        recovery.FAILED_PROOF_ARTIFACT_PATHS["plan"]: failed_plan,
        recovery.FAILED_PROOF_ARTIFACT_PATHS["marker"]: marker,
        recovery.FAILED_PROOF_ARTIFACT_PATHS["runtime_transition"]: transition,
        recovery.FAILED_PROOF_ARTIFACT_PATHS["runtime_authority"]: runtime_authority,
        recovery.FAILED_PROOF_ARTIFACT_PATHS[
            "runtime_authority_used"
        ]: runtime_authority_used,
        recovery.FAILED_PROOF_ARTIFACT_PATHS["sentinel"]: sentinel,
    }
    jsonl_values = {
        recovery.FAILED_PROOF_ARTIFACT_PATHS["placement_ledger"]: [],
        recovery.FAILED_PROOF_ARTIFACT_PATHS["cancel_ledger"]: [],
        recovery.FAILED_PROOF_ARTIFACT_PATHS["backend_claim_log"]: [],
        recovery.FAILED_PROOF_ARTIFACT_PATHS["live_service"]: [live_service],
        recovery.FAILED_PROOF_ARTIFACT_PATHS["idempotency"]: [idempotency],
        recovery.FAILED_PROOF_ARTIFACT_PATHS["audit"]: [audit],
    }
    monkeypatch.setattr(
        recovery,
        "_file_sha256",
        lambda path, *_args, **_kwargs: next(
            recovery.FAILED_PROOF_ARTIFACT_HASHES[key]
            for key, expected_path in recovery.FAILED_PROOF_ARTIFACT_PATHS.items()
            if path == expected_path
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_json",
        lambda path, *_args, **_kwargs: deepcopy(json_values[path]),
    )
    monkeypatch.setattr(
        recovery,
        "_jsonl",
        lambda path, *_args, **_kwargs: deepcopy(jsonl_values[path]),
    )
    monkeypatch.setattr(
        recovery,
        "_text",
        lambda *_args, **_kwargs: (
            'POST /api/v1/admin/live-execution/service-decisions HTTP/1.1" 200 OK\n'
            'POST /api/v1/admin/approvals/requests HTTP/1.1" 422 '
            "Unprocessable Content\n"
            "Received SIGTERM; initiating graceful shutdown\n"
            "Application shutdown complete.\n"
        ),
    )
    original_plan_hash = recovery.plan_hash
    monkeypatch.setattr(
        recovery,
        "plan_hash",
        lambda value: (
            recovery.FAILED_PROOF_PLAN_SHA256
            if value.get("schema_version") == "21"
            and value.get("batch_id") == recovery.FAILED_PROOF_BATCH_ID
            else original_plan_hash(value)
        ),
    )
    monkeypatch.setattr(
        recovery,
        "transition_hash",
        lambda _value: recovery.FAILED_PROOF_TRANSITION_SHA256,
    )
    monkeypatch.setattr(recovery, "_process_id_absent", lambda _pid: True)
    monkeypatch.setattr(recovery.os.path, "lexists", lambda _path: False)
    monkeypatch.setattr(
        recovery.base, "require_runtime_exclusivity", lambda **_kwargs: None
    )

    binding = recovery.load_failed_v15r3_execution_binding()

    assert binding == recovery.expected_failed_v15r3_execution_binding()
    sentinel["child_place_limit_order_call_count"] = 1
    with pytest.raises(
        recovery.ProofFailure,
        match="v15r4_failed_execution_sentinel_scope_mismatch",
    ):
        recovery.load_failed_v15r3_execution_binding()


def test_v15r3_source_binding_requires_successful_child_and_exact_failed_no_live_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, hashes = _r2_fixture(tmp_path)
    monkeypatch.setattr(recovery, "R2_ARTIFACT_PATHS", paths)
    monkeypatch.setattr(recovery, "R2_EXPECTED_HASHES", hashes)
    monkeypatch.setattr(recovery, "_read_process_identity", _fake_process_identity)

    binding = recovery.load_v15r2_failed_cancel_binding()

    assert binding["r2_plan_sha256"] == recovery.R2_PLAN_SHA256
    assert binding["r2_root_sdk_call_count"] == 0
    assert binding["r2_child_sdk_call_count"] == 1
    assert binding["r2_cancel_command_count"] == 0
    assert binding["child_exchange_order_id"] == recovery.CHILD_EXCHANGE_ORDER_ID
    assert binding["child_reference_notional_usdc"] == "1.7049248762"
    assert binding["failed_cancel_http_status"] == 501
    assert binding["failed_cancel_live_exchange_submitted"] is False
    assert binding["failed_cancel_live_coinbase_orders_ran"] is False
    assert binding["failed_cancel_semantic_claim_acquired"] is False
    assert binding["failed_cancel_exchange_boundary_called"] is False

    rows = [json.loads(line) for line in Path(paths["idempotency_path"]).read_text().splitlines()]
    rows[-1]["response"]["live_coinbase_orders_ran"] = True
    _write_jsonl(Path(paths["idempotency_path"]), rows)
    hashes["failed_cancel_record_canonical_sha256"] = _canonical_sha256(rows[-1])
    with pytest.raises(recovery.ProofFailure, match="v15r2_failed_cancel_not_no_live"):
        recovery.load_v15r2_failed_cancel_binding()


@pytest.mark.parametrize(
    ("mutator", "blocker"),
    [
        (lambda plan: plan.update({"child_placement_maximum": 1}), "exact_scope"),
        (lambda plan: plan.update({"actor_roles": ["admin"]}), "actor_scope"),
        (
            lambda plan: plan.update({"active_child_reference_notional_usdc": "1.70"}),
            "numeric_scope",
        ),
        (
            lambda plan: plan["cancel_command"].update(
                {"idempotency_key": recovery.R2_CANCEL_IDEMPOTENCY_KEY}
            ),
            "fresh_id_scope",
        ),
    ],
)
def test_v15r3_validation_rejects_any_broadened_or_reused_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutator,
    blocker: str,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    mutator(plan)
    plan["plan_sha256"] = recovery.plan_hash(plan)

    with pytest.raises(recovery.ProofFailure, match=f"v15r3_{blocker}_mismatch"):
        recovery.validate_v15r3_plan(
            plan,
            expected_hash=plan["plan_sha256"],
            now=datetime(2026, 7, 13, 3, 1, tzinfo=timezone.utc),
        )


def test_v15r3_active_binding_rejects_nonzero_fill_or_exchange_identity_drift() -> None:
    binding = _active_binding()
    assert recovery.validate_local_active_child_binding(binding) == binding

    filled = deepcopy(binding)
    filled["executed_size"] = "0.00000001"
    with pytest.raises(recovery.ProofFailure, match="v15r3_local_active_child_mismatch"):
        recovery.validate_local_active_child_binding(filled)

    wrong_exchange = deepcopy(binding)
    wrong_exchange["active_exchange_order_id"] = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(recovery.ProofFailure, match="v15r3_local_active_child_mismatch"):
        recovery.validate_local_active_child_binding(wrong_exchange)


def test_v15r3_prepare_creates_only_owner_only_plan_and_no_runtime_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, hashes = _r2_fixture(tmp_path / "source")
    monkeypatch.setattr(recovery, "R2_ARTIFACT_PATHS", paths)
    monkeypatch.setattr(recovery, "R2_EXPECTED_HASHES", hashes)
    monkeypatch.setattr(recovery, "backend_commit", lambda: "a" * 40)
    monkeypatch.setattr(recovery, "frontend_commit", lambda: "b" * 40)
    monkeypatch.setattr(recovery, "runner_sha256", lambda: "c" * 64)
    monkeypatch.setattr(recovery, "_read_process_identity", _fake_process_identity)
    binding = recovery.load_v15r2_failed_cancel_binding()
    completed = {
        "r2_source_binding": binding,
        "local_active_child_binding": _active_binding(),
        "failed_v15r3_execution_binding": (
            recovery.expected_failed_v15r3_execution_binding()
        ),
    }
    monkeypatch.setattr(
        recovery,
        "load_current_v15r3_source_binding",
        lambda: (binding, completed),
    )
    for name in (
        "signal_exact_process",
        "post_v15r2_live_service_disabled",
        "transition_v15r2_runtime",
        "bind_completed_v15r2_shutdown",
    ):
        monkeypatch.setattr(
            recovery,
            name,
            lambda *_args, _name=name, **_kwargs: pytest.fail(
                f"preparation must not call {_name}"
            ),
        )
    monkeypatch.setattr(
        recovery.base,
        "AdminRuntime",
        lambda *_args, **_kwargs: pytest.fail(
            "preparation must not construct a runtime"
        ),
    )

    output_dir = tmp_path / "output"
    plan_path = output_dir / "v15r3-plan.json"
    marker_path = output_dir / "v15r3-marker.json"
    placement_path = output_dir / "v15r3-placement.jsonl"
    cancel_path = output_dir / "v15r3-cancel.jsonl"
    claim_path = output_dir / "v15r3-claims.jsonl"
    handoff_path = output_dir / "v15r3-handoff.json"
    runtime_path = output_dir / "v15r3-runtime.json"

    result = recovery.prepare_v15r3_plan(
        plan_path=plan_path,
        marker_path=marker_path,
        placement_ledger_path=placement_path,
        cancel_ledger_path=cancel_path,
        backend_claim_log_path=claim_path,
        handoff_path=handoff_path,
        runtime_path=runtime_path,
        now=datetime(2026, 7, 13, 3, 0, tzinfo=timezone.utc),
        require_clean_environment=False,
    )

    assert result["status"] == "prepared"
    assert result["placement_attempt_count"] == 0
    assert result["root_placement_maximum"] == 0
    assert result["child_placement_maximum"] == 0
    assert result["cancel_command_maximum"] == 1
    assert result["live_coinbase_orders_ran"] is False
    assert result["live_coinbase_read_ran"] is True
    assert result["completed_predecessor_shutdown_bound"] is True
    assert result["marker_written"] is False
    assert result["ledger_written"] is False
    assert result["runtime_started"] is False
    assert plan_path.is_file()
    assert plan_path.stat().st_mode & 0o777 == 0o600
    assert sorted(path.name for path in output_dir.iterdir()) == [plan_path.name]
    assert not any(
        path.exists()
        for path in (
            marker_path,
            placement_path,
            cancel_path,
            claim_path,
            handoff_path,
            runtime_path,
        )
    )


def test_v15r3_completed_shutdown_binder_writes_strict_no_signal_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path / "plan-source", monkeypatch)
    expected = _recovered_transition(plan)
    completed = {
        "failed_plan_sha256": recovery.FAILED_V15R3_PLAN_SHA256,
        "failed_plan_bytes_sha256": recovery.FAILED_V15R3_PLAN_BYTES_SHA256,
        "failed_batch_id": recovery.FAILED_V15R3_BATCH_ID,
        "failed_backend_commit": recovery.FAILED_V15R3_BACKEND_COMMIT,
        "failed_runner_sha256": recovery.FAILED_V15R3_RUNNER_SHA256,
        "r2_source_binding": plan["v15r2_active_child_binding"],
        "local_active_child_binding": plan["local_active_child_binding"],
        "terminal_artifact_paths": expected["terminal_artifact_paths"],
        "terminal_artifact_hashes": expected["terminal_artifact_hashes"],
        "transition_disable_record_hashes": expected[
            "transition_disable_record_hashes"
        ],
        "failed_v15r3_execution_binding": (
            recovery.expected_failed_v15r3_execution_binding()
        ),
        "both_predecessor_exact_identities_absent": True,
        "child_readback": expected["child_readback"],
    }
    monkeypatch.setattr(
        recovery,
        "load_current_v15r3_source_binding",
        lambda: (plan["v15r2_active_child_binding"], completed),
    )
    for name in (
        "signal_exact_process",
        "post_v15r2_live_service_disabled",
        "transition_v15r2_runtime",
        "wait_exact_process_absent",
    ):
        monkeypatch.setattr(
            recovery,
            name,
            lambda *_args, _name=name, **_kwargs: pytest.fail(
                f"completed shutdown binding must not call {_name}"
            ),
        )

    transition_path = tmp_path / "transition.json"
    receipt = recovery.bind_completed_v15r2_shutdown(
        plan,
        confirmed_plan_sha256=plan["plan_sha256"],
        transition_path=transition_path,
    )

    assert set(receipt) == recovery.V15R4_RECOVERED_TRANSITION_FIELDS
    assert receipt["transition_mode"] == (
        "bind_completed_predecessor_shutdowns_no_signals"
    )
    assert receipt["predecessor_signal_attempt_count"] == 0
    assert receipt["predecessor_signal_authorized"] is False
    assert receipt["predecessor_restart_authorized"] is False
    assert receipt["both_predecessor_exact_identities_absent"] is True
    assert receipt["transition_sha256"] == recovery.transition_hash(receipt)
    assert transition_path.stat().st_mode & 0o777 == 0o600


def test_v15r3_transition_is_strictly_no_overlap_and_records_exact_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path / "plan-source", monkeypatch)
    events: list[str] = []
    transition_path = tmp_path / "transition.json"

    monkeypatch.setattr(
        recovery,
        "revalidate_v15r2_transition_processes",
        lambda _plan: events.append("identity") or {
            "parent": _fake_process_identity(1234),
            "runtime": _fake_process_identity(5678),
        },
    )
    monkeypatch.setattr(
        recovery,
        "post_v15r2_live_service_disabled",
        lambda **_kwargs: events.append("disable") or {
            "http_status": 200,
            "resolver_eligible": False,
            "service_enabled": False,
        },
    )
    monkeypatch.setattr(
        recovery,
        "read_v15r2_pretransition_sentinel",
        lambda: events.append("sentinel") or {
            "root_create_order_call_count": 0,
            "child_place_limit_order_call_count": 1,
            "root_sdk_inflight": False,
            "child_sdk_inflight": False,
            "denied_call_count": 0,
        },
    )
    monkeypatch.setattr(
        recovery,
        "signal_exact_process",
        lambda identity, sig: events.append(
            f"signal:{identity['process_id']}:{signal.Signals(sig).name}"
        ),
    )
    monkeypatch.setattr(
        recovery,
        "wait_exact_process_absent",
        lambda identity: events.append(f"absent:{identity['process_id']}") or True,
    )
    monkeypatch.setattr(
        recovery,
        "wait_v15r2_parent_loss_evidence",
        lambda **_kwargs: events.append("parent-loss") or {
            "new_sdk_placements_denied": True,
            "new_cancel_command_authorized": False,
            "live_service_disable_http_status": 200,
            "authoritative_active_read_stable": True,
        },
    )
    monkeypatch.setattr(
        recovery,
        "prove_admin_port_free",
        lambda: events.append("port-free") or {
            "port": 8787,
            "free": True,
            "competitor_pid": None,
        },
    )
    monkeypatch.setattr(
        recovery,
        "read_exact_active_child_after_transition",
        lambda **_kwargs: events.append("child-open") or {
            "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
            "exchange_order_id": recovery.CHILD_EXCHANGE_ORDER_ID,
            "status": "OPEN",
            "filled_size": "0",
            "filled_value": "0",
            "number_of_fills": 0,
            "reference_notional_usdc": "1.7049248762",
        },
    )

    proof = recovery.transition_v15r2_runtime(
        plan,
        confirmed_plan_sha256=plan["plan_sha256"],
        transition_path=transition_path,
    )

    assert events == [
        "identity",
        "disable",
        "sentinel",
        "signal:1234:SIGINT",
        "absent:1234",
        "parent-loss",
        "signal:5678:SIGTERM",
        "absent:5678",
        "port-free",
        "child-open",
    ]
    assert proof["status"] == "v15r2_to_v15r3_no_overlap_proven"
    assert proof["both_predecessor_processes_absent"] is True
    assert proof["admin_port_8787_free"] is True
    assert proof["exact_child_open_zero_fill"] is True
    assert proof["transition_sha256"] == recovery.transition_hash(proof)
    assert transition_path.stat().st_mode & 0o777 == 0o600


def test_v15r3_post_transition_authority_does_not_reload_mutated_r2_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path / "plan-source", monkeypatch)
    plan_path = tmp_path / "plan.json"
    _write_json(plan_path, plan)
    transition = _recovered_transition(plan)
    monkeypatch.setattr(
        recovery,
        "load_v15r2_failed_cancel_binding",
        lambda: pytest.fail("post-transition source reload is forbidden"),
    )
    output = tmp_path / "authority"

    authority = recovery.authorize_v15r3_execution(
        plan_path,
        expected_hash=plan["plan_sha256"],
        frozen_plan=plan,
        transition=transition,
        marker_path=output / "marker.json",
        placement_ledger_path=output / "placements.jsonl",
        cancel_ledger_path=output / "cancel.jsonl",
        backend_claim_log_path=output / "claims.jsonl",
        handoff_path=output / "handoff.json",
        now=datetime(2026, 7, 13, 3, 1, tzinfo=timezone.utc),
    )

    assert authority["placement_attempt_maximum"] == 0
    assert authority["root_placement_maximum"] == 0
    assert authority["child_placement_maximum"] == 0
    assert authority["cancel_command_maximum"] == 1
    assert (output / "placements.jsonl").read_bytes() == b""
    assert (output / "cancel.jsonl").read_bytes() == b""
    assert (output / "claims.jsonl").read_bytes() == b""
    assert not (output / "handoff.json").exists()


def test_v15r3_post_transition_requires_exact_no_signal_recovery_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path / "plan-source", monkeypatch)
    legacy = {
        "status": "v15r2_to_v15r3_no_overlap_proven",
        "controlled_plan_sha256": plan["plan_sha256"],
        "both_predecessor_processes_absent": True,
        "admin_port_8787_free": True,
        "competitor_pid": None,
        "exact_child_open_zero_fill": True,
    }
    legacy["transition_sha256"] = recovery.transition_hash(legacy)

    with pytest.raises(
        recovery.ProofFailure,
        match="v15r3_post_transition_evidence_invalid",
    ):
        recovery._validate_frozen_plan_after_transition(
            plan,
            expected_hash=plan["plan_sha256"],
            transition=legacy,
            now=datetime(2026, 7, 13, 3, 1, tzinfo=timezone.utc),
        )

    recovered = _recovered_transition(plan)
    recovery._validate_frozen_plan_after_transition(
        plan,
        expected_hash=plan["plan_sha256"],
        transition=recovered,
        now=datetime(2026, 7, 13, 3, 1, tzinfo=timezone.utc),
    )

    recovered["predecessor_signal_attempt_count"] = 1
    recovered["transition_sha256"] = recovery.transition_hash(recovered)
    with pytest.raises(
        recovery.ProofFailure,
        match="v15r3_post_transition_evidence_invalid",
    ):
        recovery._validate_frozen_plan_after_transition(
            plan,
            expected_hash=plan["plan_sha256"],
            transition=recovered,
            now=datetime(2026, 7, 13, 3, 1, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda receipt: receipt.update({"unexpected_authority": True}),
        lambda receipt: receipt.update({"failed_plan_bytes_sha256": "0" * 64}),
        lambda receipt: receipt["terminal_artifact_hashes"].update(
            {"sentinel": "0" * 64}
        ),
        lambda receipt: receipt.update(
            {"both_predecessor_exact_identities_absent": False}
        ),
        lambda receipt: receipt["child_readback"].update(
            {"filled_size": "0.00000001"}
        ),
        lambda receipt: receipt["child_readback"].update(
            {"total_fees": "0.01"}
        ),
    ],
)
def test_v15r3_post_transition_rejects_rehashed_semantic_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutator,
) -> None:
    plan = _plan(tmp_path / "plan-source", monkeypatch)
    recovered = deepcopy(_recovered_transition(plan))
    mutator(recovered)
    recovered["transition_sha256"] = recovery.transition_hash(recovered)

    with pytest.raises(
        recovery.ProofFailure,
        match="v15r3_post_transition_evidence_invalid",
    ):
        recovery._validate_frozen_plan_after_transition(
            plan,
            expected_hash=plan["plan_sha256"],
            transition=recovered,
            now=datetime(2026, 7, 13, 3, 1, tzinfo=timezone.utc),
        )


def test_v15r3_cancel_context_uses_exact_trader_and_runner_has_no_cancel_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect

    plan = _plan(tmp_path, monkeypatch)
    context, body = recovery.build_v15r3_cancel_admission_context(
        plan, plan_sha256=plan["plan_sha256"]
    )

    assert context["actor_id"] == recovery.ACTOR_ID
    assert context["actor_roles"] == ["trader"]
    assert context["payload_hash"] not in {
        recovery.R2_PROOF_PAYLOAD_HASH,
        recovery.R2_FAILED_CANCEL_PAYLOAD_HASH,
    }
    assert body["controlled_plan_sha256"] == plan["plan_sha256"]
    source = inspect.getsource(recovery.execute_v15r3_plan)
    assert '"POST", cancel_path' not in source
    assert "runner_cancel_post_submitted" in source


def test_v15r3_proof_approval_is_capped_at_sealed_plan_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, monkeypatch)
    context, _body = recovery.build_v15r3_cancel_admission_context(
        plan, plan_sha256=plan["plan_sha256"]
    )
    captured: dict[str, object] = {}

    def fake_write_proof_chain(_runtime, **kwargs):
        captured.update(kwargs)
        return {
            "approval_id": plan["cancel_command"]["approval_snapshot_id"],
            "admission_audit_id": "audit-v15r3",
            "cap_guard_decision_id": plan["cancel_command"][
                "cap_guard_decision_id"
            ],
            "reconciliation_plan_id": plan["cancel_command"][
                "reconciliation_plan_id"
            ],
        }

    monkeypatch.setattr(recovery.base, "write_proof_chain", fake_write_proof_chain)

    recovery.write_v15r3_exact_proofs(
        object(),
        plan=plan,
        context=context,
    )

    assert captured["approval_expires_at"] == plan["expires_at"]
    assert captured["command_kind"] == "child_cancel"
    assert captured["cancel"] is True


def test_shared_proof_writer_sends_explicit_sealed_approval_expiry() -> None:
    from application.admin_api.models import (
        AdminAdmissionAuditCreateRequest,
        AdminApprovalDecisionRequest,
        AdminApprovalRequestCreateRequest,
        AdminCapGuardDecisionCreateRequest,
        AdminReconciliationPlanCreateRequest,
    )

    approval_expiry = (
        datetime.now(timezone.utc) + recovery.PLAN_TTL - recovery.timedelta(seconds=5)
    ).isoformat()
    observed_decision: dict[str, object] = {}
    observed_bodies: dict[str, dict[str, object]] = {}
    observed_roles: dict[str, str] = {}
    context = {
        "route": "/route",
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": recovery.ROOT_CLIENT_ORDER_ID,
        "action_class": "live_exchange_cancel",
        "required_permission": "order:cancel",
        "service_method": "cancel",
        "actor_id": recovery.ACTOR_ID,
        "actor_roles": ["trader"],
        "operator_intent": recovery.CANCEL_OPERATOR_INTENT,
        "command_idempotency_key": "idem",
        "payload_hash": "a" * 64,
    }

    class Runtime:
        @staticmethod
        def headers(**kwargs):
            return kwargs

        @staticmethod
        def request(method, path, *, body=None, headers=None, **_kwargs):
            assert method == "POST"
            observed_bodies[path] = dict(body)
            observed_roles[path] = headers["role"]
            if path == "/admin/approvals/requests":
                AdminApprovalRequestCreateRequest.model_validate(body)
                return 200, {"approval": {"approval_request_id": "request-1"}}, {}
            if path == "/admin/approvals/requests/request-1/decisions":
                AdminApprovalDecisionRequest.model_validate(body)
                observed_decision.update(body)
                return 200, {
                    "approval": {
                        "approval_id": "approval-1",
                        "decision_actor_id": "admin-1",
                        "requested_by_actor_id": recovery.ACTOR_ID,
                        "expires_at": body["expires_at"],
                    }
                }, {}
            if path == "/admin/admission-audits":
                AdminAdmissionAuditCreateRequest.model_validate(body)
                return 200, {
                    "admission_audit": {
                        "admission_audit_id": "audit-1",
                        "resolver_eligible": True,
                    }
                }, {}
            if path == "/admin/cap-guard/decisions":
                AdminCapGuardDecisionCreateRequest.model_validate(body)
                return 200, {
                    "decision": {
                        "decision_id": "cap-1",
                        "resolver_eligible": True,
                    }
                }, {}
            if path == "/admin/reconciliation/plans":
                AdminReconciliationPlanCreateRequest.model_validate(body)
                return 200, {
                    "plan": {
                        "plan_id": "reconciliation-1",
                        "resolver_eligible": True,
                    }
                }, {}
            raise AssertionError(path)

    recovery.base.write_proof_chain(
        Runtime(),
        label="v15r3-expiry",
        context=context,
        wallet_available=Decimal("0"),
        max_notional=Decimal("0"),
        command_kind="child_cancel",
        cancel=True,
        approval_id="approval-1",
        cap_guard_decision_id="cap-1",
        reconciliation_plan_id="reconciliation-1",
        approval_expires_at=approval_expiry,
    )

    assert observed_decision["expires_at"] == approval_expiry
    proof_paths = {
        "/admin/approvals/requests",
        "/admin/admission-audits",
        "/admin/cap-guard/decisions",
        "/admin/reconciliation/plans",
    }
    assert all(
        "actor_roles" not in observed_bodies[path] for path in proof_paths
    )
    assert "actor_id" not in observed_bodies["/admin/approvals/requests"]
    assert "service_method" not in observed_bodies["/admin/approvals/requests"]
    for path in proof_paths - {"/admin/approvals/requests"}:
        assert observed_bodies[path]["actor_id"] == recovery.ACTOR_ID
        assert observed_bodies[path]["service_method"] == "cancel"
    assert context["actor_roles"] == ["trader"]
    assert observed_roles["/admin/approvals/requests"] == "trader"
    assert observed_roles["/admin/approvals/requests/request-1/decisions"] == (
        "admin"
    )
    assert all(
        observed_roles[path] == "admin"
        for path in proof_paths - {"/admin/approvals/requests"}
    )


def test_v15r3_waiting_child_guard_rejects_fill_or_non_active_drift() -> None:
    open_child = {
        "client_order_id": recovery.CHILD_CLIENT_ORDER_ID,
        "order_id": recovery.CHILD_EXCHANGE_ORDER_ID,
        "status": "OPEN",
        "filled_size": "0",
        "filled_value": "0",
        "number_of_fills": "0",
    }
    assert recovery.validate_v15r3_waiting_child_readback(open_child)["status"] == (
        "OPEN"
    )

    filled = deepcopy(open_child)
    filled.update({"status": "FILLED", "filled_size": "0.00001583"})
    with pytest.raises(recovery.ProofFailure, match="v15r3_waiting_child_fill_drift"):
        recovery.validate_v15r3_waiting_child_readback(filled)

    cancelled = deepcopy(open_child)
    cancelled["status"] = "CANCELLED"
    with pytest.raises(
        recovery.ProofFailure, match="v15r3_waiting_child_not_active"
    ):
        recovery.validate_v15r3_waiting_child_readback(cancelled)
