"""Fake-only execution-path tests for the sealed V15 child cancel slice."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import inspect
import json
import os

import pytest

from tools import run_controlled_admin_spot_child_cancel_slice as v15
from tools import run_controlled_admin_spot_root_child_batch as base


def _preflight() -> dict[str, object]:
    return {
        "portfolio_id": v15.TEST_PORTFOLIO_ID,
        "wallets": {"USDC": "980", "BTC": "0.0002"},
        "product": {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
        },
        "best_bid": "64129.52",
        "best_ask": "64129.53",
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
        approval_id=(
            "controlled-child-cancel-v15-"
            "11111111-1111-4111-8111-111111111111"
        ),
    )


def _write_plan(path, plan) -> None:
    path.write_text(json.dumps(plan), encoding="utf-8")
    os.chmod(path, 0o600)


_MONITOR_IDENTITY = {
    "schema_version": "1",
    "semantic_key": "1" * 64,
    "controlled_plan_sha256": "2" * 64,
    "root_client_order_id": "root-v15",
    "child_client_order_id": "child-v15",
    "idempotency_key": "idem-v15",
    "payload_hash": "3" * 64,
    "correlation_id": "corr-v15",
    "actor_id": base.ACTOR_ID,
    "source": "admin_api_root_child_cancel_claim_log",
}


def _backend_claim_event(
    event: str,
    outcome: str,
    *,
    reconciliation_required: bool,
) -> dict[str, object]:
    return {
        **_MONITOR_IDENTITY,
        "event": event,
        "recorded_at": "2026-07-12T22:45:00+00:00",
        "outcome": outcome,
        "response": (
            None
            if event != "outcome"
            else {
                "client_order_id": "root-v15",
                "stealth_order_id": "child-v15",
                "idempotency_key": "idem-v15",
                "correlation_id": "corr-v15",
                "data": {"controlled_plan_sha256": "2" * 64},
            }
        ),
        "reconciliation_required": reconciliation_required,
    }


def test_execute_authorization_fails_before_any_artifact_on_all_preflight_drift(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    plan_path = tmp_path / "v15.plan.json"
    marker = tmp_path / "marker.json"
    placements = tmp_path / "placements.jsonl"
    local_cancel = tmp_path / "cancel.jsonl"
    backend_claims = tmp_path / "backend-claims.jsonl"
    handoff = tmp_path / "handoff.json"
    _write_plan(plan_path, plan)

    variants = [
        {"expected_hash": "f" * 64},
        {"active_zero": {"stable_zero": False}},
        {"fresh_ids": {"fresh_read": False}},
        {
            "now": datetime(2026, 7, 13, 0, 31, tzinfo=timezone.utc),
        },
    ]
    for variant in variants:
        with pytest.raises(v15.ProofFailure):
            v15.authorize_v15_execution(
                plan_path,
                expected_hash=variant.get(
                    "expected_hash", plan["plan_sha256"]
                ),
                preflight=_preflight(),
                active_zero=variant.get(
                    "active_zero", {"stable_zero": True}
                ),
                fresh_ids=variant.get(
                    "fresh_ids", {"fresh_read": True}
                ),
                now=variant.get(
                    "now",
                    datetime(2026, 7, 12, 22, 31, tzinfo=timezone.utc),
                ),
                marker_path=marker,
                placement_ledger_path=placements,
                cancel_ledger_path=local_cancel,
                backend_claim_log_path=backend_claims,
                handoff_path=handoff,
            )
        assert not any(
            path.exists()
            for path in (
                marker,
                placements,
                local_cancel,
                backend_claims,
                handoff,
            )
        )


def test_execute_authorization_creates_exact_owner_only_budgets_and_claim_log(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    plan_path = tmp_path / "v15.plan.json"
    marker = tmp_path / "marker.json"
    placements = tmp_path / "placements.jsonl"
    local_cancel = tmp_path / "cancel.jsonl"
    backend_claims = tmp_path / "backend-claims.jsonl"
    handoff = tmp_path / "handoff.json"
    _write_plan(plan_path, plan)

    authority = v15.authorize_v15_execution(
        plan_path,
        expected_hash=plan["plan_sha256"],
        preflight=_preflight(),
        active_zero={"stable_zero": True},
        fresh_ids={"fresh_read": True},
        now=datetime(2026, 7, 12, 22, 31, tzinfo=timezone.utc),
        marker_path=marker,
        placement_ledger_path=placements,
        cancel_ledger_path=local_cancel,
        backend_claim_log_path=backend_claims,
        handoff_path=handoff,
    )

    assert authority["placement_attempt_maximum"] == 2
    assert authority["root_placement_maximum"] == 1
    assert authority["child_placement_maximum"] == 1
    assert authority["cancel_command_maximum"] == 1
    assert authority["backend_claim_log_path"] == str(backend_claims)
    for path in (marker, placements, local_cancel, backend_claims):
        assert path.exists()
        assert path.stat().st_mode & 0o077 == 0
    assert placements.read_bytes() == b""
    assert local_cancel.read_bytes() == b""
    assert backend_claims.read_bytes() == b""
    assert not handoff.exists()


def test_v15_handoff_records_actual_route_proofs_only_after_authority(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    handoff_path = tmp_path / "handoff.json"
    cancel = plan["cancel_command"]
    proofs = {
        "approval_id": cancel["approval_snapshot_id"],
        "admission_audit_id": "audit-route-created-1",
        "cap_guard_decision_id": cancel["cap_guard_decision_id"],
        "reconciliation_plan_id": cancel["reconciliation_plan_id"],
    }
    context, _ = v15.build_v15_cancel_admission_context(
        plan,
        plan_sha256=plan["plan_sha256"],
    )
    from api.v1.routes.orders import _idempotency_payload_hash
    from application.admin_api.models import AdminApiActor

    expected_payload_hash = _idempotency_payload_hash(
        endpoint=(
            f"POST /api/v1/orders/{plan['root']['client_order_id']}/"
            "fill-follow-up/child-cancel"
        ),
        actor=AdminApiActor(
            actor_id=base.ACTOR_ID,
            roles=[base.COMMAND_ROLE],
        ),
        operator_intent=cancel["operator_intent"],
        body={
            "reason": "cancel_active_deterministic_first_child",
            "manual_live_acknowledgement": True,
            "controlled_plan_sha256": plan["plan_sha256"],
        },
        path_params={
            "root_client_order_id": plan["root"]["client_order_id"]
        },
    )
    assert context["payload_hash"] == expected_payload_hash

    handoff = v15.write_v15_cancel_proof_handoff(
        handoff_path,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
        context=context,
        proofs=proofs,
        recorded_at="2026-07-12T22:45:00+00:00",
    )

    assert json.loads(handoff_path.read_text(encoding="utf-8")) == handoff
    assert handoff_path.stat().st_mode & 0o077 == 0
    assert handoff["approval_snapshot_id"] == proofs["approval_id"]
    assert handoff["admission_audit_id"] == "audit-route-created-1"
    assert handoff["identity_value"] == plan["root"]["client_order_id"]
    assert handoff["payload_hash"] == context["payload_hash"]
    changed = deepcopy(proofs)
    changed["cap_guard_decision_id"] = "wrong-cap"
    with pytest.raises(v15.ProofFailure):
        v15.write_v15_cancel_proof_handoff(
            tmp_path / "wrong.json",
            plan=plan,
            plan_sha256=plan["plan_sha256"],
            context=context,
            proofs=changed,
            recorded_at="2026-07-12T22:45:00+00:00",
        )
    wrong_context = deepcopy(context)
    wrong_context["identity_value"] = plan["child"]["client_order_id"]
    with pytest.raises(v15.ProofFailure, match="v15_handoff_route_context_mismatch"):
        v15.write_v15_cancel_proof_handoff(
            tmp_path / "wrong-context.json",
            plan=plan,
            plan_sha256=plan["plan_sha256"],
            context=wrong_context,
            proofs=proofs,
            recorded_at="2026-07-12T22:45:00+00:00",
        )


def test_v15_readiness_requires_root_route_identity_and_backend_resolved_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    root = plan["root"]
    child = plan["child"]
    cancel = plan["cancel_command"]
    readiness = {
        "type": "admin_order_fill_follow_up_child_cancel_readiness",
        "found": True,
        "ready": True,
        "readiness_status": "ready",
        "root_client_order_id": root["client_order_id"],
        "child_client_order_id": child["client_order_id"],
        "product_id": v15.PRODUCT_ID,
        "profile_alias": v15.PROFILE_LABEL,
        "portfolio_id": v15.TEST_PORTFOLIO_ID,
        "controlled_batch_id": plan["batch_id"],
        "controlled_batch_slot": 1,
        "controlled_plan_sha256": plan["plan_sha256"],
        "approval_snapshot_id": cancel["approval_snapshot_id"],
        "audit_id": "audit-route-created-1",
        "cap_guard_decision_id": cancel["cap_guard_decision_id"],
        "reconciliation_plan_id": cancel["reconciliation_plan_id"],
        "cancel_idempotency_key": cancel["idempotency_key"],
        "cancel_correlation_id": cancel["correlation_id"],
        "cancel_operator_intent": cancel["operator_intent"],
        "backend_decision": "allowed",
        "environment": "local-controlled-live-test-profile",
        "active_placement_proven": True,
        "zero_fill_proven": True,
        "exchange_order_id_evidence_present": True,
        "exchange_order_id_evidence_only": True,
        "reconciliation_required": False,
        "blockers": [],
        "read_only": True,
        "live_coinbase_orders_ran": False,
        "coinbase_order_cancel_submitted": False,
        "root_reference_notional_usdc": plan[
            "root_reference_notional_usdc"
        ],
        "child_reference_notional_usdc": "1.90",
        "aggregate_reference_notional_usdc": "2.92",
        "root_notional_cap_usdc": "9.99",
        "child_notional_cap_usdc": "2.00",
        "aggregate_notional_cap_usdc": "12.00",
    }

    assert cancel["identity_value"] == root["client_order_id"]
    assert v15._validate_v15_cancel_readiness(
        readiness,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
    )["child_client_order_id"] == child["client_order_id"]
    changed = deepcopy(readiness)
    changed["root_client_order_id"] = child["client_order_id"]
    with pytest.raises(v15.ProofFailure):
        v15._validate_v15_cancel_readiness(
            changed,
            plan=plan,
            plan_sha256=plan["plan_sha256"],
        )


def test_v15_runner_hands_cancel_to_operator_ui_and_never_posts_or_claims_it() -> None:
    source = inspect.getsource(v15.execute_v15_plan)

    assert '"awaiting_operator_ui_root_scoped_cancel"' in source
    assert "claim_v15_cancel_command(" not in source
    assert "record_v15_cancel_outcome(" not in source
    assert '"POST",\n                    cancel_path' not in source


def test_v15_cancel_handoff_precedes_the_only_child_exchange_submission() -> None:
    source = inspect.getsource(v15.execute_v15_plan)

    handoff = source.index("handoff = write_v15_cancel_proof_handoff(")
    child_exchange_submission = source.index(
        "child_status, child_response, child_response_headers = runtime.request("
    )
    root_terminal = source.index("root_exchange = base._wait_for_exchange_terminal(")
    child_attempt = source.index("child_attempt = consume_v15_placement_attempt(")

    assert root_terminal < child_attempt < handoff < child_exchange_submission
    assert source.count("handoff = write_v15_cancel_proof_handoff(") == 1
    assert source.count(
        "child_status, child_response, child_response_headers = runtime.request("
    ) == 1


@pytest.mark.parametrize(
    ("backend_rows", "now", "expected"),
    [
        (
            [],
            datetime(2026, 7, 12, 22, 45, tzinfo=timezone.utc),
            "awaiting_operator_ui_root_scoped_cancel",
        ),
        (
            [],
            datetime(2026, 7, 13, 0, 31, tzinfo=timezone.utc),
            "plan_expired_active_child_reconciliation_only",
        ),
        (
            [
                _backend_claim_event(
                    "claim", "claimed", reconciliation_required=False
                )
            ],
            datetime(2026, 7, 12, 22, 45, tzinfo=timezone.utc),
            "operator_cancel_ambiguous_reconciliation_only",
        ),
        (
            [
                _backend_claim_event(
                    "claim", "claimed", reconciliation_required=False
                ),
                _backend_claim_event(
                    "exchange_boundary",
                    "unknown",
                    reconciliation_required=True,
                ),
            ],
            datetime(2026, 7, 12, 22, 45, tzinfo=timezone.utc),
            "operator_cancel_ambiguous_reconciliation_only",
        ),
        (
            [
                _backend_claim_event(
                    "claim", "claimed", reconciliation_required=False
                ),
                _backend_claim_event(
                    "exchange_boundary",
                    "unknown",
                    reconciliation_required=True,
                ),
                _backend_claim_event(
                    "outcome", "accepted", reconciliation_required=False
                ),
            ],
            datetime(2026, 7, 12, 22, 45, tzinfo=timezone.utc),
            "verify_terminal_closeout",
        ),
        (
            [
                _backend_claim_event(
                    "claim", "claimed", reconciliation_required=False
                ),
                _backend_claim_event(
                    "outcome", "rejected", reconciliation_required=False
                ),
            ],
            datetime(2026, 7, 12, 22, 45, tzinfo=timezone.utc),
            "operator_cancel_rejected_active_child_reconciliation_only",
        ),
        (
            [
                _backend_claim_event(
                    "claim", "claimed", reconciliation_required=False
                ),
                _backend_claim_event(
                    "exchange_boundary",
                    "unknown",
                    reconciliation_required=True,
                ),
                _backend_claim_event(
                    "outcome", "unknown", reconciliation_required=True
                ),
            ],
            datetime(2026, 7, 12, 22, 45, tzinfo=timezone.utc),
            "operator_cancel_ambiguous_reconciliation_only",
        ),
    ],
)
def test_v15_operator_monitor_restart_and_expiry_never_authorize_a_command(
    backend_rows,
    now,
    expected,
) -> None:
    assert v15.v15_operator_monitor_decision(
        [{"attempt_kind": "root"}, {"attempt_kind": "child"}],
        [],
        backend_rows,
        expected_identity=_MONITOR_IDENTITY,
        now=now,
        expires_at="2026-07-13T00:30:00+00:00",
    ) == expected


def test_v15_operator_monitor_rejects_backend_claim_identity_drift() -> None:
    drifted = _backend_claim_event(
        "claim", "claimed", reconciliation_required=False
    )
    drifted["correlation_id"] = "drifted-correlation"

    with pytest.raises(v15.ProofFailure, match="v15_monitor_backend_claim_identity"):
        v15.v15_operator_monitor_decision(
            [{"attempt_kind": "root"}, {"attempt_kind": "child"}],
            [],
            [drifted],
            expected_identity=_MONITOR_IDENTITY,
            now=datetime(2026, 7, 12, 22, 45, tzinfo=timezone.utc),
            expires_at="2026-07-13T00:30:00+00:00",
        )


def test_v15_terminal_claim_validator_requires_claim_boundary_accepted_triplet(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    identity = v15.v15_backend_claim_identity(
        plan,
        plan_sha256=plan["plan_sha256"],
    )
    accepted_response = {
        "status": "accepted",
        "client_order_id": plan["root"]["client_order_id"],
        "stealth_order_id": plan["child"]["client_order_id"],
        "idempotency_key": plan["cancel_command"]["idempotency_key"],
        "correlation_id": plan["cancel_command"]["correlation_id"],
        "data": {
            "controlled_plan_sha256": plan["plan_sha256"],
            "cancellation_readback": {
                "authoritative": True,
                "pagination_complete": True,
                "exact_identity_match": True,
                "authoritative_status": "CANCELLED",
                "matched_order": {
                    "client_order_id": plan["child"]["client_order_id"],
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
    }
    rows = [
        {
            **identity,
            "event": "claim",
            "recorded_at": "2026-07-12T22:45:00+00:00",
            "outcome": "claimed",
            "response": None,
            "reconciliation_required": False,
        },
        {
            **identity,
            "event": "exchange_boundary",
            "recorded_at": "2026-07-12T22:45:01+00:00",
            "outcome": "unknown",
            "response": None,
            "reconciliation_required": True,
        },
        {
            **identity,
            "event": "outcome",
            "recorded_at": "2026-07-12T22:45:02+00:00",
            "outcome": "accepted",
            "response": accepted_response,
            "reconciliation_required": False,
        },
    ]
    path = tmp_path / "backend-claims.jsonl"
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    path.chmod(0o600)

    proof = v15._validate_v15_backend_cancel_claim_log(
        path,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
    )

    assert proof["claim_event_count"] == 1
    assert proof["exchange_boundary_event_count"] == 1
    assert proof["outcome_event_count"] == 1
    assert proof["backend_claim_event_count"] == 3


def test_v15_zero_fill_requires_all_explicit_exchange_fields() -> None:
    exact = {
        "filled_size": "0",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": 0,
    }

    assert v15.validate_v15_explicit_zero_fill(exact) == exact
    for field in exact:
        incomplete = dict(exact)
        incomplete.pop(field)
        with pytest.raises(v15.ProofFailure, match="v15_zero_fill_field_missing"):
            v15.validate_v15_explicit_zero_fill(incomplete)


def test_v15_local_cancel_ledger_is_one_claim_plus_one_terminal_outcome(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    ledger = tmp_path / "cancel.jsonl"
    ledger.touch(mode=0o600)
    claimed = v15.claim_v15_cancel_command(
        ledger,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
        claimed_at="2026-07-12T22:45:00+00:00",
    )
    accepted = v15.record_v15_cancel_outcome(
        ledger,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
        outcome="accepted",
        recorded_at="2026-07-12T22:45:01+00:00",
        response={"status": "accepted"},
    )

    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert rows == [claimed, accepted]
    assert v15.v15_resume_decision(
        [{"attempt_kind": "root"}, {"attempt_kind": "child"}],
        rows,
    ) == "verify_terminal_closeout"
    with pytest.raises(v15.ProofFailure, match="v15_cancel_outcome_already_recorded"):
        v15.record_v15_cancel_outcome(
            ledger,
            plan=plan,
            plan_sha256=plan["plan_sha256"],
            outcome="accepted",
            recorded_at="2026-07-12T22:45:02+00:00",
            response={"status": "accepted"},
        )


@pytest.mark.parametrize(
    ("placements", "cancel_rows", "expected"),
    [
        ([], [], "submit_root"),
        ([{"attempt_kind": "root"}], [], "reconcile_root_no_new_placement"),
        (
            [{"attempt_kind": "root"}, {"attempt_kind": "child"}],
            [],
            "inspect_child_no_new_placement",
        ),
        (
            [{"attempt_kind": "root"}, {"attempt_kind": "child"}],
            [{"outcome": "claimed"}],
            "reconcile_cancel_same_key_only",
        ),
        (
            [{"attempt_kind": "root"}, {"attempt_kind": "child"}],
            [{"outcome": "unknown"}],
            "reconcile_cancel_same_key_only",
        ),
        (
            [{"attempt_kind": "root"}, {"attempt_kind": "child"}],
            [{"outcome": "accepted"}],
            "verify_terminal_closeout",
        ),
    ],
)
def test_v15_interrupt_resume_never_duplicates_a_consumed_boundary(
    placements,
    cancel_rows,
    expected,
) -> None:
    assert v15.v15_resume_decision(placements, cancel_rows) == expected


def test_v15_execute_cli_requires_fixed_plan_and_exact_hash() -> None:
    with pytest.raises(v15.ProofFailure, match="v15_execute_plan_file_required"):
        v15.main(["--execute-v15-plan"])
    with pytest.raises(v15.ProofFailure, match="v15_execute_plan_file_not_fixed"):
        v15.main(
            [
                "--execute-v15-plan",
                "--plan-file",
                "/tmp/not-the-fixed-plan.json",
                "--confirm-plan-sha256",
                "a" * 64,
            ]
        )
    with pytest.raises(v15.ProofFailure, match="v15_execute_plan_hash_required"):
        v15.main(
            [
                "--execute-v15-plan",
                "--plan-file",
                str(v15.PLAN_PATH),
            ]
        )


def test_canonical_embedded_sentinel_accepts_only_v15_two_attempt_scope(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    ledger = tmp_path / "placements.jsonl"
    ledger.touch(mode=0o600)
    root = v15.consume_v15_placement_attempt(
        ledger,
        plan=plan,
        plan_sha256=plan["plan_sha256"],
        attempt_kind="root",
        exact_order_tuple=plan["root"]["order"],
        consumed_at="2026-07-12T22:40:00+00:00",
    )

    assert base.is_v15_plan(plan) is True
    assert base.current_generation_limits(plan) == (1, 1, 2)
    authority = base.build_runtime_child_authority_payload(
        state_dir=tmp_path,
        auth_file=tmp_path / "authority.json",
        global_batch_marker=tmp_path / "marker.json",
        global_batch_marker_sha256="a" * 64,
        attempt_ledger_path=ledger,
        confirmed_plan=plan,
        confirmed_plan_hash=plan["plan_sha256"],
        confirmed_runner_sha256="e" * 64,
        parent_pid=123,
        parent_start_identity="start-123",
        nonce="nonce",
    )
    assert authority["batch_size"] == 1
    records = base.read_batch_attempt_ledger(
        ledger,
        confirmed_plan=plan,
        confirmed_plan_hash=plan["plan_sha256"],
    )
    assert records == [root]
    assert base.authorized_sdk_tuple_for_call(
        records,
        attempt_kind="root",
        prior_call_count=0,
        confirmed_plan=plan,
    ) == plan["root"]["order"]
    with pytest.raises(base.ProofFailure):
        base.authorized_sdk_tuple_for_call(
            records,
            attempt_kind="root",
            prior_call_count=1,
            confirmed_plan=plan,
        )
