"""Durable Spot sweep automation control ledger for Admin API commands."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiModuleSupportStatus,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    SpotSweepAutomationControlAction,
    SpotSweepAutomationControlContractCheck,
    SpotSweepAutomationControlState,
)

from .models import AdminLiveAdmissionDecisionEvidence, SpotSweepAutomationControlRequest
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


SPOT_SWEEP_AUTOMATION_CONTROL_ROUTE = "/api/v1/spot/sweep/automation-controls"
SPOT_SWEEP_AUTOMATION_CONTROL_METHOD = "POST"
SPOT_SWEEP_AUTOMATION_CONTROL_SERVICE_METHOD = (
    "record_spot_sweep_automation_control"
)


class SpotSweepAutomationControlError(ValueError):
    """Raised when a Spot sweep automation control record is invalid."""


class SpotSweepAutomationControlRecord(BaseModel):
    """Append-only backend Spot sweep automation pause/resume/retry evidence."""

    model_config = ConfigDict(extra="forbid")

    control_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.SPOT_SWEEP_AUTOMATION
    )
    sweep_config_id: str = Field(min_length=1)
    campaign_id: str | None = None
    retry_plan_id: str | None = None
    control_action: SpotSweepAutomationControlAction
    previous_control_state: SpotSweepAutomationControlState = (
        SpotSweepAutomationControlState.ACTIVE
    )
    control_state_after: SpotSweepAutomationControlState = (
        SpotSweepAutomationControlState.ACTIVE
    )
    route: str = SPOT_SWEEP_AUTOMATION_CONTROL_ROUTE
    method: str = SPOT_SWEEP_AUTOMATION_CONTROL_METHOD
    module_id: str = "spot_operations"
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission = AdminApiPermission.SPOT_SWEEP_EXECUTE
    service_method: str = SPOT_SWEEP_AUTOMATION_CONTROL_SERVICE_METHOD
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str = Field(min_length=1)
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    control_recorded: bool = True
    pause_resume_control_recorded: bool = False
    retry_intent_accepted: bool = False
    scheduler_invoked: bool = False
    sweep_runner_invoked: bool = False
    coinbase_orders_submitted: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    submitted_notional_usdc: str = "0"
    executed_notional_usdc: str = "0"
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    source: str = "admin_api_spot_sweep_automation_control_log"


class SpotSweepAutomationControlContractCheckItem(BaseModel):
    """Operator-visible control contract check returned with command results."""

    model_config = ConfigDict(extra="forbid")

    check: SpotSweepAutomationControlContractCheck
    label: str = Field(min_length=1)
    status: AdminApiGateStatus
    support_status: AdminApiModuleSupportStatus = (
        AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED
    )
    route: str = SPOT_SWEEP_AUTOMATION_CONTROL_ROUTE
    method: str = SPOT_SWEEP_AUTOMATION_CONTROL_METHOD
    service_method: str = SPOT_SWEEP_AUTOMATION_CONTROL_SERVICE_METHOD
    required_permission: AdminApiPermission = AdminApiPermission.SPOT_SWEEP_EXECUTE
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    scheduler_invoked: bool = False
    sweep_runner_invoked: bool = False
    coinbase_orders_submitted: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    submitted_notional_usdc: str = "0"
    executed_notional_usdc: str = "0"
    current_evidence: str
    detail: str


class FileSpotSweepAutomationControlStore:
    """Append-only JSONL store for spot sweep automation control evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_SPOT_SWEEP_CONTROL_LOG_PATH")
            or Path("runtime_state") / "admin_api_spot_sweep_automation_controls.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: SpotSweepAutomationControlRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.control_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[SpotSweepAutomationControlRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[SpotSweepAutomationControlRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(SpotSweepAutomationControlRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_control_id(
        self,
        control_id: str,
    ) -> SpotSweepAutomationControlRecord | None:
        """Return the latest control record with the given id."""

        for record in self.read_recent(limit=500):
            if record.control_id == control_id:
                return record
        return None

    def read_for_sweep_config_id(
        self,
        sweep_config_id: str,
        *,
        limit: int = 100,
    ) -> list[SpotSweepAutomationControlRecord]:
        """Return recent control records for a sweep config id."""

        records: list[SpotSweepAutomationControlRecord] = []
        for record in self.read_recent(limit=500):
            if record.sweep_config_id != sweep_config_id:
                continue
            records.append(record)
            if len(records) >= max(1, min(limit, 500)):
                break
        return records


class AdminApiSpotSweepAutomationControlService:
    """Service boundary for backend-owned Spot sweep automation controls."""

    def record_control(
        self,
        *,
        control_store: FileSpotSweepAutomationControlStore,
        body: SpotSweepAutomationControlRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> SpotSweepAutomationControlRecord:
        recorded_at = _normalize_now(now)
        _validate_route_inventory()
        _validate_admission(
            admission_decision=admission_decision,
            sweep_config_id=body.sweep_config_id,
            payload_hash=payload_hash,
        )
        if (
            body.control_action == SpotSweepAutomationControlAction.ACCEPT_RETRY
            and not body.retry_plan_id
        ):
            raise SpotSweepAutomationControlError(
                "retry_plan_id is required when accepting retry intent."
            )

        latest = _latest_record_for_sweep(
            control_store=control_store,
            sweep_config_id=body.sweep_config_id,
        )
        previous_state = (
            latest.control_state_after
            if latest is not None
            else SpotSweepAutomationControlState.ACTIVE
        )
        control_state_after = _state_after_action(
            action=body.control_action,
            previous_state=previous_state,
        )
        control_id = _stable_id(
            "spot-sweep-automation-control",
            route=SPOT_SWEEP_AUTOMATION_CONTROL_ROUTE,
            sweep_config_id=body.sweep_config_id,
            action=body.control_action.value,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if control_store.find_by_control_id(control_id) is not None:
            raise SpotSweepAutomationControlError(
                "Spot sweep automation control record already exists."
            )

        pause_resume = body.control_action in {
            SpotSweepAutomationControlAction.PAUSE,
            SpotSweepAutomationControlAction.RESUME,
        }
        retry_accepted = (
            body.control_action == SpotSweepAutomationControlAction.ACCEPT_RETRY
        )
        record = SpotSweepAutomationControlRecord(
            control_id=control_id,
            recorded_at=recorded_at.isoformat(),
            sweep_config_id=body.sweep_config_id,
            campaign_id=body.campaign_id,
            retry_plan_id=body.retry_plan_id,
            control_action=body.control_action,
            previous_control_state=previous_state,
            control_state_after=control_state_after,
            actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload_hash=payload_hash,
            audit_id=audit_id,
            operator_reason=body.operator_reason,
            manual_live_acknowledgement=body.manual_live_acknowledgement,
            pause_resume_control_recorded=pause_resume,
            retry_intent_accepted=retry_accepted,
        )
        control_store.append(record)
        return record


def spot_sweep_automation_control_response_data(
    record: SpotSweepAutomationControlRecord,
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None,
) -> dict[str, Any]:
    """Return bounded operator-facing response data for one control record."""

    data = record.model_dump(mode="json")
    data.update(
        {
            "backend_owned": True,
            "route_bound": True,
            "idempotency_bound": True,
            "payload_bound": True,
            "operator_intent_bound": True,
            "rbac_permission_bound": True,
            "admission_decision_bound": admission_decision is not None,
            "cap_guard_boundary_bound": True,
            "control_contract_status": (
                AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED.value
            ),
        }
    )
    _attach_control_contract_checks(
        data,
        control_recorded=True,
        sweep_config_id=record.sweep_config_id,
        control_action=record.control_action,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        admission_decision=admission_decision,
        failure_stage=None,
    )
    return data


def spot_sweep_automation_control_rejected_response_data(
    *,
    sweep_config_id: str,
    control_action: SpotSweepAutomationControlAction,
    actor_id: str,
    operator_intent: str,
    idempotency_key: str,
    correlation_id: str,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
    failure_stage: str,
) -> dict[str, Any]:
    """Return bounded operator-facing response data for rejected controls."""

    payload_hash = (
        admission_decision.payload_hash if admission_decision is not None else None
    )
    data: dict[str, Any] = {
        "sweep_config_id": sweep_config_id,
        "control_action": control_action.value,
        "control_recorded": False,
        "scheduler_invoked": False,
        "sweep_runner_invoked": False,
        "coinbase_orders_submitted": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "backend_owned": True,
        "route_bound": True,
        "idempotency_bound": bool(idempotency_key),
        "payload_bound": payload_hash is not None,
        "operator_intent_bound": bool(operator_intent),
        "rbac_permission_bound": True,
        "admission_decision_bound": admission_decision is not None,
        "cap_guard_boundary_bound": True,
        "control_contract_status": (
            AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED.value
        ),
    }
    _attach_control_contract_checks(
        data,
        control_recorded=False,
        sweep_config_id=sweep_config_id,
        control_action=control_action,
        actor_id=actor_id,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload_hash=payload_hash,
        audit_id=None,
        admission_decision=admission_decision,
        failure_stage=failure_stage,
    )
    return data


def build_spot_sweep_automation_control_state(
    records: list[SpotSweepAutomationControlRecord],
) -> dict[str, Any]:
    """Summarize durable control state without invoking automation."""

    if not records:
        return {
            "sweep_config_id": None,
            "campaign_id": None,
            "latest_control_id": None,
            "latest_control_action": None,
            "latest_recorded_at": None,
            "control_state_after": SpotSweepAutomationControlState.ACTIVE.value,
            "control_count": 0,
            "pause_count": 0,
            "resume_count": 0,
            "retry_accepted_count": 0,
            "scheduler_invoked": False,
            "sweep_runner_invoked": False,
            "coinbase_orders_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }

    latest = records[0]
    return {
        "sweep_config_id": latest.sweep_config_id,
        "campaign_id": latest.campaign_id,
        "latest_control_id": latest.control_id,
        "latest_control_action": latest.control_action.value,
        "latest_recorded_at": latest.recorded_at,
        "control_state_after": latest.control_state_after.value,
        "control_count": len(records),
        "pause_count": sum(
            1
            for record in records
            if record.control_action == SpotSweepAutomationControlAction.PAUSE
        ),
        "resume_count": sum(
            1
            for record in records
            if record.control_action == SpotSweepAutomationControlAction.RESUME
        ),
        "retry_accepted_count": sum(
            1
            for record in records
            if record.control_action
            == SpotSweepAutomationControlAction.ACCEPT_RETRY
        ),
        "scheduler_invoked": any(record.scheduler_invoked for record in records),
        "sweep_runner_invoked": any(record.sweep_runner_invoked for record in records),
        "coinbase_orders_submitted": any(
            record.coinbase_orders_submitted for record in records
        ),
        "live_coinbase_orders_ran": any(
            record.live_coinbase_orders_ran for record in records
        ),
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    }


def _attach_control_contract_checks(
    data: dict[str, Any],
    *,
    control_recorded: bool,
    sweep_config_id: str,
    control_action: SpotSweepAutomationControlAction,
    actor_id: str,
    operator_intent: str,
    idempotency_key: str,
    correlation_id: str,
    payload_hash: str | None,
    audit_id: str | None,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
    failure_stage: str | None,
) -> None:
    checks = _build_control_contract_checks(
        control_recorded=control_recorded,
        sweep_config_id=sweep_config_id,
        control_action=control_action,
        actor_id=actor_id,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload_hash=payload_hash,
        audit_id=audit_id,
        admission_decision=admission_decision,
        failure_stage=failure_stage,
    )
    data["control_contract_check_count"] = len(checks)
    data["control_contract_checks"] = checks


def _build_control_contract_checks(
    *,
    control_recorded: bool,
    sweep_config_id: str,
    control_action: SpotSweepAutomationControlAction,
    actor_id: str,
    operator_intent: str,
    idempotency_key: str,
    correlation_id: str,
    payload_hash: str | None,
    audit_id: str | None,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
    failure_stage: str | None,
) -> list[dict[str, Any]]:
    idempotency_bound = bool(idempotency_key and payload_hash)
    operator_intent_bound = bool(operator_intent)
    admission_bound = admission_decision is not None
    admission_status = (
        admission_decision.status.value if admission_decision is not None else "missing"
    )
    admission_allowed = (
        admission_decision.allowed if admission_decision is not None else False
    )
    cap_guard_present = (
        admission_decision.cap_guard_present
        if admission_decision is not None
        else False
    )
    scheduler_invoked = False
    sweep_runner_invoked = False
    coinbase_orders_submitted = False
    no_live_passed = (
        not scheduler_invoked
        and not sweep_runner_invoked
        and not coinbase_orders_submitted
    )
    no_live_status = (
        AdminApiGateStatus.PASSED if no_live_passed else AdminApiGateStatus.BLOCKED
    )
    control_status = (
        AdminApiGateStatus.PASSED if control_recorded else AdminApiGateStatus.BLOCKED
    )
    return [
        _control_contract_check(
            check=SpotSweepAutomationControlContractCheck.IDEMPOTENCY,
            label="Idempotency",
            status=(
                AdminApiGateStatus.PASSED
                if idempotency_bound
                else AdminApiGateStatus.BLOCKED
            ),
            current_evidence=(
                f"Idempotency-Key {idempotency_key}; payload hash "
                f"{payload_hash or 'missing'}."
            ),
            detail=(
                "The control id is derived from route, sweep_config_id, action, "
                "idempotency key, and payload hash; replay is handled by the "
                "shared Admin API idempotency store."
            ),
        ),
        _control_contract_check(
            check=SpotSweepAutomationControlContractCheck.OPERATOR_INTENT,
            label="Operator intent",
            status=(
                AdminApiGateStatus.PASSED
                if operator_intent_bound
                else AdminApiGateStatus.BLOCKED
            ),
            current_evidence=(
                f"actor {actor_id}; intent {operator_intent or 'missing'}; "
                f"correlation {correlation_id}."
            ),
            detail=(
                "Operator intent is supplied through X-Operator-Intent and is "
                "included in the route-bound payload hash."
            ),
        ),
        _control_contract_check(
            check=SpotSweepAutomationControlContractCheck.RBAC_PERMISSION,
            label="RBAC permission",
            status=AdminApiGateStatus.PASSED,
            current_evidence=(
                f"Permission {AdminApiPermission.SPOT_SWEEP_EXECUTE.value}; "
                "route adapter calls require_permission before recording control evidence."
            ),
            detail=(
                "A missing role is rejected before the service records a control "
                "row, so any service response has passed the route RBAC boundary."
            ),
        ),
        _control_contract_check(
            check=SpotSweepAutomationControlContractCheck.ADMISSION_AUDIT,
            label="Admission evidence",
            status=(
                AdminApiGateStatus.PASSED
                if admission_bound
                else AdminApiGateStatus.BLOCKED
            ),
            current_evidence=(
                f"admission {admission_status}; allowed {admission_allowed}; "
                f"identity sweep_config_id={sweep_config_id}."
            ),
            detail=(
                "The route binds the control to the shared admission decision "
                "before invoking the backend command service."
            ),
        ),
        _control_contract_check(
            check=SpotSweepAutomationControlContractCheck.CAP_GUARD_BOUNDARY,
            label="Cap/guard boundary",
            status=AdminApiGateStatus.NOT_APPLICABLE,
            current_evidence=(
                f"cap_guard_present {cap_guard_present}; submitted/executed "
                "notional 0/0 USDC."
            ),
            detail=(
                "This control records local pause/resume/retry intent only. "
                "Cap/guard execution gates remain part of live sweep execution, "
                "not browser-side automation control authority."
            ),
        ),
        _control_contract_check(
            check=SpotSweepAutomationControlContractCheck.LOCAL_CONTROL_LEDGER,
            label="Local control ledger",
            status=control_status,
            current_evidence=(
                f"{control_action.value}; recorded {control_recorded}; "
                f"audit {audit_id or 'not_recorded'}; "
                f"failure_stage {failure_stage or 'none'}."
            ),
            detail=(
                "Accepted controls append durable local evidence only; they do "
                "not invoke scheduler dispatch, retry execution, reconciliation, "
                "or Coinbase order placement."
            ),
        ),
        _control_contract_check(
            check=SpotSweepAutomationControlContractCheck.NO_LIVE_EXECUTION,
            label="No-live execution",
            status=no_live_status,
            current_evidence=(
                "scheduler false; runner false; coinbase false; notional "
                "0/0 USDC."
            ),
            detail=(
                "The command response is fail-closed for live exchange execution "
                "and reports zero submitted and executed notional."
            ),
        ),
        _control_contract_check(
            check=SpotSweepAutomationControlContractCheck.FRONTEND_AUTHORITY,
            label="Frontend authority",
            status=AdminApiGateStatus.PASSED,
            current_evidence=(
                "browser display_only; BFF forward_only_no_execution; no second "
                "automation path."
            ),
            detail=(
                "The frontend may submit the canonical backend wrapper request "
                "only; it must not schedule, retry, reconcile, or call Coinbase."
            ),
        ),
    ]


def _control_contract_check(
    *,
    check: SpotSweepAutomationControlContractCheck,
    label: str,
    status: AdminApiGateStatus,
    current_evidence: str,
    detail: str,
) -> dict[str, Any]:
    return SpotSweepAutomationControlContractCheckItem(
        check=check,
        label=label,
        status=status,
        current_evidence=current_evidence,
        detail=detail,
    ).model_dump(mode="json")


def _latest_record_for_sweep(
    *,
    control_store: FileSpotSweepAutomationControlStore,
    sweep_config_id: str,
) -> SpotSweepAutomationControlRecord | None:
    records = control_store.read_for_sweep_config_id(sweep_config_id, limit=1)
    return records[0] if records else None


def _state_after_action(
    *,
    action: SpotSweepAutomationControlAction,
    previous_state: SpotSweepAutomationControlState,
) -> SpotSweepAutomationControlState:
    if action == SpotSweepAutomationControlAction.PAUSE:
        return SpotSweepAutomationControlState.PAUSED
    if action == SpotSweepAutomationControlAction.RESUME:
        return SpotSweepAutomationControlState.ACTIVE
    return previous_state


def _validate_route_inventory() -> None:
    for item in ADMIN_API_ROUTE_INVENTORY:
        if (
            item.surface
            == f"{SPOT_SWEEP_AUTOMATION_CONTROL_METHOD} {SPOT_SWEEP_AUTOMATION_CONTROL_ROUTE}"
            and item.shared_method == SPOT_SWEEP_AUTOMATION_CONTROL_SERVICE_METHOD
        ):
            return
    raise SpotSweepAutomationControlError(
        "Spot sweep automation control route inventory entry is missing."
    )


def _validate_admission(
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    sweep_config_id: str,
    payload_hash: str,
) -> None:
    if admission_decision.route != SPOT_SWEEP_AUTOMATION_CONTROL_ROUTE:
        raise SpotSweepAutomationControlError(
            "Admission route does not match automation control route."
        )
    if admission_decision.method != SPOT_SWEEP_AUTOMATION_CONTROL_METHOD:
        raise SpotSweepAutomationControlError(
            "Admission method does not match automation control method."
        )
    if admission_decision.identity_key != "sweep_config_id":
        raise SpotSweepAutomationControlError(
            "Admission identity key must be sweep_config_id."
        )
    if admission_decision.identity_value != sweep_config_id:
        raise SpotSweepAutomationControlError(
            "Admission identity value does not match sweep_config_id."
        )
    if admission_decision.service_method != SPOT_SWEEP_AUTOMATION_CONTROL_SERVICE_METHOD:
        raise SpotSweepAutomationControlError(
            "Admission service method does not match automation control service."
        )
    if admission_decision.payload_hash != payload_hash:
        raise SpotSweepAutomationControlError(
            "Admission payload hash does not match automation control payload."
        )


def _normalize_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _stable_id(prefix: str, **values: Any) -> str:
    material = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:{material}"))
