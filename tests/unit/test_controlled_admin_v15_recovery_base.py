"""Shared-runtime tests for the child-only V15R2 recovery authority."""

from __future__ import annotations

import json
import os

import pytest

from tools import run_controlled_admin_spot_root_child_batch as base


ROOT_ID = "e4ad814e-c0d1-521a-a8c5-458243935ad2"
CHILD_ID = "e403d359-ecf3-59dc-b5b0-dfdd3c3efdaf"


def _plan() -> dict[str, object]:
    plan: dict[str, object] = {
        "schema_version": "20",
        "authority_kind": "selected_chain_child_cancel_recovery_v15r2",
        "approval_id": "controlled-child-cancel-v15r2-test",
        "batch_id": "11111111-1111-5111-8111-111111111111",
        "backend_commit": "a" * 40,
        "runner_sha256": "b" * 64,
        "profile_label": base.PROFILE_LABEL,
        "portfolio_id": base.TEST_PORTFOLIO_ID,
        "product_id": base.PRODUCT_ID,
        "placement_attempt_count": 1,
        "placement_attempt_schedule": ["child"],
        "root_placement_maximum": 0,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "root_placement_authorized": False,
        "root_actual_reference_notional_usdc": "1.0075796583",
        "child_submitted_cap_usdc": "2.00",
        "slice_reference_cap_usdc": "12.00",
        "planned_reference_notional_usdc": "3.0075796583",
        "root_evidence": {
            "client_order_id": ROOT_ID,
            "exchange_order_id": "9eb2038c-5059-434c-a117-62ea0b804837",
            "placement_authorized": False,
        },
        "child": {
            "client_order_id": CHILD_ID,
            "parent_client_order_id": ROOT_ID,
            "approval_snapshot_id": "approval-child",
            "order_policy": {"base_size": "0.00001583"},
        },
        "v15r1_recovery_binding": {"r1_child_sdk_call_count": 0},
        "local_hidden_child_binding": {"child_client_order_id": CHILD_ID},
        "retry_authorized": False,
        "substitution_authorized": False,
        "later_child_authorized": False,
    }
    plan["plan_sha256"] = base.plan_hash(plan)
    return plan


def _child_tuple(plan: dict[str, object]) -> dict[str, object]:
    return {
        "approval_snapshot_id": "approval-child",
        "batch_id": plan["batch_id"],
        "batch_slot": 1,
        "root_client_order_id": ROOT_ID,
        "client_order_id": CHILD_ID,
        "product_id": base.PRODUCT_ID,
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "base_size": "0.00001583",
        "limit_price": "108154.14",
        "post_only": False,
        "price_increment": "0.01",
        "market_observed_at": "2026-07-13T01:30:11.141748Z",
        "reference_bid": "63620.08",
        "minimum_bid_ratio": "1.60",
        "target_bid_ratio": "1.70",
        "strict_max_notional_usdc": "2.00",
    }


def _row(plan: dict[str, object]) -> dict[str, object]:
    exact = _child_tuple(plan)
    return {
        "schema_version": "1",
        "sequence": 1,
        "attempt_kind": "child",
        "batch_id": plan["batch_id"],
        "root_client_order_id": ROOT_ID,
        "client_order_id": CHILD_ID,
        "plan_sha256": plan["plan_sha256"],
        "exact_order_tuple": exact,
        "exact_order_tuple_sha256": base._canonical_json_sha256(exact),
    }


def test_v15r2_shared_limits_deny_every_root_call() -> None:
    plan = _plan()

    assert base.is_v15_plan(plan) is False
    assert base.is_v15_recovery_plan(plan) is True
    assert base.current_attempt_schedule(plan) == [(1, "child")]
    assert base.current_generation_limits(plan) == (0, 1, 1)
    with pytest.raises(base.ProofFailure, match="root_sdk_call_maximum_exceeded"):
        base.authorized_sdk_tuple_for_call(
            [], attempt_kind="root", prior_call_count=0, confirmed_plan=plan
        )


def test_v15r2_shared_ledger_accepts_one_child_and_rejects_root(tmp_path) -> None:
    plan = _plan()
    ledger = tmp_path / "placements.jsonl"
    ledger.write_text(json.dumps(_row(plan), sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(ledger, 0o600)

    rows = base.read_batch_attempt_ledger(
        ledger,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
    )
    assert len(rows) == 1
    assert base.authorized_sdk_tuple_for_call(
        rows,
        attempt_kind="child",
        prior_call_count=0,
        confirmed_plan=plan,
    ) == _child_tuple(plan)

    root_row = _row(plan)
    root_row["attempt_kind"] = "root"
    ledger.write_text(json.dumps(root_row, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(base.ProofFailure, match="v15r2_runtime_attempt_record_mismatch"):
        base.read_batch_attempt_ledger(
            ledger,
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
        )


def test_v15r2_marker_constructs_runtime_with_zero_root_budget(
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
                "authority": "selected_chain_child_cancel_recovery_v15r2",
                "approval_id": plan["approval_id"],
                "batch_id": plan["batch_id"],
                "plan_sha256": plan["plan_sha256"],
                "plan_file": str(plan_path),
                "root_client_order_id": ROOT_ID,
                "child_client_order_id": CHILD_ID,
                "placement_attempt_maximum": 1,
                "root_placement_maximum": 0,
                "child_placement_maximum": 1,
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
    assert runtime.child_order_maximum == 1
    assert runtime.attempt_maximum == 1
    assert runtime.child_auth_file.exists()
