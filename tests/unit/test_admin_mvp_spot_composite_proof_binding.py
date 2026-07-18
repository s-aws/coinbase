from __future__ import annotations

from copy import deepcopy

import pytest

from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
)
from application.admin_api.models import (
    AdminApiCommandResponse,
    AdminLiveAdmissionDecisionEvidence,
)
from application.admin_api.mvp_service import (
    AdminMvpRequestContext,
    AdminMvpService,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiPermission,
)


_ACTOR_ID = "trader-proof-origin"
_PROOF_ADMIN_ID = "admin-proof-recorder"


def _proof_admin_context(kind: str) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=f"proof-record-{kind}",
        correlation_id=f"proof-correlation-{kind}",
        operator_intent=f"record_{kind}_proof_chain",
        actor_id=_PROOF_ADMIN_ID,
        roles=("admin",),
    )


def _first_pass(
    tmp_path,
    *,
    kind: str,
) -> tuple[FileIdempotencyStore, dict[str, str]]:
    manual = kind == "manual"
    client_order_id = f"client-{kind}-first-pass"
    command_key = f"command-{kind}-first-pass"
    original_intent = (
        "manual_one_off" if manual else "cancel_by_client_order_id"
    )
    payload_hash = ("a" if manual else "b") * 64
    route = (
        "/api/v1/orders"
        if manual
        else "/api/v1/orders/{client_order_id}/cancel"
    )
    endpoint = (
        "POST /api/v1/orders"
        if manual
        else f"POST /api/v1/orders/{client_order_id}/cancel"
    )
    action_class = (
        AdminApiActionClass.LIVE_EXCHANGE_PLACE
        if manual
        else AdminApiActionClass.LIVE_EXCHANGE_CANCEL
    )
    permission = (
        AdminApiPermission.ORDER_CREATE
        if manual
        else AdminApiPermission.ORDER_CANCEL
    )
    service_method = (
        "place_manual_order"
        if manual
        else "cancel_order_by_client_order_id"
    )
    admission = AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route=route,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=action_class,
        required_permission=permission,
        service_method=service_method,
        actor_id=_ACTOR_ID,
        idempotency_key=command_key,
        operator_intent=original_intent,
        payload_hash=payload_hash,
        live_exchange_submitted=False,
        blockers=[AdminApiLiveAdmissionBlocker.APPROVAL_SNAPSHOT_MISSING],
        detail="Exact durable no-live first pass for proof binding.",
    )
    response = AdminApiCommandResponse(
        status=AdminApiCommandStatus.NOT_IMPLEMENTED,
        action_class=action_class,
        required_permission=permission,
        service_method=service_method,
        message="First pass stopped before Coinbase.",
        client_order_id=client_order_id,
        correlation_id=f"command-correlation-{kind}",
        idempotency_key=command_key,
        admission_decision=admission,
        live_exchange_submitted=False,
        live_coinbase_orders_ran=False,
        failure_stage="approval_required",
    )
    store = FileIdempotencyStore(tmp_path / f"{kind}-idempotency.jsonl")
    store.put_record(
        IdempotencyRecord(
            idempotency_key=command_key,
            payload_hash=payload_hash,
            client_order_id=client_order_id,
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            response=response.model_dump(mode="json"),
            actor_id=_ACTOR_ID,
            endpoint=endpoint,
        )
    )
    assertion = {
        "route": route,
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": client_order_id,
        "action_class": action_class.value,
        "required_permission": permission.value,
        "service_method": service_method,
        "actor_id": _ACTOR_ID,
        "operator_intent": original_intent,
        "command_idempotency_key": command_key,
        "payload_hash": payload_hash,
    }
    return store, assertion


@pytest.mark.parametrize("kind", ["manual", "cancel"])
def test_composite_spot_proof_uses_exact_durable_first_pass_context(
    tmp_path,
    kind,
):
    command_store, assertion = _first_pass(tmp_path, kind=kind)
    service = AdminMvpService()
    recorder = getattr(service, f"record_spot_{kind}_order_proof_chain")

    result = recorder(
        assertion,
        _proof_admin_context(kind),
        command_idempotency_store=command_store,
    )

    assert result.status_code == 200
    admission_audit = next(iter(service.store.admission_audits.values()))
    assert admission_audit["actor_id"] == _ACTOR_ID
    assert admission_audit["operator_intent"] == assertion["operator_intent"]
    assert admission_audit["identity_value"] == assertion["identity_value"]
    assert admission_audit["payload_hash"] == assertion["payload_hash"]
    if kind == "manual":
        approval_request = next(iter(service.store.approval_requests.values()))
        assert approval_request["requested_by_actor_id"] == _PROOF_ADMIN_ID


@pytest.mark.parametrize("kind", ["manual", "cancel"])
@pytest.mark.parametrize(
    ("field", "spoofed"),
    [
        ("route", "/api/v1/futures/orders"),
        ("method", "GET"),
        ("module_id", "futures_perpetuals"),
        ("identity_key", "order_id"),
        ("identity_value", "client-spoofed"),
        ("action_class", "local_state_mutation"),
        ("required_permission", "audit:read"),
        ("service_method", "spoofed_service"),
        ("actor_id", "spoofed-actor"),
        ("operator_intent", "spoofed_intent"),
        ("command_idempotency_key", "spoofed-command-key"),
        ("payload_hash", "f" * 64),
    ],
)
def test_composite_spot_proof_rejects_body_context_spoofing_before_writes(
    tmp_path,
    kind,
    field,
    spoofed,
):
    command_store, assertion = _first_pass(tmp_path, kind=kind)
    assertion[field] = spoofed
    service = AdminMvpService()
    recorder = getattr(service, f"record_spot_{kind}_order_proof_chain")

    result = recorder(
        assertion,
        _proof_admin_context(kind),
        command_idempotency_store=command_store,
    )

    assert result.status_code == 400
    assert service.store.approval_requests == {}
    assert service.store.approval_snapshots == {}
    assert service.store.admission_audits == {}
    assert service.store.cap_guard_decisions == {}
    assert service.store.reconciliation_plans == {}


@pytest.mark.parametrize("kind", ["manual", "cancel"])
@pytest.mark.parametrize(
    "missing_field",
    [
        "identity_value",
        "actor_id",
        "operator_intent",
        "command_idempotency_key",
        "payload_hash",
    ],
)
def test_composite_spot_proof_rejects_missing_required_assertions(
    tmp_path,
    kind,
    missing_field,
):
    command_store, assertion = _first_pass(tmp_path, kind=kind)
    assertion.pop(missing_field)
    service = AdminMvpService()
    recorder = getattr(service, f"record_spot_{kind}_order_proof_chain")

    result = recorder(
        assertion,
        _proof_admin_context(kind),
        command_idempotency_store=command_store,
    )

    assert result.status_code == 400
    assert service.store.admission_audits == {}
    assert service.store.reconciliation_plans == {}


@pytest.mark.parametrize("kind", ["manual", "cancel"])
@pytest.mark.parametrize("record_mutation", ["accepted", "live"])
def test_composite_spot_proof_rejects_non_no_live_first_pass(
    tmp_path,
    kind,
    record_mutation,
):
    command_store, assertion = _first_pass(tmp_path, kind=kind)
    record = command_store.get_record(assertion["command_idempotency_key"])
    assert record is not None
    response = deepcopy(record.response)
    if record_mutation == "accepted":
        response["status"] = AdminApiCommandStatus.ACCEPTED.value
        record = record.model_copy(
            update={"status": AdminApiCommandStatus.ACCEPTED, "response": response}
        )
    else:
        response["live_exchange_submitted"] = True
        response["live_coinbase_orders_ran"] = True
        record = record.model_copy(update={"response": response})
    command_store.put_record(record)
    service = AdminMvpService()
    recorder = getattr(service, f"record_spot_{kind}_order_proof_chain")

    result = recorder(
        assertion,
        _proof_admin_context(kind),
        command_idempotency_store=command_store,
    )

    assert result.status_code == 400
    assert service.store.admission_audits == {}
    assert service.store.reconciliation_plans == {}
