"""Synthetic orchestration contract for the one-child Spot Automation adapter.

These tests deliberately inject every boundary that could otherwise reach
Coinbase.  The PostgreSQL adapter remains responsible for ordering the durable
claim/finalize transitions around the canonical Admin command service.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from coinbase.rest.types.orders_types import PreviewOrderResponse
from requests import Response
from requests.exceptions import (
    HTTPError,
    JSONDecodeError as RequestsJSONDecodeError,
    Timeout,
)

from application.admin_api.automation_models import (
    AutomationMutationContext,
    AutomationPreviewGatedSingleChildAuthorizationRequest,
    AutomationSingleChildAuthorizationRequest,
    AutomationSingleChildSafeCloseoutRequest,
)
from application.admin_api.command_service import (
    SpotProfileOrderAdmissionCoordinator,
    ValidatedSpotAutomationAdmissionEvidence,
    ValidatedSpotAutomationOwnershipEvidence,
)
from application.admin_api.models import (
    AdminApiCommandResponse,
    AdminLiveAdmissionDecisionEvidence,
    CancelOrderCommand,
    ManualOrderCommand,
)
from application.admin_api.operator_automation import (
    AutomationRepositoryConflict,
    OperatorAutomationService,
    PostgresOperatorAutomationRepositoryAdapter,
    SpotAutomationEligibilityExecutionBundle,
)
from application.admin_api.operator_spot_eligibility import (
    APPROVED_SPOT_ELIGIBILITY_ORDER,
    ApprovedSpotEligibilityCategory,
    SpotEligibilityCycleResult,
    SpotEligibilityReadOutcome,
    derive_spot_eligibility_client_order_id,
)
from application.admin_api.operator_spot_eligibility_reader import (
    SpotEligibilityActiveOrderCatalogAbsenceSnapshot,
    SpotEligibilityExactOrderAbsenceSnapshot,
    SpotEligibilityMarketReferenceSnapshot,
    SpotEligibilityPortfolioBindingSnapshot,
    SpotEligibilityReadSnapshot,
    SpotEligibilityWalletSnapshot,
)
from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
    COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
    COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
    OperatorAutomationDomain,
    OperatorAutomationJobKind,
    OperatorAutomationRunState,
)
from database.operator_automation import (
    AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
    AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
    AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
    AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
    AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    AutomationMutationCommand,
    AutomationRunRecord,
    AutomationSpotEligibilityAttemptRecord,
    AutomationSpotEligibilityCycleRecord,
    AutomationSpotPreviewGatedGoalRecord,
    AutomationSpotRunExecutionRecord,
    AutomationSpotSingleChildPlanRecord,
    AutomationStoreMutation,
    AutomationStoreConflict,
)


NOW = datetime.now(timezone.utc)
FRESH_UNTIL = NOW + timedelta(minutes=5)
NOW_TEXT = NOW.isoformat()
FRESH_UNTIL_TEXT = FRESH_UNTIL.isoformat()
DEFINITION_ID = "f15c025a-8b1c-412a-8be6-88848d1bc5e2"
RUN_ID = "7c8ca6b1-f3cf-4a02-b65b-d16966a39e28"
PORTFOLIO_ID = "483d1403-5d4d-4ae1-9084-ae2b080902b7"
PORTFOLIO_SHA256 = hashlib.sha256(PORTFOLIO_ID.encode("utf-8")).hexdigest()
PLAN_SHA256 = "a" * 64
CLIENT_ORDER_ID = derive_spot_eligibility_client_order_id(
    run_id=RUN_ID,
    plan_sha256=PLAN_SHA256,
)
AUDIT_ID = "26371b41-f16e-4dad-83cc-946055440c62"
CANCEL_AUDIT_ID = "645c91fe-9186-4207-80a9-2e6a595fc2df"


@pytest.fixture(autouse=True)
def _configured_test_portfolio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PORTFOLIO_ID)


def _context() -> AutomationMutationContext:
    return AutomationMutationContext(
        actor_id="operator-automation-test",
        roles=("trader",),
        idempotency_key="automation-execution-idempotency-1",
        correlation_id="automation-execution-correlation-1",
        operator_intent="authorize_exact_spot_automation_child",
    )


def _authorization_request() -> AutomationSingleChildAuthorizationRequest:
    return AutomationSingleChildAuthorizationRequest(
        confirm_single_child_create=True,
        confirm_final_eligibility_refresh=True,
        confirm_account_wide_active_spot_order_catalog_read=True,
        confirm_unknown_consumes_allowance=True,
        expected_plan_sha256=PLAN_SHA256,
        reason="authorize the exact bounded child",
    )


def _preview_authorization_request(
) -> AutomationPreviewGatedSingleChildAuthorizationRequest:
    return AutomationPreviewGatedSingleChildAuthorizationRequest(
        confirm_single_preview=True,
        confirm_conditional_single_child_create=True,
        confirm_final_eligibility_refresh=True,
        confirm_account_wide_active_spot_order_catalog_read=True,
        confirm_preview_unknown_consumes_allowance=True,
        confirm_create_unknown_consumes_allowance=True,
        expected_plan_sha256=PLAN_SHA256,
        reason="preview and conditionally create the exact bounded child",
    )


def _closeout_request() -> AutomationSingleChildSafeCloseoutRequest:
    return AutomationSingleChildSafeCloseoutRequest(
        confirm_exact_child_safe_closeout_cancel=True,
        confirm_unknown_consumes_allowance=True,
        expected_plan_sha256=PLAN_SHA256,
        reason="safely close the exact bounded child",
    )


def _run_record(
    *,
    state: OperatorAutomationRunState = (
        OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
    ),
    diagnostic_code: str = "awaiting_operator_authorization",
    client_order_id: str | None = None,
    live_attempt_consumed: bool = False,
    coinbase_api_call_count: int = 0,
    create_call_count: int = 0,
    cancel_call_count: int = 0,
) -> AutomationRunRecord:
    return AutomationRunRecord(
        run_id=RUN_ID,
        definition_id=DEFINITION_ID,
        domain=OperatorAutomationDomain.SPOT,
        job_kind=OperatorAutomationJobKind.SPOT_CAMPAIGN,
        state=state,
        diagnostic_code=diagnostic_code,
        audit_id=AUDIT_ID,
        correlation_id=_context().correlation_id,
        client_order_id=client_order_id,
        live_attempt_consumed=live_attempt_consumed,
        coinbase_api_call_count=coinbase_api_call_count,
        create_call_count=create_call_count,
        cancel_call_count=cancel_call_count,
        claimed_at=NOW_TEXT,
        updated_at=NOW_TEXT,
        definition_revision=1,
    )


def _plan_record() -> AutomationSpotSingleChildPlanRecord:
    return AutomationSpotSingleChildPlanRecord(
        definition_id=DEFINITION_ID,
        definition_revision=1,
        portfolio_id_sha256=PORTFOLIO_SHA256,
        product_id="BTC-USDC",
        side="BUY",
        base_size="0.00001",
        limit_price="50000",
        submitted_notional_usdc="0.5",
        possible_execution_notional_usdc="0.5",
        # PostgreSQL NUMERIC readback is value-canonical rather than
        # presentation-canonical; the runtime must compare Decimal values.
        max_submitted_notional_usdc="3.1",
        max_possible_execution_notional_usdc="1",
        post_only=False,
        plan_sha256=PLAN_SHA256,
        audit_id=AUDIT_ID,
        correlation_id=_context().correlation_id,
        created_at=NOW_TEXT,
    )


def _cycle_result() -> SpotEligibilityCycleResult:
    return SpotEligibilityCycleResult(
        cycle_number=1,
        outcome=SpotEligibilityReadOutcome.SUCCEEDED,
        eligible=True,
        attempted_categories=APPROVED_SPOT_ELIGIBILITY_ORDER,
        completed_categories=APPROVED_SPOT_ELIGIBILITY_ORDER,
        logical_call_count=len(APPROVED_SPOT_ELIGIBILITY_ORDER),
        coinbase_api_call_count=len(APPROVED_SPOT_ELIGIBILITY_ORDER),
        call_count_exact=True,
        fresh_until=FRESH_UNTIL,
        client_order_id=CLIENT_ORDER_ID,
        diagnostic_code="automation_spot_eligibility_cycle_succeeded",
        replayed=False,
    )


def _read_snapshot(
    *,
    market_source: str = "coinbase_rest_best_bid",
    best_bid: str = "49999",
    best_ask: str = "50000",
) -> SpotEligibilityReadSnapshot:
    return SpotEligibilityReadSnapshot(
        cycle_number=1,
        plan_sha256=PLAN_SHA256,
        portfolio=SpotEligibilityPortfolioBindingSnapshot(
            retail_portfolio_id=PORTFOLIO_ID,
            portfolio_id_sha256=PORTFOLIO_SHA256,
            label="Test",
            portfolio_type="CONSUMER",
            can_view=True,
            can_trade=True,
        ),
        wallets={
            "BTC": SpotEligibilityWalletSnapshot(
                currency="BTC",
                available_balance=Decimal("1"),
                total_balance=Decimal("1"),
            ),
            "USDC": SpotEligibilityWalletSnapshot(
                currency="USDC",
                available_balance=Decimal("10"),
                total_balance=Decimal("10"),
            ),
        },
        market_reference=SpotEligibilityMarketReferenceSnapshot(
            product_id="BTC-USDC",
            best_bid=Decimal(best_bid),
            best_ask=Decimal(best_ask),
            observed_at=NOW,
            source=market_source,
        ),
        exact_order_absence=SpotEligibilityExactOrderAbsenceSnapshot(
            client_order_id=CLIENT_ORDER_ID,
            product_id="BTC-USDC",
            page_count=1,
            evidence_sha256="d" * 64,
        ),
        active_order_catalog_absence=(
            SpotEligibilityActiveOrderCatalogAbsenceSnapshot(
                portfolio_id_sha256=PORTFOLIO_SHA256,
                product_type="SPOT",
                page_count=1,
                evidence_sha256="d" * 64,
            )
        ),
    )


class _ExecutionRepository:
    """In-memory fake for durable ordering only; it performs no I/O."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.control_posture = "ACTIVE"
        self.current_run = _run_record()
        self.plan = _plan_record()
        self.execution: AutomationSpotRunExecutionRecord | None = None
        self.cycles: tuple[AutomationSpotEligibilityCycleRecord, ...] = ()
        self.attempts: tuple[AutomationSpotEligibilityAttemptRecord, ...] = ()
        self.start_create_calls: list[dict[str, Any]] = []
        self.finalize_create_calls: list[dict[str, Any]] = []
        self.start_cancel_calls: list[dict[str, Any]] = []
        self.finalize_cancel_calls: list[dict[str, Any]] = []
        self.goal_key = AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY
        self.preview_goal = AutomationSpotPreviewGatedGoalRecord(
            goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
            definition_id=DEFINITION_ID,
            bound_run_id=None,
            client_order_id=None,
            eligibility_cycle=None,
            plan_sha256=None,
            portfolio_id_sha256=None,
            product_id=None,
            preview_allowance_consumed=False,
            preview_outcome=None,
            preview_failure_class=None,
            preview_rejection_code=None,
            preview_warning_present=None,
            preview_id_sha256=None,
            preview_call_count=None,
            preview_call_count_exact=False,
            create_allowance_consumed=False,
            create_outcome=None,
            cancel_allowance_consumed=False,
            cancel_outcome=None,
            updated_at=NOW_TEXT,
        )
        self.start_preview_calls: list[dict[str, Any]] = []
        self.finalize_preview_calls: list[dict[str, Any]] = []

    def get_spot_goal_key_for_run(self, run_id: str) -> str:
        assert run_id == RUN_ID
        return self.goal_key

    def get_spot_preview_gated_goal(
        self,
        *,
        goal_key: str = AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ) -> AutomationSpotPreviewGatedGoalRecord:
        assert goal_key == self.goal_key
        return self.preview_goal

    def start_spot_preview_invocation(
        self,
        run_id: str,
        *,
        eligibility_cycle: int,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotPreviewGatedGoalRecord]:
        assert self.goal_key != AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY
        assert run_id == RUN_ID
        assert eligibility_cycle == 1
        self.events.append("start_preview")
        self.start_preview_calls.append(
            {"eligibility_cycle": eligibility_cycle, "command": command}
        )
        self.preview_goal = replace(
            self.preview_goal,
            bound_run_id=RUN_ID,
            client_order_id=CLIENT_ORDER_ID,
            eligibility_cycle=1,
            plan_sha256=PLAN_SHA256,
            portfolio_id_sha256=PORTFOLIO_SHA256,
            product_id="BTC-USDC",
            preview_allowance_consumed=True,
        )
        self.current_run = replace(
            self.current_run,
            diagnostic_code="automation_spot_preview_invocation_started",
            client_order_id=CLIENT_ORDER_ID,
            live_attempt_consumed=True,
        )
        return AutomationStoreMutation(
            self.preview_goal,
            AUDIT_ID,
            command.correlation_id,
        )

    def finalize_spot_preview_invocation(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> AutomationStoreMutation[AutomationSpotPreviewGatedGoalRecord]:
        assert run_id == RUN_ID
        self.events.append("finalize_preview")
        self.finalize_preview_calls.append(dict(kwargs))
        outcome = str(kwargs["outcome"])
        self.preview_goal = replace(
            self.preview_goal,
            preview_outcome=outcome,
            preview_failure_class=str(kwargs["failure_class"]),
            preview_rejection_code=kwargs["rejection_code"],
            preview_warning_present=bool(kwargs["warning_present"]),
            preview_id_sha256=kwargs["preview_id_sha256"],
            preview_call_count=kwargs["preview_call_count"],
            preview_call_count_exact=bool(kwargs["call_count_exact"]),
        )
        if outcome == "ACCEPTED":
            state = OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
            diagnostic = "automation_spot_preview_accepted_create_ready"
        elif outcome == "REJECTED":
            state = OperatorAutomationRunState.TERMINAL
            diagnostic = "automation_spot_preview_rejected"
        else:
            state = OperatorAutomationRunState.UNKNOWN_CONSUMED
            diagnostic = "automation_spot_preview_unknown_consumed"
        self.current_run = replace(
            self.current_run,
            state=state,
            diagnostic_code=diagnostic,
            coinbase_api_call_count=(
                int(kwargs["preview_call_count"] or 0)
            ),
        )
        command = kwargs["command"]
        return AutomationStoreMutation(
            self.preview_goal,
            AUDIT_ID,
            command.correlation_id,
        )

    def get_control_posture(self) -> SimpleNamespace:
        return SimpleNamespace(posture=self.control_posture)

    def get_run(self, run_id: str) -> AutomationRunRecord | None:
        return self.current_run if run_id == RUN_ID else None

    def get_spot_single_child_plan(
        self,
        definition_id: str,
        definition_revision: int,
    ) -> AutomationSpotSingleChildPlanRecord | None:
        if (definition_id, definition_revision) != (DEFINITION_ID, 1):
            return None
        return self.plan

    def get_spot_run_execution(
        self,
        run_id: str,
    ) -> AutomationSpotRunExecutionRecord | None:
        return self.execution if run_id == RUN_ID else None

    def list_spot_eligibility_attempts(
        self,
        run_id: str,
        cycle_number: int | None = None,
    ) -> tuple[AutomationSpotEligibilityAttemptRecord, ...]:
        assert run_id == RUN_ID
        if cycle_number is None:
            return self.attempts
        return tuple(
            attempt
            for attempt in self.attempts
            if attempt.cycle_number == cycle_number
        )

    def list_spot_eligibility_cycles(
        self,
        *,
        goal_key: str = AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
    ) -> tuple[AutomationSpotEligibilityCycleRecord, ...]:
        assert goal_key == self.goal_key
        return self.cycles

    def install_fresh_cycle(self, result: SpotEligibilityCycleResult) -> None:
        assert result.replayed is False
        self.cycles = (
            AutomationSpotEligibilityCycleRecord(
                goal_key=(
                    self.goal_key
                ),
                cycle_number=result.cycle_number,
                policy_revision=(
                    5
                    if self.goal_key
                    == AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY
                    else 4
                    if self.goal_key == AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY
                    else 3
                    if self.goal_key == AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY
                    else 2
                ),
                run_id=RUN_ID,
                definition_id=DEFINITION_ID,
                definition_revision=1,
                plan_sha256=PLAN_SHA256,
                portfolio_id_sha256=PORTFOLIO_SHA256,
                product_id="BTC-USDC",
                client_order_id=CLIENT_ORDER_ID,
                state="SUCCEEDED",
                coinbase_api_call_count=result.coinbase_api_call_count,
                call_count_exact=True,
                fresh_until=FRESH_UNTIL_TEXT,
                diagnostic_code=result.diagnostic_code,
                audit_id=AUDIT_ID,
                correlation_id=_context().correlation_id,
                started_at=NOW_TEXT,
                finalized_at=NOW_TEXT,
            ),
        )
        self.attempts = tuple(
            AutomationSpotEligibilityAttemptRecord(
                run_id=RUN_ID,
                cycle_number=1,
                category=category.value,
                allowance_consumed=True,
                outcome="SUCCEEDED",
                eligible=True,
                coinbase_api_call_count=1,
                call_count_exact=True,
                observed_at=NOW_TEXT,
                fresh_until=FRESH_UNTIL_TEXT,
                evidence_sha256="d" * 64,
                diagnostic_code=(
                    "automation_spot_eligibility_"
                    f"{category.value.lower()}_succeeded"
                ),
                audit_id=AUDIT_ID,
                correlation_id=_context().correlation_id,
                started_at=NOW_TEXT,
                finalized_at=NOW_TEXT,
                portfolio_id_sha256=(
                    PORTFOLIO_SHA256
                    if category
                    is ApprovedSpotEligibilityCategory.PORTFOLIO_CATALOG
                    else None
                ),
            )
            for category in APPROVED_SPOT_ELIGIBILITY_ORDER
        )

    def audit_spot_source_gate_authorization(
        self,
        run_id: str,
        *,
        expected_plan_sha256: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationRunRecord]:
        assert run_id == RUN_ID
        assert expected_plan_sha256 == PLAN_SHA256
        return AutomationStoreMutation(
            self.current_run,
            AUDIT_ID,
            command.correlation_id,
        )

    def start_spot_create_invocation(
        self,
        run_id: str,
        *,
        eligibility_cycle: int,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotRunExecutionRecord]:
        assert run_id == RUN_ID
        assert eligibility_cycle == 1
        if self.execution is not None:
            if not self.start_create_calls:
                raise AutomationStoreConflict(
                    "automation_spot_create_allowance_consumed"
                )
            original = self.start_create_calls[0]
            if original["command"].idempotency_key != command.idempotency_key:
                raise AutomationStoreConflict(
                    "automation_spot_create_allowance_consumed"
                )
            if (
                original["eligibility_cycle"] != eligibility_cycle
                or original["command"] != command
            ):
                raise AutomationStoreConflict("automation_idempotency_conflict")
            self.start_create_calls.append(
                {
                    "eligibility_cycle": eligibility_cycle,
                    "command": command,
                    "replayed": True,
                }
            )
            return AutomationStoreMutation(
                self.execution,
                AUDIT_ID,
                command.correlation_id,
                True,
            )
        self.events.append("start_create")
        self.start_create_calls.append(
            {
                "eligibility_cycle": eligibility_cycle,
                "command": command,
                "replayed": False,
            }
        )
        if self.goal_key != AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
            assert self.preview_goal.preview_outcome == "ACCEPTED"
            self.preview_goal = replace(
                self.preview_goal,
                create_allowance_consumed=True,
            )
        self.execution = _execution_record(
            policy_revision=(
                5
                if self.goal_key
                == AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY
                else 4
                if self.goal_key == AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY
                else 3
                if self.goal_key == AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY
                else 2
            )
        )
        self.current_run = replace(
            self.current_run,
            state=OperatorAutomationRunState.INVOCATION_STARTED,
            diagnostic_code="automation_spot_create_invocation_started",
            client_order_id=CLIENT_ORDER_ID,
            live_attempt_consumed=True,
        )
        return AutomationStoreMutation(
            self.execution,
            AUDIT_ID,
            command.correlation_id,
        )

    def finalize_spot_create_invocation(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> AutomationStoreMutation[AutomationSpotRunExecutionRecord]:
        assert run_id == RUN_ID
        assert self.execution is not None
        self.events.append("finalize_create")
        self.finalize_create_calls.append(dict(kwargs))
        outcome = str(getattr(kwargs["outcome"], "value", kwargs["outcome"]))
        child_terminal = kwargs["child_terminal"]
        self.execution = replace(
            self.execution,
            create_outcome=outcome,
            create_call_count=kwargs["coinbase_api_call_count"],
            create_call_count_exact=kwargs["call_count_exact"],
            create_read_call_count=kwargs["read_call_count"],
            create_read_call_count_exact=kwargs["read_call_count_exact"],
            child_terminal=child_terminal,
        )
        if self.goal_key != AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
            self.preview_goal = replace(
                self.preview_goal,
                create_outcome=outcome,
            )
        if outcome == "UNKNOWN":
            state = OperatorAutomationRunState.UNKNOWN_CONSUMED
            diagnostic = "automation_spot_create_unknown_consumed"
        elif outcome == "ACCEPTED" and child_terminal is False:
            state = OperatorAutomationRunState.ACTIVE
            diagnostic = "automation_spot_safe_closeout_ready"
        else:
            state = OperatorAutomationRunState.TERMINAL
            diagnostic = "automation_spot_create_terminal"
        self.current_run = replace(
            self.current_run,
            state=state,
            diagnostic_code=diagnostic,
            coinbase_api_call_count=(
                int(kwargs["coinbase_api_call_count"] or 0)
                + int(kwargs["read_call_count"] or 0)
            ),
            create_call_count=int(kwargs["coinbase_api_call_count"] or 0),
        )
        command = kwargs["command"]
        return AutomationStoreMutation(
            self.execution,
            AUDIT_ID,
            command.correlation_id,
        )

    def start_spot_cancel_invocation(
        self,
        run_id: str,
        *,
        client_order_id: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotRunExecutionRecord]:
        assert run_id == RUN_ID
        assert client_order_id == CLIENT_ORDER_ID
        assert self.execution is not None
        if self.execution.cancel_allowance_consumed:
            if not self.start_cancel_calls:
                raise AutomationStoreConflict(
                    "automation_spot_cancel_allowance_consumed"
                )
            original = self.start_cancel_calls[0]
            if original["command"].idempotency_key != command.idempotency_key:
                raise AutomationStoreConflict(
                    "automation_spot_cancel_allowance_consumed"
                )
            if (
                original["client_order_id"] != client_order_id
                or original["command"] != command
            ):
                raise AutomationStoreConflict("automation_idempotency_conflict")
            self.start_cancel_calls.append(
                {
                    "client_order_id": client_order_id,
                    "command": command,
                    "replayed": True,
                }
            )
            return AutomationStoreMutation(
                self.execution,
                AUDIT_ID,
                command.correlation_id,
                True,
            )
        self.events.append("start_cancel")
        self.start_cancel_calls.append(
            {
                "client_order_id": client_order_id,
                "command": command,
                "replayed": False,
            }
        )
        self.execution = replace(
            self.execution,
            cancel_allowance_consumed=True,
        )
        return AutomationStoreMutation(
            self.execution,
            AUDIT_ID,
            command.correlation_id,
        )

    def finalize_spot_cancel_invocation(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> AutomationStoreMutation[AutomationSpotRunExecutionRecord]:
        assert run_id == RUN_ID
        assert self.execution is not None
        self.events.append("finalize_cancel")
        self.finalize_cancel_calls.append(dict(kwargs))
        outcome = str(getattr(kwargs["outcome"], "value", kwargs["outcome"]))
        self.execution = replace(
            self.execution,
            cancel_outcome=outcome,
            cancel_call_count=kwargs["coinbase_api_call_count"],
            cancel_call_count_exact=kwargs["call_count_exact"],
            cancel_read_call_count=kwargs["read_call_count"],
            cancel_read_call_count_exact=kwargs["read_call_count_exact"],
            child_terminal=kwargs["child_terminal"],
        )
        state = (
            OperatorAutomationRunState.UNKNOWN_CONSUMED
            if outcome == "UNKNOWN"
            else OperatorAutomationRunState.TERMINAL
        )
        self.current_run = replace(
            self.current_run,
            state=state,
            diagnostic_code=(
                "automation_spot_safe_closeout_unknown_consumed"
                if outcome == "UNKNOWN"
                else "automation_spot_safe_closeout_accepted_terminal"
            ),
            coinbase_api_call_count=(
                self.current_run.coinbase_api_call_count
                + int(kwargs["coinbase_api_call_count"] or 0)
                + int(kwargs["read_call_count"] or 0)
            ),
            cancel_call_count=int(kwargs["coinbase_api_call_count"] or 0),
            audit_id=CANCEL_AUDIT_ID,
            correlation_id=kwargs["command"].correlation_id,
        )
        command = kwargs["command"]
        return AutomationStoreMutation(
            self.execution,
            CANCEL_AUDIT_ID,
            command.correlation_id,
        )

    def seed_create_success(self) -> None:
        self.install_fresh_cycle(_cycle_result())
        self.execution = replace(
            _execution_record(
                policy_revision=(
                    5
                    if self.goal_key
                    == AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY
                    else 4
                    if self.goal_key == AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY
                    else 3
                    if self.goal_key == AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY
                    else 2
                )
            ),
            create_outcome="ACCEPTED",
            create_call_count=1,
            create_call_count_exact=True,
            create_read_call_count=1,
            create_read_call_count_exact=True,
            child_terminal=False,
        )
        self.current_run = _run_record(
            state=OperatorAutomationRunState.ACTIVE,
            diagnostic_code="automation_spot_safe_closeout_ready",
            client_order_id=CLIENT_ORDER_ID,
            live_attempt_consumed=True,
            coinbase_api_call_count=2,
            create_call_count=1,
        )

    def seed_cancel_success(self) -> None:
        self.seed_create_success()
        assert self.execution is not None
        self.execution = replace(
            self.execution,
            cancel_allowance_consumed=True,
            cancel_outcome="ACCEPTED",
            cancel_call_count=1,
            cancel_call_count_exact=True,
            cancel_read_call_count=2,
            cancel_read_call_count_exact=True,
            child_terminal=True,
        )
        self.current_run = replace(
            self.current_run,
            state=OperatorAutomationRunState.TERMINAL,
            diagnostic_code="automation_spot_safe_closeout_accepted_terminal",
            coinbase_api_call_count=5,
            cancel_call_count=1,
        )


def _execution_record(
    *,
    policy_revision: int = 2,
) -> AutomationSpotRunExecutionRecord:
    return AutomationSpotRunExecutionRecord(
        run_id=RUN_ID,
        policy_revision=policy_revision,
        definition_id=DEFINITION_ID,
        definition_revision=1,
        eligibility_cycle=1,
        plan_sha256=PLAN_SHA256,
        portfolio_id_sha256=PORTFOLIO_SHA256,
        product_id="BTC-USDC",
        client_order_id=CLIENT_ORDER_ID,
        create_allowance_consumed=True,
        create_outcome=None,
        create_call_count=None,
        create_call_count_exact=False,
        create_read_call_count=None,
        create_read_call_count_exact=False,
        cancel_allowance_consumed=False,
        cancel_outcome=None,
        cancel_call_count=None,
        cancel_call_count_exact=False,
        cancel_read_call_count=None,
        cancel_read_call_count_exact=False,
        child_terminal=None,
        audit_id=AUDIT_ID,
        correlation_id=_context().correlation_id,
        created_at=NOW_TEXT,
        updated_at=NOW_TEXT,
    )


class _TrackedProfileCoordinator:
    def __init__(self, events: list[str], lock_root: Path) -> None:
        self.events = events
        self.inner = SpotProfileOrderAdmissionCoordinator(lock_root=lock_root)
        self.active_lease: object | None = None

    @contextmanager
    def claim(self, portfolio_id: str) -> Iterator[object]:
        assert portfolio_id == PORTFOLIO_ID
        self.events.append("lease_enter")
        try:
            with self.inner.claim(portfolio_id) as lease:
                self.active_lease = lease
                try:
                    yield lease
                finally:
                    self.active_lease = None
        finally:
            self.events.append("lease_exit")

    def require_active(self, lease: object) -> None:
        assert lease is self.active_lease
        self.inner.require_active_lease(
            lease,  # type: ignore[arg-type]
            retail_portfolio_id=PORTFOLIO_ID,
        )


class _EligibilityRunner:
    def __init__(
        self,
        repository: _ExecutionRepository,
        coordinator: _TrackedProfileCoordinator,
        events: list[str],
        *,
        mode: str = "eligible",
    ) -> None:
        self.repository = repository
        self.coordinator = coordinator
        self.events = events
        self.mode = mode
        self.calls: list[dict[str, Any]] = []
        self.reader_calls: list[ApprovedSpotEligibilityCategory] = []
        self.completed_phase_keys: set[str] = set()

    def __call__(self, **kwargs: Any) -> SpotAutomationEligibilityExecutionBundle:
        lease = kwargs["lease"]
        self.coordinator.require_active(lease)
        assert kwargs["record"].run_id == RUN_ID
        assert kwargs["plan"].plan_sha256 == PLAN_SHA256
        phase_key = kwargs["context"].idempotency_key
        if phase_key in self.completed_phase_keys:
            raise AutomationRepositoryConflict(
                "automation_spot_fresh_eligibility_required"
            )
        self.events.append("eligibility_cycle")
        self.calls.append(dict(kwargs))
        self.reader_calls.extend(APPROVED_SPOT_ELIGIBILITY_ORDER)
        self.completed_phase_keys.add(phase_key)
        if self.mode == "unknown":
            result = SpotEligibilityCycleResult(
                cycle_number=1,
                outcome=SpotEligibilityReadOutcome.UNKNOWN,
                eligible=False,
                attempted_categories=APPROVED_SPOT_ELIGIBILITY_ORDER[:1],
                completed_categories=(),
                logical_call_count=1,
                coinbase_api_call_count=None,
                call_count_exact=False,
                fresh_until=None,
                client_order_id=CLIENT_ORDER_ID,
                diagnostic_code="automation_spot_eligibility_cycle_unknown",
                replayed=False,
            )
            return SpotAutomationEligibilityExecutionBundle(
                cycle=result,
                snapshot=_read_snapshot(),
                attempts=(),
            )
        assert self.mode == "eligible"
        result = _cycle_result()
        self.repository.install_fresh_cycle(result)
        return SpotAutomationEligibilityExecutionBundle(
            cycle=result,
            snapshot=_read_snapshot(
                market_source=(
                    "coinbase_rest_market_trade_snapshot"
                    if self.repository.goal_key
                    in {
                        AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
                        AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
                        AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
                        AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
                    }
                    else "coinbase_rest_best_bid"
                ),
                best_bid=(
                    "100000"
                    if self.repository.goal_key
                    in {
                        AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
                        AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
                    }
                    else "49999"
                ),
                best_ask=(
                    "100001"
                    if self.repository.goal_key
                    in {
                        AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
                        AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
                    }
                    else "50000"
                ),
            ),
            attempts=self.repository.attempts,
        )


class _ProofChainRecorder:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        command_kind = kwargs["command_kind"]
        assert command_kind in {"manual", "cancel"}
        operation = "CREATE" if command_kind == "manual" else "SAFE_CLOSEOUT"
        self.events.append(
            "proof_create" if command_kind == "manual" else "proof_cancel"
        )
        self.calls.append((operation, dict(kwargs)))
        prefix = "automation" if command_kind == "manual" else "automation-cancel"
        return {
            "required": True,
            "status": "passed",
            "source": "synthetic_typed_proof_stores",
            "approval": {"approval_id": f"{prefix}-approval-proof"},
            "admission_audit": {
                "audit_id": f"{prefix}-admission-proof"
            },
            "cap_guard": {"decision_id": f"{prefix}-cap-proof"},
            "reconciliation_plan": {
                "plan_id": f"{prefix}-reconciliation-proof"
            },
            "live_exchange_submitted": False,
        }


class _LiveAdmissionEvaluator:
    def __init__(
        self, events: list[str], *, admission_mode: str = "allowed"
    ) -> None:
        self.events = events
        self.admission_mode = admission_mode
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> AdminLiveAdmissionDecisionEvidence:
        proof_context = kwargs["proof_context"]
        proof_chain = kwargs["proof_chain"]
        manual = proof_context["service_method"] == "place_manual_order"
        self.events.append("admission_create" if manual else "admission_cancel")
        self.calls.append(dict(kwargs))
        if self.admission_mode == "raise":
            raise RuntimeError("private admission detail must be withheld")
        allowed = self.admission_mode in {"allowed", "mismatched_action"}
        approval = proof_chain["approval"]
        audit = proof_chain["admission_audit"]
        cap = proof_chain["cap_guard"]
        reconciliation = proof_chain["reconciliation_plan"]
        return AdminLiveAdmissionDecisionEvidence(
            status=(
                AdminApiGateStatus.PASSED
                if allowed
                else AdminApiGateStatus.BLOCKED
            ),
            allowed=allowed,
            route=str(proof_context["route"]),
            method=str(proof_context["method"]),
            module_id=str(proof_context["module_id"]),
            identity_key=str(proof_context["identity_key"]),
            identity_value=str(proof_context["identity_value"]),
            action_class=(
                AdminApiActionClass.LIVE_EXCHANGE_CANCEL
                if self.admission_mode == "mismatched_action"
                else AdminApiActionClass(str(proof_context["action_class"]))
            ),
            required_permission=AdminApiPermission(
                str(proof_context["required_permission"])
            ),
            service_method=str(proof_context["service_method"]),
            actor_id=str(proof_context["actor_id"]),
            idempotency_key=str(proof_context["command_idempotency_key"]),
            operator_intent=str(proof_context["operator_intent"]),
            payload_hash=str(proof_context["payload_hash"]),
            approval_snapshot_present=True,
            approval_snapshot_id=str(approval["approval_id"]),
            approval_snapshot_source="synthetic_typed_store",
            admission_audit_present=True,
            admission_audit_id=str(audit["audit_id"]),
            admission_audit_source="synthetic_typed_store",
            cap_guard_present=True,
            cap_guard_decision_id=str(cap["decision_id"]),
            cap_guard_source="synthetic_typed_store",
            reconciliation_plan_present=True,
            reconciliation_plan_id=str(reconciliation["plan_id"]),
            reconciliation_plan_source="synthetic_typed_store",
            live_execution_service_present=True,
            live_execution_service_status=(
                AdminApiLiveExecutionStatus.COMPLETED
            ),
            live_execution_service_source="synthetic_backend_service",
            live_execution_service_missing_reason=None,
            browser_authority="backend_admin_api" if allowed else "rejected",
            live_exchange_submitted=False,
            blockers=[],
            evidence=["synthetic_exact_binding"],
            detail=(
                "Synthetic exact backend admission passed."
                if allowed
                else "Synthetic exact backend admission blocked."
            ),
        )


class _CanonicalCommandService:
    def __init__(
        self,
        coordinator: _TrackedProfileCoordinator,
        scopes: "_ScopeFactory",
        events: list[str],
        *,
        create_mode: str = "accepted",
        cancel_mode: str = "accepted",
    ) -> None:
        self.coordinator = coordinator
        self.scopes = scopes
        self.events = events
        self.create_mode = create_mode
        self.cancel_mode = cancel_mode
        self.place_calls: list[tuple[ManualOrderCommand, object]] = []
        self.cancel_calls: list[tuple[CancelOrderCommand, object]] = []
        self.dependencies = _CommandDependencies(
            spot_order_admission_coordinator=coordinator,
        )

    def place_manual_order(
        self,
        command: ManualOrderCommand,
        *,
        automation_admission: ValidatedSpotAutomationAdmissionEvidence,
    ) -> AdminApiCommandResponse:
        self.events.append("canonical_place")
        assert self.scopes.active == COINBASE_EXECUTION_SCOPE_SPOT_PLACE
        self.coordinator.require_active(automation_admission.lease)
        assert command.request.client_order_id == CLIENT_ORDER_ID
        assert command.request.product_id == "BTC-USDC"
        assert command.request.side.value == "BUY"
        assert command.request.base_size == "0.00001"
        assert Decimal(command.request.limit_price or "0") == (
            automation_admission.limit_price
        )
        assert command.request.post_only is automation_admission.post_only
        assert command.request.manual_live_acknowledgement is True
        assert command.allow_live_execution is True
        assert command.admin_max_submitted_notional_usdc == "3.10"
        assert Decimal(command.admin_max_executed_notional_usdc or "0") == (
            automation_admission.max_possible_execution_notional_usdc
        )
        assert command.admin_approval_snapshot_id == "automation-approval-proof"
        assert command.admin_cap_guard_decision_id == "automation-cap-proof"
        assert command.admission_audit_id == "automation-admission-proof"
        self.place_calls.append((command, automation_admission))
        if self.create_mode == "raise":
            raise RuntimeError("private command exception must be withheld")
        return _create_response()

    def cancel_order_by_client_order_id(
        self,
        command: CancelOrderCommand,
        *,
        automation_ownership: ValidatedSpotAutomationOwnershipEvidence,
    ) -> AdminApiCommandResponse:
        self.events.append("canonical_cancel")
        assert self.scopes.active == COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
        self.coordinator.require_active(automation_ownership.lease)
        assert command.client_order_id == CLIENT_ORDER_ID
        assert command.request.manual_live_acknowledgement is True
        assert command.allow_live_execution is True
        self.cancel_calls.append((command, automation_ownership))
        return _cancel_response(mode=self.cancel_mode)


class _ScopeFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.active: str | None = None

    @contextmanager
    def __call__(self, scope: str) -> Iterator[None]:
        assert self.active is None
        assert scope in {
            COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
            COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
            COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW,
        }
        self.active = scope
        self.events.append(f"scope_enter:{scope}")
        try:
            yield
        finally:
            self.events.append(f"scope_exit:{scope}")
            self.active = None


class _PreviewInvoker:
    def __init__(
        self,
        scopes: _ScopeFactory,
        events: list[str],
        *,
        mode: str,
        expected_post_only: bool = False,
        expected_limit_price: str = "50000",
    ) -> None:
        self.scopes = scopes
        self.events = events
        self.mode = mode
        self.expected_post_only = expected_post_only
        self.expected_limit_price = expected_limit_price
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        assert self.scopes.active == COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW
        assert kwargs == {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "0.00001",
                    "limit_price": self.expected_limit_price,
                    "post_only": self.expected_post_only,
                }
            },
        }
        self.events.append("canonical_preview")
        self.calls.append(dict(kwargs))
        if self.mode == "raise":
            raise RuntimeError("withheld preview exception")
        if self.mode == "timeout":
            raise Timeout("withheld preview exception")
        if self.mode == "http_client_response":
            response = Response()
            response.status_code = 400
            response._content = b"withheld private response"
            raise HTTPError("withheld preview exception", response=response)
        if self.mode == "json_decode":
            raise RequestsJSONDecodeError(
                "withheld preview exception",
                "withheld private response",
                0,
            )
        if self.mode == "classifier_raise":
            class _ExplodingPreviewResponse(PreviewOrderResponse):
                def __getattribute__(self, name: str) -> Any:
                    if name == "order_total":
                        raise RuntimeError("withheld classifier exception")
                    return super().__getattribute__(name)

            return _ExplodingPreviewResponse({})
        if self.mode == "malformed":
            return SimpleNamespace(errs=[])
        return PreviewOrderResponse(
            {
                "order_total": (
                    "1.01"
                    if self.expected_limit_price == "100000"
                    else "0.50049"
                    if self.expected_limit_price == "49999"
                    else "0.5005"
                ),
                "commission_total": (
                    "0.01"
                    if self.expected_limit_price == "100000"
                    else "0.0005"
                ),
                "errs": (
                    []
                    if self.mode == "accepted"
                    else ["PREVIEW_INSUFFICIENT_FUND"]
                    if self.mode == "documented_rejected"
                    else ["PREVIEW_REJECTED"]
                ),
                "warning": [],
                "quote_size": (
                    "0.6"
                    if self.mode == "economics_mismatch"
                    else "1"
                    if self.expected_limit_price == "100000"
                    else "0.49999"
                    if self.expected_limit_price == "49999"
                    else "0.5"
                ),
                "base_size": "0.00001",
                "best_bid": (
                    "100000"
                    if self.expected_limit_price == "100000"
                    else "49999"
                ),
                "best_ask": (
                    "100001"
                    if self.expected_limit_price == "100000"
                    else "50000"
                ),
                "is_max": False,
                "preview_id": "withheld-preview-identity",
            }
        )


@dataclass(frozen=True, slots=True)
class _CommandDependencies:
    spot_order_admission_coordinator: _TrackedProfileCoordinator

    @staticmethod
    def planned_budget_fetcher() -> dict[str, float]:
        return {}


def _create_response() -> AdminApiCommandResponse:
    return AdminApiCommandResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_manual_order",
        message="canonical create completed",
        client_order_id=CLIENT_ORDER_ID,
        live_exchange_submitted=True,
        live_coinbase_orders_ran=True,
        live_coinbase_read_ran=True,
        live_coinbase_read_call_count=1,
        data={
            "submission_attempt": {
                "rest_invocation_attempted": True,
                "outcome": "accepted",
                "authoritative_readback_confirmed": True,
                "authoritative_status": "OPEN",
                "readback": {
                    "authoritative": True,
                    "exact_identity_match": True,
                    "authoritative_status": "OPEN",
                },
            }
        },
    )


def _cancel_response(*, mode: str) -> AdminApiCommandResponse:
    if mode == "already_terminal":
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="cancel_order_by_client_order_id",
            message="exact child was already terminal",
            client_order_id=CLIENT_ORDER_ID,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=True,
            live_coinbase_read_call_count=1,
            failure_stage="cancellation_preflight_terminal_status",
            data={
                "cancellation_readback": {
                    "canonical_cancel_attempted": False,
                    "pre_cancel_read_attempted": True,
                    "pre_cancel_reconciled": True,
                    "terminal_status_proven": True,
                    "authoritative_status": "FILLED",
                    "authoritative_readback": {
                        "authoritative": True,
                        "exact_identity_match": True,
                        "authoritative_status": "FILLED",
                    },
                }
            },
        )
    assert mode == "accepted"
    return AdminApiCommandResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="cancel_order_by_client_order_id",
        message="canonical cancel completed",
        client_order_id=CLIENT_ORDER_ID,
        live_coinbase_orders_ran=True,
        live_coinbase_read_ran=True,
        live_coinbase_read_call_count=2,
        data={
            "cancellation_readback": {
                "canonical_cancel_attempted": True,
                "canonical_cancel_accepted": True,
                "canonical_cancel_explicitly_rejected": False,
                "terminal_status_proven": True,
                "authoritative_status": "CANCELLED",
                "authoritative_readback": {
                    "authoritative": True,
                    "exact_identity_match": True,
                    "authoritative_status": "CANCELLED",
                },
            }
        },
    )


@dataclass
class _Harness:
    repository: _ExecutionRepository
    adapter: PostgresOperatorAutomationRepositoryAdapter
    service: OperatorAutomationService
    runner: _EligibilityRunner
    proofs: _ProofChainRecorder
    admission: _LiveAdmissionEvaluator
    commands: _CanonicalCommandService
    preview: _PreviewInvoker | None
    events: list[str]


def _harness(
    tmp_path: Path,
    *,
    admission_mode: str = "allowed",
    create_mode: str = "accepted",
    cancel_mode: str = "accepted",
    eligibility_mode: str = "eligible",
    control_posture: str = "ACTIVE",
    goal_key: str = AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
    preview_mode: str | None = None,
) -> _Harness:
    events: list[str] = []
    repository = _ExecutionRepository(events)
    repository.goal_key = goal_key
    if goal_key == AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY:
        repository.plan = replace(
            repository.plan,
            limit_price="49999",
            submitted_notional_usdc="0.49999",
            possible_execution_notional_usdc="0.49999",
            post_only=True,
        )
    if goal_key == AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY:
        repository.plan = replace(
            repository.plan,
            limit_price="100000",
            submitted_notional_usdc="1",
            possible_execution_notional_usdc="1",
            max_possible_execution_notional_usdc="1.01",
            post_only=True,
        )
    if goal_key == AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY:
        repository.plan = replace(
            repository.plan,
            limit_price="100000",
            submitted_notional_usdc="1",
            possible_execution_notional_usdc="1",
            max_possible_execution_notional_usdc="3.09",
            post_only=True,
        )
    if goal_key != AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
        repository.preview_goal = replace(
            repository.preview_goal,
            goal_key=goal_key,
        )
    repository.control_posture = control_posture
    coordinator = _TrackedProfileCoordinator(events, tmp_path)
    runner = _EligibilityRunner(
        repository,
        coordinator,
        events,
        mode=eligibility_mode,
    )
    proofs = _ProofChainRecorder(events)
    admission = _LiveAdmissionEvaluator(events, admission_mode=admission_mode)
    scopes = _ScopeFactory(events)
    commands = _CanonicalCommandService(
        coordinator,
        scopes,
        events,
        create_mode=create_mode,
        cancel_mode=cancel_mode,
    )
    preview = (
        _PreviewInvoker(
            scopes,
            events,
            mode=preview_mode,
            expected_post_only=(
                goal_key
                in {
                    AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
                    AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
                    AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
                }
            ),
            expected_limit_price=(
                "100000"
                if goal_key in {
                    AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
                    AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
                }
                else "49999"
                if goal_key == AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY
                else "50000"
            ),
        )
        if preview_mode is not None
        else None
    )
    adapter = PostgresOperatorAutomationRepositoryAdapter(
        repository,
        spot_profile_admission_coordinator=coordinator,
        spot_execution_eligibility_runner=runner,
        spot_proof_chain_recorder=proofs,
        spot_live_admission_evaluator=admission,
        spot_command_service=commands,
        spot_preview_invoker=preview,
        spot_execution_scope_factory=scopes,
        now_factory=lambda: NOW,
    )
    return _Harness(
        repository=repository,
        adapter=adapter,
        service=OperatorAutomationService(adapter),
        runner=runner,
        proofs=proofs,
        admission=admission,
        commands=commands,
        preview=preview,
        events=events,
    )


@pytest.mark.parametrize("control_posture", ["PAUSED", "DRAINING"])
def test_non_active_control_posture_blocks_before_final_eligibility_reader(
    tmp_path: Path,
    control_posture: str,
) -> None:
    harness = _harness(tmp_path, control_posture=control_posture)

    with pytest.raises(AutomationRepositoryConflict) as blocked:
        harness.adapter.authorize_single_child(
            run_id=RUN_ID,
            request=_authorization_request().model_dump(mode="json"),
            context=_context(),
        )

    assert blocked.value.code == "automation_control_plane_not_active"
    assert harness.runner.calls == []
    assert harness.runner.reader_calls == []
    assert harness.repository.cycles == ()
    assert harness.repository.attempts == ()
    assert harness.repository.start_create_calls == []
    assert harness.commands.place_calls == []
    assert harness.events == []


def test_authorize_orchestrates_one_fresh_cycle_claim_and_canonical_create(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    response = harness.service.authorize_single_child(
        run_id=RUN_ID,
        request=_authorization_request(),
        context=_context(),
    )

    assert response.replayed is False
    assert response.run.state is OperatorAutomationRunState.ACTIVE, (
        response.run.preview_outcome,
        response.run.preview_failure_class,
        response.run.preview_rejection_code,
        response.run.diagnostic_code,
        harness.events,
    )
    assert response.run.client_order_id == CLIENT_ORDER_ID
    assert response.activity.operation == "CREATE"
    assert response.activity.coinbase_api_call_count == 2
    assert response.activity.read_call_count == 1
    assert response.activity.exchange_mutation_count == 1
    assert response.activity.create_call_count == 1
    assert response.activity.cancel_call_count == 0
    assert response.activity.call_count_exact is True
    assert len(harness.runner.calls) == 1
    assert harness.runner.calls[0]["lease"] is harness.commands.place_calls[0][1].lease
    assert len(harness.repository.start_create_calls) == 1
    assert len(harness.repository.finalize_create_calls) == 1
    finalized = harness.repository.finalize_create_calls[0]
    assert finalized["outcome"] == "ACCEPTED"
    assert finalized["child_terminal"] is False
    assert finalized["coinbase_api_call_count"] == 1
    assert finalized["call_count_exact"] is True
    assert finalized["read_call_count"] == 1
    assert finalized["read_call_count_exact"] is True
    assert harness.events == [
        "lease_enter",
        "eligibility_cycle",
        "proof_create",
        "admission_create",
        "start_create",
        f"scope_enter:{COINBASE_EXECUTION_SCOPE_SPOT_PLACE}",
        "canonical_place",
        f"scope_exit:{COINBASE_EXECUTION_SCOPE_SPOT_PLACE}",
        "finalize_create",
        "lease_exit",
    ]


@pytest.mark.parametrize(
    (
        "preview_mode",
        "expected_state",
        "expected_exact",
        "expected_failure_class",
    ),
    [
        (
            "rejected",
            OperatorAutomationRunState.TERMINAL,
            True,
            "UNCLASSIFIED_REJECTION",
        ),
        (
            "documented_rejected",
            OperatorAutomationRunState.TERMINAL,
            True,
            "DOCUMENTED_REJECTION",
        ),
        (
            "malformed",
            OperatorAutomationRunState.UNKNOWN_CONSUMED,
            True,
            "RESPONSE_SCHEMA_INVALID",
        ),
        (
            "economics_mismatch",
            OperatorAutomationRunState.UNKNOWN_CONSUMED,
            True,
            "RESPONSE_SCHEMA_INVALID",
        ),
        (
            "http_client_response",
            OperatorAutomationRunState.UNKNOWN_CONSUMED,
            True,
            "HTTP_CLIENT_RESPONSE",
        ),
        (
            "json_decode",
            OperatorAutomationRunState.UNKNOWN_CONSUMED,
            True,
            "RESPONSE_SCHEMA_INVALID",
        ),
        (
            "classifier_raise",
            OperatorAutomationRunState.UNKNOWN_CONSUMED,
            True,
            "RESPONSE_SCHEMA_INVALID",
        ),
        (
            "timeout",
            OperatorAutomationRunState.UNKNOWN_CONSUMED,
            False,
            "TRANSPORT_UNKNOWN",
        ),
        (
            "raise",
            OperatorAutomationRunState.UNKNOWN_CONSUMED,
            False,
            "TRANSPORT_UNKNOWN",
        ),
    ],
)
def test_preview_gated_rejection_or_unknown_never_enters_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preview_mode: str,
    expected_state: OperatorAutomationRunState,
    expected_exact: bool,
    expected_failure_class: str,
) -> None:
    successor_client_order_id = derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=PLAN_SHA256,
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "CLIENT_ORDER_ID",
        successor_client_order_id,
    )
    harness = _harness(
        tmp_path,
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
        preview_mode=preview_mode,
    )

    response = harness.service.authorize_preview_gated_single_child(
        run_id=RUN_ID,
        request=_preview_authorization_request(),
        context=_context(),
    )

    assert response.run.state is expected_state
    assert response.run.preview_allowance_consumed is True
    assert response.run.create_allowance_consumed is False
    assert response.run.preview_failure_class == expected_failure_class
    assert response.run.preview_rejection_code == (
        "INSUFFICIENT_FUNDS"
        if preview_mode == "documented_rejected"
        else None
    )
    assert response.activity.operation == "PREVIEW_GATED_CREATE"
    assert response.activity.call_count_exact is expected_exact
    assert response.activity.preview_call_count == (1 if expected_exact else None)
    assert response.activity.read_call_count == 8
    assert response.activity.coinbase_api_call_count == (
        9 if expected_exact else None
    )
    assert response.activity.create_call_count == 0
    assert len(harness.repository.start_preview_calls) == 1
    assert len(harness.repository.finalize_preview_calls) == 1
    assert harness.repository.start_create_calls == []
    assert harness.commands.place_calls == []
    assert harness.preview is not None
    assert len(harness.preview.calls) == 1


@pytest.mark.parametrize(
    "goal_key",
    [
        AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
        AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
        AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
        AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
        AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
    ],
)
def test_preview_gated_acceptance_previews_then_creates_the_identical_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    goal_key: str,
) -> None:
    successor_client_order_id = derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=PLAN_SHA256,
        goal_key=goal_key,
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "CLIENT_ORDER_ID",
        successor_client_order_id,
    )
    harness = _harness(
        tmp_path,
        goal_key=goal_key,
        preview_mode="accepted",
    )

    response = harness.service.authorize_preview_gated_single_child(
        run_id=RUN_ID,
        request=_preview_authorization_request(),
        context=_context(),
    )

    assert response.run.state is OperatorAutomationRunState.ACTIVE, (
        response.run.preview_outcome,
        response.run.preview_failure_class,
        response.run.preview_rejection_code,
        response.run.diagnostic_code,
        harness.events,
    )
    assert response.run.client_order_id == successor_client_order_id
    assert response.run.preview_outcome == "ACCEPTED"
    assert response.run.preview_identity_retention == "HASHED"
    assert response.run.create_allowance_consumed is True
    assert response.activity.operation == "PREVIEW_GATED_CREATE"
    assert response.activity.coinbase_api_call_count == 11
    assert response.activity.preview_call_count == 1
    assert response.activity.read_call_count == 9
    assert response.activity.create_call_count == 1
    assert len(harness.preview.calls if harness.preview is not None else []) == 1
    assert len(harness.commands.place_calls) == 1
    assert harness.commands.place_calls[0][1].market_evidence.source == (
        "coinbase_rest_market_trade_snapshot"
        if goal_key
        in {
            AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
            AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
            AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
            AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
        }
        else "coinbase_rest_best_bid"
    )
    assert harness.preview is not None
    assert harness.preview.calls[0]["order_configuration"]["limit_limit_gtc"][
        "post_only"
    ] is (
        goal_key
        in {
            AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
            AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
            AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
        }
    )
    assert harness.events == [
        "lease_enter",
        "eligibility_cycle",
        "proof_create",
        "admission_create",
        f"scope_enter:{COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW}",
        "start_preview",
        "canonical_preview",
        f"scope_exit:{COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW}",
        "finalize_preview",
        "start_create",
        f"scope_enter:{COINBASE_EXECUTION_SCOPE_SPOT_PLACE}",
        "canonical_place",
        f"scope_exit:{COINBASE_EXECUTION_SCOPE_SPOT_PLACE}",
        "finalize_create",
        "lease_exit",
    ]


def test_atomic_precomputed_snapshot_keeps_one_profile_lease_through_preview_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor_client_order_id = derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=PLAN_SHA256,
        goal_key=AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "CLIENT_ORDER_ID",
        successor_client_order_id,
    )
    harness = _harness(
        tmp_path,
        goal_key=AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
        preview_mode="accepted",
    )
    coordinator = harness.commands.dependencies.spot_order_admission_coordinator
    record = harness.repository.current_run
    plan = harness.repository.plan

    with coordinator.claim(PORTFOLIO_ID) as lease:
        bundle = harness.runner(
            record=record,
            plan=plan,
            context=_context(),
            lease=lease,
        )
        response = harness.adapter._authorize_single_child_workflow(
            run_id=RUN_ID,
            request=_preview_authorization_request().model_dump(mode="json"),
            context=_context(),
            preview_gated=True,
            precomputed_bundle=bundle,
            admission_lease=lease,
        )

    assert response.entity["state"] == "ACTIVE"
    assert harness.events.count("lease_enter") == 1
    assert harness.events.count("lease_exit") == 1
    assert harness.events.index("eligibility_cycle") < harness.events.index(
        "canonical_preview"
    )
    assert harness.events.index("canonical_preview") < harness.events.index(
        "canonical_place"
    )


def test_accepted_preview_checkpoint_resumes_create_without_second_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor_client_order_id = derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=PLAN_SHA256,
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "CLIENT_ORDER_ID",
        successor_client_order_id,
    )
    harness = _harness(
        tmp_path,
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
        preview_mode="accepted",
    )
    harness.repository.preview_goal = replace(
        harness.repository.preview_goal,
        bound_run_id=RUN_ID,
        client_order_id=successor_client_order_id,
        eligibility_cycle=1,
        plan_sha256=PLAN_SHA256,
        portfolio_id_sha256=PORTFOLIO_SHA256,
        product_id="BTC-USDC",
        preview_allowance_consumed=True,
        preview_outcome="ACCEPTED",
        preview_failure_class="NONE",
        preview_warning_present=False,
        preview_id_sha256="f" * 64,
        preview_call_count=1,
        preview_call_count_exact=True,
    )
    harness.repository.current_run = replace(
        harness.repository.current_run,
        diagnostic_code="automation_spot_preview_accepted_create_ready",
        client_order_id=successor_client_order_id,
        live_attempt_consumed=True,
        coinbase_api_call_count=1,
    )

    response = harness.service.authorize_preview_gated_single_child(
        run_id=RUN_ID,
        request=_preview_authorization_request(),
        context=_context().model_copy(
            update={"idempotency_key": "resume-after-preview-acceptance"}
        ),
    )

    assert response.run.state is OperatorAutomationRunState.ACTIVE
    assert response.activity.preview_call_count == 0
    assert response.activity.coinbase_api_call_count == 10
    assert response.activity.read_call_count == 9
    assert harness.repository.start_preview_calls == []
    assert harness.preview is not None and harness.preview.calls == []
    assert len(harness.commands.place_calls) == 1


def test_atomic_accepted_preview_checkpoint_resumes_revision_five_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    goal_key = AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY
    successor_client_order_id = derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=PLAN_SHA256,
        goal_key=goal_key,
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "CLIENT_ORDER_ID",
        successor_client_order_id,
    )
    harness = _harness(
        tmp_path,
        goal_key=goal_key,
        preview_mode="accepted",
    )
    harness.repository.preview_goal = replace(
        harness.repository.preview_goal,
        bound_run_id=RUN_ID,
        client_order_id=successor_client_order_id,
        eligibility_cycle=1,
        plan_sha256=PLAN_SHA256,
        portfolio_id_sha256=PORTFOLIO_SHA256,
        product_id="BTC-USDC",
        preview_allowance_consumed=True,
        preview_outcome="ACCEPTED",
        preview_failure_class="NONE",
        preview_warning_present=False,
        preview_id_sha256="f" * 64,
        preview_call_count=1,
        preview_call_count_exact=True,
    )
    harness.repository.current_run = replace(
        harness.repository.current_run,
        diagnostic_code="automation_spot_preview_accepted_create_ready",
        client_order_id=successor_client_order_id,
        live_attempt_consumed=True,
        coinbase_api_call_count=1,
    )

    response = harness.service.authorize_preview_gated_single_child(
        run_id=RUN_ID,
        request=_preview_authorization_request(),
        context=_context().model_copy(
            update={"idempotency_key": "resume-atomic-preview-acceptance"}
        ),
    )

    assert response.run.state is OperatorAutomationRunState.ACTIVE
    assert response.activity.preview_call_count == 0
    assert harness.repository.start_preview_calls == []
    assert harness.preview is not None and harness.preview.calls == []
    assert len(harness.commands.place_calls) == 1
    admission = harness.commands.place_calls[0][1]
    assert admission.policy_revision == 5
    assert admission.standing_price_policy == (
        "ATOMIC_MARKET_SNAPSHOT_POST_ONLY_V1"
    )


def test_authorize_replay_has_no_reader_proof_admission_or_command_call(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    first = harness.service.authorize_single_child(
        run_id=RUN_ID,
        request=_authorization_request(),
        context=_context(),
    )
    assert first.replayed is False
    harness.events.clear()
    harness.runner.calls.clear()
    harness.proofs.calls.clear()
    harness.commands.place_calls.clear()

    response = harness.service.authorize_single_child(
        run_id=RUN_ID,
        request=_authorization_request(),
        context=_context(),
    )

    assert response.replayed is True
    assert response.activity.operation == "LOCAL"
    assert response.activity.coinbase_api_call_count == 0
    assert harness.events == []
    assert harness.runner.calls == []
    assert harness.proofs.calls == []
    assert harness.commands.place_calls == []
    assert len(harness.repository.start_create_calls) == 2
    assert harness.repository.start_create_calls[-1]["replayed"] is True
    assert len(harness.repository.finalize_create_calls) == 1


def test_authorize_replay_after_closeout_returns_original_create_envelope(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    create_context = _context()
    first = harness.service.authorize_single_child(
        run_id=RUN_ID,
        request=_authorization_request(),
        context=create_context,
    )
    closeout_context = _context().model_copy(
        update={
            "idempotency_key": "automation-closeout-idempotency-1",
            "correlation_id": "automation-closeout-correlation-1",
            "operator_intent": "safe_closeout_exact_automation_child",
        }
    )
    closed = harness.service.safe_closeout_single_child(
        run_id=RUN_ID,
        request=_closeout_request(),
        context=closeout_context,
    )
    assert closed.correlation_id == closeout_context.correlation_id
    assert closed.audit_id == CANCEL_AUDIT_ID
    harness.events.clear()
    harness.runner.calls.clear()
    harness.proofs.calls.clear()
    harness.commands.place_calls.clear()
    harness.commands.cancel_calls.clear()

    replay = harness.service.authorize_single_child(
        run_id=RUN_ID,
        request=_authorization_request(),
        context=create_context,
    )

    assert replay.replayed is True
    assert replay.audit_id == first.audit_id
    assert replay.correlation_id == first.correlation_id
    assert replay.correlation_id == create_context.correlation_id
    assert replay.activity.operation == "LOCAL"
    assert replay.activity.coinbase_api_call_count == 0
    assert harness.events == []
    assert harness.runner.calls == []
    assert harness.proofs.calls == []
    assert harness.commands.place_calls == []
    assert harness.commands.cancel_calls == []
    assert len(harness.repository.start_create_calls) == 2
    assert harness.repository.start_create_calls[-1]["replayed"] is True
    assert len(harness.repository.finalize_create_calls) == 1
    assert len(harness.repository.finalize_cancel_calls) == 1


@pytest.mark.parametrize(
    "changed_field",
    [
        "idempotency_key",
        "reason",
        "roles",
        "actor_id",
        "correlation_id",
        "operator_intent",
    ],
)
def test_authorize_consumed_allowance_rejects_nonidentical_replay_without_calls(
    tmp_path: Path,
    changed_field: str,
) -> None:
    harness = _harness(tmp_path)
    first = harness.service.authorize_single_child(
        run_id=RUN_ID,
        request=_authorization_request(),
        context=_context(),
    )
    assert first.replayed is False
    harness.events.clear()
    harness.runner.calls.clear()
    harness.proofs.calls.clear()
    harness.commands.place_calls.clear()
    request = _authorization_request()
    context = _context()
    if changed_field == "idempotency_key":
        context = context.model_copy(
            update={"idempotency_key": "automation-execution-idempotency-2"}
        )
    elif changed_field == "reason":
        request = request.model_copy(update={"reason": "different reason"})
    elif changed_field == "roles":
        context = context.model_copy(update={"roles": ("admin", "trader")})
    else:
        context = context.model_copy(
            update={changed_field: f"different-{changed_field}"}
        )

    with pytest.raises(AutomationRepositoryConflict) as raised:
        harness.adapter.authorize_single_child(
            run_id=RUN_ID,
            request=request.model_dump(mode="json"),
            context=context,
        )

    assert raised.value.code == (
        "automation_spot_create_allowance_consumed"
        if changed_field == "idempotency_key"
        else "automation_idempotency_conflict"
    )
    assert harness.events == []
    assert harness.runner.calls == []
    assert harness.proofs.calls == []
    assert harness.commands.place_calls == []
    assert len(harness.repository.start_create_calls) == 1
    assert len(harness.repository.finalize_create_calls) == 1


@pytest.mark.parametrize(
    ("admission_mode", "expected_code"),
    [
        ("blocked", "automation_spot_live_admission_blocked"),
        ("mismatched_action", "automation_spot_live_admission_blocked"),
        ("raise", "automation_spot_create_admission_failed"),
    ],
)
def test_admission_failure_before_durable_claim_leaves_create_unconsumed(
    tmp_path: Path,
    admission_mode: str,
    expected_code: str,
) -> None:
    harness = _harness(tmp_path, admission_mode=admission_mode)

    with pytest.raises(AutomationRepositoryConflict) as raised:
        harness.adapter.authorize_single_child(
            run_id=RUN_ID,
            request=_authorization_request().model_dump(mode="json"),
            context=_context(),
        )

    assert raised.value.code == expected_code
    assert "private" not in str(raised.value)
    assert harness.repository.execution is None
    assert harness.repository.start_create_calls == []
    assert harness.repository.finalize_create_calls == []
    assert harness.commands.place_calls == []
    assert harness.events == [
        "lease_enter",
        "eligibility_cycle",
        "proof_create",
        "admission_create",
        "lease_exit",
    ]


def test_exact_authorization_retry_after_post_cycle_failure_is_reader_free(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, admission_mode="raise")
    request = _authorization_request().model_dump(mode="json")
    context = _context()

    with pytest.raises(AutomationRepositoryConflict) as first:
        harness.adapter.authorize_single_child(
            run_id=RUN_ID,
            request=request,
            context=context,
        )

    assert first.value.code == "automation_spot_create_admission_failed"
    reader_calls_after_first = tuple(harness.runner.reader_calls)
    assert reader_calls_after_first == APPROVED_SPOT_ELIGIBILITY_ORDER
    assert len(harness.runner.calls) == 1
    assert harness.repository.execution is None
    assert harness.repository.start_create_calls == []
    assert harness.commands.place_calls == []
    harness.events.clear()

    with pytest.raises(AutomationRepositoryConflict) as replay:
        harness.adapter.authorize_single_child(
            run_id=RUN_ID,
            request=request,
            context=context,
        )

    assert replay.value.code == "automation_spot_fresh_eligibility_required"
    assert tuple(harness.runner.reader_calls) == reader_calls_after_first
    assert len(harness.runner.calls) == 1
    assert harness.repository.execution is None
    assert harness.repository.start_create_calls == []
    assert harness.repository.finalize_create_calls == []
    assert harness.commands.place_calls == []
    assert harness.events == ["lease_enter", "lease_exit"]


def test_unknown_final_eligibility_cycle_leaves_create_allowance_unconsumed(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, eligibility_mode="unknown")

    with pytest.raises(AutomationRepositoryConflict) as raised:
        harness.adapter.authorize_single_child(
            run_id=RUN_ID,
            request=_authorization_request().model_dump(mode="json"),
            context=_context(),
        )

    assert raised.value.code == "automation_spot_create_admission_failed"
    assert harness.repository.execution is None
    assert harness.repository.start_create_calls == []
    assert harness.repository.finalize_create_calls == []
    assert harness.commands.place_calls == []
    assert harness.proofs.calls == []
    assert harness.admission.calls == []
    assert harness.events == [
        "lease_enter",
        "eligibility_cycle",
        "lease_exit",
    ]


def test_exception_after_durable_claim_finalizes_unknown_consumed(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, create_mode="raise")

    response = harness.service.authorize_single_child(
        run_id=RUN_ID,
        request=_authorization_request(),
        context=_context(),
    )

    assert response.run.state is OperatorAutomationRunState.UNKNOWN_CONSUMED
    assert response.activity.operation == "CREATE"
    assert response.activity.coinbase_api_call_count is None
    assert response.activity.call_count_exact is False
    assert len(harness.repository.start_create_calls) == 1
    assert len(harness.repository.finalize_create_calls) == 1
    finalized = harness.repository.finalize_create_calls[0]
    assert finalized["outcome"] == "UNKNOWN"
    assert finalized["child_terminal"] is None
    assert finalized["coinbase_api_call_count"] is None
    assert finalized["call_count_exact"] is False
    assert finalized["read_call_count"] is None
    assert finalized["read_call_count_exact"] is False
    assert "private" not in response.run.diagnostic_code
    assert harness.events[-2:] == ["finalize_create", "lease_exit"]


def test_safe_closeout_already_terminal_accounts_one_read_and_zero_cancel(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, cancel_mode="already_terminal")
    harness.repository.seed_create_success()
    harness.events.clear()

    response = harness.service.safe_closeout_single_child(
        run_id=RUN_ID,
        request=_closeout_request(),
        context=_context(),
    )

    assert response.replayed is False
    assert response.run.state is OperatorAutomationRunState.TERMINAL
    assert response.run.child_terminal is True
    assert response.activity.operation == "SAFE_CLOSEOUT"
    assert response.activity.coinbase_api_call_count == 1
    assert response.activity.read_call_count == 1
    assert response.activity.exchange_mutation_count == 0
    assert response.activity.cancel_call_count == 0
    finalized = harness.repository.finalize_cancel_calls[0]
    assert finalized["outcome"] == "ACCEPTED"
    assert finalized["child_terminal"] is True
    assert finalized["coinbase_api_call_count"] == 0
    assert finalized["read_call_count"] == 1
    assert harness.events == [
        "lease_enter",
        "proof_cancel",
        "admission_cancel",
        "start_cancel",
        f"scope_enter:{COINBASE_EXECUTION_SCOPE_SPOT_CANCEL}",
        "canonical_cancel",
        f"scope_exit:{COINBASE_EXECUTION_SCOPE_SPOT_CANCEL}",
        "finalize_cancel",
        "lease_exit",
    ]


@pytest.mark.parametrize("control_posture", ["PAUSED", "DRAINING"])
def test_risk_reducing_safe_closeout_remains_available_while_not_active(
    tmp_path: Path,
    control_posture: str,
) -> None:
    harness = _harness(
        tmp_path,
        cancel_mode="accepted",
        control_posture=control_posture,
    )
    harness.repository.seed_create_success()
    harness.events.clear()

    projected = harness.adapter._run(harness.repository.current_run)
    assert projected["live_execution_available"] is True
    assert projected["allowed_actions"] == ["SAFE_CLOSEOUT_CHILD"]

    response = harness.service.safe_closeout_single_child(
        run_id=RUN_ID,
        request=_closeout_request(),
        context=_context(),
    )

    assert response.run.state is OperatorAutomationRunState.TERMINAL
    assert response.activity.exchange_mutation_count == 1
    assert response.activity.cancel_call_count == 1
    assert len(harness.repository.start_cancel_calls) == 1
    assert len(harness.commands.cancel_calls) == 1


def test_shutdown_suppresses_and_blocks_safe_closeout_before_proof_or_call(
    tmp_path: Path,
) -> None:
    harness = _harness(
        tmp_path,
        cancel_mode="accepted",
        control_posture="SHUTDOWN",
    )
    harness.repository.seed_create_success()
    harness.events.clear()

    projected = harness.adapter._run(harness.repository.current_run)
    assert projected["live_execution_available"] is False
    assert projected["allowed_actions"] == []

    with pytest.raises(AutomationRepositoryConflict) as blocked:
        harness.adapter.safe_closeout_single_child(
            run_id=RUN_ID,
            request=_closeout_request().model_dump(mode="json"),
            context=_context(),
        )

    assert blocked.value.code == "automation_control_plane_shutdown"
    assert harness.repository.start_cancel_calls == []
    assert harness.proofs.calls == []
    assert harness.commands.cancel_calls == []
    assert harness.events == []


def test_safe_closeout_canonical_cancel_accounts_two_reads_and_one_cancel(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, cancel_mode="accepted")
    harness.repository.seed_create_success()
    original_list_cycles = harness.repository.list_spot_eligibility_cycles

    def list_cycles_with_explicit_goal(*, goal_key):
        assert goal_key == harness.repository.goal_key
        return original_list_cycles(goal_key=goal_key)

    harness.repository.list_spot_eligibility_cycles = list_cycles_with_explicit_goal
    harness.events.clear()

    response = harness.service.safe_closeout_single_child(
        run_id=RUN_ID,
        request=_closeout_request(),
        context=_context(),
    )

    assert response.run.state is OperatorAutomationRunState.TERMINAL
    assert response.run.child_terminal is True
    assert response.activity.coinbase_api_call_count == 3
    assert response.activity.read_call_count == 2
    assert response.activity.exchange_mutation_count == 1
    assert response.activity.cancel_call_count == 1
    finalized = harness.repository.finalize_cancel_calls[0]
    assert finalized["outcome"] == "ACCEPTED"
    assert finalized["coinbase_api_call_count"] == 1
    assert finalized["read_call_count"] == 2
    assert len(harness.commands.cancel_calls) == 1


def test_atomic_market_snapshot_safe_closeout_preserves_revision_five_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor_client_order_id = derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=PLAN_SHA256,
        goal_key=AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "CLIENT_ORDER_ID",
        successor_client_order_id,
    )
    harness = _harness(
        tmp_path,
        goal_key=AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
        preview_mode="accepted",
        cancel_mode="accepted",
    )
    created = harness.service.authorize_preview_gated_single_child(
        run_id=RUN_ID,
        request=_preview_authorization_request(),
        context=_context(),
    )
    assert created.run.state is OperatorAutomationRunState.ACTIVE

    response = harness.adapter.safe_closeout_single_child(
        run_id=RUN_ID,
        request=_closeout_request().model_dump(mode="json"),
        context=_context(),
    )

    assert response.entity["state"] == "TERMINAL"
    assert len(harness.commands.cancel_calls) == 1
    ownership = harness.commands.cancel_calls[0][1]
    assert ownership.policy_revision == 5
    assert ownership.standing_price_policy == (
        "ATOMIC_MARKET_SNAPSHOT_POST_ONLY_V1"
    )


def test_safe_closeout_replay_has_no_profile_reader_or_command_call(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    harness.repository.seed_create_success()
    first = harness.service.safe_closeout_single_child(
        run_id=RUN_ID,
        request=_closeout_request(),
        context=_context(),
    )
    assert first.replayed is False
    harness.events.clear()
    harness.runner.calls.clear()
    harness.proofs.calls.clear()
    harness.commands.cancel_calls.clear()

    response = harness.service.safe_closeout_single_child(
        run_id=RUN_ID,
        request=_closeout_request(),
        context=_context(),
    )

    assert response.replayed is True
    assert response.activity.operation == "LOCAL"
    assert response.activity.coinbase_api_call_count == 0
    assert harness.events == []
    assert harness.runner.calls == []
    assert harness.proofs.calls == []
    assert harness.commands.cancel_calls == []
    assert len(harness.repository.start_cancel_calls) == 2
    assert harness.repository.start_cancel_calls[-1]["replayed"] is True
    assert len(harness.repository.finalize_cancel_calls) == 1


@pytest.mark.parametrize(
    "changed_field",
    [
        "idempotency_key",
        "reason",
        "roles",
        "actor_id",
        "correlation_id",
        "operator_intent",
    ],
)
def test_safe_closeout_consumed_allowance_rejects_nonidentical_replay_without_calls(
    tmp_path: Path,
    changed_field: str,
) -> None:
    harness = _harness(tmp_path)
    harness.repository.seed_create_success()
    first = harness.service.safe_closeout_single_child(
        run_id=RUN_ID,
        request=_closeout_request(),
        context=_context(),
    )
    assert first.replayed is False
    harness.events.clear()
    harness.runner.calls.clear()
    harness.proofs.calls.clear()
    harness.commands.cancel_calls.clear()
    request = _closeout_request()
    context = _context()
    if changed_field == "idempotency_key":
        context = context.model_copy(
            update={"idempotency_key": "automation-execution-idempotency-2"}
        )
    elif changed_field == "reason":
        request = request.model_copy(update={"reason": "different reason"})
    elif changed_field == "roles":
        context = context.model_copy(update={"roles": ("admin", "trader")})
    else:
        context = context.model_copy(
            update={changed_field: f"different-{changed_field}"}
        )

    with pytest.raises(AutomationRepositoryConflict) as raised:
        harness.adapter.safe_closeout_single_child(
            run_id=RUN_ID,
            request=request.model_dump(mode="json"),
            context=context,
        )

    assert raised.value.code == (
        "automation_spot_cancel_allowance_consumed"
        if changed_field == "idempotency_key"
        else "automation_idempotency_conflict"
    )
    assert harness.events == []
    assert harness.runner.calls == []
    assert harness.proofs.calls == []
    assert harness.commands.cancel_calls == []
    assert len(harness.repository.start_cancel_calls) == 1
    assert len(harness.repository.finalize_cancel_calls) == 1
