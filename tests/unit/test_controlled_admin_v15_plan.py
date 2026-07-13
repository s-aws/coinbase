"""Focused no-live authority tests for the sealed V15 child-cancel slice."""

from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os

import pytest

from tools import run_controlled_admin_spot_child_cancel_slice as v15


def _preflight() -> dict[str, object]:
    return {
        "portfolio_id": v15.TEST_PORTFOLIO_ID,
        "wallets": {"USDC": Decimal("980"), "BTC": Decimal("0.0002")},
        "product": {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
        },
        "best_bid": Decimal("64129.52"),
        "best_ask": Decimal("64129.53"),
        "market": {
            "product_id": v15.PRODUCT_ID,
            "source": "coinbase_rest_get_best_bid_ask_exact_product",
            "observed_at": "2026-07-12T22:30:00+00:00",
        },
        "active_spot_order_count": 0,
    }


def _plan(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(v15, "backend_production_commit", lambda: "a" * 40)
    monkeypatch.setattr(v15, "backend_runner_commit", lambda: "b" * 40)
    monkeypatch.setattr(v15, "frontend_commit", lambda: "c" * 40)
    monkeypatch.setattr(v15, "runner_sha256", lambda: "d" * 64)
    monkeypatch.setattr(
        v15,
        "load_v14_completion_binding",
        lambda: v15.offline_v14_completion_binding_fixture(),
    )
    return v15.build_v15_plan(
        _preflight(),
        now=datetime(2026, 7, 12, 22, 30, tzinfo=timezone.utc),
        approval_id="controlled-child-cancel-v15-11111111-1111-4111-8111-111111111111",
    )


def test_v15_plan_seals_two_placements_and_one_cancel_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    root = plan["root"]
    child = plan["child"]
    cancel = plan["cancel_command"]

    assert plan["schema_version"] == "19"
    assert plan["authority_kind"] == "selected_chain_child_cancel_v15"
    assert plan["profile_label"] == "Test"
    assert plan["portfolio_id"] == v15.TEST_PORTFOLIO_ID
    assert plan["product_id"] == "BTC-USDC"
    assert plan["placement_attempt_count"] == 2
    assert plan["root_placement_maximum"] == 1
    assert plan["child_placement_maximum"] == 1
    assert plan["cancel_command_maximum"] == 1
    assert plan["placement_attempt_schedule"] == ["root", "child"]
    assert root["order"]["client_order_id"] == root["client_order_id"]
    assert child["client_order_id"] == v15.deterministic_child_client_order_id(
        root["client_order_id"]
    )
    assert child["parent_client_order_id"] == root["client_order_id"]
    assert "order" not in child
    assert child["order_policy"] == {
        "product_id": "BTC-USDC",
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "post_only": False,
        "base_size_source": "authoritative_root_filled_size",
        "minimum_fresh_bid_ratio": "1.60",
        "target_fresh_bid_ratio": "1.70",
        "strict_max_notional_usdc": "2.00",
    }
    assert cancel["root_client_order_id"] == root["client_order_id"]
    assert cancel["child_client_order_id"] == child["client_order_id"]
    assert cancel["identity_key"] == "client_order_id"
    assert cancel["identity_value"] == root["client_order_id"]
    assert cancel["child_client_order_id"] == child["client_order_id"]
    assert cancel["controlled_plan_sha256_source"] == "plan_sha256"
    assert cancel["semantic_retry_policy"] == "same_idempotency_key_only"
    assert cancel["admission_audit_id_source"] == "route_bound_runtime_proof"
    assert "admission_audit_id" not in cancel
    assert cancel["route"] == (
        "/api/v1/orders/{root_client_order_id}/fill-follow-up/child-cancel"
    )
    assert plan["retry_authorized"] is False
    assert plan["substitution_authorized"] is False
    assert plan["later_child_authorized"] is False
    assert Decimal(plan["root_reference_notional_usdc"]) < Decimal("9.99")
    assert Decimal(plan["child_reference_reserve_usdc"]) == Decimal("2.00")
    assert Decimal(plan["planned_reference_notional_usdc"]) < Decimal("12.00")
    assert Decimal(plan["conservative_reference_notional_usdc"]) == Decimal(
        "11.99"
    )
    assert plan["slice_reference_cap_usdc"] == "12.00"
    assert datetime.fromisoformat(plan["expires_at"]) - datetime.fromisoformat(
        plan["created_at"]
    ) == timedelta(minutes=120)
    assert plan["plan_sha256"] == v15.plan_hash(plan)
    assert plan["v14_completion_binding"] == (
        v15.offline_v14_completion_binding_fixture()
    )


def test_v15_validator_rejects_hash_cap_identity_and_attempt_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    v15.validate_v15_plan(
        plan,
        expected_hash=plan["plan_sha256"],
        preflight=_preflight(),
        now=datetime(2026, 7, 12, 22, 31, tzinfo=timezone.utc),
    )

    for mutation in (
        lambda value: value.__setitem__("placement_attempt_count", 3),
        lambda value: value.__setitem__("slice_reference_cap_usdc", "30.00"),
        lambda value: value["child"].__setitem__(
            "parent_client_order_id", "22222222-2222-4222-8222-222222222222"
        ),
        lambda value: value["cancel_command"].__setitem__(
            "identity_key", "order_id"
        ),
        lambda value: value["cancel_command"].__setitem__(
            "identity_value", value["child"]["client_order_id"]
        ),
    ):
        changed = deepcopy(plan)
        mutation(changed)
        changed["plan_sha256"] = v15.plan_hash(changed)
        with pytest.raises(v15.ProofFailure):
            v15.validate_v15_plan(
                changed,
                expected_hash=changed["plan_sha256"],
                preflight=_preflight(),
                now=datetime(2026, 7, 12, 22, 31, tzinfo=timezone.utc),
            )

    extra_field = deepcopy(plan)
    extra_field["unsealed_authority"] = True
    extra_field["plan_sha256"] = v15.plan_hash(extra_field)
    with pytest.raises(v15.ProofFailure, match="v15_plan_fields_mismatch"):
        v15.validate_v15_plan(
            extra_field,
            expected_hash=extra_field["plan_sha256"],
            preflight=_preflight(),
            now=datetime(2026, 7, 12, 22, 31, tzinfo=timezone.utc),
        )


def test_v15_prepare_writes_only_owner_plan_and_no_execution_artifacts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    plan_path = tmp_path / "v15.plan.json"
    marker_path = tmp_path / "v15.authority.json"
    placement_ledger_path = tmp_path / "v15.placements.jsonl"
    cancel_ledger_path = tmp_path / "v15.cancel-command.jsonl"
    backend_claim_log_path = tmp_path / "v15.backend-claims.jsonl"
    handoff_path = tmp_path / "v15.operator-cancel-handoff.json"

    v15.write_prepared_v15_plan(
        plan_path,
        plan,
        marker_path=marker_path,
        placement_ledger_path=placement_ledger_path,
        cancel_ledger_path=cancel_ledger_path,
        backend_claim_log_path=backend_claim_log_path,
        handoff_path=handoff_path,
    )

    assert json.loads(plan_path.read_text(encoding="utf-8")) == plan
    assert plan_path.stat().st_mode & 0o077 == 0
    assert not marker_path.exists()
    assert not placement_ledger_path.exists()
    assert not cancel_ledger_path.exists()
    assert not backend_claim_log_path.exists()
    assert not handoff_path.exists()
    with pytest.raises(v15.ProofFailure):
        v15.write_prepared_v15_plan(
            plan_path,
            plan,
            marker_path=marker_path,
            placement_ledger_path=placement_ledger_path,
            cancel_ledger_path=cancel_ledger_path,
            backend_claim_log_path=backend_claim_log_path,
            handoff_path=handoff_path,
        )


def test_v15_cancel_claim_blocks_changed_key_and_unknown_outcome_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    command = plan["cancel_command"]
    claim = v15.build_cancel_command_claim(
        plan,
        plan_sha256=plan["plan_sha256"],
        claimed_at="2026-07-12T22:45:00+00:00",
    )

    assert v15.cancel_command_claim_decision(
        [], command=command, plan_sha256=plan["plan_sha256"]
    ) == "claim"
    assert v15.cancel_command_claim_decision(
        [claim], command=command, plan_sha256=plan["plan_sha256"]
    ) == "same_key_replay"

    changed_key = deepcopy(command)
    changed_key["idempotency_key"] = "different-idempotency-key"
    assert v15.cancel_command_claim_decision(
        [claim], command=changed_key, plan_sha256=plan["plan_sha256"]
    ) == "semantic_conflict"

    unknown = {**claim, "outcome": "unknown"}
    assert v15.cancel_command_claim_decision(
        [unknown], command=command, plan_sha256=plan["plan_sha256"]
    ) == "reconcile_same_key_only"


def test_v15_execution_authority_requires_exact_unexpired_hash_before_artifacts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    plan_path = tmp_path / "v15.plan.json"
    marker_path = tmp_path / "v15.authority.json"
    placement_path = tmp_path / "v15.placements.jsonl"
    cancel_path = tmp_path / "v15.cancel-command.jsonl"
    handoff_path = tmp_path / "v15.handoff.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    os.chmod(plan_path, 0o600)

    for invalid_plan, invalid_hash, invalid_now in (
        (plan, "f" * 64, datetime(2026, 7, 12, 22, 31, tzinfo=timezone.utc)),
        (plan, plan["plan_sha256"], datetime(2026, 7, 13, 0, 31, tzinfo=timezone.utc)),
    ):
        with pytest.raises(v15.ProofFailure):
            v15.initialize_v15_execution_authority(
                plan_path,
                invalid_plan,
                expected_hash=invalid_hash,
                preflight=_preflight(),
                now=invalid_now,
                marker_path=marker_path,
                placement_ledger_path=placement_path,
                cancel_ledger_path=cancel_path,
                handoff_path=handoff_path,
            )
        assert not marker_path.exists()
        assert not placement_path.exists()
        assert not cancel_path.exists()
        assert not handoff_path.exists()

    authority = v15.initialize_v15_execution_authority(
        plan_path,
        plan,
        expected_hash=plan["plan_sha256"],
        preflight=_preflight(),
        now=datetime(2026, 7, 12, 22, 31, tzinfo=timezone.utc),
        marker_path=marker_path,
        placement_ledger_path=placement_path,
        cancel_ledger_path=cancel_path,
        handoff_path=handoff_path,
    )

    assert authority["plan_sha256"] == plan["plan_sha256"]
    assert authority["placement_attempt_maximum"] == 2
    assert authority["cancel_command_maximum"] == 1
    assert marker_path.stat().st_mode & 0o077 == 0
    assert placement_path.stat().st_mode & 0o077 == 0
    assert cancel_path.stat().st_mode & 0o077 == 0
    assert placement_path.read_bytes() == b""
    assert cancel_path.read_bytes() == b""
    assert not handoff_path.exists()

    with pytest.raises(v15.ProofFailure):
        v15.initialize_v15_execution_authority(
            plan_path,
            plan,
            expected_hash=plan["plan_sha256"],
            preflight=_preflight(),
            now=datetime(2026, 7, 12, 22, 31, tzinfo=timezone.utc),
            marker_path=marker_path,
            placement_ledger_path=placement_path,
            cancel_ledger_path=cancel_path,
            handoff_path=handoff_path,
        )


def test_v15_attempt_and_cancel_ledgers_are_exactly_bounded(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    placement_path = tmp_path / "placements.jsonl"
    cancel_path = tmp_path / "cancel.jsonl"
    placement_path.touch(mode=0o600)
    cancel_path.touch(mode=0o600)

    root_record = v15.consume_v15_placement_attempt(
        placement_path,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
        attempt_kind="root",
        exact_order_tuple=plan["root"]["order"],
        consumed_at="2026-07-12T22:40:00+00:00",
    )
    child_tuple = v15.build_execution_child_order_tuple(
        plan,
        filled_size=Decimal(plan["root"]["order"]["base_size"]),
        fresh_market={
            "best_bid": _preflight()["best_bid"],
            "observed_at": "2026-07-12T22:40:30+00:00",
        },
        price_increment=Decimal("0.01"),
    )
    child_record = v15.consume_v15_placement_attempt(
        placement_path,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
        attempt_kind="child",
        exact_order_tuple=child_tuple,
        consumed_at="2026-07-12T22:41:00+00:00",
    )
    assert root_record["sequence"] == 1
    assert child_record["sequence"] == 2
    with pytest.raises(v15.ProofFailure):
        v15.consume_v15_placement_attempt(
            placement_path,
            plan=plan,
            plan_sha256=plan["plan_sha256"],
            attempt_kind="child",
            exact_order_tuple=child_tuple,
            consumed_at="2026-07-12T22:42:00+00:00",
        )

    claim = v15.claim_v15_cancel_command(
        cancel_path,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
        claimed_at="2026-07-12T22:43:00+00:00",
    )
    assert claim["outcome"] == "claimed"
    replay = v15.claim_v15_cancel_command(
        cancel_path,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
        claimed_at="2026-07-12T22:44:00+00:00",
    )
    assert replay == claim

    changed = deepcopy(plan)
    changed["cancel_command"]["idempotency_key"] = "changed-key"
    with pytest.raises(v15.ProofFailure, match="v15_cancel_semantic_conflict"):
        v15.claim_v15_cancel_command(
            cancel_path,
            plan=changed,
            plan_sha256=plan["plan_sha256"],
            claimed_at="2026-07-12T22:45:00+00:00",
        )


def test_v15_cancel_claim_is_one_durable_record_under_concurrency(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    cancel_path = tmp_path / "cancel.jsonl"
    cancel_path.touch(mode=0o600)

    def claim() -> dict[str, object]:
        return v15.claim_v15_cancel_command(
            cancel_path,
            plan=plan,
            plan_sha256=plan["plan_sha256"],
            claimed_at="2026-07-12T22:43:00+00:00",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))

    assert claims[0] == claims[1]
    assert len(cancel_path.read_text(encoding="utf-8").splitlines()) == 1


def test_v15_offline_self_test_has_no_live_or_execution_artifacts() -> None:
    result = v15.run_offline_self_test()

    assert result["status"] == "offline_self_test_passed"
    assert result["placement_attempt_count"] == 2
    assert result["cancel_command_maximum"] == 1
    assert result["live_coinbase_orders_ran"] is False
    assert result["marker_written"] is False
    assert result["placement_ledger_written"] is False
    assert result["cancel_ledger_written"] is False
    assert result["runtime_started"] is False
