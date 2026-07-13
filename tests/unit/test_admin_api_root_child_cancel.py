from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest

from application.admin_api.command_service import (
    CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
    AdminApiCommandDependencies,
    AdminApiCommandService,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    AdminLiveAdmissionDecisionEvidence,
    AdminOrderFillFollowUpChildCancelCommand,
    AdminOrderFillFollowUpChildCancelRequest,
)
from application.admin_api.root_child_cancel import (
    AdminRootChildCancelAuthorityError,
    AdminRootChildCancelClaimStoreError,
    FileAdminRootChildCancelClaimStore,
    load_controlled_v15_plan_authority,
    validate_controlled_v15r2_recovery_plan_scope,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiPermission,
)


ROOT_ID = "11111111-1111-4111-8111-111111111111"
CHILD_ID = str(
    uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"coinbase://filled-follow-up/{ROOT_ID}/{ROOT_ID}",
    )
)
EXCHANGE_ID = "33333333-3333-4333-8333-333333333333"
PORTFOLIO_ID = "62f28f44-8e72-4fe0-ace7-d71a01f54883"
BATCH_ID = "44444444-4444-5444-8444-444444444444"
PLAN_SHA256 = "a" * 64
R2_ROOT_ID = "e4ad814e-c0d1-521a-a8c5-458243935ad2"
R2_CHILD_ID = "e403d359-ecf3-59dc-b5b0-dfdd3c3efdaf"
R2_ROOT_EXCHANGE_ID = "9eb2038c-5059-434c-a117-62ea0b804837"
R1_PLAN_SHA256 = (
    "24fc4e211d87c7c3a95d87002f9894ff3119f1e08a48aa4d1ab68c00c7f138ed"
)
ROUTE = (
    "/api/v1/orders/{root_client_order_id}/fill-follow-up/"
    "child-cancel"
)


class _ReadService:
    def __init__(self) -> None:
        self.chain = SimpleNamespace(
            found=True,
            root_parent_client_order_id=ROOT_ID,
            parent_client_order_id=None,
            root_order=SimpleNamespace(
                client_order_id=ROOT_ID,
                product_id="BTC-USDC",
                side="BUY",
                status="FILLED",
                ownership_provenance="ADMIN_MANUAL_ROOT",
                retail_portfolio_id=PORTFOLIO_ID,
            ),
            follow_up_children=[
                SimpleNamespace(
                    client_order_id=CHILD_ID,
                    parent_order_id=ROOT_ID,
                    product_id="BTC-USDC",
                    side="SELL",
                    status="OPEN",
                    ownership_provenance="ADMIN_FILL_FOLLOW_UP",
                    retail_portfolio_id=PORTFOLIO_ID,
                )
            ],
            follow_up_child_client_order_ids=[CHILD_ID],
            follow_up_child_count=1,
            duplicate_child_client_order_ids=[],
            nested_child_client_order_ids=[],
            nested_parent_client_order_ids=[],
            flat_hierarchy_violation_count=0,
            portfolio_scope=SimpleNamespace(
                profile_alias="Test",
                expected_portfolio_id=PORTFOLIO_ID,
                root_portfolio_id=PORTFOLIO_ID,
                child_portfolio_ids={CHILD_ID: PORTFOLIO_ID},
                scope_consistent=True,
                status="matched",
            ),
            blockers=[],
        )
        self.detail = SimpleNamespace(
            found=True,
            order=SimpleNamespace(
                stealth_order_id=CHILD_ID,
                parent_stealth_order_id=ROOT_ID,
                product_id="BTC-USDC",
                side="SELL",
                status="REVEALED",
                executed_size="0",
                active_placement_client_order_id=CHILD_ID,
                active_exchange_order_id=EXCHANGE_ID,
                anchor_repricing_state={
                    "controlled_admin_first_child_reveal_preparation": {
                        "batch_id": BATCH_ID,
                        "batch_slot": 1,
                        "controlled_plan_sha256": PLAN_SHA256,
                        "portfolio_id": PORTFOLIO_ID,
                        "root_client_order_id": ROOT_ID,
                        "stealth_order_id": CHILD_ID,
                    }
                },
            ),
        )

    def build_order_fill_follow_up_chain(self, *, client_order_id: str):
        assert client_order_id == ROOT_ID
        return self.chain

    def build_stealth_order_detail(self, *, stealth_order_id: str):
        assert stealth_order_id == CHILD_ID
        return self.detail


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.read_controlled_first_child.return_value = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "retail_portfolio_id": PORTFOLIO_ID,
        "status": "REVEALED",
        "active_placement_client_order_id": CHILD_ID,
        "active_exchange_order_id": EXCHANGE_ID,
        "executed_size": "0",
        "controlled_plan_sha256": PLAN_SHA256,
    }
    return runtime


def _exchange_readback(*_args, **_kwargs):
    return {
        "authoritative": True,
        "pagination_complete": True,
        "exact_identity_match": True,
        "authoritative_status": "OPEN",
        "exchange_order_id": EXCHANGE_ID,
        "matched_order": {
            "client_order_id": CHILD_ID,
            "order_id": EXCHANGE_ID,
            "product_id": "BTC-USDC",
            "product_type": "SPOT",
            "retail_portfolio_id": PORTFOLIO_ID,
            "side": "SELL",
            "status": "OPEN",
            "filled_size": "0",
            "filled_value": "0",
            "total_fees": "0",
            "number_of_fills": 0,
            "base_size": "0.00001718",
            "limit_price": "104772.99",
        },
    }


def _plan_authority():
    plan = {
        "schema_version": "19",
        "authority_kind": "selected_chain_child_cancel_v15",
        "approval_id": "controlled-child-cancel-v15-test",
        "batch_id": BATCH_ID,
        "created_at": "2099-07-12T20:30:00+00:00",
        "expires_at": "2099-07-12T22:30:00+00:00",
        "backend_production_commit": "1" * 40,
        "backend_runner_commit": "2" * 40,
        "frontend_commit": "3" * 40,
        "runner_sha256": "4" * 64,
        "v14_completion_binding": {},
        "profile_label": "Test",
        "portfolio_id": PORTFOLIO_ID,
        "product_id": "BTC-USDC",
        "root_operator_intent": (
            "execute_one_approved_intentional_test_profile_spot_fill"
        ),
        "child_reveal_operator_intent": (
            "controlled_v15_test_profile_first_child_reveal"
        ),
        "child_cancel_operator_intent": (
            CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT
        ),
        "placement_attempt_count": 2,
        "root_placement_maximum": 1,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "placement_attempt_schedule": ["root", "child"],
        "root_reference_notional_usdc": "1.10",
        "child_reference_reserve_usdc": "2.00",
        "planned_reference_notional_usdc": "3.10",
        "conservative_reference_notional_usdc": "11.99",
        "root_submitted_cap_usdc": "9.99",
        "child_submitted_cap_usdc": "2.00",
        "slice_reference_cap_usdc": "12.00",
        "best_bid_at_plan": "64000.00",
        "best_ask_at_plan": "64000.01",
        "market_observed_at_plan": "2099-07-12T20:29:59+00:00",
        "market_source_at_plan": (
            "coinbase_rest_get_best_bid_ask_exact_product"
        ),
        "root": {
            "client_order_id": ROOT_ID,
            "order": {
                "client_order_id": ROOT_ID,
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_type": "LIMIT",
                "base_size": "0.0000171875",
                "limit_price": "64000.00",
                "post_only": False,
                "time_in_force": "FILL_OR_KILL",
                "manual_live_acknowledgement": True,
            },
            "approval_snapshot_id": "root-approval",
            "cap_guard_decision_id": "root-cap",
            "reconciliation_plan_id": "root-recon",
        },
        "child": {
            "client_order_id": CHILD_ID,
            "parent_client_order_id": ROOT_ID,
            "order_policy": {
                "product_id": "BTC-USDC",
                "side": "SELL",
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": False,
                "base_size_source": "authoritative_root_filled_size",
                "minimum_fresh_bid_ratio": "1.60",
                "target_fresh_bid_ratio": "1.70",
                "strict_max_notional_usdc": "2.00",
            },
            "approval_snapshot_id": "child-approval",
            "cap_guard_decision_id": "child-cap",
            "reconciliation_plan_id": "child-recon",
        },
        "cancel_command": {
            "route": ROUTE,
            "method": "POST",
            "root_client_order_id": ROOT_ID,
            "child_client_order_id": CHILD_ID,
            "identity_key": "client_order_id",
            "identity_value": ROOT_ID,
            "operator_intent": (
                CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT
            ),
            "idempotency_key": "idem-v15-cancel",
            "correlation_id": "corr-v15-cancel",
            "claim_id": "claim-v15",
            "approval_snapshot_id": "approval-v15",
            "admission_audit_id_source": "route_bound_runtime_proof",
            "cap_guard_decision_id": "cap-v15",
            "reconciliation_plan_id": "recon-v15",
            "controlled_plan_sha256_source": "plan_sha256",
            "semantic_retry_policy": "same_idempotency_key_only",
        },
        "retry_authorized": False,
        "substitution_authorized": False,
        "later_child_authorized": False,
        "browser_derives_child_identity": False,
        "exchange_order_id_evidence_only": True,
        "plan_sha256": PLAN_SHA256,
    }
    marker = {
        "plan_sha256": PLAN_SHA256,
        "batch_id": BATCH_ID,
        "portfolio_id": PORTFOLIO_ID,
        "product_id": "BTC-USDC",
        "root_client_order_id": ROOT_ID,
        "child_client_order_id": CHILD_ID,
        "registered_at": "2099-07-12T20:31:00+00:00",
    }
    handoff = {
        "plan_sha256": PLAN_SHA256,
        "batch_id": BATCH_ID,
        "root_client_order_id": ROOT_ID,
        "child_client_order_id": CHILD_ID,
        "approval_snapshot_id": "approval-v15",
        "admission_audit_id": "audit-v15",
        "cap_guard_decision_id": "cap-v15",
        "reconciliation_plan_id": "recon-v15",
        "route": ROUTE,
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": ROOT_ID,
        "action_class": "live_exchange_cancel",
        "required_permission": "order:cancel",
        "service_method": (
            "cancel_order_fill_follow_up_child_by_root_client_order_id"
        ),
        "actor_id": "operator@example.com",
        "command_idempotency_key": "idem-v15-cancel",
        "idempotency_key": "idem-v15-cancel",
        "correlation_id": "corr-v15-cancel",
        "operator_intent": (
            CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT
        ),
        "payload_hash": "b" * 64,
    }
    return {
        "plan": plan,
        "marker": marker,
        "handoff": handoff,
        "source": "test_v15_authority",
    }


def _recovery_plan_authority() -> dict[str, object]:
    approval_id = (
        "controlled-child-cancel-v15r2-"
        "11111111-1111-4111-8111-111111111111"
    )
    backend_commit = "5" * 40
    runner_sha256 = "6" * 64
    batch_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "coinbase://selected-child-cancel-v15r2/"
            f"{backend_commit}/{runner_sha256}/{approval_id}",
        )
    )

    def proof_id(purpose: str) -> str:
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "coinbase://selected-child-cancel-v15r2/"
                f"{batch_id}/{purpose}",
            )
        )

    registry = "/var/tmp/coinbase-admin-controlled-spot-root-child-batches"
    state_dir = (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T012938Z-24703c84"
    )
    source_paths = {
        "plan_path": (
            "/home/ec2-user/.local/state/"
            "coinbase-controlled-spot-child-cancel-v15r1-20260713.plan.json"
        ),
        "marker_path": (
            f"{registry}/test-profile-btc-usdc-selected-child-cancel-"
            "v15r1-20260713.authority.json"
        ),
        "ledger_path": (
            f"{registry}/test-profile-btc-usdc-selected-child-cancel-"
            "v15r1-20260713.placements.jsonl"
        ),
        "cancel_ledger_path": (
            f"{registry}/test-profile-btc-usdc-selected-child-cancel-"
            "v15r1-20260713.cancel-command.jsonl"
        ),
        "backend_claim_log_path": (
            f"{registry}/test-profile-btc-usdc-selected-child-cancel-"
            "v15r1-20260713.backend-claims.jsonl"
        ),
        "handoff_path": (
            f"{registry}/test-profile-btc-usdc-selected-child-cancel-"
            "v15r1-20260713.handoff.json"
        ),
        "audit_path": f"{state_dir}/audit.jsonl",
        "sentinel_path": f"{state_dir}/sdk-boundary-sentinel.json",
        "parent_authority_loss_path": (
            f"{state_dir}/parent-authority-loss.json"
        ),
    }
    source_hashes = {
        "plan_bytes_sha256": (
            "f9f79ba28444de532352200afa0703e01838e7b674cd849e287735d17dac7c08"
        ),
        "marker_bytes_sha256": (
            "ed9ab94189b2eb0e2b665a0c0784b01b2b948cee12d8fb8af8d8a03a6a238511"
        ),
        "ledger_bytes_sha256": (
            "474f931ce453a57c1b2a0a741d2a0207d7929684e9e9bf33f25562828888770c"
        ),
        "cancel_ledger_bytes_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "backend_claim_log_bytes_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "audit_bytes_sha256": (
            "cbc8ff26e0fa23c12d51f2094543e20807181e6d5c5192ca89044c113496a1e5"
        ),
        "sentinel_bytes_sha256": (
            "6a7888eeb50b8fb2d656c9f0068f7e7fc6e1753b114cf7e80094c78a2ca80e0f"
        ),
        "parent_authority_loss_bytes_sha256": "b6af47512d0261259740dc6077356580b82049f7d4dcd1d5301f8df627e1fc15",
    }
    recovery_binding = {
        "r1_plan_sha256": R1_PLAN_SHA256,
        "r1_batch_id": "fb2ca86c-7ff3-5493-a1bd-d3a73fc1e322",
        "r1_root_client_order_id": R2_ROOT_ID,
        "r1_child_client_order_id": R2_CHILD_ID,
        "r1_root_exchange_order_id": R2_ROOT_EXCHANGE_ID,
        "r1_attempt_count": 2,
        "r1_root_sdk_call_count": 1,
        "r1_child_sdk_call_count": 0,
        "root_filled_size": "0.00001583",
        "root_filled_value": "1.0075796583",
        "root_fill_count": 1,
        "fill_pagination_complete": True,
        "fill_pagination_proof_source": (
            "sealed_admin_fill_readback_proof_contract"
        ),
        "active_spot_order_count": 0,
        "handoff_absent": True,
        "cancel_ledgers_empty": True,
        "source_paths": source_paths,
        "source_hashes": source_hashes,
        "direct_fill_proof_key": (
            "spot_fill_readback:e4ad814e-c0d1-521a-a8c5-458243935ad2:"
            "audit-18ecf7f4-a489-5f3f-968f-4ce8167cdc90"
        ),
        "direct_fill_proof_canonical_sha256": (
            "f8428444e8b2a6193ef49bd76d1e4d1fa8178f31ee492ef48368d3920f48bfad"
        ),
    }
    plan: dict[str, object] = {
        "schema_version": "20",
        "authority_kind": "selected_chain_child_cancel_recovery_v15r2",
        "approval_id": approval_id,
        "batch_id": batch_id,
        "created_at": "2099-07-13T02:00:00+00:00",
        "expires_at": "2099-07-13T04:00:00+00:00",
        "backend_commit": backend_commit,
        "frontend_commit": "8" * 40,
        "runner_sha256": runner_sha256,
        "v15r1_recovery_binding": recovery_binding,
        "local_hidden_child_binding": {
            "root_client_order_id": R2_ROOT_ID,
            "root_status": "FILLED",
            "root_exchange_order_id": R2_ROOT_EXCHANGE_ID,
            "root_correlation_id": "sealed-root-correlation",
            "root_audit_id": "sealed-root-audit",
            "child_client_order_id": R2_CHILD_ID,
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
        },
        "profile_label": "Test",
        "portfolio_id": PORTFOLIO_ID,
        "product_id": "BTC-USDC",
        "placement_attempt_count": 1,
        "placement_attempt_schedule": ["child"],
        "root_placement_maximum": 0,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "root_placement_authorized": False,
        "root_reference_cap_usdc": "9.99",
        "root_actual_reference_notional_usdc": "1.0075796583",
        "child_submitted_cap_usdc": "2",
        "slice_reference_cap_usdc": "12",
        "planned_reference_notional_usdc": "3.0075796583",
        "conservative_reference_notional_usdc": "11.99",
        "root_evidence": {
            "client_order_id": R2_ROOT_ID,
            "exchange_order_id": R2_ROOT_EXCHANGE_ID,
            "status": "FILLED",
            "filled_size": "0.00001583",
            "filled_value": "1.0075796583",
            "placement_authorized": False,
        },
        "child": {
            "client_order_id": R2_CHILD_ID,
            "parent_client_order_id": R2_ROOT_ID,
            "approval_snapshot_id": proof_id("child-reveal-approval"),
            "cap_guard_decision_id": proof_id("child-reveal-cap"),
            "reconciliation_plan_id": proof_id(
                "child-reveal-reconciliation"
            ),
            "order_policy": {
                "product_id": "BTC-USDC",
                "side": "SELL",
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": False,
                "base_size": "0.00001583",
                "minimum_fresh_bid_ratio": "1.6",
                "target_fresh_bid_ratio": "1.7",
                "strict_max_notional_usdc": "2",
            },
        },
        "child_reveal_operator_intent": (
            "controlled_v15_test_profile_first_child_reveal"
        ),
        "child_cancel_operator_intent": (
            CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT
        ),
        "cancel_command": {
            "route": ROUTE,
            "method": "POST",
            "root_client_order_id": R2_ROOT_ID,
            "child_client_order_id": R2_CHILD_ID,
            "identity_key": "client_order_id",
            "identity_value": R2_ROOT_ID,
            "operator_intent": CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            "idempotency_key": proof_id("child-cancel-idempotency"),
            "correlation_id": proof_id("child-cancel-correlation"),
            "claim_id": proof_id("child-cancel-claim"),
            "approval_snapshot_id": proof_id("child-cancel-approval"),
            "admission_audit_id_source": "route_bound_runtime_proof",
            "cap_guard_decision_id": proof_id("child-cancel-cap"),
            "reconciliation_plan_id": proof_id(
                "child-cancel-reconciliation"
            ),
            "controlled_plan_sha256_source": "plan_sha256",
            "semantic_retry_policy": "same_idempotency_key_only",
        },
        "retry_authorized": False,
        "substitution_authorized": False,
        "later_child_authorized": False,
        "browser_derives_child_identity": False,
        "exchange_order_id_evidence_only": True,
    }
    encoded = json.dumps(
        plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    import hashlib

    plan_hash = hashlib.sha256(encoded).hexdigest()
    plan["plan_sha256"] = plan_hash
    cancel = dict(plan["cancel_command"])
    marker = {
        "schema_version": "1",
        "authority": "selected_chain_child_cancel_recovery_v15r2",
        "approval_id": approval_id,
        "batch_id": batch_id,
        "plan_file": "/sealed/v15r2/plan.json",
        "plan_sha256": plan_hash,
        "backend_commit": backend_commit,
        "frontend_commit": plan["frontend_commit"],
        "runner_sha256": runner_sha256,
        "profile_label": "Test",
        "portfolio_id": PORTFOLIO_ID,
        "product_id": "BTC-USDC",
        "root_client_order_id": R2_ROOT_ID,
        "child_client_order_id": R2_CHILD_ID,
        "placement_attempt_maximum": 1,
        "root_placement_maximum": 0,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "placement_ledger_path": "/sealed/v15r2/placements.jsonl",
        "cancel_ledger_path": "/sealed/v15r2/cancel.jsonl",
        "backend_claim_log_path": "/sealed/v15r2/backend-claims.jsonl",
        "handoff_path": "/sealed/v15r2/handoff.json",
        "registered_at": "2099-07-13T02:01:00+00:00",
        "process_id": 123,
    }
    handoff = {
        "schema_version": "1",
        "authority": "selected_chain_child_cancel_recovery_v15r2",
        "plan_sha256": plan_hash,
        "batch_id": batch_id,
        "root_client_order_id": R2_ROOT_ID,
        "child_client_order_id": R2_CHILD_ID,
        "approval_snapshot_id": cancel["approval_snapshot_id"],
        "admission_audit_id": "audit-v15",
        "cap_guard_decision_id": cancel["cap_guard_decision_id"],
        "reconciliation_plan_id": cancel["reconciliation_plan_id"],
        "route": ROUTE,
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": R2_ROOT_ID,
        "action_class": "live_exchange_cancel",
        "required_permission": "order:cancel",
        "service_method": (
            "cancel_order_fill_follow_up_child_by_root_client_order_id"
        ),
        "actor_id": "operator@example.com",
        "operator_intent": CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
        "command_idempotency_key": cancel["idempotency_key"],
        "payload_hash": "b" * 64,
        "idempotency_key": cancel["idempotency_key"],
        "correlation_id": cancel["correlation_id"],
        "recorded_at": "2099-07-13T02:02:00+00:00",
    }
    return {
        "plan": plan,
        "marker": marker,
        "handoff": handoff,
        "source": "test_v15r2_authority",
    }


@pytest.mark.parametrize(
    ("field", "container"),
    [
        ("executed_size", "runtime"),
        ("filled_size", "exchange"),
        ("filled_value", "exchange"),
        ("total_fees", "exchange"),
        ("number_of_fills", "exchange"),
        ("pagination_complete", "readback"),
    ],
)
def test_root_child_cancel_readiness_requires_explicit_zero_fill_fields(
    tmp_path,
    monkeypatch,
    field,
    container,
):
    service, _read_service, runtime, _rest, _claims = _service(
        tmp_path,
        monkeypatch,
    )
    if container == "runtime":
        runtime_row = dict(runtime.read_controlled_first_child.return_value)
        runtime_row.pop(field)
        runtime.read_controlled_first_child.return_value = runtime_row
    else:
        readback = deepcopy(_exchange_readback())
        if container == "readback":
            readback.pop(field)
        else:
            readback["matched_order"].pop(field)
        monkeypatch.setattr(
            "application.admin_api.command_service.exact_coinbase_order_readback",
            lambda *_args, **_kwargs: readback,
        )

    readiness = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=ROOT_ID,
        controlled_plan_sha256=PLAN_SHA256,
    )

    assert readiness.ready is False
    expected = (
        "active_first_child_identity_unproven"
        if container == "runtime"
        else (
            "active_child_exchange_identity_unproven"
            if container == "readback"
            else "active_child_zero_fill_unproven"
        )
    )
    assert expected in readiness.blockers


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("placement_attempt_count", 3),
        ("root_placement_maximum", 0),
        ("placement_attempt_schedule", ["child"]),
        ("cancel_command_maximum", 2),
        ("slice_reference_cap_usdc", "30.00"),
        ("conservative_reference_notional_usdc", "12.00"),
        ("retry_authorized", True),
    ],
)
def test_root_child_cancel_readiness_rejects_rehashed_broadened_authority(
    tmp_path,
    monkeypatch,
    field,
    value,
):
    authority = _plan_authority()
    authority["plan"] = deepcopy(authority["plan"])
    authority["plan"][field] = value
    service, *_ = _service(tmp_path, monkeypatch)
    service.dependencies.controlled_v15_plan_authority_getter = lambda: authority

    readiness = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=ROOT_ID,
        controlled_plan_sha256=PLAN_SHA256,
    )

    assert readiness.ready is False
    assert "controlled_v15_plan_schema_invalid" in readiness.blockers


def _service(tmp_path, monkeypatch):
    read_service = _ReadService()
    runtime = _runtime()
    rest_client = MagicMock()
    claim_store = FileAdminRootChildCancelClaimStore(
        tmp_path / "root-child-cancel-claims.jsonl"
    )
    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        _exchange_readback,
    )
    common = {
        "route": ROUTE,
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": ROOT_ID,
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        "required_permission": AdminApiPermission.ORDER_CANCEL,
        "operator_intent": CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
        "idempotency_key": "idem-v15-cancel",
        "payload_hash": "b" * 64,
    }
    approval = SimpleNamespace(
        **common,
        approval_id="approval-v15",
        requested_by_actor_id="operator@example.com",
        cap_guard_decision_ref="cap-v15",
        reconciliation_plan_ref="recon-v15",
        is_expired=lambda: False,
    )
    audit = SimpleNamespace(
        audit_id="audit-v15",
        admission_decision=_admission(idempotency_key="idem-v15-cancel"),
        live_exchange_submitted=False,
    )
    cap = SimpleNamespace(
        **common,
        decision_id="cap-v15",
        actor_id="operator@example.com",
        approval_snapshot_id="approval-v15",
        admission_audit_id="audit-v15",
        allowed=True,
        status=AdminApiGateStatus.PASSED,
    )
    reconciliation = SimpleNamespace(
        **common,
        plan_id="recon-v15",
        actor_id="operator@example.com",
        approval_snapshot_id="approval-v15",
        admission_audit_id="audit-v15",
        cap_guard_decision_id="cap-v15",
        allowed=True,
        status=AdminApiGateStatus.PASSED,
        post_submit_reconciliation_required=True,
    )
    approval_store = SimpleNamespace(
        find_by_approval_id=lambda _value: approval,
        approval_is_revoked=lambda _value: False,
    )
    audit_store = SimpleNamespace(find_by_audit_id=lambda _value: audit)
    cap_store = SimpleNamespace(find_by_decision_id=lambda _value: cap)
    reconciliation_store = SimpleNamespace(
        find_by_plan_id=lambda _value: reconciliation
    )
    dependencies = AdminApiCommandDependencies(
        rest_client=rest_client,
        rest_client_available=True,
        spot_portfolio_id=PORTFOLIO_ID,
        spot_portfolio_label="Test",
        read_service_getter=lambda: read_service,
        stealth_order_runtime_getter=lambda: runtime,
        root_child_cancel_claim_store_getter=lambda: claim_store,
        controlled_v15_plan_authority_getter=_plan_authority,
        approval_store_getter=lambda: approval_store,
        audit_store_getter=lambda: audit_store,
        cap_guard_store_getter=lambda: cap_store,
        reconciliation_store_getter=lambda: reconciliation_store,
    )
    return (
        AdminApiCommandService(dependencies),
        read_service,
        runtime,
        rest_client,
        claim_store,
    )


def _admission(*, idempotency_key: str, allowed: bool = True):
    return AdminLiveAdmissionDecisionEvidence(
        status=(AdminApiGateStatus.PASSED if allowed else AdminApiGateStatus.BLOCKED),
        allowed=allowed,
        route=ROUTE,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=ROOT_ID,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="cancel_order_fill_follow_up_child_by_root_client_order_id",
        actor_id="operator@example.com",
        idempotency_key=idempotency_key,
        operator_intent=CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
        payload_hash="b" * 64,
        approval_snapshot_present=allowed,
        approval_snapshot_id="approval-v15" if allowed else None,
        admission_audit_present=allowed,
        admission_audit_id="audit-v15" if allowed else None,
        cap_guard_present=allowed,
        cap_guard_decision_id="cap-v15" if allowed else None,
        reconciliation_plan_present=allowed,
        reconciliation_plan_id="recon-v15" if allowed else None,
        live_execution_service_present=allowed,
        detail="test admission",
    )


def test_v15r2_recovery_plan_scope_is_strict_and_child_only():
    authority = _recovery_plan_authority()
    plan = authority["plan"]

    validate_controlled_v15r2_recovery_plan_scope(plan)

    broadened = deepcopy(plan)
    broadened["root_placement_maximum"] = 1
    with pytest.raises(
        AdminRootChildCancelAuthorityError,
        match="controlled_v15r2_plan_schema_invalid",
    ):
        validate_controlled_v15r2_recovery_plan_scope(broadened)

    root_order_added = deepcopy(plan)
    root_order_added["root_evidence"]["order"] = {"side": "BUY"}
    with pytest.raises(
        AdminRootChildCancelAuthorityError,
        match="controlled_v15r2_plan_schema_invalid",
    ):
        validate_controlled_v15r2_recovery_plan_scope(root_order_added)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_top_level",
        "root_in_schedule",
        "burned_child_sdk_call",
        "active_local_exchange",
        "root_fill_drift",
        "root_cap_drift",
    ],
)
def test_v15r2_recovery_plan_scope_rejects_binding_or_cap_drift(mutation):
    plan = deepcopy(_recovery_plan_authority()["plan"])
    if mutation == "extra_top_level":
        plan["extra_authority"] = True
    elif mutation == "root_in_schedule":
        plan["placement_attempt_schedule"] = ["root", "child"]
    elif mutation == "burned_child_sdk_call":
        plan["v15r1_recovery_binding"]["r1_child_sdk_call_count"] = 1
    elif mutation == "active_local_exchange":
        plan["local_hidden_child_binding"]["active_exchange_order_id"] = (
            R2_ROOT_EXCHANGE_ID
        )
    elif mutation == "root_fill_drift":
        plan["root_evidence"]["filled_value"] = "1.01"
    else:
        plan["root_reference_cap_usdc"] = "10.00"

    with pytest.raises(
        AdminRootChildCancelAuthorityError,
        match="controlled_v15r2_plan_schema_invalid",
    ):
        validate_controlled_v15r2_recovery_plan_scope(plan)


def test_v15r2_authority_loader_requires_exact_marker_budgets_and_handoff(
    tmp_path,
    monkeypatch,
):
    authority = _recovery_plan_authority()
    plan_path = tmp_path / "v15r2-plan.json"
    marker_path = tmp_path / "v15r2-marker.json"
    handoff_path = tmp_path / "v15r2-handoff.json"
    marker = deepcopy(authority["marker"])
    marker["plan_file"] = str(plan_path)
    marker["handoff_path"] = str(handoff_path)

    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)

    write(plan_path, authority["plan"])
    write(marker_path, marker)
    write(handoff_path, authority["handoff"])
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_CONTROLLED_V15_PLAN_PATH", str(plan_path)
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_CONTROLLED_V15_PLAN_SHA256",
        str(authority["plan"]["plan_sha256"]),
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_CONTROLLED_V15_MARKER_PATH", str(marker_path)
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_CONTROLLED_V15_HANDOFF_PATH", str(handoff_path)
    )

    loaded = load_controlled_v15_plan_authority()
    assert loaded["plan"] == authority["plan"]
    assert loaded["marker"]["root_placement_maximum"] == 0

    marker["root_placement_maximum"] = 1
    write(marker_path, marker)
    with pytest.raises(
        AdminRootChildCancelAuthorityError,
        match="controlled_v15_plan_marker_binding_mismatch",
    ):
        load_controlled_v15_plan_authority()


def test_v15r2_readiness_uses_root_evidence_and_recovery_cap_names(
    tmp_path,
    monkeypatch,
):
    authority = _recovery_plan_authority()
    plan = authority["plan"]
    marker = authority["marker"]
    plan_hash = str(plan["plan_sha256"])
    batch_id = str(plan["batch_id"])
    service, read_service, runtime, _rest, _claims = _service(
        tmp_path, monkeypatch
    )
    service.dependencies.controlled_v15_plan_authority_getter = (
        lambda: authority
    )
    monkeypatch.setattr(
        "application.admin_api.command_service."
        "_root_child_cancel_route_proof_chain_matches",
        lambda *_args, **_kwargs: True,
    )
    child = SimpleNamespace(
        client_order_id=R2_CHILD_ID,
        parent_order_id=R2_ROOT_ID,
        product_id="BTC-USDC",
        side="SELL",
        status="OPEN",
        ownership_provenance="ADMIN_FILL_FOLLOW_UP",
        retail_portfolio_id=PORTFOLIO_ID,
    )
    read_service.chain.root_parent_client_order_id = R2_ROOT_ID
    read_service.chain.root_order.client_order_id = R2_ROOT_ID
    read_service.chain.follow_up_children = [child]
    read_service.chain.follow_up_child_client_order_ids = [R2_CHILD_ID]
    read_service.chain.portfolio_scope.child_portfolio_ids = {
        R2_CHILD_ID: PORTFOLIO_ID
    }
    read_service.detail.order.stealth_order_id = R2_CHILD_ID
    read_service.detail.order.parent_stealth_order_id = R2_ROOT_ID
    read_service.detail.order.active_placement_client_order_id = R2_CHILD_ID
    preparation = read_service.detail.order.anchor_repricing_state[
        "controlled_admin_first_child_reveal_preparation"
    ]
    preparation.update(
        {
            "batch_id": batch_id,
            "controlled_plan_sha256": plan_hash,
            "root_client_order_id": R2_ROOT_ID,
            "stealth_order_id": R2_CHILD_ID,
        }
    )
    read_service.build_order_fill_follow_up_chain = (
        lambda **_kwargs: read_service.chain
    )
    read_service.build_stealth_order_detail = (
        lambda **_kwargs: read_service.detail
    )
    runtime.read_controlled_first_child.return_value = {
        **runtime.read_controlled_first_child.return_value,
        "stealth_order_id": R2_CHILD_ID,
        "root_client_order_id": R2_ROOT_ID,
        "active_placement_client_order_id": R2_CHILD_ID,
        "controlled_plan_sha256": plan_hash,
    }
    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        lambda *_args, **_kwargs: {
            **_exchange_readback(),
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                **_exchange_readback()["matched_order"],
                "client_order_id": R2_CHILD_ID,
                "base_size": "0.00001583",
            },
        },
    )

    readiness = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=R2_ROOT_ID,
        controlled_plan_sha256=plan_hash,
    )

    assert readiness.ready is True
    assert readiness.root_client_order_id == R2_ROOT_ID
    assert readiness.child_client_order_id == R2_CHILD_ID
    assert readiness.root_reference_notional_usdc == "1.0075796583"
    assert readiness.child_reference_notional_usdc == "1.6585564317"
    assert readiness.aggregate_reference_notional_usdc == "2.6661360900"
    assert readiness.child_reference_reserve_usdc == "2"
    assert readiness.planned_aggregate_reference_notional_usdc == (
        "3.0075796583"
    )
    assert readiness.root_notional_cap_usdc == "9.99"
    assert readiness.child_notional_cap_usdc == "2"
    assert readiness.aggregate_notional_cap_usdc == "12"
    assert marker["root_placement_maximum"] == 0


def _command(*, idempotency_key: str = "idem-v15-cancel", allowed: bool = True):
    return AdminOrderFillFollowUpChildCancelCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key=idempotency_key,
            correlation_id="corr-v15-cancel",
            operator_intent=CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            actor=AdminApiActor(
                actor_id="operator@example.com",
                roles=["trader"],
            ),
        ),
        root_client_order_id=ROOT_ID,
        request=AdminOrderFillFollowUpChildCancelRequest(
            reason="cancel the selected root's deterministic first child",
            manual_live_acknowledgement=True,
            controlled_plan_sha256=PLAN_SHA256,
        ),
        admission_decision=_admission(
            idempotency_key=idempotency_key,
            allowed=allowed,
        ),
    )


def _accepted_cancel_response(command) -> AdminApiCommandResponse:
    return AdminApiCommandResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="cancel_stealth_order_by_stealth_order_id",
        message="Controlled first-child cancellation confirmed",
        stealth_order_id=CHILD_ID,
        coinbase_order_id=EXCHANGE_ID,
        correlation_id=command.envelope.correlation_id,
        idempotency_key=command.envelope.idempotency_key,
        live_exchange_submitted=True,
        live_coinbase_orders_ran=True,
        data={
            "root_client_order_id": ROOT_ID,
            "child_client_order_id": CHILD_ID,
            "controlled_plan_sha256": PLAN_SHA256,
            "cancellation_readback": {
                "authoritative": True,
                "pagination_complete": True,
                "exact_identity_match": True,
                "authoritative_status": "CANCELLED",
                "exchange_order_id": EXCHANGE_ID,
                "matched_order": {
                    "client_order_id": CHILD_ID,
                    "order_id": EXCHANGE_ID,
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "retail_portfolio_id": PORTFOLIO_ID,
                    "side": "SELL",
                    "status": "CANCELLED",
                    "filled_size": "0",
                    "filled_value": "0",
                    "total_fees": "0",
                    "number_of_fills": 0,
                },
            },
            "local_reconciliation": {
                "local_status": "CANCELLED",
                "active_placement_cleared": True,
                "executed_size": "0",
            },
            "terminal_zero_fill": {
                "proven": True,
                "filled_size": "0",
                "filled_value": "0",
                "total_fees": "0",
                "number_of_fills": 0,
                "local_executed_size": "0",
            },
        },
    )


def _accepted_cancel_after_boundary(command, **kwargs) -> AdminApiCommandResponse:
    boundary = kwargs.get("semantic_boundary_callback")
    assert callable(boundary)
    boundary()
    return _accepted_cancel_response(command)


def test_root_child_cancel_readiness_resolves_exact_child_without_browser_identity(
    tmp_path,
    monkeypatch,
):
    service, _read_service, runtime, rest_client, _claims = _service(
        tmp_path,
        monkeypatch,
    )

    readiness = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=ROOT_ID,
        controlled_plan_sha256=PLAN_SHA256,
    )

    assert readiness.ready is True
    assert readiness.root_client_order_id == ROOT_ID
    assert readiness.child_client_order_id == CHILD_ID
    assert readiness.controlled_plan_sha256 == PLAN_SHA256
    assert readiness.controlled_batch_id == BATCH_ID
    assert readiness.controlled_batch_slot == 1
    assert readiness.plan_expires_at == "2099-07-12T22:30:00+00:00"
    assert readiness.root_reference_notional_usdc == "1.10"
    assert readiness.child_reference_notional_usdc == "1.7999999682"
    assert readiness.aggregate_reference_notional_usdc == "2.8999999682"
    assert readiness.child_reference_reserve_usdc == "2.00"
    assert readiness.planned_aggregate_reference_notional_usdc == "3.10"
    assert readiness.root_notional_cap_usdc == "9.99"
    assert readiness.child_notional_cap_usdc == "2.00"
    assert readiness.aggregate_notional_cap_usdc == "12.00"
    assert readiness.cancel_idempotency_key == "idem-v15-cancel"
    assert readiness.cancel_correlation_id == "corr-v15-cancel"
    assert readiness.audit_id == "audit-v15"
    assert readiness.zero_fill_proven is True
    assert readiness.exchange_order_id_evidence_only is True
    runtime.read_controlled_first_child.assert_called_once_with(
        stealth_order_id=CHILD_ID,
        expected_root_client_order_id=ROOT_ID,
        expected_portfolio_id=PORTFOLIO_ID,
        controlled_batch_id=BATCH_ID,
        controlled_batch_slot=1,
        controlled_plan_sha256=PLAN_SHA256,
    )
    rest_client.cancel_order.assert_not_called()
    rest_client.cancel_order_by_exchange_order_id.assert_not_called()


def test_root_child_cancel_readiness_discovers_backend_plan_hash(
    tmp_path,
    monkeypatch,
):
    service, *_ = _service(tmp_path, monkeypatch)

    readiness = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=ROOT_ID,
    )

    assert readiness.ready is True
    assert readiness.controlled_plan_sha256 == PLAN_SHA256
    assert readiness.authority_source == "test_v15_authority"


def test_root_child_cancel_expiry_preserves_started_child_cleanup_authority(
    tmp_path,
    monkeypatch,
):
    authority = _plan_authority()
    authority["plan"] = deepcopy(authority["plan"])
    authority["marker"] = deepcopy(authority["marker"])
    authority["plan"]["created_at"] = "2026-07-12T18:00:00+00:00"
    authority["plan"]["expires_at"] = "2026-07-12T20:00:00+00:00"
    authority["marker"]["registered_at"] = "2026-07-12T18:01:00+00:00"
    service, *_ = _service(tmp_path, monkeypatch)
    service.dependencies.controlled_v15_plan_authority_getter = lambda: authority

    readiness = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=ROOT_ID,
        controlled_plan_sha256=PLAN_SHA256,
    )

    assert readiness.ready is True
    assert "controlled_v15_plan_expired" not in readiness.blockers


def test_root_child_cancel_readiness_allows_zero_fill_terminal_local_cleanup(
    tmp_path,
    monkeypatch,
):
    readback = deepcopy(_exchange_readback())
    readback["authoritative_status"] = "CANCELLED"
    readback["matched_order"]["status"] = "CANCELLED"
    service, *_ = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        lambda *_args, **_kwargs: readback,
    )

    readiness = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=ROOT_ID,
        controlled_plan_sha256=PLAN_SHA256,
    )

    assert readiness.ready is True
    assert readiness.authoritative_exchange_status == "CANCELLED"
    assert readiness.zero_fill_proven is True


def test_root_child_cancel_readiness_rejects_unresolved_handoff_proof_id(
    tmp_path,
    monkeypatch,
):
    service, *_ = _service(tmp_path, monkeypatch)
    service.dependencies.audit_store_getter = lambda: SimpleNamespace(
        find_by_audit_id=lambda _value: None
    )

    readiness = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=ROOT_ID,
        controlled_plan_sha256=PLAN_SHA256,
    )

    assert readiness.ready is False
    assert "controlled_v15_route_proof_chain_unresolved" in readiness.blockers


def test_expired_started_plan_can_override_only_expired_approval_for_cleanup(
    tmp_path,
    monkeypatch,
):
    authority = _plan_authority()
    authority["plan"] = deepcopy(authority["plan"])
    authority["marker"] = deepcopy(authority["marker"])
    authority["plan"]["created_at"] = "2026-07-12T18:00:00+00:00"
    authority["plan"]["expires_at"] = "2026-07-12T20:00:00+00:00"
    authority["marker"]["registered_at"] = "2026-07-12T18:01:00+00:00"
    service, *_ = _service(tmp_path, monkeypatch)
    service.dependencies.controlled_v15_plan_authority_getter = lambda: authority
    expired_approval = service.dependencies.approval_store_getter().find_by_approval_id(
        "approval-v15"
    )
    expired_approval.is_expired = lambda: True
    blocked = _admission(idempotency_key="idem-v15-cancel", allowed=False)
    blocked = blocked.model_copy(
        update={
            "payload_hash": "b" * 64,
            "blockers": [
                AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
                AdminApiLiveAdmissionBlocker.APPROVAL_SNAPSHOT_MISSING,
                AdminApiLiveAdmissionBlocker.ADMISSION_AUDIT_MISSING,
                AdminApiLiveAdmissionBlocker.CAP_GUARD_MISSING,
                AdminApiLiveAdmissionBlocker.RECONCILIATION_PLAN_MISSING,
                AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
            ],
            "live_execution_service_present": False,
        }
    )

    override = service.build_v15_active_child_cleanup_admission(
        command=_command(allowed=False),
        admission=blocked,
    )

    assert override.allowed is True
    assert override.approval_snapshot_id == "approval-v15"
    assert override.admission_audit_id == "audit-v15"
    assert override.cap_guard_decision_id == "cap-v15"
    assert override.reconciliation_plan_id == "recon-v15"


def test_parent_loss_live_disable_preserves_started_exact_cleanup_route(
    tmp_path,
    monkeypatch,
):
    authority = _plan_authority()
    authority["plan"] = deepcopy(authority["plan"])
    authority["marker"] = deepcopy(authority["marker"])
    current = datetime.now(timezone.utc)
    created_at = current - timedelta(minutes=1)
    authority["plan"]["created_at"] = created_at.isoformat()
    authority["plan"]["expires_at"] = (
        created_at + timedelta(minutes=120)
    ).isoformat()
    authority["marker"]["registered_at"] = current.isoformat()
    service, *_ = _service(tmp_path, monkeypatch)
    service.dependencies.controlled_v15_plan_authority_getter = lambda: authority
    blocked = _admission(idempotency_key="idem-v15-cancel", allowed=False)
    blocked = blocked.model_copy(
        update={
            "payload_hash": "b" * 64,
            "blockers": [
                AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
                AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
            ],
            "live_execution_service_present": False,
        }
    )

    override = service.build_v15_active_child_cleanup_admission(
        command=_command(allowed=False),
        admission=blocked,
    )

    assert override.allowed is True
    assert override.live_execution_service_source == (
        "sealed_v15_active_child_cleanup"
    )


@pytest.mark.parametrize(
    "mutation,blocker",
    [
        ("second_child", "exactly_one_first_child_required"),
        ("plan_hash", "controlled_plan_sha256_mismatch"),
        ("profile", "test_portfolio_scope_mismatch"),
        ("filled", "active_child_zero_fill_unproven"),
    ],
)
def test_root_child_cancel_readiness_fails_closed(
    tmp_path,
    monkeypatch,
    mutation,
    blocker,
):
    service, read_service, runtime, _rest, _claims = _service(
        tmp_path,
        monkeypatch,
    )
    if mutation == "second_child":
        read_service.chain.follow_up_children.append(
            SimpleNamespace(client_order_id=str(uuid.uuid4()))
        )
        read_service.chain.follow_up_child_client_order_ids.append(str(uuid.uuid4()))
        read_service.chain.follow_up_child_count = 2
    elif mutation == "plan_hash":
        preparation = read_service.detail.order.anchor_repricing_state[
            "controlled_admin_first_child_reveal_preparation"
        ]
        preparation["controlled_plan_sha256"] = "c" * 64
    elif mutation == "profile":
        read_service.chain.portfolio_scope.status = "blocked"
        read_service.chain.portfolio_scope.scope_consistent = False
    else:
        monkeypatch.setattr(
            "application.admin_api.command_service.exact_coinbase_order_readback",
            lambda *_args, **_kwargs: {
                **_exchange_readback(),
                "matched_order": {
                    **_exchange_readback()["matched_order"],
                    "filled_size": "0.00000001",
                    "number_of_fills": 1,
                },
            },
        )

    readiness = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=ROOT_ID,
        controlled_plan_sha256=PLAN_SHA256,
    )

    assert readiness.ready is False
    assert blocker in readiness.blockers
    if mutation in {"second_child", "plan_hash", "profile"}:
        runtime.read_controlled_first_child.assert_not_called()


def test_root_child_cancel_claims_once_then_delegates_canonical_service(
    tmp_path,
    monkeypatch,
):
    service, _read_service, _runtime_adapter, rest_client, claims = _service(
        tmp_path,
        monkeypatch,
    )
    canonical = MagicMock(side_effect=_accepted_cancel_after_boundary)
    service.cancel_stealth_order_by_stealth_order_id = canonical
    command = _command()

    first = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        command
    )
    replay = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        command
    )
    conflict = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        _command(idempotency_key="different-key")
    )

    assert first.status == AdminApiCommandStatus.ACCEPTED
    assert first.client_order_id == ROOT_ID
    assert first.stealth_order_id == CHILD_ID
    assert first.data["semantic_claim"]["semantic_key"]
    assert replay.status == AdminApiCommandStatus.ACCEPTED
    assert replay.data["semantic_claim"]["same_idempotency_replay"] is True
    assert conflict.status == AdminApiCommandStatus.REJECTED
    assert conflict.failure_stage in {
        "semantic_cancel_duplicate",
        "root_child_cancel_sealed_command_mismatch",
    }
    canonical.assert_called_once()
    delegated = canonical.call_args.args[0]
    assert delegated.stealth_order_id == CHILD_ID
    assert delegated.request.expected_root_client_order_id == ROOT_ID
    assert delegated.request.controlled_batch_id == BATCH_ID
    assert delegated.request.controlled_batch_slot == 1
    assert delegated.request.controlled_plan_sha256 == PLAN_SHA256
    assert canonical.call_args.kwargs["sealed_cancel_plan_sha256"] == PLAN_SHA256
    assert canonical.call_args.kwargs[
        "v15r6_verified_exchange_submission_required"
    ] is False
    assert len(claims.read_recent(limit=20)) == 3
    rest_client.cancel_order.assert_not_called()


def test_root_child_cancel_unknown_outcome_reconciles_read_only_after_restart(
    tmp_path,
    monkeypatch,
):
    service, _read_service, _runtime_adapter, _rest, claims = _service(
        tmp_path,
        monkeypatch,
    )
    unknown = AdminApiCommandResponse(
        status=AdminApiCommandStatus.REJECTED,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="cancel_stealth_order_by_stealth_order_id",
        message="cancel outcome unknown",
        stealth_order_id=CHILD_ID,
        correlation_id="corr-v15-cancel",
        idempotency_key="idem-v15-cancel",
        live_exchange_submitted=True,
        live_coinbase_orders_ran=True,
        failure_stage="cancellation_unknown",
    )
    def _unknown_after_boundary(_command, **kwargs):
        kwargs["semantic_boundary_callback"]()
        return unknown

    canonical = MagicMock(side_effect=_unknown_after_boundary)
    service.cancel_stealth_order_by_stealth_order_id = canonical
    command = _command()

    first = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        command
    )
    restarted, *_ = _service(tmp_path, monkeypatch)
    reconciled = _accepted_cancel_response(command).model_copy(
        update={
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "message": "Authoritative terminal cancellation reconciled",
        }
    )
    restarted_canonical = MagicMock(return_value=reconciled)
    restarted.cancel_stealth_order_by_stealth_order_id = restarted_canonical
    after_restart = (
        restarted.cancel_order_fill_follow_up_child_by_root_client_order_id(
            command
        )
    )

    assert first.failure_stage == "cancellation_unknown"
    assert after_restart.status == AdminApiCommandStatus.ACCEPTED
    assert after_restart.live_exchange_submitted is False
    assert after_restart.data["semantic_claim"]["reconciliation_required"] is True
    canonical.assert_called_once()
    restarted_canonical.assert_called_once()
    assert restarted_canonical.call_args.kwargs["reconciliation_only"] is True
    assert FileAdminRootChildCancelClaimStore(claims.path).read_recent(limit=20)


def test_root_child_cancel_blocked_admission_does_not_resolve_or_claim(
    tmp_path,
    monkeypatch,
):
    service, read_service, runtime, _rest, claims = _service(
        tmp_path,
        monkeypatch,
    )
    canonical = MagicMock()
    service.cancel_stealth_order_by_stealth_order_id = canonical

    response = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        _command(allowed=False)
    )

    assert response.status == AdminApiCommandStatus.NOT_IMPLEMENTED
    assert claims.read_recent(limit=20) == []
    runtime.read_controlled_first_child.assert_not_called()
    canonical.assert_not_called()
    assert read_service.chain.found is True


def test_root_child_cancel_unready_does_not_burn_semantic_claim(
    tmp_path,
    monkeypatch,
):
    service, read_service, _runtime_adapter, _rest, claims = _service(
        tmp_path,
        monkeypatch,
    )
    read_service.chain.follow_up_children.append(
        SimpleNamespace(client_order_id=str(uuid.uuid4()))
    )
    read_service.chain.follow_up_child_client_order_ids.append(str(uuid.uuid4()))
    read_service.chain.follow_up_child_count = 2
    canonical = MagicMock()
    service.cancel_stealth_order_by_stealth_order_id = canonical

    response = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        _command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "root_child_cancel_readiness"
    assert claims.read_recent(limit=20) == []
    canonical.assert_not_called()


def test_root_child_cancel_claim_store_fails_closed_on_malformed_or_duplicate_outcome(
    tmp_path,
):
    path = tmp_path / "claims.jsonl"
    path.write_text("{truncated", encoding="utf-8")
    path.chmod(0o600)
    store = FileAdminRootChildCancelClaimStore(path)

    with pytest.raises(AdminRootChildCancelClaimStoreError):
        store.read_recent()

    path.write_bytes(b"")
    decision, claim = store.claim(
        controlled_plan_sha256=PLAN_SHA256,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        idempotency_key="idem-v15-cancel",
        payload_hash="b" * 64,
        correlation_id="corr-v15-cancel",
        actor_id="operator@example.com",
    )
    assert decision == "claimed"
    rejected_response = {
        "status": "rejected",
        "client_order_id": ROOT_ID,
        "stealth_order_id": CHILD_ID,
        "idempotency_key": "idem-v15-cancel",
        "correlation_id": "corr-v15-cancel",
        "data": {"controlled_plan_sha256": PLAN_SHA256},
    }
    store.complete(claim, outcome="rejected", response=rejected_response)
    with pytest.raises(AdminRootChildCancelClaimStoreError):
        store.complete(
            claim,
            outcome="rejected",
            response=rejected_response,
        )


def test_root_child_cancel_same_key_can_resume_before_exchange_boundary(
    tmp_path,
    monkeypatch,
):
    service, *_ = _service(tmp_path, monkeypatch)
    pre_boundary = AdminApiCommandResponse(
        status=AdminApiCommandStatus.REJECTED,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="cancel_stealth_order_by_stealth_order_id",
        message="pre-cancel read temporarily unavailable",
        stealth_order_id=CHILD_ID,
        correlation_id="corr-v15-cancel",
        idempotency_key="idem-v15-cancel",
        live_exchange_submitted=False,
        live_coinbase_orders_ran=False,
        failure_stage="cancellation_readback",
    )
    call_count = 0

    def _canonical(command, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return pre_boundary
        return _accepted_cancel_after_boundary(command, **kwargs)

    canonical = MagicMock(side_effect=_canonical)
    service.cancel_stealth_order_by_stealth_order_id = canonical
    command = _command()

    first = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        command
    )
    second = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        command
    )

    assert first.status == AdminApiCommandStatus.REJECTED
    assert first.live_exchange_submitted is False
    assert first.service_method == (
        "cancel_order_fill_follow_up_child_by_root_client_order_id"
    )
    assert second.status == AdminApiCommandStatus.ACCEPTED
    assert canonical.call_count == 2


def test_root_child_cancel_second_read_transience_does_not_burn_claim(
    tmp_path,
    monkeypatch,
):
    service, *_ = _service(tmp_path, monkeypatch)
    original = service.build_order_fill_follow_up_child_cancel_readiness
    ready = original(
        root_client_order_id=ROOT_ID,
        controlled_plan_sha256=PLAN_SHA256,
    )
    transient = ready.model_copy(
        update={
            "ready": False,
            "readiness_status": "blocked",
            "backend_decision": "blocked",
            "blockers": ["transient_second_read"],
        }
    )
    service.build_order_fill_follow_up_child_cancel_readiness = MagicMock(
        side_effect=[ready, transient]
    )
    canonical = MagicMock(side_effect=_accepted_cancel_after_boundary)
    service.cancel_stealth_order_by_stealth_order_id = canonical
    command = _command()

    first = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        command
    )
    service.build_order_fill_follow_up_child_cancel_readiness = original
    second = service.cancel_order_fill_follow_up_child_by_root_client_order_id(
        command
    )

    assert first.status == AdminApiCommandStatus.REJECTED
    assert first.failure_stage == "root_child_cancel_readiness"
    assert second.status == AdminApiCommandStatus.ACCEPTED
    canonical.assert_called_once()


def test_root_child_cancel_claim_store_distinguishes_pre_boundary_and_unknown(
    tmp_path,
):
    store = FileAdminRootChildCancelClaimStore(tmp_path / "claims.jsonl")
    decision, claim = store.claim(
        controlled_plan_sha256=PLAN_SHA256,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        idempotency_key="idem-v15-cancel",
        payload_hash="b" * 64,
        correlation_id="corr-v15-cancel",
        actor_id="operator@example.com",
    )
    assert decision == "claimed"
    resumed, _ = store.inspect(
        controlled_plan_sha256=PLAN_SHA256,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        idempotency_key="idem-v15-cancel",
        payload_hash="b" * 64,
        correlation_id="corr-v15-cancel",
        actor_id="operator@example.com",
    )
    assert resumed == "resume_same_key_before_boundary"
    conflict, _ = store.inspect(
        controlled_plan_sha256=PLAN_SHA256,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        idempotency_key="idem-v15-cancel",
        payload_hash="b" * 64,
        correlation_id="drifted-correlation",
        actor_id="operator@example.com",
    )
    assert conflict == "semantic_conflict"

    store.mark_exchange_boundary(claim)
    unknown, _ = store.inspect(
        controlled_plan_sha256=PLAN_SHA256,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        idempotency_key="idem-v15-cancel",
        payload_hash="b" * 64,
        correlation_id="corr-v15-cancel",
        actor_id="operator@example.com",
    )
    assert unknown == "reconcile_same_key_only"


def test_root_child_cancel_claim_store_rejects_orphan_or_drifted_events(
    tmp_path,
):
    store = FileAdminRootChildCancelClaimStore(tmp_path / "claims.jsonl")
    _decision, claim = store.claim(
        controlled_plan_sha256=PLAN_SHA256,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        idempotency_key="idem-v15-cancel",
        payload_hash="b" * 64,
        correlation_id="corr-v15-cancel",
        actor_id="operator@example.com",
    )
    store.mark_exchange_boundary(claim)
    rows = store.path.read_text(encoding="utf-8").splitlines()
    boundary = json.loads(rows[1])
    boundary["correlation_id"] = "drifted-correlation"
    store.path.write_text(
        rows[0] + "\n" + json.dumps(boundary) + "\n",
        encoding="utf-8",
    )
    store.path.chmod(0o600)

    with pytest.raises(
        AdminRootChildCancelClaimStoreError,
        match="identity_drift",
    ):
        store.read_recent()

    orphan_path = tmp_path / "orphan.jsonl"
    orphan_path.write_text(
        json.dumps(boundary) + "\n",
        encoding="utf-8",
    )
    orphan_path.chmod(0o600)
    with pytest.raises(
        AdminRootChildCancelClaimStoreError,
        match="sequence_invalid",
    ):
        FileAdminRootChildCancelClaimStore(orphan_path).read_recent()


def test_root_child_cancel_claim_store_rejects_accepted_response_identity_drift(
    tmp_path,
):
    store = FileAdminRootChildCancelClaimStore(tmp_path / "claims.jsonl")
    _decision, claim = store.claim(
        controlled_plan_sha256=PLAN_SHA256,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        idempotency_key="idem-v15-cancel",
        payload_hash="b" * 64,
        correlation_id="corr-v15-cancel",
        actor_id="operator@example.com",
    )
    store.mark_exchange_boundary(claim)
    response = _accepted_cancel_response(_command()).model_copy(
        update={"stealth_order_id": str(uuid.uuid4())}
    )

    with pytest.raises(
        AdminRootChildCancelClaimStoreError,
        match="response_identity_invalid",
    ):
        store.complete(
            claim,
            outcome="accepted",
            response=response.model_dump(mode="json"),
        )


def test_root_child_cancel_claim_store_rejects_symlink(tmp_path):
    target = tmp_path / "target.jsonl"
    target.write_bytes(b"")
    target.chmod(0o600)
    link = tmp_path / "claims.jsonl"
    link.symlink_to(target)

    with pytest.raises(OSError):
        FileAdminRootChildCancelClaimStore(link).read_recent()
