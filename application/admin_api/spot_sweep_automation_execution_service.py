"""No-live execution contract for Admin API spot sweep automation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from business.spot_campaign import (
    build_spot_campaign_operation_lock_status,
    build_spot_campaign_retry_plan,
    load_spot_campaign_snapshot_records,
    normalize_spot_campaign_config,
)
from business.spot_portfolio_sweep import (
    evaluate_sweep_automation_due,
    load_sweep_run_records,
)
from business.spot_sweep_recovery_gate import build_sweep_recovery_gate_plan
from core.enums import (
    AdminApiGateStatus,
    AdminApiModuleSupportStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiLiveReadinessPrecondition,
    SpotCampaignStatus,
    SpotPortfolioSweepAutomationDecision,
    SpotSweepAutomationControlAction,
    SpotSweepAutomationControlState,
    SpotSweepAutomationExecutionBlocker,
    SpotSweepAutomationExecutionDecision,
)

from .models import AdminLiveAdmissionDecisionEvidence, SpotSweepAutomationRunRequest
from .spot_sweep_automation_control import (
    FileSpotSweepAutomationControlStore,
    build_spot_sweep_automation_control_state,
)


SPOT_SWEEP_AUTOMATION_RUN_ROUTE = "/api/v1/spot/sweep/automation-runs"
SPOT_SWEEP_RETRY_PLAN_PREFIX = "spot-sweep-retry"
NO_LIVE_CONTRACT_STATUS = AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED


class AdminApiSpotSweepAutomationExecutionService:
    """Review scheduler and retry execution readiness without live side effects."""

    def build_contract_data(
        self,
        *,
        request: SpotSweepAutomationRunRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence | None = None,
        sweep_state_file: str | Path,
        campaign_state_file: str | Path,
        operation_lock_file: str | Path,
        automation_control_store: FileSpotSweepAutomationControlStore,
        lock_stale_after_seconds: int = 3600,
    ) -> dict[str, Any]:
        """Return backend-owned automation evidence without invoking execution."""

        sweep_records = load_sweep_run_records(sweep_state_file)
        campaign_records = load_spot_campaign_snapshot_records(campaign_state_file)
        control_records = automation_control_store.read_for_sweep_config_id(
            request.sweep_config_id,
            limit=100,
        )
        latest_control_state = build_spot_sweep_automation_control_state(
            control_records
        )
        operation_lock_status = build_spot_campaign_operation_lock_status(
            lock_file=operation_lock_file,
            stale_after_seconds=lock_stale_after_seconds,
        )
        campaign_config = _latest_campaign_config_for_sweep(
            campaign_records=campaign_records,
            sweep_config_id=request.sweep_config_id,
        )
        scheduler_contract = _build_scheduler_dispatch_contract(
            request=request,
            sweep_records=sweep_records,
            latest_control_state=latest_control_state,
            operation_lock_status=operation_lock_status,
        )
        retry_contract = _build_retry_execution_contract(
            request=request,
            campaign_config=campaign_config,
            sweep_records=sweep_records,
            control_records=control_records,
        )
        recovery_gate_contract = _build_recovery_gate_contract(
            request=request,
            sweep_records=sweep_records,
            sweep_state_file=sweep_state_file,
        )
        scheduler_admission_contract = _build_scheduler_executor_admission_contract(
            request=request,
            scheduler_contract=scheduler_contract,
            recovery_gate_contract=recovery_gate_contract,
            admission_decision=admission_decision,
        )
        retry_admission_contract = _build_retry_executor_admission_contract(
            request=request,
            retry_contract=retry_contract,
            recovery_gate_contract=recovery_gate_contract,
            admission_decision=admission_decision,
        )
        reconciliation_contract = _build_reconciliation_execution_contract(
            recovery_gate_contract=recovery_gate_contract,
        )
        live_contract = _build_live_execution_contract()

        dry_run = bool(request.dry_run)
        automation_decision = (
            SpotSweepAutomationExecutionDecision.DRY_RUN_REVIEW_ONLY
            if dry_run
            else SpotSweepAutomationExecutionDecision.LIVE_EXECUTION_NOT_IMPLEMENTED
        )
        blockers = _unique_blockers(
            [
                (
                    SpotSweepAutomationExecutionBlocker.DRY_RUN_REVIEW_ONLY
                    if dry_run
                    else SpotSweepAutomationExecutionBlocker.LIVE_EXECUTION_DISABLED
                ),
                *scheduler_contract["blocker_enums"],
                *retry_contract["blocker_enums"],
                *recovery_gate_contract["blocker_enums"],
                (
                    SpotSweepAutomationExecutionBlocker.RECONCILIATION_EXECUTION_CONTRACT_REQUIRED
                ),
                SpotSweepAutomationExecutionBlocker.LIVE_EXECUTION_CONTRACT_REQUIRED,
            ]
        )

        return {
            "automation_execution_contract_status": NO_LIVE_CONTRACT_STATUS.value,
            "automation_execution_decision": automation_decision.value,
            "automation_execution_blockers": [item.value for item in blockers],
            "scheduler_dispatch_contract_status": NO_LIVE_CONTRACT_STATUS.value,
            "scheduler_dispatch_decision": scheduler_contract["decision"].value,
            "scheduler_dispatch_contract": scheduler_contract["data"],
            "scheduler_executor_admission_contract_status": (
                NO_LIVE_CONTRACT_STATUS.value
            ),
            "scheduler_executor_admission_decision": (
                scheduler_admission_contract["decision"].value
            ),
            "scheduler_executor_admission_contract": (
                scheduler_admission_contract["data"]
            ),
            "retry_execution_contract_status": NO_LIVE_CONTRACT_STATUS.value,
            "retry_execution_decision": retry_contract["decision"].value,
            "retry_execution_contract": retry_contract["data"],
            "retry_executor_admission_contract_status": (
                NO_LIVE_CONTRACT_STATUS.value
            ),
            "retry_executor_admission_decision": (
                retry_admission_contract["decision"].value
            ),
            "retry_executor_admission_contract": retry_admission_contract["data"],
            "recovery_gate_contract_status": (
                AdminApiModuleSupportStatus.READ_ONLY_READY.value
            ),
            "recovery_gate_decision": recovery_gate_contract["decision"].value,
            "recovery_gate_contract": recovery_gate_contract["data"],
            "reconciliation_execution_contract_status": (
                NO_LIVE_CONTRACT_STATUS.value
            ),
            "reconciliation_execution_decision": (
                reconciliation_contract["decision"].value
            ),
            "reconciliation_execution_contract": reconciliation_contract["data"],
            "live_execution_contract_status": NO_LIVE_CONTRACT_STATUS.value,
            "live_execution_decision": live_contract["decision"].value,
            "live_execution_contract": live_contract["data"],
            "scheduler_invoked": False,
            "sweep_runner_invoked": False,
            "coinbase_orders_submitted": False,
            "live_coinbase_orders_ran": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
        }


def _build_scheduler_dispatch_contract(
    *,
    request: SpotSweepAutomationRunRequest,
    sweep_records: list[dict[str, Any]],
    latest_control_state: Mapping[str, Any],
    operation_lock_status: Mapping[str, Any],
) -> dict[str, Any]:
    scheduler_decision: dict[str, Any] = {}
    dispatch_blockers: list[SpotSweepAutomationExecutionBlocker] = []
    decision = SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_INPUT_REQUIRED
    would_dispatch = False

    if not request.run_if_due:
        decision = SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_NOT_REQUESTED
        dispatch_blockers.append(
            SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_NOT_REQUESTED
        )
    elif request.repeat_every_hours is None or request.max_runs is None:
        decision = SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_INPUT_REQUIRED
        dispatch_blockers.append(
            SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_INPUT_REQUIRED
        )
    else:
        try:
            scheduler_decision = evaluate_sweep_automation_due(
                config_id=request.sweep_config_id,
                repeat_every_hours=request.repeat_every_hours,
                max_runs=int(request.max_runs),
                records=sweep_records,
            )
        except ValueError as exc:
            scheduler_decision = {"error": str(exc)}
            decision = (
                SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_INPUT_REQUIRED
            )
            dispatch_blockers.append(
                SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_INPUT_REQUIRED
            )
        else:
            decision_value = scheduler_decision.get("decision")
            if decision_value == SpotPortfolioSweepAutomationDecision.NOT_DUE.value:
                decision = SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_NOT_DUE
                dispatch_blockers.append(
                    SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_NOT_DUE
                )
            elif decision_value == SpotPortfolioSweepAutomationDecision.DISABLED.value:
                decision = SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_DISABLED
                dispatch_blockers.append(
                    SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_DISABLED
                )
            elif (
                decision_value
                == SpotPortfolioSweepAutomationDecision.MAX_RUNS_REACHED.value
            ):
                decision = (
                    SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_MAX_RUNS_REACHED
                )
                dispatch_blockers.append(
                    SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_MAX_RUNS_REACHED
                )
            elif (
                latest_control_state.get("control_state_after")
                == SpotSweepAutomationControlState.PAUSED.value
            ):
                decision = (
                    SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_BLOCKED_BY_PAUSE_CONTROL
                )
                dispatch_blockers.append(
                    SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_PAUSED
                )
            elif _operation_lock_busy(operation_lock_status):
                decision = (
                    SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_BLOCKED_BY_OPERATION_LOCK
                )
                dispatch_blockers.append(
                    SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_OPERATION_LOCK_BUSY
                )
            elif decision_value == SpotPortfolioSweepAutomationDecision.DUE.value:
                decision = (
                    SpotSweepAutomationExecutionDecision.SCHEDULER_DISPATCH_READY_LIVE_DISABLED
                )
                dispatch_blockers.append(
                    SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_LIVE_DISABLED
                )
                would_dispatch = True
            else:
                dispatch_blockers.append(
                    SpotSweepAutomationExecutionBlocker.SCHEDULER_DISPATCH_INPUT_REQUIRED
                )

    return {
        "decision": decision,
        "blocker_enums": _unique_blockers(dispatch_blockers),
        "data": {
            "contract_status": NO_LIVE_CONTRACT_STATUS.value,
            "decision": decision.value,
            "route": SPOT_SWEEP_AUTOMATION_RUN_ROUTE,
            "backend_owned": True,
            "operator_action_available": False,
            "scheduler_decision": scheduler_decision,
            "latest_control_state": dict(latest_control_state),
            "operation_lock_status": dict(operation_lock_status),
            "dispatch_blockers": [
                item.value for item in _unique_blockers(dispatch_blockers)
            ],
            "scheduler_dispatchable": False,
            "would_dispatch_if_live_enabled": would_dispatch,
            "scheduler_invoked": False,
            "sweep_runner_invoked": False,
            "coinbase_orders_submitted": False,
            "live_coinbase_orders_ran": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        },
    }


def _build_retry_execution_contract(
    *,
    request: SpotSweepAutomationRunRequest,
    campaign_config: Mapping[str, Any] | None,
    sweep_records: list[dict[str, Any]],
    control_records: list[Any],
) -> dict[str, Any]:
    retry_plan: dict[str, Any] | None = None
    if campaign_config is not None:
        retry_plan = build_spot_campaign_retry_plan(
            config=campaign_config,
            sweep_records=sweep_records,
        )

    if not retry_plan or retry_plan.get("retry_status") != SpotCampaignStatus.READY.value:
        decision = SpotSweepAutomationExecutionDecision.RETRY_EXECUTION_NO_READY_PLAN
        blockers = [SpotSweepAutomationExecutionBlocker.RETRY_EXECUTION_NO_READY_PLAN]
        retry_plan_id = None
        retry_plan_ready = False
        retry_intent_accepted = False
    else:
        retry_plan_id = _retry_plan_id(retry_plan)
        retry_plan_ready = True
        retry_intent_accepted = _retry_intent_accepted(
            control_records=control_records,
            retry_plan_id=retry_plan_id,
        )
        if retry_intent_accepted:
            decision = (
                SpotSweepAutomationExecutionDecision.RETRY_EXECUTION_READY_LIVE_DISABLED
            )
            blockers = [
                SpotSweepAutomationExecutionBlocker.RETRY_EXECUTION_LIVE_DISABLED
            ]
        else:
            decision = SpotSweepAutomationExecutionDecision.RETRY_EXECUTION_BLOCKED
            blockers = [SpotSweepAutomationExecutionBlocker.RETRY_INTENT_NOT_ACCEPTED]

    return {
        "decision": decision,
        "blocker_enums": _unique_blockers(blockers),
        "data": {
            "contract_status": NO_LIVE_CONTRACT_STATUS.value,
            "decision": decision.value,
            "route": SPOT_SWEEP_AUTOMATION_RUN_ROUTE,
            "backend_owned": True,
            "operator_action_available": False,
            "retry_plan_id": retry_plan_id,
            "retry_plan_ready": retry_plan_ready,
            "retry_intent_accepted": retry_intent_accepted,
            "retry_blockers": [item.value for item in _unique_blockers(blockers)],
            "retryable_product_ids": list(
                (retry_plan or {}).get("retryable_product_ids") or []
            ),
            "source_run_id": (retry_plan or {}).get("source_run_id"),
            "source_run_status": (retry_plan or {}).get("source_run_status"),
            "retry_executor_invoked": False,
            "sweep_runner_invoked": False,
            "coinbase_orders_submitted": False,
            "live_coinbase_orders_ran": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        },
    }


def _build_scheduler_executor_admission_contract(
    *,
    request: SpotSweepAutomationRunRequest,
    scheduler_contract: Mapping[str, Any],
    recovery_gate_contract: Mapping[str, Any],
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
) -> dict[str, Any]:
    source_ready = bool(
        (scheduler_contract.get("data") or {}).get("would_dispatch_if_live_enabled")
    )
    return _build_executor_admission_contract(
        request=request,
        admission_decision=admission_decision,
        source_contract_ready=source_ready,
        source_contract_decision=scheduler_contract["decision"].value,
        recovery_gate_contract=recovery_gate_contract,
        source_not_ready_decision=(
            SpotSweepAutomationExecutionDecision.SCHEDULER_EXECUTOR_SOURCE_NOT_READY
        ),
        recovery_gate_blocked_decision=(
            SpotSweepAutomationExecutionDecision.SCHEDULER_EXECUTOR_RECOVERY_GATE_BLOCKED
        ),
        admission_blocked_decision=(
            SpotSweepAutomationExecutionDecision.SCHEDULER_EXECUTOR_ADMISSION_BLOCKED
        ),
        admission_ready_decision=(
            SpotSweepAutomationExecutionDecision.SCHEDULER_EXECUTOR_ADMISSION_READY
        ),
        executor_invoked_key="scheduler_executor_invoked",
    )


def _build_retry_executor_admission_contract(
    *,
    request: SpotSweepAutomationRunRequest,
    retry_contract: Mapping[str, Any],
    recovery_gate_contract: Mapping[str, Any],
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
) -> dict[str, Any]:
    retry_data = retry_contract.get("data") or {}
    source_ready = bool(
        retry_data.get("retry_plan_ready") and retry_data.get("retry_intent_accepted")
    )
    return _build_executor_admission_contract(
        request=request,
        admission_decision=admission_decision,
        source_contract_ready=source_ready,
        source_contract_decision=retry_contract["decision"].value,
        recovery_gate_contract=recovery_gate_contract,
        source_not_ready_decision=(
            SpotSweepAutomationExecutionDecision.RETRY_EXECUTOR_SOURCE_NOT_READY
        ),
        recovery_gate_blocked_decision=(
            SpotSweepAutomationExecutionDecision.RETRY_EXECUTOR_RECOVERY_GATE_BLOCKED
        ),
        admission_blocked_decision=(
            SpotSweepAutomationExecutionDecision.RETRY_EXECUTOR_ADMISSION_BLOCKED
        ),
        admission_ready_decision=(
            SpotSweepAutomationExecutionDecision.RETRY_EXECUTOR_ADMISSION_READY
        ),
        executor_invoked_key="retry_executor_invoked",
    )


def _build_executor_admission_contract(
    *,
    request: SpotSweepAutomationRunRequest,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
    source_contract_ready: bool,
    source_contract_decision: str,
    recovery_gate_contract: Mapping[str, Any],
    source_not_ready_decision: SpotSweepAutomationExecutionDecision,
    recovery_gate_blocked_decision: SpotSweepAutomationExecutionDecision,
    admission_blocked_decision: SpotSweepAutomationExecutionDecision,
    admission_ready_decision: SpotSweepAutomationExecutionDecision,
    executor_invoked_key: str,
) -> dict[str, Any]:
    admission_allowed = bool(admission_decision and admission_decision.allowed)
    recovery_gate_data = recovery_gate_contract.get("data") or {}
    recovery_gate_blocks_execution = bool(
        recovery_gate_data.get("recovery_gate_blocks_execution")
    )
    executor_ready_for_admission = bool(
        source_contract_ready and not recovery_gate_blocks_execution
    )
    recovery_gate_blockers = [
        str(value)
        for value in recovery_gate_data.get("blockers") or []
        if str(value or "").strip()
    ]
    decision = (
        source_not_ready_decision
        if not source_contract_ready
        else recovery_gate_blocked_decision
        if recovery_gate_blocks_execution
        else admission_ready_decision
        if admission_allowed
        else admission_blocked_decision
    )
    admission_blockers = (
        [blocker.value for blocker in admission_decision.blockers]
        if admission_decision is not None
        else [
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED.value,
            AdminApiLiveAdmissionBlocker.APPROVAL_SNAPSHOT_MISSING.value,
            AdminApiLiveAdmissionBlocker.ADMISSION_AUDIT_MISSING.value,
            AdminApiLiveAdmissionBlocker.CAP_GUARD_MISSING.value,
            AdminApiLiveAdmissionBlocker.RECONCILIATION_PLAN_MISSING.value,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED.value,
        ]
    )
    data = {
        "contract_status": NO_LIVE_CONTRACT_STATUS.value,
        "decision": decision.value,
        "route": SPOT_SWEEP_AUTOMATION_RUN_ROUTE,
        "backend_owned": True,
        "operator_action_available": False,
        "source_contract_ready_for_admission": source_contract_ready,
        "source_contract_decision": source_contract_decision,
        "recovery_gate_attached": True,
        "recovery_gate_status": recovery_gate_data.get("recovery_gate_status"),
        "recovery_gate_blocks_execution": recovery_gate_blocks_execution,
        "recovery_gate_blockers": recovery_gate_blockers,
        "executor_ready_for_admission": executor_ready_for_admission,
        "admission_attached": admission_decision is not None,
        "admission_allowed": admission_allowed,
        "admission_status": (
            admission_decision.status.value
            if admission_decision is not None
            else AdminApiGateStatus.BLOCKED.value
        ),
        "admission_blockers": admission_blockers,
        "required_gate_chain": [
            AdminApiLiveReadinessPrecondition.APPROVAL_SNAPSHOT.value,
            AdminApiLiveReadinessPrecondition.ADMISSION_AUDIT_TRAIL.value,
            AdminApiLiveReadinessPrecondition.CAP_GUARD_CONTRACT.value,
            AdminApiLiveReadinessPrecondition.SWEEP_RECOVERY_GATE_CLEAR.value,
            AdminApiLiveReadinessPrecondition.RECONCILIATION_PLAN.value,
            AdminApiLiveReadinessPrecondition.LIVE_EXECUTION_SERVICE.value,
            AdminApiLiveReadinessPrecondition.BROWSER_BFF_BOUNDARY.value,
        ],
        "manual_live_acknowledgement_present": bool(
            request.manual_live_acknowledgement
        ),
        "scheduler_executor_invoked": False,
        "retry_executor_invoked": False,
        "sweep_runner_invoked": False,
        "coinbase_orders_submitted": False,
        "live_coinbase_orders_ran": False,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    }
    data[executor_invoked_key] = False
    return {"decision": decision, "data": data}


def _build_recovery_gate_contract(
    *,
    request: SpotSweepAutomationRunRequest,
    sweep_records: list[dict[str, Any]],
    sweep_state_file: str | Path,
) -> dict[str, Any]:
    raw_plan = build_sweep_recovery_gate_plan(
        records=sweep_records,
        state_file=Path(sweep_state_file),
        config_id=request.sweep_config_id,
    )
    recovery_gate_plan = dict(raw_plan)
    recovery_gate_plan.pop("backfill_orders", None)
    recovery_gate_plan["backfill_orders_included"] = False
    planned_reconciliation_run_count = int(
        recovery_gate_plan.get("planned_reconciliation_run_count") or 0
    )
    candidate_backfill_order_count = int(
        recovery_gate_plan.get("candidate_backfill_order_count") or 0
    )
    planned_backfill_order_count = int(
        recovery_gate_plan.get("planned_backfill_order_count") or 0
    )
    runs_needing_reconciliation = _string_list(
        recovery_gate_plan.get("runs_needing_reconciliation") or []
    )
    runs_needing_backfill = _string_list(
        recovery_gate_plan.get("runs_needing_backfill") or []
    )
    recovery_gate_blocks_execution = bool(
        planned_reconciliation_run_count or planned_backfill_order_count
    )
    decision = (
        SpotSweepAutomationExecutionDecision.RECOVERY_GATE_BLOCKED
        if recovery_gate_blocks_execution
        else SpotSweepAutomationExecutionDecision.RECOVERY_GATE_PASSED
    )
    gate_status = (
        AdminApiGateStatus.BLOCKED
        if recovery_gate_blocks_execution
        else AdminApiGateStatus.PASSED
    )
    blockers = (
        [SpotSweepAutomationExecutionBlocker.RECOVERY_GATE_PENDING]
        if recovery_gate_blocks_execution
        else []
    )

    return {
        "decision": decision,
        "blocker_enums": blockers,
        "data": {
            "contract_status": AdminApiModuleSupportStatus.READ_ONLY_READY.value,
            "decision": decision.value,
            "route": SPOT_SWEEP_AUTOMATION_RUN_ROUTE,
            "backend_owned": True,
            "operator_action_available": False,
            "sweep_config_id": request.sweep_config_id,
            "recovery_gate_status": gate_status.value,
            "recovery_gate_blocks_execution": recovery_gate_blocks_execution,
            "planned_reconciliation_run_count": planned_reconciliation_run_count,
            "candidate_backfill_order_count": candidate_backfill_order_count,
            "planned_backfill_order_count": planned_backfill_order_count,
            "runs_needing_reconciliation": runs_needing_reconciliation,
            "runs_needing_backfill": runs_needing_backfill,
            "recovery_gate_plan": recovery_gate_plan,
            "blockers": [item.value for item in blockers],
            "required_gate_chain": [
                "sweep_recovery_gate_clear",
                "scheduler_dispatch_review_contract",
                "retry_execution_review_contract",
                "sweep_reconciliation_execution_contract",
                "post_live_reconciliation",
                "audit_link",
            ],
            "recovery_executor_invoked": False,
            "reconciliation_executor_invoked": False,
            "reconciliation_executed": False,
            "fill_backfill_executed": False,
            "order_state_mutated": False,
            "exchange_state_mutated": False,
            "coinbase_read_attempted": False,
            "coinbase_orders_submitted": False,
            "live_coinbase_orders_ran": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        },
    }


def _build_reconciliation_execution_contract(
    *,
    recovery_gate_contract: Mapping[str, Any],
) -> dict[str, Any]:
    decision = (
        SpotSweepAutomationExecutionDecision.RECONCILIATION_EXECUTION_BOUNDARY_LIVE_DISABLED
    )
    recovery_gate_data = recovery_gate_contract.get("data") or {}
    return {
        "decision": decision,
        "data": {
            "contract_status": NO_LIVE_CONTRACT_STATUS.value,
            "decision": decision.value,
            "route": SPOT_SWEEP_AUTOMATION_RUN_ROUTE,
            "backend_owned": True,
            "operator_action_available": False,
            "reconciliation_execution_allowed": False,
            "recovery_gate_status": recovery_gate_data.get("recovery_gate_status"),
            "recovery_gate_blocks_execution": bool(
                recovery_gate_data.get("recovery_gate_blocks_execution")
            ),
            "required_gate_chain": [
                "sweep_recovery_gate_clear",
                "scheduler_dispatch_review_contract",
                "retry_execution_review_contract",
                "sweep_reconciliation_execution_contract",
                "post_live_reconciliation",
                "audit_link",
            ],
            "blockers": [
                (
                    SpotSweepAutomationExecutionBlocker.RECONCILIATION_EXECUTION_CONTRACT_REQUIRED.value
                )
            ],
            "reconciliation_executor_invoked": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "exchange_state_mutated": False,
            "coinbase_read_attempted": False,
            "coinbase_orders_submitted": False,
            "live_coinbase_orders_ran": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        },
    }


def _build_live_execution_contract() -> dict[str, Any]:
    decision = SpotSweepAutomationExecutionDecision.LIVE_EXECUTION_BOUNDARY_DISABLED
    return {
        "decision": decision,
        "data": {
            "contract_status": NO_LIVE_CONTRACT_STATUS.value,
            "decision": decision.value,
            "route": SPOT_SWEEP_AUTOMATION_RUN_ROUTE,
            "backend_owned": True,
            "operator_action_available": False,
            "live_execution_enabled": False,
            "live_service_invoked": False,
            "live_adapter_invoked": False,
            "required_gate_chain": [
                "approval_snapshot",
                "admission_audit",
                "cap_guard_decision",
                "scheduler_dispatch_review_contract",
                "retry_execution_review_contract",
                "reconciliation_execution_boundary",
                "sweep_live_execution_contract",
                "post_live_reconciliation",
            ],
            "blockers": [
                SpotSweepAutomationExecutionBlocker.LIVE_EXECUTION_DISABLED.value,
                SpotSweepAutomationExecutionBlocker.LIVE_EXECUTION_CONTRACT_REQUIRED.value,
            ],
            "scheduler_invoked": False,
            "sweep_runner_invoked": False,
            "coinbase_orders_submitted": False,
            "live_coinbase_orders_ran": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        },
    }


def _latest_campaign_config_for_sweep(
    *,
    campaign_records: list[dict[str, Any]],
    sweep_config_id: str,
) -> dict[str, Any] | None:
    for record in reversed(campaign_records):
        config = record.get("config")
        if not isinstance(config, Mapping):
            continue
        try:
            normalized = normalize_spot_campaign_config(config)
        except ValueError:
            continue
        if normalized.get("sweep_config_id") == sweep_config_id:
            return normalized
    return None


def _retry_plan_id(retry_plan: Mapping[str, Any]) -> str:
    return (
        f"{SPOT_SWEEP_RETRY_PLAN_PREFIX}:"
        f"{retry_plan.get('sweep_config_id')}:"
        f"{retry_plan.get('source_run_id') or 'latest'}"
    )


def _retry_intent_accepted(
    *,
    control_records: list[Any],
    retry_plan_id: str,
) -> bool:
    for record in control_records:
        if record.control_action != SpotSweepAutomationControlAction.ACCEPT_RETRY:
            continue
        if record.retry_plan_id == retry_plan_id:
            return True
    return False


def _operation_lock_busy(operation_lock_status: Mapping[str, Any]) -> bool:
    return bool(operation_lock_status.get("exists") and not operation_lock_status.get("stale"))


def _string_list(values: list[Any]) -> list[str]:
    return [text for text in (str(value or "").strip() for value in values) if text]


def _unique_blockers(
    blockers: list[SpotSweepAutomationExecutionBlocker],
) -> list[SpotSweepAutomationExecutionBlocker]:
    seen: set[SpotSweepAutomationExecutionBlocker] = set()
    ordered: list[SpotSweepAutomationExecutionBlocker] = []
    for blocker in blockers:
        if blocker in seen:
            continue
        seen.add(blocker)
        ordered.append(blocker)
    return ordered
