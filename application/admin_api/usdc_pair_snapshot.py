"""Durable M58 USDC pair snapshot evidence for Admin API automation."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    UsdcPairSnapshotAllowlistRunStateProductItem,
    UsdcPairSnapshotOrderPlanAllowlistReadinessProductItem,
    UsdcPairSnapshotOrderPlanRowItem,
    UsdcPairSnapshotRowItem,
)


class UsdcPairSnapshotRunRecord(BaseModel):
    """Append-only backend dry-run snapshot record."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    side: str = Field(min_length=1)
    max_notional_per_product_usdc: str = Field(min_length=1)
    product_ids: list[str] = Field(default_factory=list)
    account_id: str | None = None
    portfolio_id: str | None = None
    dry_run: bool = True
    snapshot_rows: list[UsdcPairSnapshotRowItem] = Field(default_factory=list)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    source: str = "admin_api_usdc_pair_snapshot_log"


class UsdcPairSnapshotOrderPlanRecord(BaseModel):
    """Append-only backend dry-run order-plan evidence record."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)
    snapshot_run_id: str = Field(min_length=1)
    planned_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    side: str = Field(min_length=1)
    max_notional_per_product_usdc: str = Field(min_length=1)
    max_total_notional_usdc: str = Field(min_length=1)
    planned_total_notional_usdc: str = "0"
    product_ids: list[str] = Field(default_factory=list)
    account_id: str | None = None
    portfolio_id: str | None = None
    time_in_force: str = Field(min_length=1)
    dry_run: bool = True
    order_plan_rows: list[UsdcPairSnapshotOrderPlanRowItem] = Field(
        default_factory=list
    )
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    source: str = "admin_api_usdc_pair_snapshot_order_plan_log"


class UsdcPairSnapshotOrderPlanLiveReadinessRecord(BaseModel):
    """Append-only backend no-live Phase E readiness evidence record."""

    model_config = ConfigDict(extra="forbid")

    readiness_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    snapshot_run_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    side: str = Field(min_length=1)
    order_count: int = 1
    single_order_only: bool = True
    minimum_order_size_preferred: bool = True
    reference_bid_price: str = Field(min_length=1)
    reference_bid_price_source: str = Field(min_length=1)
    reference_bid_price_captured_at: str = Field(min_length=1)
    reference_bid_price_freshness_status: str = Field(min_length=1)
    last_filled_price: str = Field(min_length=1)
    last_filled_price_source: str = Field(min_length=1)
    last_filled_price_captured_at: str = Field(min_length=1)
    last_filled_price_freshness_status: str = Field(min_length=1)
    intended_limit_price: str = Field(min_length=1)
    far_from_bid_status: str = Field(min_length=1)
    snapshot_non_fill_status: str = Field(min_length=1)
    submitted_notional_usdc: str = Field(min_length=1)
    max_submitted_notional_usdc: str = Field(min_length=1)
    max_executed_notional_usdc: str = Field(min_length=1)
    planned_notional_usdc: str = Field(min_length=1)
    base_size: str | None = None
    quote_size: str | None = None
    min_base_size: str | None = None
    min_quote_size: str | None = None
    preflight_passed: bool = False
    preflight_blockers: list[str] = Field(default_factory=list)
    submit_route_ready: bool = False
    submit_blockers: list[str] = Field(default_factory=list)
    cancel_before_additional_orders: bool = True
    cancel_rollback_plan_ref: str = Field(min_length=1)
    full_snapshot_fill_test: bool = False
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    cap_guard_max_submitted_notional_usdc: str = Field(default="0", min_length=1)
    cap_guard_wallet_check_status: str = Field(
        default="legacy_unverified",
        min_length=1,
    )
    cap_guard_wallet_available_notional_usdc: str = Field(default="0", min_length=1)
    cap_guard_wallet_check_source: str = Field(
        default="legacy_record_missing_cap_guard_evidence",
        min_length=1,
    )
    reconciliation_plan_id: str = Field(min_length=1)
    live_service_decision_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    detail: str = Field(min_length=1)
    source: str = "admin_api_usdc_pair_snapshot_order_plan_live_readiness_log"


class UsdcPairSnapshotOrderPlanAllowlistReadinessRecord(BaseModel):
    """Append-only backend no-live Phase F allowlist-readiness evidence."""

    model_config = ConfigDict(extra="forbid")

    readiness_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    snapshot_run_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    product_ids: list[str] = Field(default_factory=list)
    selected_product_count: int = 0
    max_products: int = 1
    candidate_product_ids: list[str] = Field(default_factory=list)
    blocked_product_ids: list[str] = Field(default_factory=list)
    cap_exhausted_product_ids: list[str] = Field(default_factory=list)
    missing_product_ids: list[str] = Field(default_factory=list)
    retryable_product_ids: list[str] = Field(default_factory=list)
    recovery_required_product_ids: list[str] = Field(default_factory=list)
    partial_success_status: str = "blocked"
    failure_isolation_status: str = "blocked"
    run_rate_limit_status: str = "blocked"
    retry_budget_status: str = "blocked"
    recovery_readiness_status: str = "blocked"
    retry_budget_per_product: int = 0
    run_rate_limit_budget_ref: str | None = None
    cancel_recovery_plan_ref: str | None = None
    fanout_readiness_status: str = "blocked"
    fanout_blockers: list[str] = Field(default_factory=list)
    product_readiness_rows: list[
        UsdcPairSnapshotOrderPlanAllowlistReadinessProductItem
    ] = Field(default_factory=list)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    detail: str = Field(min_length=1)
    source: str = "admin_api_usdc_pair_snapshot_order_plan_allowlist_readiness_log"


class UsdcPairSnapshotAllowlistRunStateRecord(BaseModel):
    """Append-only backend no-live Phase F allowlist run-state evidence."""

    model_config = ConfigDict(extra="forbid")

    run_state_id: str = Field(min_length=1)
    readiness_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    snapshot_run_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    execution_mode: str = Field(min_length=1)
    max_fanout_notional_usdc: str = Field(min_length=1)
    planned_fanout_notional_usdc: str = "0"
    allocated_fanout_notional_usdc: str = "0"
    fanout_cap_remaining_usdc: str = "0"
    fanout_cap_overage_usdc: str = "0"
    fanout_cap_allocation_status: str = Field(
        default="legacy_unverified",
        min_length=1,
    )
    wallet_allocation_status: str = Field(
        default="legacy_unverified",
        min_length=1,
    )
    wallet_available_notional_usdc: str = "0"
    wallet_allocated_notional_usdc: str = "0"
    wallet_remaining_usdc: str = "0"
    wallet_allocation_blockers: list[str] = Field(default_factory=list)
    live_wallet_reservation_status: str = Field(
        default="legacy_unverified",
        min_length=1,
    )
    live_wallet_reservation_ids: list[str] = Field(default_factory=list)
    live_wallet_reserved_notional_usdc: str = "0"
    live_wallet_debit_ids: list[str] = Field(default_factory=list)
    live_wallet_debited_notional_usdc: str = "0"
    live_wallet_release_ids: list[str] = Field(default_factory=list)
    live_wallet_released_notional_usdc: str = "0"
    live_wallet_reservation_blockers: list[str] = Field(default_factory=list)
    live_wallet_active_reservation_overcommit_run_state_ids: list[str] = Field(
        default_factory=list
    )
    live_wallet_active_reserved_notional_usdc: str = "0"
    live_wallet_overcommit_attempted_notional_usdc: str = "0"
    live_wallet_ledger_status: str = Field(default="blocked_no_live", min_length=1)
    live_wallet_ledger_id: str | None = None
    live_wallet_ledger_balance_status: str = Field(
        default="missing_live",
        min_length=1,
    )
    live_wallet_ledger_overcommit_prevention_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    live_wallet_ledger_debit_release_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    live_wallet_ledger_wallet_available_notional_usdc: str = "0"
    live_wallet_ledger_reserved_notional_usdc: str = "0"
    live_wallet_ledger_debited_notional_usdc: str = "0"
    live_wallet_ledger_released_notional_usdc: str = "0"
    live_wallet_ledger_blockers: list[str] = Field(
        default_factory=lambda: [
            "live_wallet_balance_evidence_missing",
            "live_wallet_ledger_overcommit_prevention_missing",
            "live_wallet_ledger_debit_release_missing",
        ]
    )
    live_readiness_status: str = Field(
        default="legacy_unverified",
        min_length=1,
    )
    live_ready_product_ids: list[str] = Field(default_factory=list)
    live_readiness_missing_product_ids: list[str] = Field(default_factory=list)
    live_readiness_blocked_product_ids: list[str] = Field(default_factory=list)
    live_readiness_blockers: list[str] = Field(default_factory=list)
    fanout_notional_status: str = Field(min_length=1)
    fanout_execution_scope_status: str = Field(
        default="standing_cap_authorized",
        min_length=1,
    )
    fanout_execution_scope_blockers: list[str] = Field(default_factory=list)
    product_ids: list[str] = Field(default_factory=list)
    queued_product_ids: list[str] = Field(default_factory=list)
    blocked_product_ids: list[str] = Field(default_factory=list)
    retryable_product_ids: list[str] = Field(default_factory=list)
    recovery_required_product_ids: list[str] = Field(default_factory=list)
    queued_product_count: int = 0
    blocked_product_count: int = 0
    retryable_product_count: int = 0
    recovery_required_product_count: int = 0
    run_lock_status: str = Field(min_length=1)
    run_lock_ref: str | None = None
    run_lock_recorded_at: str | None = None
    run_lock_conflict_run_state_id: str | None = None
    pause_resume_status: str = Field(min_length=1)
    abort_status: str = Field(min_length=1)
    rate_limit_status: str = Field(min_length=1)
    rate_limit_window_ref: str | None = None
    rate_limit_window_conflict_run_state_id: str | None = None
    rate_limit_max_orders_per_window: int = 5
    rate_limit_window_seconds: int = 1
    rate_limit_window_started_at: str | None = None
    rate_limit_window_expires_at: str | None = None
    rate_limit_attempted_order_count: int = 0
    rate_limit_window_remaining_order_count: int = 5
    rate_limit_window_overage_order_count: int = 0
    rate_limit_window_within_cap: bool = True
    retry_budget_status: str = Field(min_length=1)
    retry_backoff_status: str = Field(default="not_required", min_length=1)
    retry_backoff_ref: str | None = None
    retry_backoff_conflict_run_state_id: str | None = None
    cancel_recovery_plan_ref: str | None = None
    recovery_ref_conflict_run_state_id: str | None = None
    recovery_status: str = Field(min_length=1)
    partial_success_status: str = Field(min_length=1)
    runtime_fanout_execution_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_worker_ref: str | None = None
    runtime_fanout_execution_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_worker_missing",
            "runtime_fanout_wallet_ledger_live_semantics_missing",
            "runtime_fanout_retry_recovery_semantics_missing",
        ]
    )
    runtime_fanout_price_freshness_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_price_freshness_ref: str | None = None
    runtime_fanout_price_freshness_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_price_freshness_binding_missing",
            "runtime_fanout_reference_bid_recheck_missing",
            "runtime_fanout_last_fill_distance_recheck_missing",
        ]
    )
    runtime_fanout_live_service_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_live_service_ref: str | None = None
    runtime_fanout_live_service_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_live_service_binding_missing",
            "runtime_fanout_enabled_decision_recheck_missing",
            "runtime_fanout_live_service_scope_recheck_missing",
        ]
    )
    runtime_fanout_admission_audit_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_admission_audit_ref: str | None = None
    runtime_fanout_admission_audit_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_admission_audit_binding_missing",
            "runtime_fanout_admission_decision_recheck_missing",
            "runtime_fanout_operator_intent_audit_recheck_missing",
        ]
    )
    runtime_fanout_reconciliation_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_reconciliation_ref: str | None = None
    runtime_fanout_reconciliation_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_reconciliation_binding_missing",
            "runtime_fanout_reconciliation_plan_recheck_missing",
            "runtime_fanout_exchange_readback_recheck_missing",
        ]
    )
    runtime_fanout_cap_guard_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_cap_guard_ref: str | None = None
    runtime_fanout_cap_guard_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_cap_guard_binding_missing",
            "runtime_fanout_submitted_notional_guard_missing",
            "runtime_fanout_wallet_available_guard_missing",
        ]
    )
    runtime_fanout_wallet_ledger_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_wallet_ledger_ref: str | None = None
    runtime_fanout_wallet_ledger_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_live_wallet_ledger_missing",
            "runtime_fanout_wallet_overcommit_binding_missing",
            "runtime_fanout_wallet_debit_release_binding_missing",
        ]
    )
    runtime_fanout_retry_recovery_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_retry_recovery_ref: str | None = None
    runtime_fanout_retry_recovery_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_retry_budget_binding_missing",
            "runtime_fanout_recovery_replay_binding_missing",
            "runtime_fanout_partial_failure_policy_missing",
        ]
    )
    runtime_fanout_release_review_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_release_review_ref: str | None = None
    runtime_fanout_release_review_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_release_gate_uncleared",
            "runtime_fanout_contextless_review_missing",
        ]
    )
    runtime_fanout_rate_limit_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    runtime_fanout_rate_limit_ref: str | None = None
    runtime_fanout_rate_limit_blockers: list[str] = Field(
        default_factory=lambda: [
            "runtime_fanout_rate_limit_worker_missing",
            "runtime_fanout_rate_limit_runtime_binding_missing",
            "runtime_fanout_rate_limit_release_gate_uncleared",
        ]
    )
    scheduler_execution_status: str = Field(default="blocked_no_live", min_length=1)
    scheduler_execution_blockers: list[str] = Field(
        default_factory=lambda: ["scheduler_blocked"]
    )
    scheduler_unattended_execution: str = Field(default="not_run", min_length=1)
    scheduler_standing_cap_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    scheduler_standing_cap_ref: str | None = None
    scheduler_standing_cap_blockers: list[str] = Field(
        default_factory=lambda: [
            "scheduler_standing_cap_policy_missing",
            "scheduler_spot_notional_cap_proof_missing",
            "scheduler_perpetual_notional_cap_proof_missing",
        ]
    )
    scheduler_wallet_ledger_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    scheduler_wallet_ledger_ref: str | None = None
    scheduler_wallet_ledger_blockers: list[str] = Field(
        default_factory=lambda: [
            "scheduler_live_wallet_ledger_missing",
            "scheduler_wallet_overcommit_prevention_missing",
            "scheduler_wallet_debit_release_missing",
        ]
    )
    scheduler_release_review_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    scheduler_release_review_ref: str | None = None
    scheduler_release_review_blockers: list[str] = Field(
        default_factory=lambda: [
            "scheduler_release_gate_uncleared",
            "scheduler_contextless_review_missing",
        ]
    )
    scheduler_worker_status: str = Field(default="blocked_no_live", min_length=1)
    scheduler_worker_ref: str | None = None
    scheduler_worker_blockers: list[str] = Field(
        default_factory=lambda: [
            "scheduler_worker_missing",
            "scheduler_durable_worker_missing",
            "scheduler_worker_idempotency_missing",
        ]
    )
    scheduler_rate_limit_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    scheduler_rate_limit_ref: str | None = None
    scheduler_rate_limit_blockers: list[str] = Field(
        default_factory=lambda: [
            "scheduler_rate_limit_worker_missing",
            "scheduler_rate_limit_runtime_binding_missing",
            "scheduler_rate_limit_release_gate_uncleared",
        ]
    )
    scheduler_runtime_control_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    scheduler_runtime_control_ref: str | None = None
    scheduler_runtime_control_blockers: list[str] = Field(
        default_factory=lambda: [
            "scheduler_pause_control_missing",
            "scheduler_abort_control_missing",
            "scheduler_runtime_control_binding_missing",
        ]
    )
    scheduler_retry_policy_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    scheduler_retry_policy_ref: str | None = None
    scheduler_retry_policy_blockers: list[str] = Field(
        default_factory=lambda: [
            "scheduler_retry_budget_policy_missing",
            "scheduler_retry_backoff_binding_missing",
            "scheduler_retry_release_gate_uncleared",
        ]
    )
    scheduler_cadence_status: str = Field(default="disabled_no_live", min_length=1)
    scheduler_cadence_blockers: list[str] = Field(
        default_factory=lambda: [
            "scheduler_worker_missing",
            "scheduler_cadence_not_configured",
            "scheduler_release_gate_uncleared",
        ]
    )
    scheduler_recovery_runbook_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    scheduler_recovery_runbook_ref: str | None = None
    scheduler_recovery_runbook_blockers: list[str] = Field(
        default_factory=lambda: [
            "scheduler_recovery_runbook_missing",
            "scheduler_recovery_worker_missing",
            "scheduler_reconciliation_replay_missing",
        ]
    )
    fanout_execution_status: str = "blocked"
    run_state_status: str = "blocked"
    fanout_blockers: list[str] = Field(default_factory=list)
    product_states: list[UsdcPairSnapshotAllowlistRunStateProductItem] = Field(
        default_factory=list
    )
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    detail: str = Field(min_length=1)
    source: str = "admin_api_usdc_pair_snapshot_allowlist_run_state_log"


class UsdcPairSnapshotLiveWalletReservationRecord(BaseModel):
    """Append-only backend no-live M58 live-wallet reservation evidence."""

    model_config = ConfigDict(extra="forbid")

    reservation_id: str = Field(min_length=1)
    run_state_id: str = Field(min_length=1)
    readiness_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    snapshot_run_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    reserved_notional_usdc: str = Field(min_length=1)
    wallet_available_notional_usdc: str = Field(min_length=1)
    reservation_status: str = Field(default="reserved_no_live", min_length=1)
    debit_status: str = Field(default="missing_no_live", min_length=1)
    debit_id: str | None = None
    debited_notional_usdc: str = "0"
    release_status: str = Field(default="missing_no_live", min_length=1)
    release_id: str | None = None
    released_notional_usdc: str = "0"
    release_reason: str | None = None
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    detail: str = Field(min_length=1)
    source: str = "admin_api_usdc_pair_snapshot_live_wallet_reservation_log"


class UsdcPairSnapshotLiveWalletLedgerRecord(BaseModel):
    """Append-only backend M58 live-wallet ledger boundary evidence."""

    model_config = ConfigDict(extra="forbid")

    ledger_id: str = Field(min_length=1)
    run_state_id: str = Field(min_length=1)
    readiness_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    snapshot_run_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ledger_mode: str = Field(default="no_live_boundary", min_length=1)
    wallet_balance_source: str = Field(
        default="cap_guard_wallet_available_notional_no_live",
        min_length=1,
    )
    wallet_available_notional_usdc: str = "0"
    planned_fanout_notional_usdc: str = "0"
    allocated_fanout_notional_usdc: str = "0"
    reserved_notional_usdc: str = "0"
    debited_notional_usdc: str = "0"
    released_notional_usdc: str = "0"
    active_reserved_notional_usdc: str = "0"
    overcommit_attempted_notional_usdc: str = "0"
    ledger_status: str = Field(default="blocked_no_live", min_length=1)
    wallet_balance_status: str = Field(default="missing_live", min_length=1)
    overcommit_prevention_status: str = Field(
        default="blocked_no_live",
        min_length=1,
    )
    debit_release_status: str = Field(default="blocked_no_live", min_length=1)
    ledger_blockers: list[str] = Field(
        default_factory=lambda: [
            "live_wallet_balance_evidence_missing",
            "live_wallet_ledger_overcommit_prevention_missing",
            "live_wallet_ledger_debit_release_missing",
        ]
    )
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    detail: str = Field(min_length=1)
    source: str = "admin_api_usdc_pair_snapshot_live_wallet_ledger_log"


class UsdcPairSnapshotOrderPlanLiveSubmitRecord(BaseModel):
    """Append-only backend controlled-live submit/cancel evidence record."""

    model_config = ConfigDict(extra="forbid")

    submission_id: str = Field(min_length=1)
    readiness_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    snapshot_run_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    submitted_at: str | None = None
    cancelled_at: str | None = None
    side: str = Field(min_length=1)
    order_count: int = 1
    single_order_only: bool = True
    submitted_notional_usdc: str = Field(min_length=1)
    executed_notional_usdc: str = "0"
    max_executed_notional_usdc: str = Field(min_length=1)
    intended_limit_price: str = Field(min_length=1)
    reference_bid_price: str = Field(min_length=1)
    last_filled_price: str = Field(min_length=1)
    cancel_before_additional_orders: bool = True
    additional_orders_blocked: bool = True
    cancel_submitted: bool = False
    cancel_rollback_complete: bool = False
    cancel_rollback_plan_ref: str = Field(min_length=1)
    full_snapshot_fill_test: bool = False
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    live_service_decision_id: str = Field(min_length=1)
    coinbase_order_id: str | None = None
    coinbase_order_id_evidence_only: bool = True
    order_configuration: dict[str, Any] = Field(default_factory=dict)
    submit_result: dict[str, Any] = Field(default_factory=dict)
    cancel_result: dict[str, Any] = Field(default_factory=dict)
    operator_stop_conditions: list[str] = Field(default_factory=list)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    detail: str = Field(min_length=1)
    source: str = "admin_api_usdc_pair_snapshot_order_plan_live_submit_log"


class FileUsdcPairSnapshotRunStore:
    """Append-only JSONL store for M58 dry-run snapshot records."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_LOG_PATH")
            or Path("runtime_state") / "admin_api_usdc_pair_snapshot_runs.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: UsdcPairSnapshotRunRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.run_id

    def read_recent(self, *, limit: int = 100) -> list[UsdcPairSnapshotRunRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotRunRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(UsdcPairSnapshotRunRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_run_id(self, run_id: str) -> UsdcPairSnapshotRunRecord | None:
        """Return the latest record for ``run_id`` if present."""

        with self._lock:
            if not self.path.exists():
                return None
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                record = UsdcPairSnapshotRunRecord.model_validate_json(line)
            except ValueError:
                continue
            if record.run_id == run_id:
                return record
        return None

    def count_records(self) -> int:
        """Return the number of readable snapshot run records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotRunRecord.model_validate_json(line)
            except ValueError:
                continue
            count += 1
        return count


class FileUsdcPairSnapshotOrderPlanStore:
    """Append-only JSONL store for M58 dry-run order-plan records."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ORDER_PLAN_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_usdc_pair_snapshot_order_plans.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: UsdcPairSnapshotOrderPlanRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.plan_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[UsdcPairSnapshotOrderPlanRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotOrderPlanRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    UsdcPairSnapshotOrderPlanRecord.model_validate_json(line)
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_plan_id(
        self,
        plan_id: str,
    ) -> UsdcPairSnapshotOrderPlanRecord | None:
        """Return the latest record for ``plan_id`` if present."""

        with self._lock:
            if not self.path.exists():
                return None
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                record = UsdcPairSnapshotOrderPlanRecord.model_validate_json(line)
            except ValueError:
                continue
            if record.plan_id == plan_id:
                return record
        return None

    def count_records(self) -> int:
        """Return the number of readable order-plan records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotOrderPlanRecord.model_validate_json(line)
            except ValueError:
                continue
            count += 1
        return count


class FileUsdcPairSnapshotOrderPlanLiveReadinessStore:
    """Append-only JSONL store for M58 no-live Phase E readiness evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_usdc_pair_snapshot_order_plan_live_readiness.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: UsdcPairSnapshotOrderPlanLiveReadinessRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.readiness_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[UsdcPairSnapshotOrderPlanLiveReadinessRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotOrderPlanLiveReadinessRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    UsdcPairSnapshotOrderPlanLiveReadinessRecord.model_validate_json(
                        line
                    )
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def count_records(self) -> int:
        """Return the number of readable live-readiness records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotOrderPlanLiveReadinessRecord.model_validate_json(
                    line
                )
            except ValueError:
                continue
            count += 1
        return count


class FileUsdcPairSnapshotOrderPlanAllowlistReadinessStore:
    """Append-only JSONL store for M58 no-live Phase F allowlist evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_usdc_pair_snapshot_order_plan_allowlist_readiness.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(
        self,
        record: UsdcPairSnapshotOrderPlanAllowlistReadinessRecord,
    ) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.readiness_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[UsdcPairSnapshotOrderPlanAllowlistReadinessRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotOrderPlanAllowlistReadinessRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    UsdcPairSnapshotOrderPlanAllowlistReadinessRecord.model_validate_json(
                        line
                    )
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def count_records(self) -> int:
        """Return the number of readable allowlist-readiness records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotOrderPlanAllowlistReadinessRecord.model_validate_json(
                    line
                )
            except ValueError:
                continue
            count += 1
        return count

    def find_by_readiness_id(
        self,
        readiness_id: str,
    ) -> UsdcPairSnapshotOrderPlanAllowlistReadinessRecord | None:
        """Return the latest readable record for an allowlist readiness id."""

        return next(
            (
                record
                for record in self.read_recent(limit=500)
                if record.readiness_id == readiness_id
            ),
            None,
        )


class FileUsdcPairSnapshotAllowlistRunStateStore:
    """Append-only JSONL store for M58 no-live Phase F run-state evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_usdc_pair_snapshot_allowlist_run_states.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: UsdcPairSnapshotAllowlistRunStateRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.run_state_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[UsdcPairSnapshotAllowlistRunStateRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotAllowlistRunStateRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    UsdcPairSnapshotAllowlistRunStateRecord.model_validate_json(
                        line
                    )
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def count_records(self) -> int:
        """Return the number of readable allowlist run-state records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotAllowlistRunStateRecord.model_validate_json(line)
            except ValueError:
                continue
            count += 1
        return count

    def find_by_run_state_id(
        self,
        run_state_id: str,
    ) -> UsdcPairSnapshotAllowlistRunStateRecord | None:
        """Return the latest readable record for an allowlist run-state id."""

        return next(
            (
                record
                for record in self.read_recent(limit=500)
                if record.run_state_id == run_state_id
            ),
            None,
        )


class FileUsdcPairSnapshotLiveWalletReservationStore:
    """Append-only JSONL store for M58 no-live wallet reservation evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_LIVE_WALLET_RESERVATION_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_usdc_pair_snapshot_live_wallet_reservations.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: UsdcPairSnapshotLiveWalletReservationRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.reservation_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[UsdcPairSnapshotLiveWalletReservationRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotLiveWalletReservationRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    UsdcPairSnapshotLiveWalletReservationRecord.model_validate_json(
                        line
                    )
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_reservation_id(
        self,
        reservation_id: str,
    ) -> UsdcPairSnapshotLiveWalletReservationRecord | None:
        """Return the latest readable wallet reservation record for an id."""

        return next(
            (
                record
                for record in self.read_recent(limit=500)
                if record.reservation_id == reservation_id
            ),
            None,
        )

    def count_records(self) -> int:
        """Return the number of readable wallet reservation records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotLiveWalletReservationRecord.model_validate_json(line)
            except ValueError:
                continue
            count += 1
        return count


class FileUsdcPairSnapshotLiveWalletLedgerStore:
    """Append-only JSONL store for M58 live-wallet ledger boundary evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_LIVE_WALLET_LEDGER_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_usdc_pair_snapshot_live_wallet_ledger.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: UsdcPairSnapshotLiveWalletLedgerRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.ledger_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[UsdcPairSnapshotLiveWalletLedgerRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotLiveWalletLedgerRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    UsdcPairSnapshotLiveWalletLedgerRecord.model_validate_json(
                        line
                    )
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_ledger_id(
        self,
        ledger_id: str,
    ) -> UsdcPairSnapshotLiveWalletLedgerRecord | None:
        """Return the latest readable wallet ledger record for an id."""

        return next(
            (
                record
                for record in self.read_recent(limit=500)
                if record.ledger_id == ledger_id
            ),
            None,
        )

    def count_records(self) -> int:
        """Return the number of readable wallet ledger records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotLiveWalletLedgerRecord.model_validate_json(line)
            except ValueError:
                continue
            count += 1
        return count


class FileUsdcPairSnapshotOrderPlanLiveSubmitStore:
    """Append-only JSONL store for M58 controlled-live submit evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_usdc_pair_snapshot_order_plan_live_submit.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: UsdcPairSnapshotOrderPlanLiveSubmitRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.submission_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[UsdcPairSnapshotOrderPlanLiveSubmitRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotOrderPlanLiveSubmitRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    UsdcPairSnapshotOrderPlanLiveSubmitRecord.model_validate_json(
                        line
                    )
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def count_records(self) -> int:
        """Return the number of readable live-submission records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotOrderPlanLiveSubmitRecord.model_validate_json(line)
            except ValueError:
                continue
            count += 1
        return count

    def find_by_submission_id(
        self,
        submission_id: str,
    ) -> UsdcPairSnapshotOrderPlanLiveSubmitRecord | None:
        """Return the latest readable record for a submission id."""

        return next(
            (
                record
                for record in self.read_recent(limit=500)
                if record.submission_id == submission_id
            ),
            None,
        )

    def find_latest_for_readiness(
        self,
        *,
        readiness_id: str,
        product_id: str,
        client_order_id: str,
    ) -> UsdcPairSnapshotOrderPlanLiveSubmitRecord | None:
        """Return the latest submission evidence for a readiness row."""

        normalized_product_id = product_id.upper()
        return next(
            (
                record
                for record in self.read_recent(limit=500)
                if record.readiness_id == readiness_id
                and record.product_id.upper() == normalized_product_id
                and record.client_order_id == client_order_id
            ),
            None,
        )
