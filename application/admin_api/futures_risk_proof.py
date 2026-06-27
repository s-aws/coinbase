"""Durable futures/perpetual risk proof evidence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    AdminFuturesCommandAction,
    AdminFuturesCommandRiskProofKind,
    AdminFuturesRiskProofEvidenceSource,
)


class FuturesRiskProofRecord(BaseModel):
    """Append-only backend futures/perpetual risk proof evidence."""

    model_config = ConfigDict(extra="forbid")

    futures_risk_proof_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.FUTURES_RISK_PROOF
    )
    command: AdminFuturesCommandAction
    proof_kind: AdminFuturesCommandRiskProofKind
    proof_contract_ref: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_source: AdminFuturesRiskProofEvidenceSource
    risk_evidence_refs: list[str] = Field(default_factory=list)
    product_id: str | None = Field(default=None, min_length=1)
    position_key: str | None = Field(default=None, min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    route: str = "/api/v1/futures/risk-proofs"
    method: str = "POST"
    module_id: str = "futures_perpetuals"
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission = (
        AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    )
    service_method: str = "record_futures_risk_proof"
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str = Field(min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_futures_risk_proof_log"
    proof_persisted: bool = True
    risk_proof_verified: bool = False
    risk_proof_accepted: bool = False
    command_route_registered: bool = False
    command_draft_created: bool = False
    command_execution_allowed: bool = False
    margin_validated: bool = False
    collateral_validated: bool = False
    liquidation_validated: bool = False
    funding_validated: bool = False
    reduce_only_validated: bool = False
    close_only_validated: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"


class FileFuturesRiskProofStore:
    """Append-only JSONL futures/perpetual risk proof store."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_FUTURES_RISK_PROOF_LOG_PATH")
            or Path("runtime_state") / "admin_api_futures_risk_proofs.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: FuturesRiskProofRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.futures_risk_proof_id

    def read_recent(self, *, limit: int = 100) -> list[FuturesRiskProofRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[FuturesRiskProofRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(FuturesRiskProofRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def read_all(self) -> list[FuturesRiskProofRecord]:
        """Return every proof record from newest to oldest.

        List routes stay bounded through ``read_recent``. Identity lookups must
        not be bounded, because detail reads and duplicate detection are durable
        proof-id contracts over the append-only log.
        """

        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[FuturesRiskProofRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(FuturesRiskProofRecord.model_validate_json(line))
            except ValueError:
                continue
        return records

    def find_by_proof_id(
        self,
        futures_risk_proof_id: str,
    ) -> FuturesRiskProofRecord | None:
        """Return the latest futures risk proof record for the id."""

        for record in self.read_all():
            if record.futures_risk_proof_id == futures_risk_proof_id:
                return record
        return None

    def read_for_command(
        self,
        *,
        command: AdminFuturesCommandAction,
        proof_kind: AdminFuturesCommandRiskProofKind | None = None,
        limit: int = 100,
    ) -> list[FuturesRiskProofRecord]:
        """Return recent proof records for one futures command and proof kind."""

        records: list[FuturesRiskProofRecord] = []
        for record in self.read_recent(limit=500):
            if record.command != command:
                continue
            if proof_kind is not None and record.proof_kind != proof_kind:
                continue
            records.append(record)
            if len(records) >= max(1, min(limit, 500)):
                break
        return records
