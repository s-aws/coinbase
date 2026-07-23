"""PostgreSQL durability for the local operator Automation control plane.

This module owns records and transitions only.  It imports no Coinbase client
and cannot dispatch a domain job.  Public Admin API projection and RBAC remain
in the application layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
from typing import Any, Generic, Literal, Mapping, TypeVar
import uuid

from core.enums import (
    OperatorAutomationControlPosture,
    OperatorAutomationDefinitionState,
    OperatorAutomationDomain,
    OperatorAutomationJobKind,
    OperatorAutomationRunState,
    OperatorAutomationScheduleKind,
)
from core.operator_spot_near_market_evidence import (
    NEAR_MARKET_POLICY_REVISION,
    near_market_preparation_evidence_sha256,
)
from core.operator_spot_minimum_size_evidence import (
    MINIMUM_SIZE_POLICY_REVISION,
    minimum_size_preparation_evidence_sha256,
)
from database.database import PostgresDB


_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ACTIVE_RUN_STATES = (
    OperatorAutomationRunState.CLAIMED,
    OperatorAutomationRunState.PREPARING,
    OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
    OperatorAutomationRunState.INVOCATION_STARTED,
    OperatorAutomationRunState.ACTIVE,
)
_PRE_INVOCATION_STATES = (
    OperatorAutomationRunState.CLAIMED,
    OperatorAutomationRunState.PREPARING,
    OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
)
_POST_INVOCATION_STATES = (
    OperatorAutomationRunState.INVOCATION_STARTED,
    OperatorAutomationRunState.ACTIVE,
)
_SPOT_JOB_KINDS = {
    OperatorAutomationJobKind.SPOT_CAMPAIGN,
    OperatorAutomationJobKind.SPOT_SWEEP,
    OperatorAutomationJobKind.SPOT_LADDER,
}
AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES = (
    "API_KEY_PERMISSIONS",
    "PORTFOLIO_CATALOG",
    "ACCOUNT_WALLET_BALANCES",
    "PRODUCT_METADATA",
    "BEST_BID_ASK",
    "FEE_SUMMARY",
    "EXACT_ORDER_RECONCILIATION",
    "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG",
)
_AUTOMATION_SPOT_ELIGIBILITY_V1_CATEGORIES = (
    AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:-1]
)
_AUTOMATION_SPOT_ELIGIBILITY_POLICY_REVISION = 2
_AUTOMATION_SPOT_NEAR_MARKET_ELIGIBILITY_POLICY_REVISION = 3
_AUTOMATION_SPOT_MINIMUM_SIZE_ELIGIBILITY_POLICY_REVISION = 4
_AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_POLICY_REVISION = 5
_AUTOMATION_SPOT_ELIGIBILITY_CATEGORY_SET = frozenset(
    AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
)
_AUTOMATION_SPOT_ELIGIBILITY_OUTCOMES = frozenset(
    {"SUCCEEDED", "REJECTED", "UNKNOWN"}
)
_AUTOMATION_SPOT_ELIGIBILITY_CYCLE_STATES = frozenset(
    {"OPEN", "SUCCEEDED", "REJECTED", "UNKNOWN"}
)
_AUTOMATION_SPOT_MUTATION_OUTCOMES = frozenset(
    {"ACCEPTED", "REJECTED", "UNKNOWN"}
)
_AUTOMATION_SPOT_EXACT_PREVIEW_UNKNOWN_FAILURE_CLASSES = frozenset(
    {
        "RESPONSE_SCHEMA_INVALID",
        "RESPONSE_DECODING_FAILURE",
        "HTTP_CLIENT_RESPONSE",
        "HTTP_SERVER_RESPONSE",
        "HTTP_REDIRECT_RESPONSE",
        "HTTP_RESPONSE_INVALID",
        "READ_TIMEOUT",
    }
)
_AUTOMATION_SPOT_EXACT_ZERO_PREVIEW_UNKNOWN_FAILURE_CLASSES = frozenset(
    {
        "REQUEST_COMPOSITION_FAILURE",
        "DNS_RESOLUTION_FAILURE",
        "TCP_CONNECTION_FAILURE",
        "CONNECT_TIMEOUT",
        "PROXY_FAILURE",
    }
)
_AUTOMATION_SPOT_INEXACT_PREVIEW_UNKNOWN_FAILURE_CLASSES = frozenset(
    {
        "SDK_INVOCATION_UNKNOWN",
        "TLS_OR_CERTIFICATE_FAILURE",
        "CONNECTION_RESET",
        "TRANSPORT_UNKNOWN",
    }
)
_AUTOMATION_SPOT_PREVIEW_REJECTION_CODES = frozenset(
    {
        "UNKNOWN_DOCUMENTED",
        "INSUFFICIENT_FUNDS",
        "SIZE_PRECISION",
        "PRICE_PRECISION",
        "BASE_SIZE_TOO_LARGE",
        "BASE_SIZE_TOO_SMALL",
        "QUOTE_SIZE_PRECISION",
        "QUOTE_SIZE_TOO_LARGE",
        "QUOTE_SIZE_TOO_SMALL",
        "PRICE_TOO_LARGE",
        "POST_ONLY_LIMIT_PRICE",
        "LIMIT_PRICE",
        "NO_LIQUIDITY",
        "PRODUCT_PRICE_BOOK_MISSING",
        "MARKET_TRADE_DATA_MISSING",
        "PRODUCT_INVALID",
        "PRODUCT_UNTRADABLE",
        "MARKET_STATE",
        "ORDER_CONFIGURATION",
        "POLICY",
        "OTHER_DOCUMENTED",
        "MULTIPLE_DOCUMENTED",
    }
)
AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY = (
    "operator_spot_automation_single_child_execution_adapter_v1"
)
AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY = (
    "operator_spot_automation_preview_gated_successor_candidate_v2"
)
AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY = (
    "operator_spot_automation_documented_market_freshness_successor_v3"
)
AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY = (
    "operator_spot_automation_near_market_successor_v4"
)
AUTOMATION_SPOT_NEAR_MARKET_V5_GOAL_KEY = (
    "operator_spot_automation_near_market_successor_v5"
)
AUTOMATION_SPOT_NEAR_MARKET_V6_GOAL_KEY = (
    "operator_spot_automation_near_market_successor_v6"
)
AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS = frozenset(
    {
        AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
        AUTOMATION_SPOT_NEAR_MARKET_V5_GOAL_KEY,
        AUTOMATION_SPOT_NEAR_MARKET_V6_GOAL_KEY,
    }
)
AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY = (
    "operator_spot_automation_minimum_size_successor_v7"
)
AUTOMATION_SPOT_MINIMUM_SIZE_V8_GOAL_KEY = (
    "operator_spot_automation_minimum_size_successor_v8"
)
AUTOMATION_SPOT_MINIMUM_SIZE_V9_GOAL_KEY = (
    "operator_spot_automation_minimum_size_successor_v9"
)
AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS = frozenset(
    {
        AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
        AUTOMATION_SPOT_MINIMUM_SIZE_V8_GOAL_KEY,
        AUTOMATION_SPOT_MINIMUM_SIZE_V9_GOAL_KEY,
    }
)
AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY = (
    "operator_spot_automation_atomic_market_snapshot_successor_v10"
)
AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V11_GOAL_KEY = (
    "operator_spot_automation_atomic_market_snapshot_successor_v11"
)
AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V12_GOAL_KEY = (
    "operator_spot_automation_atomic_market_snapshot_successor_v12"
)
AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_PREDECESSOR_GOAL_KEYS = frozenset(
    {
        AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
        AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V11_GOAL_KEY,
        AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V12_GOAL_KEY,
    }
)
AUTOMATION_SPOT_TRANSPORT_V13_GOAL_KEY = (
    "operator_spot_automation_transport_successor_v13"
)
AUTOMATION_SPOT_TRANSPORT_V14_GOAL_KEY = (
    "operator_spot_automation_transport_successor_v14"
)
AUTOMATION_SPOT_TRANSPORT_V15_GOAL_KEY = (
    "operator_spot_automation_transport_successor_v15"
)
AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS = frozenset(
    {
        AUTOMATION_SPOT_TRANSPORT_V13_GOAL_KEY,
        AUTOMATION_SPOT_TRANSPORT_V14_GOAL_KEY,
        AUTOMATION_SPOT_TRANSPORT_V15_GOAL_KEY,
    }
)
# V14/V15 remain fail-closed until a post-terminal offline remediation adds a
# reviewed official-documentation-backed correction for that exact version.
_AUTOMATION_SPOT_DOCUMENTED_TRANSPORT_SUCCESSOR_CORRECTIONS: frozenset[int] = (
    frozenset()
)
AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS = frozenset(
    {
        *AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_PREDECESSOR_GOAL_KEYS,
        *AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS,
    }
)


def _select_transport_successor(
    goals: Mapping[str, Mapping[str, Any]],
    cycles: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    *,
    documented_corrections: frozenset[int] = frozenset(),
) -> tuple[int, str] | None:
    """Select V13, then only successors enabled by a reviewed correction."""

    ordered = (
        (13, AUTOMATION_SPOT_TRANSPORT_V13_GOAL_KEY),
        (14, AUTOMATION_SPOT_TRANSPORT_V14_GOAL_KEY),
        (15, AUTOMATION_SPOT_TRANSPORT_V15_GOAL_KEY),
    )
    if set(goals) != set(AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS) or len(cycles) >= 10:
        return None
    target: tuple[int, str] | None = None
    for version, goal_key in ordered:
        goal = goals[goal_key]
        if goal.get("definition_id") is None:
            if version != 13 and version not in documented_corrections:
                return None
            target = (version, goal_key)
            break
        if goal.get("preview_outcome") not in {"REJECTED", "UNKNOWN"}:
            return None
    if target is None:
        return None
    target_cycles = [cycle for cycle in cycles if cycle.get("goal_key") == target[1]]
    if target_cycles:
        latest = max(target_cycles, key=lambda cycle: int(cycle["cycle_number"]))
        if latest.get("state") in {"CLAIMED", "READINESS_PASSED", "MATERIALIZED"}:
            return None
    return target


def _select_atomic_market_snapshot_successor(
    goals: Mapping[str, Mapping[str, Any]],
    cycles: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> tuple[int, str] | None:
    """Select the exact next V10-V12 candidate without mutating its ledger."""

    ordered = (
        (10, AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY),
        (11, AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V11_GOAL_KEY),
        (12, AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V12_GOAL_KEY),
    )
    if set(goals) != set(AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_PREDECESSOR_GOAL_KEYS):
        return None
    if len(cycles) >= 10:
        return None
    target: tuple[int, str] | None = None
    for version, goal_key in ordered:
        goal = goals[goal_key]
        if goal.get("definition_id") is None:
            target = (version, goal_key)
            break
        if goal.get("preview_outcome") not in {"REJECTED", "UNKNOWN"}:
            return None
    if target is None:
        return None
    target_cycles = [cycle for cycle in cycles if cycle.get("goal_key") == target[1]]
    if target_cycles:
        latest = max(target_cycles, key=lambda cycle: int(cycle["cycle_number"]))
        if latest.get("state") in {"CLAIMED", "MATERIALIZED"}:
            return None
    return target
AUTOMATION_SPOT_POST_ONLY_GOAL_KEYS = frozenset(
    {
        *AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS,
        *AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS,
        *AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS,
    }
)
_AUTOMATION_SPOT_NEAR_MARKET_PREPARATION_CATEGORIES = (
    AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6]
)
_AUTOMATION_SPOT_NEAR_MARKET_PREPARATION_DIAGNOSTICS = frozenset(
    {
        "automation_near_market_api_key_permissions_rejected",
        "automation_near_market_best_bid_ask_rejected",
        "automation_near_market_fee_summary_rejected",
        "automation_near_market_portfolio_catalog_rejected",
        "automation_near_market_portfolio_configuration_invalid",
        "automation_near_market_preparation_unknown",
        "automation_near_market_product_metadata_rejected",
        "automation_near_market_terms_derived",
        "automation_near_market_wallet_balances_rejected",
        "near_market_fee_invalid",
        "near_market_no_valid_size",
        "near_market_post_only_crossing",
        "near_market_product_blocked",
        "near_market_product_metadata_invalid",
        "near_market_snapshot_future",
        "near_market_snapshot_invalid",
        "near_market_snapshot_stale",
        "near_market_snapshot_timestamp_invalid",
        "near_market_wallet_insufficient",
    }
)
_AUTOMATION_SPOT_MINIMUM_SIZE_PREPARATION_CATEGORIES = (
    AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6]
)
_AUTOMATION_SPOT_MINIMUM_SIZE_PREPARATION_DIAGNOSTICS = frozenset(
    {
        "automation_minimum_size_api_key_permissions_rejected",
        "automation_minimum_size_api_key_permissions_unknown",
        "automation_minimum_size_best_bid_ask_rejected",
        "automation_minimum_size_best_bid_ask_unknown",
        "automation_minimum_size_fee_summary_rejected",
        "automation_minimum_size_fee_summary_unknown",
        "automation_minimum_size_portfolio_catalog_rejected",
        "automation_minimum_size_portfolio_catalog_unknown",
        "automation_minimum_size_portfolio_configuration_invalid",
        "automation_minimum_size_materialization_unknown",
        "automation_minimum_size_preparation_unknown",
        "automation_minimum_size_product_metadata_rejected",
        "automation_minimum_size_product_metadata_unknown",
        "automation_minimum_size_runner_composition_unknown",
        "automation_minimum_size_wallet_balances_rejected",
        "automation_minimum_size_wallet_balances_unknown",
        "minimum_size_fee_invalid",
        "minimum_size_fee_reserve_cap_conflict",
        "minimum_size_increment_conflict",
        "minimum_size_post_only_crossing",
        "minimum_size_product_blocked",
        "minimum_size_product_metadata_invalid",
        "minimum_size_snapshot_future",
        "minimum_size_snapshot_invalid",
        "minimum_size_snapshot_stale",
        "minimum_size_snapshot_timestamp_invalid",
        "minimum_size_submitted_cap_conflict",
        "minimum_size_v4_base_minimum_conflict",
        "minimum_size_v4_boundary_not_reproduced",
        "minimum_size_v4_fee_reserve_conflict",
        "minimum_size_v4_increment_conflict",
        "minimum_size_v4_quote_minimum_conflict",
        "minimum_size_wallet_insufficient",
    }
)
_AUTOMATION_SPOT_MINIMUM_SIZE_STAGE_UNKNOWN_PREFIX_LENGTH = {
    "automation_minimum_size_runner_composition_unknown": 0,
    "automation_minimum_size_api_key_permissions_unknown": 0,
    "automation_minimum_size_portfolio_catalog_unknown": 1,
    "automation_minimum_size_wallet_balances_unknown": 2,
    "automation_minimum_size_product_metadata_unknown": 3,
    "automation_minimum_size_best_bid_ask_unknown": 4,
    "automation_minimum_size_fee_summary_unknown": 5,
    "automation_minimum_size_materialization_unknown": 6,
}
_AUTOMATION_SPOT_MINIMUM_SIZE_UNKNOWN_DIAGNOSTICS = frozenset(
    {
        "automation_minimum_size_preparation_unknown",
        *_AUTOMATION_SPOT_MINIMUM_SIZE_STAGE_UNKNOWN_PREFIX_LENGTH,
    }
)
_AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY = AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY
_AUTOMATION_SPOT_PREVIEW_GOAL_KEYS = frozenset(
    {
        AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
        AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
        *AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS,
        *AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS,
        *AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS,
    }
)
_AUTOMATION_SPOT_GOAL_KEYS = frozenset(
    {
        AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
        *_AUTOMATION_SPOT_PREVIEW_GOAL_KEYS,
    }
)
_AUTOMATION_SPOT_CLIENT_ORDER_NAMESPACE = uuid.UUID(
    "af243a31-5934-52e2-b540-8d7b101d82ca"
)


def _spot_policy_revision_for_goal(goal_key: str) -> int:
    if goal_key in AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS:
        return _AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_POLICY_REVISION
    if goal_key in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS:
        return _AUTOMATION_SPOT_MINIMUM_SIZE_ELIGIBILITY_POLICY_REVISION
    if goal_key in AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS:
        return _AUTOMATION_SPOT_NEAR_MARKET_ELIGIBILITY_POLICY_REVISION
    return _AUTOMATION_SPOT_ELIGIBILITY_POLICY_REVISION


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _aware_utc_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _new_id() -> str:
    return str(uuid.uuid4())


def _decimal_text(value: Any, *, code: str) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise AutomationStoreInvalid(code) from None
    if not parsed.is_finite() or parsed <= 0:
        raise AutomationStoreInvalid(code)
    return format(parsed.normalize(), "f")


def _validate_id(value: str, *, code: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise AutomationStoreInvalid(code) from None
    canonical = str(parsed)
    if canonical != value:
        raise AutomationStoreInvalid(code)
    return canonical


@dataclass(frozen=True)
class AutomationMutationCommand:
    idempotency_key: str
    payload_sha256: str
    actor_id: str
    correlation_id: str
    operator_intent: str


@dataclass(frozen=True)
class AutomationDefinitionCreateCommand(AutomationMutationCommand):
    domain: OperatorAutomationDomain
    job_kind: OperatorAutomationJobKind
    label: str
    product_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _AutomationSpotSingleChildPlanCreateCommand(AutomationMutationCommand):
    definition_id: str
    definition_revision: int
    portfolio_id_sha256: str
    product_id: str
    side: str
    base_size: str
    limit_price: str
    submitted_notional_usdc: str
    possible_execution_notional_usdc: str
    max_submitted_notional_usdc: str
    max_possible_execution_notional_usdc: str
    post_only: bool


@dataclass(frozen=True)
class AutomationSpotSingleChildPlanTerms:
    """Identity-free immutable terms committed with a definition revision."""

    portfolio_id_sha256: str
    product_id: str
    side: str
    base_size: str
    limit_price: str
    submitted_notional_usdc: str
    possible_execution_notional_usdc: str
    max_submitted_notional_usdc: str
    max_possible_execution_notional_usdc: str
    post_only: bool


@dataclass(frozen=True)
class AutomationControlPlaneRecord:
    posture: OperatorAutomationControlPosture
    updated_at: str


@dataclass(frozen=True)
class AutomationDefinitionRecord:
    definition_id: str
    revision: int
    label: str
    domain: OperatorAutomationDomain
    job_kind: OperatorAutomationJobKind
    lifecycle_state: OperatorAutomationDefinitionState
    product_ids: tuple[str, ...]
    schedule_kind: OperatorAutomationScheduleKind
    interval_seconds: int | None
    next_review_at: str | None
    schedule_due: bool
    due_reason: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AutomationRunRecord:
    run_id: str
    definition_id: str
    domain: OperatorAutomationDomain
    job_kind: OperatorAutomationJobKind
    state: OperatorAutomationRunState
    diagnostic_code: str
    audit_id: str
    correlation_id: str
    client_order_id: str | None
    live_attempt_consumed: bool
    coinbase_api_call_count: int
    create_call_count: int
    cancel_call_count: int
    claimed_at: str
    updated_at: str
    definition_revision: int | None = None


@dataclass(frozen=True)
class AutomationSpotSingleChildPlanRecord:
    definition_id: str
    definition_revision: int
    portfolio_id_sha256: str
    product_id: Literal["BTC-USDC"]
    side: Literal["BUY", "SELL"]
    base_size: str
    limit_price: str
    submitted_notional_usdc: str
    possible_execution_notional_usdc: str
    max_submitted_notional_usdc: str
    max_possible_execution_notional_usdc: str
    post_only: bool
    plan_sha256: str
    audit_id: str
    correlation_id: str
    created_at: str


@dataclass(frozen=True)
class AutomationSpotEligibilityCycleRecord:
    goal_key: str
    cycle_number: int
    policy_revision: int
    run_id: str
    definition_id: str
    definition_revision: int
    plan_sha256: str
    portfolio_id_sha256: str
    product_id: Literal["BTC-USDC"]
    client_order_id: str
    state: Literal["OPEN", "SUCCEEDED", "REJECTED", "UNKNOWN"]
    coinbase_api_call_count: int | None
    call_count_exact: bool
    fresh_until: str | None
    diagnostic_code: str
    audit_id: str
    correlation_id: str
    started_at: str
    finalized_at: str | None


@dataclass(frozen=True)
class AutomationSpotEligibilityAttemptRecord:
    run_id: str
    cycle_number: int
    category: str
    allowance_consumed: bool
    outcome: Literal["SUCCEEDED", "REJECTED", "UNKNOWN"] | None
    eligible: bool | None
    coinbase_api_call_count: int | None
    call_count_exact: bool
    observed_at: str | None
    fresh_until: str | None
    evidence_sha256: str | None
    diagnostic_code: str
    audit_id: str
    correlation_id: str
    started_at: str
    finalized_at: str | None
    portfolio_id_sha256: str | None = None


@dataclass(frozen=True)
class AutomationSpotEligibilityCycleAllocationRecord:
    run: AutomationRunRecord
    cycle: AutomationSpotEligibilityCycleRecord


@dataclass(frozen=True)
class AutomationSpotRunExecutionRecord:
    run_id: str
    policy_revision: int
    definition_id: str
    definition_revision: int
    eligibility_cycle: int
    plan_sha256: str
    portfolio_id_sha256: str
    product_id: Literal["BTC-USDC"]
    client_order_id: str
    create_allowance_consumed: bool
    create_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None
    create_call_count: int | None
    create_call_count_exact: bool
    create_read_call_count: int | None
    create_read_call_count_exact: bool
    cancel_allowance_consumed: bool
    cancel_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None
    cancel_call_count: int | None
    cancel_call_count_exact: bool
    cancel_read_call_count: int | None
    cancel_read_call_count_exact: bool
    child_terminal: bool | None
    audit_id: str
    correlation_id: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AutomationSpotLiveProofGoalRecord:
    goal_key: str
    create_allowance_consumed: bool
    cancel_allowance_consumed: bool
    bound_run_id: str | None
    client_order_id: str | None
    create_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None
    cancel_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None
    updated_at: str


@dataclass(frozen=True)
class AutomationSpotPreviewGatedGoalRecord:
    goal_key: str
    definition_id: str | None
    bound_run_id: str | None
    client_order_id: str | None
    eligibility_cycle: int | None
    plan_sha256: str | None
    portfolio_id_sha256: str | None
    product_id: Literal["BTC-USDC"] | None
    preview_allowance_consumed: bool
    preview_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None
    preview_failure_class: str | None
    preview_rejection_code: str | None
    preview_warning_present: bool | None
    preview_id_sha256: str | None
    preview_call_count: int | None
    preview_call_count_exact: bool
    create_allowance_consumed: bool
    create_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None
    cancel_allowance_consumed: bool
    cancel_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None
    updated_at: str


@dataclass(frozen=True)
class AutomationSpotNearMarketPreparationRecord:
    cycle_number: int
    goal_key: str
    candidate_version: int
    state: Literal["CLAIMED", "MATERIALIZED", "BLOCKED", "UNKNOWN"]
    definition_id: str | None
    diagnostic_code: str
    completed_categories: tuple[str, ...]
    coinbase_api_call_count: int | None
    call_count_exact: bool
    evidence_sha256: str | None
    audit_id: str
    correlation_id: str
    started_at: str
    finalized_at: str | None


@dataclass(frozen=True)
class AutomationSpotNearMarketMaterializationEvidence:
    cycle_number: int
    goal_key: str
    diagnostic_code: str
    completed_categories: tuple[str, ...]
    coinbase_api_call_count: int
    evidence_sha256: str


@dataclass(frozen=True)
class AutomationSpotMinimumSizePreparationRecord:
    cycle_number: int
    goal_key: str
    candidate_version: int
    state: Literal["CLAIMED", "MATERIALIZED", "BLOCKED", "UNKNOWN"]
    definition_id: str | None
    diagnostic_code: str
    completed_categories: tuple[str, ...]
    coinbase_api_call_count: int | None
    call_count_exact: bool
    evidence_sha256: str | None
    audit_id: str
    correlation_id: str
    started_at: str
    finalized_at: str | None


@dataclass(frozen=True)
class AutomationSpotMinimumSizeMaterializationEvidence:
    cycle_number: int
    goal_key: str
    diagnostic_code: str
    completed_categories: tuple[str, ...]
    coinbase_api_call_count: int
    evidence_sha256: str


@dataclass(frozen=True)
class AutomationSpotAtomicMarketSnapshotCycleRecord:
    cycle_number: int
    goal_key: str
    candidate_version: int
    state: Literal["CLAIMED", "MATERIALIZED", "BLOCKED", "UNKNOWN"]
    definition_id: str | None
    run_id: str | None
    plan_sha256: str | None
    client_order_id: str | None
    diagnostic_code: str
    completed_categories: tuple[str, ...]
    coinbase_api_call_count: int | None
    call_count_exact: bool
    market_snapshot_sha256: str | None
    evidence_sha256: str | None
    audit_id: str
    correlation_id: str
    started_at: str
    finalized_at: str | None


@dataclass(frozen=True)
class AutomationSpotTransportSuccessorCycleRecord:
    cycle_number: int
    goal_key: str
    candidate_version: int
    state: Literal[
        "CLAIMED", "READINESS_PASSED", "MATERIALIZED", "BLOCKED", "UNKNOWN"
    ]
    definition_id: str | None
    run_id: str | None
    plan_sha256: str | None
    client_order_id: str | None
    diagnostic_code: str
    dns_status: Literal["NOT_ATTEMPTED", "SUCCEEDED", "FAILED"]
    tcp_status: Literal["NOT_ATTEMPTED", "SUCCEEDED", "FAILED"]
    tls_status: Literal["NOT_ATTEMPTED", "SUCCEEDED", "FAILED"]
    readiness_failure_class: str | None
    dns_probe_count: int
    tcp_probe_count: int
    tls_probe_count: int
    readiness_evidence_sha256: str | None
    completed_categories: tuple[str, ...]
    coinbase_api_call_count: int | None
    call_count_exact: bool
    market_snapshot_sha256: str | None
    evidence_sha256: str | None
    audit_id: str
    correlation_id: str
    started_at: str
    finalized_at: str | None


@dataclass(frozen=True)
class AutomationRunEventRecord:
    event_id: str
    run_id: str
    sequence: int
    from_state: OperatorAutomationRunState | None
    to_state: OperatorAutomationRunState
    diagnostic_code: str
    audit_id: str
    idempotency_key_sha256: str
    correlation_id: str
    recorded_at: str


@dataclass(frozen=True)
class AutomationLifecycleEventRecord:
    event_id: str
    definition_id: str | None
    from_state: str | None
    to_state: str
    diagnostic_code: str
    audit_id: str
    correlation_id: str
    recorded_at: str


T = TypeVar("T")


@dataclass(frozen=True)
class AutomationStorePage(Generic[T]):
    items: tuple[T, ...]
    total_count: int

    @property
    def total(self) -> int:
        return self.total_count


@dataclass(frozen=True)
class AutomationStoreMutation(Generic[T]):
    entity: T
    audit_id: str
    correlation_id: str
    replayed: bool = False


class AutomationStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AutomationStoreConflict(AutomationStoreError):
    pass


class AutomationStoreNotFound(AutomationStoreError):
    pass


class AutomationStoreInvalid(AutomationStoreError):
    pass


class AutomationStoreUnavailable(AutomationStoreError):
    pass


class OperatorAutomationRepository:
    """Typed, transaction-bounded PostgreSQL repository."""

    def __init__(self, database: PostgresDB, *, schema: str = "public") -> None:
        if _SCHEMA_PATTERN.fullmatch(schema) is None:
            raise AutomationStoreInvalid("automation_schema_invalid")
        self.database = database
        self.schema = schema
        self._prefix = f'"{schema}".'

    def ensure_schema(self) -> None:
        """Install the additive schema and immutable event guard idempotently."""

        active_states = ", ".join(f"'{state.value}'" for state in _ACTIVE_RUN_STATES)
        spot_goal_keys = ", ".join(
            f"'{goal_key}'" for goal_key in sorted(_AUTOMATION_SPOT_GOAL_KEYS)
        )
        preview_goal_keys = ", ".join(
            f"'{goal_key}'"
            for goal_key in sorted(_AUTOMATION_SPOT_PREVIEW_GOAL_KEYS)
        )
        preview_rejection_codes = ", ".join(
            f"'{code}'"
            for code in sorted(_AUTOMATION_SPOT_PREVIEW_REJECTION_CODES)
        )
        near_market_goal_keys = ", ".join(
            f"'{goal_key}'"
            for goal_key in sorted(AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS)
        )
        minimum_size_goal_keys = ", ".join(
            f"'{goal_key}'"
            for goal_key in sorted(AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS)
        )
        atomic_market_snapshot_goal_keys = ", ".join(
            f"'{goal_key}'"
            for goal_key in sorted(
                AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_PREDECESSOR_GOAL_KEYS
            )
        )
        transport_goal_keys = ", ".join(
            f"'{goal_key}'"
            for goal_key in sorted(AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS)
        )
        with self.database.get_cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_control_plane_state (
                    singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
                    posture TEXT NOT NULL CHECK (posture IN ('ACTIVE','PAUSED','DRAINING','SHUTDOWN')),
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_control_plane_state
                    (singleton, posture, updated_at)
                VALUES (1, 'ACTIVE', NOW())
                ON CONFLICT (singleton) DO NOTHING
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_definition (
                    definition_id UUID PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    label TEXT NOT NULL CHECK (char_length(label) BETWEEN 1 AND 120),
                    domain TEXT NOT NULL CHECK (domain IN ('SPOT','ORDERS')),
                    job_kind TEXT NOT NULL CHECK (job_kind IN ('SPOT_CAMPAIGN','SPOT_SWEEP','SPOT_LADDER','FOLLOW_UP')),
                    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('DRAFT','ENABLED','DISABLED','PAUSED','DRAINING')),
                    product_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('MANUAL_ONLY','INTERVAL_REVIEW_ONLY')),
                    interval_seconds INTEGER CHECK (interval_seconds IS NULL OR interval_seconds BETWEEN 60 AND 31536000),
                    next_review_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    CHECK (
                        (schedule_kind = 'MANUAL_ONLY' AND interval_seconds IS NULL AND next_review_at IS NULL)
                        OR
                        (schedule_kind = 'INTERVAL_REVIEW_ONLY' AND interval_seconds IS NOT NULL AND next_review_at IS NOT NULL)
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_run (
                    run_id UUID PRIMARY KEY,
                    definition_id UUID NOT NULL REFERENCES {self._prefix}automation_definition(definition_id),
                    domain TEXT NOT NULL CHECK (domain IN ('SPOT','ORDERS')),
                    job_kind TEXT NOT NULL CHECK (job_kind IN ('SPOT_CAMPAIGN','SPOT_SWEEP','SPOT_LADDER','FOLLOW_UP')),
                    state TEXT NOT NULL CHECK (state IN ('CLAIMED','PREPARING','AWAITING_OPERATOR_AUTHORIZATION','BLOCKED','ABORTED','INVOCATION_STARTED','ACTIVE','TERMINAL','UNKNOWN_CONSUMED')),
                    diagnostic_code TEXT NOT NULL CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    client_order_id UUID,
                    live_attempt_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    coinbase_api_call_count INTEGER NOT NULL DEFAULT 0 CHECK (coinbase_api_call_count >= 0),
                    create_call_count INTEGER NOT NULL DEFAULT 0 CHECK (create_call_count >= 0),
                    cancel_call_count INTEGER NOT NULL DEFAULT 0 CHECK (cancel_call_count >= 0),
                    claimed_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_run
                ADD COLUMN IF NOT EXISTS definition_revision INTEGER
                    CHECK (definition_revision IS NULL OR definition_revision >= 1)
                """
            )
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS automation_run_one_active_per_definition
                ON {self._prefix}automation_run (definition_id)
                WHERE state IN ({active_states})
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_single_child_plan (
                    definition_id UUID NOT NULL REFERENCES {self._prefix}automation_definition(definition_id),
                    definition_revision INTEGER NOT NULL CHECK (definition_revision >= 1),
                    portfolio_id_sha256 CHAR(64) NOT NULL
                        CHECK (portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    product_id TEXT NOT NULL CHECK (product_id = 'BTC-USDC'),
                    side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
                    base_size NUMERIC NOT NULL CHECK (base_size > 0),
                    limit_price NUMERIC NOT NULL CHECK (limit_price > 0),
                    submitted_notional_usdc NUMERIC NOT NULL
                        CHECK (
                            submitted_notional_usdc > 0
                            AND submitted_notional_usdc <= 3.10
                            AND submitted_notional_usdc = base_size * limit_price
                        ),
                    possible_execution_notional_usdc NUMERIC NOT NULL
                        CHECK (
                            possible_execution_notional_usdc > 0
                            AND possible_execution_notional_usdc <= submitted_notional_usdc
                        ),
                    max_submitted_notional_usdc NUMERIC NOT NULL
                        CHECK (max_submitted_notional_usdc = 3.10),
                    max_possible_execution_notional_usdc NUMERIC NOT NULL
                        CHECK (
                            max_possible_execution_notional_usdc > 0
                            AND max_possible_execution_notional_usdc < 3.10
                            AND possible_execution_notional_usdc
                                <= max_possible_execution_notional_usdc
                        ),
                    post_only BOOLEAN NOT NULL,
                    plan_sha256 CHAR(64) NOT NULL UNIQUE
                        CHECK (plan_sha256 ~ '^[0-9a-f]{{64}}$'),
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    created_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (definition_id, definition_revision)
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_single_child_plan
                DROP CONSTRAINT IF EXISTS
                    automation_spot_single_child_plan_check1
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_single_child_plan
                DROP CONSTRAINT IF EXISTS
                    automation_spot_single_child_max_possible_execution_notio_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_single_child_plan
                DROP CONSTRAINT IF EXISTS
                    automation_spot_single_child_plan_possible_execution_notional_usdc_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_single_child_plan
                ADD CONSTRAINT
                    automation_spot_single_child_plan_possible_execution_notional_usdc_check
                CHECK (
                    possible_execution_notional_usdc > 0
                    AND possible_execution_notional_usdc
                        <= submitted_notional_usdc
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_single_child_plan
                DROP CONSTRAINT IF EXISTS
                    automation_spot_single_child_plan_max_possible_execution_notional_usdc_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_single_child_plan
                ADD CONSTRAINT
                    automation_spot_single_child_plan_max_possible_execution_notional_usdc_check
                CHECK (
                    max_possible_execution_notional_usdc > 0
                    AND max_possible_execution_notional_usdc < 3.10
                    AND possible_execution_notional_usdc
                        <= max_possible_execution_notional_usdc
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_plan_goal (
                    definition_id UUID PRIMARY KEY REFERENCES
                        {self._prefix}automation_definition(definition_id),
                    goal_key TEXT NOT NULL UNIQUE CHECK (
                        goal_key IN ({spot_goal_keys})
                    ),
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_single_child_plan
                DROP CONSTRAINT IF EXISTS
                    automation_spot_single_child_plan_post_only_check
                """
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_plan_goal (
                    definition_id, goal_key, created_at
                )
                SELECT DISTINCT plan.definition_id, %s, NOW()
                FROM {self._prefix}automation_spot_single_child_plan AS plan
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM {self._prefix}automation_spot_plan_goal AS binding
                    WHERE binding.definition_id = plan.definition_id
                )
                """,
                (AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,),
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_plan_goal
                DROP CONSTRAINT IF EXISTS automation_spot_plan_goal_goal_key_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_plan_goal
                ADD CONSTRAINT automation_spot_plan_goal_goal_key_check
                CHECK (goal_key IN ({spot_goal_keys}))
                """
            )
            eligibility_categories = ", ".join(
                f"'{category}'" for category in AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_eligibility_cycle (
                    goal_key TEXT NOT NULL CHECK (
                        goal_key IN ({spot_goal_keys})
                    ),
                    cycle_number SMALLINT NOT NULL CHECK (cycle_number BETWEEN 1 AND 10),
                    policy_revision SMALLINT NOT NULL DEFAULT 2
                        CHECK (policy_revision IN (1,2,3,4,5)),
                    run_id UUID NOT NULL REFERENCES {self._prefix}automation_run(run_id),
                    definition_id UUID NOT NULL,
                    definition_revision INTEGER NOT NULL CHECK (definition_revision >= 1),
                    plan_sha256 CHAR(64) NOT NULL
                        CHECK (plan_sha256 ~ '^[0-9a-f]{{64}}$'),
                    portfolio_id_sha256 CHAR(64) NOT NULL
                        CHECK (portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    product_id TEXT NOT NULL CHECK (product_id = 'BTC-USDC'),
                    client_order_id UUID NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('OPEN','SUCCEEDED','REJECTED','UNKNOWN')
                    ),
                    coinbase_api_call_count INTEGER CHECK (
                        coinbase_api_call_count IS NULL
                        OR coinbase_api_call_count >= 0
                    ),
                    call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    fresh_until TIMESTAMPTZ,
                    diagnostic_code TEXT NOT NULL
                        CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL
                        CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    started_at TIMESTAMPTZ NOT NULL,
                    finalized_at TIMESTAMPTZ,
                    PRIMARY KEY (goal_key, cycle_number),
                    FOREIGN KEY (definition_id, definition_revision)
                        REFERENCES {self._prefix}automation_spot_single_child_plan(
                            definition_id, definition_revision
                        ),
                    CONSTRAINT automation_spot_eligibility_cycle_result_shape_valid
                    CHECK (
                        (state = 'OPEN' AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact AND fresh_until IS NULL
                            AND finalized_at IS NULL)
                        OR
                        (state = 'SUCCEEDED'
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact AND fresh_until IS NOT NULL
                            AND finalized_at IS NOT NULL)
                        OR
                        (state = 'REJECTED'
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact AND finalized_at IS NOT NULL)
                        OR
                        (state = 'UNKNOWN' AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact AND fresh_until IS NULL
                            AND finalized_at IS NOT NULL)
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS automation_spot_one_open_eligibility_cycle
                ON {self._prefix}automation_spot_eligibility_cycle (goal_key)
                WHERE state = 'OPEN'
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_cycle
                ADD COLUMN IF NOT EXISTS fresh_until TIMESTAMPTZ
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_cycle
                ADD COLUMN IF NOT EXISTS policy_revision SMALLINT
                """
            )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_eligibility_cycle
                SET policy_revision = 1
                WHERE policy_revision IS NULL
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_cycle
                ALTER COLUMN policy_revision SET DEFAULT 2,
                ALTER COLUMN policy_revision SET NOT NULL
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_cycle
                DROP CONSTRAINT IF EXISTS
                    automation_spot_eligibility_cycle_policy_revision_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_cycle
                ADD CONSTRAINT
                    automation_spot_eligibility_cycle_policy_revision_check
                CHECK (policy_revision IN (1,2,3,4,5))
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_eligibility_attempt (
                    run_id UUID NOT NULL REFERENCES {self._prefix}automation_run(run_id),
                    goal_key TEXT NOT NULL DEFAULT '{_AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY}'
                        CHECK (goal_key IN ({spot_goal_keys})),
                    cycle_number SMALLINT NOT NULL CHECK (cycle_number BETWEEN 1 AND 10),
                    category TEXT NOT NULL CONSTRAINT
                        automation_spot_eligibility_attempt_category_check
                        CHECK (category IN ({eligibility_categories})),
                    allowance_consumed BOOLEAN NOT NULL CHECK (allowance_consumed),
                    outcome TEXT CHECK (outcome IN ('SUCCEEDED','REJECTED','UNKNOWN')),
                    eligible BOOLEAN,
                    coinbase_api_call_count INTEGER CONSTRAINT
                        automation_spot_eligibility_call_count_nonnegative CHECK (
                        coinbase_api_call_count IS NULL OR coinbase_api_call_count >= 0
                    ),
                    call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    diagnostic_code TEXT NOT NULL CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    started_at TIMESTAMPTZ NOT NULL,
                    finalized_at TIMESTAMPTZ,
                    observed_at TIMESTAMPTZ,
                    fresh_until TIMESTAMPTZ,
                    evidence_sha256 CHAR(64) CHECK (
                        evidence_sha256 IS NULL
                        OR evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    portfolio_id_sha256 CHAR(64) CHECK (
                        portfolio_id_sha256 IS NULL
                        OR portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    PRIMARY KEY (run_id, cycle_number, category),
                    CONSTRAINT automation_spot_eligibility_cycle_fk
                    FOREIGN KEY (goal_key, cycle_number)
                        REFERENCES {self._prefix}automation_spot_eligibility_cycle(
                            goal_key, cycle_number
                        ),
                    CONSTRAINT automation_spot_eligibility_result_shape_valid
                    CHECK (
                        (outcome IS NULL AND eligible IS NULL AND coinbase_api_call_count IS NULL
                            AND call_count_exact = FALSE AND finalized_at IS NULL
                            AND observed_at IS NULL AND fresh_until IS NULL
                            AND evidence_sha256 IS NULL)
                        OR
                        (outcome = 'SUCCEEDED' AND eligible IS TRUE
                            AND call_count_exact
                            AND coinbase_api_call_count >= 1
                            AND finalized_at IS NOT NULL
                            AND observed_at IS NOT NULL
                            AND fresh_until > observed_at
                            AND evidence_sha256 IS NOT NULL)
                        OR
                        (outcome = 'REJECTED' AND eligible IS FALSE
                            AND call_count_exact
                            AND coinbase_api_call_count IS NOT NULL
                            AND finalized_at IS NOT NULL
                            AND (
                                (observed_at IS NOT NULL AND (
                                    fresh_until IS NULL
                                    OR fresh_until > observed_at
                                ))
                                OR (
                                    goal_key IN (
                                        '{AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY}',
                                        {near_market_goal_keys}
                                    )
                                    AND category = 'BEST_BID_ASK'
                                    AND observed_at IS NULL
                                    AND fresh_until IS NULL
                                    AND evidence_sha256 IS NULL
                                )
                            ))
                        OR
                        (outcome = 'UNKNOWN' AND eligible IS FALSE
                            AND NOT call_count_exact
                            AND coinbase_api_call_count IS NULL
                            AND finalized_at IS NOT NULL
                            AND observed_at IS NULL AND fresh_until IS NULL
                            AND evidence_sha256 IS NULL)
                    )
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                ADD COLUMN IF NOT EXISTS goal_key TEXT NOT NULL
                    DEFAULT '{_AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY}'
                    CHECK (goal_key IN ({spot_goal_keys}))
                """
            )
            for table_name in (
                "automation_spot_eligibility_cycle",
                "automation_spot_eligibility_attempt",
            ):
                cursor.execute(
                    f"""
                    ALTER TABLE {self._prefix}{table_name}
                    DROP CONSTRAINT IF EXISTS {table_name}_goal_key_check
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE {self._prefix}{table_name}
                    ADD CONSTRAINT {table_name}_goal_key_check
                    CHECK (goal_key IN ({spot_goal_keys}))
                    """
                )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                DROP CONSTRAINT IF EXISTS
                    automation_spot_eligibility_attempt_category_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                ADD CONSTRAINT
                    automation_spot_eligibility_attempt_category_check
                CHECK (category IN ({eligibility_categories}))
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                ADD COLUMN IF NOT EXISTS portfolio_id_sha256 CHAR(64) CHECK (
                    portfolio_id_sha256 IS NULL
                    OR portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS fresh_until TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS evidence_sha256 CHAR(64) CHECK (
                    evidence_sha256 IS NULL
                    OR evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                DROP CONSTRAINT IF EXISTS
                    automation_spot_eligibility_attempt_coinbase_api_call_count_check
                """
            )
            cursor.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint AS constraint_row
                        JOIN pg_class AS table_row
                          ON table_row.oid = constraint_row.conrelid
                        JOIN pg_namespace AS namespace_row
                          ON namespace_row.oid = table_row.relnamespace
                        WHERE namespace_row.nspname = '{self.schema}'
                          AND table_row.relname =
                              'automation_spot_eligibility_attempt'
                          AND constraint_row.conname =
                              'automation_spot_eligibility_call_count_nonnegative'
                    ) THEN
                        ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                        ADD CONSTRAINT
                            automation_spot_eligibility_call_count_nonnegative
                        CHECK (
                            coinbase_api_call_count IS NULL
                            OR coinbase_api_call_count >= 0
                        );
                    END IF;
                END;
                $$
                """
            )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_eligibility_attempt
                SET outcome = 'UNKNOWN', eligible = FALSE,
                    coinbase_api_call_count = NULL, call_count_exact = FALSE,
                    diagnostic_code =
                        'automation_spot_eligibility_legacy_evidence_unknown',
                    observed_at = NULL, fresh_until = NULL,
                    evidence_sha256 = NULL, portfolio_id_sha256 = NULL
                WHERE outcome IS NOT NULL
                  AND observed_at IS NULL
                  AND NOT (
                      goal_key IN (
                          '{AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY}',
                          {near_market_goal_keys}
                      )
                      AND category = 'BEST_BID_ASK'
                      AND outcome = 'REJECTED'
                      AND eligible IS FALSE
                      AND call_count_exact
                      AND coinbase_api_call_count IS NOT NULL
                      AND finalized_at IS NOT NULL
                      AND fresh_until IS NULL
                      AND evidence_sha256 IS NULL
                      AND portfolio_id_sha256 IS NULL
                  )
                """
            )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_eligibility_cycle AS cycle
                SET state = 'UNKNOWN', coinbase_api_call_count = NULL,
                    call_count_exact = FALSE, fresh_until = NULL,
                    diagnostic_code =
                        'automation_spot_eligibility_legacy_cycle_unknown',
                    finalized_at = COALESCE(cycle.finalized_at, NOW())
                WHERE cycle.state = 'SUCCEEDED'
                  AND cycle.fresh_until IS NULL
                  OR EXISTS (
                      SELECT 1
                      FROM {self._prefix}automation_spot_eligibility_attempt
                          AS attempt
                      WHERE attempt.goal_key = cycle.goal_key
                        AND attempt.cycle_number = cycle.cycle_number
                        AND attempt.diagnostic_code =
                            'automation_spot_eligibility_legacy_evidence_unknown'
                  )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                DROP CONSTRAINT IF EXISTS
                    automation_spot_eligibility_result_shape_valid
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                ADD CONSTRAINT automation_spot_eligibility_result_shape_valid
                CHECK (
                    (outcome IS NULL AND eligible IS NULL
                        AND coinbase_api_call_count IS NULL
                        AND NOT call_count_exact AND finalized_at IS NULL
                        AND observed_at IS NULL AND fresh_until IS NULL
                        AND evidence_sha256 IS NULL)
                    OR
                    (outcome = 'SUCCEEDED' AND eligible IS TRUE
                        AND call_count_exact AND coinbase_api_call_count >= 1
                        AND finalized_at IS NOT NULL
                        AND observed_at IS NOT NULL
                        AND fresh_until > observed_at
                        AND evidence_sha256 IS NOT NULL)
                    OR
                    (outcome = 'REJECTED' AND eligible IS FALSE
                        AND call_count_exact
                        AND coinbase_api_call_count IS NOT NULL
                        AND finalized_at IS NOT NULL
                        AND (
                            (observed_at IS NOT NULL AND (
                                fresh_until IS NULL
                                OR fresh_until > observed_at
                            ))
                            OR (
                                goal_key IN (
                                    '{AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY}',
                                    {near_market_goal_keys}
                                )
                                AND category = 'BEST_BID_ASK'
                                AND observed_at IS NULL
                                AND fresh_until IS NULL
                                AND evidence_sha256 IS NULL
                            )
                        ))
                    OR
                    (outcome = 'UNKNOWN' AND eligible IS FALSE
                        AND NOT call_count_exact
                        AND coinbase_api_call_count IS NULL
                        AND finalized_at IS NOT NULL
                        AND observed_at IS NULL AND fresh_until IS NULL
                        AND evidence_sha256 IS NULL)
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_cycle
                DROP CONSTRAINT IF EXISTS
                    automation_spot_eligibility_cycle_result_shape_valid
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_eligibility_cycle
                ADD CONSTRAINT
                    automation_spot_eligibility_cycle_result_shape_valid
                CHECK (
                    (state = 'OPEN' AND coinbase_api_call_count IS NULL
                        AND NOT call_count_exact AND fresh_until IS NULL
                        AND finalized_at IS NULL)
                    OR
                    (state = 'SUCCEEDED'
                        AND coinbase_api_call_count IS NOT NULL
                        AND call_count_exact AND fresh_until IS NOT NULL
                        AND finalized_at IS NOT NULL)
                    OR
                    (state = 'REJECTED'
                        AND coinbase_api_call_count IS NOT NULL
                        AND call_count_exact AND finalized_at IS NOT NULL)
                    OR
                    (state = 'UNKNOWN' AND coinbase_api_call_count IS NULL
                        AND NOT call_count_exact AND fresh_until IS NULL
                        AND finalized_at IS NOT NULL)
                )
                """
            )
            cursor.execute(
                f"""
                SELECT attempt.cycle_number, attempt.run_id,
                       MIN(attempt.started_at) AS started_at,
                       (ARRAY_AGG(attempt.audit_id ORDER BY attempt.started_at))[1]
                           AS audit_id,
                       (ARRAY_AGG(attempt.correlation_id
                                  ORDER BY attempt.started_at))[1]
                           AS correlation_id,
                       run.definition_id, run.definition_revision,
                       plan.plan_sha256, plan.portfolio_id_sha256,
                       plan.product_id
                FROM {self._prefix}automation_spot_eligibility_attempt AS attempt
                JOIN {self._prefix}automation_run AS run
                  ON run.run_id = attempt.run_id
                LEFT JOIN {self._prefix}automation_spot_single_child_plan AS plan
                  ON plan.definition_id = run.definition_id
                 AND plan.definition_revision = run.definition_revision
                LEFT JOIN {self._prefix}automation_spot_eligibility_cycle AS cycle
                  ON cycle.goal_key = attempt.goal_key
                 AND cycle.cycle_number = attempt.cycle_number
                WHERE cycle.cycle_number IS NULL
                GROUP BY attempt.cycle_number, attempt.run_id,
                         run.definition_id, run.definition_revision,
                         plan.plan_sha256, plan.portfolio_id_sha256,
                         plan.product_id
                ORDER BY attempt.cycle_number, attempt.run_id
                """
            )
            orphan_cycles = self._rows(cursor)
            if len({int(row["cycle_number"]) for row in orphan_cycles}) != len(
                orphan_cycles
            ):
                raise AutomationStoreUnavailable(
                    "automation_spot_eligibility_legacy_cycle_ambiguous"
                )
            migrated_at = _utc_now()
            for orphan in orphan_cycles:
                if (
                    orphan.get("definition_revision") is None
                    or orphan.get("plan_sha256") is None
                    or orphan.get("portfolio_id_sha256") is None
                    or orphan.get("product_id") != "BTC-USDC"
                ):
                    raise AutomationStoreUnavailable(
                        "automation_spot_eligibility_legacy_binding_missing"
                    )
                client_order_id = self.deterministic_spot_client_order_id(
                    run_id=str(orphan["run_id"]),
                    plan_sha256=orphan["plan_sha256"],
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._prefix}automation_spot_eligibility_cycle (
                        goal_key, cycle_number, policy_revision, run_id, definition_id,
                        definition_revision, plan_sha256,
                        portfolio_id_sha256, product_id, client_order_id,
                        state, coinbase_api_call_count, call_count_exact,
                        diagnostic_code, audit_id, correlation_id,
                        started_at, finalized_at
                    ) VALUES (
                        %s,%s,1,%s,%s,%s,%s,%s,%s,%s,
                        'UNKNOWN',NULL,FALSE,
                        'automation_spot_eligibility_legacy_cycle_unknown',
                        %s,%s,%s,%s
                    )
                    """,
                    (
                        goal_key,
                        int(orphan["cycle_number"]),
                        str(orphan["run_id"]),
                        str(orphan["definition_id"]),
                        int(orphan["definition_revision"]),
                        orphan["plan_sha256"],
                        orphan["portfolio_id_sha256"],
                        orphan["product_id"],
                        client_order_id,
                        str(orphan["audit_id"]),
                        orphan["correlation_id"],
                        orphan["started_at"],
                        migrated_at,
                    ),
                )
            cursor.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint AS constraint_row
                        JOIN pg_class AS table_row
                          ON table_row.oid = constraint_row.conrelid
                        JOIN pg_namespace AS namespace_row
                          ON namespace_row.oid = table_row.relnamespace
                        WHERE namespace_row.nspname = '{self.schema}'
                          AND table_row.relname =
                              'automation_spot_eligibility_attempt'
                          AND constraint_row.conname =
                              'automation_spot_eligibility_cycle_fk'
                    ) THEN
                        ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                        ADD CONSTRAINT automation_spot_eligibility_cycle_fk
                        FOREIGN KEY (goal_key, cycle_number)
                        REFERENCES {self._prefix}automation_spot_eligibility_cycle(
                            goal_key, cycle_number
                        );
                    END IF;
                END;
                $$
                """
            )
            cursor.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint AS constraint_row
                        JOIN pg_class AS table_row
                          ON table_row.oid = constraint_row.conrelid
                        JOIN pg_namespace AS namespace_row
                          ON namespace_row.oid = table_row.relnamespace
                        WHERE namespace_row.nspname = '{self.schema}'
                          AND table_row.relname = 'automation_spot_eligibility_attempt'
                          AND constraint_row.conname = 'automation_spot_eligibility_portfolio_binding_valid'
                    ) THEN
                        ALTER TABLE {self._prefix}automation_spot_eligibility_attempt
                        ADD CONSTRAINT automation_spot_eligibility_portfolio_binding_valid
                        CHECK (
                            portfolio_id_sha256 IS NULL
                            OR (
                                category = 'PORTFOLIO_CATALOG'
                                AND outcome = 'SUCCEEDED'
                                AND eligible IS TRUE
                                AND call_count_exact
                                AND coinbase_api_call_count IS NOT NULL
                                AND finalized_at IS NOT NULL
                            )
                        );
                    END IF;
                END;
                $$
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_run_execution (
                    run_id UUID PRIMARY KEY REFERENCES {self._prefix}automation_run(run_id),
                    policy_revision SMALLINT NOT NULL DEFAULT 2
                        CHECK (policy_revision IN (1,2,3,4,5)),
                    definition_id UUID NOT NULL,
                    definition_revision INTEGER NOT NULL,
                    eligibility_cycle SMALLINT NOT NULL CHECK (eligibility_cycle BETWEEN 1 AND 10),
                    plan_sha256 CHAR(64) NOT NULL,
                    portfolio_id_sha256 CHAR(64) NOT NULL
                        CHECK (portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    product_id TEXT NOT NULL CHECK (product_id = 'BTC-USDC'),
                    client_order_id UUID NOT NULL UNIQUE,
                    create_allowance_consumed BOOLEAN NOT NULL CHECK (create_allowance_consumed),
                    create_outcome TEXT CHECK (create_outcome IN ('ACCEPTED','REJECTED','UNKNOWN')),
                    create_call_count INTEGER CHECK (
                        create_call_count IS NULL OR create_call_count IN (0,1)
                    ),
                    create_call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    create_read_call_count INTEGER CHECK (
                        create_read_call_count IS NULL
                        OR create_read_call_count BETWEEN 0 AND 100
                    ),
                    create_read_call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    cancel_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    cancel_outcome TEXT CHECK (cancel_outcome IN ('ACCEPTED','REJECTED','UNKNOWN')),
                    cancel_call_count INTEGER CHECK (
                        cancel_call_count IS NULL OR cancel_call_count IN (0,1)
                    ),
                    cancel_call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    cancel_read_call_count INTEGER CHECK (
                        cancel_read_call_count IS NULL
                        OR cancel_read_call_count BETWEEN 0 AND 200
                    ),
                    cancel_read_call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    child_terminal BOOLEAN,
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    FOREIGN KEY (definition_id, definition_revision)
                        REFERENCES {self._prefix}automation_spot_single_child_plan(definition_id, definition_revision),
                    CONSTRAINT automation_spot_create_result_shape_valid CHECK (
                        (create_outcome IS NULL AND create_call_count IS NULL
                            AND create_call_count_exact = FALSE AND child_terminal IS NULL)
                        OR
                        (create_outcome = 'ACCEPTED'
                            AND create_call_count_exact AND create_call_count = 1)
                        OR
                        (create_outcome = 'REJECTED'
                            AND (
                                (create_call_count_exact
                                    AND create_call_count IN (0,1))
                                OR
                                (NOT create_call_count_exact
                                    AND create_call_count IS NULL)
                            ))
                        OR
                        (create_outcome = 'UNKNOWN'
                            AND (
                                (create_call_count_exact
                                    AND create_call_count IN (0,1))
                                OR
                                (NOT create_call_count_exact
                                    AND create_call_count IS NULL)
                            ))
                    ),
                    CONSTRAINT automation_spot_cancel_allowance_shape_valid CHECK (
                        (NOT cancel_allowance_consumed AND cancel_outcome IS NULL
                            AND cancel_call_count IS NULL AND cancel_call_count_exact = FALSE)
                        OR cancel_allowance_consumed
                    ),
                    CONSTRAINT automation_spot_safe_closeout_result_shape_valid CHECK (
                        cancel_outcome IS NULL
                        OR (cancel_outcome = 'ACCEPTED'
                            AND cancel_call_count_exact
                            AND cancel_call_count IN (0,1)
                            AND child_terminal IS NOT NULL)
                        OR (cancel_outcome = 'REJECTED'
                            AND child_terminal IS FALSE
                            AND (
                                (cancel_call_count_exact
                                    AND cancel_call_count IN (0,1))
                                OR
                                (NOT cancel_call_count_exact
                                    AND cancel_call_count IS NULL)
                            ))
                        OR (cancel_outcome = 'UNKNOWN'
                            AND child_terminal IS NULL
                            AND (
                                (cancel_call_count_exact
                                    AND cancel_call_count IN (0,1))
                                OR
                                (NOT cancel_call_count_exact
                                    AND cancel_call_count IS NULL)
                            ))
                    )
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                ADD COLUMN IF NOT EXISTS policy_revision SMALLINT
                """
            )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_run_execution
                SET policy_revision = 1
                WHERE policy_revision IS NULL
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                ALTER COLUMN policy_revision SET DEFAULT 2,
                ALTER COLUMN policy_revision SET NOT NULL
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                DROP CONSTRAINT IF EXISTS
                    automation_spot_run_execution_policy_revision_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                ADD CONSTRAINT
                    automation_spot_run_execution_policy_revision_check
                CHECK (policy_revision IN (1,2,3,4,5))
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                ADD COLUMN IF NOT EXISTS create_read_call_count INTEGER CHECK (
                    create_read_call_count IS NULL
                    OR create_read_call_count BETWEEN 0 AND 100
                ),
                ADD COLUMN IF NOT EXISTS create_read_call_count_exact
                    BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS cancel_read_call_count INTEGER CHECK (
                    cancel_read_call_count IS NULL
                    OR cancel_read_call_count BETWEEN 0 AND 200
                ),
                ADD COLUMN IF NOT EXISTS cancel_read_call_count_exact
                    BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                DROP CONSTRAINT IF EXISTS
                    automation_spot_run_execution_cancel_read_call_count_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                DROP CONSTRAINT IF EXISTS
                    automation_spot_cancel_read_call_count_range
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                ADD CONSTRAINT automation_spot_cancel_read_call_count_range
                CHECK (
                    cancel_read_call_count IS NULL
                    OR cancel_read_call_count BETWEEN 0 AND 200
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                DROP CONSTRAINT IF EXISTS
                    automation_spot_execution_v2_read_shape_valid
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                ADD CONSTRAINT automation_spot_execution_v2_read_shape_valid
                CHECK (
                    policy_revision = 1
                    OR (
                        (
                            (create_outcome IS NULL
                                AND create_read_call_count IS NULL
                                AND NOT create_read_call_count_exact)
                            OR
                            (create_outcome IS NOT NULL AND (
                                (create_read_call_count_exact
                                    AND create_read_call_count IS NOT NULL)
                                OR
                                (NOT create_read_call_count_exact
                                    AND create_read_call_count IS NULL)
                            ))
                        )
                        AND
                        (
                            (cancel_outcome IS NULL
                                AND cancel_read_call_count IS NULL
                                AND NOT cancel_read_call_count_exact)
                            OR
                            (cancel_outcome IS NOT NULL AND (
                                (cancel_read_call_count_exact
                                    AND cancel_read_call_count IS NOT NULL)
                                OR
                                (NOT cancel_read_call_count_exact
                                    AND cancel_read_call_count IS NULL)
                            ))
                        )
                    )
                )
                """
            )
            cursor.execute(
                f"""
                DO $$
                DECLARE
                    constraint_record RECORD;
                BEGIN
                    FOR constraint_record IN
                        SELECT constraint_row.conname
                        FROM pg_constraint AS constraint_row
                        JOIN pg_class AS table_row
                          ON table_row.oid = constraint_row.conrelid
                        JOIN pg_namespace AS namespace_row
                          ON namespace_row.oid = table_row.relnamespace
                        WHERE namespace_row.nspname = '{self.schema}'
                          AND table_row.relname = 'automation_spot_run_execution'
                          AND constraint_row.contype = 'c'
                          AND (
                              (
                                  pg_get_constraintdef(constraint_row.oid)
                                      LIKE '%create_outcome%'
                                  AND pg_get_constraintdef(constraint_row.oid)
                                      LIKE '%create_call_count%'
                              )
                              OR
                              (
                                  pg_get_constraintdef(constraint_row.oid)
                                      LIKE '%cancel_outcome%'
                                  AND pg_get_constraintdef(constraint_row.oid)
                                      LIKE '%cancel_call_count%'
                              )
                          )
                    LOOP
                        EXECUTE format(
                            'ALTER TABLE %I.%I DROP CONSTRAINT %I',
                            '{self.schema}',
                            'automation_spot_run_execution',
                            constraint_record.conname
                        );
                    END LOOP;
                END;
                $$
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_run_execution
                ADD CONSTRAINT automation_spot_create_result_shape_valid
                CHECK (
                    (create_outcome IS NULL AND create_call_count IS NULL
                        AND NOT create_call_count_exact
                        AND child_terminal IS NULL)
                    OR
                    (create_outcome = 'ACCEPTED'
                        AND create_call_count_exact
                        AND create_call_count = 1)
                    OR
                    (create_outcome = 'REJECTED'
                        AND (
                            (create_call_count_exact
                                AND create_call_count IN (0,1))
                            OR
                            (NOT create_call_count_exact
                                AND create_call_count IS NULL)
                        ))
                    OR
                    (create_outcome = 'UNKNOWN'
                        AND (
                            (create_call_count_exact
                                AND create_call_count IN (0,1))
                            OR
                            (NOT create_call_count_exact
                                AND create_call_count IS NULL)
                        ))
                ),
                ADD CONSTRAINT automation_spot_cancel_allowance_shape_valid
                CHECK (
                    (NOT cancel_allowance_consumed
                        AND cancel_outcome IS NULL
                        AND cancel_call_count IS NULL
                        AND NOT cancel_call_count_exact)
                    OR cancel_allowance_consumed
                ),
                ADD CONSTRAINT automation_spot_safe_closeout_result_shape_valid
                CHECK (
                    cancel_outcome IS NULL
                    OR
                    (cancel_outcome = 'ACCEPTED'
                        AND cancel_call_count_exact
                        AND cancel_call_count IN (0,1)
                        AND child_terminal IS NOT NULL)
                    OR
                    (cancel_outcome = 'REJECTED'
                        AND child_terminal IS FALSE
                        AND (
                            (cancel_call_count_exact
                                AND cancel_call_count IN (0,1))
                            OR
                            (NOT cancel_call_count_exact
                                AND cancel_call_count IS NULL)
                        ))
                    OR
                    (cancel_outcome = 'UNKNOWN'
                        AND child_terminal IS NULL
                        AND (
                            (cancel_call_count_exact
                                AND cancel_call_count IN (0,1))
                            OR
                            (NOT cancel_call_count_exact
                                AND cancel_call_count IS NULL)
                        ))
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_live_proof_goal (
                    singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
                    goal_key TEXT NOT NULL CHECK (
                        goal_key = '{_AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY}'
                    ),
                    create_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    cancel_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    bound_run_id UUID REFERENCES {self._prefix}automation_spot_run_execution(run_id),
                    client_order_id UUID,
                    create_outcome TEXT CHECK (create_outcome IN ('ACCEPTED','REJECTED','UNKNOWN')),
                    cancel_outcome TEXT CHECK (cancel_outcome IN ('ACCEPTED','REJECTED','UNKNOWN')),
                    updated_at TIMESTAMPTZ NOT NULL,
                    CHECK (
                        (NOT create_allowance_consumed AND bound_run_id IS NULL
                            AND client_order_id IS NULL AND create_outcome IS NULL
                            AND NOT cancel_allowance_consumed AND cancel_outcome IS NULL)
                        OR
                        (create_allowance_consumed AND bound_run_id IS NOT NULL
                            AND client_order_id IS NOT NULL)
                    ),
                    CHECK (NOT cancel_allowance_consumed OR create_allowance_consumed)
                )
                """
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_live_proof_goal (
                    singleton, goal_key, create_allowance_consumed,
                    cancel_allowance_consumed, bound_run_id, client_order_id,
                    create_outcome, cancel_outcome,
                    updated_at
                ) VALUES (1,%s,FALSE,FALSE,NULL,NULL,NULL,NULL,NOW())
                ON CONFLICT (singleton) DO NOTHING
                """,
                (_AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,),
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_preview_gated_goal (
                    goal_key TEXT PRIMARY KEY CHECK (
                        goal_key IN ({preview_goal_keys})
                    ),
                    definition_id UUID UNIQUE REFERENCES
                        {self._prefix}automation_definition(definition_id),
                    bound_run_id UUID UNIQUE REFERENCES
                        {self._prefix}automation_run(run_id),
                    client_order_id UUID,
                    eligibility_cycle SMALLINT CHECK (
                        eligibility_cycle IS NULL
                        OR eligibility_cycle BETWEEN 1 AND 10
                    ),
                    plan_sha256 CHAR(64) CHECK (
                        plan_sha256 IS NULL
                        OR plan_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    portfolio_id_sha256 CHAR(64) CHECK (
                        portfolio_id_sha256 IS NULL
                        OR portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    product_id TEXT CHECK (
                        product_id IS NULL OR product_id = 'BTC-USDC'
                    ),
                    preview_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    preview_outcome TEXT CHECK (
                        preview_outcome IN ('ACCEPTED','REJECTED','UNKNOWN')
                    ),
                    preview_failure_class TEXT CHECK (
                        preview_failure_class IN (
                            'NONE', 'DOCUMENTED_REJECTION',
                            'UNCLASSIFIED_REJECTION',
                            'RESPONSE_SCHEMA_INVALID',
                            'HTTP_CLIENT_RESPONSE', 'HTTP_SERVER_RESPONSE',
                            'HTTP_REDIRECT_RESPONSE', 'HTTP_RESPONSE_INVALID',
                            'REQUEST_COMPOSITION_FAILURE',
                            'SDK_INVOCATION_UNKNOWN',
                            'DNS_RESOLUTION_FAILURE',
                            'TCP_CONNECTION_FAILURE', 'CONNECT_TIMEOUT',
                            'TLS_OR_CERTIFICATE_FAILURE', 'PROXY_FAILURE',
                            'READ_TIMEOUT', 'CONNECTION_RESET',
                            'RESPONSE_DECODING_FAILURE',
                            'TRANSPORT_UNKNOWN'
                        )
                    ),
                    preview_rejection_code TEXT CHECK (
                        preview_rejection_code IN ({preview_rejection_codes})
                    ),
                    preview_warning_present BOOLEAN,
                    preview_id_sha256 CHAR(64) CHECK (
                        preview_id_sha256 IS NULL
                        OR preview_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    preview_call_count INTEGER CHECK (
                        preview_call_count IS NULL
                        OR preview_call_count IN (0, 1)
                    ),
                    preview_call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    create_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    create_outcome TEXT CHECK (
                        create_outcome IN ('ACCEPTED','REJECTED','UNKNOWN')
                    ),
                    cancel_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    cancel_outcome TEXT CHECK (
                        cancel_outcome IN ('ACCEPTED','REJECTED','UNKNOWN')
                    ),
                    updated_at TIMESTAMPTZ NOT NULL,
                    CHECK (
                        definition_id IS NOT NULL
                        OR (
                            bound_run_id IS NULL AND client_order_id IS NULL
                            AND eligibility_cycle IS NULL
                            AND plan_sha256 IS NULL
                            AND portfolio_id_sha256 IS NULL
                            AND product_id IS NULL
                            AND NOT preview_allowance_consumed
                            AND preview_outcome IS NULL
                            AND preview_failure_class IS NULL
                            AND preview_rejection_code IS NULL
                            AND preview_warning_present IS NULL
                            AND preview_id_sha256 IS NULL
                            AND preview_call_count IS NULL
                            AND NOT preview_call_count_exact
                            AND NOT create_allowance_consumed
                            AND create_outcome IS NULL
                            AND NOT cancel_allowance_consumed
                            AND cancel_outcome IS NULL
                        )
                    ),
                    CHECK (
                        NOT preview_allowance_consumed
                        OR (
                            bound_run_id IS NOT NULL
                            AND client_order_id IS NOT NULL
                            AND eligibility_cycle IS NOT NULL
                            AND plan_sha256 IS NOT NULL
                            AND portfolio_id_sha256 IS NOT NULL
                            AND product_id = 'BTC-USDC'
                        )
                    ),
                    CHECK (
                        preview_outcome IS NULL
                        OR (
                            preview_allowance_consumed
                            AND preview_failure_class IS NOT NULL
                            AND preview_warning_present IS NOT NULL
                            AND (
                                (preview_call_count_exact
                                    AND preview_call_count IN (0, 1))
                                OR
                                (NOT preview_call_count_exact
                                    AND preview_call_count IS NULL
                                    AND preview_outcome = 'UNKNOWN')
                            )
                        )
                    ),
                    CHECK (
                        preview_rejection_code IS NULL
                        OR (
                            preview_outcome = 'REJECTED'
                            AND preview_failure_class = 'DOCUMENTED_REJECTION'
                        )
                    ),
                    CHECK (
                        preview_id_sha256 IS NULL
                        OR preview_outcome = 'ACCEPTED'
                    ),
                    CHECK (
                        NOT create_allowance_consumed
                        OR preview_outcome = 'ACCEPTED'
                    ),
                    CHECK (
                        preview_outcome NOT IN ('REJECTED','UNKNOWN')
                        OR NOT create_allowance_consumed
                    ),
                    CHECK (
                        NOT cancel_allowance_consumed
                        OR create_allowance_consumed
                    )
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                ADD COLUMN IF NOT EXISTS preview_rejection_code TEXT
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                DROP CONSTRAINT IF EXISTS
                    automation_spot_preview_gated_goal_preview_call_count_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                DROP CONSTRAINT IF EXISTS
                    automation_spot_preview_call_count_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                ADD CONSTRAINT automation_spot_preview_call_count_check
                CHECK (
                    preview_call_count IS NULL
                    OR preview_call_count IN (0, 1)
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                DROP CONSTRAINT IF EXISTS
                    automation_spot_preview_unknown_accounting_shape_valid
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                ADD CONSTRAINT
                    automation_spot_preview_unknown_accounting_shape_valid
                CHECK (
                    preview_outcome IS DISTINCT FROM 'UNKNOWN'
                    OR (
                        preview_failure_class IN (
                            'RESPONSE_SCHEMA_INVALID',
                            'RESPONSE_DECODING_FAILURE',
                            'HTTP_CLIENT_RESPONSE', 'HTTP_SERVER_RESPONSE',
                            'HTTP_REDIRECT_RESPONSE', 'HTTP_RESPONSE_INVALID',
                            'READ_TIMEOUT'
                        )
                        AND preview_call_count_exact
                        AND preview_call_count = 1
                    )
                    OR (
                        preview_failure_class IN (
                            'REQUEST_COMPOSITION_FAILURE',
                            'DNS_RESOLUTION_FAILURE',
                            'TCP_CONNECTION_FAILURE', 'CONNECT_TIMEOUT',
                            'PROXY_FAILURE'
                        )
                        AND preview_call_count_exact
                        AND preview_call_count = 0
                    )
                    OR (
                        preview_failure_class IN (
                            'SDK_INVOCATION_UNKNOWN',
                            'TLS_OR_CERTIFICATE_FAILURE',
                            'CONNECTION_RESET', 'TRANSPORT_UNKNOWN'
                        )
                        AND NOT preview_call_count_exact
                        AND preview_call_count IS NULL
                    )
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                DROP CONSTRAINT IF EXISTS
                    automation_spot_preview_gated_goal_preview_failure_class_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                DROP CONSTRAINT IF EXISTS
                    automation_spot_preview_failure_class_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                ADD CONSTRAINT automation_spot_preview_failure_class_check
                CHECK (
                    preview_failure_class IN (
                        'NONE', 'DOCUMENTED_REJECTION',
                        'UNCLASSIFIED_REJECTION',
                        'RESPONSE_SCHEMA_INVALID',
                        'HTTP_CLIENT_RESPONSE', 'HTTP_SERVER_RESPONSE',
                        'HTTP_REDIRECT_RESPONSE', 'HTTP_RESPONSE_INVALID',
                        'REQUEST_COMPOSITION_FAILURE',
                        'SDK_INVOCATION_UNKNOWN',
                        'DNS_RESOLUTION_FAILURE',
                        'TCP_CONNECTION_FAILURE', 'CONNECT_TIMEOUT',
                        'TLS_OR_CERTIFICATE_FAILURE', 'PROXY_FAILURE',
                        'READ_TIMEOUT', 'CONNECTION_RESET',
                        'RESPONSE_DECODING_FAILURE',
                        'TRANSPORT_UNKNOWN'
                    )
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                DROP CONSTRAINT IF EXISTS
                    automation_spot_preview_rejection_code_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                ADD CONSTRAINT automation_spot_preview_rejection_code_check
                CHECK (
                    preview_rejection_code IS NULL
                    OR (
                        preview_rejection_code IN ({preview_rejection_codes})
                        AND preview_outcome = 'REJECTED'
                        AND preview_failure_class = 'DOCUMENTED_REJECTION'
                    )
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                DROP CONSTRAINT IF EXISTS
                    automation_spot_preview_gated_goal_goal_key_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self._prefix}automation_spot_preview_gated_goal
                ADD CONSTRAINT
                    automation_spot_preview_gated_goal_goal_key_check
                CHECK (goal_key IN ({preview_goal_keys}))
                """
            )
            for preview_goal_key in sorted(_AUTOMATION_SPOT_PREVIEW_GOAL_KEYS):
                cursor.execute(
                    f"""
                    INSERT INTO {self._prefix}automation_spot_preview_gated_goal (
                        goal_key, updated_at
                    ) VALUES (%s, NOW())
                    ON CONFLICT (goal_key) DO NOTHING
                    """,
                    (preview_goal_key,),
                )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_near_market_preparation (
                    cycle_number SMALLINT PRIMARY KEY
                        CHECK (cycle_number BETWEEN 1 AND 10),
                    goal_key TEXT NOT NULL
                        CHECK (goal_key IN ({near_market_goal_keys})),
                    candidate_version SMALLINT NOT NULL
                        CHECK (candidate_version BETWEEN 4 AND 6),
                    state TEXT NOT NULL CHECK (
                        state IN ('CLAIMED','MATERIALIZED','BLOCKED','UNKNOWN')
                    ),
                    definition_id UUID UNIQUE REFERENCES
                        {self._prefix}automation_definition(definition_id),
                    idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE
                        CHECK (idempotency_key_sha256 ~ '^[0-9a-f]{{64}}$'),
                    payload_sha256 CHAR(64) NOT NULL
                        CHECK (payload_sha256 ~ '^[0-9a-f]{{64}}$'),
                    actor_id_sha256 CHAR(64) NOT NULL
                        CHECK (actor_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    operator_intent_sha256 CHAR(64) NOT NULL
                        CHECK (operator_intent_sha256 ~ '^[0-9a-f]{{64}}$'),
                    diagnostic_code TEXT NOT NULL
                        CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    completed_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
                    coinbase_api_call_count INTEGER CHECK (
                        coinbase_api_call_count IS NULL
                        OR coinbase_api_call_count >= 0
                    ),
                    call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    evidence_sha256 CHAR(64) CHECK (
                        evidence_sha256 IS NULL
                        OR evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL
                        CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    started_at TIMESTAMPTZ NOT NULL,
                    finalized_at TIMESTAMPTZ,
                    CHECK (
                        (candidate_version = 4 AND goal_key = '{AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY}')
                        OR (candidate_version = 5 AND goal_key = '{AUTOMATION_SPOT_NEAR_MARKET_V5_GOAL_KEY}')
                        OR (candidate_version = 6 AND goal_key = '{AUTOMATION_SPOT_NEAR_MARKET_V6_GOAL_KEY}')
                    ),
                    CHECK (
                        (state = 'CLAIMED' AND definition_id IS NULL
                            AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact
                            AND evidence_sha256 IS NULL
                            AND finalized_at IS NULL)
                        OR
                        (state = 'MATERIALIZED' AND definition_id IS NOT NULL
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact
                            AND evidence_sha256 IS NOT NULL
                            AND finalized_at IS NOT NULL)
                        OR
                        (state = 'BLOCKED' AND definition_id IS NULL
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact
                            AND evidence_sha256 IS NOT NULL
                            AND finalized_at IS NOT NULL)
                        OR
                        (state = 'UNKNOWN' AND definition_id IS NULL
                            AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact
                            AND evidence_sha256 IS NULL
                            AND finalized_at IS NOT NULL)
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_minimum_size_preparation (
                    cycle_number SMALLINT PRIMARY KEY
                        CHECK (cycle_number BETWEEN 1 AND 10),
                    goal_key TEXT NOT NULL
                        CHECK (goal_key IN ({minimum_size_goal_keys})),
                    candidate_version SMALLINT NOT NULL
                        CHECK (candidate_version BETWEEN 7 AND 9),
                    state TEXT NOT NULL CHECK (
                        state IN ('CLAIMED','MATERIALIZED','BLOCKED','UNKNOWN')
                    ),
                    definition_id UUID UNIQUE REFERENCES
                        {self._prefix}automation_definition(definition_id),
                    idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE
                        CHECK (idempotency_key_sha256 ~ '^[0-9a-f]{{64}}$'),
                    payload_sha256 CHAR(64) NOT NULL
                        CHECK (payload_sha256 ~ '^[0-9a-f]{{64}}$'),
                    actor_id_sha256 CHAR(64) NOT NULL
                        CHECK (actor_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    operator_intent_sha256 CHAR(64) NOT NULL
                        CHECK (operator_intent_sha256 ~ '^[0-9a-f]{{64}}$'),
                    diagnostic_code TEXT NOT NULL
                        CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    completed_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
                    coinbase_api_call_count INTEGER CHECK (
                        coinbase_api_call_count IS NULL
                        OR coinbase_api_call_count >= 0
                    ),
                    call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    evidence_sha256 CHAR(64) CHECK (
                        evidence_sha256 IS NULL
                        OR evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL
                        CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    started_at TIMESTAMPTZ NOT NULL,
                    finalized_at TIMESTAMPTZ,
                    CHECK (
                        (candidate_version = 7 AND goal_key = '{AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY}')
                        OR (candidate_version = 8 AND goal_key = '{AUTOMATION_SPOT_MINIMUM_SIZE_V8_GOAL_KEY}')
                        OR (candidate_version = 9 AND goal_key = '{AUTOMATION_SPOT_MINIMUM_SIZE_V9_GOAL_KEY}')
                    ),
                    CHECK (
                        (state = 'CLAIMED' AND definition_id IS NULL
                            AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact
                            AND evidence_sha256 IS NULL
                            AND finalized_at IS NULL)
                        OR
                        (state = 'MATERIALIZED' AND definition_id IS NOT NULL
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact
                            AND evidence_sha256 IS NOT NULL
                            AND finalized_at IS NOT NULL)
                        OR
                        (state = 'BLOCKED' AND definition_id IS NULL
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact
                            AND evidence_sha256 IS NOT NULL
                            AND finalized_at IS NOT NULL)
                        OR
                        (state = 'UNKNOWN' AND definition_id IS NULL
                            AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact
                            AND evidence_sha256 IS NULL
                            AND finalized_at IS NOT NULL)
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_atomic_market_snapshot_cycle (
                    cycle_number SMALLINT PRIMARY KEY
                        CHECK (cycle_number BETWEEN 1 AND 10),
                    goal_key TEXT NOT NULL
                        CHECK (goal_key IN ({atomic_market_snapshot_goal_keys})),
                    candidate_version SMALLINT NOT NULL
                        CHECK (candidate_version BETWEEN 10 AND 12),
                    state TEXT NOT NULL CHECK (
                        state IN ('CLAIMED','MATERIALIZED','BLOCKED','UNKNOWN')
                    ),
                    definition_id UUID UNIQUE REFERENCES
                        {self._prefix}automation_definition(definition_id),
                    run_id UUID UNIQUE REFERENCES
                        {self._prefix}automation_run(run_id),
                    plan_sha256 CHAR(64) UNIQUE CHECK (
                        plan_sha256 IS NULL
                        OR plan_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    client_order_id UUID UNIQUE,
                    idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE
                        CHECK (idempotency_key_sha256 ~ '^[0-9a-f]{{64}}$'),
                    payload_sha256 CHAR(64) NOT NULL
                        CHECK (payload_sha256 ~ '^[0-9a-f]{{64}}$'),
                    actor_id_sha256 CHAR(64) NOT NULL
                        CHECK (actor_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    operator_intent_sha256 CHAR(64) NOT NULL
                        CHECK (operator_intent_sha256 ~ '^[0-9a-f]{{64}}$'),
                    diagnostic_code TEXT NOT NULL
                        CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    completed_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
                    coinbase_api_call_count INTEGER CHECK (
                        coinbase_api_call_count IS NULL
                        OR coinbase_api_call_count >= 0
                    ),
                    call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    market_snapshot_sha256 CHAR(64) CHECK (
                        market_snapshot_sha256 IS NULL
                        OR market_snapshot_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    evidence_sha256 CHAR(64) CHECK (
                        evidence_sha256 IS NULL
                        OR evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL
                        CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    started_at TIMESTAMPTZ NOT NULL,
                    finalized_at TIMESTAMPTZ,
                    CHECK (
                        (candidate_version = 10 AND goal_key = '{AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY}')
                        OR (candidate_version = 11 AND goal_key = '{AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V11_GOAL_KEY}')
                        OR (candidate_version = 12 AND goal_key = '{AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_V12_GOAL_KEY}')
                    ),
                    CHECK (
                        (state = 'CLAIMED' AND definition_id IS NULL
                            AND run_id IS NULL AND plan_sha256 IS NULL
                            AND client_order_id IS NULL
                            AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact
                            AND market_snapshot_sha256 IS NULL
                            AND evidence_sha256 IS NULL
                            AND finalized_at IS NULL)
                        OR
                        (state = 'MATERIALIZED' AND definition_id IS NOT NULL
                            AND run_id IS NOT NULL AND plan_sha256 IS NOT NULL
                            AND client_order_id IS NOT NULL
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact
                            AND market_snapshot_sha256 IS NOT NULL
                            AND evidence_sha256 IS NOT NULL
                            AND finalized_at IS NOT NULL)
                        OR
                        (state = 'BLOCKED' AND definition_id IS NULL
                            AND run_id IS NULL AND plan_sha256 IS NULL
                            AND client_order_id IS NULL
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact
                            AND market_snapshot_sha256 IS NULL
                            AND evidence_sha256 IS NOT NULL
                            AND finalized_at IS NOT NULL)
                        OR
                        (state = 'UNKNOWN' AND definition_id IS NULL
                            AND run_id IS NULL AND plan_sha256 IS NULL
                            AND client_order_id IS NULL
                            AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact
                            AND market_snapshot_sha256 IS NULL
                            AND evidence_sha256 IS NULL
                            AND finalized_at IS NOT NULL)
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_spot_transport_successor_cycle (
                    cycle_number SMALLINT PRIMARY KEY
                        CHECK (cycle_number BETWEEN 1 AND 10),
                    goal_key TEXT NOT NULL
                        CHECK (goal_key IN ({transport_goal_keys})),
                    candidate_version SMALLINT NOT NULL
                        CHECK (candidate_version BETWEEN 13 AND 15),
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'CLAIMED','READINESS_PASSED','MATERIALIZED',
                            'BLOCKED','UNKNOWN'
                        )
                    ),
                    definition_id UUID UNIQUE REFERENCES
                        {self._prefix}automation_definition(definition_id),
                    run_id UUID UNIQUE REFERENCES
                        {self._prefix}automation_run(run_id),
                    plan_sha256 CHAR(64) UNIQUE CHECK (
                        plan_sha256 IS NULL
                        OR plan_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    client_order_id UUID UNIQUE,
                    idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE
                        CHECK (idempotency_key_sha256 ~ '^[0-9a-f]{{64}}$'),
                    payload_sha256 CHAR(64) NOT NULL
                        CHECK (payload_sha256 ~ '^[0-9a-f]{{64}}$'),
                    actor_id_sha256 CHAR(64) NOT NULL
                        CHECK (actor_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    operator_intent_sha256 CHAR(64) NOT NULL
                        CHECK (operator_intent_sha256 ~ '^[0-9a-f]{{64}}$'),
                    diagnostic_code TEXT NOT NULL
                        CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    dns_status TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED' CHECK (
                        dns_status IN ('NOT_ATTEMPTED','SUCCEEDED','FAILED')
                    ),
                    tcp_status TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED' CHECK (
                        tcp_status IN ('NOT_ATTEMPTED','SUCCEEDED','FAILED')
                    ),
                    tls_status TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED' CHECK (
                        tls_status IN ('NOT_ATTEMPTED','SUCCEEDED','FAILED')
                    ),
                    readiness_failure_class TEXT CHECK (
                        readiness_failure_class IN (
                            'NONE','DNS_RESOLUTION_FAILURE',
                            'TCP_CONNECTION_FAILURE','CONNECT_TIMEOUT',
                            'TLS_OR_CERTIFICATE_FAILURE','UNKNOWN_TRANSPORT'
                        )
                    ),
                    dns_probe_count SMALLINT NOT NULL DEFAULT 0
                        CHECK (dns_probe_count IN (0, 1)),
                    tcp_probe_count SMALLINT NOT NULL DEFAULT 0
                        CHECK (tcp_probe_count IN (0, 1)),
                    tls_probe_count SMALLINT NOT NULL DEFAULT 0
                        CHECK (tls_probe_count IN (0, 1)),
                    readiness_evidence_sha256 CHAR(64) CHECK (
                        readiness_evidence_sha256 IS NULL
                        OR readiness_evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    completed_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
                    coinbase_api_call_count INTEGER CHECK (
                        coinbase_api_call_count IS NULL
                        OR coinbase_api_call_count >= 0
                    ),
                    call_count_exact BOOLEAN NOT NULL DEFAULT FALSE,
                    market_snapshot_sha256 CHAR(64) CHECK (
                        market_snapshot_sha256 IS NULL
                        OR market_snapshot_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    evidence_sha256 CHAR(64) CHECK (
                        evidence_sha256 IS NULL
                        OR evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL
                        CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    started_at TIMESTAMPTZ NOT NULL,
                    finalized_at TIMESTAMPTZ,
                    CHECK (
                        (candidate_version = 13 AND goal_key = '{AUTOMATION_SPOT_TRANSPORT_V13_GOAL_KEY}')
                        OR (candidate_version = 14 AND goal_key = '{AUTOMATION_SPOT_TRANSPORT_V14_GOAL_KEY}')
                        OR (candidate_version = 15 AND goal_key = '{AUTOMATION_SPOT_TRANSPORT_V15_GOAL_KEY}')
                    ),
                    CONSTRAINT automation_spot_transport_readiness_shape CHECK (
                        (readiness_failure_class IS NULL
                            AND dns_status = 'NOT_ATTEMPTED'
                            AND tcp_status = 'NOT_ATTEMPTED'
                            AND tls_status = 'NOT_ATTEMPTED'
                            AND dns_probe_count = 0
                            AND tcp_probe_count = 0
                            AND tls_probe_count = 0)
                        OR
                        (readiness_failure_class = 'NONE'
                            AND dns_status = 'SUCCEEDED'
                            AND tcp_status = 'SUCCEEDED'
                            AND tls_status = 'SUCCEEDED'
                            AND dns_probe_count = 1
                            AND tcp_probe_count = 1
                            AND tls_probe_count = 1)
                        OR
                        (readiness_failure_class = 'DNS_RESOLUTION_FAILURE'
                            AND dns_status = 'FAILED'
                            AND tcp_status = 'NOT_ATTEMPTED'
                            AND tls_status = 'NOT_ATTEMPTED'
                            AND dns_probe_count = 1
                            AND tcp_probe_count = 0
                            AND tls_probe_count = 0)
                        OR
                        (readiness_failure_class IN (
                                'TCP_CONNECTION_FAILURE','CONNECT_TIMEOUT'
                            )
                            AND dns_status = 'SUCCEEDED'
                            AND tcp_status = 'FAILED'
                            AND tls_status = 'NOT_ATTEMPTED'
                            AND dns_probe_count = 1
                            AND tcp_probe_count = 1
                            AND tls_probe_count = 0)
                        OR
                        (readiness_failure_class = 'TLS_OR_CERTIFICATE_FAILURE'
                            AND dns_status = 'SUCCEEDED'
                            AND tcp_status = 'SUCCEEDED'
                            AND tls_status = 'FAILED'
                            AND dns_probe_count = 1
                            AND tcp_probe_count = 1
                            AND tls_probe_count = 1)
                        OR
                        (readiness_failure_class = 'UNKNOWN_TRANSPORT'
                            AND (
                                (dns_status = 'FAILED'
                                    AND tcp_status = 'NOT_ATTEMPTED'
                                    AND tls_status = 'NOT_ATTEMPTED'
                                    AND dns_probe_count = 1
                                    AND tcp_probe_count = 0
                                    AND tls_probe_count = 0)
                                OR
                                (dns_status = 'SUCCEEDED'
                                    AND tcp_status = 'FAILED'
                                    AND tls_status = 'NOT_ATTEMPTED'
                                    AND dns_probe_count = 1
                                    AND tcp_probe_count = 1
                                    AND tls_probe_count = 0)
                                OR
                                (dns_status = 'SUCCEEDED'
                                    AND tcp_status = 'SUCCEEDED'
                                    AND tls_status = 'FAILED'
                                    AND dns_probe_count = 1
                                    AND tcp_probe_count = 1
                                    AND tls_probe_count = 1)
                            ))
                    ),
                    CONSTRAINT automation_spot_transport_cycle_state_shape CHECK (
                        (state = 'CLAIMED'
                            AND definition_id IS NULL AND run_id IS NULL
                            AND plan_sha256 IS NULL AND client_order_id IS NULL
                            AND readiness_failure_class IS NULL
                            AND dns_status = 'NOT_ATTEMPTED'
                            AND tcp_status = 'NOT_ATTEMPTED'
                            AND tls_status = 'NOT_ATTEMPTED'
                            AND dns_probe_count = 0 AND tcp_probe_count = 0
                            AND tls_probe_count = 0
                            AND readiness_evidence_sha256 IS NULL
                            AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact
                            AND market_snapshot_sha256 IS NULL
                            AND evidence_sha256 IS NULL
                            AND finalized_at IS NULL)
                        OR
                        (state = 'READINESS_PASSED'
                            AND definition_id IS NULL AND run_id IS NULL
                            AND plan_sha256 IS NULL AND client_order_id IS NULL
                            AND readiness_failure_class = 'NONE'
                            AND dns_probe_count = 1 AND tcp_probe_count = 1
                            AND tls_probe_count = 1
                            AND readiness_evidence_sha256 IS NOT NULL
                            AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact
                            AND market_snapshot_sha256 IS NULL
                            AND evidence_sha256 IS NULL
                            AND finalized_at IS NULL)
                        OR
                        (state = 'MATERIALIZED'
                            AND definition_id IS NOT NULL AND run_id IS NOT NULL
                            AND plan_sha256 IS NOT NULL
                            AND client_order_id IS NOT NULL
                            AND readiness_failure_class = 'NONE'
                            AND readiness_evidence_sha256 IS NOT NULL
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact
                            AND market_snapshot_sha256 IS NOT NULL
                            AND evidence_sha256 IS NOT NULL
                            AND finalized_at IS NOT NULL)
                        OR
                        (state = 'BLOCKED'
                            AND definition_id IS NULL AND run_id IS NULL
                            AND plan_sha256 IS NULL AND client_order_id IS NULL
                            AND readiness_failure_class IS NOT NULL
                            AND readiness_evidence_sha256 IS NOT NULL
                            AND coinbase_api_call_count IS NOT NULL
                            AND call_count_exact
                            AND market_snapshot_sha256 IS NULL
                            AND evidence_sha256 IS NOT NULL
                            AND finalized_at IS NOT NULL)
                        OR
                        (state = 'UNKNOWN'
                            AND definition_id IS NULL AND run_id IS NULL
                            AND plan_sha256 IS NULL AND client_order_id IS NULL
                            AND (
                                (readiness_failure_class IS NULL
                                    AND dns_status = 'NOT_ATTEMPTED'
                                    AND tcp_status = 'NOT_ATTEMPTED'
                                    AND tls_status = 'NOT_ATTEMPTED'
                                    AND dns_probe_count = 0
                                    AND tcp_probe_count = 0
                                    AND tls_probe_count = 0
                                    AND readiness_evidence_sha256 IS NULL)
                                OR
                                (readiness_failure_class = 'NONE'
                                    AND readiness_evidence_sha256 IS NOT NULL)
                            )
                            AND coinbase_api_call_count IS NULL
                            AND NOT call_count_exact
                            AND market_snapshot_sha256 IS NULL
                            AND evidence_sha256 IS NULL
                            AND finalized_at IS NOT NULL)
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_idempotency (
                    idempotency_key_sha256 CHAR(64) PRIMARY KEY,
                    payload_sha256 CHAR(64) NOT NULL,
                    actor_id_sha256 CHAR(64) NOT NULL,
                    operator_intent_sha256 CHAR(64) NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id UUID NOT NULL,
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    result_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_event_outbox (
                    event_id UUID PRIMARY KEY,
                    definition_id UUID REFERENCES {self._prefix}automation_definition(definition_id),
                    run_id UUID REFERENCES {self._prefix}automation_run(run_id),
                    sequence INTEGER,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    diagnostic_code TEXT NOT NULL CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    audit_id UUID NOT NULL,
                    idempotency_key_sha256 CHAR(64) NOT NULL,
                    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    event_json JSONB NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL,
                    UNIQUE (run_id, sequence)
                )
                """
            )
            function_name = f'"{self.schema}".reject_automation_event_mutation'
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION {function_name}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'automation_event_outbox_is_append_only';
                END;
                $$
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_event_outbox_no_update ON {self._prefix}automation_event_outbox"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_event_outbox_no_update
                BEFORE UPDATE ON {self._prefix}automation_event_outbox
                FOR EACH ROW EXECUTE FUNCTION {function_name}()
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_event_outbox_no_delete ON {self._prefix}automation_event_outbox"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_event_outbox_no_delete
                BEFORE DELETE ON {self._prefix}automation_event_outbox
                FOR EACH ROW EXECUTE FUNCTION {function_name}()
                """
            )
            immutable_plan_function = (
                f'"{self.schema}".reject_automation_spot_plan_mutation'
            )
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION {immutable_plan_function}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'automation_spot_single_child_plan_is_immutable';
                END;
                $$
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_spot_plan_no_update ON {self._prefix}automation_spot_single_child_plan"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_plan_no_update
                BEFORE UPDATE ON {self._prefix}automation_spot_single_child_plan
                FOR EACH ROW EXECUTE FUNCTION {immutable_plan_function}()
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_spot_plan_no_delete ON {self._prefix}automation_spot_single_child_plan"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_plan_no_delete
                BEFORE DELETE ON {self._prefix}automation_spot_single_child_plan
                FOR EACH ROW EXECUTE FUNCTION {immutable_plan_function}()
                """
            )
            immutable_goal_binding_function = (
                f'"{self.schema}".reject_automation_spot_goal_binding_mutation'
            )
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION {immutable_goal_binding_function}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'automation_spot_plan_goal_is_immutable';
                END;
                $$
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_spot_plan_goal_no_update "
                f"ON {self._prefix}automation_spot_plan_goal"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_plan_goal_no_update
                BEFORE UPDATE ON {self._prefix}automation_spot_plan_goal
                FOR EACH ROW EXECUTE FUNCTION {immutable_goal_binding_function}()
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_spot_plan_goal_no_delete "
                f"ON {self._prefix}automation_spot_plan_goal"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_plan_goal_no_delete
                BEFORE DELETE ON {self._prefix}automation_spot_plan_goal
                FOR EACH ROW EXECUTE FUNCTION {immutable_goal_binding_function}()
                """
            )
            immutable_preparation_function = (
                f'"{self.schema}".'
                "reject_automation_spot_near_market_preparation_mutation"
            )
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION {immutable_preparation_function}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'automation_spot_near_market_preparation_is_immutable';
                    END IF;
                    IF NEW.cycle_number IS DISTINCT FROM OLD.cycle_number
                       OR NEW.goal_key IS DISTINCT FROM OLD.goal_key
                       OR NEW.candidate_version IS DISTINCT FROM OLD.candidate_version
                       OR NEW.idempotency_key_sha256 IS DISTINCT FROM OLD.idempotency_key_sha256
                       OR NEW.payload_sha256 IS DISTINCT FROM OLD.payload_sha256
                       OR NEW.actor_id_sha256 IS DISTINCT FROM OLD.actor_id_sha256
                       OR NEW.operator_intent_sha256 IS DISTINCT FROM OLD.operator_intent_sha256
                       OR NEW.correlation_id IS DISTINCT FROM OLD.correlation_id
                       OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
                        RAISE EXCEPTION 'automation_spot_near_market_preparation_binding_is_immutable';
                    END IF;
                    IF OLD.state <> 'CLAIMED'
                       OR NEW.state NOT IN ('MATERIALIZED','BLOCKED','UNKNOWN') THEN
                        RAISE EXCEPTION 'automation_spot_near_market_preparation_is_immutable';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
            cursor.execute(
                "DROP TRIGGER IF EXISTS "
                "automation_spot_near_market_preparation_no_update ON "
                f"{self._prefix}automation_spot_near_market_preparation"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_near_market_preparation_no_update
                BEFORE UPDATE ON {self._prefix}automation_spot_near_market_preparation
                FOR EACH ROW EXECUTE FUNCTION {immutable_preparation_function}()
                """
            )
            cursor.execute(
                "DROP TRIGGER IF EXISTS "
                "automation_spot_near_market_preparation_no_delete ON "
                f"{self._prefix}automation_spot_near_market_preparation"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_near_market_preparation_no_delete
                BEFORE DELETE ON {self._prefix}automation_spot_near_market_preparation
                FOR EACH ROW EXECUTE FUNCTION {immutable_preparation_function}()
                """
            )
            immutable_minimum_size_preparation_function = (
                f'"{self.schema}".'
                "reject_automation_spot_minimum_size_preparation_mutation"
            )
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION {immutable_minimum_size_preparation_function}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'automation_spot_minimum_size_preparation_is_immutable';
                    END IF;
                    IF NEW.cycle_number IS DISTINCT FROM OLD.cycle_number
                       OR NEW.goal_key IS DISTINCT FROM OLD.goal_key
                       OR NEW.candidate_version IS DISTINCT FROM OLD.candidate_version
                       OR NEW.idempotency_key_sha256 IS DISTINCT FROM OLD.idempotency_key_sha256
                       OR NEW.payload_sha256 IS DISTINCT FROM OLD.payload_sha256
                       OR NEW.actor_id_sha256 IS DISTINCT FROM OLD.actor_id_sha256
                       OR NEW.operator_intent_sha256 IS DISTINCT FROM OLD.operator_intent_sha256
                       OR NEW.correlation_id IS DISTINCT FROM OLD.correlation_id
                       OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
                        RAISE EXCEPTION 'automation_spot_minimum_size_preparation_binding_is_immutable';
                    END IF;
                    IF OLD.state <> 'CLAIMED'
                       OR NEW.state NOT IN ('MATERIALIZED','BLOCKED','UNKNOWN') THEN
                        RAISE EXCEPTION 'automation_spot_minimum_size_preparation_is_immutable';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
            cursor.execute(
                "DROP TRIGGER IF EXISTS "
                "automation_spot_minimum_size_preparation_no_update ON "
                f"{self._prefix}automation_spot_minimum_size_preparation"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_minimum_size_preparation_no_update
                BEFORE UPDATE ON {self._prefix}automation_spot_minimum_size_preparation
                FOR EACH ROW EXECUTE FUNCTION {immutable_minimum_size_preparation_function}()
                """
            )
            cursor.execute(
                "DROP TRIGGER IF EXISTS "
                "automation_spot_minimum_size_preparation_no_delete ON "
                f"{self._prefix}automation_spot_minimum_size_preparation"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_minimum_size_preparation_no_delete
                BEFORE DELETE ON {self._prefix}automation_spot_minimum_size_preparation
                FOR EACH ROW EXECUTE FUNCTION {immutable_minimum_size_preparation_function}()
                """
            )
            immutable_cycle_binding_function = (
                f'"{self.schema}".reject_automation_spot_cycle_binding_mutation'
            )
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION {immutable_cycle_binding_function}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'automation_spot_eligibility_cycle_is_immutable';
                    END IF;
                    IF NEW.goal_key IS DISTINCT FROM OLD.goal_key
                       OR NEW.cycle_number IS DISTINCT FROM OLD.cycle_number
                       OR NEW.policy_revision IS DISTINCT FROM OLD.policy_revision
                       OR NEW.run_id IS DISTINCT FROM OLD.run_id
                       OR NEW.definition_id IS DISTINCT FROM OLD.definition_id
                       OR NEW.definition_revision IS DISTINCT FROM OLD.definition_revision
                       OR NEW.plan_sha256 IS DISTINCT FROM OLD.plan_sha256
                       OR NEW.portfolio_id_sha256 IS DISTINCT FROM OLD.portfolio_id_sha256
                       OR NEW.product_id IS DISTINCT FROM OLD.product_id
                       OR NEW.client_order_id IS DISTINCT FROM OLD.client_order_id
                       OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
                        RAISE EXCEPTION 'automation_spot_eligibility_cycle_binding_is_immutable';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_spot_cycle_binding_no_update ON {self._prefix}automation_spot_eligibility_cycle"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_cycle_binding_no_update
                BEFORE UPDATE ON {self._prefix}automation_spot_eligibility_cycle
                FOR EACH ROW EXECUTE FUNCTION {immutable_cycle_binding_function}()
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_spot_cycle_no_delete ON {self._prefix}automation_spot_eligibility_cycle"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_spot_cycle_no_delete
                BEFORE DELETE ON {self._prefix}automation_spot_eligibility_cycle
                FOR EACH ROW EXECUTE FUNCTION {immutable_cycle_binding_function}()
                """
            )

    @staticmethod
    def _validate_command(command: AutomationMutationCommand) -> None:
        if not command.idempotency_key or len(command.idempotency_key) > 255:
            raise AutomationStoreInvalid("automation_idempotency_key_invalid")
        if _SHA256_PATTERN.fullmatch(command.payload_sha256) is None:
            raise AutomationStoreInvalid("automation_payload_hash_invalid")
        if not command.actor_id or len(command.actor_id) > 255:
            raise AutomationStoreInvalid("automation_actor_invalid")
        if not command.correlation_id or len(command.correlation_id) > 255:
            raise AutomationStoreInvalid("automation_correlation_invalid")
        if not command.operator_intent or len(command.operator_intent) > 255:
            raise AutomationStoreInvalid("automation_operator_intent_invalid")

    @staticmethod
    def _rows(cursor: Any) -> list[dict[str, Any]]:
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    @staticmethod
    def _row(cursor: Any) -> dict[str, Any] | None:
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))

    @staticmethod
    def _advisory_key(key_sha256: str) -> int:
        unsigned = int(key_sha256[:16], 16)
        return unsigned if unsigned < 2**63 else unsigned - 2**64

    def _idempotency_replay(
        self,
        cursor: Any,
        *,
        command: AutomationMutationCommand,
        resource_type: str,
    ) -> dict[str, Any] | None:
        self._validate_command(command)
        key_sha256 = _hash(command.idempotency_key)
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (self._advisory_key(key_sha256),))
        cursor.execute(
            f"""
            SELECT payload_sha256, actor_id_sha256, operator_intent_sha256,
                   resource_type, audit_id, correlation_id, result_json
            FROM {self._prefix}automation_idempotency
            WHERE idempotency_key_sha256 = %s
            """,
            (key_sha256,),
        )
        row = self._row(cursor)
        if row is None:
            return None
        if (
            row["payload_sha256"] != command.payload_sha256
            or row["actor_id_sha256"] != _hash(command.actor_id)
            or row["operator_intent_sha256"] != _hash(command.operator_intent)
            or row["resource_type"] != resource_type
            or row["correlation_id"] != command.correlation_id
        ):
            raise AutomationStoreConflict("automation_idempotency_conflict")
        result = row["result_json"]
        if isinstance(result, str):
            result = json.loads(result)
        return {
            "entity": result,
            "audit_id": str(row["audit_id"]),
            "correlation_id": row["correlation_id"],
        }

    def _store_idempotency(
        self,
        cursor: Any,
        *,
        command: AutomationMutationCommand,
        resource_type: str,
        resource_id: str,
        audit_id: str,
        result: Mapping[str, Any],
        recorded_at: datetime,
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self._prefix}automation_idempotency (
                idempotency_key_sha256, payload_sha256, actor_id_sha256,
                operator_intent_sha256, resource_type, resource_id, audit_id,
                correlation_id, result_json, created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            """,
            (
                _hash(command.idempotency_key),
                command.payload_sha256,
                _hash(command.actor_id),
                _hash(command.operator_intent),
                resource_type,
                resource_id,
                audit_id,
                command.correlation_id,
                json.dumps(result, sort_keys=True, separators=(",", ":")),
                recorded_at,
            ),
        )

    def _control_from_row(self, row: Mapping[str, Any]) -> AutomationControlPlaneRecord:
        return AutomationControlPlaneRecord(
            posture=OperatorAutomationControlPosture(row["posture"]),
            updated_at=_iso(row["updated_at"]) or "",
        )

    def _definition_from_row(
        self,
        row: Mapping[str, Any],
        *,
        control_posture: OperatorAutomationControlPosture,
        now: datetime | None = None,
    ) -> AutomationDefinitionRecord:
        lifecycle = OperatorAutomationDefinitionState(row["lifecycle_state"])
        schedule_kind = OperatorAutomationScheduleKind(row["schedule_kind"])
        next_review = row["next_review_at"]
        current = now or _utc_now()
        if control_posture is not OperatorAutomationControlPosture.ACTIVE:
            due, reason = False, "control_plane_not_active"
        elif schedule_kind is OperatorAutomationScheduleKind.MANUAL_ONLY:
            due, reason = False, "manual_only"
        elif lifecycle is not OperatorAutomationDefinitionState.ENABLED:
            due, reason = False, "definition_inactive"
        elif next_review is not None and next_review <= current:
            due, reason = True, "due"
        else:
            due, reason = False, "not_due"
        product_ids = row["product_ids"]
        if isinstance(product_ids, str):
            product_ids = json.loads(product_ids)
        return AutomationDefinitionRecord(
            definition_id=str(row["definition_id"]),
            revision=int(row["revision"]),
            label=row["label"],
            domain=OperatorAutomationDomain(row["domain"]),
            job_kind=OperatorAutomationJobKind(row["job_kind"]),
            lifecycle_state=lifecycle,
            product_ids=tuple(product_ids or ()),
            schedule_kind=schedule_kind,
            interval_seconds=row["interval_seconds"],
            next_review_at=_iso(next_review),
            schedule_due=due,
            due_reason=reason,
            created_at=_iso(row["created_at"]) or "",
            updated_at=_iso(row["updated_at"]) or "",
        )

    @staticmethod
    def _definition_json(record: AutomationDefinitionRecord) -> dict[str, Any]:
        result = asdict(record)
        result["domain"] = record.domain.value
        result["job_kind"] = record.job_kind.value
        result["lifecycle_state"] = record.lifecycle_state.value
        result["schedule_kind"] = record.schedule_kind.value
        result["product_ids"] = list(record.product_ids)
        return result

    def _definition_from_json(self, value: Mapping[str, Any]) -> AutomationDefinitionRecord:
        return AutomationDefinitionRecord(
            definition_id=value["definition_id"],
            revision=int(value["revision"]),
            label=value["label"],
            domain=OperatorAutomationDomain(value["domain"]),
            job_kind=OperatorAutomationJobKind(value["job_kind"]),
            lifecycle_state=OperatorAutomationDefinitionState(value["lifecycle_state"]),
            product_ids=tuple(value.get("product_ids") or ()),
            schedule_kind=OperatorAutomationScheduleKind(value["schedule_kind"]),
            interval_seconds=value.get("interval_seconds"),
            next_review_at=value.get("next_review_at"),
            schedule_due=bool(value["schedule_due"]),
            due_reason=value["due_reason"],
            created_at=value["created_at"],
            updated_at=value["updated_at"],
        )

    def _append_event(
        self,
        cursor: Any,
        *,
        definition_id: str | None,
        run_id: str | None,
        from_state: str | None,
        to_state: str,
        diagnostic_code: str,
        audit_id: str,
        idempotency_key_sha256: str,
        correlation_id: str,
        recorded_at: datetime,
    ) -> None:
        sequence: int | None = None
        if run_id is not None:
            cursor.execute(
                f"SELECT COALESCE(MAX(sequence), 0) + 1 FROM {self._prefix}automation_event_outbox WHERE run_id = %s",
                (run_id,),
            )
            sequence = int(cursor.fetchone()[0])
        event_id = _new_id()
        event_json = {
            "diagnostic_code": diagnostic_code,
            "event_id": event_id,
            "from_state": from_state,
            "run_id": run_id,
            "sequence": sequence,
            "to_state": to_state,
        }
        cursor.execute(
            f"""
            INSERT INTO {self._prefix}automation_event_outbox (
                event_id, definition_id, run_id, sequence, from_state, to_state,
                diagnostic_code, audit_id, idempotency_key_sha256,
                correlation_id, event_json, recorded_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            """,
            (
                event_id,
                definition_id,
                run_id,
                sequence,
                from_state,
                to_state,
                diagnostic_code,
                audit_id,
                idempotency_key_sha256,
                correlation_id,
                json.dumps(event_json, sort_keys=True, separators=(",", ":")),
                recorded_at,
            ),
        )

    def get_control_posture(self) -> AutomationControlPlaneRecord:
        rows = self.database.execute_query(
            f"SELECT posture, updated_at FROM {self._prefix}automation_control_plane_state WHERE singleton = 1"
        )
        if len(rows) != 1:
            raise AutomationStoreUnavailable("automation_control_plane_unavailable")
        return self._control_from_row(rows[0])

    def _spot_goal_key_for_definition_cursor(
        self,
        cursor: Any,
        *,
        definition_id: str,
    ) -> str:
        cursor.execute(
            f"SELECT goal_key FROM {self._prefix}automation_spot_plan_goal "
            "WHERE definition_id = %s",
            (definition_id,),
        )
        row = self._row(cursor)
        if row is None or row.get("goal_key") not in _AUTOMATION_SPOT_GOAL_KEYS:
            raise AutomationStoreUnavailable(
                "automation_spot_goal_binding_unavailable"
            )
        return str(row["goal_key"])

    def _spot_goal_key_for_run_cursor(
        self,
        cursor: Any,
        *,
        run_id: str,
    ) -> str:
        cursor.execute(
            f"""
            SELECT binding.goal_key
            FROM {self._prefix}automation_run AS run
            JOIN {self._prefix}automation_spot_plan_goal AS binding
              ON binding.definition_id = run.definition_id
            WHERE run.run_id = %s
            """,
            (run_id,),
        )
        row = self._row(cursor)
        if row is None or row.get("goal_key") not in _AUTOMATION_SPOT_GOAL_KEYS:
            raise AutomationStoreUnavailable(
                "automation_spot_goal_binding_unavailable"
            )
        return str(row["goal_key"])

    def get_spot_goal_key_for_definition(self, definition_id: str) -> str:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        rows = self.database.execute_query(
            f"SELECT goal_key FROM {self._prefix}automation_spot_plan_goal "
            "WHERE definition_id = %s",
            (definition_id,),
        )
        if len(rows) != 1 or rows[0].get("goal_key") not in (
            _AUTOMATION_SPOT_GOAL_KEYS
        ):
            raise AutomationStoreNotFound(
                "automation_spot_goal_binding_not_found"
            )
        return str(rows[0]["goal_key"])

    def get_spot_goal_key_for_run(self, run_id: str) -> str:
        _validate_id(run_id, code="automation_run_id_invalid")
        rows = self.database.execute_query(
            f"""
            SELECT binding.goal_key
            FROM {self._prefix}automation_run AS run
            JOIN {self._prefix}automation_spot_plan_goal AS binding
              ON binding.definition_id = run.definition_id
            WHERE run.run_id = %s
            """,
            (run_id,),
        )
        if len(rows) != 1 or rows[0].get("goal_key") not in (
            _AUTOMATION_SPOT_GOAL_KEYS
        ):
            raise AutomationStoreNotFound(
                "automation_spot_goal_binding_not_found"
            )
        return str(rows[0]["goal_key"])

    def _lock_spot_single_child_definition_slot(
        self,
        cursor: Any,
        *,
        definition_id: str | None,
        goal_key: str,
    ) -> None:
        """Serialize one immutable plan-bearing definition per durable goal."""

        if goal_key not in _AUTOMATION_SPOT_GOAL_KEYS:
            raise AutomationStoreInvalid("automation_spot_goal_key_invalid")

        cursor.execute(
            f"SELECT singleton FROM {self._prefix}automation_spot_live_proof_goal WHERE singleton = 1 FOR UPDATE"
        )
        if cursor.fetchone() is None:
            raise AutomationStoreUnavailable(
                "automation_spot_live_proof_goal_unavailable"
            )
        if goal_key in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS:
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_spot_preview_gated_goal "
                "WHERE goal_key = %s FOR UPDATE",
                (goal_key,),
            )
            successor_goal = self._row(cursor)
            if successor_goal is None:
                raise AutomationStoreUnavailable(
                    "automation_spot_preview_gated_goal_unavailable"
                )
        cursor.execute(
            f"SELECT definition_id FROM {self._prefix}automation_spot_plan_goal "
            "WHERE goal_key = %s",
            (goal_key,),
        )
        existing = self._row(cursor)
        if existing is not None and str(existing["definition_id"]) != definition_id:
            code = (
                "automation_spot_preview_successor_definition_already_exists"
                if goal_key in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS
                else "automation_spot_single_child_definition_already_exists"
            )
            raise AutomationStoreConflict(code)
        if goal_key == AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
            return

        if goal_key == AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY:
            cursor.execute(
                f"""
                SELECT state, diagnostic_code, definition_id,
                       coinbase_api_call_count, call_count_exact
                FROM {self._prefix}automation_spot_near_market_preparation
                WHERE goal_key = %s
                ORDER BY cycle_number DESC
                LIMIT 1
                FOR UPDATE
                """,
                (AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,),
            )
            predecessor = self._row(cursor)
            if not (
                predecessor is not None
                and predecessor.get("state") == "BLOCKED"
                and predecessor.get("diagnostic_code")
                == "near_market_no_valid_size"
                and predecessor.get("definition_id") is None
                and type(predecessor.get("coinbase_api_call_count")) is int
                and predecessor.get("call_count_exact") is True
            ):
                raise AutomationStoreConflict(
                    "automation_spot_minimum_size_v4_predecessor_not_terminal"
                )
            return

        near_market_predecessor = {
            AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY: (
                AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY
            ),
            AUTOMATION_SPOT_NEAR_MARKET_V5_GOAL_KEY: (
                AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY
            ),
            AUTOMATION_SPOT_NEAR_MARKET_V6_GOAL_KEY: (
                AUTOMATION_SPOT_NEAR_MARKET_V5_GOAL_KEY
            ),
            AUTOMATION_SPOT_MINIMUM_SIZE_V8_GOAL_KEY: (
                AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY
            ),
            AUTOMATION_SPOT_MINIMUM_SIZE_V9_GOAL_KEY: (
                AUTOMATION_SPOT_MINIMUM_SIZE_V8_GOAL_KEY
            ),
        }.get(goal_key)
        if near_market_predecessor is not None:
            cursor.execute(
                f"""
                SELECT definition_id, bound_run_id, preview_outcome
                FROM {self._prefix}automation_spot_preview_gated_goal
                WHERE goal_key = %s
                FOR UPDATE
                """,
                (near_market_predecessor,),
            )
            predecessor_goal = self._row(cursor)
            predecessor_run = None
            if (
                predecessor_goal is not None
                and predecessor_goal.get("bound_run_id") is not None
            ):
                cursor.execute(
                    f"""
                    SELECT state, diagnostic_code
                    FROM {self._prefix}automation_run
                    WHERE run_id = %s
                    FOR UPDATE
                    """,
                    (str(predecessor_goal["bound_run_id"]),),
                )
                predecessor_run = self._row(cursor)
            predecessor_terminal = bool(
                predecessor_goal is not None
                and predecessor_goal.get("definition_id") is not None
                and predecessor_goal.get("preview_outcome")
                in {"REJECTED", "UNKNOWN"}
                and predecessor_run is not None
                and (
                    predecessor_run.get("state")
                    in {
                        OperatorAutomationRunState.TERMINAL.value,
                        OperatorAutomationRunState.UNKNOWN_CONSUMED.value,
                    }
                    or (
                        predecessor_run.get("state")
                        == OperatorAutomationRunState.BLOCKED.value
                        and predecessor_run.get("diagnostic_code")
                        == "automation_run_blocked"
                    )
                )
            )
            if not predecessor_terminal:
                code = (
                    "automation_spot_minimum_size_predecessor_not_terminal"
                    if goal_key in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS
                    else "automation_spot_near_market_predecessor_not_terminal"
                )
                raise AutomationStoreConflict(code)
            return

        if goal_key == AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY:
            cursor.execute(
                f"""
                SELECT definition_id
                FROM {self._prefix}automation_spot_preview_gated_goal
                WHERE goal_key = %s
                FOR UPDATE
                """,
                (AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,),
            )
            predecessor_goal = self._row(cursor)
            predecessor = None
            if (
                predecessor_goal is not None
                and predecessor_goal.get("definition_id") is not None
            ):
                cursor.execute(
                    f"""
                    SELECT state, diagnostic_code
                    FROM {self._prefix}automation_run
                    WHERE definition_id = %s
                    ORDER BY claimed_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (str(predecessor_goal["definition_id"]),),
                )
                predecessor = self._row(cursor)
            predecessor_terminal = bool(
                predecessor_goal is not None
                and predecessor_goal.get("definition_id") is not None
                and predecessor is not None
                and (
                    predecessor.get("state")
                    in {
                        OperatorAutomationRunState.TERMINAL.value,
                        OperatorAutomationRunState.UNKNOWN_CONSUMED.value,
                    }
                    or (
                        predecessor.get("state")
                        == OperatorAutomationRunState.BLOCKED.value
                        and predecessor.get("diagnostic_code")
                        == "automation_run_blocked"
                    )
                )
            )
            if not predecessor_terminal:
                raise AutomationStoreConflict(
                    "automation_spot_documented_freshness_predecessor_not_terminal"
                )
            return

        cursor.execute(
            f"SELECT * FROM {self._prefix}automation_spot_live_proof_goal "
            "WHERE singleton = 1"
        )
        predecessor_goal = self._row(cursor)
        predecessor_run_id = (
            str(predecessor_goal["bound_run_id"])
            if predecessor_goal is not None
            and predecessor_goal.get("bound_run_id") is not None
            else None
        )
        predecessor_terminal = False
        if predecessor_run_id is not None:
            cursor.execute(
                f"SELECT state FROM {self._prefix}automation_run WHERE run_id = %s",
                (predecessor_run_id,),
            )
            predecessor_run = self._row(cursor)
            predecessor_terminal = bool(
                predecessor_run is not None
                and predecessor_run["state"]
                in {
                    OperatorAutomationRunState.TERMINAL.value,
                    OperatorAutomationRunState.UNKNOWN_CONSUMED.value,
                }
            )
        if (
            predecessor_goal is None
            or not bool(predecessor_goal["create_allowance_consumed"])
            or predecessor_goal.get("create_outcome") is None
            or not predecessor_terminal
        ):
            raise AutomationStoreConflict(
                "automation_spot_preview_predecessor_not_terminal"
            )

    def create_definition(
        self,
        command: AutomationDefinitionCreateCommand,
        *,
        spot_single_child_plan: AutomationSpotSingleChildPlanTerms | None = None,
        spot_goal_key: str = AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
        spot_near_market_materialization: (
            AutomationSpotNearMarketMaterializationEvidence | None
        ) = None,
        spot_minimum_size_materialization: (
            AutomationSpotMinimumSizeMaterializationEvidence | None
        ) = None,
    ) -> AutomationStoreMutation[AutomationDefinitionRecord]:
        domain = OperatorAutomationDomain(command.domain)
        job_kind = OperatorAutomationJobKind(command.job_kind)
        if (job_kind in _SPOT_JOB_KINDS) is not (domain is OperatorAutomationDomain.SPOT):
            raise AutomationStoreInvalid("automation_definition_domain_kind_mismatch")
        if job_kind is OperatorAutomationJobKind.FOLLOW_UP and domain is not OperatorAutomationDomain.ORDERS:
            raise AutomationStoreInvalid("automation_definition_domain_kind_mismatch")
        label = command.label.strip()
        if not label or len(label) > 120:
            raise AutomationStoreInvalid("automation_definition_label_invalid")
        if len(set(command.product_ids)) != len(command.product_ids):
            raise AutomationStoreInvalid("automation_definition_product_scope_invalid")
        if job_kind is OperatorAutomationJobKind.FOLLOW_UP and command.product_ids:
            raise AutomationStoreInvalid("automation_follow_up_product_scope_forbidden")
        if spot_single_child_plan is not None and (
            domain is not OperatorAutomationDomain.SPOT
            or job_kind is not OperatorAutomationJobKind.SPOT_CAMPAIGN
            or tuple(command.product_ids) != ("BTC-USDC",)
        ):
            raise AutomationStoreInvalid("automation_spot_plan_definition_mismatch")
        if spot_single_child_plan is not None and spot_goal_key not in (
            _AUTOMATION_SPOT_GOAL_KEYS
        ):
            raise AutomationStoreInvalid("automation_spot_goal_key_invalid")
        if (
            spot_goal_key in AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS
            and spot_near_market_materialization is None
        ):
            raise AutomationStoreInvalid(
                "automation_near_market_materialization_required"
            )
        if (
            spot_goal_key in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS
            and spot_minimum_size_materialization is None
        ):
            raise AutomationStoreInvalid(
                "automation_minimum_size_materialization_required"
            )
        if (
            spot_near_market_materialization is not None
            and spot_minimum_size_materialization is not None
        ):
            raise AutomationStoreInvalid(
                "automation_spot_materialization_ambiguous"
            )
        if spot_near_market_materialization is not None:
            evidence = spot_near_market_materialization
            expected_evidence_sha256 = (
                near_market_preparation_evidence_sha256(
                    call_count=evidence.coinbase_api_call_count,
                    categories=evidence.completed_categories,
                    diagnostic_code=evidence.diagnostic_code,
                    outcome="MATERIALIZED",
                    policy_revision=NEAR_MARKET_POLICY_REVISION,
                    plan=(
                        {
                            "base_size": spot_single_child_plan.base_size,
                            "limit_price": spot_single_child_plan.limit_price,
                            "max_possible_execution_notional_usdc": (
                                spot_single_child_plan
                                .max_possible_execution_notional_usdc
                            ),
                            "max_submitted_notional_usdc": (
                                spot_single_child_plan
                                .max_submitted_notional_usdc
                            ),
                            "possible_execution_notional_usdc": (
                                spot_single_child_plan
                                .possible_execution_notional_usdc
                            ),
                            "post_only": spot_single_child_plan.post_only,
                            "portfolio_id_sha256": (
                                spot_single_child_plan.portfolio_id_sha256
                            ),
                            "product_id": spot_single_child_plan.product_id,
                            "side": spot_single_child_plan.side,
                            "submitted_notional_usdc": (
                                spot_single_child_plan
                                .submitted_notional_usdc
                            ),
                        }
                        if spot_single_child_plan is not None
                        else None
                    ),
                )
                if spot_single_child_plan is not None
                else None
            )
            if (
                spot_single_child_plan is None
                or spot_goal_key not in AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS
                or evidence.goal_key != spot_goal_key
                or type(evidence.cycle_number) is not int
                or not 1 <= evidence.cycle_number <= 10
                or evidence.diagnostic_code
                != "automation_near_market_terms_derived"
                or type(evidence.coinbase_api_call_count) is not int
                or evidence.coinbase_api_call_count
                < len(_AUTOMATION_SPOT_NEAR_MARKET_PREPARATION_CATEGORIES)
                or tuple(evidence.completed_categories)
                != _AUTOMATION_SPOT_NEAR_MARKET_PREPARATION_CATEGORIES
                or _SHA256_PATTERN.fullmatch(evidence.evidence_sha256) is None
                or evidence.evidence_sha256 != expected_evidence_sha256
            ):
                raise AutomationStoreInvalid(
                    "automation_near_market_materialization_invalid"
                )
        if spot_minimum_size_materialization is not None:
            evidence = spot_minimum_size_materialization
            expected_evidence_sha256 = (
                minimum_size_preparation_evidence_sha256(
                    call_count=evidence.coinbase_api_call_count,
                    categories=evidence.completed_categories,
                    diagnostic_code=evidence.diagnostic_code,
                    outcome="MATERIALIZED",
                    policy_revision=MINIMUM_SIZE_POLICY_REVISION,
                    plan=(
                        {
                            "base_size": spot_single_child_plan.base_size,
                            "limit_price": spot_single_child_plan.limit_price,
                            "max_possible_execution_notional_usdc": (
                                spot_single_child_plan
                                .max_possible_execution_notional_usdc
                            ),
                            "max_submitted_notional_usdc": (
                                spot_single_child_plan
                                .max_submitted_notional_usdc
                            ),
                            "possible_execution_notional_usdc": (
                                spot_single_child_plan
                                .possible_execution_notional_usdc
                            ),
                            "post_only": spot_single_child_plan.post_only,
                            "portfolio_id_sha256": (
                                spot_single_child_plan.portfolio_id_sha256
                            ),
                            "product_id": spot_single_child_plan.product_id,
                            "side": spot_single_child_plan.side,
                            "submitted_notional_usdc": (
                                spot_single_child_plan
                                .submitted_notional_usdc
                            ),
                            "v4_boundary_classification": (
                                evidence.diagnostic_code
                            ),
                        }
                        if spot_single_child_plan is not None
                        else None
                    ),
                )
                if spot_single_child_plan is not None
                else None
            )
            if (
                spot_single_child_plan is None
                or spot_goal_key not in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS
                or evidence.goal_key != spot_goal_key
                or type(evidence.cycle_number) is not int
                or not 1 <= evidence.cycle_number <= 10
                or evidence.diagnostic_code
                not in {
                    "minimum_size_v4_base_minimum_conflict",
                    "minimum_size_v4_boundary_not_reproduced",
                    "minimum_size_v4_fee_reserve_conflict",
                    "minimum_size_v4_increment_conflict",
                    "minimum_size_v4_quote_minimum_conflict",
                }
                or type(evidence.coinbase_api_call_count) is not int
                or evidence.coinbase_api_call_count
                < len(_AUTOMATION_SPOT_MINIMUM_SIZE_PREPARATION_CATEGORIES)
                or tuple(evidence.completed_categories)
                != _AUTOMATION_SPOT_MINIMUM_SIZE_PREPARATION_CATEGORIES
                or _SHA256_PATTERN.fullmatch(evidence.evidence_sha256) is None
                or evidence.evidence_sha256 != expected_evidence_sha256
            ):
                raise AutomationStoreInvalid(
                    "automation_minimum_size_materialization_invalid"
                )

        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type="definition_create",
            )
            if replay is not None:
                replayed_record = self._definition_from_json(replay["entity"])
                if spot_single_child_plan is not None:
                    self._verify_atomic_spot_plan_replay(
                        cursor,
                        record=replayed_record,
                        terms=spot_single_child_plan,
                        command=command,
                        goal_key=spot_goal_key,
                    )
                    if (
                        self._spot_goal_key_for_definition_cursor(
                            cursor,
                            definition_id=replayed_record.definition_id,
                        )
                        != spot_goal_key
                    ):
                        raise AutomationStoreConflict(
                            "automation_spot_goal_binding_mismatch"
                        )
                return AutomationStoreMutation(
                    entity=replayed_record,
                    audit_id=replay["audit_id"],
                    correlation_id=replay["correlation_id"],
                    replayed=True,
                )
            if spot_single_child_plan is not None:
                self._lock_spot_single_child_definition_slot(
                    cursor,
                    definition_id=None,
                    goal_key=spot_goal_key,
                )
            now = _utc_now()
            definition_id = _new_id()
            audit_id = _new_id()
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_definition (
                    definition_id, revision, label, domain, job_kind,
                    lifecycle_state, product_ids, schedule_kind,
                    interval_seconds, next_review_at, created_at, updated_at
                ) VALUES (%s,1,%s,%s,%s,'DRAFT',%s::jsonb,'MANUAL_ONLY',NULL,NULL,%s,%s)
                RETURNING *
                """,
                (
                    definition_id,
                    label,
                    domain.value,
                    job_kind.value,
                    json.dumps(list(command.product_ids)),
                    now,
                    now,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            record = self._definition_from_row(
                row,
                control_posture=OperatorAutomationControlPosture.ACTIVE,
                now=now,
            )
            if spot_single_child_plan is not None:
                plan_values = self._validated_spot_plan_values(
                    self._spot_plan_command_for_revision(
                        definition_id=definition_id,
                        definition_revision=record.revision,
                        terms=spot_single_child_plan,
                        command=command,
                    ),
                    post_only_required=(
                        spot_goal_key in AUTOMATION_SPOT_POST_ONLY_GOAL_KEYS
                    ),
                    dynamic_execution_cap=(
                        spot_goal_key in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS
                    ),
                )
                self._insert_spot_single_child_plan(
                    cursor,
                    values=plan_values,
                    audit_id=audit_id,
                    correlation_id=command.correlation_id,
                    recorded_at=now,
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._prefix}automation_spot_plan_goal (
                        definition_id, goal_key, created_at
                    ) VALUES (%s,%s,%s)
                    """,
                    (definition_id, spot_goal_key, now),
                )
                if spot_goal_key in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS:
                    cursor.execute(
                        f"""
                        UPDATE {self._prefix}automation_spot_preview_gated_goal
                        SET definition_id = %s, updated_at = %s
                        WHERE goal_key = %s AND definition_id IS NULL
                        """,
                        (
                            definition_id,
                            now,
                            spot_goal_key,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise AutomationStoreConflict(
                            "automation_spot_preview_successor_definition_already_exists"
                        )
                if spot_near_market_materialization is not None:
                    evidence = spot_near_market_materialization
                    cursor.execute(
                        f"""
                        UPDATE {self._prefix}automation_spot_near_market_preparation
                        SET state = 'MATERIALIZED', definition_id = %s,
                            diagnostic_code = %s,
                            completed_categories = %s::jsonb,
                            coinbase_api_call_count = %s,
                            call_count_exact = TRUE,
                            evidence_sha256 = %s,
                            audit_id = %s, finalized_at = %s
                        WHERE cycle_number = %s AND goal_key = %s
                          AND state = 'CLAIMED'
                        """,
                        (
                            definition_id,
                            evidence.diagnostic_code,
                            json.dumps(list(evidence.completed_categories)),
                            evidence.coinbase_api_call_count,
                            evidence.evidence_sha256,
                            audit_id,
                            now,
                            evidence.cycle_number,
                            evidence.goal_key,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise AutomationStoreConflict(
                            "automation_near_market_preparation_not_claimed"
                        )
                if spot_minimum_size_materialization is not None:
                    evidence = spot_minimum_size_materialization
                    cursor.execute(
                        f"""
                        UPDATE {self._prefix}automation_spot_minimum_size_preparation
                        SET state = 'MATERIALIZED', definition_id = %s,
                            diagnostic_code = %s,
                            completed_categories = %s::jsonb,
                            coinbase_api_call_count = %s,
                            call_count_exact = TRUE,
                            evidence_sha256 = %s,
                            audit_id = %s, finalized_at = %s
                        WHERE cycle_number = %s AND goal_key = %s
                          AND state = 'CLAIMED'
                        """,
                        (
                            definition_id,
                            evidence.diagnostic_code,
                            json.dumps(list(evidence.completed_categories)),
                            evidence.coinbase_api_call_count,
                            evidence.evidence_sha256,
                            audit_id,
                            now,
                            evidence.cycle_number,
                            evidence.goal_key,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise AutomationStoreConflict(
                            "automation_minimum_size_preparation_not_claimed"
                        )
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=None,
                from_state=None,
                to_state=record.lifecycle_state.value,
                diagnostic_code="automation_definition_created",
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type="definition_create",
                resource_id=definition_id,
                audit_id=audit_id,
                result=self._definition_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    @staticmethod
    def _spot_plan_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotSingleChildPlanRecord:
        return AutomationSpotSingleChildPlanRecord(
            definition_id=str(row["definition_id"]),
            definition_revision=int(row["definition_revision"]),
            portfolio_id_sha256=row["portfolio_id_sha256"],
            product_id=row["product_id"],
            side=row["side"],
            base_size=_decimal_text(
                row["base_size"], code="automation_spot_plan_base_size_invalid"
            ),
            limit_price=_decimal_text(
                row["limit_price"], code="automation_spot_plan_limit_price_invalid"
            ),
            submitted_notional_usdc=_decimal_text(
                row["submitted_notional_usdc"],
                code="automation_spot_plan_submitted_notional_invalid",
            ),
            possible_execution_notional_usdc=_decimal_text(
                row["possible_execution_notional_usdc"],
                code="automation_spot_plan_possible_execution_invalid",
            ),
            max_submitted_notional_usdc=_decimal_text(
                row["max_submitted_notional_usdc"],
                code="automation_spot_plan_submitted_cap_invalid",
            ),
            max_possible_execution_notional_usdc=_decimal_text(
                row["max_possible_execution_notional_usdc"],
                code="automation_spot_plan_execution_cap_invalid",
            ),
            post_only=bool(row["post_only"]),
            plan_sha256=row["plan_sha256"],
            audit_id=str(row["audit_id"]),
            correlation_id=row["correlation_id"],
            created_at=_iso(row["created_at"]) or "",
        )

    @staticmethod
    def _validated_spot_plan_values(
        command: _AutomationSpotSingleChildPlanCreateCommand,
        *,
        post_only_required: bool = False,
        dynamic_execution_cap: bool = False,
    ) -> dict[str, Any]:
        _validate_id(
            command.definition_id,
            code="automation_definition_id_invalid",
        )
        if (
            type(command.definition_revision) is not int
            or command.definition_revision < 1
        ):
            raise AutomationStoreInvalid("automation_spot_plan_revision_invalid")
        if _SHA256_PATTERN.fullmatch(command.portfolio_id_sha256) is None:
            raise AutomationStoreInvalid("automation_spot_plan_portfolio_hash_invalid")
        if command.product_id != "BTC-USDC":
            raise AutomationStoreInvalid("automation_spot_plan_product_blocked")
        side = str(command.side).upper()
        if side not in {"BUY", "SELL"}:
            raise AutomationStoreInvalid("automation_spot_plan_side_invalid")
        if (
            type(command.post_only) is not bool
            or command.post_only is not post_only_required
        ):
            raise AutomationStoreInvalid("automation_spot_plan_post_only_invalid")
        base_size = _decimal_text(
            command.base_size,
            code="automation_spot_plan_base_size_invalid",
        )
        limit_price = _decimal_text(
            command.limit_price,
            code="automation_spot_plan_limit_price_invalid",
        )
        submitted = _decimal_text(
            command.submitted_notional_usdc,
            code="automation_spot_plan_submitted_notional_invalid",
        )
        possible = _decimal_text(
            command.possible_execution_notional_usdc,
            code="automation_spot_plan_possible_execution_invalid",
        )
        submitted_cap = _decimal_text(
            command.max_submitted_notional_usdc,
            code="automation_spot_plan_submitted_cap_invalid",
        )
        execution_cap = _decimal_text(
            command.max_possible_execution_notional_usdc,
            code="automation_spot_plan_execution_cap_invalid",
        )
        if Decimal(submitted_cap) != Decimal("3.10"):
            raise AutomationStoreInvalid("automation_spot_plan_submitted_cap_invalid")
        execution_cap_decimal = Decimal(execution_cap)
        if dynamic_execution_cap:
            if not Decimal("0") < execution_cap_decimal < Decimal("3.10"):
                raise AutomationStoreInvalid(
                    "automation_spot_plan_execution_cap_invalid"
                )
        elif execution_cap_decimal != Decimal("1.00"):
            raise AutomationStoreInvalid(
                "automation_spot_plan_execution_cap_invalid"
            )
        if Decimal(base_size) * Decimal(limit_price) != Decimal(submitted):
            raise AutomationStoreInvalid("automation_spot_plan_notional_mismatch")
        if (
            Decimal(submitted) >= Decimal("3.10")
            if dynamic_execution_cap
            else Decimal(submitted) > Decimal("3.10")
        ):
            raise AutomationStoreInvalid("automation_spot_plan_submitted_cap_exceeded")
        possible_decimal = Decimal(possible)
        if dynamic_execution_cap:
            execution_invalid = (
                possible_decimal != Decimal(submitted)
                or possible_decimal > execution_cap_decimal
            )
        else:
            execution_invalid = possible_decimal > Decimal("1.00")
        if execution_invalid or possible_decimal > Decimal(submitted):
            raise AutomationStoreInvalid("automation_spot_plan_execution_cap_exceeded")
        canonical = {
            "base_size": base_size,
            "definition_id": command.definition_id,
            "definition_revision": command.definition_revision,
            "limit_price": limit_price,
            "max_possible_execution_notional_usdc": execution_cap,
            "max_submitted_notional_usdc": submitted_cap,
            "portfolio_id_sha256": command.portfolio_id_sha256,
            "possible_execution_notional_usdc": possible,
            "post_only": command.post_only,
            "product_id": command.product_id,
            "side": side,
            "submitted_notional_usdc": submitted,
        }
        canonical["plan_sha256"] = hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        return canonical

    @staticmethod
    def _spot_plan_command_for_revision(
        *,
        definition_id: str,
        definition_revision: int,
        terms: AutomationSpotSingleChildPlanTerms,
        command: AutomationMutationCommand,
    ) -> _AutomationSpotSingleChildPlanCreateCommand:
        return _AutomationSpotSingleChildPlanCreateCommand(
            idempotency_key=command.idempotency_key,
            payload_sha256=command.payload_sha256,
            actor_id=command.actor_id,
            correlation_id=command.correlation_id,
            operator_intent=command.operator_intent,
            definition_id=definition_id,
            definition_revision=definition_revision,
            portfolio_id_sha256=terms.portfolio_id_sha256,
            product_id=terms.product_id,
            side=terms.side,
            base_size=terms.base_size,
            limit_price=terms.limit_price,
            submitted_notional_usdc=terms.submitted_notional_usdc,
            possible_execution_notional_usdc=(
                terms.possible_execution_notional_usdc
            ),
            max_submitted_notional_usdc=terms.max_submitted_notional_usdc,
            max_possible_execution_notional_usdc=(
                terms.max_possible_execution_notional_usdc
            ),
            post_only=terms.post_only,
        )

    def _insert_spot_single_child_plan(
        self,
        cursor: Any,
        *,
        values: Mapping[str, Any],
        audit_id: str,
        correlation_id: str,
        recorded_at: datetime,
    ) -> AutomationSpotSingleChildPlanRecord:
        """Insert one immutable plan inside its owning definition transaction."""

        cursor.execute(
            f"""
            INSERT INTO {self._prefix}automation_spot_single_child_plan (
                definition_id, definition_revision, portfolio_id_sha256,
                product_id, side, base_size, limit_price,
                submitted_notional_usdc, possible_execution_notional_usdc,
                max_submitted_notional_usdc,
                max_possible_execution_notional_usdc, post_only,
                plan_sha256, audit_id, correlation_id, created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING *
            """,
            (
                values["definition_id"],
                values["definition_revision"],
                values["portfolio_id_sha256"],
                values["product_id"],
                values["side"],
                values["base_size"],
                values["limit_price"],
                values["submitted_notional_usdc"],
                values["possible_execution_notional_usdc"],
                values["max_submitted_notional_usdc"],
                values["max_possible_execution_notional_usdc"],
                values["post_only"],
                values["plan_sha256"],
                audit_id,
                correlation_id,
                recorded_at,
            ),
        )
        row = self._row(cursor)
        assert row is not None
        return self._spot_plan_from_row(row)

    def _spot_plan_for_revision(
        self,
        cursor: Any,
        *,
        definition_id: str,
        definition_revision: int,
    ) -> AutomationSpotSingleChildPlanRecord | None:
        cursor.execute(
            f"""
            SELECT * FROM {self._prefix}automation_spot_single_child_plan
            WHERE definition_id = %s AND definition_revision = %s
            """,
            (definition_id, definition_revision),
        )
        row = self._row(cursor)
        return self._spot_plan_from_row(row) if row is not None else None

    def _verify_atomic_spot_plan_replay(
        self,
        cursor: Any,
        *,
        record: AutomationDefinitionRecord,
        terms: AutomationSpotSingleChildPlanTerms,
        command: AutomationMutationCommand,
        goal_key: str,
    ) -> None:
        expected = self._validated_spot_plan_values(
            self._spot_plan_command_for_revision(
                definition_id=record.definition_id,
                definition_revision=record.revision,
                terms=terms,
                command=command,
            ),
            post_only_required=(
                goal_key in AUTOMATION_SPOT_POST_ONLY_GOAL_KEYS
            ),
            dynamic_execution_cap=(
                goal_key in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS
            ),
        )
        persisted = self._spot_plan_for_revision(
            cursor,
            definition_id=record.definition_id,
            definition_revision=record.revision,
        )
        if persisted is None:
            raise AutomationStoreConflict("automation_spot_plan_missing")
        if persisted.plan_sha256 != expected["plan_sha256"]:
            raise AutomationStoreConflict("automation_spot_plan_replay_mismatch")

    def _carry_spot_single_child_plan(
        self,
        cursor: Any,
        *,
        record: AutomationDefinitionRecord,
        command: AutomationMutationCommand,
        audit_id: str,
        recorded_at: datetime,
    ) -> AutomationSpotSingleChildPlanRecord | None:
        if (
            record.job_kind is not OperatorAutomationJobKind.SPOT_CAMPAIGN
            or record.revision <= 1
        ):
            return None
        previous = self._spot_plan_for_revision(
            cursor,
            definition_id=record.definition_id,
            definition_revision=record.revision - 1,
        )
        if previous is None:
            return None
        self._lock_spot_single_child_definition_slot(
            cursor,
            definition_id=record.definition_id,
            goal_key=self._spot_goal_key_for_definition_cursor(
                cursor,
                definition_id=record.definition_id,
            ),
        )
        goal_key = self._spot_goal_key_for_definition_cursor(
            cursor,
            definition_id=record.definition_id,
        )
        terms = AutomationSpotSingleChildPlanTerms(
            portfolio_id_sha256=previous.portfolio_id_sha256,
            product_id=previous.product_id,
            side=previous.side,
            base_size=previous.base_size,
            limit_price=previous.limit_price,
            submitted_notional_usdc=previous.submitted_notional_usdc,
            possible_execution_notional_usdc=(
                previous.possible_execution_notional_usdc
            ),
            max_submitted_notional_usdc=previous.max_submitted_notional_usdc,
            max_possible_execution_notional_usdc=(
                previous.max_possible_execution_notional_usdc
            ),
            post_only=previous.post_only,
        )
        values = self._validated_spot_plan_values(
            self._spot_plan_command_for_revision(
                definition_id=record.definition_id,
                definition_revision=record.revision,
                terms=terms,
                command=command,
            ),
            post_only_required=(
                goal_key in AUTOMATION_SPOT_POST_ONLY_GOAL_KEYS
            ),
            dynamic_execution_cap=(
                goal_key in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS
            ),
        )
        return self._insert_spot_single_child_plan(
            cursor,
            values=values,
            audit_id=audit_id,
            correlation_id=command.correlation_id,
            recorded_at=recorded_at,
        )

    def _verify_carried_spot_plan_replay(
        self,
        cursor: Any,
        *,
        record: AutomationDefinitionRecord,
        command: AutomationMutationCommand,
    ) -> None:
        if (
            record.job_kind is not OperatorAutomationJobKind.SPOT_CAMPAIGN
            or record.revision <= 1
        ):
            return
        previous = self._spot_plan_for_revision(
            cursor,
            definition_id=record.definition_id,
            definition_revision=record.revision - 1,
        )
        if previous is None:
            return
        current = self._spot_plan_for_revision(
            cursor,
            definition_id=record.definition_id,
            definition_revision=record.revision,
        )
        if current is None:
            raise AutomationStoreConflict("automation_spot_plan_revision_missing")
        goal_key = self._spot_goal_key_for_definition_cursor(
            cursor,
            definition_id=record.definition_id,
        )
        expected = self._validated_spot_plan_values(
            self._spot_plan_command_for_revision(
                definition_id=record.definition_id,
                definition_revision=record.revision,
                terms=AutomationSpotSingleChildPlanTerms(
                    portfolio_id_sha256=previous.portfolio_id_sha256,
                    product_id=previous.product_id,
                    side=previous.side,
                    base_size=previous.base_size,
                    limit_price=previous.limit_price,
                    submitted_notional_usdc=previous.submitted_notional_usdc,
                    possible_execution_notional_usdc=(
                        previous.possible_execution_notional_usdc
                    ),
                    max_submitted_notional_usdc=(
                        previous.max_submitted_notional_usdc
                    ),
                    max_possible_execution_notional_usdc=(
                        previous.max_possible_execution_notional_usdc
                    ),
                    post_only=previous.post_only,
                ),
                command=command,
            ),
            post_only_required=(
                goal_key in AUTOMATION_SPOT_POST_ONLY_GOAL_KEYS
            ),
            dynamic_execution_cap=(
                goal_key in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS
            ),
        )
        if current.plan_sha256 != expected["plan_sha256"]:
            raise AutomationStoreConflict(
                "automation_spot_plan_revision_mismatch"
            )

    def get_spot_single_child_plan(
        self,
        definition_id: str,
        definition_revision: int,
    ) -> AutomationSpotSingleChildPlanRecord | None:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        if type(definition_revision) is not int or definition_revision < 1:
            raise AutomationStoreInvalid("automation_spot_plan_revision_invalid")
        rows = self.database.execute_query(
            f"""
            SELECT * FROM {self._prefix}automation_spot_single_child_plan
            WHERE definition_id = %s AND definition_revision = %s
            """,
            (definition_id, definition_revision),
        )
        return self._spot_plan_from_row(rows[0]) if rows else None

    def _current_control(self, cursor: Any, *, for_update: bool = False) -> OperatorAutomationControlPosture:
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            f"SELECT posture FROM {self._prefix}automation_control_plane_state WHERE singleton = 1{suffix}"
        )
        row = cursor.fetchone()
        if row is None:
            raise AutomationStoreUnavailable("automation_control_plane_unavailable")
        return OperatorAutomationControlPosture(row[0])

    def get_definition(self, definition_id: str) -> AutomationDefinitionRecord | None:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        with self.database.get_cursor() as cursor:
            posture = self._current_control(cursor)
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition WHERE definition_id = %s",
                (definition_id,),
            )
            row = self._row(cursor)
            return (
                self._definition_from_row(row, control_posture=posture)
                if row is not None
                else None
            )

    def list_definitions(
        self,
        *,
        domain: OperatorAutomationDomain | str | None = None,
        job_kind: OperatorAutomationJobKind | str | None = None,
        lifecycle_state: OperatorAutomationDefinitionState | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationDefinitionRecord]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        conditions: list[str] = []
        params: list[Any] = []
        if domain is not None:
            domain_value = OperatorAutomationDomain(domain).value
            conditions.append("domain = %s")
            params.append(domain_value)
        if job_kind is not None:
            job_value = OperatorAutomationJobKind(job_kind).value
            conditions.append("job_kind = %s")
            params.append(job_value)
        if lifecycle_state is not None:
            state_value = OperatorAutomationDefinitionState(lifecycle_state).value
            conditions.append("lifecycle_state = %s")
            params.append(state_value)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.database.get_cursor() as cursor:
            posture = self._current_control(cursor)
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_definition{where}",
                tuple(params),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition{where} ORDER BY created_at, definition_id LIMIT %s OFFSET %s",
                tuple([*params, limit, offset]),
            )
            rows = self._rows(cursor)
            return AutomationStorePage(
                items=tuple(
                    self._definition_from_row(row, control_posture=posture)
                    for row in rows
                ),
                total_count=total,
            )

    @staticmethod
    def _definition_target(
        current: OperatorAutomationDefinitionState,
        action: str,
    ) -> OperatorAutomationDefinitionState:
        normalized = action.lower()
        transitions = {
            OperatorAutomationDefinitionState.DRAFT: {
                "enable": OperatorAutomationDefinitionState.ENABLED,
                "disable": OperatorAutomationDefinitionState.DISABLED,
            },
            OperatorAutomationDefinitionState.ENABLED: {
                "pause": OperatorAutomationDefinitionState.PAUSED,
                "drain": OperatorAutomationDefinitionState.DRAINING,
                "disable": OperatorAutomationDefinitionState.DISABLED,
            },
            OperatorAutomationDefinitionState.PAUSED: {
                "resume": OperatorAutomationDefinitionState.ENABLED,
                "drain": OperatorAutomationDefinitionState.DRAINING,
                "disable": OperatorAutomationDefinitionState.DISABLED,
            },
            OperatorAutomationDefinitionState.DRAINING: {
                "resume": OperatorAutomationDefinitionState.ENABLED,
                "disable": OperatorAutomationDefinitionState.DISABLED,
            },
            OperatorAutomationDefinitionState.DISABLED: {
                "enable": OperatorAutomationDefinitionState.ENABLED,
            },
        }
        try:
            return transitions[current][normalized]
        except KeyError:
            raise AutomationStoreConflict("automation_definition_transition_invalid") from None

    def transition_definition(
        self,
        definition_id: str,
        action: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationDefinitionRecord]:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        normalized = _enum_value(action).lower()
        resource_type = f"definition_{normalized}"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                replayed_record = self._definition_from_json(replay["entity"])
                self._verify_carried_spot_plan_replay(
                    cursor,
                    record=replayed_record,
                    command=command,
                )
                return AutomationStoreMutation(
                    replayed_record,
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            posture = self._current_control(cursor)
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition WHERE definition_id = %s FOR UPDATE",
                (definition_id,),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreNotFound("automation_definition_not_found")
            current = OperatorAutomationDefinitionState(row["lifecycle_state"])
            target = self._definition_target(current, normalized)
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_definition
                SET lifecycle_state = %s, revision = revision + 1, updated_at = %s
                WHERE definition_id = %s
                RETURNING *
                """,
                (target.value, now, definition_id),
            )
            updated = self._row(cursor)
            assert updated is not None
            record = self._definition_from_row(
                updated,
                control_posture=posture,
                now=now,
            )
            self._carry_spot_single_child_plan(
                cursor,
                record=record,
                command=command,
                audit_id=audit_id,
                recorded_at=now,
            )
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=None,
                from_state=current.value,
                to_state=target.value,
                diagnostic_code=f"automation_definition_{normalized}",
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=definition_id,
                audit_id=audit_id,
                result=self._definition_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    def set_schedule(
        self,
        definition_id: str,
        schedule_kind: OperatorAutomationScheduleKind | str,
        *,
        interval_seconds: int | None,
        command: AutomationMutationCommand,
        _evidence_kind: str = "set",
    ) -> AutomationStoreMutation[AutomationDefinitionRecord]:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        if _evidence_kind not in {"set", "clear"}:
            raise AutomationStoreInvalid("automation_schedule_evidence_invalid")
        resource_type = f"definition_{_evidence_kind}_schedule"
        diagnostic_code = f"automation_schedule_{'set' if _evidence_kind == 'set' else 'cleared'}"
        kind = OperatorAutomationScheduleKind(schedule_kind)
        if kind is OperatorAutomationScheduleKind.MANUAL_ONLY:
            if interval_seconds is not None:
                raise AutomationStoreInvalid("automation_manual_schedule_interval_forbidden")
        elif type(interval_seconds) is not int or not 60 <= interval_seconds <= 31_536_000:
            raise AutomationStoreInvalid("automation_schedule_interval_invalid")
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                replayed_record = self._definition_from_json(replay["entity"])
                self._verify_carried_spot_plan_replay(
                    cursor,
                    record=replayed_record,
                    command=command,
                )
                return AutomationStoreMutation(
                    replayed_record,
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            posture = self._current_control(cursor)
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition WHERE definition_id = %s FOR UPDATE",
                (definition_id,),
            )
            if self._row(cursor) is None:
                raise AutomationStoreNotFound("automation_definition_not_found")
            now = _utc_now()
            next_review_at = (
                now + timedelta(seconds=interval_seconds or 0)
                if kind is OperatorAutomationScheduleKind.INTERVAL_REVIEW_ONLY
                else None
            )
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_definition
                SET schedule_kind = %s, interval_seconds = %s,
                    next_review_at = %s, revision = revision + 1, updated_at = %s
                WHERE definition_id = %s RETURNING *
                """,
                (kind.value, interval_seconds, next_review_at, now, definition_id),
            )
            updated = self._row(cursor)
            assert updated is not None
            record = self._definition_from_row(updated, control_posture=posture, now=now)
            self._carry_spot_single_child_plan(
                cursor,
                record=record,
                command=command,
                audit_id=audit_id,
                recorded_at=now,
            )
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=None,
                from_state=None,
                to_state=kind.value,
                diagnostic_code=diagnostic_code,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=definition_id,
                audit_id=audit_id,
                result=self._definition_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    def clear_schedule(
        self,
        definition_id: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationDefinitionRecord]:
        return self.set_schedule(
            definition_id,
            OperatorAutomationScheduleKind.MANUAL_ONLY,
            interval_seconds=None,
            command=AutomationMutationCommand(
                idempotency_key=command.idempotency_key,
                payload_sha256=command.payload_sha256,
                actor_id=command.actor_id,
                correlation_id=command.correlation_id,
                operator_intent=command.operator_intent,
            ),
            _evidence_kind="clear",
        )

    def transition_control_posture(
        self,
        action: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationControlPlaneRecord]:
        normalized = _enum_value(action).lower()
        targets = {
            "pause": OperatorAutomationControlPosture.PAUSED,
            "resume": OperatorAutomationControlPosture.ACTIVE,
            "drain": OperatorAutomationControlPosture.DRAINING,
            "shutdown": OperatorAutomationControlPosture.SHUTDOWN,
        }
        if normalized not in targets:
            raise AutomationStoreInvalid("automation_control_action_invalid")
        resource_type = f"control_{normalized}"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                value = replay["entity"]
                record = AutomationControlPlaneRecord(
                    posture=OperatorAutomationControlPosture(value["posture"]),
                    updated_at=value["updated_at"],
                )
                return AutomationStoreMutation(
                    record,
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            current = self._current_control(cursor, for_update=True)
            target = targets[normalized]
            allowed_targets = {
                OperatorAutomationControlPosture.ACTIVE: {
                    OperatorAutomationControlPosture.PAUSED,
                    OperatorAutomationControlPosture.DRAINING,
                    OperatorAutomationControlPosture.SHUTDOWN,
                },
                OperatorAutomationControlPosture.PAUSED: {
                    OperatorAutomationControlPosture.ACTIVE,
                    OperatorAutomationControlPosture.DRAINING,
                    OperatorAutomationControlPosture.SHUTDOWN,
                },
                OperatorAutomationControlPosture.DRAINING: {
                    OperatorAutomationControlPosture.ACTIVE,
                    OperatorAutomationControlPosture.SHUTDOWN,
                },
                OperatorAutomationControlPosture.SHUTDOWN: {
                    OperatorAutomationControlPosture.ACTIVE,
                },
            }
            if target not in allowed_targets[current]:
                raise AutomationStoreConflict(
                    "automation_control_transition_invalid"
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"UPDATE {self._prefix}automation_control_plane_state SET posture = %s, updated_at = %s WHERE singleton = 1 RETURNING posture, updated_at",
                (target.value, now),
            )
            row = self._row(cursor)
            assert row is not None
            record = self._control_from_row(row)
            self._append_event(
                cursor,
                definition_id=None,
                run_id=None,
                from_state=current.value,
                to_state=target.value,
                diagnostic_code=f"automation_control_{normalized}",
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            result = {"posture": record.posture.value, "updated_at": record.updated_at}
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=audit_id,
                audit_id=audit_id,
                result=result,
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    @staticmethod
    def _spot_eligibility_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotEligibilityAttemptRecord:
        return AutomationSpotEligibilityAttemptRecord(
            run_id=str(row["run_id"]),
            cycle_number=int(row["cycle_number"]),
            category=row["category"],
            allowance_consumed=bool(row["allowance_consumed"]),
            outcome=row["outcome"],
            eligible=(
                bool(row["eligible"]) if row.get("eligible") is not None else None
            ),
            coinbase_api_call_count=(
                int(row["coinbase_api_call_count"])
                if row.get("coinbase_api_call_count") is not None
                else None
            ),
            call_count_exact=bool(row["call_count_exact"]),
            observed_at=_iso(row.get("observed_at")),
            fresh_until=_iso(row.get("fresh_until")),
            evidence_sha256=row.get("evidence_sha256"),
            diagnostic_code=row["diagnostic_code"],
            audit_id=str(row["audit_id"]),
            correlation_id=row["correlation_id"],
            started_at=_iso(row["started_at"]) or "",
            finalized_at=_iso(row.get("finalized_at")),
            portfolio_id_sha256=row.get("portfolio_id_sha256"),
        )

    @staticmethod
    def _spot_eligibility_cycle_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotEligibilityCycleRecord:
        state = str(row["state"])
        if state not in _AUTOMATION_SPOT_ELIGIBILITY_CYCLE_STATES:
            raise AutomationStoreUnavailable(
                "automation_spot_eligibility_cycle_state_invalid"
            )
        return AutomationSpotEligibilityCycleRecord(
            goal_key=row["goal_key"],
            cycle_number=int(row["cycle_number"]),
            policy_revision=int(row["policy_revision"]),
            run_id=str(row["run_id"]),
            definition_id=str(row["definition_id"]),
            definition_revision=int(row["definition_revision"]),
            plan_sha256=row["plan_sha256"],
            portfolio_id_sha256=row["portfolio_id_sha256"],
            product_id=row["product_id"],
            client_order_id=str(row["client_order_id"]),
            state=state,
            coinbase_api_call_count=(
                int(row["coinbase_api_call_count"])
                if row.get("coinbase_api_call_count") is not None
                else None
            ),
            call_count_exact=bool(row["call_count_exact"]),
            fresh_until=_iso(row.get("fresh_until")),
            diagnostic_code=row["diagnostic_code"],
            audit_id=str(row["audit_id"]),
            correlation_id=row["correlation_id"],
            started_at=_iso(row["started_at"]) or "",
            finalized_at=_iso(row.get("finalized_at")),
        )

    def list_spot_eligibility_cycles(
        self,
        *,
        goal_key: str = AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
    ) -> tuple[AutomationSpotEligibilityCycleRecord, ...]:
        if goal_key not in _AUTOMATION_SPOT_GOAL_KEYS:
            raise AutomationStoreInvalid("automation_spot_goal_key_invalid")
        rows = self.database.execute_query(
            f"""
            SELECT *
            FROM {self._prefix}automation_spot_eligibility_cycle
            WHERE goal_key = %s
            ORDER BY cycle_number
            """,
            (goal_key,),
        )
        return tuple(
            self._spot_eligibility_cycle_from_row(row) for row in rows
        )

    @staticmethod
    def _spot_eligibility_json(
        record: AutomationSpotEligibilityAttemptRecord,
    ) -> dict[str, Any]:
        return asdict(record)

    @staticmethod
    def _spot_eligibility_from_json(
        value: Mapping[str, Any],
    ) -> AutomationSpotEligibilityAttemptRecord:
        return AutomationSpotEligibilityAttemptRecord(
            run_id=value["run_id"],
            cycle_number=int(value["cycle_number"]),
            category=value["category"],
            allowance_consumed=bool(value["allowance_consumed"]),
            outcome=value.get("outcome"),
            eligible=(
                bool(value["eligible"])
                if value.get("eligible") is not None
                else None
            ),
            coinbase_api_call_count=(
                int(value["coinbase_api_call_count"])
                if value.get("coinbase_api_call_count") is not None
                else None
            ),
            call_count_exact=bool(value["call_count_exact"]),
            observed_at=value.get("observed_at"),
            fresh_until=value.get("fresh_until"),
            evidence_sha256=value.get("evidence_sha256"),
            diagnostic_code=value["diagnostic_code"],
            audit_id=value["audit_id"],
            correlation_id=value["correlation_id"],
            started_at=value["started_at"],
            finalized_at=value.get("finalized_at"),
            portfolio_id_sha256=value.get("portfolio_id_sha256"),
        )

    @staticmethod
    def _validate_spot_eligibility_category(*, category: str) -> None:
        if category not in _AUTOMATION_SPOT_ELIGIBILITY_CATEGORY_SET:
            raise AutomationStoreInvalid(
                "automation_spot_eligibility_category_invalid"
            )

    def _require_spot_run_plan(
        self,
        cursor: Any,
        *,
        run_id: str,
        allowed_states: frozenset[OperatorAutomationRunState],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        cursor.execute(
            f"SELECT * FROM {self._prefix}automation_run WHERE run_id = %s FOR UPDATE",
            (run_id,),
        )
        run = self._row(cursor)
        if run is None:
            raise AutomationStoreNotFound("automation_run_not_found")
        if OperatorAutomationRunState(run["state"]) not in allowed_states:
            raise AutomationStoreConflict("automation_spot_run_state_invalid")
        revision = run.get("definition_revision")
        if revision is None:
            raise AutomationStoreConflict("automation_spot_run_plan_missing")
        cursor.execute(
            f"""
            SELECT * FROM {self._prefix}automation_spot_single_child_plan
            WHERE definition_id = %s AND definition_revision = %s
            """,
            (str(run["definition_id"]), int(revision)),
        )
        plan = self._row(cursor)
        if plan is None:
            raise AutomationStoreConflict("automation_spot_run_plan_missing")
        return run, plan

    def _lock_open_spot_eligibility_cycle_cursor(
        self,
        cursor: Any,
        *,
        run: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        goal_key = self._spot_goal_key_for_definition_cursor(
            cursor,
            definition_id=str(run["definition_id"]),
        )
        cursor.execute(
            f"""
            SELECT *
            FROM {self._prefix}automation_spot_eligibility_cycle
            WHERE goal_key = %s AND state = 'OPEN'
            FOR UPDATE
            """,
            (goal_key,),
        )
        cycle = self._row(cursor)
        if cycle is None:
            raise AutomationStoreConflict(
                "automation_spot_eligibility_cycle_not_open"
            )
        expected_client_order_id = self.deterministic_spot_client_order_id(
            run_id=str(run["run_id"]),
            plan_sha256=plan["plan_sha256"],
            goal_key=goal_key,
        )
        if (
            str(cycle["run_id"]) != str(run["run_id"])
            or str(cycle["definition_id"]) != str(run["definition_id"])
            or int(cycle["definition_revision"])
            != int(run["definition_revision"])
            or cycle["plan_sha256"] != plan["plan_sha256"]
            or cycle["portfolio_id_sha256"]
            != plan["portfolio_id_sha256"]
            or cycle["product_id"] != plan["product_id"]
            or str(cycle["client_order_id"]) != expected_client_order_id
        ):
            raise AutomationStoreUnavailable(
                "automation_spot_eligibility_cycle_binding_invalid"
            )
        return cycle

    def _lock_spot_eligibility_attempts_cursor(
        self,
        cursor: Any,
        *,
        run_id: str,
        cycle_number: int,
    ) -> list[dict[str, Any]]:
        goal_key = self._spot_goal_key_for_run_cursor(
            cursor,
            run_id=run_id,
        )
        cursor.execute(
            f"""
            SELECT *
            FROM {self._prefix}automation_spot_eligibility_attempt
            WHERE run_id = %s AND goal_key = %s AND cycle_number = %s
            FOR UPDATE
            """,
            (
                run_id,
                goal_key,
                cycle_number,
            ),
        )
        return self._rows(cursor)

    @staticmethod
    def _require_next_spot_eligibility_category(
        attempts: list[Mapping[str, Any]],
        *,
        category: str,
        policy_revision: int,
    ) -> None:
        if policy_revision == 1:
            categories = _AUTOMATION_SPOT_ELIGIBILITY_V1_CATEGORIES
        elif policy_revision in {
            _AUTOMATION_SPOT_ELIGIBILITY_POLICY_REVISION,
            _AUTOMATION_SPOT_NEAR_MARKET_ELIGIBILITY_POLICY_REVISION,
            _AUTOMATION_SPOT_MINIMUM_SIZE_ELIGIBILITY_POLICY_REVISION,
        }:
            categories = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
        else:
            raise AutomationStoreUnavailable(
                "automation_spot_eligibility_policy_revision_invalid"
            )
        consumed = {str(row["category"]) for row in attempts}
        if category in consumed:
            raise AutomationStoreConflict(
                "automation_spot_eligibility_category_consumed"
            )
        if any(row["outcome"] is None for row in attempts):
            raise AutomationStoreConflict(
                "automation_spot_eligibility_attempt_in_progress"
            )
        expected_prefix = set(
            categories[: len(attempts)]
        )
        if consumed != expected_prefix:
            raise AutomationStoreUnavailable(
                "automation_spot_eligibility_sequence_corrupt"
            )
        if (
            len(attempts) >= len(categories)
            or category != categories[len(attempts)]
        ):
            raise AutomationStoreConflict(
                "automation_spot_eligibility_category_sequence_invalid"
            )

    def start_spot_eligibility_attempt(
        self,
        run_id: str,
        *,
        category: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotEligibilityAttemptRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        self._validate_spot_eligibility_category(category=category)
        resource_type = f"spot_eligibility_start_{category.lower()}"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            goal_key, _goal = self._lock_spot_goal_for_run_cursor(
                cursor,
                run_id=run_id,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._spot_eligibility_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            run, plan = self._require_spot_run_plan(
                cursor,
                run_id=run_id,
                allowed_states=frozenset({OperatorAutomationRunState.PREPARING}),
            )
            cycle = self._lock_open_spot_eligibility_cycle_cursor(
                cursor,
                run=run,
                plan=plan,
            )
            cycle_number = int(cycle["cycle_number"])
            attempts = self._lock_spot_eligibility_attempts_cursor(
                cursor,
                run_id=run_id,
                cycle_number=cycle_number,
            )
            self._require_next_spot_eligibility_category(
                attempts,
                category=category,
                policy_revision=int(cycle["policy_revision"]),
            )
            now = _utc_now()
            audit_id = _new_id()
            diagnostic = "automation_spot_eligibility_invocation_started"
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_eligibility_attempt (
                    run_id, goal_key, cycle_number, category, allowance_consumed,
                    outcome, eligible, coinbase_api_call_count, call_count_exact,
                    diagnostic_code, audit_id, correlation_id, started_at,
                    finalized_at
                ) VALUES (%s,%s,%s,%s,TRUE,NULL,NULL,NULL,FALSE,%s,%s,%s,%s,NULL)
                RETURNING *
                """,
                (
                    run_id,
                    goal_key,
                    cycle_number,
                    category,
                    diagnostic,
                    audit_id,
                    command.correlation_id,
                    now,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            record = self._spot_eligibility_from_row(row)
            self._append_event(
                cursor,
                definition_id=str(run["definition_id"]),
                run_id=run_id,
                from_state=run["state"],
                to_state=run["state"],
                diagnostic_code=diagnostic,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._spot_eligibility_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(
                record,
                audit_id,
                command.correlation_id,
            )

    def finalize_spot_eligibility_attempt(
        self,
        run_id: str,
        *,
        category: str,
        outcome: str,
        eligible: bool,
        coinbase_api_call_count: int | None,
        call_count_exact: bool,
        portfolio_id_sha256: str | None,
        observed_at: datetime | str | None,
        fresh_until: datetime | str | None,
        evidence_sha256: str | None,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotEligibilityAttemptRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        self._validate_spot_eligibility_category(category=category)
        normalized_outcome = str(outcome).upper()
        if normalized_outcome not in _AUTOMATION_SPOT_ELIGIBILITY_OUTCOMES:
            raise AutomationStoreInvalid(
                "automation_spot_eligibility_outcome_invalid"
            )
        normalized_observed_at = _aware_utc_datetime(observed_at)
        normalized_fresh_until = _aware_utc_datetime(fresh_until)
        valid_evidence_sha256 = bool(
            evidence_sha256 is not None
            and _SHA256_PATTERN.fullmatch(evidence_sha256) is not None
        )
        known_result = (
            normalized_outcome == "SUCCEEDED"
            and eligible is True
            and call_count_exact is True
            and type(coinbase_api_call_count) is int
            and coinbase_api_call_count >= 1
            and normalized_observed_at is not None
            and normalized_fresh_until is not None
            and normalized_fresh_until > normalized_observed_at
            and valid_evidence_sha256
        ) or (
            normalized_outcome == "REJECTED"
            and eligible is False
            and call_count_exact is True
            and type(coinbase_api_call_count) is int
            and coinbase_api_call_count >= 0
            and normalized_observed_at is not None
            and (
                fresh_until is None
                or (
                    normalized_fresh_until is not None
                    and normalized_fresh_until > normalized_observed_at
                )
            )
            and (evidence_sha256 is None or valid_evidence_sha256)
        )
        unknown_result = (
            normalized_outcome == "UNKNOWN"
            and eligible is False
            and call_count_exact is False
            and coinbase_api_call_count is None
            and observed_at is None
            and fresh_until is None
            and evidence_sha256 is None
        )
        missing_market_observation_rejection = (
            normalized_outcome == "REJECTED"
            and category == "BEST_BID_ASK"
            and eligible is False
            and call_count_exact is True
            and type(coinbase_api_call_count) is int
            and coinbase_api_call_count >= 0
            and observed_at is None
            and fresh_until is None
            and evidence_sha256 is None
        )
        if type(eligible) is not bool or type(call_count_exact) is not bool or not (
            known_result or unknown_result or missing_market_observation_rejection
        ):
            raise AutomationStoreInvalid(
                "automation_spot_eligibility_result_invalid"
            )
        catalog_proof = bool(
            category == "PORTFOLIO_CATALOG"
            and normalized_outcome == "SUCCEEDED"
            and eligible
            and call_count_exact
            and coinbase_api_call_count is not None
        )
        if catalog_proof:
            if portfolio_id_sha256 is None:
                raise AutomationStoreInvalid(
                    "automation_spot_portfolio_binding_required"
                )
            if _SHA256_PATTERN.fullmatch(portfolio_id_sha256) is None:
                raise AutomationStoreInvalid(
                    "automation_spot_portfolio_binding_invalid"
                )
        elif portfolio_id_sha256 is not None:
            raise AutomationStoreInvalid(
                "automation_spot_portfolio_binding_forbidden"
            )
        resource_type = f"spot_eligibility_finalize_{category.lower()}"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            goal_key, _goal = self._lock_spot_goal_for_run_cursor(
                cursor,
                run_id=run_id,
            )
            if (
                missing_market_observation_rejection
                and goal_key
                not in {
                    AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
                    *AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS,
                    *AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS,
                }
            ):
                raise AutomationStoreInvalid(
                    "automation_spot_eligibility_result_invalid"
                )
            if replay is not None:
                return AutomationStoreMutation(
                    self._spot_eligibility_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            run, plan = self._require_spot_run_plan(
                cursor,
                run_id=run_id,
                allowed_states=frozenset({OperatorAutomationRunState.PREPARING}),
            )
            if (
                catalog_proof
                and portfolio_id_sha256 != plan["portfolio_id_sha256"]
            ):
                raise AutomationStoreConflict(
                    "automation_spot_portfolio_binding_mismatch"
                )
            cycle = self._lock_open_spot_eligibility_cycle_cursor(
                cursor,
                run=run,
                plan=plan,
            )
            cycle_number = int(cycle["cycle_number"])
            attempts = self._lock_spot_eligibility_attempts_cursor(
                cursor,
                run_id=run_id,
                cycle_number=cycle_number,
            )
            attempt = next(
                (
                    row
                    for row in attempts
                    if str(row["category"]) == category
                ),
                None,
            )
            if attempt is None:
                raise AutomationStoreNotFound(
                    "automation_spot_eligibility_attempt_not_found"
                )
            if attempt["outcome"] is not None:
                raise AutomationStoreConflict(
                    "automation_spot_eligibility_already_finalized"
                )
            now = _utc_now()
            audit_id = _new_id()
            diagnostic = (
                f"automation_spot_eligibility_{normalized_outcome.lower()}"
            )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_eligibility_attempt
                SET outcome = %s, eligible = %s,
                    coinbase_api_call_count = %s, call_count_exact = %s,
                    diagnostic_code = %s, audit_id = %s,
                    correlation_id = %s, finalized_at = %s,
                    portfolio_id_sha256 = %s, observed_at = %s,
                    fresh_until = %s, evidence_sha256 = %s
                WHERE run_id = %s AND cycle_number = %s AND category = %s
                RETURNING *
                """,
                (
                    normalized_outcome,
                    eligible,
                    coinbase_api_call_count,
                    call_count_exact,
                    diagnostic,
                    audit_id,
                    command.correlation_id,
                    now,
                    portfolio_id_sha256,
                    normalized_observed_at,
                    normalized_fresh_until,
                    evidence_sha256,
                    run_id,
                    cycle_number,
                    category,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            record = self._spot_eligibility_from_row(row)
            policy_revision = int(cycle["policy_revision"])
            if policy_revision == 1:
                cycle_categories = _AUTOMATION_SPOT_ELIGIBILITY_V1_CATEGORIES
            elif policy_revision in {
                _AUTOMATION_SPOT_ELIGIBILITY_POLICY_REVISION,
                _AUTOMATION_SPOT_NEAR_MARKET_ELIGIBILITY_POLICY_REVISION,
                _AUTOMATION_SPOT_MINIMUM_SIZE_ELIGIBILITY_POLICY_REVISION,
                _AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_POLICY_REVISION,
            }:
                cycle_categories = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
            else:
                raise AutomationStoreUnavailable(
                    "automation_spot_eligibility_policy_revision_invalid"
                )
            terminal_cycle_state: str | None = None
            if normalized_outcome in {"REJECTED", "UNKNOWN"}:
                terminal_cycle_state = normalized_outcome
            elif (
                category == cycle_categories[-1]
                and len(attempts)
                == len(cycle_categories)
            ):
                terminal_cycle_state = "SUCCEEDED"
            if terminal_cycle_state is not None:
                if terminal_cycle_state == "UNKNOWN":
                    cycle_call_count = None
                    cycle_count_exact = False
                    cycle_fresh_until = None
                else:
                    prior_counts = [
                        int(item["coinbase_api_call_count"])
                        for item in attempts
                        if item["category"] != category
                        and item["coinbase_api_call_count"] is not None
                    ]
                    cycle_call_count = sum(prior_counts) + int(
                        coinbase_api_call_count or 0
                    )
                    cycle_count_exact = True
                    if terminal_cycle_state == "SUCCEEDED":
                        successful_deadlines = [
                            item["fresh_until"]
                            for item in attempts
                            if item["category"] != category
                            and item["outcome"] == "SUCCEEDED"
                            and item["fresh_until"] is not None
                        ]
                        if (
                            len(successful_deadlines)
                            != len(cycle_categories) - 1
                            or normalized_fresh_until is None
                        ):
                            raise AutomationStoreUnavailable(
                                "automation_spot_eligibility_freshness_corrupt"
                            )
                        cycle_fresh_until = min(
                            *successful_deadlines,
                            normalized_fresh_until,
                        )
                    else:
                        cycle_fresh_until = normalized_fresh_until
                cycle_diagnostic = (
                    f"automation_spot_eligibility_cycle_"
                    f"{terminal_cycle_state.lower()}"
                )
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_eligibility_cycle
                    SET state = %s, coinbase_api_call_count = %s,
                        call_count_exact = %s, fresh_until = %s,
                        diagnostic_code = %s,
                        audit_id = %s, correlation_id = %s, finalized_at = %s
                    WHERE goal_key = %s AND cycle_number = %s
                      AND state = 'OPEN'
                    """,
                    (
                        terminal_cycle_state,
                        cycle_call_count,
                        cycle_count_exact,
                        cycle_fresh_until,
                        cycle_diagnostic,
                        audit_id,
                        command.correlation_id,
                        now,
                        goal_key,
                        cycle_number,
                    ),
                )
                if cursor.rowcount != 1:
                    raise AutomationStoreConflict(
                        "automation_spot_eligibility_cycle_not_open"
                    )
            self._append_event(
                cursor,
                definition_id=str(run["definition_id"]),
                run_id=run_id,
                from_state=run["state"],
                to_state=run["state"],
                diagnostic_code=diagnostic,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            if terminal_cycle_state is not None:
                if terminal_cycle_state == "SUCCEEDED":
                    target_state = (
                        OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
                    )
                    run_diagnostic = "awaiting_operator_authorization"
                else:
                    target_state = OperatorAutomationRunState.BLOCKED
                    run_diagnostic = "automation_spot_eligibility_refresh_required"
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_run
                    SET state = %s, diagnostic_code = %s, audit_id = %s,
                        correlation_id = %s, updated_at = %s
                    WHERE run_id = %s AND state = %s
                    """,
                    (
                        target_state.value,
                        run_diagnostic,
                        audit_id,
                        command.correlation_id,
                        now,
                        run_id,
                        OperatorAutomationRunState.PREPARING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise AutomationStoreConflict(
                        "automation_spot_run_state_invalid"
                    )
                self._append_event(
                    cursor,
                    definition_id=str(run["definition_id"]),
                    run_id=run_id,
                    from_state=OperatorAutomationRunState.PREPARING.value,
                    to_state=target_state.value,
                    diagnostic_code=run_diagnostic,
                    audit_id=audit_id,
                    idempotency_key_sha256=_hash(command.idempotency_key),
                    correlation_id=command.correlation_id,
                    recorded_at=now,
                )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._spot_eligibility_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(
                record,
                audit_id,
                command.correlation_id,
            )

    def list_spot_eligibility_attempts(
        self,
        run_id: str,
        *,
        cycle_number: int | None = None,
    ) -> tuple[AutomationSpotEligibilityAttemptRecord, ...]:
        _validate_id(run_id, code="automation_run_id_invalid")
        if cycle_number is not None and (
            type(cycle_number) is not int or not 1 <= cycle_number <= 10
        ):
            raise AutomationStoreInvalid(
                "automation_spot_eligibility_cycle_invalid"
            )
        params: tuple[Any, ...]
        where = "run_id = %s"
        if cycle_number is None:
            params = (run_id,)
        else:
            where += " AND cycle_number = %s"
            params = (run_id, cycle_number)
        rows = self.database.execute_query(
            f"""
            SELECT * FROM {self._prefix}automation_spot_eligibility_attempt
            WHERE {where}
            ORDER BY cycle_number, category
            """,
            params,
        )
        return tuple(self._spot_eligibility_from_row(row) for row in rows)

    @staticmethod
    def _spot_execution_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotRunExecutionRecord:
        return AutomationSpotRunExecutionRecord(
            run_id=str(row["run_id"]),
            policy_revision=int(row["policy_revision"]),
            definition_id=str(row["definition_id"]),
            definition_revision=int(row["definition_revision"]),
            eligibility_cycle=int(row["eligibility_cycle"]),
            plan_sha256=row["plan_sha256"],
            portfolio_id_sha256=row["portfolio_id_sha256"],
            product_id=row["product_id"],
            client_order_id=str(row["client_order_id"]),
            create_allowance_consumed=bool(row["create_allowance_consumed"]),
            create_outcome=row["create_outcome"],
            create_call_count=(
                int(row["create_call_count"])
                if row.get("create_call_count") is not None
                else None
            ),
            create_call_count_exact=bool(row["create_call_count_exact"]),
            create_read_call_count=(
                int(row["create_read_call_count"])
                if row.get("create_read_call_count") is not None
                else None
            ),
            create_read_call_count_exact=bool(
                row["create_read_call_count_exact"]
            ),
            cancel_allowance_consumed=bool(row["cancel_allowance_consumed"]),
            cancel_outcome=row["cancel_outcome"],
            cancel_call_count=(
                int(row["cancel_call_count"])
                if row.get("cancel_call_count") is not None
                else None
            ),
            cancel_call_count_exact=bool(row["cancel_call_count_exact"]),
            cancel_read_call_count=(
                int(row["cancel_read_call_count"])
                if row.get("cancel_read_call_count") is not None
                else None
            ),
            cancel_read_call_count_exact=bool(
                row["cancel_read_call_count_exact"]
            ),
            child_terminal=(
                bool(row["child_terminal"])
                if row.get("child_terminal") is not None
                else None
            ),
            audit_id=str(row["audit_id"]),
            correlation_id=row["correlation_id"],
            created_at=_iso(row["created_at"]) or "",
            updated_at=_iso(row["updated_at"]) or "",
        )

    @staticmethod
    def _spot_execution_json(
        record: AutomationSpotRunExecutionRecord,
    ) -> dict[str, Any]:
        return asdict(record)

    @staticmethod
    def _spot_execution_from_json(
        value: Mapping[str, Any],
    ) -> AutomationSpotRunExecutionRecord:
        return AutomationSpotRunExecutionRecord(
            run_id=value["run_id"],
            policy_revision=int(value.get("policy_revision", 1)),
            definition_id=value["definition_id"],
            definition_revision=int(value["definition_revision"]),
            eligibility_cycle=int(value["eligibility_cycle"]),
            plan_sha256=value["plan_sha256"],
            portfolio_id_sha256=value["portfolio_id_sha256"],
            product_id=value["product_id"],
            client_order_id=value["client_order_id"],
            create_allowance_consumed=bool(value["create_allowance_consumed"]),
            create_outcome=value.get("create_outcome"),
            create_call_count=(
                int(value["create_call_count"])
                if value.get("create_call_count") is not None
                else None
            ),
            create_call_count_exact=bool(value["create_call_count_exact"]),
            create_read_call_count=(
                int(value["create_read_call_count"])
                if value.get("create_read_call_count") is not None
                else None
            ),
            create_read_call_count_exact=bool(
                value.get("create_read_call_count_exact", False)
            ),
            cancel_allowance_consumed=bool(value["cancel_allowance_consumed"]),
            cancel_outcome=value.get("cancel_outcome"),
            cancel_call_count=(
                int(value["cancel_call_count"])
                if value.get("cancel_call_count") is not None
                else None
            ),
            cancel_call_count_exact=bool(value["cancel_call_count_exact"]),
            cancel_read_call_count=(
                int(value["cancel_read_call_count"])
                if value.get("cancel_read_call_count") is not None
                else None
            ),
            cancel_read_call_count_exact=bool(
                value.get("cancel_read_call_count_exact", False)
            ),
            child_terminal=(
                bool(value["child_terminal"])
                if value.get("child_terminal") is not None
                else None
            ),
            audit_id=value["audit_id"],
            correlation_id=value["correlation_id"],
            created_at=value["created_at"],
            updated_at=value["updated_at"],
        )

    @staticmethod
    def _spot_goal_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotLiveProofGoalRecord:
        return AutomationSpotLiveProofGoalRecord(
            goal_key=row["goal_key"],
            create_allowance_consumed=bool(row["create_allowance_consumed"]),
            cancel_allowance_consumed=bool(row["cancel_allowance_consumed"]),
            bound_run_id=(
                str(row["bound_run_id"])
                if row.get("bound_run_id") is not None
                else None
            ),
            client_order_id=(
                str(row["client_order_id"])
                if row.get("client_order_id") is not None
                else None
            ),
            create_outcome=row["create_outcome"],
            cancel_outcome=row["cancel_outcome"],
            updated_at=_iso(row["updated_at"]) or "",
        )

    @staticmethod
    def _spot_preview_goal_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotPreviewGatedGoalRecord:
        return AutomationSpotPreviewGatedGoalRecord(
            goal_key=row["goal_key"],
            definition_id=(
                str(row["definition_id"])
                if row.get("definition_id") is not None
                else None
            ),
            bound_run_id=(
                str(row["bound_run_id"])
                if row.get("bound_run_id") is not None
                else None
            ),
            client_order_id=(
                str(row["client_order_id"])
                if row.get("client_order_id") is not None
                else None
            ),
            eligibility_cycle=(
                int(row["eligibility_cycle"])
                if row.get("eligibility_cycle") is not None
                else None
            ),
            plan_sha256=row.get("plan_sha256"),
            portfolio_id_sha256=row.get("portfolio_id_sha256"),
            product_id=row.get("product_id"),
            preview_allowance_consumed=bool(
                row["preview_allowance_consumed"]
            ),
            preview_outcome=row.get("preview_outcome"),
            preview_failure_class=row.get("preview_failure_class"),
            preview_rejection_code=row.get("preview_rejection_code"),
            preview_warning_present=(
                bool(row["preview_warning_present"])
                if row.get("preview_warning_present") is not None
                else None
            ),
            preview_id_sha256=row.get("preview_id_sha256"),
            preview_call_count=(
                int(row["preview_call_count"])
                if row.get("preview_call_count") is not None
                else None
            ),
            preview_call_count_exact=bool(row["preview_call_count_exact"]),
            create_allowance_consumed=bool(
                row["create_allowance_consumed"]
            ),
            create_outcome=row.get("create_outcome"),
            cancel_allowance_consumed=bool(
                row["cancel_allowance_consumed"]
            ),
            cancel_outcome=row.get("cancel_outcome"),
            updated_at=_iso(row["updated_at"]) or "",
        )

    @staticmethod
    def deterministic_spot_client_order_id(
        *,
        run_id: str,
        plan_sha256: str,
        goal_key: str = AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
    ) -> str:
        _validate_id(run_id, code="automation_run_id_invalid")
        if _SHA256_PATTERN.fullmatch(plan_sha256) is None:
            raise AutomationStoreInvalid("automation_spot_plan_hash_invalid")
        if goal_key not in _AUTOMATION_SPOT_GOAL_KEYS:
            raise AutomationStoreInvalid("automation_spot_goal_key_invalid")
        return str(
            uuid.uuid5(
                _AUTOMATION_SPOT_CLIENT_ORDER_NAMESPACE,
                f"{goal_key}:{run_id}:{plan_sha256}",
            )
        )

    def _require_spot_eligible_cycle(
        self,
        cursor: Any,
        *,
        run: Mapping[str, Any],
        plan: Mapping[str, Any],
        cycle_number: int,
    ) -> None:
        run_id = str(run["run_id"])
        goal_key = self._spot_goal_key_for_definition_cursor(
            cursor,
            definition_id=str(run["definition_id"]),
        )
        cursor.execute(
            f"""
            SELECT *
            FROM {self._prefix}automation_spot_eligibility_cycle
            WHERE goal_key = %s AND cycle_number = %s
            FOR UPDATE
            """,
            (goal_key, cycle_number),
        )
        cycle = self._row(cursor)
        cycle_fresh_until = (
            _aware_utc_datetime(cycle.get("fresh_until"))
            if cycle is not None
            else None
        )
        expected_client_order_id = self.deterministic_spot_client_order_id(
            run_id=run_id,
            plan_sha256=plan["plan_sha256"],
            goal_key=goal_key,
        )
        expected_policy_revision = _spot_policy_revision_for_goal(goal_key)
        if (
            cycle is None
            or int(cycle.get("policy_revision") or 0)
            != expected_policy_revision
            or cycle["state"] != "SUCCEEDED"
            or not bool(cycle["call_count_exact"])
            or cycle["coinbase_api_call_count"] is None
            or cycle_fresh_until is None
            or cycle_fresh_until <= _utc_now()
            or str(cycle["run_id"]) != run_id
            or str(cycle["definition_id"]) != str(run["definition_id"])
            or int(cycle["definition_revision"])
            != int(run["definition_revision"])
            or cycle["plan_sha256"] != plan["plan_sha256"]
            or cycle["portfolio_id_sha256"]
            != plan["portfolio_id_sha256"]
            or cycle["product_id"] != plan["product_id"]
            or str(cycle["client_order_id"]) != expected_client_order_id
        ):
            raise AutomationStoreConflict(
                "automation_spot_exact_eligibility_not_proven"
            )
        cursor.execute(
            f"""
            SELECT category, outcome, eligible, coinbase_api_call_count,
                   call_count_exact, portfolio_id_sha256
            FROM {self._prefix}automation_spot_eligibility_attempt
            WHERE run_id = %s AND goal_key = %s AND cycle_number = %s
            FOR UPDATE
            """,
            (run_id, goal_key, cycle_number),
        )
        attempts = self._rows(cursor)
        if (
            {row["category"] for row in attempts}
            != _AUTOMATION_SPOT_ELIGIBILITY_CATEGORY_SET
            or any(
                row["outcome"] != "SUCCEEDED"
                or not bool(row["eligible"])
                or not bool(row["call_count_exact"])
                or row["coinbase_api_call_count"] is None
                or (
                    row["category"] == "PORTFOLIO_CATALOG"
                    and row.get("portfolio_id_sha256")
                    != plan["portfolio_id_sha256"]
                )
                or (
                    row["category"] != "PORTFOLIO_CATALOG"
                    and row.get("portfolio_id_sha256") is not None
                )
                for row in attempts
            )
        ):
            raise AutomationStoreConflict(
                "automation_spot_exact_eligibility_not_proven"
            )

    @staticmethod
    def _spot_preview_goal_json(
        record: AutomationSpotPreviewGatedGoalRecord,
    ) -> dict[str, Any]:
        return asdict(record)

    @staticmethod
    def _spot_preview_goal_from_json(
        value: Mapping[str, Any],
    ) -> AutomationSpotPreviewGatedGoalRecord:
        return AutomationSpotPreviewGatedGoalRecord(
            goal_key=value["goal_key"],
            definition_id=value.get("definition_id"),
            bound_run_id=value.get("bound_run_id"),
            client_order_id=value.get("client_order_id"),
            eligibility_cycle=(
                int(value["eligibility_cycle"])
                if value.get("eligibility_cycle") is not None
                else None
            ),
            plan_sha256=value.get("plan_sha256"),
            portfolio_id_sha256=value.get("portfolio_id_sha256"),
            product_id=value.get("product_id"),
            preview_allowance_consumed=bool(
                value["preview_allowance_consumed"]
            ),
            preview_outcome=value.get("preview_outcome"),
            preview_failure_class=value.get("preview_failure_class"),
            preview_rejection_code=value.get("preview_rejection_code"),
            preview_warning_present=value.get("preview_warning_present"),
            preview_id_sha256=value.get("preview_id_sha256"),
            preview_call_count=(
                int(value["preview_call_count"])
                if value.get("preview_call_count") is not None
                else None
            ),
            preview_call_count_exact=bool(value["preview_call_count_exact"]),
            create_allowance_consumed=bool(
                value["create_allowance_consumed"]
            ),
            create_outcome=value.get("create_outcome"),
            cancel_allowance_consumed=bool(
                value["cancel_allowance_consumed"]
            ),
            cancel_outcome=value.get("cancel_outcome"),
            updated_at=value["updated_at"],
        )

    def start_spot_preview_invocation(
        self,
        run_id: str,
        *,
        eligibility_cycle: int,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotPreviewGatedGoalRecord]:
        """Durably consume the V2 Preview allowance before network I/O."""

        _validate_id(run_id, code="automation_run_id_invalid")
        if type(eligibility_cycle) is not int or not 1 <= eligibility_cycle <= 10:
            raise AutomationStoreInvalid(
                "automation_spot_eligibility_cycle_invalid"
            )
        resource_type = "spot_preview_invocation_start"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            goal_key, goal = self._lock_spot_goal_for_run_cursor(
                cursor,
                run_id=run_id,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._spot_preview_goal_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            if goal_key not in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS:
                raise AutomationStoreConflict(
                    "automation_spot_preview_goal_mismatch"
                )
            if bool(goal["preview_allowance_consumed"]):
                raise AutomationStoreConflict(
                    "automation_spot_preview_allowance_consumed"
                )
            run, plan = self._require_spot_run_plan(
                cursor,
                run_id=run_id,
                allowed_states=frozenset(
                    {OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION}
                ),
            )
            if str(goal.get("definition_id")) != str(run["definition_id"]):
                raise AutomationStoreConflict(
                    "automation_spot_preview_candidate_mismatch"
                )
            self._require_spot_eligible_cycle(
                cursor,
                run=run,
                plan=plan,
                cycle_number=eligibility_cycle,
            )
            client_order_id = self.deterministic_spot_client_order_id(
                run_id=run_id,
                plan_sha256=plan["plan_sha256"],
                goal_key=goal_key,
            )
            now = _utc_now()
            audit_id = _new_id()
            diagnostic = "automation_spot_preview_invocation_started"
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_preview_gated_goal
                SET bound_run_id = %s, client_order_id = %s,
                    eligibility_cycle = %s, plan_sha256 = %s,
                    portfolio_id_sha256 = %s, product_id = %s,
                    preview_allowance_consumed = TRUE, updated_at = %s
                WHERE goal_key = %s AND preview_allowance_consumed = FALSE
                RETURNING *
                """,
                (
                    run_id,
                    client_order_id,
                    eligibility_cycle,
                    plan["plan_sha256"],
                    plan["portfolio_id_sha256"],
                    plan["product_id"],
                    now,
                    goal_key,
                ),
            )
            goal_row = self._row(cursor)
            if goal_row is None:
                raise AutomationStoreConflict(
                    "automation_spot_preview_allowance_consumed"
                )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_run
                SET diagnostic_code = %s, audit_id = %s,
                    correlation_id = %s, client_order_id = %s,
                    live_attempt_consumed = TRUE, updated_at = %s
                WHERE run_id = %s
                """,
                (
                    diagnostic,
                    audit_id,
                    command.correlation_id,
                    client_order_id,
                    now,
                    run_id,
                ),
            )
            record = self._spot_preview_goal_from_row(goal_row)
            self._append_event(
                cursor,
                definition_id=str(run["definition_id"]),
                run_id=run_id,
                from_state=run["state"],
                to_state=run["state"],
                diagnostic_code=diagnostic,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._spot_preview_goal_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(
                record,
                audit_id,
                command.correlation_id,
            )

    def finalize_spot_preview_invocation(
        self,
        run_id: str,
        *,
        outcome: str,
        failure_class: str,
        rejection_code: str | None,
        warning_present: bool,
        preview_id_sha256: str | None,
        preview_call_count: int | None,
        call_count_exact: bool,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotPreviewGatedGoalRecord]:
        """Persist only allowlisted Preview classification and accounting."""

        _validate_id(run_id, code="automation_run_id_invalid")
        normalized = str(outcome).upper()
        allowed_failures = {
            "NONE",
            "DOCUMENTED_REJECTION",
            "UNCLASSIFIED_REJECTION",
            "RESPONSE_SCHEMA_INVALID",
            "RESPONSE_DECODING_FAILURE",
            "HTTP_CLIENT_RESPONSE",
            "HTTP_SERVER_RESPONSE",
            "HTTP_REDIRECT_RESPONSE",
            "HTTP_RESPONSE_INVALID",
            "REQUEST_COMPOSITION_FAILURE",
            "SDK_INVOCATION_UNKNOWN",
            "DNS_RESOLUTION_FAILURE",
            "TCP_CONNECTION_FAILURE",
            "CONNECT_TIMEOUT",
            "TLS_OR_CERTIFICATE_FAILURE",
            "PROXY_FAILURE",
            "READ_TIMEOUT",
            "CONNECTION_RESET",
            "TRANSPORT_UNKNOWN",
        }
        if (
            normalized not in _AUTOMATION_SPOT_MUTATION_OUTCOMES
            or failure_class not in allowed_failures
            or (
                rejection_code is not None
                and rejection_code
                not in _AUTOMATION_SPOT_PREVIEW_REJECTION_CODES
            )
            or type(warning_present) is not bool
            or type(call_count_exact) is not bool
            or (
                call_count_exact
                and preview_call_count not in {0, 1}
            )
            or (
                not call_count_exact
                and (
                    preview_call_count is not None
                    or normalized != "UNKNOWN"
                )
            )
            or (normalized == "ACCEPTED" and failure_class != "NONE")
            or (
                rejection_code is not None
                and (
                    normalized != "REJECTED"
                    or failure_class != "DOCUMENTED_REJECTION"
                )
            )
            or (normalized == "REJECTED" and failure_class not in {
                "DOCUMENTED_REJECTION",
                "UNCLASSIFIED_REJECTION",
            })
            or (normalized == "UNKNOWN" and failure_class not in {
                "RESPONSE_SCHEMA_INVALID",
                "RESPONSE_DECODING_FAILURE",
                "HTTP_CLIENT_RESPONSE",
                "HTTP_SERVER_RESPONSE",
                "HTTP_REDIRECT_RESPONSE",
                "HTTP_RESPONSE_INVALID",
                "REQUEST_COMPOSITION_FAILURE",
                "SDK_INVOCATION_UNKNOWN",
                "DNS_RESOLUTION_FAILURE",
                "TCP_CONNECTION_FAILURE",
                "CONNECT_TIMEOUT",
                "TLS_OR_CERTIFICATE_FAILURE",
                "PROXY_FAILURE",
                "READ_TIMEOUT",
                "CONNECTION_RESET",
                "TRANSPORT_UNKNOWN",
            })
            or (
                normalized == "UNKNOWN"
                and failure_class
                in _AUTOMATION_SPOT_EXACT_PREVIEW_UNKNOWN_FAILURE_CLASSES
                and (
                    not call_count_exact
                    or preview_call_count != 1
                )
            )
            or (
                normalized == "UNKNOWN"
                and failure_class
                in _AUTOMATION_SPOT_EXACT_ZERO_PREVIEW_UNKNOWN_FAILURE_CLASSES
                and (
                    not call_count_exact
                    or preview_call_count != 0
                )
            )
            or (
                normalized == "UNKNOWN"
                and failure_class
                in _AUTOMATION_SPOT_INEXACT_PREVIEW_UNKNOWN_FAILURE_CLASSES
                and (
                    call_count_exact
                    or preview_call_count is not None
                )
            )
            or (
                preview_id_sha256 is not None
                and (
                    normalized != "ACCEPTED"
                    or _SHA256_PATTERN.fullmatch(preview_id_sha256) is None
                )
            )
        ):
            raise AutomationStoreInvalid(
                "automation_spot_preview_result_invalid"
            )
        resource_type = "spot_preview_invocation_finalize"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            goal_key, goal = self._lock_spot_goal_for_run_cursor(
                cursor,
                run_id=run_id,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._spot_preview_goal_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_run "
                "WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            run = self._row(cursor)
            if (
                goal_key not in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS
                or run is None
                or str(goal.get("bound_run_id")) != run_id
                or not bool(goal["preview_allowance_consumed"])
                or goal.get("preview_outcome") is not None
                or run.get("diagnostic_code")
                != "automation_spot_preview_invocation_started"
            ):
                raise AutomationStoreConflict(
                    "automation_spot_preview_invocation_not_started"
                )
            if normalized == "ACCEPTED":
                target = OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
                diagnostic = "automation_spot_preview_accepted_create_ready"
            elif normalized == "REJECTED":
                target = OperatorAutomationRunState.TERMINAL
                diagnostic = "automation_spot_preview_rejected"
            else:
                target = OperatorAutomationRunState.UNKNOWN_CONSUMED
                diagnostic = "automation_spot_preview_unknown_consumed"
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_preview_gated_goal
                SET preview_outcome = %s, preview_failure_class = %s,
                    preview_rejection_code = %s,
                    preview_warning_present = %s, preview_id_sha256 = %s,
                    preview_call_count = %s,
                    preview_call_count_exact = %s, updated_at = %s
                WHERE goal_key = %s AND preview_outcome IS NULL
                RETURNING *
                """,
                (
                    normalized,
                    failure_class,
                    rejection_code,
                    warning_present,
                    preview_id_sha256,
                    preview_call_count,
                    call_count_exact,
                    now,
                    goal_key,
                ),
            )
            goal_row = self._row(cursor)
            if goal_row is None:
                raise AutomationStoreConflict(
                    "automation_spot_preview_already_finalized"
                )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_run
                SET state = %s, diagnostic_code = %s, audit_id = %s,
                    correlation_id = %s,
                    coinbase_api_call_count = coinbase_api_call_count + %s,
                    updated_at = %s
                WHERE run_id = %s
                """,
                (
                    target.value,
                    diagnostic,
                    audit_id,
                    command.correlation_id,
                    preview_call_count
                    if call_count_exact and preview_call_count is not None
                    else 0,
                    now,
                    run_id,
                ),
            )
            record = self._spot_preview_goal_from_row(goal_row)
            self._append_event(
                cursor,
                definition_id=str(run["definition_id"]),
                run_id=run_id,
                from_state=run["state"],
                to_state=target.value,
                diagnostic_code=diagnostic,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._spot_preview_goal_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(
                record,
                audit_id,
                command.correlation_id,
            )
    @staticmethod
    def _validate_spot_mutation_result(
        *,
        operation: Literal["CREATE", "SAFE_CLOSEOUT"],
        outcome: str,
        child_terminal: bool | None,
        coinbase_api_call_count: int | None,
        call_count_exact: bool,
    ) -> str:
        if operation not in {"CREATE", "SAFE_CLOSEOUT"}:
            raise AutomationStoreInvalid(
                "automation_spot_mutation_operation_invalid"
            )
        normalized = str(outcome).upper()
        if normalized not in _AUTOMATION_SPOT_MUTATION_OUTCOMES:
            raise AutomationStoreInvalid("automation_spot_mutation_outcome_invalid")
        if type(call_count_exact) is not bool:
            raise AutomationStoreInvalid(
                "automation_spot_mutation_accounting_invalid"
            )
        known_exact_count = bool(
            call_count_exact
            and type(coinbase_api_call_count) is int
            and coinbase_api_call_count in {0, 1}
        )
        unknown_count = bool(
            not call_count_exact and coinbase_api_call_count is None
        )
        if normalized == "ACCEPTED":
            accounting_valid = bool(
                known_exact_count
                and (
                    operation == "SAFE_CLOSEOUT"
                    or coinbase_api_call_count == 1
                )
            )
        else:
            accounting_valid = known_exact_count or unknown_count
        if not accounting_valid:
            raise AutomationStoreInvalid(
                "automation_spot_mutation_accounting_invalid"
            )
        if normalized == "ACCEPTED":
            if type(child_terminal) is not bool:
                raise AutomationStoreInvalid(
                    "automation_spot_mutation_child_state_invalid"
                )
        elif normalized == "REJECTED":
            if child_terminal is not False:
                raise AutomationStoreInvalid(
                    "automation_spot_mutation_child_state_invalid"
                )
        elif child_terminal is not None:
            raise AutomationStoreInvalid(
                "automation_spot_mutation_child_state_invalid"
            )
        return normalized

    @staticmethod
    def _validate_spot_read_accounting(
        *,
        read_call_count: int | None,
        read_call_count_exact: bool,
        max_read_call_count: int,
    ) -> None:
        if type(read_call_count_exact) is not bool:
            raise AutomationStoreInvalid(
                "automation_spot_read_accounting_invalid"
            )
        if read_call_count_exact:
            if (
                type(read_call_count) is not int
                or not 0 <= read_call_count <= max_read_call_count
            ):
                raise AutomationStoreInvalid(
                    "automation_spot_read_accounting_invalid"
                )
        elif read_call_count is not None:
            raise AutomationStoreInvalid(
                "automation_spot_read_accounting_invalid"
            )

    def start_spot_create_invocation(
        self,
        run_id: str,
        *,
        eligibility_cycle: int,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotRunExecutionRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        if type(eligibility_cycle) is not int or not 1 <= eligibility_cycle <= 10:
            raise AutomationStoreInvalid(
                "automation_spot_eligibility_cycle_invalid"
            )
        resource_type = "spot_create_invocation_start"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._spot_execution_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            if (
                self._current_control(cursor, for_update=True)
                is not OperatorAutomationControlPosture.ACTIVE
            ):
                raise AutomationStoreConflict(
                    "automation_control_plane_not_active"
                )
            goal_key, goal = self._lock_spot_goal_for_run_cursor(
                cursor,
                run_id=run_id,
            )
            if bool(goal["create_allowance_consumed"]):
                raise AutomationStoreConflict(
                    "automation_spot_create_allowance_consumed"
                )
            run, plan = self._require_spot_run_plan(
                cursor,
                run_id=run_id,
                allowed_states=frozenset(
                    {OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION}
                ),
            )
            if goal_key in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS and (
                goal.get("preview_outcome") != "ACCEPTED"
                or str(goal.get("bound_run_id")) != run_id
                or goal.get("plan_sha256") != plan["plan_sha256"]
                or goal.get("portfolio_id_sha256")
                != plan["portfolio_id_sha256"]
                or goal.get("product_id") != plan["product_id"]
                or run.get("diagnostic_code")
                != "automation_spot_preview_accepted_create_ready"
            ):
                raise AutomationStoreConflict(
                    "automation_spot_preview_acceptance_not_proven"
                )
            self._require_spot_eligible_cycle(
                cursor,
                run=run,
                plan=plan,
                cycle_number=eligibility_cycle,
            )
            cursor.execute(
                f"SELECT 1 FROM {self._prefix}automation_spot_run_execution WHERE run_id = %s",
                (run_id,),
            )
            if cursor.fetchone() is not None:
                raise AutomationStoreConflict(
                    "automation_spot_run_execution_already_started"
                )
            client_order_id = self.deterministic_spot_client_order_id(
                run_id=run_id,
                plan_sha256=plan["plan_sha256"],
                goal_key=goal_key,
            )
            now = _utc_now()
            audit_id = _new_id()
            diagnostic = "automation_spot_create_invocation_started"
            execution_policy_revision = _spot_policy_revision_for_goal(
                goal_key
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_run_execution (
                    run_id, policy_revision, definition_id, definition_revision,
                    eligibility_cycle, plan_sha256, portfolio_id_sha256,
                    product_id, client_order_id, create_allowance_consumed,
                    create_outcome, create_call_count, create_call_count_exact,
                    cancel_allowance_consumed, cancel_outcome,
                    cancel_call_count, cancel_call_count_exact, child_terminal,
                    audit_id, correlation_id, created_at, updated_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NULL,NULL,FALSE,
                    FALSE,NULL,NULL,FALSE,NULL,%s,%s,%s,%s
                ) RETURNING *
                """,
                (
                    run_id,
                    execution_policy_revision,
                    str(run["definition_id"]),
                    int(run["definition_revision"]),
                    eligibility_cycle,
                    plan["plan_sha256"],
                    plan["portfolio_id_sha256"],
                    plan["product_id"],
                    client_order_id,
                    audit_id,
                    command.correlation_id,
                    now,
                    now,
                ),
            )
            execution_row = self._row(cursor)
            assert execution_row is not None
            if goal_key == AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_live_proof_goal
                    SET create_allowance_consumed = TRUE, bound_run_id = %s,
                        client_order_id = %s, updated_at = %s
                    WHERE singleton = 1
                    """,
                    (run_id, client_order_id, now),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_preview_gated_goal
                    SET create_allowance_consumed = TRUE, updated_at = %s
                    WHERE goal_key = %s AND preview_outcome = 'ACCEPTED'
                      AND create_allowance_consumed = FALSE
                    """,
                    (now, goal_key),
                )
                if cursor.rowcount != 1:
                    raise AutomationStoreConflict(
                        "automation_spot_create_allowance_consumed"
                    )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_run
                SET state = %s, diagnostic_code = %s, audit_id = %s,
                    correlation_id = %s, client_order_id = %s,
                    live_attempt_consumed = TRUE,
                    updated_at = %s
                WHERE run_id = %s
                """,
                (
                    OperatorAutomationRunState.INVOCATION_STARTED.value,
                    diagnostic,
                    audit_id,
                    command.correlation_id,
                    client_order_id,
                    now,
                    run_id,
                ),
            )
            record = self._spot_execution_from_row(execution_row)
            self._append_event(
                cursor,
                definition_id=record.definition_id,
                run_id=run_id,
                from_state=run["state"],
                to_state=OperatorAutomationRunState.INVOCATION_STARTED.value,
                diagnostic_code=diagnostic,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._spot_execution_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(
                record,
                audit_id,
                command.correlation_id,
            )

    def finalize_spot_create_invocation(
        self,
        run_id: str,
        *,
        outcome: str,
        child_terminal: bool | None,
        coinbase_api_call_count: int | None,
        call_count_exact: bool,
        command: AutomationMutationCommand,
        read_call_count: int | None = 0,
        read_call_count_exact: bool = True,
    ) -> AutomationStoreMutation[AutomationSpotRunExecutionRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        normalized = self._validate_spot_mutation_result(
            operation="CREATE",
            outcome=outcome,
            child_terminal=child_terminal,
            coinbase_api_call_count=coinbase_api_call_count,
            call_count_exact=call_count_exact,
        )
        self._validate_spot_read_accounting(
            read_call_count=read_call_count,
            read_call_count_exact=read_call_count_exact,
            max_read_call_count=100,
        )
        resource_type = "spot_create_invocation_finalize"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._spot_execution_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            goal_key, goal = self._lock_spot_goal_for_run_cursor(
                cursor,
                run_id=run_id,
            )
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_run WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            run = self._row(cursor)
            if run is None:
                raise AutomationStoreNotFound("automation_run_not_found")
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_spot_run_execution WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            execution = self._row(cursor)
            if execution is None:
                raise AutomationStoreNotFound(
                    "automation_spot_run_execution_not_found"
                )
            if (
                str(goal.get("bound_run_id")) != run_id
                or not bool(goal["create_allowance_consumed"])
                or OperatorAutomationRunState(run["state"])
                is not OperatorAutomationRunState.INVOCATION_STARTED
            ):
                raise AutomationStoreConflict(
                    "automation_spot_create_invocation_not_started"
                )
            if execution["create_outcome"] is not None:
                raise AutomationStoreConflict(
                    "automation_spot_create_already_finalized"
                )
            if normalized == "UNKNOWN":
                target = OperatorAutomationRunState.UNKNOWN_CONSUMED
                diagnostic = "automation_spot_create_unknown_consumed"
            elif normalized == "REJECTED":
                target = OperatorAutomationRunState.TERMINAL
                diagnostic = "automation_spot_create_rejected"
            elif child_terminal:
                target = OperatorAutomationRunState.TERMINAL
                diagnostic = "automation_spot_create_accepted_terminal"
            else:
                target = OperatorAutomationRunState.ACTIVE
                diagnostic = "automation_spot_safe_closeout_ready"
            event_diagnostic = (
                "automation_spot_create_accepted_active"
                if target is OperatorAutomationRunState.ACTIVE
                else diagnostic
            )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_run_execution
                SET create_outcome = %s, create_call_count = %s,
                    create_call_count_exact = %s,
                    create_read_call_count = %s,
                    create_read_call_count_exact = %s, child_terminal = %s,
                    audit_id = %s, correlation_id = %s, updated_at = %s
                WHERE run_id = %s RETURNING *
                """,
                (
                    normalized,
                    coinbase_api_call_count,
                    call_count_exact,
                    read_call_count,
                    read_call_count_exact,
                    child_terminal,
                    audit_id,
                    command.correlation_id,
                    now,
                    run_id,
                ),
            )
            execution_row = self._row(cursor)
            assert execution_row is not None
            if goal_key == AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_live_proof_goal
                    SET create_outcome = %s, updated_at = %s
                    WHERE singleton = 1
                    """,
                    (normalized, now),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_preview_gated_goal
                    SET create_outcome = %s, updated_at = %s
                    WHERE goal_key = %s
                    """,
                    (
                        normalized,
                        now,
                        goal_key,
                    ),
                )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_run
                SET state = %s, diagnostic_code = %s, audit_id = %s,
                    correlation_id = %s,
                    coinbase_api_call_count = coinbase_api_call_count + %s,
                    create_call_count = create_call_count + %s,
                    updated_at = %s
                WHERE run_id = %s
                """,
                (
                    target.value,
                    diagnostic,
                    audit_id,
                    command.correlation_id,
                    (
                        (
                            coinbase_api_call_count
                            if call_count_exact
                            and coinbase_api_call_count is not None
                            else 0
                        )
                        + (
                            read_call_count
                            if read_call_count_exact
                            and read_call_count is not None
                            else 0
                        )
                    ),
                    (
                        coinbase_api_call_count
                        if call_count_exact
                        and coinbase_api_call_count is not None
                        else 0
                    ),
                    now,
                    run_id,
                ),
            )
            record = self._spot_execution_from_row(execution_row)
            self._append_event(
                cursor,
                definition_id=record.definition_id,
                run_id=run_id,
                from_state=run["state"],
                to_state=target.value,
                diagnostic_code=event_diagnostic,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._spot_execution_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(
                record,
                audit_id,
                command.correlation_id,
            )

    def start_spot_cancel_invocation(
        self,
        run_id: str,
        *,
        client_order_id: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotRunExecutionRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        _validate_id(
            client_order_id,
            code="automation_spot_client_order_id_invalid",
        )
        resource_type = "spot_cancel_invocation_start"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._spot_execution_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            control_posture = self._current_control(cursor, for_update=True)
            if control_posture is OperatorAutomationControlPosture.SHUTDOWN:
                raise AutomationStoreConflict(
                    "automation_control_plane_shutdown"
                )
            if control_posture not in {
                OperatorAutomationControlPosture.ACTIVE,
                OperatorAutomationControlPosture.PAUSED,
                OperatorAutomationControlPosture.DRAINING,
            }:
                raise AutomationStoreConflict(
                    "automation_control_plane_not_active"
                )
            goal_key, goal = self._lock_spot_goal_for_run_cursor(
                cursor,
                run_id=run_id,
            )
            if bool(goal["cancel_allowance_consumed"]):
                raise AutomationStoreConflict(
                    "automation_spot_cancel_allowance_consumed"
                )
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_run WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            run = self._row(cursor)
            if run is None:
                raise AutomationStoreNotFound("automation_run_not_found")
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_spot_run_execution WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            execution = self._row(cursor)
            if execution is None:
                raise AutomationStoreNotFound(
                    "automation_spot_run_execution_not_found"
                )
            if (
                int(execution.get("policy_revision") or 0)
                != _spot_policy_revision_for_goal(goal_key)
                or
                str(goal.get("bound_run_id")) != run_id
                or goal.get("create_outcome") != "ACCEPTED"
                or execution.get("create_outcome") != "ACCEPTED"
                or OperatorAutomationRunState(run["state"])
                is not OperatorAutomationRunState.ACTIVE
                or execution.get("child_terminal") is not False
            ):
                raise AutomationStoreConflict(
                    "automation_spot_cancel_not_eligible"
                )
            if (
                str(execution["client_order_id"]) != client_order_id
                or str(goal["client_order_id"]) != client_order_id
            ):
                raise AutomationStoreConflict(
                    "automation_spot_cancel_child_mismatch"
                )
            if (
                not bool(execution["create_read_call_count_exact"])
                or execution.get("create_read_call_count") is None
                or int(execution["create_read_call_count"]) < 1
            ):
                raise AutomationStoreConflict(
                    "automation_spot_cancel_create_readback_required"
                )
            if bool(execution["cancel_allowance_consumed"]):
                raise AutomationStoreConflict(
                    "automation_spot_cancel_allowance_consumed"
                )
            now = _utc_now()
            audit_id = _new_id()
            diagnostic = "automation_spot_safe_closeout_invocation_started"
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_run_execution
                SET cancel_allowance_consumed = TRUE, audit_id = %s,
                    correlation_id = %s, updated_at = %s
                WHERE run_id = %s RETURNING *
                """,
                (audit_id, command.correlation_id, now, run_id),
            )
            execution_row = self._row(cursor)
            assert execution_row is not None
            if goal_key == AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_live_proof_goal
                    SET cancel_allowance_consumed = TRUE, updated_at = %s
                    WHERE singleton = 1
                    """,
                    (now,),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_preview_gated_goal
                    SET cancel_allowance_consumed = TRUE, updated_at = %s
                    WHERE goal_key = %s
                      AND cancel_allowance_consumed = FALSE
                    """,
                    (now, goal_key),
                )
                if cursor.rowcount != 1:
                    raise AutomationStoreConflict(
                        "automation_spot_cancel_allowance_consumed"
                    )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_run
                SET diagnostic_code = %s, audit_id = %s, correlation_id = %s,
                    updated_at = %s
                WHERE run_id = %s
                """,
                (
                    diagnostic,
                    audit_id,
                    command.correlation_id,
                    now,
                    run_id,
                ),
            )
            record = self._spot_execution_from_row(execution_row)
            self._append_event(
                cursor,
                definition_id=record.definition_id,
                run_id=run_id,
                from_state=run["state"],
                to_state=run["state"],
                diagnostic_code=diagnostic,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._spot_execution_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(
                record,
                audit_id,
                command.correlation_id,
            )

    def finalize_spot_cancel_invocation(
        self,
        run_id: str,
        *,
        outcome: str,
        child_terminal: bool | None,
        coinbase_api_call_count: int | None,
        call_count_exact: bool,
        command: AutomationMutationCommand,
        read_call_count: int | None = 0,
        read_call_count_exact: bool = True,
    ) -> AutomationStoreMutation[AutomationSpotRunExecutionRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        normalized = self._validate_spot_mutation_result(
            operation="SAFE_CLOSEOUT",
            outcome=outcome,
            child_terminal=child_terminal,
            coinbase_api_call_count=coinbase_api_call_count,
            call_count_exact=call_count_exact,
        )
        self._validate_spot_read_accounting(
            read_call_count=read_call_count,
            read_call_count_exact=read_call_count_exact,
            max_read_call_count=200,
        )
        resource_type = "spot_cancel_invocation_finalize"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._spot_execution_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            goal_key, goal = self._lock_spot_goal_for_run_cursor(
                cursor,
                run_id=run_id,
            )
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_run WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            run = self._row(cursor)
            if run is None:
                raise AutomationStoreNotFound("automation_run_not_found")
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_spot_run_execution WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            execution = self._row(cursor)
            if execution is None:
                raise AutomationStoreNotFound(
                    "automation_spot_run_execution_not_found"
                )
            if (
                str(goal.get("bound_run_id")) != run_id
                or not bool(goal["cancel_allowance_consumed"])
                or not bool(execution["cancel_allowance_consumed"])
                or execution["cancel_outcome"] is not None
                or OperatorAutomationRunState(run["state"])
                is not OperatorAutomationRunState.ACTIVE
            ):
                raise AutomationStoreConflict(
                    "automation_spot_cancel_invocation_not_started"
                )
            if normalized == "UNKNOWN":
                target = OperatorAutomationRunState.UNKNOWN_CONSUMED
                diagnostic = "automation_spot_safe_closeout_unknown_consumed"
            elif normalized == "REJECTED":
                target = OperatorAutomationRunState.TERMINAL
                diagnostic = "automation_spot_safe_closeout_rejected"
            elif child_terminal:
                target = OperatorAutomationRunState.TERMINAL
                diagnostic = "automation_spot_safe_closeout_accepted_terminal"
            else:
                target = OperatorAutomationRunState.TERMINAL
                diagnostic = "automation_spot_safe_closeout_accepted_nonterminal"
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_run_execution
                SET cancel_outcome = %s, cancel_call_count = %s,
                    cancel_call_count_exact = %s,
                    cancel_read_call_count = %s,
                    cancel_read_call_count_exact = %s, child_terminal = %s,
                    audit_id = %s, correlation_id = %s, updated_at = %s
                WHERE run_id = %s RETURNING *
                """,
                (
                    normalized,
                    coinbase_api_call_count,
                    call_count_exact,
                    read_call_count,
                    read_call_count_exact,
                    child_terminal,
                    audit_id,
                    command.correlation_id,
                    now,
                    run_id,
                ),
            )
            execution_row = self._row(cursor)
            assert execution_row is not None
            if goal_key == AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_live_proof_goal
                    SET cancel_outcome = %s, updated_at = %s
                    WHERE singleton = 1
                    """,
                    (normalized, now),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_preview_gated_goal
                    SET cancel_outcome = %s, updated_at = %s
                    WHERE goal_key = %s
                    """,
                    (
                        normalized,
                        now,
                        goal_key,
                    ),
                )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_run
                SET state = %s, diagnostic_code = %s, audit_id = %s,
                    correlation_id = %s,
                    coinbase_api_call_count = coinbase_api_call_count + %s,
                    cancel_call_count = cancel_call_count + %s,
                    updated_at = %s
                WHERE run_id = %s
                """,
                (
                    target.value,
                    diagnostic,
                    audit_id,
                    command.correlation_id,
                    (
                        (
                            coinbase_api_call_count
                            if call_count_exact
                            and coinbase_api_call_count is not None
                            else 0
                        )
                        + (
                            read_call_count
                            if read_call_count_exact
                            and read_call_count is not None
                            else 0
                        )
                    ),
                    (
                        coinbase_api_call_count
                        if call_count_exact
                        and coinbase_api_call_count is not None
                        else 0
                    ),
                    now,
                    run_id,
                ),
            )
            record = self._spot_execution_from_row(execution_row)
            self._append_event(
                cursor,
                definition_id=record.definition_id,
                run_id=run_id,
                from_state=run["state"],
                to_state=target.value,
                diagnostic_code=diagnostic,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._spot_execution_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(
                record,
                audit_id,
                command.correlation_id,
            )

    def get_spot_run_execution(
        self,
        run_id: str,
    ) -> AutomationSpotRunExecutionRecord | None:
        _validate_id(run_id, code="automation_run_id_invalid")
        rows = self.database.execute_query(
            f"SELECT * FROM {self._prefix}automation_spot_run_execution WHERE run_id = %s",
            (run_id,),
        )
        return self._spot_execution_from_row(rows[0]) if rows else None

    def get_spot_live_proof_goal(self) -> AutomationSpotLiveProofGoalRecord:
        rows = self.database.execute_query(
            f"SELECT * FROM {self._prefix}automation_spot_live_proof_goal WHERE singleton = 1"
        )
        if len(rows) != 1:
            raise AutomationStoreUnavailable(
                "automation_spot_live_proof_goal_unavailable"
            )
        return self._spot_goal_from_row(rows[0])

    def get_spot_preview_gated_goal(
        self,
        *,
        goal_key: str = AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ) -> AutomationSpotPreviewGatedGoalRecord:
        if goal_key not in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS:
            raise AutomationStoreInvalid("automation_spot_goal_key_invalid")
        rows = self.database.execute_query(
            f"SELECT * FROM {self._prefix}automation_spot_preview_gated_goal "
            "WHERE goal_key = %s",
            (goal_key,),
        )
        if len(rows) != 1:
            raise AutomationStoreUnavailable(
                "automation_spot_preview_gated_goal_unavailable"
            )
        return self._spot_preview_goal_from_row(rows[0])

    @staticmethod
    def _near_market_preparation_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotNearMarketPreparationRecord:
        categories = row.get("completed_categories") or []
        if isinstance(categories, str):
            categories = json.loads(categories)
        return AutomationSpotNearMarketPreparationRecord(
            cycle_number=int(row["cycle_number"]),
            goal_key=str(row["goal_key"]),
            candidate_version=int(row["candidate_version"]),
            state=str(row["state"]),
            definition_id=(
                str(row["definition_id"])
                if row.get("definition_id") is not None
                else None
            ),
            diagnostic_code=str(row["diagnostic_code"]),
            completed_categories=tuple(str(item) for item in categories),
            coinbase_api_call_count=(
                int(row["coinbase_api_call_count"])
                if row.get("coinbase_api_call_count") is not None
                else None
            ),
            call_count_exact=bool(row["call_count_exact"]),
            evidence_sha256=row.get("evidence_sha256"),
            audit_id=str(row["audit_id"]),
            correlation_id=str(row["correlation_id"]),
            started_at=_iso(row["started_at"]) or "",
            finalized_at=_iso(row.get("finalized_at")),
        )

    def list_spot_near_market_preparations(
        self,
    ) -> tuple[AutomationSpotNearMarketPreparationRecord, ...]:
        rows = self.database.execute_query(
            f"SELECT * FROM {self._prefix}automation_spot_near_market_preparation "
            "ORDER BY cycle_number"
        )
        return tuple(
            self._near_market_preparation_from_row(row) for row in rows
        )

    def start_spot_near_market_preparation(
        self,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotNearMarketPreparationRecord]:
        """Claim one goal-global, no-retry derivation cycle before any read."""

        self._validate_command(command)
        idempotency_hash = _hash(command.idempotency_key)
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_near_market_preparation
                WHERE idempotency_key_sha256 = %s
                FOR UPDATE
                """,
                (idempotency_hash,),
            )
            replay = self._row(cursor)
            if replay is not None:
                if (
                    replay["payload_sha256"] != command.payload_sha256
                    or replay["actor_id_sha256"] != _hash(command.actor_id)
                    or replay["operator_intent_sha256"]
                    != _hash(command.operator_intent)
                    or replay["correlation_id"] != command.correlation_id
                ):
                    raise AutomationStoreConflict(
                        "automation_near_market_preparation_idempotency_conflict"
                    )
                record = self._near_market_preparation_from_row(replay)
                return AutomationStoreMutation(
                    record,
                    record.audit_id,
                    record.correlation_id,
                    True,
                )

            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_preview_gated_goal
                WHERE goal_key = ANY(%s)
                ORDER BY goal_key
                FOR UPDATE
                """,
                (list(sorted(AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS)),),
            )
            goal_rows = {
                str(row["goal_key"]): row for row in self._rows(cursor)
            }
            if set(goal_rows) != set(AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS):
                raise AutomationStoreUnavailable(
                    "automation_near_market_goal_ledger_unavailable"
                )
            ordered = (
                (4, AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY),
                (5, AUTOMATION_SPOT_NEAR_MARKET_V5_GOAL_KEY),
                (6, AUTOMATION_SPOT_NEAR_MARKET_V6_GOAL_KEY),
            )
            target: tuple[int, str] | None = None
            for version, goal_key in ordered:
                row = goal_rows[goal_key]
                if row.get("definition_id") is None:
                    target = (version, goal_key)
                    break
                if row.get("preview_outcome") not in {"REJECTED", "UNKNOWN"}:
                    raise AutomationStoreConflict(
                        "automation_near_market_successor_not_available"
                    )
            if target is None:
                raise AutomationStoreConflict(
                    "automation_near_market_candidates_exhausted"
                )
            candidate_version, goal_key = target
            self._lock_spot_single_child_definition_slot(
                cursor,
                definition_id=None,
                goal_key=goal_key,
            )

            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_near_market_preparation
                WHERE goal_key = %s
                ORDER BY cycle_number DESC
                LIMIT 1
                FOR UPDATE
                """,
                (goal_key,),
            )
            latest = self._row(cursor)
            if latest is not None:
                if latest["state"] == "CLAIMED":
                    raise AutomationStoreConflict(
                        "automation_near_market_preparation_in_progress"
                    )
                if latest["state"] == "MATERIALIZED":
                    raise AutomationStoreConflict(
                        "automation_near_market_successor_not_available"
                    )
                if (
                    latest["state"] == "BLOCKED"
                    and latest["diagnostic_code"]
                    == "near_market_no_valid_size"
                ):
                    raise AutomationStoreConflict(
                        "automation_near_market_no_valid_size_terminal"
                    )

            cursor.execute(
                f"""
                SELECT MAX(cycle_number) AS cycle_number
                FROM (
                    SELECT cycle_number
                    FROM {self._prefix}automation_spot_near_market_preparation
                    UNION ALL
                    SELECT cycle_number
                    FROM {self._prefix}automation_spot_eligibility_cycle
                    WHERE goal_key = ANY(%s)
                ) AS consumed
                """,
                (list(sorted(AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS)),),
            )
            consumed = self._row(cursor)
            cycle_number = int(
                (consumed or {}).get("cycle_number") or 0
            ) + 1
            if cycle_number > 10:
                raise AutomationStoreConflict(
                    "automation_near_market_cycles_exhausted"
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_near_market_preparation (
                    cycle_number, goal_key, candidate_version, state,
                    definition_id, idempotency_key_sha256, payload_sha256,
                    actor_id_sha256, operator_intent_sha256, diagnostic_code,
                    completed_categories, coinbase_api_call_count,
                    call_count_exact, evidence_sha256, audit_id,
                    correlation_id, started_at, finalized_at
                ) VALUES (
                    %s,%s,%s,'CLAIMED',NULL,%s,%s,%s,%s,
                    'automation_near_market_preparation_claimed','[]'::jsonb,
                    NULL,FALSE,NULL,%s,%s,%s,NULL
                )
                RETURNING *
                """,
                (
                    cycle_number,
                    goal_key,
                    candidate_version,
                    idempotency_hash,
                    command.payload_sha256,
                    _hash(command.actor_id),
                    _hash(command.operator_intent),
                    audit_id,
                    command.correlation_id,
                    now,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            return AutomationStoreMutation(
                self._near_market_preparation_from_row(row),
                audit_id,
                command.correlation_id,
            )

    def finalize_spot_near_market_preparation(
        self,
        *,
        cycle_number: int,
        goal_key: str,
        state: Literal["BLOCKED", "UNKNOWN"],
        diagnostic_code: str,
        completed_categories: tuple[str, ...],
        coinbase_api_call_count: int | None,
        call_count_exact: bool,
        evidence_sha256: str | None,
        definition_id: str | None,
    ) -> AutomationStoreMutation[AutomationSpotNearMarketPreparationRecord]:
        """Finalize sanitized preparation evidence; raw values are forbidden."""

        if (
            type(cycle_number) is not int
            or not 1 <= cycle_number <= 10
            or goal_key not in AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS
            or state not in {"BLOCKED", "UNKNOWN"}
            or diagnostic_code
            not in _AUTOMATION_SPOT_NEAR_MARKET_PREPARATION_DIAGNOSTICS
            or tuple(completed_categories)
            != _AUTOMATION_SPOT_NEAR_MARKET_PREPARATION_CATEGORIES[
                : len(completed_categories)
            ]
            or len(completed_categories)
            > len(_AUTOMATION_SPOT_NEAR_MARKET_PREPARATION_CATEGORIES)
            or definition_id is not None
            or (
                state == "UNKNOWN"
                and (
                    coinbase_api_call_count is not None
                    or call_count_exact
                    or evidence_sha256 is not None
                )
            )
            or (
                state != "UNKNOWN"
                and (
                    type(coinbase_api_call_count) is not int
                    or coinbase_api_call_count < 0
                    or not call_count_exact
                    or evidence_sha256 is None
                )
            )
            or (
                evidence_sha256 is not None
                and _SHA256_PATTERN.fullmatch(evidence_sha256) is None
            )
        ):
            raise AutomationStoreInvalid(
                "automation_near_market_preparation_result_invalid"
            )
        if definition_id is not None:
            _validate_id(
                definition_id,
                code="automation_definition_id_invalid",
            )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_near_market_preparation
                WHERE cycle_number = %s AND goal_key = %s
                FOR UPDATE
                """,
                (cycle_number, goal_key),
            )
            current = self._row(cursor)
            if current is None:
                raise AutomationStoreNotFound(
                    "automation_near_market_preparation_not_found"
                )
            if current["state"] != "CLAIMED":
                record = self._near_market_preparation_from_row(current)
                return AutomationStoreMutation(
                    record,
                    record.audit_id,
                    record.correlation_id,
                    True,
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_near_market_preparation
                SET state = %s, definition_id = %s, diagnostic_code = %s,
                    completed_categories = %s::jsonb,
                    coinbase_api_call_count = %s, call_count_exact = %s,
                    evidence_sha256 = %s, audit_id = %s,
                    finalized_at = %s
                WHERE cycle_number = %s AND goal_key = %s AND state = 'CLAIMED'
                RETURNING *
                """,
                (
                    state,
                    definition_id,
                    diagnostic_code,
                    json.dumps(list(completed_categories)),
                    coinbase_api_call_count,
                    call_count_exact,
                    evidence_sha256,
                    audit_id,
                    now,
                    cycle_number,
                    goal_key,
                ),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreConflict(
                    "automation_near_market_preparation_already_finalized"
                )
            record = self._near_market_preparation_from_row(row)
            return AutomationStoreMutation(
                record,
                audit_id,
                record.correlation_id,
            )

    @staticmethod
    def _minimum_size_preparation_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotMinimumSizePreparationRecord:
        categories = row.get("completed_categories") or []
        if isinstance(categories, str):
            categories = json.loads(categories)
        return AutomationSpotMinimumSizePreparationRecord(
            cycle_number=int(row["cycle_number"]),
            goal_key=str(row["goal_key"]),
            candidate_version=int(row["candidate_version"]),
            state=str(row["state"]),
            definition_id=(
                str(row["definition_id"])
                if row.get("definition_id") is not None
                else None
            ),
            diagnostic_code=str(row["diagnostic_code"]),
            completed_categories=tuple(str(item) for item in categories),
            coinbase_api_call_count=(
                int(row["coinbase_api_call_count"])
                if row.get("coinbase_api_call_count") is not None
                else None
            ),
            call_count_exact=bool(row["call_count_exact"]),
            evidence_sha256=row.get("evidence_sha256"),
            audit_id=str(row["audit_id"]),
            correlation_id=str(row["correlation_id"]),
            started_at=_iso(row["started_at"]) or "",
            finalized_at=_iso(row.get("finalized_at")),
        )

    def list_spot_minimum_size_preparations(
        self,
    ) -> tuple[AutomationSpotMinimumSizePreparationRecord, ...]:
        rows = self.database.execute_query(
            f"SELECT * FROM {self._prefix}automation_spot_minimum_size_preparation "
            "ORDER BY cycle_number"
        )
        return tuple(
            self._minimum_size_preparation_from_row(row) for row in rows
        )

    def start_spot_minimum_size_preparation(
        self,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotMinimumSizePreparationRecord]:
        """Claim one V7-V9 goal-global cycle before any Coinbase read."""

        self._validate_command(command)
        idempotency_hash = _hash(command.idempotency_key)
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_minimum_size_preparation
                WHERE idempotency_key_sha256 = %s
                FOR UPDATE
                """,
                (idempotency_hash,),
            )
            replay = self._row(cursor)
            if replay is not None:
                if (
                    replay["payload_sha256"] != command.payload_sha256
                    or replay["actor_id_sha256"] != _hash(command.actor_id)
                    or replay["operator_intent_sha256"]
                    != _hash(command.operator_intent)
                    or replay["correlation_id"] != command.correlation_id
                ):
                    raise AutomationStoreConflict(
                        "automation_minimum_size_preparation_idempotency_conflict"
                    )
                record = self._minimum_size_preparation_from_row(replay)
                return AutomationStoreMutation(
                    record,
                    record.audit_id,
                    record.correlation_id,
                    True,
                )

            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_preview_gated_goal
                WHERE goal_key = ANY(%s)
                ORDER BY goal_key
                FOR UPDATE
                """,
                (list(sorted(AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS)),),
            )
            goal_rows = {
                str(row["goal_key"]): row for row in self._rows(cursor)
            }
            if set(goal_rows) != set(AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS):
                raise AutomationStoreUnavailable(
                    "automation_minimum_size_goal_ledger_unavailable"
                )
            ordered = (
                (7, AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY),
                (8, AUTOMATION_SPOT_MINIMUM_SIZE_V8_GOAL_KEY),
                (9, AUTOMATION_SPOT_MINIMUM_SIZE_V9_GOAL_KEY),
            )
            target: tuple[int, str] | None = None
            for version, goal_key in ordered:
                row = goal_rows[goal_key]
                if row.get("definition_id") is None:
                    target = (version, goal_key)
                    break
                if row.get("preview_outcome") not in {"REJECTED", "UNKNOWN"}:
                    raise AutomationStoreConflict(
                        "automation_minimum_size_successor_not_available"
                    )
            if target is None:
                raise AutomationStoreConflict(
                    "automation_minimum_size_candidates_exhausted"
                )
            candidate_version, goal_key = target
            self._lock_spot_single_child_definition_slot(
                cursor,
                definition_id=None,
                goal_key=goal_key,
            )

            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_minimum_size_preparation
                WHERE goal_key = %s
                ORDER BY cycle_number DESC
                LIMIT 1
                FOR UPDATE
                """,
                (goal_key,),
            )
            latest = self._row(cursor)
            if latest is not None:
                if latest["state"] == "CLAIMED":
                    raise AutomationStoreConflict(
                        "automation_minimum_size_preparation_in_progress"
                    )
                if latest["state"] == "MATERIALIZED":
                    raise AutomationStoreConflict(
                        "automation_minimum_size_successor_not_available"
                    )
                if latest["state"] == "BLOCKED" and latest[
                    "diagnostic_code"
                ] in {
                    "minimum_size_wallet_insufficient",
                    "minimum_size_submitted_cap_conflict",
                    "minimum_size_fee_reserve_cap_conflict",
                }:
                    raise AutomationStoreConflict(
                        "automation_minimum_size_terminal"
                    )

            cursor.execute(
                f"""
                SELECT MAX(cycle_number) AS cycle_number
                FROM (
                    SELECT cycle_number
                    FROM {self._prefix}automation_spot_minimum_size_preparation
                    UNION ALL
                    SELECT cycle_number
                    FROM {self._prefix}automation_spot_eligibility_cycle
                    WHERE goal_key = ANY(%s)
                ) AS consumed
                """,
                (list(sorted(AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS)),),
            )
            consumed = self._row(cursor)
            cycle_number = int(
                (consumed or {}).get("cycle_number") or 0
            ) + 1
            if cycle_number > 10:
                raise AutomationStoreConflict(
                    "automation_minimum_size_cycles_exhausted"
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_minimum_size_preparation (
                    cycle_number, goal_key, candidate_version, state,
                    definition_id, idempotency_key_sha256, payload_sha256,
                    actor_id_sha256, operator_intent_sha256, diagnostic_code,
                    completed_categories, coinbase_api_call_count,
                    call_count_exact, evidence_sha256, audit_id,
                    correlation_id, started_at, finalized_at
                ) VALUES (
                    %s,%s,%s,'CLAIMED',NULL,%s,%s,%s,%s,
                    'automation_minimum_size_preparation_claimed','[]'::jsonb,
                    NULL,FALSE,NULL,%s,%s,%s,NULL
                )
                RETURNING *
                """,
                (
                    cycle_number,
                    goal_key,
                    candidate_version,
                    idempotency_hash,
                    command.payload_sha256,
                    _hash(command.actor_id),
                    _hash(command.operator_intent),
                    audit_id,
                    command.correlation_id,
                    now,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            return AutomationStoreMutation(
                self._minimum_size_preparation_from_row(row),
                audit_id,
                command.correlation_id,
            )

    def finalize_spot_minimum_size_preparation(
        self,
        *,
        cycle_number: int,
        goal_key: str,
        state: Literal["BLOCKED", "UNKNOWN"],
        diagnostic_code: str,
        completed_categories: tuple[str, ...],
        coinbase_api_call_count: int | None,
        call_count_exact: bool,
        evidence_sha256: str | None,
        definition_id: str | None,
    ) -> AutomationStoreMutation[AutomationSpotMinimumSizePreparationRecord]:
        """Finalize value-blind V7-V9 preparation evidence."""

        expected_evidence_sha256 = (
            minimum_size_preparation_evidence_sha256(
                call_count=coinbase_api_call_count,
                categories=completed_categories,
                diagnostic_code=diagnostic_code,
                outcome=state,
                policy_revision=MINIMUM_SIZE_POLICY_REVISION,
                plan=None,
            )
            if state == "BLOCKED"
            and type(coinbase_api_call_count) is int
            and call_count_exact
            else None
        )
        stage_unknown_prefix_length = (
            _AUTOMATION_SPOT_MINIMUM_SIZE_STAGE_UNKNOWN_PREFIX_LENGTH.get(
                diagnostic_code
            )
        )
        if (
            type(cycle_number) is not int
            or not 1 <= cycle_number <= 10
            or goal_key not in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS
            or state not in {"BLOCKED", "UNKNOWN"}
            or diagnostic_code
            not in _AUTOMATION_SPOT_MINIMUM_SIZE_PREPARATION_DIAGNOSTICS
            or (state == "UNKNOWN")
            is not (
                diagnostic_code
                in _AUTOMATION_SPOT_MINIMUM_SIZE_UNKNOWN_DIAGNOSTICS
            )
            or (
                stage_unknown_prefix_length is not None
                and tuple(completed_categories)
                != _AUTOMATION_SPOT_MINIMUM_SIZE_PREPARATION_CATEGORIES[
                    :stage_unknown_prefix_length
                ]
            )
            or tuple(completed_categories)
            != _AUTOMATION_SPOT_MINIMUM_SIZE_PREPARATION_CATEGORIES[
                : len(completed_categories)
            ]
            or len(completed_categories)
            > len(_AUTOMATION_SPOT_MINIMUM_SIZE_PREPARATION_CATEGORIES)
            or definition_id is not None
            or (
                state == "UNKNOWN"
                and (
                    coinbase_api_call_count is not None
                    or call_count_exact
                    or evidence_sha256 is not None
                )
            )
            or (
                state != "UNKNOWN"
                and (
                    type(coinbase_api_call_count) is not int
                    or coinbase_api_call_count < 0
                    or not call_count_exact
                    or evidence_sha256 is None
                )
            )
            or (
                evidence_sha256 is not None
                and _SHA256_PATTERN.fullmatch(evidence_sha256) is None
            )
            or (
                state == "BLOCKED"
                and evidence_sha256 != expected_evidence_sha256
            )
        ):
            raise AutomationStoreInvalid(
                "automation_minimum_size_preparation_result_invalid"
            )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_minimum_size_preparation
                WHERE cycle_number = %s AND goal_key = %s
                FOR UPDATE
                """,
                (cycle_number, goal_key),
            )
            current = self._row(cursor)
            if current is None:
                raise AutomationStoreNotFound(
                    "automation_minimum_size_preparation_not_found"
                )
            if current["state"] != "CLAIMED":
                record = self._minimum_size_preparation_from_row(current)
                return AutomationStoreMutation(
                    record,
                    record.audit_id,
                    record.correlation_id,
                    True,
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_minimum_size_preparation
                SET state = %s, definition_id = %s, diagnostic_code = %s,
                    completed_categories = %s::jsonb,
                    coinbase_api_call_count = %s, call_count_exact = %s,
                    evidence_sha256 = %s, audit_id = %s,
                    finalized_at = %s
                WHERE cycle_number = %s AND goal_key = %s AND state = 'CLAIMED'
                RETURNING *
                """,
                (
                    state,
                    definition_id,
                    diagnostic_code,
                    json.dumps(list(completed_categories)),
                    coinbase_api_call_count,
                    call_count_exact,
                    evidence_sha256,
                    audit_id,
                    now,
                    cycle_number,
                    goal_key,
                ),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreConflict(
                    "automation_minimum_size_preparation_already_finalized"
                )
            record = self._minimum_size_preparation_from_row(row)
            return AutomationStoreMutation(
                record,
                audit_id,
                record.correlation_id,
            )

    @staticmethod
    def _atomic_market_snapshot_cycle_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotAtomicMarketSnapshotCycleRecord:
        categories = row.get("completed_categories") or []
        if isinstance(categories, str):
            categories = json.loads(categories)
        return AutomationSpotAtomicMarketSnapshotCycleRecord(
            cycle_number=int(row["cycle_number"]),
            goal_key=str(row["goal_key"]),
            candidate_version=int(row["candidate_version"]),
            state=str(row["state"]),
            definition_id=(
                str(row["definition_id"])
                if row.get("definition_id") is not None
                else None
            ),
            run_id=(
                str(row["run_id"])
                if row.get("run_id") is not None
                else None
            ),
            plan_sha256=row.get("plan_sha256"),
            client_order_id=(
                str(row["client_order_id"])
                if row.get("client_order_id") is not None
                else None
            ),
            diagnostic_code=str(row["diagnostic_code"]),
            completed_categories=tuple(str(item) for item in categories),
            coinbase_api_call_count=(
                int(row["coinbase_api_call_count"])
                if row.get("coinbase_api_call_count") is not None
                else None
            ),
            call_count_exact=bool(row["call_count_exact"]),
            market_snapshot_sha256=row.get("market_snapshot_sha256"),
            evidence_sha256=row.get("evidence_sha256"),
            audit_id=str(row["audit_id"]),
            correlation_id=str(row["correlation_id"]),
            started_at=_iso(row["started_at"]) or "",
            finalized_at=_iso(row.get("finalized_at")),
        )

    def list_spot_atomic_market_snapshot_cycles(
        self,
    ) -> tuple[AutomationSpotAtomicMarketSnapshotCycleRecord, ...]:
        rows = self.database.execute_query(
            f"SELECT * FROM {self._prefix}automation_spot_atomic_market_snapshot_cycle "
            "ORDER BY cycle_number"
        )
        return tuple(
            self._atomic_market_snapshot_cycle_from_row(row) for row in rows
        )

    def spot_atomic_market_snapshot_successor_available(self) -> bool:
        """Return ledger-backed actionability without reserving a cycle."""

        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_spot_preview_gated_goal "
                "WHERE goal_key = ANY(%s)",
                (list(sorted(AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_PREDECESSOR_GOAL_KEYS)),),
            )
            goals = {str(row["goal_key"]): row for row in self._rows(cursor)}
            cursor.execute(
                f"SELECT cycle_number, goal_key, state FROM "
                f"{self._prefix}automation_spot_atomic_market_snapshot_cycle "
                "ORDER BY cycle_number"
            )
            cycles = self._rows(cursor)
        return _select_atomic_market_snapshot_successor(goals, cycles) is not None

    def start_spot_atomic_market_snapshot_cycle(
        self,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotAtomicMarketSnapshotCycleRecord]:
        """Claim one goal-global V10-V12 cycle before any Coinbase read."""

        self._validate_command(command)
        idempotency_hash = _hash(command.idempotency_key)
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_atomic_market_snapshot_cycle
                WHERE idempotency_key_sha256 = %s
                FOR UPDATE
                """,
                (idempotency_hash,),
            )
            replay = self._row(cursor)
            if replay is not None:
                if (
                    replay["payload_sha256"] != command.payload_sha256
                    or replay["actor_id_sha256"] != _hash(command.actor_id)
                    or replay["operator_intent_sha256"]
                    != _hash(command.operator_intent)
                    or replay["correlation_id"] != command.correlation_id
                ):
                    raise AutomationStoreConflict(
                        "automation_atomic_market_snapshot_idempotency_conflict"
                    )
                record = self._atomic_market_snapshot_cycle_from_row(replay)
                return AutomationStoreMutation(
                    record,
                    record.audit_id,
                    record.correlation_id,
                    True,
                )
            posture = self._current_control(cursor, for_update=True)
            if posture is not OperatorAutomationControlPosture.ACTIVE:
                raise AutomationStoreConflict(
                    "automation_control_plane_not_active"
                )
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_preview_gated_goal
                WHERE goal_key = ANY(%s)
                ORDER BY goal_key
                FOR UPDATE
                """,
                (list(sorted(AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_PREDECESSOR_GOAL_KEYS)),),
            )
            goals = {str(row["goal_key"]): row for row in self._rows(cursor)}
            if set(goals) != set(AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_PREDECESSOR_GOAL_KEYS):
                raise AutomationStoreUnavailable(
                    "automation_atomic_market_snapshot_goal_ledger_unavailable"
                )
            cursor.execute(
                f"SELECT cycle_number, goal_key, state FROM "
                f"{self._prefix}automation_spot_atomic_market_snapshot_cycle "
                "ORDER BY cycle_number FOR UPDATE"
            )
            existing_cycles = self._rows(cursor)
            target = _select_atomic_market_snapshot_successor(
                goals,
                existing_cycles,
            )
            if target is None:
                raise AutomationStoreConflict(
                    "automation_atomic_market_snapshot_successor_not_available"
                )
            candidate_version, goal_key = target
            cycle_number = max(
                (int(cycle["cycle_number"]) for cycle in existing_cycles),
                default=0,
            ) + 1
            if cycle_number > 10:
                raise AutomationStoreConflict(
                    "automation_atomic_market_snapshot_cycles_exhausted"
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_atomic_market_snapshot_cycle (
                    cycle_number, goal_key, candidate_version, state,
                    definition_id, run_id, plan_sha256, client_order_id,
                    idempotency_key_sha256, payload_sha256, actor_id_sha256,
                    operator_intent_sha256, diagnostic_code,
                    completed_categories, coinbase_api_call_count,
                    call_count_exact, market_snapshot_sha256,
                    evidence_sha256, audit_id, correlation_id,
                    started_at, finalized_at
                ) VALUES (
                    %s,%s,%s,'CLAIMED',NULL,NULL,NULL,NULL,%s,%s,%s,%s,
                    'atomic_market_snapshot_cycle_claimed','[]'::jsonb,
                    NULL,FALSE,NULL,NULL,%s,%s,%s,NULL
                ) RETURNING *
                """,
                (
                    cycle_number,
                    goal_key,
                    candidate_version,
                    idempotency_hash,
                    command.payload_sha256,
                    _hash(command.actor_id),
                    _hash(command.operator_intent),
                    audit_id,
                    command.correlation_id,
                    now,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            return AutomationStoreMutation(
                self._atomic_market_snapshot_cycle_from_row(row),
                audit_id,
                command.correlation_id,
            )

    def finalize_spot_atomic_market_snapshot_terminal(
        self,
        *,
        cycle_number: int,
        goal_key: str,
        state: Literal["BLOCKED", "UNKNOWN"],
        diagnostic_code: str,
        completed_categories: tuple[str, ...],
        coinbase_api_call_count: int | None,
        call_count_exact: bool,
        evidence_sha256: str | None,
    ) -> AutomationStoreMutation[AutomationSpotAtomicMarketSnapshotCycleRecord]:
        """Close a failed cycle without creating any candidate or allowance."""

        if (
            goal_key not in AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_PREDECESSOR_GOAL_KEYS
            or state not in {"BLOCKED", "UNKNOWN"}
            or not diagnostic_code.startswith(("atomic_", "minimum_", "automation_"))
            or tuple(completed_categories)
            != AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[: len(completed_categories)]
            or len(completed_categories) > 8
            or (state == "UNKNOWN")
            is not (
                coinbase_api_call_count is None
                and not call_count_exact
                and evidence_sha256 is None
            )
            or (
                state == "BLOCKED"
                and (
                    type(coinbase_api_call_count) is not int
                    or coinbase_api_call_count < 0
                    or not call_count_exact
                    or evidence_sha256 is None
                )
            )
            or (
                evidence_sha256 is not None
                and _SHA256_PATTERN.fullmatch(evidence_sha256) is None
            )
        ):
            raise AutomationStoreInvalid(
                "automation_atomic_market_snapshot_result_invalid"
            )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM {self._prefix}automation_spot_atomic_market_snapshot_cycle
                WHERE cycle_number = %s AND goal_key = %s
                FOR UPDATE
                """,
                (cycle_number, goal_key),
            )
            current = self._row(cursor)
            if current is None:
                raise AutomationStoreNotFound(
                    "automation_atomic_market_snapshot_cycle_not_found"
                )
            if current["state"] != "CLAIMED":
                record = self._atomic_market_snapshot_cycle_from_row(current)
                return AutomationStoreMutation(
                    record,
                    record.audit_id,
                    record.correlation_id,
                    True,
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_atomic_market_snapshot_cycle
                SET state = %s, diagnostic_code = %s,
                    completed_categories = %s::jsonb,
                    coinbase_api_call_count = %s, call_count_exact = %s,
                    evidence_sha256 = %s, audit_id = %s, finalized_at = %s
                WHERE cycle_number = %s AND goal_key = %s AND state = 'CLAIMED'
                RETURNING *
                """,
                (
                    state,
                    diagnostic_code,
                    json.dumps(list(completed_categories)),
                    coinbase_api_call_count,
                    call_count_exact,
                    evidence_sha256,
                    audit_id,
                    now,
                    cycle_number,
                    goal_key,
                ),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreConflict(
                    "automation_atomic_market_snapshot_already_finalized"
                )
            record = self._atomic_market_snapshot_cycle_from_row(row)
            return AutomationStoreMutation(
                record,
                audit_id,
                record.correlation_id,
            )

    def materialize_spot_atomic_market_snapshot_and_claim_preview(
        self,
        *,
        cycle_number: int,
        goal_key: str,
        definition_id: str,
        run_id: str,
        terms: AutomationSpotSingleChildPlanTerms,
        expected_plan_sha256: str,
        expected_client_order_id: str,
        market_snapshot_sha256: str,
        evidence_sha256: str,
        attempts: tuple[Any, ...],
    ) -> AutomationStoreMutation[AutomationSpotAtomicMarketSnapshotCycleRecord]:
        """Persist all final terms/evidence/identity and consume Preview atomically."""

        _validate_id(definition_id, code="automation_definition_id_invalid")
        _validate_id(run_id, code="automation_run_id_invalid")
        if (
            goal_key not in AUTOMATION_SPOT_ATOMIC_MARKET_SNAPSHOT_PREDECESSOR_GOAL_KEYS
            or _SHA256_PATTERN.fullmatch(expected_plan_sha256) is None
            or _SHA256_PATTERN.fullmatch(market_snapshot_sha256) is None
            or _SHA256_PATTERN.fullmatch(evidence_sha256) is None
            or len(attempts) != len(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES)
            or tuple(item.category for item in attempts)
            != AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
        ):
            raise AutomationStoreInvalid(
                "automation_atomic_market_snapshot_materialization_invalid"
            )
        values = self._validated_spot_plan_values(
            self._spot_plan_command_for_revision(
                definition_id=definition_id,
                definition_revision=1,
                terms=terms,
                command=AutomationMutationCommand(
                    idempotency_key="atomic-market-snapshot-materialization",
                    payload_sha256=evidence_sha256,
                    actor_id="backend-owned-atomic-market-snapshot",
                    correlation_id="atomic-market-snapshot-binding",
                    operator_intent="materialize_atomic_market_snapshot",
                ),
            ),
            post_only_required=True,
            dynamic_execution_cap=True,
        )
        if (
            values["plan_sha256"] != expected_plan_sha256
            or Decimal(values["submitted_notional_usdc"]) >= Decimal("3.10")
            or Decimal(values["possible_execution_notional_usdc"])
            >= Decimal("3.10")
        ):
            raise AutomationStoreInvalid(
                "automation_atomic_market_snapshot_plan_binding_invalid"
            )
        expected_identity = self.deterministic_spot_client_order_id(
            run_id=run_id,
            plan_sha256=expected_plan_sha256,
            goal_key=goal_key,
        )
        if expected_identity != expected_client_order_id:
            raise AutomationStoreInvalid(
                "automation_atomic_market_snapshot_identity_invalid"
            )
        total_calls = 0
        fresh_until_values: list[datetime] = []
        for item in attempts:
            observed_at = _aware_utc_datetime(item.observed_at)
            fresh_until = _aware_utc_datetime(item.fresh_until)
            if (
                type(item.coinbase_api_call_count) is not int
                or item.coinbase_api_call_count < 1
                or observed_at is None
                or fresh_until is None
                or fresh_until <= observed_at
                or _SHA256_PATTERN.fullmatch(item.evidence_sha256) is None
            ):
                raise AutomationStoreInvalid(
                    "automation_atomic_market_snapshot_attempt_invalid"
                )
            total_calls += item.coinbase_api_call_count
            fresh_until_values.append(fresh_until)
        now = _utc_now()
        if min(fresh_until_values) <= now:
            raise AutomationStoreConflict(
                "automation_atomic_market_snapshot_stale"
            )
        with self.database.get_cursor() as cursor:
            posture = self._current_control(cursor, for_update=True)
            if posture is not OperatorAutomationControlPosture.ACTIVE:
                raise AutomationStoreConflict(
                    "automation_control_plane_not_active"
                )
            cursor.execute(
                f"""
                SELECT * FROM {self._prefix}automation_spot_atomic_market_snapshot_cycle
                WHERE cycle_number = %s AND goal_key = %s
                FOR UPDATE
                """,
                (cycle_number, goal_key),
            )
            current = self._row(cursor)
            if current is None:
                raise AutomationStoreNotFound(
                    "automation_atomic_market_snapshot_cycle_not_found"
                )
            if current["state"] != "CLAIMED":
                record = self._atomic_market_snapshot_cycle_from_row(current)
                return AutomationStoreMutation(
                    record,
                    record.audit_id,
                    record.correlation_id,
                    True,
                )
            cursor.execute(
                f"""
                SELECT * FROM {self._prefix}automation_spot_preview_gated_goal
                WHERE goal_key = %s FOR UPDATE
                """,
                (goal_key,),
            )
            goal = self._row(cursor)
            if (
                goal is None
                or goal.get("definition_id") is not None
                or bool(goal.get("preview_allowance_consumed"))
            ):
                raise AutomationStoreConflict(
                    "automation_spot_preview_allowance_consumed"
                )
            audit_id = _new_id()
            correlation_id = str(current["correlation_id"])
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_definition (
                    definition_id, revision, label, domain, job_kind,
                    lifecycle_state, product_ids, schedule_kind,
                    interval_seconds, next_review_at, created_at, updated_at
                ) VALUES (
                    %s,1,%s,'SPOT','SPOT_CAMPAIGN','ENABLED',
                    '["BTC-USDC"]'::jsonb,'MANUAL_ONLY',NULL,NULL,%s,%s
                )
                """,
                (
                    definition_id,
                    f"BTC-USDC atomic market snapshot V{int(current['candidate_version'])}",
                    now,
                    now,
                ),
            )
            self._insert_spot_single_child_plan(
                cursor,
                values=values,
                audit_id=audit_id,
                correlation_id=correlation_id,
                recorded_at=now,
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_plan_goal (
                    definition_id, goal_key, created_at
                ) VALUES (%s,%s,%s)
                """,
                (definition_id, goal_key, now),
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_run (
                    run_id, definition_id, definition_revision, domain,
                    job_kind, state, diagnostic_code, audit_id,
                    correlation_id, client_order_id, live_attempt_consumed,
                    coinbase_api_call_count, create_call_count,
                    cancel_call_count, claimed_at, updated_at
                ) VALUES (
                    %s,%s,1,'SPOT','SPOT_CAMPAIGN',
                    'AWAITING_OPERATOR_AUTHORIZATION',
                    'automation_spot_preview_invocation_started',%s,%s,%s,
                    TRUE,%s,0,0,%s,%s
                )
                """,
                (
                    run_id,
                    definition_id,
                    audit_id,
                    correlation_id,
                    expected_client_order_id,
                    total_calls,
                    now,
                    now,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_eligibility_cycle (
                    goal_key, cycle_number, policy_revision, run_id,
                    definition_id, definition_revision, plan_sha256,
                    portfolio_id_sha256, product_id, client_order_id,
                    state, coinbase_api_call_count, call_count_exact,
                    fresh_until, diagnostic_code, audit_id, correlation_id,
                    started_at, finalized_at
                ) VALUES (
                    %s,%s,5,%s,%s,1,%s,%s,'BTC-USDC',%s,'SUCCEEDED',
                    %s,TRUE,%s,'automation_spot_eligibility_succeeded',
                    %s,%s,%s,%s
                )
                """,
                (
                    goal_key,
                    cycle_number,
                    run_id,
                    definition_id,
                    expected_plan_sha256,
                    values["portfolio_id_sha256"],
                    expected_client_order_id,
                    total_calls,
                    min(fresh_until_values),
                    audit_id,
                    correlation_id,
                    now,
                    now,
                ),
            )
            for item in attempts:
                portfolio_evidence = (
                    values["portfolio_id_sha256"]
                    if item.category == "PORTFOLIO_CATALOG"
                    else None
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._prefix}automation_spot_eligibility_attempt (
                        run_id, goal_key, cycle_number, category,
                        allowance_consumed, outcome, eligible,
                        coinbase_api_call_count, call_count_exact,
                        diagnostic_code, audit_id, correlation_id,
                        started_at, finalized_at, observed_at, fresh_until,
                        evidence_sha256, portfolio_id_sha256
                    ) VALUES (
                        %s,%s,%s,%s,TRUE,'SUCCEEDED',TRUE,%s,TRUE,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s
                    )
                    """,
                    (
                        run_id,
                        goal_key,
                        cycle_number,
                        item.category,
                        item.coinbase_api_call_count,
                        f"automation_spot_eligibility_{item.category.lower()}_succeeded",
                        audit_id,
                        correlation_id,
                        now,
                        now,
                        item.observed_at,
                        item.fresh_until,
                        item.evidence_sha256,
                        portfolio_evidence,
                    ),
                )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_preview_gated_goal
                SET definition_id = %s, bound_run_id = %s,
                    client_order_id = %s, eligibility_cycle = %s,
                    plan_sha256 = %s, portfolio_id_sha256 = %s,
                    product_id = 'BTC-USDC', preview_allowance_consumed = TRUE,
                    updated_at = %s
                WHERE goal_key = %s AND definition_id IS NULL
                  AND preview_allowance_consumed = FALSE
                """,
                (
                    definition_id,
                    run_id,
                    expected_client_order_id,
                    cycle_number,
                    expected_plan_sha256,
                    values["portfolio_id_sha256"],
                    now,
                    goal_key,
                ),
            )
            if cursor.rowcount != 1:
                raise AutomationStoreConflict(
                    "automation_spot_preview_allowance_consumed"
                )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_atomic_market_snapshot_cycle
                SET state = 'MATERIALIZED', definition_id = %s, run_id = %s,
                    plan_sha256 = %s, client_order_id = %s,
                    diagnostic_code = 'atomic_market_snapshot_terms_bound',
                    completed_categories = %s::jsonb,
                    coinbase_api_call_count = %s, call_count_exact = TRUE,
                    market_snapshot_sha256 = %s, evidence_sha256 = %s,
                    audit_id = %s, finalized_at = %s
                WHERE cycle_number = %s AND goal_key = %s AND state = 'CLAIMED'
                RETURNING *
                """,
                (
                    definition_id,
                    run_id,
                    expected_plan_sha256,
                    expected_client_order_id,
                    json.dumps(list(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES)),
                    total_calls,
                    market_snapshot_sha256,
                    evidence_sha256,
                    audit_id,
                    now,
                    cycle_number,
                    goal_key,
                ),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreConflict(
                    "automation_atomic_market_snapshot_already_finalized"
                )
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=run_id,
                from_state=None,
                to_state=OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION.value,
                diagnostic_code="automation_spot_preview_invocation_started",
                audit_id=audit_id,
                idempotency_key_sha256=str(current["idempotency_key_sha256"]),
                correlation_id=correlation_id,
                recorded_at=now,
            )
            record = self._atomic_market_snapshot_cycle_from_row(row)
            return AutomationStoreMutation(record, audit_id, correlation_id)

    @staticmethod
    def _transport_successor_cycle_from_row(
        row: Mapping[str, Any],
    ) -> AutomationSpotTransportSuccessorCycleRecord:
        categories = row.get("completed_categories") or []
        if isinstance(categories, str):
            categories = json.loads(categories)
        return AutomationSpotTransportSuccessorCycleRecord(
            cycle_number=int(row["cycle_number"]),
            goal_key=str(row["goal_key"]),
            candidate_version=int(row["candidate_version"]),
            state=str(row["state"]),
            definition_id=(
                str(row["definition_id"])
                if row.get("definition_id") is not None
                else None
            ),
            run_id=(
                str(row["run_id"])
                if row.get("run_id") is not None
                else None
            ),
            plan_sha256=row.get("plan_sha256"),
            client_order_id=(
                str(row["client_order_id"])
                if row.get("client_order_id") is not None
                else None
            ),
            diagnostic_code=str(row["diagnostic_code"]),
            dns_status=str(row["dns_status"]),
            tcp_status=str(row["tcp_status"]),
            tls_status=str(row["tls_status"]),
            readiness_failure_class=row.get("readiness_failure_class"),
            dns_probe_count=int(row["dns_probe_count"]),
            tcp_probe_count=int(row["tcp_probe_count"]),
            tls_probe_count=int(row["tls_probe_count"]),
            readiness_evidence_sha256=row.get("readiness_evidence_sha256"),
            completed_categories=tuple(str(item) for item in categories),
            coinbase_api_call_count=(
                int(row["coinbase_api_call_count"])
                if row.get("coinbase_api_call_count") is not None
                else None
            ),
            call_count_exact=bool(row["call_count_exact"]),
            market_snapshot_sha256=row.get("market_snapshot_sha256"),
            evidence_sha256=row.get("evidence_sha256"),
            audit_id=str(row["audit_id"]),
            correlation_id=str(row["correlation_id"]),
            started_at=_iso(row["started_at"]) or "",
            finalized_at=_iso(row.get("finalized_at")),
        )

    def list_spot_transport_successor_cycles(
        self,
    ) -> tuple[AutomationSpotTransportSuccessorCycleRecord, ...]:
        rows = self.database.execute_query(
            f"SELECT * FROM {self._prefix}automation_spot_transport_successor_cycle "
            "ORDER BY cycle_number"
        )
        return tuple(self._transport_successor_cycle_from_row(row) for row in rows)

    def spot_transport_successor_available(self) -> bool:
        """Return V13-V15 ledger actionability without reserving a cycle."""

        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_spot_preview_gated_goal "
                "WHERE goal_key = ANY(%s)",
                (list(sorted(AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS)),),
            )
            goals = {str(row["goal_key"]): row for row in self._rows(cursor)}
            cursor.execute(
                f"SELECT cycle_number, goal_key, state FROM "
                f"{self._prefix}automation_spot_transport_successor_cycle "
                "ORDER BY cycle_number"
            )
            cycles = self._rows(cursor)
        return (
            _select_transport_successor(
                goals,
                cycles,
                documented_corrections=(
                    _AUTOMATION_SPOT_DOCUMENTED_TRANSPORT_SUCCESSOR_CORRECTIONS
                ),
            )
            is not None
        )

    def start_spot_transport_successor_cycle(
        self,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotTransportSuccessorCycleRecord]:
        """Claim one goal-global V13-V15 cycle before any probe or API read."""

        self._validate_command(command)
        idempotency_hash = _hash(command.idempotency_key)
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_transport_successor_cycle
                WHERE idempotency_key_sha256 = %s
                FOR UPDATE
                """,
                (idempotency_hash,),
            )
            replay = self._row(cursor)
            if replay is not None:
                if (
                    replay["payload_sha256"] != command.payload_sha256
                    or replay["actor_id_sha256"] != _hash(command.actor_id)
                    or replay["operator_intent_sha256"]
                    != _hash(command.operator_intent)
                    or replay["correlation_id"] != command.correlation_id
                ):
                    raise AutomationStoreConflict(
                        "automation_transport_successor_idempotency_conflict"
                    )
                record = self._transport_successor_cycle_from_row(replay)
                return AutomationStoreMutation(
                    record,
                    record.audit_id,
                    record.correlation_id,
                    True,
                )
            posture = self._current_control(cursor, for_update=True)
            if posture is not OperatorAutomationControlPosture.ACTIVE:
                raise AutomationStoreConflict("automation_control_plane_not_active")
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_preview_gated_goal
                WHERE goal_key = ANY(%s)
                ORDER BY goal_key
                FOR UPDATE
                """,
                (list(sorted(AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS)),),
            )
            goals = {str(row["goal_key"]): row for row in self._rows(cursor)}
            if set(goals) != set(AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS):
                raise AutomationStoreUnavailable(
                    "automation_transport_successor_goal_ledger_unavailable"
                )
            cursor.execute(
                f"SELECT cycle_number, goal_key, state FROM "
                f"{self._prefix}automation_spot_transport_successor_cycle "
                "ORDER BY cycle_number FOR UPDATE"
            )
            existing_cycles = self._rows(cursor)
            target = _select_transport_successor(
                goals,
                existing_cycles,
                documented_corrections=(
                    _AUTOMATION_SPOT_DOCUMENTED_TRANSPORT_SUCCESSOR_CORRECTIONS
                ),
            )
            if target is None:
                raise AutomationStoreConflict(
                    "automation_transport_successor_not_available"
                )
            candidate_version, goal_key = target
            cycle_number = max(
                (int(cycle["cycle_number"]) for cycle in existing_cycles),
                default=0,
            ) + 1
            if cycle_number > 10:
                raise AutomationStoreConflict(
                    "automation_transport_successor_cycles_exhausted"
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_transport_successor_cycle (
                    cycle_number, goal_key, candidate_version, state,
                    definition_id, run_id, plan_sha256, client_order_id,
                    idempotency_key_sha256, payload_sha256, actor_id_sha256,
                    operator_intent_sha256, diagnostic_code,
                    dns_status, tcp_status, tls_status,
                    readiness_failure_class, dns_probe_count, tcp_probe_count,
                    tls_probe_count, readiness_evidence_sha256,
                    completed_categories, coinbase_api_call_count,
                    call_count_exact, market_snapshot_sha256,
                    evidence_sha256, audit_id, correlation_id,
                    started_at, finalized_at
                ) VALUES (
                    %s,%s,%s,'CLAIMED',NULL,NULL,NULL,NULL,%s,%s,%s,%s,
                    'transport_readiness_cycle_claimed',
                    'NOT_ATTEMPTED','NOT_ATTEMPTED','NOT_ATTEMPTED',
                    NULL,0,0,0,NULL,'[]'::jsonb,NULL,FALSE,NULL,NULL,
                    %s,%s,%s,NULL
                ) RETURNING *
                """,
                (
                    cycle_number,
                    goal_key,
                    candidate_version,
                    idempotency_hash,
                    command.payload_sha256,
                    _hash(command.actor_id),
                    _hash(command.operator_intent),
                    audit_id,
                    command.correlation_id,
                    now,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            return AutomationStoreMutation(
                self._transport_successor_cycle_from_row(row),
                audit_id,
                command.correlation_id,
            )

    def finalize_spot_transport_readiness(
        self,
        *,
        cycle_number: int,
        goal_key: str,
        ready: bool,
        failure_class: str,
        dns_status: str,
        tcp_status: str,
        tls_status: str,
        dns_probe_count: int,
        tcp_probe_count: int,
        tls_probe_count: int,
    ) -> AutomationStoreMutation[AutomationSpotTransportSuccessorCycleRecord]:
        """Persist only fixed probe stages; never accept address/cert/error values."""

        allowed_failures = {
            "NONE",
            "DNS_RESOLUTION_FAILURE",
            "TCP_CONNECTION_FAILURE",
            "CONNECT_TIMEOUT",
            "TLS_OR_CERTIFICATE_FAILURE",
            "UNKNOWN_TRANSPORT",
        }
        statuses = {"NOT_ATTEMPTED", "SUCCEEDED", "FAILED"}
        success_shape = (
            failure_class == "NONE"
            and (dns_status, tcp_status, tls_status)
            == ("SUCCEEDED", "SUCCEEDED", "SUCCEEDED")
            and (dns_probe_count, tcp_probe_count, tls_probe_count) == (1, 1, 1)
        )
        probe_shape = (
            dns_status,
            tcp_status,
            tls_status,
            dns_probe_count,
            tcp_probe_count,
            tls_probe_count,
        )
        dns_failure_shape = (
            "FAILED",
            "NOT_ATTEMPTED",
            "NOT_ATTEMPTED",
            1,
            0,
            0,
        )
        tcp_failure_shape = (
            "SUCCEEDED",
            "FAILED",
            "NOT_ATTEMPTED",
            1,
            1,
            0,
        )
        tls_failure_shape = (
            "SUCCEEDED",
            "SUCCEEDED",
            "FAILED",
            1,
            1,
            1,
        )
        failure_shape = (
            failure_class == "DNS_RESOLUTION_FAILURE"
            and probe_shape == dns_failure_shape
        ) or (
            failure_class in {"TCP_CONNECTION_FAILURE", "CONNECT_TIMEOUT"}
            and probe_shape == tcp_failure_shape
        ) or (
            failure_class == "TLS_OR_CERTIFICATE_FAILURE"
            and probe_shape == tls_failure_shape
        ) or (
            failure_class == "UNKNOWN_TRANSPORT"
            and probe_shape
            in {dns_failure_shape, tcp_failure_shape, tls_failure_shape}
        )
        if (
            goal_key not in AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS
            or type(ready) is not bool
            or failure_class not in allowed_failures
            or {dns_status, tcp_status, tls_status} - statuses
            or any(
                type(value) is not int or value not in {0, 1}
                for value in (dns_probe_count, tcp_probe_count, tls_probe_count)
            )
            or ready is not success_shape
            or (not ready and failure_class == "NONE")
            or (not ready and not failure_shape)
        ):
            raise AutomationStoreInvalid("automation_transport_readiness_invalid")
        readiness_evidence_sha256 = _hash(
            json.dumps(
                {
                    "hostname": "api.coinbase.com",
                    "port": 443,
                    "failure_class": failure_class,
                    "dns_status": dns_status,
                    "tcp_status": tcp_status,
                    "tls_status": tls_status,
                    "dns_probe_count": dns_probe_count,
                    "tcp_probe_count": tcp_probe_count,
                    "tls_probe_count": tls_probe_count,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        target_state = "READINESS_PASSED" if ready else "BLOCKED"
        diagnostic = (
            "transport_readiness_succeeded"
            if ready
            else f"transport_readiness_{failure_class.lower()}"
        )
        terminal_evidence = (
            None
            if ready
            else _hash(
                json.dumps(
                    {
                        "cycle_number": cycle_number,
                        "goal_key": goal_key,
                        "readiness_evidence_sha256": readiness_evidence_sha256,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM {self._prefix}automation_spot_transport_successor_cycle
                WHERE cycle_number = %s AND goal_key = %s FOR UPDATE
                """,
                (cycle_number, goal_key),
            )
            current = self._row(cursor)
            if current is None:
                raise AutomationStoreNotFound(
                    "automation_transport_successor_cycle_not_found"
                )
            if current["state"] != "CLAIMED":
                record = self._transport_successor_cycle_from_row(current)
                return AutomationStoreMutation(
                    record, record.audit_id, record.correlation_id, True
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_transport_successor_cycle
                SET state = %s, diagnostic_code = %s,
                    dns_status = %s, tcp_status = %s, tls_status = %s,
                    readiness_failure_class = %s,
                    dns_probe_count = %s, tcp_probe_count = %s,
                    tls_probe_count = %s, readiness_evidence_sha256 = %s,
                    coinbase_api_call_count = %s, call_count_exact = %s,
                    evidence_sha256 = %s, audit_id = %s, finalized_at = %s
                WHERE cycle_number = %s AND goal_key = %s AND state = 'CLAIMED'
                RETURNING *
                """,
                (
                    target_state,
                    diagnostic,
                    dns_status,
                    tcp_status,
                    tls_status,
                    failure_class,
                    dns_probe_count,
                    tcp_probe_count,
                    tls_probe_count,
                    readiness_evidence_sha256,
                    None if ready else 0,
                    False if ready else True,
                    terminal_evidence,
                    audit_id,
                    None if ready else now,
                    cycle_number,
                    goal_key,
                ),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreConflict(
                    "automation_transport_readiness_already_finalized"
                )
            record = self._transport_successor_cycle_from_row(row)
            return AutomationStoreMutation(
                record, audit_id, record.correlation_id
            )

    def finalize_spot_transport_successor_terminal(
        self,
        *,
        cycle_number: int,
        goal_key: str,
        state: Literal["BLOCKED", "UNKNOWN"],
        diagnostic_code: str,
        completed_categories: tuple[str, ...],
        coinbase_api_call_count: int | None,
        call_count_exact: bool,
        evidence_sha256: str | None,
    ) -> AutomationStoreMutation[AutomationSpotTransportSuccessorCycleRecord]:
        """Close a post-readiness failed cycle without creating a candidate."""

        if (
            goal_key not in AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS
            or state not in {"BLOCKED", "UNKNOWN"}
            or not diagnostic_code.startswith(("atomic_", "minimum_", "automation_"))
            or tuple(completed_categories)
            != AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[: len(completed_categories)]
            or len(completed_categories) > 8
            or (state == "UNKNOWN")
            is not (
                coinbase_api_call_count is None
                and not call_count_exact
                and evidence_sha256 is None
            )
            or (
                state == "BLOCKED"
                and (
                    type(coinbase_api_call_count) is not int
                    or coinbase_api_call_count < 0
                    or not call_count_exact
                    or evidence_sha256 is None
                )
            )
            or (
                evidence_sha256 is not None
                and _SHA256_PATTERN.fullmatch(evidence_sha256) is None
            )
        ):
            raise AutomationStoreInvalid(
                "automation_transport_successor_result_invalid"
            )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM {self._prefix}automation_spot_transport_successor_cycle
                WHERE cycle_number = %s AND goal_key = %s FOR UPDATE
                """,
                (cycle_number, goal_key),
            )
            current = self._row(cursor)
            if current is None:
                raise AutomationStoreNotFound(
                    "automation_transport_successor_cycle_not_found"
                )
            if current["state"] != "READINESS_PASSED":
                record = self._transport_successor_cycle_from_row(current)
                return AutomationStoreMutation(
                    record, record.audit_id, record.correlation_id, True
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_transport_successor_cycle
                SET state = %s, diagnostic_code = %s,
                    completed_categories = %s::jsonb,
                    coinbase_api_call_count = %s, call_count_exact = %s,
                    evidence_sha256 = %s, audit_id = %s, finalized_at = %s
                WHERE cycle_number = %s AND goal_key = %s
                  AND state = 'READINESS_PASSED'
                RETURNING *
                """,
                (
                    state,
                    diagnostic_code,
                    json.dumps(list(completed_categories)),
                    coinbase_api_call_count,
                    call_count_exact,
                    evidence_sha256,
                    audit_id,
                    now,
                    cycle_number,
                    goal_key,
                ),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreConflict(
                    "automation_transport_successor_already_finalized"
                )
            record = self._transport_successor_cycle_from_row(row)
            return AutomationStoreMutation(
                record, audit_id, record.correlation_id
            )

    def materialize_spot_transport_successor_and_claim_preview(
        self,
        *,
        cycle_number: int,
        goal_key: str,
        definition_id: str,
        run_id: str,
        terms: AutomationSpotSingleChildPlanTerms,
        expected_plan_sha256: str,
        expected_client_order_id: str,
        market_snapshot_sha256: str,
        evidence_sha256: str,
        attempts: tuple[Any, ...],
    ) -> AutomationStoreMutation[AutomationSpotTransportSuccessorCycleRecord]:
        """Persist V13-V15 terms/evidence and consume one Preview claim atomically."""

        _validate_id(definition_id, code="automation_definition_id_invalid")
        _validate_id(run_id, code="automation_run_id_invalid")
        if (
            goal_key not in AUTOMATION_SPOT_TRANSPORT_GOAL_KEYS
            or _SHA256_PATTERN.fullmatch(expected_plan_sha256) is None
            or _SHA256_PATTERN.fullmatch(market_snapshot_sha256) is None
            or _SHA256_PATTERN.fullmatch(evidence_sha256) is None
            or len(attempts) != len(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES)
            or tuple(item.category for item in attempts)
            != AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
        ):
            raise AutomationStoreInvalid(
                "automation_transport_successor_materialization_invalid"
            )
        values = self._validated_spot_plan_values(
            self._spot_plan_command_for_revision(
                definition_id=definition_id,
                definition_revision=1,
                terms=terms,
                command=AutomationMutationCommand(
                    idempotency_key="transport-successor-materialization",
                    payload_sha256=evidence_sha256,
                    actor_id="backend-owned-transport-successor",
                    correlation_id="transport-successor-binding",
                    operator_intent="materialize_transport_successor",
                ),
            ),
            post_only_required=True,
            dynamic_execution_cap=True,
        )
        if (
            values["plan_sha256"] != expected_plan_sha256
            or Decimal(values["submitted_notional_usdc"]) >= Decimal("3.10")
            or Decimal(values["possible_execution_notional_usdc"])
            >= Decimal("3.10")
        ):
            raise AutomationStoreInvalid(
                "automation_transport_successor_plan_binding_invalid"
            )
        expected_identity = self.deterministic_spot_client_order_id(
            run_id=run_id,
            plan_sha256=expected_plan_sha256,
            goal_key=goal_key,
        )
        if expected_identity != expected_client_order_id:
            raise AutomationStoreInvalid(
                "automation_transport_successor_identity_invalid"
            )
        total_calls = 0
        fresh_until_values: list[datetime] = []
        for item in attempts:
            observed_at = _aware_utc_datetime(item.observed_at)
            fresh_until = _aware_utc_datetime(item.fresh_until)
            if (
                type(item.coinbase_api_call_count) is not int
                or item.coinbase_api_call_count < 1
                or observed_at is None
                or fresh_until is None
                or fresh_until <= observed_at
                or _SHA256_PATTERN.fullmatch(item.evidence_sha256) is None
            ):
                raise AutomationStoreInvalid(
                    "automation_transport_successor_attempt_invalid"
                )
            total_calls += item.coinbase_api_call_count
            fresh_until_values.append(fresh_until)
        now = _utc_now()
        if min(fresh_until_values) <= now:
            raise AutomationStoreConflict("automation_transport_successor_stale")
        with self.database.get_cursor() as cursor:
            posture = self._current_control(cursor, for_update=True)
            if posture is not OperatorAutomationControlPosture.ACTIVE:
                raise AutomationStoreConflict("automation_control_plane_not_active")
            cursor.execute(
                f"""
                SELECT * FROM {self._prefix}automation_spot_transport_successor_cycle
                WHERE cycle_number = %s AND goal_key = %s FOR UPDATE
                """,
                (cycle_number, goal_key),
            )
            current = self._row(cursor)
            if current is None:
                raise AutomationStoreNotFound(
                    "automation_transport_successor_cycle_not_found"
                )
            if current["state"] != "READINESS_PASSED":
                record = self._transport_successor_cycle_from_row(current)
                return AutomationStoreMutation(
                    record, record.audit_id, record.correlation_id, True
                )
            cursor.execute(
                f"""
                SELECT * FROM {self._prefix}automation_spot_preview_gated_goal
                WHERE goal_key = %s FOR UPDATE
                """,
                (goal_key,),
            )
            goal = self._row(cursor)
            if (
                goal is None
                or goal.get("definition_id") is not None
                or bool(goal.get("preview_allowance_consumed"))
            ):
                raise AutomationStoreConflict(
                    "automation_spot_preview_allowance_consumed"
                )
            audit_id = _new_id()
            correlation_id = str(current["correlation_id"])
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_definition (
                    definition_id, revision, label, domain, job_kind,
                    lifecycle_state, product_ids, schedule_kind,
                    interval_seconds, next_review_at, created_at, updated_at
                ) VALUES (
                    %s,1,%s,'SPOT','SPOT_CAMPAIGN','ENABLED',
                    '["BTC-USDC"]'::jsonb,'MANUAL_ONLY',NULL,NULL,%s,%s
                )
                """,
                (
                    definition_id,
                    f"BTC-USDC transport explainable V{int(current['candidate_version'])}",
                    now,
                    now,
                ),
            )
            self._insert_spot_single_child_plan(
                cursor,
                values=values,
                audit_id=audit_id,
                correlation_id=correlation_id,
                recorded_at=now,
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_plan_goal (
                    definition_id, goal_key, created_at
                ) VALUES (%s,%s,%s)
                """,
                (definition_id, goal_key, now),
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_run (
                    run_id, definition_id, definition_revision, domain,
                    job_kind, state, diagnostic_code, audit_id,
                    correlation_id, client_order_id, live_attempt_consumed,
                    coinbase_api_call_count, create_call_count,
                    cancel_call_count, claimed_at, updated_at
                ) VALUES (
                    %s,%s,1,'SPOT','SPOT_CAMPAIGN',
                    'AWAITING_OPERATOR_AUTHORIZATION',
                    'automation_spot_preview_invocation_started',%s,%s,%s,
                    TRUE,%s,0,0,%s,%s
                )
                """,
                (
                    run_id,
                    definition_id,
                    audit_id,
                    correlation_id,
                    expected_client_order_id,
                    total_calls,
                    now,
                    now,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_spot_eligibility_cycle (
                    goal_key, cycle_number, policy_revision, run_id,
                    definition_id, definition_revision, plan_sha256,
                    portfolio_id_sha256, product_id, client_order_id,
                    state, coinbase_api_call_count, call_count_exact,
                    fresh_until, diagnostic_code, audit_id, correlation_id,
                    started_at, finalized_at
                ) VALUES (
                    %s,%s,5,%s,%s,1,%s,%s,'BTC-USDC',%s,'SUCCEEDED',
                    %s,TRUE,%s,'automation_spot_eligibility_succeeded',
                    %s,%s,%s,%s
                )
                """,
                (
                    goal_key,
                    cycle_number,
                    run_id,
                    definition_id,
                    expected_plan_sha256,
                    values["portfolio_id_sha256"],
                    expected_client_order_id,
                    total_calls,
                    min(fresh_until_values),
                    audit_id,
                    correlation_id,
                    now,
                    now,
                ),
            )
            for item in attempts:
                portfolio_evidence = (
                    values["portfolio_id_sha256"]
                    if item.category == "PORTFOLIO_CATALOG"
                    else None
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._prefix}automation_spot_eligibility_attempt (
                        run_id, goal_key, cycle_number, category,
                        allowance_consumed, outcome, eligible,
                        coinbase_api_call_count, call_count_exact,
                        diagnostic_code, audit_id, correlation_id,
                        started_at, finalized_at, observed_at, fresh_until,
                        evidence_sha256, portfolio_id_sha256
                    ) VALUES (
                        %s,%s,%s,%s,TRUE,'SUCCEEDED',TRUE,%s,TRUE,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s
                    )
                    """,
                    (
                        run_id,
                        goal_key,
                        cycle_number,
                        item.category,
                        item.coinbase_api_call_count,
                        f"automation_spot_eligibility_{item.category.lower()}_succeeded",
                        audit_id,
                        correlation_id,
                        now,
                        now,
                        item.observed_at,
                        item.fresh_until,
                        item.evidence_sha256,
                        portfolio_evidence,
                    ),
                )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_preview_gated_goal
                SET definition_id = %s, bound_run_id = %s,
                    client_order_id = %s, eligibility_cycle = %s,
                    plan_sha256 = %s, portfolio_id_sha256 = %s,
                    product_id = 'BTC-USDC', preview_allowance_consumed = TRUE,
                    updated_at = %s
                WHERE goal_key = %s AND definition_id IS NULL
                  AND preview_allowance_consumed = FALSE
                """,
                (
                    definition_id,
                    run_id,
                    expected_client_order_id,
                    cycle_number,
                    expected_plan_sha256,
                    values["portfolio_id_sha256"],
                    now,
                    goal_key,
                ),
            )
            if cursor.rowcount != 1:
                raise AutomationStoreConflict(
                    "automation_spot_preview_allowance_consumed"
                )
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_spot_transport_successor_cycle
                SET state = 'MATERIALIZED', definition_id = %s, run_id = %s,
                    plan_sha256 = %s, client_order_id = %s,
                    diagnostic_code = 'atomic_market_snapshot_terms_bound',
                    completed_categories = %s::jsonb,
                    coinbase_api_call_count = %s, call_count_exact = TRUE,
                    market_snapshot_sha256 = %s, evidence_sha256 = %s,
                    audit_id = %s, finalized_at = %s
                WHERE cycle_number = %s AND goal_key = %s
                  AND state = 'READINESS_PASSED'
                RETURNING *
                """,
                (
                    definition_id,
                    run_id,
                    expected_plan_sha256,
                    expected_client_order_id,
                    json.dumps(list(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES)),
                    total_calls,
                    market_snapshot_sha256,
                    evidence_sha256,
                    audit_id,
                    now,
                    cycle_number,
                    goal_key,
                ),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreConflict(
                    "automation_transport_successor_already_finalized"
                )
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=run_id,
                from_state=None,
                to_state=(
                    OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION.value
                ),
                diagnostic_code="automation_spot_preview_invocation_started",
                audit_id=audit_id,
                idempotency_key_sha256=str(current["idempotency_key_sha256"]),
                correlation_id=correlation_id,
                recorded_at=now,
            )
            record = self._transport_successor_cycle_from_row(row)
            return AutomationStoreMutation(record, audit_id, correlation_id)

    def has_spot_single_child_run(
        self,
        *,
        goal_key: str = AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
    ) -> bool:
        """Return whether one plan-bearing run is claimed for this goal."""

        if goal_key not in _AUTOMATION_SPOT_GOAL_KEYS:
            raise AutomationStoreInvalid("automation_spot_goal_key_invalid")

        rows = self.database.execute_query(
            f"""
            SELECT EXISTS (
                SELECT 1
                FROM {self._prefix}automation_run AS run
                JOIN {self._prefix}automation_spot_single_child_plan AS plan
                  ON plan.definition_id = run.definition_id
                 AND plan.definition_revision = run.definition_revision
                JOIN {self._prefix}automation_spot_plan_goal AS binding
                  ON binding.definition_id = run.definition_id
                WHERE binding.goal_key = %s
            ) AS claimed
            """,
            (goal_key,),
        )
        if len(rows) != 1:
            raise AutomationStoreUnavailable(
                "automation_spot_live_proof_goal_unavailable"
            )
        return bool(rows[0]["claimed"])

    def _run_from_row(self, row: Mapping[str, Any]) -> AutomationRunRecord:
        return AutomationRunRecord(
            run_id=str(row["run_id"]),
            definition_id=str(row["definition_id"]),
            definition_revision=(
                int(row["definition_revision"])
                if row.get("definition_revision") is not None
                else None
            ),
            domain=OperatorAutomationDomain(row["domain"]),
            job_kind=OperatorAutomationJobKind(row["job_kind"]),
            state=OperatorAutomationRunState(row["state"]),
            diagnostic_code=row["diagnostic_code"],
            audit_id=str(row["audit_id"]),
            correlation_id=row["correlation_id"],
            client_order_id=(
                str(row["client_order_id"])
                if row.get("client_order_id") is not None
                else None
            ),
            live_attempt_consumed=bool(row["live_attempt_consumed"]),
            coinbase_api_call_count=int(row["coinbase_api_call_count"]),
            create_call_count=int(row["create_call_count"]),
            cancel_call_count=int(row["cancel_call_count"]),
            claimed_at=_iso(row["claimed_at"]) or "",
            updated_at=_iso(row["updated_at"]) or "",
        )

    @staticmethod
    def _run_json(record: AutomationRunRecord) -> dict[str, Any]:
        result = asdict(record)
        result["domain"] = record.domain.value
        result["job_kind"] = record.job_kind.value
        result["state"] = record.state.value
        return result

    def _run_from_json(self, value: Mapping[str, Any]) -> AutomationRunRecord:
        return AutomationRunRecord(
            run_id=value["run_id"],
            definition_id=value["definition_id"],
            definition_revision=(
                int(value["definition_revision"])
                if value.get("definition_revision") is not None
                else None
            ),
            domain=OperatorAutomationDomain(value["domain"]),
            job_kind=OperatorAutomationJobKind(value["job_kind"]),
            state=OperatorAutomationRunState(value["state"]),
            diagnostic_code=value["diagnostic_code"],
            audit_id=value["audit_id"],
            correlation_id=value["correlation_id"],
            client_order_id=value.get("client_order_id"),
            live_attempt_consumed=bool(value["live_attempt_consumed"]),
            coinbase_api_call_count=int(value["coinbase_api_call_count"]),
            create_call_count=int(value["create_call_count"]),
            cancel_call_count=int(value["cancel_call_count"]),
            claimed_at=value["claimed_at"],
            updated_at=value["updated_at"],
        )

    def claim_one_shot_run(
        self,
        definition_id: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationRunRecord]:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type="run_claim_one_shot",
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._run_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            posture = self._current_control(cursor, for_update=True)
            if posture is not OperatorAutomationControlPosture.ACTIVE:
                raise AutomationStoreConflict("automation_control_plane_not_active")
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition WHERE definition_id = %s FOR UPDATE",
                (definition_id,),
            )
            definition = self._row(cursor)
            if definition is None:
                raise AutomationStoreNotFound("automation_definition_not_found")
            if definition["lifecycle_state"] != OperatorAutomationDefinitionState.ENABLED.value:
                raise AutomationStoreConflict("automation_definition_not_enabled")
            cursor.execute(
                f"SELECT run_id FROM {self._prefix}automation_run WHERE definition_id = %s AND state = ANY(%s) LIMIT 1",
                (definition_id, [state.value for state in _ACTIVE_RUN_STATES]),
            )
            if cursor.fetchone() is not None:
                raise AutomationStoreConflict("automation_run_in_progress")
            cursor.execute(
                f"""
                SELECT 1
                FROM {self._prefix}automation_spot_single_child_plan
                WHERE definition_id = %s AND definition_revision = %s
                """,
                (definition_id, int(definition["revision"])),
            )
            if cursor.fetchone() is not None:
                goal_key = self._spot_goal_key_for_definition_cursor(
                    cursor,
                    definition_id=definition_id,
                )
                if goal_key == AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
                    self._lock_spot_live_goal_cursor(cursor)
                else:
                    successor_goal = self._lock_spot_preview_goal_cursor(
                        cursor,
                        goal_key=goal_key,
                    )
                    if str(successor_goal.get("definition_id")) != definition_id:
                        raise AutomationStoreConflict(
                            "automation_spot_preview_candidate_mismatch"
                        )
                cursor.execute(
                    f"""
                    SELECT 1
                    FROM {self._prefix}automation_run AS run
                    JOIN {self._prefix}automation_spot_single_child_plan AS plan
                      ON plan.definition_id = run.definition_id
                     AND plan.definition_revision = run.definition_revision
                    WHERE run.definition_id = %s
                    LIMIT 1
                    """,
                    (definition_id,),
                )
                if cursor.fetchone() is not None:
                    raise AutomationStoreConflict(
                        "automation_spot_goal_run_already_claimed"
                    )
            now = _utc_now()
            run_id = _new_id()
            audit_id = _new_id()
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_run (
                    run_id, definition_id, definition_revision, domain, job_kind, state,
                    diagnostic_code, audit_id, correlation_id, client_order_id,
                    live_attempt_consumed, coinbase_api_call_count,
                    create_call_count, cancel_call_count, claimed_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,'CLAIMED','one_shot_run_claimed',%s,%s,NULL,FALSE,0,0,0,%s,%s)
                RETURNING *
                """,
                (
                    run_id,
                    definition_id,
                    int(definition["revision"]),
                    definition["domain"],
                    definition["job_kind"],
                    audit_id,
                    command.correlation_id,
                    now,
                    now,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            record = self._run_from_row(row)
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=run_id,
                from_state=None,
                to_state=record.state.value,
                diagnostic_code=record.diagnostic_code,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type="run_claim_one_shot",
                resource_id=run_id,
                audit_id=audit_id,
                result=self._run_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    def audit_spot_source_gate_authorization(
        self,
        run_id: str,
        *,
        expected_plan_sha256: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationRunRecord]:
        """Bind one blocked authorization request without changing run state or calls."""

        _validate_id(run_id, code="automation_run_id_invalid")
        resource_type = "spot_source_gate_authorization"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._run_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            cursor.execute(
                f"""
                SELECT run.*, plan.plan_sha256
                FROM {self._prefix}automation_run AS run
                LEFT JOIN {self._prefix}automation_spot_single_child_plan AS plan
                  ON plan.definition_id = run.definition_id
                 AND plan.definition_revision = run.definition_revision
                WHERE run.run_id = %s
                FOR UPDATE OF run
                """,
                (run_id,),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreNotFound("automation_run_not_found")
            if (
                row["job_kind"] != OperatorAutomationJobKind.SPOT_CAMPAIGN.value
                or row.get("definition_revision") is None
                or row.get("plan_sha256") is None
            ):
                raise AutomationStoreConflict(
                    "automation_single_child_run_ineligible"
                )
            if expected_plan_sha256 != row["plan_sha256"]:
                raise AutomationStoreConflict(
                    "automation_single_child_plan_mismatch"
                )
            if (
                row["state"] != OperatorAutomationRunState.BLOCKED.value
                or row["diagnostic_code"]
                != "automation_active_order_catalog_read_not_authorized"
            ):
                raise AutomationStoreConflict(
                    "automation_single_child_run_not_authorizable"
                )
            record = self._run_from_row(row)
            now = _utc_now()
            audit_id = _new_id()
            diagnostic = "automation_active_order_catalog_read_not_authorized"
            self._append_event(
                cursor,
                definition_id=record.definition_id,
                run_id=run_id,
                from_state=OperatorAutomationRunState.BLOCKED.value,
                to_state=OperatorAutomationRunState.BLOCKED.value,
                diagnostic_code=diagnostic,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._run_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(
                record,
                audit_id,
                command.correlation_id,
            )

    def _lock_spot_live_goal_cursor(self, cursor: Any) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self._prefix}automation_spot_live_proof_goal
            WHERE singleton = 1
            FOR UPDATE
            """
        )
        goal = self._row(cursor)
        if (
            goal is None
            or goal.get("goal_key") != _AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY
        ):
            raise AutomationStoreUnavailable(
                "automation_spot_live_proof_goal_unavailable"
            )
        return goal

    def _lock_spot_preview_goal_cursor(
        self,
        cursor: Any,
        *,
        goal_key: str,
    ) -> dict[str, Any]:
        if goal_key not in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS:
            raise AutomationStoreInvalid("automation_spot_goal_key_invalid")
        cursor.execute(
            f"""
            SELECT *
            FROM {self._prefix}automation_spot_preview_gated_goal
            WHERE goal_key = %s
            FOR UPDATE
            """,
            (goal_key,),
        )
        goal = self._row(cursor)
        if goal is None:
            raise AutomationStoreUnavailable(
                "automation_spot_preview_gated_goal_unavailable"
            )
        return goal

    def _lock_spot_goal_for_run_cursor(
        self,
        cursor: Any,
        *,
        run_id: str,
    ) -> tuple[str, dict[str, Any]]:
        goal_key = self._spot_goal_key_for_run_cursor(
            cursor,
            run_id=run_id,
        )
        if goal_key == AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY:
            return goal_key, self._lock_spot_live_goal_cursor(cursor)
        return goal_key, self._lock_spot_preview_goal_cursor(
            cursor,
            goal_key=goal_key,
        )

    def _insert_spot_eligibility_cycle_cursor(
        self,
        cursor: Any,
        *,
        run: Mapping[str, Any],
        plan: Mapping[str, Any],
        cycle_number: int,
        audit_id: str,
        correlation_id: str,
        recorded_at: datetime,
    ) -> AutomationSpotEligibilityCycleRecord:
        goal_key = self._spot_goal_key_for_definition_cursor(
            cursor,
            definition_id=str(run["definition_id"]),
        )
        client_order_id = self.deterministic_spot_client_order_id(
            run_id=str(run["run_id"]),
            plan_sha256=plan["plan_sha256"],
            goal_key=goal_key,
        )
        policy_revision = _spot_policy_revision_for_goal(goal_key)
        cursor.execute(
            f"""
            INSERT INTO {self._prefix}automation_spot_eligibility_cycle (
                goal_key, cycle_number, policy_revision, run_id, definition_id,
                definition_revision, plan_sha256, portfolio_id_sha256,
                product_id, client_order_id, state,
                coinbase_api_call_count, call_count_exact, diagnostic_code,
                audit_id, correlation_id, started_at, finalized_at
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OPEN',NULL,FALSE,
                'automation_spot_eligibility_cycle_opened',%s,%s,%s,NULL
            )
            RETURNING *
            """,
            (
                goal_key,
                cycle_number,
                policy_revision,
                str(run["run_id"]),
                str(run["definition_id"]),
                int(run["definition_revision"]),
                plan["plan_sha256"],
                plan["portfolio_id_sha256"],
                plan["product_id"],
                client_order_id,
                audit_id,
                correlation_id,
                recorded_at,
            ),
        )
        row = self._row(cursor)
        assert row is not None
        return self._spot_eligibility_cycle_from_row(row)

    def _allocate_spot_eligibility_cycle_cursor(
        self,
        cursor: Any,
        *,
        run_id: str,
        expected_plan_sha256: str,
        command: AutomationMutationCommand,
        start_state: OperatorAutomationRunState,
        start_diagnostic_codes: frozenset[str],
        transition_diagnostic: str,
    ) -> tuple[AutomationRunRecord, AutomationSpotEligibilityCycleRecord, str]:
        cursor.execute(
            f"""
            SELECT run.*, plan.plan_sha256, plan.portfolio_id_sha256,
                   plan.product_id
            FROM {self._prefix}automation_run AS run
            LEFT JOIN {self._prefix}automation_spot_single_child_plan AS plan
              ON plan.definition_id = run.definition_id
             AND plan.definition_revision = run.definition_revision
            WHERE run.run_id = %s
            FOR UPDATE OF run
            """,
            (run_id,),
        )
        row = self._row(cursor)
        if row is None:
            raise AutomationStoreNotFound("automation_run_not_found")
        if (
            row["job_kind"] != OperatorAutomationJobKind.SPOT_CAMPAIGN.value
            or row.get("definition_revision") is None
            or row.get("plan_sha256") is None
            or row.get("portfolio_id_sha256") is None
            or row.get("product_id") != "BTC-USDC"
        ):
            raise AutomationStoreConflict(
                "automation_single_child_run_ineligible"
            )
        if expected_plan_sha256 != row["plan_sha256"]:
            raise AutomationStoreConflict(
                "automation_single_child_plan_mismatch"
            )
        if (
            row["state"] != start_state.value
            or row["diagnostic_code"] not in start_diagnostic_codes
        ):
            raise AutomationStoreConflict(
                "automation_single_child_run_not_resumable"
            )

        goal_key = self._spot_goal_key_for_definition_cursor(
            cursor,
            definition_id=str(row["definition_id"]),
        )

        if goal_key in AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS:
            series_goal_keys = AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS
        elif goal_key in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS:
            series_goal_keys = AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS
        else:
            series_goal_keys = None
        if series_goal_keys is not None:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_eligibility_cycle
                WHERE goal_key = ANY(%s)
                ORDER BY cycle_number
                FOR UPDATE
                """,
                (list(sorted(series_goal_keys)),),
            )
        else:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._prefix}automation_spot_eligibility_cycle
                WHERE goal_key = %s
                ORDER BY cycle_number
                FOR UPDATE
                """,
                (goal_key,),
            )
        cycles = self._rows(cursor)
        if any(cycle["state"] == "OPEN" for cycle in cycles):
            raise AutomationStoreConflict(
                "automation_spot_eligibility_cycle_in_progress"
            )
        next_cycle = max(
            (int(cycle["cycle_number"]) for cycle in cycles),
            default=0,
        ) + 1
        if goal_key in AUTOMATION_SPOT_NEAR_MARKET_GOAL_KEYS:
            preparation_table = "automation_spot_near_market_preparation"
        elif goal_key in AUTOMATION_SPOT_MINIMUM_SIZE_GOAL_KEYS:
            preparation_table = "automation_spot_minimum_size_preparation"
        else:
            preparation_table = None
        if preparation_table is not None:
            cursor.execute(
                f"""
                SELECT cycle_number
                FROM {self._prefix}{preparation_table}
                ORDER BY cycle_number
                FOR UPDATE
                """
            )
            preparations = self._rows(cursor)
            next_cycle = max(
                next_cycle,
                max(
                    (
                        int(preparation["cycle_number"])
                        for preparation in preparations
                    ),
                    default=0,
                )
                + 1,
            )
        if next_cycle > 10:
            raise AutomationStoreConflict(
                "automation_spot_eligibility_cycles_exhausted"
            )

        now = _utc_now()
        audit_id = _new_id()
        diagnostic = transition_diagnostic
        cursor.execute(
            f"""
            UPDATE {self._prefix}automation_run
            SET state = %s, diagnostic_code = %s, audit_id = %s,
                correlation_id = %s, updated_at = %s
            WHERE run_id = %s RETURNING *
            """,
            (
                OperatorAutomationRunState.PREPARING.value,
                diagnostic,
                audit_id,
                command.correlation_id,
                now,
                run_id,
            ),
        )
        updated = self._row(cursor)
        assert updated is not None
        record = self._run_from_row(updated)
        cycle = self._insert_spot_eligibility_cycle_cursor(
            cursor,
            run=row,
            plan=row,
            cycle_number=next_cycle,
            audit_id=audit_id,
            correlation_id=command.correlation_id,
            recorded_at=now,
        )
        self._append_event(
            cursor,
            definition_id=record.definition_id,
            run_id=run_id,
            from_state=start_state.value,
            to_state=OperatorAutomationRunState.PREPARING.value,
            diagnostic_code=diagnostic,
            audit_id=audit_id,
            idempotency_key_sha256=_hash(command.idempotency_key),
            correlation_id=command.correlation_id,
            recorded_at=now,
        )
        return record, cycle, audit_id

    def _allocate_spot_eligibility_cycle(
        self,
        run_id: str,
        *,
        expected_plan_sha256: str,
        command: AutomationMutationCommand,
        resource_type: str,
        start_state: OperatorAutomationRunState,
        start_diagnostic_codes: frozenset[str],
        transition_diagnostic: str,
    ) -> AutomationStoreMutation[AutomationSpotEligibilityCycleAllocationRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            goal_key, _goal = self._lock_spot_goal_for_run_cursor(
                cursor,
                run_id=run_id,
            )
            if replay is not None:
                identity = replay["entity"]
                replay_run_id = identity.get("run_id")
                replay_cycle_number = identity.get("cycle_number")
                if (
                    replay_run_id != run_id
                    or type(replay_cycle_number) is not int
                    or not 1 <= replay_cycle_number <= 10
                ):
                    raise AutomationStoreUnavailable(
                        "automation_spot_eligibility_replay_identity_invalid"
                    )
                cursor.execute(
                    f"SELECT * FROM {self._prefix}automation_run "
                    "WHERE run_id = %s FOR UPDATE",
                    (run_id,),
                )
                current_run = self._row(cursor)
                if current_run is None:
                    raise AutomationStoreUnavailable(
                        "automation_spot_eligibility_replay_run_missing"
                    )
                cursor.execute(
                    f"""
                    SELECT *
                    FROM {self._prefix}automation_spot_eligibility_cycle
                    WHERE goal_key = %s AND cycle_number = %s
                    FOR UPDATE
                    """,
                    (
                        goal_key,
                        replay_cycle_number,
                    ),
                )
                current_cycle = self._row(cursor)
                if (
                    current_cycle is None
                    or str(current_cycle["run_id"]) != run_id
                    or current_cycle["plan_sha256"] != expected_plan_sha256
                ):
                    raise AutomationStoreUnavailable(
                        "automation_spot_eligibility_replay_binding_invalid"
                    )
                if current_cycle["state"] == "OPEN":
                    raise AutomationStoreConflict(
                        "automation_spot_eligibility_cycle_in_progress"
                    )
                terminal_result_applied = bool(
                    (
                        current_cycle["state"] == "SUCCEEDED"
                        and current_run["state"]
                        == OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION.value
                        and current_run["diagnostic_code"]
                        == "awaiting_operator_authorization"
                    )
                    or (
                        current_cycle["state"] in {"REJECTED", "UNKNOWN"}
                        and current_run["state"]
                        == OperatorAutomationRunState.BLOCKED.value
                        and current_run["diagnostic_code"]
                        == "automation_spot_eligibility_refresh_required"
                    )
                )
                replay_during_newer_cycle = False
                if (
                    current_run["state"]
                    == OperatorAutomationRunState.PREPARING.value
                    and current_run["diagnostic_code"]
                    in {
                        "automation_spot_source_gate_resumed",
                        "automation_spot_final_admission_started",
                    }
                ):
                    cursor.execute(
                        f"""
                        SELECT *
                        FROM {self._prefix}automation_spot_eligibility_cycle
                        WHERE goal_key = %s AND state = 'OPEN'
                        FOR UPDATE
                        """,
                        (goal_key,),
                    )
                    open_cycles = self._rows(cursor)
                    replay_during_newer_cycle = bool(
                        len(open_cycles) == 1
                        and str(open_cycles[0]["run_id"]) == run_id
                        and int(open_cycles[0]["cycle_number"])
                        > replay_cycle_number
                        and open_cycles[0]["plan_sha256"]
                        == expected_plan_sha256
                    )
                if not (terminal_result_applied or replay_during_newer_cycle):
                    raise AutomationStoreUnavailable(
                        "automation_spot_eligibility_terminal_source_gate_missing"
                    )
                return AutomationStoreMutation(
                    AutomationSpotEligibilityCycleAllocationRecord(
                        run=self._run_from_row(current_run),
                        cycle=self._spot_eligibility_cycle_from_row(
                            current_cycle
                        ),
                    ),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            record, cycle, audit_id = (
                self._allocate_spot_eligibility_cycle_cursor(
                    cursor,
                    run_id=run_id,
                    expected_plan_sha256=expected_plan_sha256,
                    command=command,
                    start_state=start_state,
                    start_diagnostic_codes=start_diagnostic_codes,
                    transition_diagnostic=transition_diagnostic,
                )
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result={
                    "run_id": run_id,
                    "cycle_number": cycle.cycle_number,
                },
                recorded_at=_utc_now(),
            )
            return AutomationStoreMutation(
                AutomationSpotEligibilityCycleAllocationRecord(
                    run=record,
                    cycle=cycle,
                ),
                audit_id,
                command.correlation_id,
            )

    def resume_spot_source_gated_run(
        self,
        run_id: str,
        *,
        expected_plan_sha256: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotEligibilityCycleAllocationRecord]:
        """Atomically resume an exact blocked source gate and allocate a cycle."""

        return self._allocate_spot_eligibility_cycle(
            run_id,
            expected_plan_sha256=expected_plan_sha256,
            command=command,
            resource_type="spot_source_gate_resume",
            start_state=OperatorAutomationRunState.BLOCKED,
            start_diagnostic_codes=frozenset(
                {
                    "automation_active_order_catalog_read_not_authorized",
                    "automation_spot_eligibility_refresh_required",
                    "restart_pre_invocation_blocked",
                }
            ),
            transition_diagnostic="automation_spot_source_gate_resumed",
        )

    def allocate_spot_authorization_cycle(
        self,
        run_id: str,
        *,
        expected_plan_sha256: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationSpotEligibilityCycleAllocationRecord]:
        """Allocate the final fresh cycle for an exact operator Create decision."""

        return self._allocate_spot_eligibility_cycle(
            run_id,
            expected_plan_sha256=expected_plan_sha256,
            command=command,
            resource_type="spot_authorization_cycle_allocate",
            start_state=OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
            start_diagnostic_codes=frozenset(
                {"awaiting_operator_authorization"}
            ),
            transition_diagnostic="automation_spot_final_admission_started",
        )

    @staticmethod
    def _run_transition_allowed(
        current: OperatorAutomationRunState,
        target: OperatorAutomationRunState,
    ) -> bool:
        transitions = {
            OperatorAutomationRunState.CLAIMED: {
                OperatorAutomationRunState.PREPARING,
                OperatorAutomationRunState.BLOCKED,
                OperatorAutomationRunState.ABORTED,
            },
            OperatorAutomationRunState.PREPARING: {
                OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                OperatorAutomationRunState.BLOCKED,
                OperatorAutomationRunState.ABORTED,
            },
            OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION: {
                OperatorAutomationRunState.INVOCATION_STARTED,
                OperatorAutomationRunState.BLOCKED,
                OperatorAutomationRunState.ABORTED,
            },
            OperatorAutomationRunState.INVOCATION_STARTED: {
                OperatorAutomationRunState.ACTIVE,
                OperatorAutomationRunState.TERMINAL,
                OperatorAutomationRunState.UNKNOWN_CONSUMED,
            },
            OperatorAutomationRunState.ACTIVE: {
                OperatorAutomationRunState.TERMINAL,
                OperatorAutomationRunState.UNKNOWN_CONSUMED,
            },
        }
        return target in transitions.get(current, set())

    def transition_run(
        self,
        run_id: str,
        target_state: OperatorAutomationRunState | str,
        *,
        diagnostic_code: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationRunRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        target = OperatorAutomationRunState(target_state)
        if re.fullmatch(r"[a-z0-9_]{1,96}", diagnostic_code) is None:
            raise AutomationStoreInvalid("automation_run_diagnostic_invalid")
        resource_type = f"run_transition_{target.value.lower()}"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._run_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_run WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreNotFound("automation_run_not_found")
            current = OperatorAutomationRunState(row["state"])
            if not self._run_transition_allowed(current, target):
                raise AutomationStoreConflict("automation_run_transition_invalid")
            now = _utc_now()
            audit_id = _new_id()
            live_consumed = bool(row["live_attempt_consumed"]) or target is OperatorAutomationRunState.UNKNOWN_CONSUMED
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_run
                SET state = %s, diagnostic_code = %s, audit_id = %s,
                    correlation_id = %s, live_attempt_consumed = %s,
                    updated_at = %s
                WHERE run_id = %s RETURNING *
                """,
                (
                    target.value,
                    diagnostic_code,
                    audit_id,
                    command.correlation_id,
                    live_consumed,
                    now,
                    run_id,
                ),
            )
            updated = self._row(cursor)
            assert updated is not None
            record = self._run_from_row(updated)
            self._append_event(
                cursor,
                definition_id=record.definition_id,
                run_id=run_id,
                from_state=current.value,
                to_state=target.value,
                diagnostic_code=diagnostic_code,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._run_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    def get_run(self, run_id: str) -> AutomationRunRecord | None:
        _validate_id(run_id, code="automation_run_id_invalid")
        rows = self.database.execute_query(
            f"SELECT * FROM {self._prefix}automation_run WHERE run_id = %s",
            (run_id,),
        )
        return self._run_from_row(rows[0]) if rows else None

    def list_runs(
        self,
        *,
        definition_id: str | None = None,
        state: OperatorAutomationRunState | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationRunRecord]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        conditions: list[str] = []
        params: list[Any] = []
        if definition_id is not None:
            _validate_id(definition_id, code="automation_definition_id_invalid")
            conditions.append("definition_id = %s")
            params.append(definition_id)
        if state is not None:
            conditions.append("state = %s")
            params.append(OperatorAutomationRunState(state).value)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_run{where}",
                tuple(params),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_run{where} ORDER BY claimed_at, run_id LIMIT %s OFFSET %s",
                tuple([*params, limit, offset]),
            )
            return AutomationStorePage(
                tuple(self._run_from_row(row) for row in self._rows(cursor)),
                total,
            )

    def list_run_events(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationRunEventRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {self._prefix}automation_run WHERE run_id = %s",
                (run_id,),
            )
            if cursor.fetchone() is None:
                raise AutomationStoreNotFound("automation_run_not_found")
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_event_outbox WHERE run_id = %s",
                (run_id,),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT event_id, run_id, sequence, from_state, to_state,
                       diagnostic_code, audit_id, idempotency_key_sha256,
                       correlation_id, recorded_at
                FROM {self._prefix}automation_event_outbox
                WHERE run_id = %s ORDER BY sequence LIMIT %s OFFSET %s
                """,
                (run_id, limit, offset),
            )
            records = tuple(
                AutomationRunEventRecord(
                    event_id=str(row["event_id"]),
                    run_id=str(row["run_id"]),
                    sequence=int(row["sequence"]),
                    from_state=(
                        OperatorAutomationRunState(row["from_state"])
                        if row["from_state"] is not None
                        else None
                    ),
                    to_state=OperatorAutomationRunState(row["to_state"]),
                    diagnostic_code=row["diagnostic_code"],
                    audit_id=str(row["audit_id"]),
                    idempotency_key_sha256=row["idempotency_key_sha256"],
                    correlation_id=row["correlation_id"],
                    recorded_at=_iso(row["recorded_at"]) or "",
                )
                for row in self._rows(cursor)
            )
            return AutomationStorePage(records, total)

    def list_definition_events(
        self,
        definition_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationLifecycleEventRecord]:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {self._prefix}automation_definition WHERE definition_id = %s",
                (definition_id,),
            )
            if cursor.fetchone() is None:
                raise AutomationStoreNotFound("automation_definition_not_found")
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_event_outbox WHERE definition_id = %s AND run_id IS NULL",
                (definition_id,),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT event_id, definition_id, from_state, to_state,
                       diagnostic_code, audit_id, correlation_id, recorded_at
                FROM {self._prefix}automation_event_outbox
                WHERE definition_id = %s AND run_id IS NULL
                ORDER BY recorded_at, event_id LIMIT %s OFFSET %s
                """,
                (definition_id, limit, offset),
            )
            return AutomationStorePage(
                tuple(
                    self._lifecycle_event_from_row(row)
                    for row in self._rows(cursor)
                ),
                total,
            )

    def list_control_events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationLifecycleEventRecord]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_event_outbox WHERE definition_id IS NULL AND run_id IS NULL"
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT event_id, definition_id, from_state, to_state,
                       diagnostic_code, audit_id, correlation_id, recorded_at
                FROM {self._prefix}automation_event_outbox
                WHERE definition_id IS NULL AND run_id IS NULL
                ORDER BY recorded_at, event_id LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return AutomationStorePage(
                tuple(
                    self._lifecycle_event_from_row(row)
                    for row in self._rows(cursor)
                ),
                total,
            )

    @staticmethod
    def _lifecycle_event_from_row(
        row: Mapping[str, Any],
    ) -> AutomationLifecycleEventRecord:
        return AutomationLifecycleEventRecord(
            event_id=str(row["event_id"]),
            definition_id=(
                str(row["definition_id"])
                if row["definition_id"] is not None
                else None
            ),
            from_state=row["from_state"],
            to_state=row["to_state"],
            diagnostic_code=row["diagnostic_code"],
            audit_id=str(row["audit_id"]),
            correlation_id=row["correlation_id"],
            recorded_at=_iso(row["recorded_at"]) or "",
        )

    def recover_runs_after_restart(self) -> tuple[AutomationRunRecord, ...]:
        """Recover pre-invocation work and quarantine any invoked work once."""

        recovered: list[AutomationRunRecord] = []
        with self.database.get_cursor() as cursor:
            self._lock_spot_live_goal_cursor(cursor)
            for preview_goal_key in sorted(_AUTOMATION_SPOT_PREVIEW_GOAL_KEYS):
                self._lock_spot_preview_goal_cursor(
                    cursor,
                    goal_key=preview_goal_key,
                )
            cursor.execute(
                f"SELECT cycle_number FROM "
                f"{self._prefix}automation_spot_near_market_preparation "
                "WHERE state = 'CLAIMED' FOR UPDATE"
            )
            for preparation in self._rows(cursor):
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_near_market_preparation
                    SET state = 'UNKNOWN',
                        diagnostic_code = 'automation_near_market_preparation_unknown',
                        completed_categories = '[]'::jsonb,
                        coinbase_api_call_count = NULL,
                        call_count_exact = FALSE,
                        evidence_sha256 = NULL,
                        audit_id = %s,
                        finalized_at = %s
                    WHERE cycle_number = %s AND state = 'CLAIMED'
                    """,
                    (
                        _new_id(),
                        _utc_now(),
                        int(preparation["cycle_number"]),
                    ),
                )
            cursor.execute(
                f"SELECT cycle_number FROM "
                f"{self._prefix}automation_spot_atomic_market_snapshot_cycle "
                "WHERE state = 'CLAIMED' FOR UPDATE"
            )
            for cycle in self._rows(cursor):
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_atomic_market_snapshot_cycle
                    SET state = 'UNKNOWN',
                        diagnostic_code = 'automation_atomic_market_snapshot_restart_unknown',
                        completed_categories = '[]'::jsonb,
                        coinbase_api_call_count = NULL,
                        call_count_exact = FALSE,
                        market_snapshot_sha256 = NULL,
                        evidence_sha256 = NULL,
                        audit_id = %s,
                        finalized_at = %s
                    WHERE cycle_number = %s AND state = 'CLAIMED'
                    """,
                    (
                        _new_id(),
                        _utc_now(),
                        int(cycle["cycle_number"]),
                    ),
                )
            cursor.execute(
                f"SELECT cycle_number FROM "
                f"{self._prefix}automation_spot_transport_successor_cycle "
                "WHERE state IN ('CLAIMED','READINESS_PASSED') FOR UPDATE"
            )
            for cycle in self._rows(cursor):
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_transport_successor_cycle
                    SET state = 'UNKNOWN',
                        diagnostic_code = 'automation_transport_successor_restart_unknown',
                        completed_categories = '[]'::jsonb,
                        coinbase_api_call_count = NULL,
                        call_count_exact = FALSE,
                        market_snapshot_sha256 = NULL,
                        evidence_sha256 = NULL,
                        audit_id = %s,
                        finalized_at = %s
                    WHERE cycle_number = %s
                      AND state IN ('CLAIMED','READINESS_PASSED')
                    """,
                    (
                        _new_id(),
                        _utc_now(),
                        int(cycle["cycle_number"]),
                    ),
                )
            cursor.execute(
                f"SELECT cycle_number FROM "
                f"{self._prefix}automation_spot_minimum_size_preparation "
                "WHERE state = 'CLAIMED' FOR UPDATE"
            )
            for preparation in self._rows(cursor):
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_spot_minimum_size_preparation
                    SET state = 'UNKNOWN',
                        diagnostic_code = 'automation_minimum_size_preparation_unknown',
                        completed_categories = '[]'::jsonb,
                        coinbase_api_call_count = NULL,
                        call_count_exact = FALSE,
                        evidence_sha256 = NULL,
                        audit_id = %s,
                        finalized_at = %s
                    WHERE cycle_number = %s AND state = 'CLAIMED'
                    """,
                    (
                        _new_id(),
                        _utc_now(),
                        int(preparation["cycle_number"]),
                    ),
                )
            cursor.execute(
                f"""
                SELECT * FROM {self._prefix}automation_run
                WHERE state = ANY(%s)
                ORDER BY claimed_at, run_id
                FOR UPDATE
                """,
                ([state.value for state in _ACTIVE_RUN_STATES],),
            )
            rows = self._rows(cursor)
            for row in rows:
                current = OperatorAutomationRunState(row["state"])
                cursor.execute(
                    f"SELECT goal_key FROM {self._prefix}automation_spot_plan_goal "
                    "WHERE definition_id = %s",
                    (str(row["definition_id"]),),
                )
                binding = self._row(cursor)
                goal_key = (
                    str(binding["goal_key"])
                    if binding is not None
                    and binding.get("goal_key") in _AUTOMATION_SPOT_GOAL_KEYS
                    else None
                )
                execution = None
                open_eligibility_cycle = None
                preview_inflight = bool(
                    goal_key in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS
                    and current
                    is OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
                    and row.get("diagnostic_code")
                    == "automation_spot_preview_invocation_started"
                )
                if (
                    goal_key in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS
                    and current
                    is OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
                    and row.get("diagnostic_code")
                    == "automation_spot_preview_accepted_create_ready"
                ):
                    # A finalized accepted Preview is a durable, known
                    # checkpoint.  It may resume only through the separately
                    # claimed V2 Create allowance and must not be consumed by
                    # process restart.
                    continue
                if current is OperatorAutomationRunState.ACTIVE:
                    cursor.execute(
                        f"""
                        SELECT *
                        FROM {self._prefix}automation_spot_run_execution
                        WHERE run_id = %s FOR UPDATE
                        """,
                        (str(row["run_id"]),),
                    )
                    execution = self._row(cursor)
                    stable_accepted_child = bool(
                        execution is not None
                        and execution["create_outcome"] == "ACCEPTED"
                        and bool(execution["create_read_call_count_exact"])
                        and execution["create_read_call_count"] is not None
                        and int(execution["create_read_call_count"]) >= 1
                        and execution["child_terminal"] is False
                        and not bool(execution["cancel_allowance_consumed"])
                        and execution["cancel_outcome"] is None
                    )
                    if stable_accepted_child:
                        # ACTIVE is a durable terminal point for the Create
                        # invocation, not an interrupted invocation.  It stays
                        # actionable only for a separately claimed exact-child
                        # safe closeout and must survive process restarts.
                        continue
                if current in _PRE_INVOCATION_STATES:
                    cursor.execute(
                        f"""
                        SELECT *
                        FROM {self._prefix}automation_spot_eligibility_cycle
                        WHERE goal_key = %s AND run_id = %s AND state = 'OPEN'
                        FOR UPDATE
                        """,
                        (
                            goal_key or _AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
                            str(row["run_id"]),
                        ),
                    )
                    open_eligibility_cycle = self._row(cursor)
                    if open_eligibility_cycle is not None:
                        self._lock_spot_eligibility_attempts_cursor(
                            cursor,
                            run_id=str(row["run_id"]),
                            cycle_number=int(
                                open_eligibility_cycle["cycle_number"]
                            ),
                        )
                if preview_inflight:
                    target = OperatorAutomationRunState.UNKNOWN_CONSUMED
                    diagnostic = "automation_spot_preview_unknown_consumed"
                    live_consumed = True
                elif current in _POST_INVOCATION_STATES:
                    target = OperatorAutomationRunState.UNKNOWN_CONSUMED
                    diagnostic = "restart_unknown_consumed"
                    live_consumed = True
                elif open_eligibility_cycle is not None:
                    target = OperatorAutomationRunState.BLOCKED
                    diagnostic = (
                        "automation_active_order_catalog_read_not_authorized"
                    )
                    live_consumed = False
                elif current in _PRE_INVOCATION_STATES:
                    target = OperatorAutomationRunState.BLOCKED
                    diagnostic = "restart_pre_invocation_blocked"
                    live_consumed = False
                else:  # pragma: no cover - guarded by the query values
                    continue
                now = _utc_now()
                audit_id = _new_id()
                correlation_id = "automation-restart-recovery"
                evidence_key = _hash(
                    f"automation-restart:{row['run_id']}:{current.value}:{diagnostic}"
                )
                if open_eligibility_cycle is not None:
                    cycle_number = int(
                        open_eligibility_cycle["cycle_number"]
                    )
                    cursor.execute(
                        f"""
                        UPDATE {self._prefix}automation_spot_eligibility_attempt
                        SET outcome = 'UNKNOWN', eligible = FALSE,
                            coinbase_api_call_count = NULL,
                            call_count_exact = FALSE,
                            diagnostic_code = 'automation_spot_eligibility_unknown',
                            audit_id = %s, correlation_id = %s,
                            finalized_at = %s, portfolio_id_sha256 = NULL,
                            observed_at = NULL, fresh_until = NULL,
                            evidence_sha256 = NULL
                        WHERE run_id = %s AND goal_key = %s
                          AND cycle_number = %s AND outcome IS NULL
                        """,
                        (
                            audit_id,
                            correlation_id,
                            now,
                            str(row["run_id"]),
                            goal_key or _AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
                            cycle_number,
                        ),
                    )
                    cursor.execute(
                        f"""
                        UPDATE {self._prefix}automation_spot_eligibility_cycle
                        SET state = 'UNKNOWN', coinbase_api_call_count = NULL,
                            call_count_exact = FALSE,
                            fresh_until = NULL,
                            diagnostic_code =
                                'automation_spot_eligibility_cycle_unknown',
                            audit_id = %s, correlation_id = %s,
                            finalized_at = %s
                        WHERE goal_key = %s AND cycle_number = %s
                          AND state = 'OPEN'
                        """,
                        (
                            audit_id,
                            correlation_id,
                            now,
                            goal_key or _AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
                            cycle_number,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise AutomationStoreUnavailable(
                            "automation_spot_eligibility_cycle_recovery_failed"
                        )
                if preview_inflight:
                    cursor.execute(
                        f"""
                        UPDATE {self._prefix}automation_spot_preview_gated_goal
                        SET preview_outcome = 'UNKNOWN',
                            preview_failure_class = 'TRANSPORT_UNKNOWN',
                            preview_warning_present = FALSE,
                            preview_id_sha256 = NULL,
                            preview_call_count = NULL,
                            preview_call_count_exact = FALSE,
                            updated_at = %s
                        WHERE goal_key = %s AND bound_run_id = %s
                          AND preview_allowance_consumed
                          AND preview_outcome IS NULL
                        """,
                        (
                            now,
                            goal_key,
                            str(row["run_id"]),
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise AutomationStoreUnavailable(
                            "automation_spot_preview_recovery_failed"
                        )
                if current in _POST_INVOCATION_STATES:
                    if execution is None:
                        cursor.execute(
                            f"""
                            SELECT *
                            FROM {self._prefix}automation_spot_run_execution
                            WHERE run_id = %s FOR UPDATE
                            """,
                            (str(row["run_id"]),),
                        )
                        execution = self._row(cursor)
                    if execution is not None and execution["create_outcome"] is None:
                        cursor.execute(
                            f"""
                            UPDATE {self._prefix}automation_spot_run_execution
                            SET create_outcome = 'UNKNOWN',
                                create_call_count = NULL,
                                create_call_count_exact = FALSE,
                                create_read_call_count = NULL,
                                create_read_call_count_exact = FALSE,
                                child_terminal = NULL,
                                audit_id = %s, correlation_id = %s,
                                updated_at = %s
                            WHERE run_id = %s
                            """,
                            (
                                audit_id,
                                correlation_id,
                                now,
                                str(row["run_id"]),
                            ),
                        )
                        if goal_key in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS:
                            cursor.execute(
                                f"""
                                UPDATE {self._prefix}automation_spot_preview_gated_goal
                                SET create_outcome = 'UNKNOWN', updated_at = %s
                                WHERE goal_key = %s AND bound_run_id = %s
                                  AND create_outcome IS NULL
                                """,
                                (
                                    now,
                                    goal_key,
                                    str(row["run_id"]),
                                ),
                            )
                        else:
                            cursor.execute(
                                f"""
                                UPDATE {self._prefix}automation_spot_live_proof_goal
                                SET create_outcome = 'UNKNOWN', updated_at = %s
                                WHERE singleton = 1 AND bound_run_id = %s
                                  AND create_outcome IS NULL
                                """,
                                (now, str(row["run_id"])),
                            )
                    elif (
                        execution is not None
                        and bool(execution["cancel_allowance_consumed"])
                        and execution["cancel_outcome"] is None
                    ):
                        cursor.execute(
                            f"""
                            UPDATE {self._prefix}automation_spot_run_execution
                            SET cancel_outcome = 'UNKNOWN',
                                cancel_call_count = NULL,
                                cancel_call_count_exact = FALSE,
                                cancel_read_call_count = NULL,
                                cancel_read_call_count_exact = FALSE,
                                child_terminal = NULL,
                                audit_id = %s, correlation_id = %s,
                                updated_at = %s
                            WHERE run_id = %s
                            """,
                            (
                                audit_id,
                                correlation_id,
                                now,
                                str(row["run_id"]),
                            ),
                        )
                        if goal_key in _AUTOMATION_SPOT_PREVIEW_GOAL_KEYS:
                            cursor.execute(
                                f"""
                                UPDATE {self._prefix}automation_spot_preview_gated_goal
                                SET cancel_outcome = 'UNKNOWN', updated_at = %s
                                WHERE goal_key = %s AND bound_run_id = %s
                                  AND cancel_outcome IS NULL
                                """,
                                (
                                    now,
                                    goal_key,
                                    str(row["run_id"]),
                                ),
                            )
                        else:
                            cursor.execute(
                                f"""
                                UPDATE {self._prefix}automation_spot_live_proof_goal
                                SET cancel_outcome = 'UNKNOWN', updated_at = %s
                                WHERE singleton = 1 AND bound_run_id = %s
                                  AND cancel_outcome IS NULL
                                """,
                                (now, str(row["run_id"])),
                            )
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_run
                    SET state = %s, diagnostic_code = %s, audit_id = %s,
                        correlation_id = %s, live_attempt_consumed = %s,
                        updated_at = %s
                    WHERE run_id = %s RETURNING *
                    """,
                    (
                        target.value,
                        diagnostic,
                        audit_id,
                        correlation_id,
                        live_consumed,
                        now,
                        str(row["run_id"]),
                    ),
                )
                updated = self._row(cursor)
                assert updated is not None
                record = self._run_from_row(updated)
                self._append_event(
                    cursor,
                    definition_id=record.definition_id,
                    run_id=record.run_id,
                    from_state=current.value,
                    to_state=target.value,
                    diagnostic_code=diagnostic,
                    audit_id=audit_id,
                    idempotency_key_sha256=evidence_key,
                    correlation_id=correlation_id,
                    recorded_at=now,
                )
                recovered.append(record)
        return tuple(recovered)


def get_default_operator_automation_repository() -> OperatorAutomationRepository:
    schema = os.environ.get("COINBASE_OPERATOR_AUTOMATION_DB_SCHEMA", "public")
    return OperatorAutomationRepository(PostgresDB(), schema=schema)


def initialize_operator_automation_schema() -> None:
    repository = get_default_operator_automation_repository()
    repository.ensure_schema()
    repository.recover_runs_after_restart()
