"""Exact schema-21 authority checks for the cancel-only V15R3 recovery."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import pytest

from application.admin_api import root_child_cancel as authority


ROOT_ID = "e4ad814e-c0d1-521a-a8c5-458243935ad2"
CHILD_ID = "e403d359-ecf3-59dc-b5b0-dfdd3c3efdaf"
ROOT_EXCHANGE_ID = "9eb2038c-5059-434c-a117-62ea0b804837"
CHILD_EXCHANGE_ID = "5bb903af-3c6e-4d0a-bd73-087f0dfead89"
R2_PLAN_SHA256 = (
    "0b9ab483459a986ad05200a6740a0de6dca63b6c5da197572c952ce8aef524c2"
)
R2_BATCH_ID = "bb88b375-66a3-5562-87bd-1e88ebceecda"
PORTFOLIO_ID = "62f28f44-8e72-4fe0-ace7-d71a01f54883"


def _proof_id(batch_id: str, purpose: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"coinbase://selected-child-cancel-v15r3/{batch_id}/{purpose}",
        )
    )


def _plan() -> dict[str, object]:
    approval_id = (
        "controlled-child-cancel-v15r3-"
        "11111111-1111-4111-8111-111111111111"
    )
    backend_commit = "a" * 40
    frontend_commit = "b" * 40
    runner_sha256 = "c" * 64
    batch_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "coinbase://selected-child-cancel-v15r3/"
            f"{backend_commit}/{runner_sha256}/{approval_id}",
        )
    )
    cancel = {
        "route": authority.ROOT_CHILD_CANCEL_ROUTE,
        "method": "POST",
        "root_client_order_id": ROOT_ID,
        "child_client_order_id": CHILD_ID,
        "active_exchange_order_id_evidence": CHILD_EXCHANGE_ID,
        "identity_key": "client_order_id",
        "identity_value": ROOT_ID,
        "operator_intent": "controlled_v15_test_profile_first_child_cancel",
        "actor_roles": ["trader"],
        "idempotency_key": _proof_id(batch_id, "child-cancel-idempotency"),
        "correlation_id": _proof_id(batch_id, "child-cancel-correlation"),
        "claim_id": _proof_id(batch_id, "child-cancel-claim"),
        "approval_snapshot_id": _proof_id(batch_id, "child-cancel-approval"),
        "admission_audit_id_source": "route_bound_runtime_proof",
        "cap_guard_decision_id": _proof_id(batch_id, "child-cancel-cap"),
        "reconciliation_plan_id": _proof_id(
            batch_id, "child-cancel-reconciliation"
        ),
        "controlled_plan_sha256_source": "plan_sha256",
        "semantic_retry_policy": "fresh_v15r3_idempotency_key_exactly_once",
        "exchange_order_id_fallback_authorized": False,
    }
    plan: dict[str, object] = {
        "schema_version": "21",
        "authority_kind": authority.CONTROLLED_V15R3_AUTHORITY_KIND,
        "approval_id": approval_id,
        "batch_id": batch_id,
        "created_at": "2026-07-13T03:00:00+00:00",
        "expires_at": "2026-07-13T05:00:00+00:00",
        "backend_commit": backend_commit,
        "frontend_commit": frontend_commit,
        "runner_sha256": runner_sha256,
        "profile_label": "Test",
        "portfolio_id": PORTFOLIO_ID,
        "product_id": "BTC-USDC",
        "placement_attempt_count": 0,
        "placement_attempt_schedule": [],
        "root_placement_maximum": 0,
        "child_placement_maximum": 0,
        "cancel_command_maximum": 1,
        "root_placement_authorized": False,
        "child_placement_authorized": False,
        "root_reference_cap_usdc": "9.99",
        "child_reference_cap_usdc": "2.00",
        "slice_reference_cap_usdc": "12.00",
        "root_actual_reference_notional_usdc": "1.0075796583",
        "active_child_reference_notional_usdc": "1.7049248762",
        "aggregate_reference_notional_usdc": "2.7125045345",
        "planned_reference_notional_usdc": "2.7125045345",
        "root_evidence": {
            "client_order_id": ROOT_ID,
            "exchange_order_id": ROOT_EXCHANGE_ID,
            "status": "FILLED",
            "filled_size": "0.00001583",
            "filled_value": "1.0075796583",
            "placement_authorized": False,
        },
        "child": {
            "client_order_id": CHILD_ID,
            "parent_client_order_id": ROOT_ID,
            "active_exchange_order_id": CHILD_EXCHANGE_ID,
            "origin_controlled_plan_sha256": R2_PLAN_SHA256,
            "origin_controlled_batch_id": R2_BATCH_ID,
        },
        "child_evidence": {
            "client_order_id": CHILD_ID,
            "parent_client_order_id": ROOT_ID,
            "exchange_order_id": CHILD_EXCHANGE_ID,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "status": "OPEN",
            "stealth_status": "REVEALED",
            "base_size": "0.00001583",
            "limit_price": "107702.14",
            "filled_size": "0",
            "filled_value": "0",
            "total_fees": "0",
            "number_of_fills": 0,
            "reference_notional_usdc": "1.7049248762",
            "origin_controlled_plan_sha256": R2_PLAN_SHA256,
            "origin_controlled_batch_id": R2_BATCH_ID,
            "placement_authorized": False,
            "exchange_order_id_evidence_only": True,
        },
        "v15r2_active_child_binding": {
            "r2_plan_sha256": R2_PLAN_SHA256,
            "r2_batch_id": R2_BATCH_ID,
            "root_client_order_id": ROOT_ID,
            "root_exchange_order_id": ROOT_EXCHANGE_ID,
            "child_client_order_id": CHILD_ID,
            "child_exchange_order_id": CHILD_EXCHANGE_ID,
            "r2_placement_attempt_count": 1,
            "r2_root_sdk_call_count": 0,
            "r2_child_sdk_call_count": 1,
            "r2_cancel_command_count": 0,
            "child_status": "OPEN",
            "child_zero_fill_proven": True,
            "child_reference_notional_usdc": "1.7049248762",
            "aggregate_reference_notional_usdc": "2.7125045345",
            "r2_proof_payload_hash": (
                "47ea2b0bdec88367454689f1a287b28bc17a353e8362a71473a9e84da39ced05"
            ),
            "failed_cancel_idempotency_key": (
                "cd7713ea-5841-5c8a-9aea-161a2eb32e31"
            ),
            "failed_cancel_correlation_id": (
                "cd79b000-9c19-58dd-9ce0-537d4823bdec"
            ),
            "failed_cancel_payload_hash": (
                "5875e395e1692d1c82c5fded7a3e80f75c568d449df9825a2593c1dfeb4769c6"
            ),
            "failed_cancel_audit_id": (
                "60018f6a-745d-4a43-9990-82b29928bbe8"
            ),
            "failed_cancel_http_status": 501,
            "failed_cancel_status": "not_implemented",
            "failed_cancel_live_exchange_submitted": False,
            "failed_cancel_live_coinbase_orders_ran": False,
            "failed_cancel_semantic_claim_acquired": False,
            "failed_cancel_exchange_boundary_called": False,
            "cancel_ledgers_empty": True,
            "r2_state_dir": authority.CONTROLLED_V15R2_STATE_DIR,
            "r2_parent_process_identity": dict(
                authority.CONTROLLED_V15R2_PARENT_PROCESS_IDENTITY
            ),
            "r2_runtime_process_identity": dict(
                authority.CONTROLLED_V15R2_RUNTIME_PROCESS_IDENTITY
            ),
            "source_paths": dict(authority.CONTROLLED_V15R2_SOURCE_PATHS),
            "source_hashes": dict(authority.CONTROLLED_V15R2_SOURCE_HASHES),
        },
        "local_active_child_binding": {
            "root_client_order_id": ROOT_ID,
            "root_status": "FILLED",
            "root_exchange_order_id": ROOT_EXCHANGE_ID,
            "root_correlation_id": "d85733d6-51af-5fd9-b287-6bddc4e547a4",
            "root_audit_id": "6089e672-8c15-4b9b-9645-41a78170d4d5",
            "child_client_order_id": CHILD_ID,
            "child_parent_status": "OPEN",
            "child_size": "0.00001583",
            "child_limit_price": "107702.14",
            "child_exchange_order_id": CHILD_EXCHANGE_ID,
            "child_correlation_id": "d85733d6-51af-5fd9-b287-6bddc4e547a4",
            "child_audit_id": "6089e672-8c15-4b9b-9645-41a78170d4d5",
            "child_stealth_status": "REVEALED",
            "revealed_size": "0.00001583",
            "executed_size": "0",
            "remaining_size": "0",
            "active_placement_client_order_id": CHILD_ID,
            "active_exchange_order_id": CHILD_EXCHANGE_ID,
            "active_exchange_price": "107702.14",
            "controlled_plan_sha256": R2_PLAN_SHA256,
            "controlled_batch_id": R2_BATCH_ID,
            "reference_notional_usdc": "1.7049248762",
            "direct_child_client_order_ids": [],
            "nested_child_client_order_ids": [],
        },
        "actor_id": "operator-controlled-spot-proof",
        "actor_roles": ["trader"],
        "child_cancel_operator_intent": (
            "controlled_v15_test_profile_first_child_cancel"
        ),
        "cancel_command": cancel,
        "retry_authorized": False,
        "substitution_authorized": False,
        "later_child_authorized": False,
        "browser_derives_child_identity": False,
        "exchange_order_id_evidence_only": True,
        "exchange_order_id_fallback_authorized": False,
        "plan_sha256": "",
    }
    plan["plan_sha256"] = authority._canonical_plan_hash(plan)
    return plan


def _write_owner_only(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _marker_handoff(
    plan: dict[str, object],
    *,
    plan_path: Path,
    handoff_path: Path,
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    batch_id = str(plan["batch_id"])
    cancel = dict(plan["cancel_command"])
    marker = {
        "schema_version": "1",
        "authority": authority.CONTROLLED_V15R3_AUTHORITY_KIND,
        "approval_id": plan["approval_id"],
        "batch_id": batch_id,
        "plan_file": str(plan_path),
        "plan_sha256": plan["plan_sha256"],
        "backend_commit": plan["backend_commit"],
        "frontend_commit": plan["frontend_commit"],
        "runner_sha256": plan["runner_sha256"],
        "profile_label": "Test",
        "portfolio_id": PORTFOLIO_ID,
        "product_id": "BTC-USDC",
        "root_client_order_id": ROOT_ID,
        "child_client_order_id": CHILD_ID,
        "placement_attempt_maximum": 0,
        "root_placement_maximum": 0,
        "child_placement_maximum": 0,
        "cancel_command_maximum": 1,
        "placement_ledger_path": str(tmp_path / "placements.jsonl"),
        "cancel_ledger_path": str(tmp_path / "cancel.jsonl"),
        "backend_claim_log_path": str(tmp_path / "claims.jsonl"),
        "handoff_path": str(handoff_path),
        "registered_at": "2026-07-13T03:01:00+00:00",
        "process_id": 1234,
    }
    handoff = {
        "schema_version": "1",
        "authority": authority.CONTROLLED_V15R3_AUTHORITY_KIND,
        "plan_sha256": plan["plan_sha256"],
        "batch_id": batch_id,
        "root_client_order_id": ROOT_ID,
        "child_client_order_id": CHILD_ID,
        "approval_snapshot_id": cancel["approval_snapshot_id"],
        "admission_audit_id": _proof_id(batch_id, "child-cancel-audit"),
        "cap_guard_decision_id": cancel["cap_guard_decision_id"],
        "reconciliation_plan_id": cancel["reconciliation_plan_id"],
        "route": authority.ROOT_CHILD_CANCEL_ROUTE,
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": ROOT_ID,
        "action_class": "live_exchange_cancel",
        "required_permission": "order:cancel",
        "service_method": authority.ROOT_CHILD_CANCEL_SERVICE_METHOD,
        "actor_id": "operator-controlled-spot-proof",
        "actor_roles": ["trader"],
        "operator_intent": cancel["operator_intent"],
        "command_idempotency_key": cancel["idempotency_key"],
        "payload_hash": "d" * 64,
        "idempotency_key": cancel["idempotency_key"],
        "correlation_id": cancel["correlation_id"],
        "recorded_at": "2026-07-13T03:01:01+00:00",
    }
    return marker, handoff


def test_v15r3_exact_cancel_only_plan_validates_dispatches_and_scopes_root() -> None:
    plan = _plan()

    assert authority.is_controlled_v15r3_recovery_plan(plan) is True
    authority.validate_controlled_v15r3_recovery_plan_scope(plan)
    authority.validate_controlled_child_cancel_plan_scope(plan)
    assert authority.controlled_child_cancel_root_scope(plan) == plan["root_evidence"]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda plan: plan.update({"child_placement_maximum": 1}),
        lambda plan: plan.update({"actor_roles": ["admin"]}),
        lambda plan: plan.update(
            {"active_child_reference_notional_usdc": "1.7049248763"}
        ),
        lambda plan: plan["child_evidence"].update({"filled_size": "0.1"}),
        lambda plan: plan["v15r2_active_child_binding"].update(
            {"r2_child_sdk_call_count": 0}
        ),
        lambda plan: plan["v15r2_active_child_binding"][
            "r2_runtime_process_identity"
        ].update({"start_identity": "16871270"}),
        lambda plan: plan["cancel_command"].update(
            {"idempotency_key": "cd7713ea-5841-5c8a-9aea-161a2eb32e31"}
        ),
    ],
)
def test_v15r3_rejects_scope_actor_zero_fill_source_or_fresh_id_drift(
    mutator,
) -> None:
    plan = _plan()
    mutator(plan)
    plan["plan_sha256"] = authority._canonical_plan_hash(plan)

    with pytest.raises(
        authority.AdminRootChildCancelAuthorityError,
        match="controlled_v15r3_plan_schema_invalid",
    ):
        authority.validate_controlled_child_cancel_plan_scope(plan)


def test_v15r3_loader_binds_zero_placement_marker_and_exact_actor_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    plan_path = tmp_path / "plan.json"
    marker_path = tmp_path / "marker.json"
    handoff_path = tmp_path / "handoff.json"
    marker, handoff = _marker_handoff(
        plan,
        plan_path=plan_path,
        handoff_path=handoff_path,
        tmp_path=tmp_path,
    )
    for filename in ("placements.jsonl", "cancel.jsonl", "claims.jsonl"):
        (tmp_path / filename).touch(mode=0o600)
    _write_owner_only(plan_path, plan)
    _write_owner_only(marker_path, marker)
    _write_owner_only(handoff_path, handoff)
    monkeypatch.setenv(authority.CONTROLLED_V15_PLAN_PATH_ENV, str(plan_path))
    monkeypatch.setenv(
        authority.CONTROLLED_V15_PLAN_SHA256_ENV, str(plan["plan_sha256"])
    )
    monkeypatch.setenv(authority.CONTROLLED_V15_MARKER_PATH_ENV, str(marker_path))
    monkeypatch.setenv(authority.CONTROLLED_V15_HANDOFF_PATH_ENV, str(handoff_path))

    loaded = authority.load_controlled_v15_plan_authority()

    assert loaded["plan"] == plan
    assert loaded["handoff"]["actor_roles"] == ["trader"]

    drifted = deepcopy(handoff)
    drifted["actor_roles"] = ["admin"]
    _write_owner_only(handoff_path, drifted)
    with pytest.raises(
        authority.AdminRootChildCancelAuthorityError,
        match="controlled_v15_plan_marker_binding_mismatch",
    ):
        authority.load_controlled_v15_plan_authority()
