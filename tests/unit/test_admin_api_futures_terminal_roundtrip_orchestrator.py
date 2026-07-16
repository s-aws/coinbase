from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from typing import Any

import pytest

from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_LIVE_POLICY,
    SLICE3_PRODUCT_ID,
    FileSlice3ActionClaimStore,
    Slice3AcceptedPreview,
    Slice3ActionKind,
    Slice3ClaimEvent,
    Slice3CapEvidence,
    Slice3CreateRequest,
    Slice3ExecutionAuthority,
    Slice3MarginWindowEvidence,
    Slice3MarketReference,
    Slice3MutationOutcome,
    Slice3MutationResult,
    Slice3OrderObservation,
    Slice3OrderResolutionSource,
    Slice3Plan,
    Slice3PortfolioBinding,
    Slice3PositionObservation,
    Slice3ReadSlot,
    Slice3MutationGate,
)
from application.admin_api.futures_terminal_roundtrip_activation import (
    Slice3ActivationSeal,
)
from application.admin_api.futures_terminal_roundtrip_admission import (
    SLICE3_ADMISSION_ARTIFACT_PATH,
    Slice3AdmissionSeal,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (
    Slice3ExactOrderEvidence,
    Slice3MarginSummary,
    Slice3OpenOrderZeroProof,
)
from application.admin_api.futures_terminal_roundtrip_orchestrator import (
    FileSlice3TerminalArtifactStore,
    Slice3OrchestrationError,
    Slice3OrchestrationStatus,
    Slice3TerminalRoundtripOrchestrator,
)
from application.admin_api.futures_terminal_roundtrip_reads import (
    FileSlice3ReadJournal,
    Slice3ReadOutcome,
    Slice3ReadRecordEvent,
    slice3_read_declaration,
)
from application.admin_api.futures_terminal_roundtrip_terminal import (
    Slice3HaltedReconciliationEvidence,
)
from core.enums import (
    AdminFuturesPositionSide,
    OrderSide,
    OrderStatus,
    TimeInForce,
)


NOW = datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc)
CREATE_ID = "00000000-0000-4000-8000-000000000501"
CLOSE_ID = "00000000-0000-4000-8000-000000000502"
PREVIEW_ID = "private-preview-orchestrator-501"
PORTFOLIO_ID = "private-portfolio-orchestrator-501"
CREATE_EXCHANGE_ID = "private-create-exchange-orchestrator-501"
CLOSE_EXCHANGE_ID = "private-close-exchange-orchestrator-502"
ACTIVATION_HASH = "a" * 64
ADMISSION_CHAIN_HASH = "b" * 64
ADMISSION_RECORD_HASH = "c" * 64
ADMISSION_ARTIFACT_HASH = "d" * 64


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _terminal_record(path: Path) -> dict[str, object]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    terminal = rows[-1]
    assert isinstance(terminal, dict)
    return terminal


def _slice3_file_sha256(filename: str) -> str:
    path = Path(__file__).parents[2] / "application" / "admin_api" / filename
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan() -> Slice3Plan:
    create = Slice3CreateRequest(
        client_order_id=CREATE_ID,
        preview_id=PREVIEW_ID,
        product_id=SLICE3_PRODUCT_ID,
        side=OrderSide.BUY,
        base_size="1",
        limit_price="6.40",
        post_only=True,
        time_in_force=TimeInForce.GTC,
    )
    preview = Slice3AcceptedPreview.from_request(
        accepted=True,
        preview_id=PREVIEW_ID,
        preview_request=create.preview_request(),
        accepted_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(minutes=5),
        evidence_sha256="1" * 64,
        expiry_source="coinbase_documented_preview_response",
        expiry_evidence_sha256="2" * 64,
        candidate_contract_size="10",
        candidate_limit_price="6.40",
        candidate_reference_price="6.40",
        commission_total="0.12",
        order_margin_total="10",
        available_margin_usdc="250",
    )
    return Slice3Plan.build(
        policy=SLICE3_LIVE_POLICY,
        execution_authority=Slice3ExecutionAuthority(
            actor_id="operator-controlled-futures-proof",
            roles=("trader",),
            correlation_id="00000000-0000-4000-8000-000000000511",
            preview_idempotency_key="00000000-0000-4000-8000-000000000512",
            authorization_sha256="8" * 64,
            route="backend_tool_only_no_http_route",
            method="CLI",
            service_method="Slice3TerminalRoundtripOrchestrator.run",
            permission="operator_explicit_attachment_authority",
            approval_evidence_sha256="8" * 64,
            admission_evidence_sha256="9" * 64,
            cap_guard_evidence_sha256="a" * 64,
            reconciliation_evidence_sha256="b" * 64,
            live_service_evidence_sha256="c" * 64,
            adapter_evidence_sha256="d" * 64,
            product_evidence_sha256="e" * 64,
            market_evidence_sha256="f" * 64,
            margin_collateral_evidence_sha256="8" * 64,
            liquidation_evidence_sha256="9" * 64,
            fee_funding_evidence_sha256="a" * 64,
            observed_at=NOW,
        ),
        margin_windows=Slice3MarginWindowEvidence(
            retail_regular="MARGIN_WINDOW_TYPE_UNSPECIFIED",
            retail_intraday_margin_1="MARGIN_WINDOW_TYPE_INTRADAY",
        ),
        portfolio=Slice3PortfolioBinding(
            portfolio_id=PORTFOLIO_ID,
            portfolio_name="Default",
            portfolio_type="DEFAULT",
            can_view=True,
            can_trade=True,
            product_family="US_CFM",
            intx_excluded=True,
            request_override_allowed=False,
            read_authorized=True,
            exact_match_count=1,
            selection_authority="cdp_api_key_permissioned_portfolio",
            observed_at=NOW,
            permission_evidence_sha256="b" * 64,
            portfolio_catalog_sha256="c" * 64,
        ),
        preview=preview,
        create=create,
        caps=Slice3CapEvidence(
            opening_reference_usdc="64",
            maximum_concurrent_exposure_usdc="64",
            conservative_close_usdc="76.8",
            branch_turnover_usdc="140.8",
        ),
        close_client_order_id=CLOSE_ID,
        baseline_position_contracts="0",
        baseline_position_sha256="2" * 64,
        backend_revision="backend-test-revision",
        openapi_revision="openapi-test-revision",
        now=NOW,
    )


def _position(
    contracts: str,
    *,
    observed_at: datetime = NOW,
) -> Slice3PositionObservation:
    flat = Decimal(contracts) == 0
    return Slice3PositionObservation(
        authoritative=True,
        product_id=SLICE3_PRODUCT_ID,
        side=(AdminFuturesPositionSide.FLAT if flat else AdminFuturesPositionSide.LONG),
        contracts=contracts,
        reference_price=None if flat else "6.40",
        contract_size="10",
        observed_at=observed_at,
        snapshot_sha256=_canonical_sha256(
            {"kind": "position", "contracts": contracts, "at": observed_at.isoformat()}
        ),
    )


def _order(
    *,
    client_id: str,
    exchange_id: str,
    side: OrderSide,
    status: OrderStatus,
    filled: str,
    remaining: str,
    resolution: Slice3OrderResolutionSource = (
        Slice3OrderResolutionSource.AUTHORITATIVE_ORDER_READ
    ),
    observed_at: datetime = NOW,
) -> Slice3ExactOrderEvidence:
    configuration = (
        {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "6.40",
                "post_only": True,
            }
        }
        if side is OrderSide.BUY
        else {"market_market_ioc": {"base_size": filled}}
    )
    return Slice3ExactOrderEvidence(
        observation=Slice3OrderObservation(
            authoritative=True,
            pagination_complete=True,
            product_id=SLICE3_PRODUCT_ID,
            client_order_id=client_id,
            exchange_order_id=exchange_id,
            status=status,
            filled_contracts=filled,
            remaining_contracts=remaining,
            active_order_count=(
                1
                if status in {
                    OrderStatus.PENDING,
                    OrderStatus.OPEN,
                    OrderStatus.QUEUED,
                    OrderStatus.CANCEL_QUEUED,
                    OrderStatus.EDIT_QUEUED,
                }
                else 0
            ),
            observed_at=observed_at,
            resolution_source=resolution,
            exact_client_order_match_count=(
                1
                if resolution
                is Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
                else None
            ),
        ),
        side=side,
        filled_value=(
            "0" if Decimal(filled) == 0 else str(Decimal(filled) * Decimal("64"))
        ),
        total_fees=("0" if Decimal(filled) == 0 else "0.02"),
        number_of_fills=0 if Decimal(filled) == 0 else 1,
        order_configuration_sha256=_canonical_sha256(configuration),
    )


def _zero_orders(
    *,
    observed_at: datetime = NOW,
    active_order_count: int = 0,
) -> Slice3OpenOrderZeroProof:
    return Slice3OpenOrderZeroProof(
        authoritative=True,
        pagination_complete=True,
        scope="exact_product_active_transitional_orders",
        product_id=SLICE3_PRODUCT_ID,
        exact_product_active_order_count=active_order_count,
        observed_at=observed_at,
        snapshot_sha256="3" * 64,
    )


def _margin(
    *,
    available_margin_usdc: str = "250",
    status: str = "ready",
    observed_at: datetime = NOW,
) -> Slice3MarginSummary:
    return Slice3MarginSummary(
        status=status,
        account_family="coinbase_futures_us_cfm",
        available_margin_usdc=available_margin_usdc,
        total_usd_balance_usdc="500",
        initial_margin_usdc="40",
        liquidation_threshold_usdc="80",
        retail_regular_margin_window="MARGIN_WINDOW_TYPE_UNSPECIFIED",
        retail_intraday_margin_window="MARGIN_WINDOW_TYPE_INTRADAY",
        observed_at=observed_at,
        snapshot_sha256="4" * 64,
    )


@dataclass
class _FakeManifest:
    plan_sha256: str
    action_path: Path
    read_path: Path
    terminal_path: Path
    backend_revision: str
    openapi_revision: str
    authorization_text_sha256: str
    core_module_sha256: str
    port_module_sha256: str
    orchestrator_module_sha256: str
    admission_module_sha256: str
    admission_chain_sha256: str
    admission_record_sha256: str
    admission_artifact_file_sha256: str
    action_journal_schema_sha256: str
    read_journal_schema_sha256: str
    terminal_evidence_schema_sha256: str
    slice3_live_policy_sha256: str
    manifest_sha256: str = ACTIVATION_HASH

    def validate_at(self, now: datetime) -> None:
        assert NOW <= now < NOW + timedelta(minutes=20)

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "readiness": "ready",
            "slice3_plan_sha256": self.plan_sha256,
            "authorization_text_sha256": self.authorization_text_sha256,
            "backend_revision": self.backend_revision,
            "openapi_revision": self.openapi_revision,
            "journal_path": str(self.action_path),
            "read_journal_path": str(self.read_path),
            "terminal_evidence_path": str(self.terminal_path),
            "schema_versions": {
                "action_journal": "slice3-action-claim-record-v4",
                "read_journal": "slice3-read-journal-record-v1",
                "terminal_evidence": "slice3-terminal-roundtrip-evidence-v2",
                "slice3_live_policy": "slice3-terminal-roundtrip-policy-v1",
            },
            "schema_policy_sha256": {
                "action_journal_schema": self.action_journal_schema_sha256,
                "read_journal_schema": self.read_journal_schema_sha256,
                "terminal_evidence_schema": self.terminal_evidence_schema_sha256,
                "slice3_live_policy": self.slice3_live_policy_sha256,
            },
            "module_sha256": {
                "core": self.core_module_sha256,
                "port": self.port_module_sha256,
                "orchestrator": self.orchestrator_module_sha256,
            },
            "admission_module_sha256": self.admission_module_sha256,
            "admission_chain_sha256": self.admission_chain_sha256,
            "admission_record_sha256": self.admission_record_sha256,
            "admission_artifact_file_sha256": (self.admission_artifact_file_sha256),
            "attempt_limits": {
                "preview": 0,
                "create": 1,
                "cancel": 1,
                "close": 1,
                "reduce": 0,
                "retry": 0,
                "fallback": 0,
                "redirect": 0,
            },
            "live_adapter_bound": True,
            "route_registered": False,
            "raw_identifier_values_included": False,
        }


@dataclass(frozen=True)
class _FakeAdmissionChain:
    plan_sha256: str
    authorization_sha256: str
    chain_sha256: str = ADMISSION_CHAIN_HASH

    def validate_at(self, now: datetime) -> None:
        assert NOW <= now < NOW + timedelta(minutes=20)


class _FakeAdmissionStore:
    def __init__(self, seal: Slice3AdmissionSeal) -> None:
        self.seal = seal
        self.path = SLICE3_ADMISSION_ARTIFACT_PATH
        self.calls = 0

    def read(
        self,
        *,
        now: datetime,
        expected_chain_sha256: str,
    ) -> Slice3AdmissionSeal:
        self.calls += 1
        assert expected_chain_sha256 == ADMISSION_CHAIN_HASH
        self.seal.chain.validate_at(now)
        return self.seal


class _FakeActivationStore:
    def __init__(
        self,
        seal: Slice3ActivationSeal,
        admission_store: _FakeAdmissionStore,
    ) -> None:
        self.seal = seal
        self.admission_store = admission_store
        self.calls = 0

    def read(
        self, *, now: datetime, expected_manifest_sha256: str
    ) -> Slice3ActivationSeal:
        self.calls += 1
        assert expected_manifest_sha256 == ACTIVATION_HASH
        self.seal.manifest.validate_at(now)
        return self.seal


def _activation(
    plan: Slice3Plan,
    *,
    action_path: Path,
    read_path: Path,
    terminal_path: Path,
) -> _FakeActivationStore:
    manifest = _FakeManifest(
        plan_sha256=plan.plan_sha256,
        action_path=action_path,
        read_path=read_path,
        terminal_path=terminal_path,
        backend_revision=plan.backend_revision,
        openapi_revision=plan.openapi_revision,
        authorization_text_sha256=(plan.execution_authority.authorization_sha256),
        core_module_sha256=_slice3_file_sha256("futures_terminal_roundtrip.py"),
        port_module_sha256=_slice3_file_sha256(
            "futures_terminal_roundtrip_coinbase.py"
        ),
        orchestrator_module_sha256=_slice3_file_sha256(
            "futures_terminal_roundtrip_orchestrator.py"
        ),
        admission_module_sha256=_slice3_file_sha256(
            "futures_terminal_roundtrip_admission.py"
        ),
        admission_chain_sha256=ADMISSION_CHAIN_HASH,
        admission_record_sha256=ADMISSION_RECORD_HASH,
        admission_artifact_file_sha256=ADMISSION_ARTIFACT_HASH,
        action_journal_schema_sha256=_slice3_file_sha256(
            "futures_terminal_roundtrip.py"
        ),
        read_journal_schema_sha256=_slice3_file_sha256(
            "futures_terminal_roundtrip_reads.py"
        ),
        terminal_evidence_schema_sha256=_slice3_file_sha256(
            "futures_terminal_roundtrip_terminal.py"
        ),
        slice3_live_policy_sha256=_canonical_sha256(plan.policy.sanitized_evidence()),
    )
    seal = Slice3ActivationSeal(
        manifest=manifest,  # type: ignore[arg-type]
        manifest_sha256=ACTIVATION_HASH,
        record_sha256="5" * 64,
        artifact_file_sha256="6" * 64,
        device=1,
        inode=2,
        size=3,
        mode=0o100400,
        owner_uid=0,
        link_count=1,
        mtime_ns=4,
    )
    admission_seal = Slice3AdmissionSeal(
        chain=_FakeAdmissionChain(
            plan_sha256=plan.plan_sha256,
            authorization_sha256=(plan.execution_authority.authorization_sha256),
        ),  # type: ignore[arg-type]
        chain_sha256=ADMISSION_CHAIN_HASH,
        record_sha256=ADMISSION_RECORD_HASH,
        artifact_file_sha256=ADMISSION_ARTIFACT_HASH,
        device=1,
        inode=2,
        size=3,
        mode=0o400,
        owner_uid=os.geteuid(),
        link_count=1,
        mtime_ns=4,
    )
    return _FakeActivationStore(
        seal,
        _FakeAdmissionStore(admission_seal),
    )


class _FakePort:
    def __init__(
        self,
        *,
        create_result: Slice3MutationResult,
        positions: list[Slice3PositionObservation],
        opening_orders: list[Slice3ExactOrderEvidence],
        close_order: Slice3ExactOrderEvidence | None = None,
        cancel_result: Slice3MutationResult | Exception | None = None,
        close_result: Slice3MutationResult | Exception | None = None,
        margins: list[Slice3MarginSummary] | None = None,
        active_order_counts: list[int] | None = None,
        failures: dict[str, set[int]] | None = None,
    ) -> None:
        self.create_result = create_result
        self.positions = list(positions)
        self.opening_orders = list(opening_orders)
        self.close_order = close_order
        self.cancel_result = cancel_result
        self.close_result = close_result
        self.margins = list(margins) if margins is not None else None
        self.active_order_counts = (
            list(active_order_counts) if active_order_counts is not None else None
        )
        self.failures = failures or {}
        self.calls: list[str] = []
        self.close_requests: list[dict[str, object]] = []

    def _record(self, name: str) -> None:
        self.calls.append(name)
        call_number = self.calls.count(name)
        if call_number in self.failures.get(name, set()):
            raise RuntimeError(
                "private orchestrator delegate exception must be withheld"
            )

    def create_order(self, **kwargs: object) -> Slice3MutationResult:
        self._record("create")
        return self.create_result

    def cancel_order(self, **kwargs: object) -> Slice3MutationResult:
        self._record("cancel")
        if isinstance(self.cancel_result, Exception):
            raise self.cancel_result
        if self.cancel_result is not None:
            return self.cancel_result
        return Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="cancel_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        )

    def close_position(self, **kwargs: object) -> Slice3MutationResult:
        self._record("close")
        self.close_requests.append(dict(kwargs))
        if isinstance(self.close_result, Exception):
            raise self.close_result
        if self.close_result is not None:
            return self.close_result
        return Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="close_accepted",
            exchange_order_id=CLOSE_EXCHANGE_ID,
        )

    def prove_zero_open_orders(
        self, *, observed_at: datetime
    ) -> Slice3OpenOrderZeroProof:
        self._record("zero_orders")
        active_order_count = (
            self.active_order_counts.pop(0)
            if self.active_order_counts is not None
            else 0
        )
        return _zero_orders(
            observed_at=observed_at,
            active_order_count=active_order_count,
        )

    def read_position(self, *, observed_at: datetime) -> Slice3PositionObservation:
        self._record("position")
        return self.positions.pop(0)

    def read_exact_order(self, **kwargs: object) -> Slice3ExactOrderEvidence:
        self._record("exact_order")
        if kwargs.get("client_order_id") == CLOSE_ID:
            assert self.close_order is not None
            return self.close_order
        return self.opening_orders.pop(0)

    def resolve_exact_order_by_client_order_id(
        self, **kwargs: object
    ) -> Slice3ExactOrderEvidence:
        self._record("resolve_opening")
        return self.opening_orders.pop(0)

    def resolve_exact_close_order_by_client_order_id(
        self, **kwargs: object
    ) -> Slice3ExactOrderEvidence:
        self._record("resolve_close")
        assert self.close_order is not None
        return self.close_order

    def read_market_reference(self, *, observed_at: datetime) -> Slice3MarketReference:
        self._record("market")
        return Slice3MarketReference(
            authoritative=True,
            product_id=SLICE3_PRODUCT_ID,
            reference_price="6.41",
            observed_at=observed_at,
            snapshot_sha256="7" * 64,
        )

    def read_margin_summary(self, *, observed_at: datetime) -> Slice3MarginSummary:
        self._record("margin")
        if self.margins is not None:
            return self.margins.pop(0)
        return _margin(observed_at=observed_at)


def _orchestrator(
    tmp_path: Path,
    plan: Slice3Plan,
    port: _FakePort,
    *,
    now_provider: Any = None,
) -> tuple[Slice3TerminalRoundtripOrchestrator, _FakeActivationStore]:
    action_path = tmp_path / "actions.jsonl"
    read_path = tmp_path / "reads.jsonl"
    terminal_path = tmp_path / "terminal.json"
    activation = _activation(
        plan,
        action_path=action_path,
        read_path=read_path,
        terminal_path=terminal_path,
    )
    orchestrator = Slice3TerminalRoundtripOrchestrator(
        action_store=FileSlice3ActionClaimStore(action_path),
        read_journal=FileSlice3ReadJournal(read_path),
        terminal_store=FileSlice3TerminalArtifactStore(terminal_path),
        port_factory=lambda _: port,
        now_provider=(now_provider if now_provider is not None else lambda: NOW),
        admission_store=activation.admission_store,
    )
    return orchestrator, activation


def test_now_is_resampled_before_reads_mutation_and_terminal_validation(
    tmp_path: Path,
) -> None:
    plan = _plan()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_rejected",
        ),
        positions=[_position("0"), _position("0")],
        opening_orders=[],
    )
    samples = 0

    def advancing_now() -> datetime:
        nonlocal samples
        value = NOW + timedelta(milliseconds=samples)
        samples += 1
        return value

    orchestrator, activation = _orchestrator(
        tmp_path,
        plan,
        port,
        now_provider=advancing_now,
    )

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert samples >= 12


def test_filled_branch_is_one_create_one_close_no_cancel(tmp_path: Path) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    close = _order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[_position("0"), _position("1"), _position("1"), _position("0")],
        opening_orders=[opening],
        close_order=close,
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("create") == 1
    assert port.calls.count("cancel") == 0
    assert port.calls.count("close") == 1
    assert port.calls.count("market") == 1
    assert activation.calls == 1
    cancel_record = FileSlice3ActionClaimStore(tmp_path / "actions.jsonl").inspect(
        plan.action_claim(Slice3ActionKind.CANCEL)
    )
    assert cancel_record is not None
    assert cancel_record.event is Slice3ClaimEvent.RETIRED
    assert cancel_record.reason_code == "cancel_not_required_filled_branch"
    serialized = (tmp_path / "terminal.json").read_text(encoding="utf-8")
    for private in (
        PREVIEW_ID,
        PORTFOLIO_ID,
        CREATE_ID,
        CLOSE_ID,
        CREATE_EXCHANGE_ID,
        CLOSE_EXCHANGE_ID,
    ):
        assert private not in serialized


def test_filled_branch_never_closes_with_another_active_product_order(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[_position("0"), _position("1"), _position("1"), _position("0")],
        opening_orders=[opening],
        active_order_counts=[0, 1, 0],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert port.calls.count("create") == 1
    assert port.calls.count("cancel") == 0
    assert port.calls.count("close") == 0
    assert port.calls.count("zero_orders") == 3


def test_explicit_create_rejection_uses_no_order_cancel_or_close(
    tmp_path: Path,
) -> None:
    plan = _plan()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_rejected",
        ),
        positions=[_position("0"), _position("0")],
        opening_orders=[],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("create") == 1
    assert "exact_order" not in port.calls
    assert "resolve_opening" not in port.calls
    assert "cancel" not in port.calls
    assert "close" not in port.calls
    assert result.terminal_evidence is not None
    assert result.terminal_evidence.opening_order is None
    action_store = FileSlice3ActionClaimStore(tmp_path / "actions.jsonl")
    assert (
        action_store.inspect(plan.action_claim(Slice3ActionKind.CANCEL)).reason_code
        == "cancel_not_required_create_rejected"
    )
    assert (
        action_store.inspect(plan.action_claim(Slice3ActionKind.CLOSE)).reason_code
        == "close_not_required_create_rejected"
    )


def test_second_run_is_blocked_without_second_port_or_mutation(tmp_path: Path) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FAILED,
        filled="0",
        remaining="1",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[_position("0"), _position("0"), _position("0")],
        opening_orders=[opening],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)
    first = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )
    assert first.status is Slice3OrchestrationStatus.RESTORED_BASELINE

    with pytest.raises(Exception):
        orchestrator.run(
            plan=plan,
            activation_store=activation,  # type: ignore[arg-type]
            expected_activation_manifest_sha256=ACTIVATION_HASH,
        )

    assert port.calls.count("create") == 1


def test_open_zero_fill_branch_cancels_once_and_does_not_close(
    tmp_path: Path,
) -> None:
    plan = _plan()
    active = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.OPEN,
        filled="0",
        remaining="1",
    )
    terminal = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0",
        remaining="1",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("0"),
            _position("0"),
            _position("0"),
        ],
        opening_orders=[active, terminal],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("create") == 1
    assert port.calls.count("cancel") == 1
    assert port.calls.count("close") == 0
    close_record = FileSlice3ActionClaimStore(tmp_path / "actions.jsonl").inspect(
        plan.action_claim(Slice3ActionKind.CLOSE)
    )
    assert close_record is not None
    assert close_record.event is Slice3ClaimEvent.RETIRED
    assert close_record.reason_code == "close_not_required_zero_exposure"


@pytest.mark.parametrize(
    "status",
    [OrderStatus.PENDING, OrderStatus.QUEUED, OrderStatus.EDIT_QUEUED],
)
def test_transitional_zero_fill_branches_never_cancel_or_close(
    tmp_path: Path,
    status: OrderStatus,
) -> None:
    plan = _plan()
    active = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=status,
        filled="0",
        remaining="1",
    )
    terminal = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0",
        remaining="1",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("0"),
            _position("0"),
            _position("0"),
        ],
        opening_orders=[active, terminal],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert port.calls.count("create") == 1
    assert port.calls.count("cancel") == 0
    assert port.calls.count("close") == 0


def test_cancel_queued_never_recancels_or_closes_and_halts_with_sanitized_count(
    tmp_path: Path,
) -> None:
    plan = _plan()
    cancel_queued = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCEL_QUEUED,
        filled="0",
        remaining="1",
    )
    recovery_cancel_queued = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCEL_QUEUED,
        filled="0",
        remaining="1",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("0"),
            _position("0"),
            _position("0"),
        ],
        opening_orders=[cancel_queued, recovery_cancel_queued],
        active_order_counts=[0, 1],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert result.reason_code == "cancel_queued_final_reconciliation_required"
    assert port.calls.count("create") == 1
    assert port.calls.count("cancel") == 0
    assert port.calls.count("close") == 0
    assert port.calls.count("resolve_opening") == 1
    terminal = _terminal_record(tmp_path / "terminal.json")
    halted = terminal["terminal_evidence"]
    assert halted["open_orders"] == {
        "proof_status": "proven",
        "product_id": SLICE3_PRODUCT_ID,
        "active_order_count": 1,
        "observed_at": NOW.isoformat(),
        "snapshot_sha256": "3" * 64,
    }
    assert halted["raw_response_included"] is False
    assert halted["identifier_values_included"] is False
    assert halted["exception_text_included"] is False
    serialized = json.dumps(halted, sort_keys=True)
    assert CREATE_ID not in serialized
    assert CREATE_EXCHANGE_ID not in serialized


def test_partial_branch_cancels_residual_then_closes_exact_delta(
    tmp_path: Path,
) -> None:
    plan = _plan()
    active = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.OPEN,
        filled="0.5",
        remaining="0.5",
    )
    terminal = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0.5",
        remaining="0.5",
    )
    close = _order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="0.5",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("0.5"),
            _position("0.5"),
            _position("0"),
        ],
        opening_orders=[active, terminal],
        close_order=close,
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("create") == 1
    assert port.calls.count("cancel") == 1
    assert port.calls.count("close") == 1
    assert port.calls.count("market") == 1
    assert port.close_requests == [
        {
            "client_order_id": CLOSE_ID,
            "product_id": SLICE3_PRODUCT_ID,
            "size": "0.5",
        }
    ]


def test_post_cancel_branch_never_closes_with_another_active_product_order(
    tmp_path: Path,
) -> None:
    plan = _plan()
    active = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.OPEN,
        filled="0.5",
        remaining="0.5",
    )
    terminal = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0.5",
        remaining="0.5",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("0.5"),
            _position("0.5"),
            _position("0"),
        ],
        opening_orders=[active, terminal],
        active_order_counts=[0, 1, 0],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert port.calls.count("create") == 1
    assert port.calls.count("cancel") == 1
    assert port.calls.count("close") == 0
    assert port.calls.count("zero_orders") == 3


def test_unknown_create_uses_only_exact_client_lookup_then_closes(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    close = _order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.UNKNOWN,
            reason_code="create_outcome_unknown",
        ),
        positions=[_position("0"), _position("1"), _position("1"), _position("0")],
        opening_orders=[opening],
        close_order=close,
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("resolve_opening") == 1
    assert port.calls.count("exact_order") == 1  # Close readback only.
    assert port.calls.count("create") == 1
    assert port.calls.count("close") == 1


def test_unknown_close_uses_only_exact_close_client_lookup(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    close = _order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        close_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.UNKNOWN,
            reason_code="close_outcome_unknown",
        ),
        positions=[_position("0"), _position("1"), _position("1"), _position("0")],
        opening_orders=[opening],
        close_order=close,
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("resolve_close") == 1
    assert port.calls.count("exact_order") == 1  # Opening readback only.
    assert port.calls.count("close") == 1


def test_unknown_create_without_exact_unique_resolution_halts(
    tmp_path: Path,
) -> None:
    plan = _plan()
    not_exact = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.UNKNOWN,
            reason_code="create_outcome_unknown",
        ),
        positions=[_position("0"), _position("0")],
        opening_orders=[not_exact, not_exact],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert port.calls.count("resolve_opening") == 2
    assert "cancel" not in port.calls
    assert "close" not in port.calls
    terminal = (tmp_path / "terminal.json").read_text(encoding="utf-8")
    assert "unknown_create_not_uniquely_resolved" in terminal


def test_post_create_read_exception_runs_one_recovery_pass_and_restores(
    tmp_path: Path,
) -> None:
    plan = _plan()
    recovery_opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    close = _order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[_position("0"), _position("1"), _position("0")],
        opening_orders=[recovery_opening],
        close_order=close,
        failures={"exact_order": {1}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("create") == 1
    assert port.calls.count("resolve_opening") == 1
    assert port.calls.count("close") == 1
    assert port.calls.count("position") == 3
    assert port.calls.count("zero_orders") == 3
    assert port.calls.count("margin") == 2
    terminal = (tmp_path / "terminal.json").read_text(encoding="utf-8")
    assert "private orchestrator delegate exception" not in terminal
    assert '"status":"restored_baseline"' in terminal


def test_recovery_branch_never_closes_with_another_active_product_order(
    tmp_path: Path,
) -> None:
    plan = _plan()
    recovery_opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[_position("0"), _position("1"), _position("0")],
        opening_orders=[recovery_opening],
        active_order_counts=[0, 1, 0],
        failures={"exact_order": {1}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert port.calls.count("create") == 1
    assert port.calls.count("resolve_opening") == 1
    assert port.calls.count("close") == 0
    assert port.calls.count("zero_orders") == 3


def test_recovery_initiated_cancel_uses_dedicated_post_cancel_reads_once(
    tmp_path: Path,
) -> None:
    plan = _plan()
    recovery_opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.OPEN,
        filled="0",
        remaining="1",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    cancelled = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0",
        remaining="1",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("0"),
            _position("0"),
            _position("0"),
        ],
        opening_orders=[recovery_opening, cancelled],
        failures={"exact_order": {1}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("create") == 1
    assert port.calls.count("cancel") == 1
    assert port.calls.count("close") == 0
    assert port.calls.count("resolve_opening") == 1
    assert port.calls.count("exact_order") == 2
    consumed_slots = {
        record.slot
        for record in orchestrator.read_journal.read_all()
        if record.event is Slice3ReadRecordEvent.CONSUMED
    }
    assert Slice3ReadSlot.RECOVERY_POST_CANCEL_TERMINAL_ORDER in consumed_slots
    assert Slice3ReadSlot.RECOVERY_POST_CANCEL_POSITION in consumed_slots


def test_post_cancel_read_failure_recovers_without_cancel_replay(
    tmp_path: Path,
) -> None:
    plan = _plan()
    normal_opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.OPEN,
        filled="0",
        remaining="1",
    )
    recovery_cancelled = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0",
        remaining="1",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("0"),
            _position("0"),
            _position("0"),
        ],
        opening_orders=[normal_opening, recovery_cancelled],
        failures={"exact_order": {2}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("create") == 1
    assert port.calls.count("cancel") == 1
    assert port.calls.count("close") == 0
    assert port.calls.count("resolve_opening") == 1
    assert port.calls.count("exact_order") == 2


def test_create_mutation_exception_is_unknown_and_exactly_reconciled(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FAILED,
        filled="0",
        remaining="1",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[_position("0"), _position("0"), _position("0")],
        opening_orders=[opening],
        failures={"create": {1}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("create") == 1
    assert port.calls.count("resolve_opening") == 1
    assert "cancel" not in port.calls
    assert "close" not in port.calls


def test_cancel_mutation_exception_is_unknown_then_terminally_read_once(
    tmp_path: Path,
) -> None:
    plan = _plan()
    active = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.OPEN,
        filled="0.5",
        remaining="0.5",
    )
    terminal = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0.5",
        remaining="0.5",
    )
    close = _order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="0.5",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("0.5"),
            _position("0.5"),
            _position("0"),
        ],
        opening_orders=[active, terminal],
        close_order=close,
        failures={"cancel": {1}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("cancel") == 1
    assert port.calls.count("exact_order") == 3
    assert port.calls.count("close") == 1


def test_close_mutation_exception_uses_only_exact_close_lookup(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    close = _order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[_position("0"), _position("1"), _position("1"), _position("0")],
        opening_orders=[opening],
        close_order=close,
        failures={"close": {1}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("close") == 1
    assert port.calls.count("resolve_close") == 1
    assert "private orchestrator delegate exception" not in (
        tmp_path / "terminal.json"
    ).read_text(encoding="utf-8")


def test_explicit_close_rejection_halts_and_reconciles_without_order_fallback(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        close_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="close_explicitly_rejected",
        ),
        positions=[
            _position("0"),
            _position("1"),
            _position("1"),
            _position("1"),
            _position("1"),
        ],
        opening_orders=[
            opening,
            _order(
                client_id=CREATE_ID,
                exchange_id=CREATE_EXCHANGE_ID,
                side=OrderSide.BUY,
                status=OrderStatus.FILLED,
                filled="1",
                remaining="0",
                resolution=(Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP),
            ),
        ],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert result.reason_code == "recovery_close_outcome_unrestored"
    assert port.calls.count("close") == 1
    assert port.calls.count("exact_order") == 1  # Normal opening only.
    assert port.calls.count("resolve_opening") == 1
    assert port.calls.count("resolve_close") == 0
    assert port.calls.count("zero_orders") == 3
    assert port.calls.count("margin") == 2
    terminal = _terminal_record(tmp_path / "terminal.json")
    halted = terminal["terminal_evidence"]
    assert isinstance(
        result.terminal_evidence,
        Slice3HaltedReconciliationEvidence,
    )
    assert result.terminal_evidence.sanitized_evidence(plan=plan, now=NOW) == halted
    assert halted == {
        **halted,
        "schema_version": "slice3-halted-reconciliation-evidence-v1",
        "mutation_began": True,
        "final_reconciliation_attempted": True,
        "final_reconciliation_complete": True,
        "restored_baseline": False,
        "raw_response_included": False,
        "identifier_values_included": False,
        "exception_text_included": False,
    }
    assert halted["position"] == {
        "proof_status": "proven",
        "product_id": SLICE3_PRODUCT_ID,
        "side": "LONG",
        "contracts": "1",
        "baseline_delta_contracts": "1",
        "contract_size": "10",
        "observed_at": NOW.isoformat(),
        "snapshot_sha256": _canonical_sha256(
            {"kind": "position", "contracts": "1", "at": NOW.isoformat()}
        ),
    }
    assert halted["open_orders"] == {
        "proof_status": "proven",
        "product_id": SLICE3_PRODUCT_ID,
        "active_order_count": 0,
        "observed_at": NOW.isoformat(),
        "snapshot_sha256": "3" * 64,
    }
    assert halted["margin"] == {
        "proof_status": "proven",
        "status": "ready",
        "account_family": "coinbase_futures_us_cfm",
        "available_margin_usdc": "250",
        "total_usd_balance_usdc": "500",
        "initial_margin_usdc": "40",
        "liquidation_threshold_usdc": "80",
        "observed_at": NOW.isoformat(),
        "snapshot_sha256": "4" * 64,
    }


def test_explicit_close_rejection_with_incomplete_reconciliation_records_unknowns(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        close_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="close_explicitly_rejected",
        ),
        positions=[
            _position("0"),
            _position("1"),
            _position("1"),
            _position("1"),
            _position("1"),
        ],
        opening_orders=[
            opening,
            _order(
                client_id=CREATE_ID,
                exchange_id=CREATE_EXCHANGE_ID,
                side=OrderSide.BUY,
                status=OrderStatus.FILLED,
                filled="1",
                remaining="0",
                resolution=(Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP),
            ),
        ],
        failures={"zero_orders": {3}, "margin": {2}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    terminal = _terminal_record(tmp_path / "terminal.json")
    halted = terminal["terminal_evidence"]
    assert halted["mutation_began"] is True
    assert halted["final_reconciliation_attempted"] is True
    assert halted["final_reconciliation_complete"] is False
    assert halted["restored_baseline"] is False
    assert halted["position"]["proof_status"] == "proven"
    assert halted["position"]["contracts"] == "1"
    assert halted["position"]["baseline_delta_contracts"] == "1"
    assert halted["open_orders"] == {
        "proof_status": "unknown",
        "product_id": SLICE3_PRODUCT_ID,
        "active_order_count": None,
        "observed_at": None,
        "snapshot_sha256": None,
    }
    assert halted["margin"] == {
        "proof_status": "unknown",
        "status": None,
        "account_family": None,
        "available_margin_usdc": None,
        "total_usd_balance_usdc": None,
        "initial_margin_usdc": None,
        "liquidation_threshold_usdc": None,
        "observed_at": None,
        "snapshot_sha256": None,
    }
    serialized = (tmp_path / "terminal.json").read_text(encoding="utf-8")
    assert "private orchestrator delegate exception" not in serialized


def test_pre_create_insufficient_margin_halts_before_create(
    tmp_path: Path,
) -> None:
    plan = _plan()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[_position("0")],
        opening_orders=[],
        margins=[_margin(available_margin_usdc="10.12")],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert result.reason_code == "pre_create_margin_invalid"
    assert port.calls == ["zero_orders", "position", "margin"]
    action_store = FileSlice3ActionClaimStore(tmp_path / "actions.jsonl")
    assert all(
        action_store.inspect(plan.action_claim(action)).event
        is Slice3ClaimEvent.RETIRED
        for action in Slice3ActionKind
    )
    halted = _terminal_record(tmp_path / "terminal.json")["terminal_evidence"]
    assert halted["mutation_began"] is False
    assert halted["final_reconciliation_attempted"] is False
    assert halted["final_reconciliation_complete"] is False
    assert halted["restored_baseline"] is False
    assert halted["position"]["proof_status"] == "unknown"
    assert halted["open_orders"]["proof_status"] == "unknown"
    assert halted["margin"]["proof_status"] == "unknown"


def test_pre_create_active_order_count_halts_before_create(tmp_path: Path) -> None:
    plan = _plan()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[],
        opening_orders=[],
        active_order_counts=[1],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert result.reason_code == "pre_create_open_orders_invalid"
    assert port.calls == ["zero_orders"]
    assert "create" not in port.calls
    halted = _terminal_record(tmp_path / "terminal.json")["terminal_evidence"]
    assert halted["mutation_began"] is False


def test_unknown_close_lookup_exception_recovers_without_close_replay(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("1"),
            _position("1"),
            _position("0"),
            _position("0"),
        ],
        opening_orders=[
            opening,
            _order(
                client_id=CREATE_ID,
                exchange_id=CREATE_EXCHANGE_ID,
                side=OrderSide.BUY,
                status=OrderStatus.FILLED,
                filled="1",
                remaining="0",
                resolution=(Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP),
            ),
        ],
        close_order=_order(
            client_id=CLOSE_ID,
            exchange_id=CLOSE_EXCHANGE_ID,
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            filled="1",
            remaining="0",
            resolution=(Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP),
        ),
        failures={"close": {1}, "resolve_close": {1}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("close") == 1
    assert port.calls.count("resolve_close") == 2
    assert port.calls.count("resolve_opening") == 1
    assert port.calls.count("zero_orders") == 3
    assert port.calls.count("margin") == 2
    serialized = (tmp_path / "terminal.json").read_text(encoding="utf-8")
    assert "private orchestrator delegate exception" not in serialized
    for private in (PREVIEW_ID, PORTFOLIO_ID, CREATE_ID, CLOSE_ID):
        assert private not in serialized


def test_final_position_failure_still_attempts_open_order_and_margin_proofs(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
    )
    close = _order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[
            _position("0"),
            _position("1"),
            _position("1"),
            _position("0"),
            _position("0"),
        ],
        opening_orders=[
            opening,
            _order(
                client_id=CREATE_ID,
                exchange_id=CREATE_EXCHANGE_ID,
                side=OrderSide.BUY,
                status=OrderStatus.FILLED,
                filled="1",
                remaining="0",
                resolution=(Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP),
            ),
        ],
        close_order=close,
        failures={"position": {4}},
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert port.calls.count("position") == 6
    assert port.calls.count("zero_orders") == 4
    assert port.calls.count("margin") == 3
    assert port.calls.count("close") == 1
    assert port.calls.count("resolve_close") == 1


def test_activation_path_or_policy_drift_blocks_before_claim_or_port(
    tmp_path: Path,
) -> None:
    plan = _plan()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_rejected",
        ),
        positions=[],
        opening_orders=[],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)
    manifest = activation.seal.manifest
    assert isinstance(manifest, _FakeManifest)
    manifest.read_path = tmp_path / "redirected-reads.jsonl"

    with pytest.raises(Slice3OrchestrationError, match="activation_binding"):
        orchestrator.run(
            plan=plan,
            activation_store=activation,  # type: ignore[arg-type]
            expected_activation_manifest_sha256=ACTIVATION_HASH,
        )

    assert not (tmp_path / "actions.jsonl").exists()
    assert not (tmp_path / "terminal.json").exists()
    assert port.calls == []


def test_activation_live_policy_hash_drift_blocks_before_terminal_reservation(
    tmp_path: Path,
) -> None:
    plan = _plan()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_rejected",
        ),
        positions=[],
        opening_orders=[],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)
    manifest = activation.seal.manifest
    assert isinstance(manifest, _FakeManifest)
    manifest.slice3_live_policy_sha256 = "f" * 64

    with pytest.raises(Slice3OrchestrationError, match="activation_binding"):
        orchestrator.run(
            plan=plan,
            activation_store=activation,  # type: ignore[arg-type]
            expected_activation_manifest_sha256=ACTIVATION_HASH,
        )

    assert not (tmp_path / "actions.jsonl").exists()
    assert not (tmp_path / "reads.jsonl").exists()
    assert not (tmp_path / "terminal.json").exists()
    assert port.calls == []


@pytest.mark.parametrize(
    "manifest_field",
    [
        "authorization_text_sha256",
        "core_module_sha256",
        "port_module_sha256",
        "orchestrator_module_sha256",
        "admission_module_sha256",
        "admission_chain_sha256",
        "admission_record_sha256",
        "admission_artifact_file_sha256",
        "action_journal_schema_sha256",
        "read_journal_schema_sha256",
        "terminal_evidence_schema_sha256",
    ],
)
def test_activation_auth_module_or_schema_tamper_blocks_before_any_attempt(
    tmp_path: Path,
    manifest_field: str,
) -> None:
    plan = _plan()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_rejected",
        ),
        positions=[],
        opening_orders=[],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)
    manifest = activation.seal.manifest
    assert isinstance(manifest, _FakeManifest)
    setattr(manifest, manifest_field, "f" * 64)

    with pytest.raises(Slice3OrchestrationError, match="activation_binding"):
        orchestrator.run(
            plan=plan,
            activation_store=activation,  # type: ignore[arg-type]
            expected_activation_manifest_sha256=ACTIVATION_HASH,
        )

    assert not (tmp_path / "actions.jsonl").exists()
    assert not (tmp_path / "reads.jsonl").exists()
    assert not (tmp_path / "terminal.json").exists()
    assert port.calls == []


@pytest.mark.parametrize(
    "seal_field",
    ["chain_sha256", "record_sha256", "artifact_file_sha256"],
)
def test_runtime_admission_seal_tamper_blocks_before_any_attempt(
    tmp_path: Path,
    seal_field: str,
) -> None:
    plan = _plan()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_rejected",
        ),
        positions=[],
        opening_orders=[],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)
    activation.admission_store.seal = replace(
        activation.admission_store.seal,
        **{seal_field: "f" * 64},
    )

    with pytest.raises(Slice3OrchestrationError, match="activation_binding"):
        orchestrator.run(
            plan=plan,
            activation_store=activation,  # type: ignore[arg-type]
            expected_activation_manifest_sha256=ACTIVATION_HASH,
        )

    assert activation.admission_store.calls == 1
    assert not (tmp_path / "actions.jsonl").exists()
    assert not (tmp_path / "reads.jsonl").exists()
    assert not (tmp_path / "terminal.json").exists()
    assert port.calls == []


def test_redirected_admission_store_blocks_before_any_attempt(
    tmp_path: Path,
) -> None:
    plan = _plan()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_rejected",
        ),
        positions=[],
        opening_orders=[],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)
    activation.admission_store.path = tmp_path / "redirected-admission.json"

    with pytest.raises(Slice3OrchestrationError, match="activation_binding"):
        orchestrator.run(
            plan=plan,
            activation_store=activation,  # type: ignore[arg-type]
            expected_activation_manifest_sha256=ACTIVATION_HASH,
        )

    assert activation.admission_store.calls == 0
    assert not (tmp_path / "actions.jsonl").exists()
    assert not (tmp_path / "terminal.json").exists()
    assert port.calls == []


def test_all_action_claims_exist_before_single_port_construction(
    tmp_path: Path,
) -> None:
    plan = _plan()
    action_path = tmp_path / "actions.jsonl"
    read_path = tmp_path / "reads.jsonl"
    terminal_path = tmp_path / "terminal.json"
    action_store = FileSlice3ActionClaimStore(action_path)
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_rejected",
        ),
        positions=[_position("0"), _position("0")],
        opening_orders=[],
    )
    constructions = 0

    def construct(_seal: Slice3ActivationSeal) -> _FakePort:
        nonlocal constructions
        constructions += 1
        records = action_store.read_all()
        for action in Slice3ActionKind:
            matching = [record for record in records if record.action is action]
            assert matching[-1].event is Slice3ClaimEvent.CLAIM
        return port

    activation = _activation(
        plan,
        action_path=action_path,
        read_path=read_path,
        terminal_path=terminal_path,
    )
    orchestrator = Slice3TerminalRoundtripOrchestrator(
        action_store=action_store,
        read_journal=FileSlice3ReadJournal(read_path),
        terminal_store=FileSlice3TerminalArtifactStore(terminal_path),
        port_factory=construct,
        now_provider=lambda: NOW,
        admission_store=activation.admission_store,
    )

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert constructions == 1


def test_terminal_artifact_is_canonical_owner_only_and_read_journaled(
    tmp_path: Path,
) -> None:
    plan = _plan()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FAILED,
        filled="0",
        remaining="1",
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=CREATE_EXCHANGE_ID,
        ),
        positions=[_position("0"), _position("0"), _position("0")],
        opening_orders=[opening],
    )
    orchestrator, activation = _orchestrator(tmp_path, plan, port)

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    terminal_path = tmp_path / "terminal.json"
    assert stat.S_IMODE(terminal_path.stat().st_mode) == 0o400
    assert terminal_path.stat().st_uid == os.geteuid()
    lines = terminal_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert line == json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
    read_records = FileSlice3ReadJournal(tmp_path / "reads.jsonl").read_all()
    assert len(read_records) == 16
    assert all(
        sum(record.slot is candidate.slot for record in read_records) == 2
        for candidate in read_records
    )


def test_concurrent_invocation_constructs_only_one_port(tmp_path: Path) -> None:
    plan = _plan()
    action_path = tmp_path / "actions.jsonl"
    read_path = tmp_path / "reads.jsonl"
    terminal_path = tmp_path / "terminal.json"
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_rejected",
        ),
        positions=[_position("0"), _position("0")],
        opening_orders=[],
    )
    construction_lock = threading.Lock()
    constructions = 0

    def construct(_seal: Slice3ActivationSeal) -> _FakePort:
        nonlocal constructions
        with construction_lock:
            constructions += 1
        return port

    def new_orchestrator() -> Slice3TerminalRoundtripOrchestrator:
        return Slice3TerminalRoundtripOrchestrator(
            action_store=FileSlice3ActionClaimStore(action_path),
            read_journal=FileSlice3ReadJournal(read_path),
            terminal_store=FileSlice3TerminalArtifactStore(terminal_path),
            port_factory=construct,
            now_provider=lambda: NOW,
            admission_store=activation.admission_store,
        )

    activation = _activation(
        plan,
        action_path=action_path,
        read_path=read_path,
        terminal_path=terminal_path,
    )
    barrier = threading.Barrier(2)

    def invoke(orchestrator: Slice3TerminalRoundtripOrchestrator) -> str:
        barrier.wait()
        try:
            result = orchestrator.run(
                plan=plan,
                activation_store=activation,  # type: ignore[arg-type]
                expected_activation_manifest_sha256=ACTIVATION_HASH,
            )
        except Slice3OrchestrationError:
            return "blocked"
        return result.status.value

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(invoke, [new_orchestrator(), new_orchestrator()]))

    assert outcomes.count(Slice3OrchestrationStatus.RESTORED_BASELINE.value) == 1
    assert outcomes.count("blocked") == 1
    assert constructions == 1
    assert port.calls.count("create") == 1


def test_interrupted_attempt_is_terminalized_without_port_or_delegate_call(
    tmp_path: Path,
) -> None:
    plan = _plan()
    action_path = tmp_path / "actions.jsonl"
    read_path = tmp_path / "reads.jsonl"
    terminal_path = tmp_path / "terminal.json"
    action_store = FileSlice3ActionClaimStore(action_path)
    read_journal = FileSlice3ReadJournal(read_path)
    terminal_store = FileSlice3TerminalArtifactStore(terminal_path)
    activation = _activation(
        plan,
        action_path=action_path,
        read_path=read_path,
        terminal_path=terminal_path,
    )
    interrupted_lease = terminal_store.reserve(
        plan_sha256=plan.plan_sha256,
        activation_manifest_sha256=ACTIVATION_HASH,
        now=NOW,
    )
    Slice3MutationGate(action_store).reserve_action_claims(plan, now=NOW)
    read_journal.reserve(
        plan_sha256=plan.plan_sha256,
        slot=Slice3ReadSlot.PRE_CREATE_POSITION,
        declaration=slice3_read_declaration(Slice3ReadSlot.PRE_CREATE_POSITION),
    )
    interrupted_lease.release()
    constructions = 0

    def construct(_seal: Slice3ActivationSeal) -> _FakePort:
        nonlocal constructions
        constructions += 1
        raise AssertionError("recovery_must_not_construct_port")

    orchestrator = Slice3TerminalRoundtripOrchestrator(
        action_store=action_store,
        read_journal=read_journal,
        terminal_store=terminal_store,
        port_factory=construct,
        now_provider=lambda: NOW,
        admission_store=activation.admission_store,
    )

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert result.reason_code == "interrupted_attempt_recovered"
    assert constructions == 0
    create_record = action_store.inspect(plan.action_claim(Slice3ActionKind.CREATE))
    assert create_record is not None
    assert create_record.event is Slice3ClaimEvent.RETIRED
    recovered_read = read_journal.inspect(
        plan_sha256=plan.plan_sha256,
        slot=Slice3ReadSlot.PRE_CREATE_POSITION,
    )
    assert recovered_read is not None
    assert recovered_read.outcome is Slice3ReadOutcome.FAILED
    assert stat.S_IMODE(terminal_path.stat().st_mode) == 0o400


def test_interrupted_create_boundary_resumes_only_finite_risk_off_path(
    tmp_path: Path,
) -> None:
    plan = _plan()
    recovery_now = NOW + timedelta(minutes=6)
    assert recovery_now > plan.expires_at
    assert recovery_now < plan.risk_off_expires_at
    action_path = tmp_path / "actions.jsonl"
    read_path = tmp_path / "reads.jsonl"
    terminal_path = tmp_path / "terminal.json"
    action_store = FileSlice3ActionClaimStore(action_path)
    read_journal = FileSlice3ReadJournal(read_path)
    terminal_store = FileSlice3TerminalArtifactStore(terminal_path)
    activation = _activation(
        plan,
        action_path=action_path,
        read_path=read_path,
        terminal_path=terminal_path,
    )
    interrupted_lease = terminal_store.reserve(
        plan_sha256=plan.plan_sha256,
        activation_manifest_sha256=ACTIVATION_HASH,
        now=NOW,
    )
    Slice3MutationGate(action_store).reserve_action_claims(plan, now=NOW)
    action_store.mark_exchange_boundary(plan.action_claim(Slice3ActionKind.CREATE))
    interrupted_lease.release()
    opening = _order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        resolution=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
        observed_at=recovery_now,
    )
    close = _order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        observed_at=recovery_now,
    )
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.UNKNOWN,
            reason_code="create_outcome_unknown",
        ),
        positions=[
            _position("1", observed_at=recovery_now),
            _position("0", observed_at=recovery_now),
        ],
        opening_orders=[opening],
        close_order=close,
    )
    constructions = 0

    def construct(_seal: Slice3ActivationSeal) -> _FakePort:
        nonlocal constructions
        constructions += 1
        return port

    orchestrator = Slice3TerminalRoundtripOrchestrator(
        action_store=action_store,
        read_journal=read_journal,
        terminal_store=terminal_store,
        port_factory=construct,
        now_provider=lambda: recovery_now,
        admission_store=activation.admission_store,
    )

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.RESTORED_BASELINE
    assert constructions == 1
    assert port.calls.count("create") == 0
    assert port.calls.count("resolve_opening") == 1
    assert port.calls.count("close") == 1
    assert stat.S_IMODE(terminal_path.stat().st_mode) == 0o400
    consumed_slots = {
        record.slot
        for record in read_journal.read_all()
        if record.event is Slice3ReadRecordEvent.CONSUMED
    }
    assert consumed_slots == {
        Slice3ReadSlot.RECOVERY_OPENING_ORDER_BY_CLIENT_ID,
        Slice3ReadSlot.RECOVERY_POSITION,
        Slice3ReadSlot.RECOVERY_MARKET,
        Slice3ReadSlot.RECOVERY_PRE_CLOSE_OPEN_ORDERS,
        Slice3ReadSlot.RECOVERY_CLOSE_ORDER_BY_CLIENT_ID,
        Slice3ReadSlot.RECOVERY_FINAL_POSITION,
        Slice3ReadSlot.RECOVERY_FINAL_OPEN_ORDERS,
        Slice3ReadSlot.RECOVERY_FINAL_MARGIN,
    }


def test_fresh_initial_execution_cannot_create_after_normal_expiry(
    tmp_path: Path,
) -> None:
    plan = _plan()
    expired_create_at = plan.expires_at + timedelta(microseconds=1)
    assert expired_create_at < plan.risk_off_expires_at
    action_path = tmp_path / "actions.jsonl"
    read_path = tmp_path / "reads.jsonl"
    terminal_path = tmp_path / "terminal.json"
    activation = _activation(
        plan,
        action_path=action_path,
        read_path=read_path,
        terminal_path=terminal_path,
    )
    constructions = 0

    def construct(_seal: Slice3ActivationSeal) -> _FakePort:
        nonlocal constructions
        constructions += 1
        raise AssertionError("expired_fresh_create_must_not_construct_port")

    orchestrator = Slice3TerminalRoundtripOrchestrator(
        action_store=FileSlice3ActionClaimStore(action_path),
        read_journal=FileSlice3ReadJournal(read_path),
        terminal_store=FileSlice3TerminalArtifactStore(terminal_path),
        port_factory=construct,
        now_provider=lambda: expired_create_at,
        admission_store=activation.admission_store,
    )

    with pytest.raises(Slice3OrchestrationError, match="activation_binding"):
        orchestrator.run(
            plan=plan,
            activation_store=activation,  # type: ignore[arg-type]
            expected_activation_manifest_sha256=ACTIVATION_HASH,
        )

    assert activation.admission_store.calls == 1
    assert constructions == 0
    assert not action_path.exists()
    assert not read_path.exists()
    assert not terminal_path.exists()


def test_interrupted_recovery_rejects_at_exact_risk_off_expiry(
    tmp_path: Path,
) -> None:
    plan = _plan()
    action_path = tmp_path / "actions.jsonl"
    read_path = tmp_path / "reads.jsonl"
    terminal_path = tmp_path / "terminal.json"
    action_store = FileSlice3ActionClaimStore(action_path)
    terminal_store = FileSlice3TerminalArtifactStore(terminal_path)
    activation = _activation(
        plan,
        action_path=action_path,
        read_path=read_path,
        terminal_path=terminal_path,
    )
    interrupted_lease = terminal_store.reserve(
        plan_sha256=plan.plan_sha256,
        activation_manifest_sha256=ACTIVATION_HASH,
        now=NOW,
    )
    Slice3MutationGate(action_store).reserve_action_claims(plan, now=NOW)
    action_store.mark_exchange_boundary(plan.action_claim(Slice3ActionKind.CREATE))
    interrupted_lease.release()
    action_bytes = action_path.read_bytes()
    terminal_bytes = terminal_path.read_bytes()
    constructions = 0

    def construct(_seal: Slice3ActivationSeal) -> _FakePort:
        nonlocal constructions
        constructions += 1
        raise AssertionError("expired_risk_off_must_not_construct_port")

    orchestrator = Slice3TerminalRoundtripOrchestrator(
        action_store=action_store,
        read_journal=FileSlice3ReadJournal(read_path),
        terminal_store=terminal_store,
        port_factory=construct,
        now_provider=lambda: plan.risk_off_expires_at,
        admission_store=activation.admission_store,
    )

    with pytest.raises(Slice3OrchestrationError, match="activation_binding"):
        orchestrator.run(
            plan=plan,
            activation_store=activation,  # type: ignore[arg-type]
            expected_activation_manifest_sha256=ACTIVATION_HASH,
        )

    assert activation.calls == 0
    assert activation.admission_store.calls == 0
    assert constructions == 0
    assert action_path.read_bytes() == action_bytes
    assert terminal_path.read_bytes() == terminal_bytes
    assert not read_path.exists()


def test_crash_left_recovery_slot_halts_without_delegate_or_second_pass(
    tmp_path: Path,
) -> None:
    plan = _plan()
    action_path = tmp_path / "actions.jsonl"
    read_path = tmp_path / "reads.jsonl"
    terminal_path = tmp_path / "terminal.json"
    action_store = FileSlice3ActionClaimStore(action_path)
    read_journal = FileSlice3ReadJournal(read_path)
    terminal_store = FileSlice3TerminalArtifactStore(terminal_path)
    activation = _activation(
        plan,
        action_path=action_path,
        read_path=read_path,
        terminal_path=terminal_path,
    )
    lease = terminal_store.reserve(
        plan_sha256=plan.plan_sha256,
        activation_manifest_sha256=ACTIVATION_HASH,
        now=NOW,
    )
    Slice3MutationGate(action_store).reserve_action_claims(plan, now=NOW)
    action_store.mark_exchange_boundary(plan.action_claim(Slice3ActionKind.CREATE))
    read_journal.reserve(
        plan_sha256=plan.plan_sha256,
        slot=Slice3ReadSlot.RECOVERY_OPENING_ORDER_BY_CLIENT_ID,
        declaration=slice3_read_declaration(
            Slice3ReadSlot.RECOVERY_OPENING_ORDER_BY_CLIENT_ID
        ),
    )
    lease.release()
    port = _FakePort(
        create_result=Slice3MutationResult(
            outcome=Slice3MutationOutcome.UNKNOWN,
            reason_code="create_outcome_unknown",
        ),
        positions=[_position("0")],
        opening_orders=[],
    )
    constructions = 0

    def construct(_seal: Slice3ActivationSeal) -> _FakePort:
        nonlocal constructions
        constructions += 1
        return port

    orchestrator = Slice3TerminalRoundtripOrchestrator(
        action_store=action_store,
        read_journal=read_journal,
        terminal_store=terminal_store,
        port_factory=construct,
        now_provider=lambda: NOW,
        admission_store=activation.admission_store,
    )

    result = orchestrator.run(
        plan=plan,
        activation_store=activation,  # type: ignore[arg-type]
        expected_activation_manifest_sha256=ACTIVATION_HASH,
    )

    assert result.status is Slice3OrchestrationStatus.HALTED
    assert result.reason_code == "recovery_create_lookup_failed"
    assert constructions == 1
    assert port.calls.count("resolve_opening") == 0
    recovered = read_journal.inspect(
        plan_sha256=plan.plan_sha256,
        slot=Slice3ReadSlot.RECOVERY_OPENING_ORDER_BY_CLIENT_ID,
    )
    assert recovered is not None
    assert recovered.outcome is Slice3ReadOutcome.FAILED
    with pytest.raises(Slice3OrchestrationError, match="attempt_consumed"):
        orchestrator.run(
            plan=plan,
            activation_store=activation,  # type: ignore[arg-type]
            expected_activation_manifest_sha256=ACTIVATION_HASH,
        )
    assert constructions == 1
