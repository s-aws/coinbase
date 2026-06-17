"""Live execution service posture for Admin API command admission.

This module intentionally exposes service-state evidence only. It does not
place, cancel, move, reconcile, or submit Coinbase orders.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Protocol, Sequence
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiLiveAdapterConstructionArtifact,
    AdminApiLiveAdapterDecisionResolutionStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
)


DISABLED_LIVE_EXECUTION_SERVICE_SOURCE = "disabled_backend_service"
DISABLED_STEALTH_LIVE_EXECUTION_ADAPTER_SOURCE = (
    "disabled_stealth_command_live_adapter"
)
POST_WRITE_RECONCILIATION_ROUTE = "/api/v1/admin/reconciliation/plans"
POST_WRITE_RECONCILIATION_METHOD = "POST"
POST_WRITE_RECONCILIATION_SOURCE = "post_write_reconciliation_contract"
EXECUTION_BOUNDARY_AUTHORITY = "backend_contract_only_no_execution"
LIVE_EXECUTION_DISABLED_REASON = "live_execution_disabled"
DISABLED_LIVE_EXECUTION_FORBIDDEN_METHODS = (
    "create_order",
    "cancel_order",
    "execute",
    "submit",
    "coinbase_client",
)
LIVE_EXECUTION_SERVICE_ENABLEMENT_AUTHORITY = "backend_runtime_configuration_only"
LIVE_EXECUTION_SERVICE_REQUIRED_ENABLEMENT_ARTIFACTS = (
    "explicit_backend_live_enablement_decision",
    "configured_admin_api_live_execution_service",
    "runtime_live_service_configuration",
    "deployment_live_service_enablement_record",
)
LIVE_EXECUTION_SERVICE_ENABLEMENT_CONTRACT_REFS = (
    "application/admin_api/live_execution.py::AdminApiLiveExecutionService",
    "application/admin_api/live_execution.py::DisabledAdminApiLiveExecutionService",
    "application/admin_api/stealth_execution_preflight.py::execution_live_readiness",
)
LIVE_EXECUTION_SERVICE_ENABLEMENT_VERIFICATION_GATES = (
    "live_service_configuration_is_backend_owned",
    "browser_and_bff_do_not_hold_live_switch",
    "disabled_service_contract_replaced_by_reviewed_live_service",
    "live_coinbase_execution_requires_explicit_phase_approval",
)
LIVE_EXECUTION_SERVICE_ENABLEMENT_BLOCKERS = (
    "explicit_live_enablement_decision_missing",
    "backend_live_service_configuration_missing",
)
LIVE_EXECUTION_SERVICE_CONTRACT_EVIDENCE_REF = "live_execution_service_contract"
LIVE_SERVICE_DECISION_SOURCE = "admin_api_live_service_decision_log"
LIVE_SERVICE_DECISION_ROUTE = "/api/v1/admin/live-execution/service-decisions"
LIVE_SERVICE_DECISION_METHOD = "POST"
LIVE_SERVICE_DECISION_MODULE_ID = "admin_system_health"
LIVE_SERVICE_DECISION_SERVICE_METHOD = "record_live_service_decision"
LIVE_SERVICE_DECISION_REQUIRED_PERMISSION = AdminApiPermission.CONFIG_UPDATE
LIVE_ADAPTER_DECISION_SOURCE = "admin_api_live_adapter_decision_log"
LIVE_ADAPTER_DECISION_ROUTE = "/api/v1/admin/live-execution/adapter-decisions"
LIVE_ADAPTER_DECISION_METHOD = "POST"
LIVE_ADAPTER_DECISION_MODULE_ID = "admin_system_health"
LIVE_ADAPTER_DECISION_SERVICE_METHOD = "record_live_adapter_decision"
LIVE_ADAPTER_DECISION_REQUIRED_PERMISSION = AdminApiPermission.CONFIG_UPDATE
LIVE_ADAPTER_DECISION_NON_RESOLUTION_REASON = (
    "latest_adapter_decision_is_readback_only_and_cannot_satisfy_construction"
)
LIVE_ADAPTER_DECISION_NO_RECORD_REASON = "no_live_adapter_decision_record_available"
LIVE_ADAPTER_DECISION_NEXT_REQUIRED_CONTRACT = (
    "backend_live_adapter_construction_contract"
)
LIVE_ADAPTER_DECISION_FORBIDDEN_RESOLUTION_CLAIMS = (
    "decision_record_constructs_adapter",
    "decision_record_enables_adapter",
    "decision_record_approves_coinbase_execution",
    "decision_record_satisfies_construction_artifacts",
    "decision_record_clears_live_readiness_blocker",
)
LIVE_EXECUTION_ADAPTER_CONSTRUCTION_AUTHORITY = "backend_route_binding_only_no_execution"
LIVE_EXECUTION_ADAPTER_CONSTRUCTION_SATISFACTION_AUTHORITY = (
    "backend_live_adapter_construction_only"
)
LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS = (
    AdminApiLiveAdapterConstructionArtifact.ROUTE_BOUND_STEALTH_LIVE_EXECUTION_ADAPTER,
    AdminApiLiveAdapterConstructionArtifact.SHARED_COMMAND_SERVICE_ADAPTER,
    AdminApiLiveAdapterConstructionArtifact.ROUTE_INVENTORY_EXECUTION_BINDING,
)
LIVE_ADAPTER_CONSTRUCTION_CONTRACT_SOURCE = (
    "backend_live_adapter_construction_contract"
)
LIVE_ADAPTER_CONSTRUCTION_CONTRACT_AUTHORITY = "backend_contract_only_no_execution"
LIVE_ADAPTER_CONSTRUCTION_ARTIFACT_ACCEPTANCE_AUTHORITY = (
    "backend_artifact_acceptance_requirements_only_no_execution"
)
LIVE_ADAPTER_CONSTRUCTION_ARTIFACT_ACCEPTANCE_READBACK_SOURCE = (
    "backend_live_adapter_artifact_acceptance_readback"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_AUTHORITY = (
    "backend_acceptance_evidence_readback_only_no_construction"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CONTRACT_SOURCE = (
    "backend_live_adapter_acceptance_evidence_producer_contract"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CONTRACT_AUTHORITY = (
    "backend_acceptance_evidence_producer_contract_only_no_write"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CONTRACT_MISSING_REASON = (
    "backend_acceptance_evidence_producer_contract_missing"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_SOURCE = (
    "backend_acceptance_evidence_producer_readiness_contract"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_AUTHORITY = (
    "backend_producer_readiness_only_no_write"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_SUMMARY_SOURCE = (
    "backend_acceptance_evidence_producer_readiness_summary"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_SUMMARY_AUTHORITY = (
    "backend_derived_from_producer_readiness_items_no_write"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_MISSING_REASON = (
    "acceptance_evidence_producer_readiness_item_missing"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_ACTION_SOURCE = (
    "backend_acceptance_evidence_producer_clearance_action_contract"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_ACTION_AUTHORITY = (
    "backend_clearance_action_only_no_write"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_ACTION_MISSING_REASON = (
    "acceptance_evidence_producer_clearance_action_missing"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_DEPENDENCY_SUMMARY_SOURCE = (
    "backend_acceptance_evidence_producer_clearance_dependency_summary"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_DEPENDENCY_SUMMARY_AUTHORITY = (
    "backend_derived_from_producer_clearance_actions_no_write"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_WORK_ITEM_SOURCE = (
    "backend_acceptance_evidence_producer_clearance_work_items"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_WORK_ITEM_AUTHORITY = (
    "backend_derived_from_first_blocked_producer_clearance_action"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_WORK_QUEUE_SOURCE = (
    "backend_acceptance_evidence_producer_clearance_work_queue"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_WORK_QUEUE_AUTHORITY = (
    "backend_derived_from_producer_clearance_work_items"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_CLAIM_TRACE_SOURCE = (
    "backend_acceptance_evidence_producer_clearance_claim_traces"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_CLAIM_TRACE_AUTHORITY = (
    "backend_derived_from_producer_clearance_work_items_no_claim_resolution"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_CLAIM_SUMMARY_SOURCE = (
    "backend_acceptance_evidence_producer_clearance_claim_trace_summary"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_CLAIM_SUMMARY_AUTHORITY = (
    "backend_derived_from_producer_clearance_claim_traces"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_ROUTE_REQUIREMENT_SOURCE = (
    "backend_acceptance_evidence_producer_route_requirements"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_ROUTE_REQUIREMENT_AUTHORITY = (
    "backend_derived_from_producer_clearance_claim_traces_no_route_registration"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_ROUTE_SUMMARY_SOURCE = (
    "backend_acceptance_evidence_producer_route_requirement_summary"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_ROUTE_SUMMARY_AUTHORITY = (
    "backend_derived_from_producer_route_requirements"
)
LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_ITEMS = (
    "producer_route_contract",
    "append_only_acceptance_evidence_store",
    "validation_replay_gate",
)
LIVE_ADAPTER_CONSTRUCTION_ARTIFACT_ACCEPTANCE_MISSING_REASON = (
    "required_backend_acceptance_evidence_missing"
)
LIVE_ADAPTER_CONSTRUCTION_CONTRACT_REF = (
    "application/admin_api/live_execution.py::build_live_adapter_construction_contract"
)
LIVE_EXECUTION_ADAPTER_CONSTRUCTION_CONTRACT_REFS = (
    "application/admin_api/live_execution.py::build_live_execution_adapter_contract",
    LIVE_ADAPTER_CONSTRUCTION_CONTRACT_REF,
    "application/admin_api/command_service.py::AdminApiCommandService",
    "application/admin_api/route_inventory.py",
)
LIVE_EXECUTION_ADAPTER_CONSTRUCTION_VERIFICATION_GATES = (
    "adapter_is_route_bound",
    "adapter_calls_shared_command_service_only",
    "no_parallel_manager_or_coinbase_path_exists",
    "live_coinbase_execution_requires_explicit_phase_approval",
)
LIVE_EXECUTION_ADAPTER_CONSTRUCTION_BLOCKERS = (
    "backend_live_adapter_construction_missing",
    "route_bound_stealth_live_execution_adapter_missing",
)
LIVE_EXECUTION_ADAPTER_CONTRACT_EVIDENCE_REF = "live_execution_adapter_contract"
M53_PILOT_LIVE_ADAPTER_ROUTE = "/api/v1/orders"
M53_PILOT_LIVE_ADAPTER_METHOD = "POST"
M53_PILOT_LIVE_ADAPTER_MODULE_ID = "spot_operations"
M53_PILOT_LIVE_ADAPTER_SERVICE_METHOD = "place_manual_order"
M53_PILOT_LIVE_ADAPTER_SOURCE = "m53_backend_pilot_dry_run"
M53_PILOT_LIVE_ADAPTER_MISSING_REASON = "pilot_dry_run_only"


@contextmanager
def _append_only_store_lock(path: Path) -> Iterator[None]:
    """Serialize append-only uniqueness checks across store instances."""

    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True, slots=True)
class AdminApiLiveExecutionServiceState:
    """Backend-owned live execution service posture."""

    required: bool = True
    present: bool = False
    status: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.LIVE_DISABLED
    source: str = "not_configured"
    missing_reason: str | None = LIVE_EXECUTION_DISABLED_REASON


class LiveServiceDecisionRecord(BaseModel):
    """Append-only backend live-service enablement decision evidence."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    requested_service_status: AdminApiLiveExecutionStatus = (
        AdminApiLiveExecutionStatus.LIVE_DISABLED
    )
    service_enabled: bool = False
    source: str = LIVE_SERVICE_DECISION_SOURCE
    deployment_ref: str = Field(min_length=1)
    runtime_configuration_ref: str = Field(min_length=1)
    decision_reason: str = Field(min_length=1)
    live_coinbase_execution_approved: bool = False
    max_submitted_notional_usdc: str = "0"
    max_executed_notional_usdc: str = "0"


class LiveAdapterDecisionRecord(BaseModel):
    """Append-only backend live-adapter construction decision evidence."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    requested_adapter_status: AdminApiLiveExecutionStatus = (
        AdminApiLiveExecutionStatus.LIVE_DISABLED
    )
    target_route: str = Field(min_length=1)
    target_method: str = Field(min_length=1)
    target_module_id: str = Field(min_length=1)
    target_service_method: str = Field(min_length=1)
    adapter_reference: str = Field(min_length=1)
    adapter_constructed: bool = False
    adapter_enabled: bool = False
    source: str = LIVE_ADAPTER_DECISION_SOURCE
    construction_review_ref: str = Field(min_length=1)
    decision_reason: str = Field(min_length=1)
    live_coinbase_execution_approved: bool = False
    max_submitted_notional_usdc: str = "0"
    max_executed_notional_usdc: str = "0"


class FileAdminApiLiveServiceDecisionStore:
    """Append-only JSONL live-service decision evidence store."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_LIVE_SERVICE_DECISION_LOG_PATH")
            or Path("runtime_state") / "admin_api_live_service_decisions.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: LiveServiceDecisionRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.decision_id

    def read_recent(self, *, limit: int = 100) -> list[LiveServiceDecisionRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[LiveServiceDecisionRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(LiveServiceDecisionRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_decision_id(
        self,
        decision_id: str,
    ) -> LiveServiceDecisionRecord | None:
        """Return the latest record with the given decision id, if present."""

        for record in self.read_recent(limit=500):
            if record.decision_id == decision_id:
                return record
        return None


class FileAdminApiLiveAdapterDecisionStore:
    """Append-only JSONL live-adapter decision evidence store."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_LIVE_ADAPTER_DECISION_LOG_PATH")
            or Path("runtime_state") / "admin_api_live_adapter_decisions.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: LiveAdapterDecisionRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.decision_id

    def append_if_decision_id_absent(
        self,
        record: LiveAdapterDecisionRecord,
    ) -> bool:
        """Append only when the decision id is absent from the full log."""

        with self._lock, _append_only_store_lock(self.path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        existing = LiveAdapterDecisionRecord.model_validate_json(
                            line
                        )
                    except ValueError:
                        continue
                    if existing.decision_id == record.decision_id:
                        return False
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return True

    def read_recent(self, *, limit: int = 100) -> list[LiveAdapterDecisionRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[LiveAdapterDecisionRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(LiveAdapterDecisionRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_decision_id(
        self,
        decision_id: str,
    ) -> LiveAdapterDecisionRecord | None:
        """Return the latest record with the given decision id, if present."""

        with self._lock:
            if not self.path.exists():
                return None
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                record = LiveAdapterDecisionRecord.model_validate_json(line)
            except ValueError:
                continue
            if record.decision_id == decision_id:
                return record
        return None


class AdminApiLiveExecutionService(Protocol):
    """Protocol for service-state providers used by admission evidence."""

    def admission_state(self) -> AdminApiLiveExecutionServiceState:
        """Return backend-owned live execution service posture."""
        ...


class DisabledAdminApiLiveExecutionService:
    """Disabled service boundary for future live Admin API execution.

    The current implementation is evidence-only. Keeping this object separate
    from command routes makes the final execution boundary visible without
    adding an executable path.
    """

    def admission_state(self) -> AdminApiLiveExecutionServiceState:
        return AdminApiLiveExecutionServiceState(
            required=True,
            present=True,
            status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
            source=DISABLED_LIVE_EXECUTION_SERVICE_SOURCE,
            missing_reason=LIVE_EXECUTION_DISABLED_REASON,
        )


def get_disabled_live_execution_service() -> DisabledAdminApiLiveExecutionService:
    """Return the default backend-owned disabled live execution service."""

    return DisabledAdminApiLiveExecutionService()


def read_latest_live_service_decision(
    store: FileAdminApiLiveServiceDecisionStore | None = None,
) -> LiveServiceDecisionRecord | None:
    """Return the newest local live-service decision evidence, if present."""

    decision_store = store or FileAdminApiLiveServiceDecisionStore()
    try:
        records = decision_store.read_recent(limit=1)
    except OSError:
        return None
    return records[0] if records else None


def read_latest_live_adapter_decision(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    store: FileAdminApiLiveAdapterDecisionStore | None = None,
) -> LiveAdapterDecisionRecord | None:
    """Return newest local adapter decision evidence for one route binding."""

    decision_store = store or FileAdminApiLiveAdapterDecisionStore()
    try:
        records = decision_store.read_recent(limit=500)
    except OSError:
        return None
    for record in records:
        if (
            record.target_method == method
            and record.target_route == route
            and record.target_module_id == module_id
            and record.target_service_method == service_method
        ):
            return record
    return None


def build_live_execution_service_blocker_trace() -> dict[str, Any]:
    """Return blocker-chain trace evidence for live-service enablement."""

    return {
        "blocker_authority": LIVE_EXECUTION_SERVICE_ENABLEMENT_AUTHORITY,
        "blocker_contract_refs": list(LIVE_EXECUTION_SERVICE_ENABLEMENT_CONTRACT_REFS),
        "blocker_evidence_refs": [LIVE_EXECUTION_SERVICE_CONTRACT_EVIDENCE_REF],
        "required_resolution_artifacts": list(
            LIVE_EXECUTION_SERVICE_REQUIRED_ENABLEMENT_ARTIFACTS
        ),
        "missing_resolution_artifacts": list(
            LIVE_EXECUTION_SERVICE_REQUIRED_ENABLEMENT_ARTIFACTS
        ),
        "verification_gates": list(
            LIVE_EXECUTION_SERVICE_ENABLEMENT_VERIFICATION_GATES
        ),
        "blocking_contract_blockers": list(LIVE_EXECUTION_SERVICE_ENABLEMENT_BLOCKERS),
    }


def build_live_execution_adapter_blocker_trace() -> dict[str, Any]:
    """Return blocker-chain trace evidence for live-adapter construction."""

    return {
        "blocker_authority": LIVE_EXECUTION_ADAPTER_CONSTRUCTION_AUTHORITY,
        "blocker_contract_refs": list(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_CONTRACT_REFS
        ),
        "blocker_evidence_refs": [LIVE_EXECUTION_ADAPTER_CONTRACT_EVIDENCE_REF],
        "required_resolution_artifacts": list(
            LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS
        ),
        "missing_resolution_artifacts": list(
            LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS
        ),
        "verification_gates": list(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_VERIFICATION_GATES
        ),
        "blocking_contract_blockers": list(LIVE_EXECUTION_ADAPTER_CONSTRUCTION_BLOCKERS),
    }


def build_live_execution_adapter_construction_satisfaction() -> dict[str, Any]:
    """Return fail-closed satisfaction evidence for adapter construction."""

    return {
        "route_mapping_satisfies_construction": False,
        "adapter_configuration_satisfies_construction": False,
        "construction_satisfaction_authority": (
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_SATISFACTION_AUTHORITY
        ),
        "satisfied_construction_artifacts": [],
        "unsatisfied_construction_artifacts": list(
            LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS
        ),
    }


def build_live_adapter_construction_contract(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    action_class: AdminApiActionClass,
) -> dict[str, Any]:
    """Return typed no-live evidence for the required adapter construction contract."""

    adapter_reference = f"AdminApiCommandService.{service_method}"
    command_service_ref = (
        f"application/admin_api/command_service.py::"
        f"AdminApiCommandService.{service_method}"
    )
    route_inventory_ref = f"application/admin_api/route_inventory.py::{module_id}"
    artifact_details = {
        AdminApiLiveAdapterConstructionArtifact.ROUTE_BOUND_STEALTH_LIVE_EXECUTION_ADAPTER: (
            "A reviewed backend adapter object must bind exactly one route, "
            "method, module, service method, action class, and command identity."
        ),
        AdminApiLiveAdapterConstructionArtifact.SHARED_COMMAND_SERVICE_ADAPTER: (
            "Adapter construction must call the shared AdminApiCommandService "
            "method only; it must not call managers, Coinbase, or route-local "
            "execution code directly."
        ),
        AdminApiLiveAdapterConstructionArtifact.ROUTE_INVENTORY_EXECUTION_BINDING: (
            "The route inventory must identify the same live-shaped command "
            "route, module id, permission, action class, and shared method."
        ),
    }
    artifact_acceptance = {
        AdminApiLiveAdapterConstructionArtifact.ROUTE_BOUND_STEALTH_LIVE_EXECUTION_ADAPTER: {
            "required_evidence_id": "route_bound_stealth_live_execution_adapter_evidence",
            "evidence_owner": "admin_api_contract",
            "required_source_refs": [
                LIVE_ADAPTER_CONSTRUCTION_CONTRACT_REF,
                route_inventory_ref,
                command_service_ref,
            ],
            "acceptance_checks": [
                f"method_matches:{method}",
                f"route_matches:{route}",
                f"module_id_matches:{module_id}",
                f"service_method_matches:{service_method}",
                f"action_class_matches:{action_class.value}",
            ],
            "negative_checks": [
                "adapter_does_not_call_coinbase_client_directly",
                "adapter_does_not_call_stealth_manager_directly",
                "adapter_does_not_execute_reconciliation",
                "adapter_does_not_mutate_lifecycle_or_exchange_state",
            ],
        },
        AdminApiLiveAdapterConstructionArtifact.SHARED_COMMAND_SERVICE_ADAPTER: {
            "required_evidence_id": "shared_command_service_adapter_evidence",
            "evidence_owner": "admin_api_contract",
            "required_source_refs": [
                command_service_ref,
                "application/admin_api/command_service.py::AdminApiCommandService",
            ],
            "acceptance_checks": [
                f"adapter_reference_matches:{adapter_reference}",
                f"shared_service_method_exists:{service_method}",
                "command_identity_comes_from_backend_route_context",
            ],
            "negative_checks": [
                "no_route_local_executor",
                "no_dashboard_websocket_shortcut",
                "no_browser_supplied_execution_authority",
            ],
        },
        AdminApiLiveAdapterConstructionArtifact.ROUTE_INVENTORY_EXECUTION_BINDING: {
            "required_evidence_id": "route_inventory_execution_binding_evidence",
            "evidence_owner": "admin_api_contract",
            "required_source_refs": [
                route_inventory_ref,
                "application/admin_api/route_inventory.py",
            ],
            "acceptance_checks": [
                f"inventory_method_matches:{method}",
                f"inventory_route_matches:{route}",
                f"inventory_module_matches:{module_id}",
                f"inventory_service_method_matches:{service_method}",
                f"inventory_action_class_matches:{action_class.value}",
            ],
            "negative_checks": [
                "no_unregistered_command_route",
                "no_missing_required_permission",
                "no_secondary_execution_path",
            ],
        },
    }
    artifacts = [
        {
            "artifact": artifact,
            "status": AdminApiGateStatus.BLOCKED,
            "required": True,
            "satisfied": False,
            "source_ref": LIVE_ADAPTER_CONSTRUCTION_CONTRACT_SOURCE,
            "expected_evidence_ref": LIVE_ADAPTER_CONSTRUCTION_CONTRACT_REF,
            "missing_reason": f"{artifact.value}_missing",
            "verification_gate": (
                LIVE_EXECUTION_ADAPTER_CONSTRUCTION_VERIFICATION_GATES[index]
            ),
            "acceptance_authority": (
                LIVE_ADAPTER_CONSTRUCTION_ARTIFACT_ACCEPTANCE_AUTHORITY
            ),
            "current_evidence_present": False,
            "evidence_ids": [],
            "evidence_source_refs": [],
            "satisfies_artifact": False,
            "acceptance_evidence_status": AdminApiGateStatus.BLOCKED,
            "acceptance_evidence_count": 1,
            "missing_acceptance_evidence_count": 1,
            "accepted_acceptance_evidence_count": 0,
            "acceptance_evidence": [
                {
                    "artifact": artifact,
                    "status": AdminApiGateStatus.BLOCKED,
                    "evidence_id": artifact_acceptance[artifact][
                        "required_evidence_id"
                    ],
                    "source": (
                        LIVE_ADAPTER_CONSTRUCTION_ARTIFACT_ACCEPTANCE_READBACK_SOURCE
                    ),
                    "evidence_present": False,
                    "evidence_owner": artifact_acceptance[artifact][
                        "evidence_owner"
                    ],
                    "expected_source_refs": artifact_acceptance[artifact][
                        "required_source_refs"
                    ],
                    "observed_source_refs": [],
                    "accepted": False,
                    "satisfies_artifact": False,
                    "missing_reason": (
                        LIVE_ADAPTER_CONSTRUCTION_ARTIFACT_ACCEPTANCE_MISSING_REASON
                    ),
                    "blocker": f"{artifact.value}_acceptance_evidence_missing",
                    "browser_authority": "display_only",
                    "bff_authority": "forward_only_no_execution",
                    "detail": (
                        "Required backend acceptance evidence has not been "
                        "recorded; this readback cannot construct or satisfy "
                        "a live adapter."
                    ),
                }
            ],
            "satisfaction_blockers": [
                f"{artifact.value}_evidence_missing",
                f"{artifact.value}_acceptance_not_run",
                f"{artifact.value}_acceptance_evidence_missing",
            ],
            **artifact_acceptance[artifact],
            "detail": artifact_details[artifact],
        }
        for index, artifact in enumerate(
            LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS
        )
    ]
    acceptance_evidence_rows = [
        evidence
        for artifact_item in artifacts
        for evidence in artifact_item["acceptance_evidence"]
    ]
    missing_acceptance_evidence = [
        evidence
        for evidence in acceptance_evidence_rows
        if not evidence["evidence_present"]
    ]
    accepted_acceptance_evidence = [
        evidence for evidence in acceptance_evidence_rows if evidence["accepted"]
    ]
    acceptance_evidence_blockers = [
        evidence["blocker"] for evidence in missing_acceptance_evidence
    ]
    next_required_acceptance_evidence_ids = [
        evidence["evidence_id"] for evidence in missing_acceptance_evidence
    ]
    producer_readiness_templates = (
        {
            "category": "producer_route_contract",
            "required_ref": (
                "application/admin_api/live_execution.py::"
                "acceptance_evidence_producer_route_contract"
            ),
            "required_route": None,
            "required_method": "POST",
            "verification_gate": (
                "producer_route_is_backend_owned_and_route_inventory_bound"
            ),
        },
        {
            "category": "append_only_acceptance_evidence_store",
            "required_ref": (
                "application/admin_api/live_execution.py::"
                "acceptance_evidence_append_only_store"
            ),
            "required_route": None,
            "required_method": None,
            "verification_gate": (
                "acceptance_evidence_store_is_append_only_and_replay_safe"
            ),
        },
        {
            "category": "validation_replay_gate",
            "required_ref": (
                "application/admin_api/live_execution.py::"
                "acceptance_evidence_validation_replay_gate"
            ),
            "required_route": None,
            "required_method": None,
            "verification_gate": (
                "acceptance_evidence_payload_validation_and_replay_are_configured"
            ),
        },
    )
    acceptance_evidence_producer_contracts = [
        {
            "evidence_id": evidence["evidence_id"],
            "artifact": evidence["artifact"],
            "status": AdminApiGateStatus.BLOCKED,
            "required": True,
            "configured": False,
            "backend_owned": True,
            "route_bound": True,
            "source": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CONTRACT_SOURCE
            ),
            "authority": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CONTRACT_AUTHORITY
            ),
            "producer_contract_id": f"{evidence['evidence_id']}_producer_contract",
            "producer_route": None,
            "producer_route_available": False,
            "recording_method": "not_configured",
            "required_owner": evidence["evidence_owner"],
            "required_source_refs": evidence["expected_source_refs"],
            "required_checks": artifact_acceptance[evidence["artifact"]][
                "acceptance_checks"
            ],
            "missing_reason": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CONTRACT_MISSING_REASON
            ),
            "blocker": (
                f"{evidence['artifact'].value}_acceptance_evidence_producer_contract_missing"
            ),
            "writer_configured": False,
            "writes_acceptance_evidence": False,
            "accepts_evidence": False,
            "satisfies_construction": False,
            "readiness_status": AdminApiGateStatus.BLOCKED,
            "readiness_source": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_SOURCE
            ),
            "readiness_authority": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_AUTHORITY
            ),
            "readiness_item_count": len(producer_readiness_templates),
            "missing_readiness_item_count": len(producer_readiness_templates),
            "satisfied_readiness_item_count": 0,
            "readiness_blockers": [
                f"{evidence['artifact'].value}_{template['category']}_missing"
                for template in producer_readiness_templates
            ],
            "readiness_items": [
                {
                    "readiness_item_id": (
                        f"{evidence['evidence_id']}_{template['category']}"
                    ),
                    "category": template["category"],
                    "status": AdminApiGateStatus.BLOCKED,
                    "required": True,
                    "satisfied": False,
                    "source": (
                        LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_SOURCE
                    ),
                    "authority": (
                        LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_AUTHORITY
                    ),
                    "required_ref": template["required_ref"],
                    "required_route": template["required_route"],
                    "required_method": template["required_method"],
                    "verification_gate": template["verification_gate"],
                    "missing_reason": (
                        LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_MISSING_REASON
                    ),
                    "blocker": (
                        f"{evidence['artifact'].value}_{template['category']}_missing"
                    ),
                    "route_available": False,
                    "store_available": False,
                    "validation_configured": False,
                    "replay_protection_configured": False,
                    "writer_allowed": False,
                    "writes_acceptance_evidence": False,
                    "accepts_evidence": False,
                    "satisfies_producer_contract": False,
                    "browser_authority": "display_only",
                    "bff_authority": "forward_only_no_execution",
                    "detail": (
                        "This readiness item identifies a required backend "
                        "contract for future acceptance-evidence production; "
                        "it is not configured and grants no write authority."
                    ),
                }
                for template in producer_readiness_templates
            ],
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": (
                "No backend-owned producer route or recording method exists "
                "for this acceptance evidence id; the construction contract "
                "remains read-only and cannot accept or write evidence."
            ),
        }
        for evidence in missing_acceptance_evidence
    ]
    missing_acceptance_evidence_producer_contracts = [
        contract
        for contract in acceptance_evidence_producer_contracts
        if not contract["configured"]
    ]
    configured_acceptance_evidence_producer_contracts = [
        contract
        for contract in acceptance_evidence_producer_contracts
        if contract["configured"]
    ]
    acceptance_evidence_producer_contract_blockers = [
        contract["blocker"]
        for contract in missing_acceptance_evidence_producer_contracts
    ]
    producer_readiness_items = [
        item
        for contract in acceptance_evidence_producer_contracts
        for item in contract["readiness_items"]
    ]
    missing_producer_readiness_items = [
        item for item in producer_readiness_items if not item["satisfied"]
    ]
    satisfied_producer_readiness_items = [
        item for item in producer_readiness_items if item["satisfied"]
    ]
    producer_readiness_blockers = [
        item["blocker"] for item in missing_producer_readiness_items
    ]
    producer_readiness_summary = {
        "status": AdminApiGateStatus.BLOCKED,
        "source": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_SUMMARY_SOURCE
        ),
        "authority": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_SUMMARY_AUTHORITY
        ),
        "producer_contract_count": len(acceptance_evidence_producer_contracts),
        "readiness_item_count": len(producer_readiness_items),
        "missing_readiness_item_count": len(missing_producer_readiness_items),
        "satisfied_readiness_item_count": len(satisfied_producer_readiness_items),
        "required_categories": list(
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_ITEMS
        ),
        "missing_categories": list(
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_READINESS_ITEMS
        ),
        "satisfied_categories": [],
        "producer_contract_ids": [
            contract["producer_contract_id"]
            for contract in acceptance_evidence_producer_contracts
        ],
        "next_required_readiness_item_ids": [
            item["readiness_item_id"] for item in missing_producer_readiness_items
        ],
        "blockers": producer_readiness_blockers,
        "first_blocker": (
            producer_readiness_blockers[0] if producer_readiness_blockers else None
        ),
        "all_producer_contracts_ready": False,
        "producer_route_available": False,
        "store_available": False,
        "validation_configured": False,
        "replay_protection_configured": False,
        "writer_allowed": False,
        "writes_acceptance_evidence": False,
        "accepts_evidence": False,
        "satisfies_producer_contracts": False,
        "satisfies_construction": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            "Producer readiness is derived from missing route, store, and "
            "validation/replay rows. It is a summary only and grants no "
            "acceptance-evidence write authority."
        ),
    }
    missing_producer_readiness_entries = [
        (contract, item)
        for contract in acceptance_evidence_producer_contracts
        for item in contract["readiness_items"]
        if not item["satisfied"]
    ]
    producer_readiness_clearance_actions = [
        {
            "clearance_action_id": (
                f"{item['readiness_item_id']}_clearance_action"
            ),
            "clearance_sequence": sequence,
            "readiness_item_id": item["readiness_item_id"],
            "producer_contract_id": contract["producer_contract_id"],
            "evidence_id": contract["evidence_id"],
            "artifact": contract["artifact"],
            "category": item["category"],
            "status": AdminApiGateStatus.BLOCKED,
            "required": True,
            "ready": False,
            "source": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_ACTION_SOURCE
            ),
            "authority": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_ACTION_AUTHORITY
            ),
            "required_ref": item["required_ref"],
            "required_route": item["required_route"],
            "required_method": item["required_method"],
            "verification_gate": item["verification_gate"],
            "missing_reason": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_ACTION_MISSING_REASON
            ),
            "readiness_blocker": item["blocker"],
            "blocker": f"{item['blocker']}_clearance_action_missing",
            "route_available": False,
            "store_available": False,
            "validation_configured": False,
            "replay_protection_configured": False,
            "writer_allowed": False,
            "writes_acceptance_evidence": False,
            "accepts_evidence": False,
            "satisfies_producer_contract": False,
            "satisfies_construction": False,
            "clearance_allowed": False,
            "clearance_executed": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": (
                "This clearance action names the backend work required to "
                "resolve one producer-readiness item. It is planning evidence "
                "only and cannot configure routes, stores, writers, replay "
                "gates, or live adapter construction."
            ),
        }
        for sequence, (contract, item) in enumerate(
            missing_producer_readiness_entries, start=1
        )
    ]
    blocked_producer_readiness_clearance_actions = [
        action
        for action in producer_readiness_clearance_actions
        if not action["ready"]
    ]
    ready_producer_readiness_clearance_actions = [
        action
        for action in producer_readiness_clearance_actions
        if action["ready"]
    ]
    producer_readiness_clearance_dependency_blocked_refs = [
        action["clearance_action_id"]
        for action in producer_readiness_clearance_actions
        if not action["ready"]
    ]
    producer_readiness_clearable_action_refs = [
        action["clearance_action_id"]
        for action in producer_readiness_clearance_actions
        if action["ready"]
        and action["clearance_allowed"]
        and action["clearance_executed"]
    ]
    producer_readiness_terminal_action_refs = [
        action["clearance_action_id"]
        for action in producer_readiness_clearance_actions
        if action["category"] == "validation_replay_gate"
    ]
    producer_readiness_clearance_dependency_summary = {
        "source_ref": "acceptance_evidence_producer_clearance_actions",
        "status": AdminApiGateStatus.BLOCKED,
        "source": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_DEPENDENCY_SUMMARY_SOURCE
        ),
        "authority": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_DEPENDENCY_SUMMARY_AUTHORITY
        ),
        "total_action_count": len(producer_readiness_clearance_actions),
        "blocked_action_count": len(
            blocked_producer_readiness_clearance_actions
        ),
        "ready_action_count": len(ready_producer_readiness_clearance_actions),
        "dependency_ready_count": 0,
        "dependency_blocked_count": len(
            producer_readiness_clearance_dependency_blocked_refs
        ),
        "predecessor_edge_count": 0,
        "successor_edge_count": 0,
        "dependency_blocked_refs": (
            producer_readiness_clearance_dependency_blocked_refs
        ),
        "clearable_action_refs": producer_readiness_clearable_action_refs,
        "terminal_action_refs": producer_readiness_terminal_action_refs,
        "first_clearance_action_id": (
            producer_readiness_clearance_actions[0]["clearance_action_id"]
            if producer_readiness_clearance_actions
            else None
        ),
        "first_dependency_blocked_ref": (
            producer_readiness_clearance_dependency_blocked_refs[0]
            if producer_readiness_clearance_dependency_blocked_refs
            else None
        ),
        "dependency_graph_ready": False,
        "clearance_allowed": False,
        "clearance_executed": False,
        "route_available": False,
        "store_available": False,
        "validation_configured": False,
        "replay_protection_configured": False,
        "writer_allowed": False,
        "writes_acceptance_evidence": False,
        "accepts_evidence": False,
        "satisfies_producer_contracts": False,
        "satisfies_construction": False,
        "execution_allowed": False,
        "executed": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            "Producer-readiness clearance dependency summary is "
            "backend-derived planning evidence over blocked clearance "
            "actions. It proves no producer clearance action is clearable and "
            "does not configure routes, stores, validation/replay gates, "
            "writers, acceptance paths, adapter construction, or live "
            "execution."
        ),
    }
    first_blocked_action_by_producer_contract: dict[str, dict[str, Any]] = {}
    for action in blocked_producer_readiness_clearance_actions:
        first_blocked_action_by_producer_contract.setdefault(
            action["producer_contract_id"], action
        )
    producer_readiness_clearance_work_items = [
        {
            "source_ref": "acceptance_evidence_producer_clearance_actions",
            "status": AdminApiGateStatus.BLOCKED,
            "source": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_WORK_ITEM_SOURCE
            ),
            "work_item_index": index,
            "producer_contract_id": action["producer_contract_id"],
            "evidence_id": action["evidence_id"],
            "artifact": action["artifact"],
            "category": action["category"],
            "clearance_action_id": action["clearance_action_id"],
            "readiness_item_id": action["readiness_item_id"],
            "clearance_sequence": action["clearance_sequence"],
            "required_ref": action["required_ref"],
            "required_route": action["required_route"],
            "required_method": action["required_method"],
            "verification_gate": action["verification_gate"],
            "readiness_blocker": action["readiness_blocker"],
            "blocker": action["blocker"],
            "missing_reason": action["missing_reason"],
            "work_item_authority": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_WORK_ITEM_AUTHORITY
            ),
            "route_available": False,
            "store_available": False,
            "validation_configured": False,
            "replay_protection_configured": False,
            "writer_allowed": False,
            "writes_acceptance_evidence": False,
            "accepts_evidence": False,
            "satisfies_producer_contract": False,
            "satisfies_construction": False,
            "dependency_ready": False,
            "clearance_ready": False,
            "clearance_allowed": False,
            "clearance_executed": False,
            "blocks_m55_completion": True,
            "blocks_live_execution": True,
            "execution_allowed": False,
            "executed": False,
            "no_live_execution": True,
            "backend_owned": True,
            "route_bound": True,
            "command_context_bound": True,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": (
                "This work item points to the first blocked producer-clearance "
                "action for one missing acceptance-evidence producer contract. "
                "It is planning evidence only and cannot configure producers, "
                "write evidence, construct adapters, or enable live execution."
            ),
        }
        for index, action in enumerate(
            first_blocked_action_by_producer_contract.values(), start=1
        )
    ]
    blocked_producer_readiness_clearance_work_items = [
        item
        for item in producer_readiness_clearance_work_items
        if not item["clearance_ready"]
    ]
    ready_producer_readiness_clearance_work_items = [
        item
        for item in producer_readiness_clearance_work_items
        if item["clearance_ready"]
    ]
    producer_readiness_clearance_work_queue_summary = {
        "source_ref": "acceptance_evidence_producer_clearance_work_items",
        "status": AdminApiGateStatus.BLOCKED,
        "source": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_WORK_QUEUE_SOURCE
        ),
        "total_work_item_count": len(producer_readiness_clearance_work_items),
        "blocked_work_item_count": len(
            blocked_producer_readiness_clearance_work_items
        ),
        "ready_work_item_count": len(
            ready_producer_readiness_clearance_work_items
        ),
        "producer_contract_count": len(
            first_blocked_action_by_producer_contract
        ),
        "work_item_refs": [
            item["clearance_action_id"]
            for item in producer_readiness_clearance_work_items
        ],
        "producer_contract_ids": [
            item["producer_contract_id"]
            for item in producer_readiness_clearance_work_items
        ],
        "evidence_ids": [
            item["evidence_id"] for item in producer_readiness_clearance_work_items
        ],
        "artifacts": [
            item["artifact"] for item in producer_readiness_clearance_work_items
        ],
        "categories": [
            item["category"] for item in producer_readiness_clearance_work_items
        ],
        "required_refs": list(
            dict.fromkeys(
                item["required_ref"]
                for item in producer_readiness_clearance_work_items
            )
        ),
        "verification_gates": list(
            dict.fromkeys(
                item["verification_gate"]
                for item in producer_readiness_clearance_work_items
            )
        ),
        "first_work_item_ref": (
            producer_readiness_clearance_work_items[0]["clearance_action_id"]
            if producer_readiness_clearance_work_items
            else None
        ),
        "first_producer_contract_id": (
            producer_readiness_clearance_work_items[0]["producer_contract_id"]
            if producer_readiness_clearance_work_items
            else None
        ),
        "first_artifact": (
            producer_readiness_clearance_work_items[0]["artifact"]
            if producer_readiness_clearance_work_items
            else None
        ),
        "work_queue_authority": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_WORK_QUEUE_AUTHORITY
        ),
        "work_queue_ready": False,
        "producer_clearance_ready": False,
        "m55_completion_claim_allowed": False,
        "live_execution_allowed": False,
        "executable": False,
        "route_available": False,
        "store_available": False,
        "validation_configured": False,
        "replay_protection_configured": False,
        "writer_allowed": False,
        "writes_acceptance_evidence": False,
        "accepts_evidence": False,
        "satisfies_producer_contracts": False,
        "satisfies_construction": False,
        "execution_allowed": False,
        "executed": False,
        "no_live_execution": True,
        "backend_owned": True,
        "route_bound": True,
        "command_context_bound": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            "Producer-clearance work queue summary is backend-derived planning "
            "evidence over the first blocked clearance action for each missing "
            "acceptance-evidence producer contract. It cannot configure routes, "
            "stores, validation/replay gates, writers, acceptance paths, "
            "adapter construction, or live execution."
        ),
    }
    producer_readiness_clearance_claim_traces = [
        {
            "source_ref": "acceptance_evidence_producer_clearance_work_items",
            "status": AdminApiGateStatus.BLOCKED,
            "source": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_CLAIM_TRACE_SOURCE
            ),
            "claim_trace_index": index,
            "claim_id": (
                f"{item['producer_contract_id']}_producer_route_contract_claim"
            ),
            "claim": "producer_route_contract_available",
            "producer_contract_id": item["producer_contract_id"],
            "evidence_id": item["evidence_id"],
            "artifact": item["artifact"],
            "category": item["category"],
            "work_item_ref": item["clearance_action_id"],
            "readiness_item_id": item["readiness_item_id"],
            "required_ref": item["required_ref"],
            "required_route": item["required_route"],
            "required_method": item["required_method"],
            "verification_gate": item["verification_gate"],
            "blocker": item["blocker"],
            "claim_trace_authority": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_CLAIM_TRACE_AUTHORITY
            ),
            "claim_allowed": False,
            "claim_resolved": False,
            "clears_work_item": False,
            "route_available": False,
            "store_available": False,
            "validation_configured": False,
            "replay_protection_configured": False,
            "writer_allowed": False,
            "writes_acceptance_evidence": False,
            "accepts_evidence": False,
            "satisfies_producer_contract": False,
            "satisfies_construction": False,
            "construction_allowed": False,
            "adapter_constructed": False,
            "live_execution_allowed": False,
            "execution_allowed": False,
            "executed": False,
            "no_live_execution": True,
            "backend_owned": True,
            "route_bound": True,
            "command_context_bound": True,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": (
                "This claim trace maps the forbidden producer-route contract "
                "availability claim to the blocked producer-clearance work "
                "item that would need backend-owned implementation first. It "
                "cannot resolve the claim, clear the work item, construct an "
                "adapter, or enable live execution."
            ),
        }
        for index, item in enumerate(
            producer_readiness_clearance_work_items, start=1
        )
    ]
    blocked_producer_readiness_clearance_claim_traces = [
        trace
        for trace in producer_readiness_clearance_claim_traces
        if not trace["claim_resolved"]
    ]
    ready_producer_readiness_clearance_claim_traces = [
        trace
        for trace in producer_readiness_clearance_claim_traces
        if trace["claim_resolved"]
    ]
    producer_readiness_clearance_claim_trace_summary = {
        "source_ref": "acceptance_evidence_producer_clearance_claim_traces",
        "status": AdminApiGateStatus.BLOCKED,
        "source": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_CLAIM_SUMMARY_SOURCE
        ),
        "authority": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_CLAIM_SUMMARY_AUTHORITY
        ),
        "total_claim_trace_count": len(
            producer_readiness_clearance_claim_traces
        ),
        "blocked_claim_trace_count": len(
            blocked_producer_readiness_clearance_claim_traces
        ),
        "resolved_claim_trace_count": len(
            ready_producer_readiness_clearance_claim_traces
        ),
        "claim_ids": [
            trace["claim_id"]
            for trace in producer_readiness_clearance_claim_traces
        ],
        "claims": list(
            dict.fromkeys(
                trace["claim"]
                for trace in producer_readiness_clearance_claim_traces
            )
        ),
        "work_item_refs": [
            trace["work_item_ref"]
            for trace in producer_readiness_clearance_claim_traces
        ],
        "producer_contract_ids": [
            trace["producer_contract_id"]
            for trace in producer_readiness_clearance_claim_traces
        ],
        "evidence_ids": [
            trace["evidence_id"]
            for trace in producer_readiness_clearance_claim_traces
        ],
        "artifacts": [
            trace["artifact"]
            for trace in producer_readiness_clearance_claim_traces
        ],
        "required_refs": list(
            dict.fromkeys(
                trace["required_ref"]
                for trace in producer_readiness_clearance_claim_traces
            )
        ),
        "verification_gates": list(
            dict.fromkeys(
                trace["verification_gate"]
                for trace in producer_readiness_clearance_claim_traces
            )
        ),
        "first_claim_id": (
            producer_readiness_clearance_claim_traces[0]["claim_id"]
            if producer_readiness_clearance_claim_traces
            else None
        ),
        "first_work_item_ref": (
            producer_readiness_clearance_claim_traces[0]["work_item_ref"]
            if producer_readiness_clearance_claim_traces
            else None
        ),
        "claim_trace_ready": False,
        "all_claims_resolved": False,
        "work_queue_ready": False,
        "producer_clearance_ready": False,
        "m55_completion_claim_allowed": False,
        "construction_allowed": False,
        "adapter_constructed": False,
        "live_execution_allowed": False,
        "executable": False,
        "route_available": False,
        "store_available": False,
        "validation_configured": False,
        "replay_protection_configured": False,
        "writer_allowed": False,
        "writes_acceptance_evidence": False,
        "accepts_evidence": False,
        "satisfies_producer_contracts": False,
        "satisfies_construction": False,
        "execution_allowed": False,
        "executed": False,
        "no_live_execution": True,
        "backend_owned": True,
        "route_bound": True,
        "command_context_bound": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            "Producer-clearance claim trace summary is backend-derived "
            "evidence over blocked work items. It proves producer-route "
            "contract availability claims remain unresolved and cannot clear "
            "work items, construct adapters, or enable live execution."
        ),
    }
    producer_route_requirements = [
        {
            "source_ref": "acceptance_evidence_producer_clearance_claim_traces",
            "status": AdminApiGateStatus.BLOCKED,
            "source": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_ROUTE_REQUIREMENT_SOURCE
            ),
            "route_requirement_index": index,
            "route_requirement_id": (
                f"{trace['producer_contract_id']}_producer_route_requirement"
            ),
            "claim_id": trace["claim_id"],
            "claim": trace["claim"],
            "producer_contract_id": trace["producer_contract_id"],
            "evidence_id": trace["evidence_id"],
            "artifact": trace["artifact"],
            "category": trace["category"],
            "work_item_ref": trace["work_item_ref"],
            "readiness_item_id": trace["readiness_item_id"],
            "required_ref": trace["required_ref"],
            "required_route": trace["required_route"],
            "required_method": trace["required_method"],
            "verification_gate": trace["verification_gate"],
            "blocker": trace["blocker"],
            "route_contract_ref": trace["required_ref"],
            "route_requirement_authority": (
                LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_ROUTE_REQUIREMENT_AUTHORITY
            ),
            "route_contract_available": False,
            "route_registered": False,
            "route_inventory_bound": False,
            "shared_command_service_bound": False,
            "producer_route_available": False,
            "claim_allowed": False,
            "claim_resolved": False,
            "clears_claim_trace": False,
            "clears_work_item": False,
            "store_available": False,
            "validation_configured": False,
            "replay_protection_configured": False,
            "writer_allowed": False,
            "writes_acceptance_evidence": False,
            "accepts_evidence": False,
            "satisfies_producer_contract": False,
            "satisfies_construction": False,
            "construction_allowed": False,
            "adapter_constructed": False,
            "live_execution_allowed": False,
            "execution_allowed": False,
            "executed": False,
            "no_live_execution": True,
            "backend_owned": True,
            "route_bound": True,
            "command_context_bound": True,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": (
                "This route requirement is backend-derived evidence for the "
                "producer route contract that would be needed before the "
                "producer-route availability claim could ever resolve. It "
                "does not register a route, bind route inventory, write "
                "acceptance evidence, construct an adapter, or enable live "
                "execution."
            ),
        }
        for index, trace in enumerate(
            producer_readiness_clearance_claim_traces, start=1
        )
    ]
    blocked_producer_route_requirements = [
        route_requirement
        for route_requirement in producer_route_requirements
        if not route_requirement["route_contract_available"]
    ]
    ready_producer_route_requirements = [
        route_requirement
        for route_requirement in producer_route_requirements
        if route_requirement["route_contract_available"]
    ]
    producer_route_requirement_summary = {
        "source_ref": "acceptance_evidence_producer_route_requirements",
        "status": AdminApiGateStatus.BLOCKED,
        "source": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_ROUTE_SUMMARY_SOURCE
        ),
        "authority": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_ROUTE_SUMMARY_AUTHORITY
        ),
        "total_route_requirement_count": len(producer_route_requirements),
        "blocked_route_requirement_count": len(
            blocked_producer_route_requirements
        ),
        "ready_route_requirement_count": len(ready_producer_route_requirements),
        "route_requirement_ids": [
            route_requirement["route_requirement_id"]
            for route_requirement in producer_route_requirements
        ],
        "claim_ids": [
            route_requirement["claim_id"]
            for route_requirement in producer_route_requirements
        ],
        "work_item_refs": [
            route_requirement["work_item_ref"]
            for route_requirement in producer_route_requirements
        ],
        "producer_contract_ids": [
            route_requirement["producer_contract_id"]
            for route_requirement in producer_route_requirements
        ],
        "evidence_ids": [
            route_requirement["evidence_id"]
            for route_requirement in producer_route_requirements
        ],
        "artifacts": [
            route_requirement["artifact"]
            for route_requirement in producer_route_requirements
        ],
        "route_contract_refs": list(
            dict.fromkeys(
                route_requirement["route_contract_ref"]
                for route_requirement in producer_route_requirements
            )
        ),
        "required_refs": list(
            dict.fromkeys(
                route_requirement["required_ref"]
                for route_requirement in producer_route_requirements
            )
        ),
        "verification_gates": list(
            dict.fromkeys(
                route_requirement["verification_gate"]
                for route_requirement in producer_route_requirements
            )
        ),
        "first_route_requirement_id": (
            producer_route_requirements[0]["route_requirement_id"]
            if producer_route_requirements
            else None
        ),
        "first_claim_id": (
            producer_route_requirements[0]["claim_id"]
            if producer_route_requirements
            else None
        ),
        "route_requirement_ready": False,
        "all_route_contracts_available": False,
        "all_routes_registered": False,
        "route_inventory_bound": False,
        "shared_command_service_bound": False,
        "producer_route_available": False,
        "claim_trace_ready": False,
        "all_claims_resolved": False,
        "work_queue_ready": False,
        "producer_clearance_ready": False,
        "m55_completion_claim_allowed": False,
        "construction_allowed": False,
        "adapter_constructed": False,
        "live_execution_allowed": False,
        "executable": False,
        "store_available": False,
        "validation_configured": False,
        "replay_protection_configured": False,
        "writer_allowed": False,
        "writes_acceptance_evidence": False,
        "accepts_evidence": False,
        "satisfies_producer_contracts": False,
        "satisfies_construction": False,
        "execution_allowed": False,
        "executed": False,
        "no_live_execution": True,
        "backend_owned": True,
        "route_bound": True,
        "command_context_bound": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            "Producer-route requirement summary is backend-derived evidence "
            "over route requirements that remain unavailable. It cannot "
            "register routes, bind route inventory, satisfy producer "
            "contracts, construct adapters, or enable live execution."
        ),
    }
    return {
        "contract_id": LIVE_ADAPTER_DECISION_NEXT_REQUIRED_CONTRACT,
        "status": AdminApiGateStatus.BLOCKED,
        "required": True,
        "configured": False,
        "backend_owned": True,
        "route_bound": True,
        "source": LIVE_ADAPTER_CONSTRUCTION_CONTRACT_SOURCE,
        "authority": LIVE_ADAPTER_CONSTRUCTION_CONTRACT_AUTHORITY,
        "module_id": module_id,
        "route": route,
        "method": method,
        "service_method": service_method,
        "adapter_reference": adapter_reference,
        "action_class": action_class,
        "artifact_count": len(artifacts),
        "required_artifact_count": len(artifacts),
        "satisfied_artifact_count": 0,
        "missing_artifact_count": len(artifacts),
        "acceptance_evidence_status": AdminApiGateStatus.BLOCKED,
        "acceptance_evidence_source": (
            LIVE_ADAPTER_CONSTRUCTION_ARTIFACT_ACCEPTANCE_READBACK_SOURCE
        ),
        "acceptance_evidence_authority": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_AUTHORITY
        ),
        "acceptance_evidence_count": len(acceptance_evidence_rows),
        "missing_acceptance_evidence_count": len(missing_acceptance_evidence),
        "accepted_acceptance_evidence_count": len(accepted_acceptance_evidence),
        "acceptance_evidence_satisfies_construction": False,
        "acceptance_evidence_blockers": acceptance_evidence_blockers,
        "next_required_acceptance_evidence_ids": (
            next_required_acceptance_evidence_ids
        ),
        "acceptance_evidence_producer_contract_status": AdminApiGateStatus.BLOCKED,
        "acceptance_evidence_producer_contract_source": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CONTRACT_SOURCE
        ),
        "acceptance_evidence_producer_contract_authority": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CONTRACT_AUTHORITY
        ),
        "acceptance_evidence_producer_contract_count": len(
            acceptance_evidence_producer_contracts
        ),
        "missing_acceptance_evidence_producer_contract_count": len(
            missing_acceptance_evidence_producer_contracts
        ),
        "configured_acceptance_evidence_producer_contract_count": len(
            configured_acceptance_evidence_producer_contracts
        ),
        "acceptance_evidence_producer_contract_blockers": (
            acceptance_evidence_producer_contract_blockers
        ),
        "acceptance_evidence_producer_contracts": (
            acceptance_evidence_producer_contracts
        ),
        "acceptance_evidence_producer_readiness_summary": (
            producer_readiness_summary
        ),
        "acceptance_evidence_producer_clearance_action_status": (
            AdminApiGateStatus.BLOCKED
        ),
        "acceptance_evidence_producer_clearance_action_source": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_ACTION_SOURCE
        ),
        "acceptance_evidence_producer_clearance_action_authority": (
            LIVE_ADAPTER_CONSTRUCTION_ACCEPTANCE_EVIDENCE_PRODUCER_CLEARANCE_ACTION_AUTHORITY
        ),
        "acceptance_evidence_producer_clearance_action_count": len(
            producer_readiness_clearance_actions
        ),
        "blocked_acceptance_evidence_producer_clearance_action_count": len(
            blocked_producer_readiness_clearance_actions
        ),
        "ready_acceptance_evidence_producer_clearance_action_count": len(
            ready_producer_readiness_clearance_actions
        ),
        "acceptance_evidence_producer_clearance_action_blockers": [
            action["blocker"]
            for action in blocked_producer_readiness_clearance_actions
        ],
        "acceptance_evidence_producer_clearance_actions": (
            producer_readiness_clearance_actions
        ),
        "acceptance_evidence_producer_clearance_dependency_summary": (
            producer_readiness_clearance_dependency_summary
        ),
        "acceptance_evidence_producer_clearance_work_items": (
            producer_readiness_clearance_work_items
        ),
        "acceptance_evidence_producer_clearance_work_queue_summary": (
            producer_readiness_clearance_work_queue_summary
        ),
        "acceptance_evidence_producer_clearance_claim_traces": (
            producer_readiness_clearance_claim_traces
        ),
        "acceptance_evidence_producer_clearance_claim_trace_summary": (
            producer_readiness_clearance_claim_trace_summary
        ),
        "acceptance_evidence_producer_route_requirements": (
            producer_route_requirements
        ),
        "acceptance_evidence_producer_route_requirement_summary": (
            producer_route_requirement_summary
        ),
        "artifacts": artifacts,
        "required_artifacts": list(LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS),
        "satisfied_artifacts": [],
        "missing_artifacts": list(LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS),
        "verification_gates": list(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_VERIFICATION_GATES
        ),
        "blockers": list(LIVE_EXECUTION_ADAPTER_CONSTRUCTION_BLOCKERS),
        "construction_allowed": False,
        "adapter_constructed": False,
        "adapter_enabled": False,
        "executable": False,
        "live_exchange_submission_allowed": False,
        "live_coinbase_execution_approved": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "forbidden_methods": list(DISABLED_LIVE_EXECUTION_FORBIDDEN_METHODS),
        "evidence": [
            "The backend construction contract is present as read-only evidence.",
            "No route-bound executable adapter has been constructed.",
            "Adapter construction remains blocked until every artifact is satisfied by backend-owned code and gates.",
            "No backend-owned acceptance-evidence producer contract is configured.",
            "Producer-readiness clearance actions are blocked planning evidence only.",
            "Browser and BFF layers may display this contract but cannot satisfy it.",
        ],
        "detail": (
            f"{method} {route} still requires "
            f"{LIVE_ADAPTER_DECISION_NEXT_REQUIRED_CONTRACT} before "
            f"{adapter_reference} can be considered for live execution."
        ),
    }


def build_live_execution_adapter_decision_readback(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    live_adapter_decision_store: FileAdminApiLiveAdapterDecisionStore | None = None,
) -> dict[str, Any]:
    """Return fail-closed latest adapter decision readback evidence."""

    latest_decision = read_latest_live_adapter_decision(
        method=method,
        route=route,
        module_id=module_id,
        service_method=service_method,
        store=live_adapter_decision_store,
    )
    latest_decision_available = latest_decision is not None
    return {
        "latest_adapter_decision_available": latest_decision_available,
        "latest_adapter_decision_id": (
            latest_decision.decision_id if latest_decision is not None else None
        ),
        "latest_adapter_decision_recorded_at": (
            latest_decision.recorded_at if latest_decision is not None else None
        ),
        "latest_adapter_decision_status": (
            latest_decision.status if latest_decision is not None else None
        ),
        "latest_adapter_decision_requested_status": (
            latest_decision.requested_adapter_status
            if latest_decision is not None
            else None
        ),
        "latest_adapter_decision_source": (
            latest_decision.source if latest_decision is not None else None
        ),
        "latest_adapter_decision_adapter_constructed": (
            latest_decision.adapter_constructed if latest_decision is not None else False
        ),
        "latest_adapter_decision_adapter_enabled": (
            latest_decision.adapter_enabled if latest_decision is not None else False
        ),
        "latest_adapter_decision_live_coinbase_execution_approved": (
            latest_decision.live_coinbase_execution_approved
            if latest_decision is not None
            else False
        ),
        "latest_adapter_decision_recorded_artifacts": (
            ["explicit_backend_live_adapter_construction_decision"]
            if latest_decision_available
            else []
        ),
        "latest_adapter_decision_recorded_artifacts_satisfy_construction": False,
        "latest_adapter_decision_satisfaction_authority": (
            "readback_only_no_adapter_construction_satisfaction"
        ),
        "latest_adapter_decision_satisfied_construction_artifacts": [],
        "latest_adapter_decision_unsatisfied_construction_artifacts": (
            list(LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS)
            if latest_decision_available
            else []
        ),
        "latest_adapter_decision_resolution_status": (
            AdminApiLiveAdapterDecisionResolutionStatus.READBACK_ONLY
            if latest_decision_available
            else AdminApiLiveAdapterDecisionResolutionStatus.NOT_AVAILABLE
        ),
        "latest_adapter_decision_non_resolution_reason": (
            LIVE_ADAPTER_DECISION_NON_RESOLUTION_REASON
            if latest_decision_available
            else LIVE_ADAPTER_DECISION_NO_RECORD_REASON
        ),
        "latest_adapter_decision_required_resolution_artifacts": (
            list(LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS)
            if latest_decision_available
            else []
        ),
        "latest_adapter_decision_missing_resolution_artifacts": (
            list(LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS)
            if latest_decision_available
            else []
        ),
        "latest_adapter_decision_forbidden_resolution_claims": (
            list(LIVE_ADAPTER_DECISION_FORBIDDEN_RESOLUTION_CLAIMS)
            if latest_decision_available
            else []
        ),
        "latest_adapter_decision_next_required_contract": (
            LIVE_ADAPTER_DECISION_NEXT_REQUIRED_CONTRACT
            if latest_decision_available
            else None
        ),
        "latest_adapter_decision_resolver_eligible": False,
        "latest_adapter_decision_resolves_construction": False,
    }


def build_live_execution_service_contract(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    action_class: AdminApiActionClass,
    live_execution_service: AdminApiLiveExecutionService | None = None,
    live_service_decision_store: FileAdminApiLiveServiceDecisionStore | None = None,
) -> dict[str, Any]:
    """Return read-only route-to-live-service boundary evidence.

    This is a projection of the backend-owned live execution service state,
    not a live service implementation or adapter factory.
    """

    service = live_execution_service or get_disabled_live_execution_service()
    state = service.admission_state()
    latest_decision = read_latest_live_service_decision(live_service_decision_store)
    latest_decision_available = latest_decision is not None
    latest_decision_recorded_artifacts = (
        ["explicit_backend_live_enablement_decision"]
        if latest_decision_available
        else []
    )
    return {
        "required": state.required,
        "present": state.present,
        "enabled": False,
        "backend_owned": True,
        "route_bound": True,
        "final_boundary": True,
        "status": state.status,
        "source": state.source,
        "missing_reason": state.missing_reason,
        "module_id": module_id,
        "route": route,
        "method": method,
        "service_method": service_method,
        "service_reference": "DisabledAdminApiLiveExecutionService.admission_state",
        "action_class": action_class,
        "executable": False,
        "live_exchange_submission_allowed": False,
        "live_exchange_submitted": False,
        "enablement_precondition_required": True,
        "enablement_precondition_resolved": False,
        "enablement_precondition_authority": (
            LIVE_EXECUTION_SERVICE_ENABLEMENT_AUTHORITY
        ),
        "required_enablement_artifacts": list(
            LIVE_EXECUTION_SERVICE_REQUIRED_ENABLEMENT_ARTIFACTS
        ),
        "missing_enablement_artifacts": list(
            LIVE_EXECUTION_SERVICE_REQUIRED_ENABLEMENT_ARTIFACTS
        ),
        "enablement_contract_refs": list(
            LIVE_EXECUTION_SERVICE_ENABLEMENT_CONTRACT_REFS
        ),
        "enablement_verification_gates": list(
            LIVE_EXECUTION_SERVICE_ENABLEMENT_VERIFICATION_GATES
        ),
        "enablement_blockers": list(LIVE_EXECUTION_SERVICE_ENABLEMENT_BLOCKERS),
        "latest_service_decision_available": latest_decision_available,
        "latest_service_decision_id": (
            latest_decision.decision_id if latest_decision is not None else None
        ),
        "latest_service_decision_recorded_at": (
            latest_decision.recorded_at if latest_decision is not None else None
        ),
        "latest_service_decision_status": (
            latest_decision.status if latest_decision is not None else None
        ),
        "latest_service_decision_requested_status": (
            latest_decision.requested_service_status
            if latest_decision is not None
            else None
        ),
        "latest_service_decision_source": (
            latest_decision.source if latest_decision is not None else None
        ),
        "latest_service_decision_service_enabled": (
            latest_decision.service_enabled if latest_decision is not None else False
        ),
        "latest_service_decision_live_coinbase_execution_approved": (
            latest_decision.live_coinbase_execution_approved
            if latest_decision is not None
            else False
        ),
        "latest_service_decision_recorded_artifacts": (
            latest_decision_recorded_artifacts
        ),
        "latest_service_decision_recorded_artifacts_satisfy_enablement": False,
        "latest_service_decision_satisfaction_authority": (
            "readback_only_no_enablement_satisfaction"
        ),
        "latest_service_decision_satisfied_enablement_artifacts": [],
        "latest_service_decision_unsatisfied_enablement_artifacts": (
            list(LIVE_EXECUTION_SERVICE_REQUIRED_ENABLEMENT_ARTIFACTS)
            if latest_decision_available
            else []
        ),
        "latest_service_decision_resolver_eligible": False,
        "latest_service_decision_resolves_enablement": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "forbidden_methods": list(DISABLED_LIVE_EXECUTION_FORBIDDEN_METHODS),
        "evidence": [
            "Live execution service state is owned by backend admission.",
            "The current service state is disabled and non-executable.",
            "Backend live enablement preconditions are unresolved.",
            (
                "Latest live-service decision readback is local evidence only "
                "and does not resolve enablement."
            ),
            "Browser and BFF layers may display this boundary but cannot enable it.",
        ],
        "detail": (
            f"{method} {route} requires the backend live execution service for "
            f"{service_method}; the service remains disabled with "
            f"{state.missing_reason or LIVE_EXECUTION_DISABLED_REASON}."
        ),
    }


def build_disabled_live_execution_adapter_contract(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    action_class: AdminApiActionClass,
    live_adapter_decision_store: FileAdminApiLiveAdapterDecisionStore | None = None,
) -> dict[str, Any]:
    """Return read-only route-to-service adapter evidence.

    The adapter contract names the shared backend command method that would
    remain the execution boundary in a future live phase. It does not add an
    executable method to the disabled service descriptor.
    """

    adapter_reference = f"AdminApiCommandService.{service_method}"
    return {
        "required": True,
        "configured": False,
        "backend_owned": True,
        "route_bound": True,
        "status": AdminApiLiveExecutionStatus.LIVE_DISABLED,
        "source": DISABLED_LIVE_EXECUTION_SERVICE_SOURCE,
        "missing_reason": LIVE_EXECUTION_DISABLED_REASON,
        "module_id": module_id,
        "route": route,
        "method": method,
        "service_method": service_method,
        "adapter_reference": adapter_reference,
        "action_class": action_class,
        "executable": False,
        "construction_precondition_required": True,
        "construction_precondition_resolved": False,
        "construction_precondition_authority": (
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_AUTHORITY
        ),
        "required_construction_artifacts": list(
            LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS
        ),
        "missing_construction_artifacts": list(
            LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS
        ),
        "construction_contract_refs": list(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_CONTRACT_REFS
        ),
        "construction_verification_gates": list(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_VERIFICATION_GATES
        ),
        "construction_blockers": list(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_BLOCKERS
        ),
        "construction_contract_available": True,
        "construction_contract_ref": LIVE_ADAPTER_DECISION_NEXT_REQUIRED_CONTRACT,
        "construction_contract_satisfies_construction": False,
        "construction_contract": build_live_adapter_construction_contract(
            method=method,
            route=route,
            module_id=module_id,
            service_method=service_method,
            action_class=action_class,
        ),
        **build_live_execution_adapter_construction_satisfaction(),
        **build_live_execution_adapter_decision_readback(
            method=method,
            route=route,
            module_id=module_id,
            service_method=service_method,
            live_adapter_decision_store=live_adapter_decision_store,
        ),
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "forbidden_methods": list(DISABLED_LIVE_EXECUTION_FORBIDDEN_METHODS),
        "evidence": [
            "Live-shaped route is mapped to the shared backend command service.",
            "The disabled live execution service descriptor has no executable adapter.",
            "Backend live adapter construction preconditions are unresolved.",
            "Browser and BFF layers cannot create a route-local execution adapter.",
        ],
        "detail": (
            f"{method} {route} is mapped to {adapter_reference}, but the "
            "Admin API live execution service remains disabled and "
            "non-executable."
        ),
    }


def build_m53_pilot_live_execution_adapter_contract(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    action_class: AdminApiActionClass,
    live_adapter_decision_store: FileAdminApiLiveAdapterDecisionStore | None = None,
) -> dict[str, Any]:
    """Return the M53 route-bound pilot adapter evidence.

    This contract deliberately stops short of executable live submission. It
    proves the selected route is mapped to the shared command service and can
    be dry-run admitted, while the live execution service remains the final
    backend-only boundary before any Coinbase call is possible.
    """

    adapter_reference = f"AdminApiCommandService.{service_method}"
    return {
        "required": True,
        "configured": True,
        "backend_owned": True,
        "route_bound": True,
        "status": AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
        "source": M53_PILOT_LIVE_ADAPTER_SOURCE,
        "missing_reason": M53_PILOT_LIVE_ADAPTER_MISSING_REASON,
        "module_id": module_id,
        "route": route,
        "method": method,
        "service_method": service_method,
        "adapter_reference": adapter_reference,
        "action_class": action_class,
        "executable": False,
        "construction_precondition_required": True,
        "construction_precondition_resolved": False,
        "construction_precondition_authority": (
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_AUTHORITY
        ),
        "required_construction_artifacts": list(
            LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS
        ),
        "missing_construction_artifacts": list(
            LIVE_EXECUTION_ADAPTER_REQUIRED_CONSTRUCTION_ARTIFACTS
        ),
        "construction_contract_refs": list(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_CONTRACT_REFS
        ),
        "construction_verification_gates": list(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_VERIFICATION_GATES
        ),
        "construction_blockers": list(
            LIVE_EXECUTION_ADAPTER_CONSTRUCTION_BLOCKERS
        ),
        "construction_contract_available": True,
        "construction_contract_ref": LIVE_ADAPTER_DECISION_NEXT_REQUIRED_CONTRACT,
        "construction_contract_satisfies_construction": False,
        "construction_contract": build_live_adapter_construction_contract(
            method=method,
            route=route,
            module_id=module_id,
            service_method=service_method,
            action_class=action_class,
        ),
        **build_live_execution_adapter_construction_satisfaction(),
        **build_live_execution_adapter_decision_readback(
            method=method,
            route=route,
            module_id=module_id,
            service_method=service_method,
            live_adapter_decision_store=live_adapter_decision_store,
        ),
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "forbidden_methods": list(DISABLED_LIVE_EXECUTION_FORBIDDEN_METHODS),
        "evidence": [
            "M53 pilot maps one route to the shared backend command service.",
            "Pilot adapter admission is dry-run only and exposes no submit method.",
            "Live execution service admission remains required before Coinbase submission.",
            "Backend live adapter construction preconditions remain unresolved.",
            "Browser and BFF layers cannot make the pilot adapter executable.",
        ],
        "detail": (
            f"{method} {route} is configured as the M53 dry-run pilot for "
            f"{adapter_reference}; it remains non-executable until backend "
            "live execution service admission, route-bound approvals, caps, "
            "admission audit, reconciliation proof, and live caps all pass."
        ),
    }


def build_live_execution_adapter_contract(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    action_class: AdminApiActionClass,
    live_adapter_decision_store: FileAdminApiLiveAdapterDecisionStore | None = None,
) -> dict[str, Any]:
    """Return route-specific live adapter evidence for Admin API readiness."""

    if (
        method == M53_PILOT_LIVE_ADAPTER_METHOD
        and route == M53_PILOT_LIVE_ADAPTER_ROUTE
        and module_id == M53_PILOT_LIVE_ADAPTER_MODULE_ID
        and service_method == M53_PILOT_LIVE_ADAPTER_SERVICE_METHOD
    ):
        return build_m53_pilot_live_execution_adapter_contract(
            method=method,
            route=route,
            module_id=module_id,
            service_method=service_method,
            action_class=action_class,
            live_adapter_decision_store=live_adapter_decision_store,
        )
    return build_disabled_live_execution_adapter_contract(
        method=method,
        route=route,
        module_id=module_id,
        service_method=service_method,
        action_class=action_class,
        live_adapter_decision_store=live_adapter_decision_store,
    )


def build_disabled_live_execution_intent(
    *,
    method: str,
    route: str,
    module_id: str,
    identity_key: str,
    identity_value: str | None,
    action_class: AdminApiActionClass,
    required_permission: AdminApiPermission | str,
    service_method: str,
    actor_id: str,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
    blockers: Sequence[AdminApiLiveAdmissionBlocker],
    live_execution_state: AdminApiLiveExecutionServiceState,
) -> dict[str, Any]:
    """Return the disabled command-to-execution intent evidence.

    This envelope describes the backend-owned execution intent that must be
    admitted before a future live adapter may submit anything. It is evidence
    only; it does not expose create, cancel, submit, or execute behavior.
    """

    adapter_reference = f"AdminApiCommandService.{service_method}"
    return {
        "required": True,
        "prepared": False,
        "backend_owned": True,
        "route_bound": True,
        "payload_bound": True,
        "idempotency_bound": True,
        "executable": False,
        "status": live_execution_state.status,
        "source": live_execution_state.source,
        "missing_reason": live_execution_state.missing_reason,
        "module_id": module_id,
        "route": route,
        "method": method,
        "identity_key": identity_key,
        "identity_value": identity_value,
        "action_class": action_class,
        "required_permission": required_permission,
        "service_method": service_method,
        "adapter_reference": adapter_reference,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
        "operator_intent": operator_intent,
        "payload_hash": payload_hash,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "live_exchange_submitted": False,
        "blockers": list(blockers),
        "evidence": [
            "Execution intent is owned by backend command admission.",
            "Payload hash, idempotency key, actor, and operator intent are bound.",
            "Live execution service remains disabled before adapter invocation.",
        ],
        "detail": (
            f"{method} {route} produced a disabled execution intent for "
            f"{adapter_reference}; no live adapter may execute while "
            f"{live_execution_state.missing_reason or LIVE_EXECUTION_DISABLED_REASON} "
            "is present."
        ),
    }
