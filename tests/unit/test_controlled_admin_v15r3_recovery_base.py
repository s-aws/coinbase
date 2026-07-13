"""Shared-runtime no-placement tests for sealed V15R3 cancel recovery."""

from __future__ import annotations

import json
import os

import pytest

from tools import run_controlled_admin_spot_root_child_batch as base


ROOT_ID = "e4ad814e-c0d1-521a-a8c5-458243935ad2"
CHILD_ID = "e403d359-ecf3-59dc-b5b0-dfdd3c3efdaf"


def _plan() -> dict[str, object]:
    plan: dict[str, object] = {
        "schema_version": "21",
        "authority_kind": "selected_chain_child_cancel_recovery_v15r3",
        "approval_id": "controlled-child-cancel-v15r3-test",
        "batch_id": "11111111-1111-5111-8111-111111111111",
        "backend_commit": "a" * 40,
        "runner_sha256": "b" * 64,
        "profile_label": base.PROFILE_LABEL,
        "portfolio_id": base.TEST_PORTFOLIO_ID,
        "product_id": base.PRODUCT_ID,
        "placement_attempt_count": 0,
        "placement_attempt_schedule": [],
        "root_placement_maximum": 0,
        "child_placement_maximum": 0,
        "cancel_command_maximum": 1,
        "root_placement_authorized": False,
        "root_actual_reference_notional_usdc": "1.0075796583",
        "child_active_reference_notional_usdc": "1.7049248762",
        "slice_reference_cap_usdc": "12.00",
        "planned_reference_notional_usdc": "2.7125045345",
        "root_evidence": {
            "client_order_id": ROOT_ID,
            "exchange_order_id": "9eb2038c-5059-434c-a117-62ea0b804837",
            "placement_authorized": False,
        },
        "child": {
            "client_order_id": CHILD_ID,
            "parent_client_order_id": ROOT_ID,
            "active_exchange_order_id": "5bb903af-3c6e-4d0a-bd73-087f0dfead89",
            "origin_controlled_plan_sha256": "0" * 64,
            "origin_controlled_batch_id": "22222222-2222-5222-8222-222222222222",
        },
        "v15r2_active_child_binding": {"r2_child_sdk_call_count": 1},
        "actor_id": "operator-controlled-spot-proof",
        "actor_roles": ["trader"],
        "cancel_command": {"operator_intent": "controlled_v15_test_profile_first_child_cancel"},
        "retry_authorized": False,
        "substitution_authorized": False,
        "later_child_authorized": False,
    }
    plan["plan_sha256"] = base.plan_hash(plan)
    return plan


def test_v15r3_shared_limits_deny_all_order_sdk_calls() -> None:
    plan = _plan()

    assert base.is_v15_plan(plan) is False
    assert base.is_v15_recovery_plan(plan) is True
    assert base.is_v15_cancel_only_recovery_plan(plan) is True
    assert base.current_attempt_schedule(plan) == []
    assert base.current_generation_limits(plan) == (0, 0, 0)
    for attempt_kind in ("root", "child"):
        with pytest.raises(
            base.ProofFailure,
            match=rf"{attempt_kind}_sdk_call_maximum_exceeded",
        ):
            base.authorized_sdk_tuple_for_call(
                [],
                attempt_kind=attempt_kind,
                prior_call_count=0,
                confirmed_plan=plan,
            )


def test_v15r3_shared_ledger_accepts_only_empty_file(tmp_path) -> None:
    plan = _plan()
    ledger = tmp_path / "placements.jsonl"
    ledger.touch(mode=0o600)

    assert base.read_batch_attempt_ledger(
        ledger,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
    ) == []

    ledger.write_text(json.dumps({"attempt_kind": "child"}) + "\n", encoding="utf-8")
    os.chmod(ledger, 0o600)
    with pytest.raises(base.ProofFailure, match="v15r3_runtime_attempt_count_exceeded"):
        base.read_batch_attempt_ledger(
            ledger,
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
        )


def test_v15r3_marker_constructs_runtime_with_zero_order_budget(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    marker = tmp_path / "marker.json"
    ledger = tmp_path / "placements.jsonl"
    plan_path = tmp_path / "plan.json"
    handoff = tmp_path / "handoff.json"
    claims = tmp_path / "claims.jsonl"
    ledger.touch(mode=0o600)
    claims.touch(mode=0o600)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    os.chmod(plan_path, 0o600)
    marker.write_text(
        json.dumps(
            {
                "authority": "selected_chain_child_cancel_recovery_v15r3",
                "approval_id": plan["approval_id"],
                "batch_id": plan["batch_id"],
                "plan_sha256": plan["plan_sha256"],
                "plan_file": str(plan_path),
                "root_client_order_id": ROOT_ID,
                "child_client_order_id": CHILD_ID,
                "placement_attempt_maximum": 0,
                "root_placement_maximum": 0,
                "child_placement_maximum": 0,
                "placement_ledger_path": str(ledger),
                "handoff_path": str(handoff),
                "backend_claim_log_path": str(claims),
            }
        ),
        encoding="utf-8",
    )
    os.chmod(marker, 0o600)
    monkeypatch.setattr(base, "ROOT", tmp_path)

    runtime = base.AdminRuntime(
        portfolio_id=base.TEST_PORTFOLIO_ID,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        global_batch_marker=marker,
        attempt_ledger_path=ledger,
        controlled_v15_plan_path=plan_path,
        controlled_v15_handoff_path=handoff,
        controlled_v15_claim_log_path=claims,
    )

    assert runtime.root_order_maximum == 0
    assert runtime.child_order_maximum == 0
    assert runtime.attempt_maximum == 0
    assert runtime.child_auth_file.exists()
