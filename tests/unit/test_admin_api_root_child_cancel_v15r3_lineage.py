"""V15R3 command authority must not rewrite the R2 child preparation."""

from __future__ import annotations

from datetime import datetime, timezone

from application.admin_api import command_service


R2_PLAN = "0b9ab483459a986ad05200a6740a0de6dca63b6c5da197572c952ce8aef524c2"
R2_BATCH = "bb88b375-66a3-5562-87bd-1e88ebceecda"
R3_PLAN = "3" * 64
R3_BATCH = "33333333-3333-5333-8333-333333333333"


def _r3_plan() -> dict[str, object]:
    return {
        "schema_version": "21",
        "authority_kind": "selected_chain_child_cancel_recovery_v15r3",
        "plan_sha256": R3_PLAN,
        "batch_id": R3_BATCH,
        "v15r2_active_child_binding": {
            "r2_plan_sha256": R2_PLAN,
            "r2_batch_id": R2_BATCH,
        },
    }


def test_v15r3_lineage_uses_new_hash_for_command_and_r2_hash_for_child_read() -> None:
    lineage = command_service._root_child_cancel_plan_lineage(
        _r3_plan(),
        observed_preparation_plan_sha256=R2_PLAN,
        observed_preparation_batch_id=R2_BATCH,
        requested_command_plan_sha256=R3_PLAN,
    )

    assert lineage == {
        "valid": True,
        "command_plan_sha256": R3_PLAN,
        "command_batch_id": R3_BATCH,
        "runtime_child_plan_sha256": R2_PLAN,
        "runtime_child_batch_id": R2_BATCH,
    }


def test_v15r3_lineage_rejects_origin_or_requested_command_drift() -> None:
    for observed_plan, observed_batch, requested in (
        ("4" * 64, R2_BATCH, R3_PLAN),
        (R2_PLAN, "44444444-4444-5444-8444-444444444444", R3_PLAN),
        (R2_PLAN, R2_BATCH, "5" * 64),
    ):
        lineage = command_service._root_child_cancel_plan_lineage(
            _r3_plan(),
            observed_preparation_plan_sha256=observed_plan,
            observed_preparation_batch_id=observed_batch,
            requested_command_plan_sha256=requested,
        )
        assert lineage["valid"] is False


def test_non_r3_lineage_preserves_existing_single_plan_behavior() -> None:
    lineage = command_service._root_child_cancel_plan_lineage(
        {"schema_version": "20", "plan_sha256": R2_PLAN, "batch_id": R2_BATCH},
        observed_preparation_plan_sha256=R2_PLAN,
        observed_preparation_batch_id=R2_BATCH,
        requested_command_plan_sha256=R2_PLAN,
    )

    assert lineage == {
        "valid": True,
        "command_plan_sha256": R2_PLAN,
        "command_batch_id": R2_BATCH,
        "runtime_child_plan_sha256": R2_PLAN,
        "runtime_child_batch_id": R2_BATCH,
    }


def test_v15r3_delegate_uses_r2_origin_without_changing_r3_semantic_identity() -> None:
    delegated = command_service._root_child_cancel_delegate_lineage(
        _r3_plan(),
        command_plan_sha256=R3_PLAN,
        command_batch_id=R3_BATCH,
    )

    assert delegated == {
        "valid": True,
        "controlled_plan_sha256": R2_PLAN,
        "controlled_batch_id": R2_BATCH,
    }

    assert command_service._root_child_cancel_delegate_lineage(
        _r3_plan(),
        command_plan_sha256="6" * 64,
        command_batch_id=R3_BATCH,
    )["valid"] is False


def test_v15r3_expiry_blocks_new_claim_even_when_execution_registered() -> None:
    now = datetime(2026, 7, 13, 5, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 7, 13, 4, 59, tzinfo=timezone.utc)

    assert command_service._root_child_cancel_plan_expired_for_new_claim(
        _r3_plan(),
        now=now,
        expires_at=expires_at,
        execution_started_within_plan=True,
    ) is True
    assert command_service._root_child_cancel_post_expiry_cleanup_allowed(
        _r3_plan()
    ) is False

    legacy = {
        "schema_version": "20",
        "authority_kind": "selected_chain_child_cancel_recovery_v15r2",
    }
    assert command_service._root_child_cancel_plan_expired_for_new_claim(
        legacy,
        now=now,
        expires_at=expires_at,
        execution_started_within_plan=True,
    ) is False
    assert command_service._root_child_cancel_post_expiry_cleanup_allowed(
        legacy
    ) is True
