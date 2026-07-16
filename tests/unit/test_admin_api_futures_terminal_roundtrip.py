from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time
from typing import Any

import pytest

from application.admin_api import futures_terminal_roundtrip as roundtrip_module
from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_LIVE_POLICY,
    SLICE3_POLICY,
    SLICE3_PRODUCT_ID,
    FileSlice3ActionClaimStore,
    Slice3AcceptedPreview,
    Slice3ActionClaim,
    Slice3ActionKind,
    Slice3CapEvidence,
    Slice3ClaimDecision,
    Slice3ClaimError,
    Slice3ClaimEvent,
    Slice3ClaimRecord,
    Slice3CreateRequest,
    Slice3DirectiveKind,
    Slice3ExecutionAuthority,
    Slice3MarginWindowEvidence,
    Slice3MutationBlocked,
    Slice3MutationGate,
    Slice3MutationOutcome,
    Slice3MutationResult,
    Slice3OpenOrderZeroProof,
    Slice3OrderObservation,
    Slice3OrderResolutionSource,
    Slice3Plan,
    Slice3PlanError,
    Slice3PolicyError,
    Slice3PortfolioBinding,
    Slice3PositionObservation,
    Slice3PreCreateEvidence,
    Slice3MarketReference,
    Slice3ReadBudget,
    Slice3ReadSlot,
    Slice3TerminalEvidence,
    decide_slice3_next_action,
    initial_slice3_directive,
)
from core.enums import (
    AdminFuturesPositionSide,
    OrderSide,
    OrderStatus,
    TimeInForce,
)


NOW = datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc)
CREATE_CLIENT_ORDER_ID = "00000000-0000-4000-8000-000000000301"
CLOSE_CLIENT_ORDER_ID = "00000000-0000-4000-8000-000000000302"
PREVIEW_ID = "preview-private-synthetic-3"
EXCHANGE_ORDER_ID = "exchange-private-synthetic-3"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _claim_from_process(
    path: str,
    claim: Slice3ActionClaim,
    start: Any,
    results: Any,
) -> None:
    class _SlowAppendStore(FileSlice3ActionClaimStore):
        def _append_locked(
            self,
            descriptor: int,
            record: Slice3ClaimRecord,
        ) -> None:
            time.sleep(0.2)
            super()._append_locked(descriptor, record)

    assert start.wait(timeout=5)
    try:
        decision, _record = _SlowAppendStore(path).claim(claim)
    except Exception as exc:
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put((decision.value, None, None))


def _margin_windows() -> Slice3MarginWindowEvidence:
    return Slice3MarginWindowEvidence(
        retail_regular="MARGIN_WINDOW_TYPE_UNSPECIFIED",
        retail_intraday_margin_1="MARGIN_WINDOW_TYPE_INTRADAY",
    )


def _portfolio() -> Slice3PortfolioBinding:
    return Slice3PortfolioBinding(
        portfolio_id="portfolio-private-synthetic-3",
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
        permission_evidence_sha256=SHA_A,
        portfolio_catalog_sha256=SHA_B,
    )


def _execution_authority() -> Slice3ExecutionAuthority:
    return Slice3ExecutionAuthority(
        actor_id="operator-controlled-futures-proof",
        roles=("trader",),
        correlation_id="00000000-0000-4000-8000-000000000311",
        preview_idempotency_key="00000000-0000-4000-8000-000000000312",
        authorization_sha256=SHA_A,
        route="backend_tool_only_no_http_route",
        method="CLI",
        service_method="Slice3TerminalRoundtripOrchestrator.run",
        permission="operator_explicit_attachment_authority",
        approval_evidence_sha256=SHA_A,
        admission_evidence_sha256=SHA_B,
        cap_guard_evidence_sha256=SHA_C,
        reconciliation_evidence_sha256=SHA_A,
        live_service_evidence_sha256=SHA_B,
        adapter_evidence_sha256=SHA_C,
        product_evidence_sha256=SHA_A,
        market_evidence_sha256=SHA_B,
        margin_collateral_evidence_sha256=SHA_C,
        liquidation_evidence_sha256=SHA_A,
        fee_funding_evidence_sha256=SHA_B,
        observed_at=NOW,
    )


def _create_request(
    *,
    preview_id: str = PREVIEW_ID,
    product_id: str = SLICE3_PRODUCT_ID,
    side: OrderSide = OrderSide.BUY,
    base_size: str = "1",
    post_only: bool = True,
    time_in_force: TimeInForce = TimeInForce.GTC,
) -> Slice3CreateRequest:
    return Slice3CreateRequest(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        preview_id=preview_id,
        product_id=product_id,
        side=side,
        base_size=base_size,
        limit_price="6.40",
        post_only=post_only,
        time_in_force=time_in_force,
    )


def _accepted_preview(
    create: Slice3CreateRequest,
    *,
    accepted: bool = True,
    expires_at: datetime | None = None,
    preview_id: str = PREVIEW_ID,
) -> Slice3AcceptedPreview:
    return Slice3AcceptedPreview.from_request(
        accepted=accepted,
        preview_id=preview_id,
        preview_request=create.preview_request(),
        accepted_at=NOW - timedelta(seconds=5),
        expires_at=expires_at or NOW + timedelta(minutes=10),
        evidence_sha256=SHA_A,
        expiry_source="coinbase_documented_preview_response",
        expiry_evidence_sha256=SHA_C,
        candidate_contract_size="10",
        candidate_limit_price=create.limit_price,
        candidate_reference_price="6.40",
        commission_total="0.12",
        order_margin_total="10",
        available_margin_usdc="250",
    )


def _caps(
    *,
    opening: str = "64.00",
    exposure: str = "64.00",
    close: str = "76.80",
    turnover: str = "140.80",
) -> Slice3CapEvidence:
    return Slice3CapEvidence(
        opening_reference_usdc=opening,
        maximum_concurrent_exposure_usdc=exposure,
        conservative_close_usdc=close,
        branch_turnover_usdc=turnover,
    )


def _plan(
    *,
    create: Slice3CreateRequest | None = None,
    preview: Slice3AcceptedPreview | None = None,
    caps: Slice3CapEvidence | None = None,
    policy=SLICE3_POLICY,  # type: ignore[no-untyped-def]
    now: datetime = NOW,
) -> Slice3Plan:
    create = create or _create_request()
    preview = preview or _accepted_preview(create)
    return Slice3Plan.build(
        policy=policy,
        execution_authority=_execution_authority(),
        margin_windows=_margin_windows(),
        portfolio=_portfolio(),
        preview=preview,
        create=create,
        caps=caps or _caps(),
        close_client_order_id=CLOSE_CLIENT_ORDER_ID,
        baseline_position_contracts="0",
        baseline_position_sha256=SHA_B,
        backend_revision="backend-synthetic-revision",
        openapi_revision="openapi-synthetic-revision",
        now=now,
    )


def _live_plan() -> Slice3Plan:
    return _plan(policy=SLICE3_LIVE_POLICY)


def _position(
    *,
    contracts: str,
    side: AdminFuturesPositionSide,
    reference_price: str | None = "6.40",
    observed_at: datetime = NOW,
) -> Slice3PositionObservation:
    return Slice3PositionObservation(
        authoritative=True,
        product_id=SLICE3_PRODUCT_ID,
        side=side,
        contracts=contracts,
        reference_price=reference_price,
        contract_size="10",
        observed_at=observed_at,
        snapshot_sha256=SHA_C,
    )


def _zero_open_orders(
    *,
    active_order_count: int = 0,
    observed_at: datetime = NOW,
    authoritative: bool = True,
    pagination_complete: bool = True,
) -> Slice3OpenOrderZeroProof:
    return Slice3OpenOrderZeroProof(
        authoritative=authoritative,
        pagination_complete=pagination_complete,
        scope="exact_product_active_transitional_orders",
        product_id=SLICE3_PRODUCT_ID,
        exact_product_active_order_count=active_order_count,
        observed_at=observed_at,
        snapshot_sha256=SHA_C,
    )


def _order(
    *,
    status: OrderStatus,
    filled: str,
    remaining: str,
    active_count: int,
    authoritative: bool = True,
    pagination_complete: bool = True,
    exchange_order_id: str | None = EXCHANGE_ORDER_ID,
    resolution_source: Slice3OrderResolutionSource = (
        Slice3OrderResolutionSource.AUTHORITATIVE_ORDER_READ
    ),
    exact_client_order_match_count: int | None = None,
) -> Slice3OrderObservation:
    return Slice3OrderObservation(
        authoritative=authoritative,
        pagination_complete=pagination_complete,
        product_id=SLICE3_PRODUCT_ID,
        client_order_id=CREATE_CLIENT_ORDER_ID,
        exchange_order_id=exchange_order_id,
        status=status,
        filled_contracts=filled,
        remaining_contracts=remaining,
        active_order_count=active_count,
        observed_at=NOW,
        resolution_source=resolution_source,
        exact_client_order_match_count=exact_client_order_match_count,
    )


def _market(
    *,
    reference_price: str = "6.40",
    observed_at: datetime = NOW,
) -> Slice3MarketReference:
    return Slice3MarketReference(
        authoritative=True,
        product_id=SLICE3_PRODUCT_ID,
        reference_price=reference_price,
        observed_at=observed_at,
        snapshot_sha256="d" * 64,
    )


def _pre_create() -> Slice3PreCreateEvidence:
    return Slice3PreCreateEvidence(
        open_orders_authoritative=True,
        open_orders_pagination_complete=True,
        open_orders_scope="exact_product_active_transitional_orders",
        exact_product_active_order_count=0,
        open_orders_snapshot_sha256="e" * 64,
        open_orders_observed_at=NOW,
        position=_position(
            contracts="0",
            side=AdminFuturesPositionSide.FLAT,
            reference_price=None,
        ),
        margin_authoritative=True,
        margin_status="ready",
        margin_account_family="coinbase_futures_us_cfm",
        margin_available_usdc="250",
        margin_windows=_margin_windows(),
        margin_observed_at=NOW,
        margin_snapshot_sha256="9" * 64,
    )


def test_slice3_policy_is_separate_exact_and_dormant() -> None:
    evidence = SLICE3_POLICY.sanitized_evidence()

    assert evidence["schema_version"] == "slice3-terminal-roundtrip-policy-v1"
    assert evidence["authority"] == (
        "operator_defined_slice_3_only_not_coinbase_documented"
    )
    assert evidence["live_adapter_bound"] is False
    assert evidence["route_registered"] is False
    assert evidence["attempt_limits"] == {
        "create": 1,
        "cancel": 1,
        "close": 1,
        "retry": 0,
        "fallback": 0,
        "redirect": 0,
    }
    SLICE3_POLICY.validate_margin_windows(_margin_windows())

    with pytest.raises(Slice3PolicyError, match="margin_window_pair"):
        SLICE3_POLICY.validate_margin_windows(
            Slice3MarginWindowEvidence(
                retail_regular="MARGIN_WINDOW_TYPE_INTRADAY",
                retail_intraday_margin_1="MARGIN_WINDOW_TYPE_INTRADAY",
            )
        )


def test_plan_binds_accepted_unexpired_identical_preview_and_sanitizes_ids() -> None:
    plan = _plan()

    assert plan.create.preview_id == PREVIEW_ID
    assert plan.preview.preview_id == PREVIEW_ID
    assert plan.create.preview_request() == plan.preview.preview_request()
    assert len(plan.plan_sha256) == 64
    assert plan.policy.schema_version == "slice3-terminal-roundtrip-policy-v1"
    assert plan.create.product_id == SLICE3_PRODUCT_ID
    assert plan.create.side is OrderSide.BUY
    assert plan.create.base_size == "1"
    assert plan.contract_size == Decimal("10")
    assert plan.preview.candidate_reference_price == "6.40"
    assert plan.preview.order_margin_total == "10"
    assert plan.preview.available_margin_usdc == "250"
    assert plan.create.post_only is True
    assert plan.create.time_in_force is TimeInForce.GTC

    serialized = json.dumps(plan.sanitized_evidence(), sort_keys=True)
    assert PREVIEW_ID not in serialized
    assert "portfolio-private-synthetic-3" not in serialized
    assert CREATE_CLIENT_ORDER_ID not in serialized
    assert CLOSE_CLIENT_ORDER_ID not in serialized
    assert PREVIEW_ID not in repr(plan)
    assert "portfolio-private-synthetic-3" not in repr(plan)
    assert CREATE_CLIENT_ORDER_ID not in repr(plan)
    assert CLOSE_CLIENT_ORDER_ID not in repr(plan)
    assert plan.preview.preview_id_sha256 in serialized
    assert plan.portfolio.portfolio_id_sha256 in serialized
    assert hashlib.sha256(CREATE_CLIENT_ORDER_ID.encode()).hexdigest() in serialized
    assert hashlib.sha256(CLOSE_CLIENT_ORDER_ID.encode()).hexdigest() in serialized


def test_plan_binds_successor_authority_and_fresh_unique_portfolio_evidence() -> None:
    plan = _plan()
    evidence = plan.sanitized_evidence()

    assert evidence["schema_version"] == "slice3-terminal-roundtrip-plan-v4"
    assert evidence["execution_authority"] == {
        "schema_version": "slice3-execution-authority-v1",
        "actor_id": "operator-controlled-futures-proof",
        "roles": ["trader"],
        "correlation_id_sha256": hashlib.sha256(
            b"00000000-0000-4000-8000-000000000311"
        ).hexdigest(),
        "preview_idempotency_key_sha256": hashlib.sha256(
            b"00000000-0000-4000-8000-000000000312"
        ).hexdigest(),
        "authorization_sha256": SHA_A,
        "route": "backend_tool_only_no_http_route",
        "method": "CLI",
        "service_method": "Slice3TerminalRoundtripOrchestrator.run",
        "permission": "operator_explicit_attachment_authority",
        "approval_evidence_sha256": SHA_A,
        "admission_evidence_sha256": SHA_B,
        "cap_guard_evidence_sha256": SHA_C,
        "reconciliation_evidence_sha256": SHA_A,
        "live_service_evidence_sha256": SHA_B,
        "adapter_evidence_sha256": SHA_C,
        "product_evidence_sha256": SHA_A,
        "market_evidence_sha256": SHA_B,
        "margin_collateral_evidence_sha256": SHA_C,
        "liquidation_evidence_sha256": SHA_A,
        "fee_funding_evidence_sha256": SHA_B,
        "observed_at": NOW.isoformat(),
    }
    assert evidence["portfolio"]["read_authorized"] is True
    assert evidence["portfolio"]["exact_match_count"] == 1
    assert evidence["portfolio"]["selection_authority"] == (
        "cdp_api_key_permissioned_portfolio"
    )
    assert evidence["portfolio"]["observed_at"] == NOW.isoformat()
    assert evidence["portfolio"]["permission_evidence_sha256"] == SHA_A
    assert evidence["portfolio"]["portfolio_catalog_sha256"] == SHA_B
    assert "00000000-0000-4000-8000-000000000311" not in json.dumps(evidence)
    assert "00000000-0000-4000-8000-000000000312" not in json.dumps(evidence)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda authority: replace(authority, actor_id="other"),
            "actor_invalid",
        ),
        (
            lambda authority: replace(authority, roles=("admin",)),
            "roles_invalid",
        ),
        (
            lambda authority: replace(
                authority,
                preview_idempotency_key=authority.correlation_id,
            ),
            "identifier_collision",
        ),
        (
            lambda authority: replace(
                authority,
                observed_at=NOW - timedelta(seconds=31),
            ),
            "authority_stale",
        ),
        (
            lambda authority: replace(
                authority,
                approval_evidence_sha256="not-a-hash",
            ),
            "approval_evidence_sha256_invalid",
        ),
    ],
)
def test_validate_at_rejects_execution_authority_drift(
    mutate: Callable[[Slice3ExecutionAuthority], Slice3ExecutionAuthority],
    reason: str,
) -> None:
    plan = _live_plan()
    tampered = replace(plan, execution_authority=mutate(plan.execution_authority))

    with pytest.raises(Slice3PlanError, match=reason):
        tampered.validate_at(NOW)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda portfolio: replace(portfolio, exact_match_count=2),
            "default_portfolio_binding_invalid",
        ),
        (
            lambda portfolio: replace(
                portfolio,
                observed_at=NOW - timedelta(seconds=31),
            ),
            "portfolio_stale",
        ),
        (
            lambda portfolio: replace(
                portfolio,
                permission_evidence_sha256="not-a-hash",
            ),
            "permission_evidence_sha256_invalid",
        ),
    ],
)
def test_validate_at_rejects_portfolio_selection_evidence_drift(
    mutate: Callable[[Slice3PortfolioBinding], Slice3PortfolioBinding],
    reason: str,
) -> None:
    plan = _live_plan()
    tampered = replace(plan, portfolio=mutate(plan.portfolio))

    with pytest.raises(Slice3PlanError, match=reason):
        tampered.validate_at(NOW)


@pytest.mark.parametrize(
    ("create", "preview", "caps", "now", "reason"),
    [
        (
            _create_request(preview_id="different-preview"),
            _accepted_preview(_create_request()),
            _caps(),
            NOW,
            "preview_id_mismatch",
        ),
        (
            _create_request(side=OrderSide.SELL),
            _accepted_preview(_create_request(side=OrderSide.SELL)),
            _caps(),
            NOW,
            "create_side_invalid",
        ),
        (
            _create_request(post_only=False),
            _accepted_preview(_create_request(post_only=False)),
            _caps(),
            NOW,
            "post_only_required",
        ),
        (
            _create_request(),
            _accepted_preview(_create_request(), accepted=False),
            _caps(),
            NOW,
            "preview_not_accepted",
        ),
        (
            _create_request(),
            _accepted_preview(_create_request(), expires_at=NOW - timedelta(seconds=1)),
            _caps(),
            NOW,
            "preview_expired",
        ),
        (
            _create_request(),
            _accepted_preview(_create_request()),
            _caps(opening="100.00", turnover="176.80"),
            NOW,
            "opening_cap",
        ),
        (
            _create_request(),
            _accepted_preview(_create_request()),
            _caps(exposure="150.00"),
            NOW,
            "exposure_cap",
        ),
        (
            _create_request(),
            _accepted_preview(_create_request()),
            _caps(close="150.00", turnover="214.00"),
            NOW,
            "close_cap",
        ),
        (
            _create_request(),
            _accepted_preview(_create_request()),
            _caps(close="235.99", turnover="299.99"),
            NOW,
            "close_cap",
        ),
        (
            _create_request(),
            _accepted_preview(_create_request()),
            _caps(exposure="65.00"),
            NOW,
            "exposure_binding",
        ),
        (
            _create_request(),
            _accepted_preview(_create_request()),
            _caps(close="70.00", turnover="134.00"),
            NOW,
            "close_binding",
        ),
    ],
)
def test_plan_rejects_scope_preview_and_strict_cap_drift(
    create: Slice3CreateRequest,
    preview: Slice3AcceptedPreview,
    caps: Slice3CapEvidence,
    now: datetime,
    reason: str,
) -> None:
    with pytest.raises((Slice3PlanError, Slice3PolicyError), match=reason):
        _plan(create=create, preview=preview, caps=caps, now=now)


def test_plan_rejects_accepted_candidate_contract_size_drift() -> None:
    create = _create_request()
    preview = replace(
        _accepted_preview(create),
        candidate_contract_size="1",
    )

    with pytest.raises(Slice3PlanError, match="candidate_contract_size"):
        _plan(create=create, preview=preview)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda plan: replace(
                plan,
                create=replace(plan.create, preview_id="different-preview"),
            ),
            "preview_id_mismatch",
        ),
        (
            lambda plan: replace(
                plan,
                caps=replace(
                    plan.caps,
                    conservative_close_usdc="1",
                    branch_turnover_usdc="65",
                ),
            ),
            "close_binding",
        ),
        (
            lambda plan: replace(
                plan,
                baseline_position_contracts=Decimal("1"),
            ),
            "baseline_position_not_flat",
        ),
        (
            lambda plan: replace(plan, contract_size=Decimal("9")),
            "contract_size_invalid",
        ),
        (
            lambda plan: replace(
                plan,
                close_client_order_id=plan.create.client_order_id,
            ),
            "close_client_order_id_reused",
        ),
        (
            lambda plan: replace(plan, backend_revision=""),
            "backend_revision_invalid",
        ),
        (
            lambda plan: replace(
                plan,
                expires_at=plan.expires_at + timedelta(seconds=1),
            ),
            "expiry_binding_invalid",
        ),
    ],
)
def test_validate_at_rejects_frozen_plan_replacement_bypass(
    mutate,
    reason: str,
) -> None:  # type: ignore[no-untyped-def]
    tampered = mutate(_live_plan())

    with pytest.raises((Slice3PlanError, Slice3PolicyError), match=reason):
        tampered.validate_at(NOW)


def test_preview_expiry_blocks_create_but_not_bounded_preclaimed_risk_off() -> None:
    plan = _live_plan()
    after_preview_expiry = plan.expires_at + timedelta(seconds=1)

    with pytest.raises(Slice3PlanError):
        plan.validate_at(after_preview_expiry)

    plan.validate_risk_off_at(after_preview_expiry)
    assert plan.risk_off_expires_at > plan.expires_at
    assert plan.risk_off_expires_at <= (
        plan.preview.accepted_at + timedelta(minutes=15)
    )

    with pytest.raises(Slice3PlanError, match="risk_off_expired"):
        plan.validate_risk_off_at(plan.risk_off_expires_at)


def test_initial_result_unknown_consumes_into_read_only_and_reject_stops() -> None:
    unknown = initial_slice3_directive(
        Slice3MutationResult(
            outcome=Slice3MutationOutcome.UNKNOWN,
            reason_code="create_outcome_unknown",
        )
    )
    rejected = initial_slice3_directive(
        Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code="create_explicitly_rejected",
        )
    )

    assert unknown.kind is Slice3DirectiveKind.READ_ONLY_RECONCILE
    assert rejected.kind is Slice3DirectiveKind.COMPLETE_REJECTED


def test_open_order_cancels_once_and_partial_requires_residual_cancel_first() -> None:
    plan = _plan()
    flat = _position(
        contracts="0",
        side=AdminFuturesPositionSide.FLAT,
        reference_price=None,
    )
    opened = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.OPEN,
            filled="0",
            remaining="1",
            active_count=1,
        ),
        position=flat,
        now=NOW,
    )
    partial = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.OPEN,
            filled="0.25",
            remaining="0.75",
            active_count=1,
        ),
        position=_position(
            contracts="0.25",
            side=AdminFuturesPositionSide.LONG,
        ),
        now=NOW,
    )

    assert opened.kind is Slice3DirectiveKind.CANCEL_OPEN
    assert opened.exchange_order_id == EXCHANGE_ORDER_ID
    assert partial.kind is Slice3DirectiveKind.CANCEL_RESIDUAL
    assert partial.close_contracts is None


def test_pending_order_is_read_only_without_cancel_authority() -> None:
    directive = decide_slice3_next_action(
        _plan(),
        order=_order(
            status=OrderStatus.PENDING,
            filled="0",
            remaining="1",
            active_count=1,
        ),
        position=_position(
            contracts="0",
            side=AdminFuturesPositionSide.FLAT,
            reference_price=None,
        ),
        now=NOW,
    )

    assert directive.kind is Slice3DirectiveKind.READ_ONLY_RECONCILE
    assert directive.reason_code == "transitional_order_mutation_not_authorized"
    assert directive.exchange_order_id is None


@pytest.mark.parametrize(
    "status",
    [OrderStatus.QUEUED, OrderStatus.EDIT_QUEUED],
)
def test_queued_zero_fill_statuses_are_read_only_without_cancel_authority(
    status: OrderStatus,
) -> None:
    directive = decide_slice3_next_action(
        _plan(),
        order=_order(
            status=status,
            filled="0",
            remaining="1",
            active_count=1,
        ),
        position=_position(
            contracts="0",
            side=AdminFuturesPositionSide.FLAT,
            reference_price=None,
        ),
        now=NOW,
    )

    assert directive.kind is Slice3DirectiveKind.READ_ONLY_RECONCILE
    assert directive.reason_code == "transitional_order_mutation_not_authorized"
    assert directive.exchange_order_id is None
    assert directive.close_contracts is None


@pytest.mark.parametrize("status", [OrderStatus.QUEUED, OrderStatus.EDIT_QUEUED])
def test_queued_partial_statuses_are_read_only_without_residual_cancel(
    status: OrderStatus,
) -> None:
    directive = decide_slice3_next_action(
        _plan(),
        order=_order(
            status=status,
            filled="0.25",
            remaining="0.75",
            active_count=1,
        ),
        position=_position(
            contracts="0.25",
            side=AdminFuturesPositionSide.LONG,
        ),
        now=NOW,
    )

    assert directive.kind is Slice3DirectiveKind.READ_ONLY_RECONCILE
    assert directive.reason_code == "transitional_order_mutation_not_authorized"
    assert directive.exchange_order_id is None
    assert directive.close_contracts is None


@pytest.mark.parametrize(
    ("filled", "remaining", "position"),
    [
        (
            "0",
            "1",
            _position(
                contracts="0",
                side=AdminFuturesPositionSide.FLAT,
                reference_price=None,
            ),
        ),
        (
            "0.25",
            "0.75",
            _position(
                contracts="0.25",
                side=AdminFuturesPositionSide.LONG,
            ),
        ),
        (
            "1",
            "0",
            _position(
                contracts="1",
                side=AdminFuturesPositionSide.LONG,
            ),
        ),
    ],
)
def test_cancel_queued_is_read_only_and_never_closes_or_recancels(
    filled: str,
    remaining: str,
    position: Slice3PositionObservation,
) -> None:
    directive = decide_slice3_next_action(
        _plan(),
        order=_order(
            status=OrderStatus.CANCEL_QUEUED,
            filled=filled,
            remaining=remaining,
            active_count=1,
        ),
        position=position,
        now=NOW,
    )

    assert directive.kind is Slice3DirectiveKind.READ_ONLY_RECONCILE
    assert directive.reason_code == "cancel_queued_final_reconciliation_required"
    assert directive.exchange_order_id is None
    assert directive.close_contracts is None


@pytest.mark.parametrize(
    "status",
    [OrderStatus.QUEUED, OrderStatus.EDIT_QUEUED, OrderStatus.CANCEL_QUEUED],
)
def test_transitional_statuses_enforce_contract_conservation(
    status: OrderStatus,
) -> None:
    directive = decide_slice3_next_action(
        _plan(),
        order=_order(
            status=status,
            filled="0.25",
            remaining="0.5",
            active_count=1,
        ),
        position=_position(
            contracts="0.25",
            side=AdminFuturesPositionSide.LONG,
        ),
        now=NOW,
    )

    assert directive.kind is Slice3DirectiveKind.HALT_SAFETY
    assert directive.close_contracts is None


@pytest.mark.parametrize(
    "status",
    [OrderStatus.QUEUED, OrderStatus.EDIT_QUEUED, OrderStatus.CANCEL_QUEUED],
)
def test_transitional_statuses_enforce_position_conservation(
    status: OrderStatus,
) -> None:
    directive = decide_slice3_next_action(
        _plan(),
        order=_order(
            status=status,
            filled="0.25",
            remaining="0.75",
            active_count=1,
        ),
        position=_position(
            contracts="0",
            side=AdminFuturesPositionSide.FLAT,
            reference_price=None,
        ),
        now=NOW,
    )

    assert directive.kind is Slice3DirectiveKind.HALT_SAFETY
    assert directive.close_contracts is None


def test_partial_only_closes_after_terminal_zero_active_proof() -> None:
    plan = _plan()
    partial_position = _position(
        contracts="0.25",
        side=AdminFuturesPositionSide.LONG,
    )
    still_active = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.OPEN,
            filled="0.25",
            remaining="0.75",
            active_count=1,
        ),
        position=partial_position,
        now=NOW,
    )
    terminal = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.CANCELLED,
            filled="0.25",
            remaining="0.75",
            active_count=0,
        ),
        position=partial_position,
        now=NOW,
    )

    assert still_active.kind is Slice3DirectiveKind.CANCEL_RESIDUAL
    assert terminal.kind is Slice3DirectiveKind.CLOSE_EXACT_DELTA
    assert terminal.close_contracts == Decimal("0.25")


def test_filled_closes_exact_fresh_delta_but_unknown_or_residual_is_read_only() -> None:
    plan = _plan()
    filled = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.FILLED,
            filled="1",
            remaining="0",
            active_count=0,
        ),
        position=_position(
            contracts="1",
            side=AdminFuturesPositionSide.LONG,
        ),
        now=NOW,
    )
    unknown = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.SUBMISSION_UNKNOWN,
            filled="0",
            remaining="1",
            active_count=0,
            authoritative=False,
            pagination_complete=False,
            exchange_order_id=None,
        ),
        position=_position(
            contracts="1",
            side=AdminFuturesPositionSide.LONG,
        ),
        now=NOW,
    )
    residual = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.FILLED,
            filled="1",
            remaining="0",
            active_count=1,
        ),
        position=_position(
            contracts="1",
            side=AdminFuturesPositionSide.LONG,
        ),
        now=NOW,
    )

    assert filled.kind is Slice3DirectiveKind.CLOSE_EXACT_DELTA
    assert filled.close_contracts == Decimal("1")
    assert unknown.kind is Slice3DirectiveKind.READ_ONLY_RECONCILE
    assert residual.kind is Slice3DirectiveKind.READ_ONLY_RECONCILE


def test_unknown_create_requires_one_exact_client_id_match_before_any_mutation() -> (
    None
):
    plan = _plan()
    position = _position(
        contracts="1",
        side=AdminFuturesPositionSide.LONG,
    )
    exact = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.FILLED,
            filled="1",
            remaining="0",
            active_count=0,
            resolution_source=(
                Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
            ),
            exact_client_order_match_count=1,
        ),
        position=position,
        create_outcome=Slice3MutationOutcome.UNKNOWN,
        now=NOW,
    )
    no_match = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.SUBMISSION_UNKNOWN,
            filled="0",
            remaining="1",
            active_count=0,
            authoritative=False,
            pagination_complete=True,
            exchange_order_id=None,
            resolution_source=(
                Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
            ),
            exact_client_order_match_count=0,
        ),
        position=position,
        create_outcome=Slice3MutationOutcome.UNKNOWN,
        now=NOW,
    )
    ambiguous = decide_slice3_next_action(
        plan,
        order=_order(
            status=OrderStatus.SUBMISSION_UNKNOWN,
            filled="0",
            remaining="1",
            active_count=0,
            authoritative=False,
            pagination_complete=True,
            exchange_order_id=None,
            resolution_source=(
                Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
            ),
            exact_client_order_match_count=2,
        ),
        position=position,
        create_outcome=Slice3MutationOutcome.UNKNOWN,
        now=NOW,
    )

    assert exact.kind is Slice3DirectiveKind.CLOSE_EXACT_DELTA
    assert no_match.kind is Slice3DirectiveKind.READ_ONLY_RECONCILE
    assert ambiguous.kind is Slice3DirectiveKind.READ_ONLY_RECONCILE


def test_terminal_zero_position_completes_roundtrip() -> None:
    directive = decide_slice3_next_action(
        _plan(),
        order=_order(
            status=OrderStatus.CANCELLED,
            filled="0",
            remaining="1",
            active_count=0,
        ),
        position=_position(
            contracts="0",
            side=AdminFuturesPositionSide.FLAT,
            reference_price=None,
        ),
        now=NOW,
    )

    assert directive.kind is Slice3DirectiveKind.COMPLETE_FLAT


def test_terminal_evidence_requires_terminal_order_flat_position_and_fresh_reads() -> (
    None
):
    evidence = Slice3TerminalEvidence(
        post_close_order=_order(
            status=OrderStatus.FILLED,
            filled="1",
            remaining="0",
            active_count=0,
        ),
        final_position=_position(
            contracts="0",
            side=AdminFuturesPositionSide.FLAT,
            reference_price=None,
        ),
        final_open_orders_authoritative=True,
        final_open_orders_pagination_complete=True,
        final_exact_product_active_order_count=0,
        final_open_orders_snapshot_sha256="f" * 64,
        margin_authoritative=True,
        margin_observed_at=NOW,
        margin_snapshot_sha256="1" * 64,
    )

    evidence.validate(_plan(), now=NOW)
    serialized = json.dumps(evidence.sanitized_evidence(), sort_keys=True)
    assert EXCHANGE_ORDER_ID not in serialized

    with pytest.raises(Slice3PlanError, match="final_active_orders"):
        replace(evidence, final_exact_product_active_order_count=1).validate(
            _plan(), now=NOW
        )


def test_read_budget_is_finite_non_polling_and_each_slot_is_single_use() -> None:
    budget = Slice3ReadBudget()

    for slot in Slice3ReadSlot:
        budget.consume(slot)

    assert budget.total == 23
    assert set(budget.snapshot().values()) == {1}
    with pytest.raises(Slice3MutationBlocked, match="read_slot_consumed"):
        budget.consume(Slice3ReadSlot.POST_CREATE_ORDER)


def test_file_claim_store_preclaims_close_and_consumes_after_boundary(
    tmp_path: Path,
) -> None:
    plan = _plan()
    store = FileSlice3ActionClaimStore(tmp_path / "slice3-claims.jsonl")
    close_claim = plan.action_claim(Slice3ActionKind.CLOSE)
    assert close_claim.portfolio_id_sha256 == plan.portfolio.portfolio_id_sha256

    decision, claimed = store.claim(close_claim)
    assert decision is Slice3ClaimDecision.CLAIMED
    assert claimed.event is Slice3ClaimEvent.CLAIM

    repeated, _ = store.claim(close_claim)
    assert repeated is Slice3ClaimDecision.EXISTS

    bound = store.bind_close_evidence(
        close_claim,
        position_snapshot_sha256=SHA_C,
        market_snapshot_sha256="d" * 64,
        dependency_evidence_sha256="e" * 64,
    )
    assert bound.event is Slice3ClaimEvent.EVIDENCE_BOUND
    boundary = store.mark_exchange_boundary(close_claim)
    assert boundary.event is Slice3ClaimEvent.EXCHANGE_BOUNDARY
    assert boundary.outcome is Slice3MutationOutcome.UNKNOWN

    result = Slice3MutationResult(
        outcome=Slice3MutationOutcome.ACCEPTED,
        reason_code="close_accepted",
        exchange_order_id=EXCHANGE_ORDER_ID,
    )
    terminal = store.complete(close_claim, result)
    assert terminal.event is Slice3ClaimEvent.OUTCOME
    assert terminal.exchange_order_id_sha256 is not None

    records = store.read_all()
    assert records[0].previous_record_sha256 == "0" * 64
    for previous, current in zip(records[:-1], records[1:], strict=True):
        assert current.previous_record_sha256 == previous.record_sha256
    for record in records:
        assert record.portfolio_id_sha256 == plan.portfolio.portfolio_id_sha256
        payload = record.to_dict()
        record_sha256 = payload.pop("record_sha256")
        assert (
            record_sha256
            == hashlib.sha256(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest()
        )

    raw = (tmp_path / "slice3-claims.jsonl").read_text(encoding="utf-8")
    assert EXCHANGE_ORDER_ID not in raw
    assert PREVIEW_ID not in raw
    assert CREATE_CLIENT_ORDER_ID not in raw
    assert CLOSE_CLIENT_ORDER_ID not in raw
    assert "portfolio-private-synthetic-3" not in raw
    with pytest.raises(Slice3ClaimError, match="already_consumed"):
        store.mark_exchange_boundary(close_claim)


def test_file_claim_store_rejects_hash_tamper_and_hardlinks(
    tmp_path: Path,
) -> None:
    plan = _live_plan()
    path = tmp_path / "slice3-claims.jsonl"
    store = FileSlice3ActionClaimStore(path)
    store.claim(plan.action_claim(Slice3ActionKind.CREATE))

    row = json.loads(path.read_text(encoding="utf-8"))
    row["recorded_at"] = "2026-07-15T00:00:00+00:00"
    path.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    with pytest.raises(Slice3ClaimError, match="record_hash_invalid"):
        store.read_all()

    path.unlink()
    store.claim(plan.action_claim(Slice3ActionKind.CREATE))
    os.link(path, tmp_path / "claim-hardlink.jsonl")
    with pytest.raises(Slice3ClaimError, match="claim_log_unsafe"):
        store.read_all()


def test_file_claim_store_rejects_symlink_target(tmp_path: Path) -> None:
    real = tmp_path / "real.jsonl"
    real.write_text("", encoding="utf-8")
    os.chmod(real, 0o600)
    linked = tmp_path / "linked.jsonl"
    linked.symlink_to(real)
    store = FileSlice3ActionClaimStore(linked)

    with pytest.raises(Slice3ClaimError, match="claim_log_unsafe"):
        store.claim(_live_plan().action_claim(Slice3ActionKind.CREATE))


def test_file_claim_store_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "slice3-claims.jsonl"
    store = FileSlice3ActionClaimStore(path)
    store.claim(_live_plan().action_claim(Slice3ActionKind.CREATE))
    raw = path.read_text(encoding="utf-8")
    duplicated = raw.replace(
        '"event":"claim"',
        '"event":"claim","event":"claim"',
        1,
    )
    assert duplicated != raw
    path.write_text(duplicated, encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_duplicate_key$",
    ) as captured:
        store.read_all()

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_file_claim_store_rejects_symlinked_parent_components(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    path = linked_parent / "nested" / "slice3-claims.jsonl"
    store = FileSlice3ActionClaimStore(path)

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_unsafe$",
    ):
        store.read_all()

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_unsafe$",
    ):
        store.claim(_live_plan().action_claim(Slice3ActionKind.CREATE))

    assert not (real_parent / "nested" / "slice3-claims.jsonl").exists()


@pytest.mark.parametrize("unsafe_mode", [0o400, 0o640, 0o644])
def test_file_claim_store_requires_exact_owner_read_write_mode(
    tmp_path: Path,
    unsafe_mode: int,
) -> None:
    path = tmp_path / "slice3-claims.jsonl"
    store = FileSlice3ActionClaimStore(path)
    store.claim(_live_plan().action_claim(Slice3ActionKind.CREATE))
    path.chmod(unsafe_mode)

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_unsafe$",
    ):
        store.read_all()


def test_file_claim_store_rejects_owner_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "slice3-claims.jsonl"
    store = FileSlice3ActionClaimStore(path)
    store.claim(_live_plan().action_claim(Slice3ActionKind.CREATE))
    actual_uid = os.getuid()
    monkeypatch.setattr(roundtrip_module.os, "getuid", lambda: actual_uid + 1)

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_unsafe$",
    ):
        store.read_all()


def test_file_claim_store_revalidates_path_after_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "slice3-claims.jsonl"
    displaced = tmp_path / "displaced-after-open.jsonl"
    store = FileSlice3ActionClaimStore(path)
    real_flock = roundtrip_module.fcntl.flock
    replaced = False

    def replace_after_lock(descriptor: int, operation: int) -> None:
        nonlocal replaced
        real_flock(descriptor, operation)
        if operation == roundtrip_module.fcntl.LOCK_EX and not replaced:
            replaced = True
            os.replace(path, displaced)
            path.write_bytes(b"")
            path.chmod(0o600)

    monkeypatch.setattr(roundtrip_module.fcntl, "flock", replace_after_lock)

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_unsafe$",
    ):
        store.claim(_live_plan().action_claim(Slice3ActionKind.CREATE))

    assert path.read_bytes() == b""
    assert displaced.read_bytes() == b""


def test_file_claim_store_revalidates_path_after_read_before_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "slice3-claims.jsonl"
    displaced = tmp_path / "displaced-after-read.jsonl"
    store = FileSlice3ActionClaimStore(path)
    original_read = store._read_locked
    replaced = False

    def replace_after_read(descriptor: int) -> list[Slice3ClaimRecord]:
        nonlocal replaced
        records = original_read(descriptor)
        if not replaced:
            replaced = True
            os.replace(path, displaced)
            path.write_bytes(b"")
            path.chmod(0o600)
        return records

    monkeypatch.setattr(store, "_read_locked", replace_after_read)

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_unsafe$",
    ):
        store.claim(_live_plan().action_claim(Slice3ActionKind.CREATE))

    assert path.read_bytes() == b""
    assert displaced.read_bytes() == b""


def test_file_claim_store_revalidates_path_after_fsynced_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "slice3-claims.jsonl"
    displaced = tmp_path / "displaced-after-write.jsonl"
    store = FileSlice3ActionClaimStore(path)
    real_fsync = roundtrip_module.os.fsync
    replaced = False

    def replace_during_file_fsync(descriptor: int) -> None:
        nonlocal replaced
        real_fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not replaced
            and roundtrip_module.stat.S_ISREG(metadata.st_mode)
            and path.exists()
            and path.stat().st_ino == metadata.st_ino
        ):
            replaced = True
            os.replace(path, displaced)
            path.write_bytes(b"")
            path.chmod(0o600)

    monkeypatch.setattr(roundtrip_module.os, "fsync", replace_during_file_fsync)

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_unsafe$",
    ):
        store.claim(_live_plan().action_claim(Slice3ActionKind.CREATE))

    assert path.read_bytes() == b""
    assert b'"event":"claim"' in displaced.read_bytes()


def test_file_claim_store_rejects_truncated_and_malformed_private_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "slice3-claims.jsonl"
    store = FileSlice3ActionClaimStore(path)
    store.claim(_live_plan().action_claim(Slice3ActionKind.CREATE))
    with path.open("ab") as stream:
        stream.write(b'{"partial":')
    path.chmod(0o600)

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_truncated$",
    ):
        store.read_all()

    private_text = "PRIVATE-SLICE3-MALFORMED-ROW-TEXT"
    path.write_text('{"private":"' + private_text + '"\n', encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_malformed$",
    ) as captured:
        store.read_all()

    assert str(captured.value) == "slice3_claim_log_malformed"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert private_text not in repr(captured.value)

    path.write_text(
        '{"action_index":' + ("9" * 5000) + "}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_malformed$",
    ) as numeric_error:
        store.read_all()

    assert numeric_error.value.__cause__ is None
    assert numeric_error.value.__context__ is None


@pytest.mark.parametrize("tamper", ["record", "hash", "previous_chain"])
def test_file_claim_store_rejects_record_and_global_chain_tamper(
    tmp_path: Path,
    tamper: str,
) -> None:
    path = tmp_path / "slice3-claims.jsonl"
    plan = _live_plan()
    store = FileSlice3ActionClaimStore(path)
    store.claim(plan.action_claim(Slice3ActionKind.CREATE))
    store.claim(plan.action_claim(Slice3ActionKind.CANCEL))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if tamper == "record":
        rows[0]["recorded_at"] = "2026-07-15T00:00:00+00:00"
    elif tamper == "hash":
        rows[0]["record_sha256"] = "f" * 64
    else:
        rows[1]["previous_record_sha256"] = "e" * 64
        rows[1]["record_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in rows[1].items()
                    if key != "record_sha256"
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_record_hash_invalid$",
    ):
        store.read_all()


def test_file_claim_store_cross_process_claim_has_one_semantic_winner(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("fork")
    start = context.Event()
    results = context.Queue()
    path = tmp_path / "slice3-claims.jsonl"
    claim = _live_plan().action_claim(Slice3ActionKind.CREATE)
    processes = [
        context.Process(
            target=_claim_from_process,
            args=(str(path), claim, start, results),
        )
        for _ in range(2)
    ]

    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=10)

    assert [process.exitcode for process in processes] == [0, 0]
    assert sorted(results.get(timeout=5)[0] for _ in processes) == [
        "claimed",
        "exists",
    ]
    records = FileSlice3ActionClaimStore(path).read_all()
    assert len(records) == 1
    assert records[0].semantic_key == claim.semantic_key


def test_crash_after_exchange_boundary_stays_unknown_and_blocks_callable(
    tmp_path: Path,
) -> None:
    plan = _live_plan()
    path = tmp_path / "slice3-claims.jsonl"
    first = FileSlice3ActionClaimStore(path)
    gate = Slice3MutationGate(first)
    gate.reserve_action_claims(plan, now=NOW)
    create_claim = plan.action_claim(Slice3ActionKind.CREATE)
    boundary = first.mark_exchange_boundary(create_claim)
    assert boundary.outcome is Slice3MutationOutcome.UNKNOWN

    resumed = FileSlice3ActionClaimStore(path)
    recovered = resumed.inspect(create_claim)
    assert recovered is not None
    assert recovered.event is Slice3ClaimEvent.EXCHANGE_BOUNDARY
    assert recovered.outcome is Slice3MutationOutcome.UNKNOWN
    callable_count = 0

    def forbidden_factory() -> _RecordingPort:
        nonlocal callable_count
        callable_count += 1
        return _RecordingPort([])

    with pytest.raises(Slice3MutationBlocked, match="create_claim_consumed"):
        Slice3MutationGate(resumed).execute_create(
            plan,
            pre_create=_pre_create(),
            port_factory=forbidden_factory,
            now=NOW,
        )
    with pytest.raises(Slice3ClaimError, match="already_consumed"):
        resumed.mark_exchange_boundary(create_claim)

    assert callable_count == 0
    assert resumed.inspect(create_claim) == recovered

    terminal = resumed.recover_boundary_as_unknown(create_claim)
    assert terminal.event is Slice3ClaimEvent.OUTCOME
    assert terminal.outcome is Slice3MutationOutcome.UNKNOWN
    assert terminal.reason_code == "create_process_interrupted"
    assert terminal.exchange_order_id_sha256 is None
    repeated = resumed.recover_boundary_as_unknown(create_claim)
    assert repeated == terminal
    assert resumed.inspect(create_claim) == terminal


def test_file_claim_store_os_errors_are_fixed_and_context_free(
    tmp_path: Path,
) -> None:
    private_component = "PRIVATE-SLICE3-OS-PATH-TEXT"
    path = tmp_path / private_component
    path.symlink_to(tmp_path / "missing-target")

    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_unsafe$",
    ) as captured:
        FileSlice3ActionClaimStore(path).claim(
            _live_plan().action_claim(Slice3ActionKind.CREATE)
        )

    assert str(captured.value) == "slice3_claim_log_unsafe"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert private_component not in repr(captured.value)

    invalid_path = Path(f"{tmp_path}/{private_component}\0suffix")
    with pytest.raises(
        Slice3ClaimError,
        match="^slice3_claim_log_unsafe$",
    ) as invalid_path_error:
        FileSlice3ActionClaimStore(invalid_path).claim(
            _live_plan().action_claim(Slice3ActionKind.CREATE)
        )

    assert invalid_path_error.value.__cause__ is None
    assert invalid_path_error.value.__context__ is None
    assert private_component not in repr(invalid_path_error.value)


def test_file_claim_store_retires_unused_action_with_dependency_hash(
    tmp_path: Path,
) -> None:
    plan = _live_plan()
    store = FileSlice3ActionClaimStore(tmp_path / "slice3-claims.jsonl")
    cancel_claim = plan.action_claim(Slice3ActionKind.CANCEL)
    store.claim(cancel_claim)

    retired = store.retire_unused(
        cancel_claim,
        reason_code="cancel_not_required_filled_branch",
        dependency_evidence_sha256=SHA_A,
    )

    assert retired.event is Slice3ClaimEvent.RETIRED
    assert retired.reason_code == "cancel_not_required_filled_branch"
    assert retired.dependency_evidence_sha256 == SHA_A
    with pytest.raises(Slice3ClaimError, match="already_consumed"):
        store.mark_exchange_boundary(cancel_claim)
    raw = store.path.read_text(encoding="utf-8")
    assert CREATE_CLIENT_ORDER_ID not in raw
    assert CLOSE_CLIENT_ORDER_ID not in raw


class _RecordingPort:
    def __init__(
        self,
        events: list[str],
        *,
        create_result: Slice3MutationResult | Exception | None = None,
        cancel_result: Slice3MutationResult | Exception | None = None,
        close_result: Slice3MutationResult | Exception | None = None,
    ) -> None:
        self.events = events
        self.create_result = create_result or Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="create_accepted",
            exchange_order_id=EXCHANGE_ORDER_ID,
        )
        self.cancel_result = cancel_result or Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="cancel_accepted",
            exchange_order_id=EXCHANGE_ORDER_ID,
        )
        self.close_result = close_result or Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code="close_accepted",
        )
        self.create_kwargs: dict[str, object] | None = None
        self.cancel_kwargs: dict[str, object] | None = None
        self.close_kwargs: dict[str, object] | None = None

    @staticmethod
    def _return_or_raise(
        value: Slice3MutationResult | Exception,
    ) -> Slice3MutationResult:
        if isinstance(value, Exception):
            raise value
        return value

    def create_order(self, **kwargs: object) -> Slice3MutationResult:
        self.events.append("port.create_order")
        self.create_kwargs = kwargs
        return self._return_or_raise(self.create_result)

    def cancel_order(self, **kwargs: object) -> Slice3MutationResult:
        self.events.append("port.cancel_order")
        self.cancel_kwargs = kwargs
        return self._return_or_raise(self.cancel_result)

    def close_position(self, **kwargs: object) -> Slice3MutationResult:
        self.events.append("port.close_position")
        self.close_kwargs = kwargs
        return self._return_or_raise(self.close_result)


class _RecordingStore(FileSlice3ActionClaimStore):
    def __init__(self, path: Path, events: list[str]) -> None:
        super().__init__(path)
        self.events = events

    def claim(self, claim):  # type: ignore[no-untyped-def]
        self.events.append(f"store.claim.{claim.action.value}")
        return super().claim(claim)

    def bind_cancel_evidence(self, claim, **kwargs):  # type: ignore[no-untyped-def]
        self.events.append("store.bind.cancel")
        return super().bind_cancel_evidence(claim, **kwargs)

    def bind_close_evidence(self, claim, **kwargs):  # type: ignore[no-untyped-def]
        self.events.append("store.bind.close")
        return super().bind_close_evidence(claim, **kwargs)

    def mark_exchange_boundary(self, claim):  # type: ignore[no-untyped-def]
        self.events.append(f"store.boundary.{claim.action.value}")
        return super().mark_exchange_boundary(claim)


def _factory(port: _RecordingPort, events: list[str]) -> Callable[[], _RecordingPort]:
    def build() -> _RecordingPort:
        events.append("port.construct")
        return port

    return build


def _execute_create_for_gate(
    gate: Slice3MutationGate,
    plan: Slice3Plan,
    port: _RecordingPort,
    events: list[str],
) -> Slice3MutationResult:
    return gate.execute_create(
        plan,
        pre_create=_pre_create(),
        port_factory=_factory(port, events),
        now=NOW,
    )


def test_gate_rejects_dormant_policy_before_any_claim_or_client(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    store = _RecordingStore(tmp_path / "slice3-claims.jsonl", events)
    gate = Slice3MutationGate(store)

    with pytest.raises(Slice3MutationBlocked, match="live_policy_not_bound"):
        gate.reserve_action_claims(_plan(), now=NOW)

    assert events == []
    assert not store.path.exists()


@pytest.mark.parametrize(
    ("pre_create", "reason"),
    [
        (
            replace(
                _pre_create(),
                open_orders_observed_at=NOW - timedelta(seconds=31),
            ),
            "open_orders_stale",
        ),
        (
            replace(
                _pre_create(),
                margin_observed_at=NOW - timedelta(seconds=31),
            ),
            "margin_stale",
        ),
        (
            replace(_pre_create(), margin_available_usdc="10.12"),
            "margin_insufficient",
        ),
        (
            replace(
                _pre_create(),
                margin_windows=Slice3MarginWindowEvidence(
                    retail_regular="MARGIN_WINDOW_TYPE_INTRADAY",
                    retail_intraday_margin_1=("MARGIN_WINDOW_TYPE_INTRADAY"),
                ),
            ),
            "margin_window_pair_invalid",
        ),
    ],
)
def test_create_gate_requires_fresh_zero_orders_and_margin_before_client(
    tmp_path: Path,
    pre_create: Slice3PreCreateEvidence,
    reason: str,
) -> None:
    events: list[str] = []
    plan = _live_plan()
    store = _RecordingStore(tmp_path / "slice3-claims.jsonl", events)
    gate = Slice3MutationGate(store)
    gate.reserve_action_claims(plan, now=NOW)

    with pytest.raises(Slice3MutationBlocked, match=reason):
        gate.execute_create(
            plan,
            pre_create=pre_create,
            port_factory=_factory(_RecordingPort(events), events),
            now=NOW,
        )

    assert "port.construct" not in events
    assert "port.create_order" not in events


def test_gate_preclaims_close_then_claims_create_before_client_and_boundary(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plan = _live_plan()
    store = _RecordingStore(tmp_path / "slice3-claims.jsonl", events)
    gate = Slice3MutationGate(store)
    port = _RecordingPort(events)

    gate.reserve_action_claims(plan, now=NOW)
    result = gate.execute_create(
        plan,
        pre_create=_pre_create(),
        port_factory=_factory(port, events),
        now=NOW,
    )

    assert result.outcome is Slice3MutationOutcome.ACCEPTED
    assert events == [
        "store.claim.close",
        "store.claim.cancel",
        "store.claim.create",
        "port.construct",
        "store.boundary.create",
        "port.create_order",
    ]
    assert port.create_kwargs == {
        "client_order_id": CREATE_CLIENT_ORDER_ID,
        "product_id": SLICE3_PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "6.40",
                "post_only": True,
            }
        },
        "preview_id": PREVIEW_ID,
    }

    with pytest.raises(Slice3MutationBlocked, match="create_claim_consumed"):
        gate.execute_create(
            plan,
            pre_create=_pre_create(),
            port_factory=_factory(port, events),
            now=NOW,
        )
    assert events.count("port.create_order") == 1


def test_gate_unknown_create_is_consumed_without_exception_leak_or_retry(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plan = _live_plan()
    path = tmp_path / "slice3-claims.jsonl"
    store = _RecordingStore(path, events)
    gate = Slice3MutationGate(store)
    port = _RecordingPort(
        events,
        create_result=RuntimeError("withheld exchange exception text"),
    )

    gate.reserve_action_claims(plan, now=NOW)
    result = gate.execute_create(
        plan,
        pre_create=_pre_create(),
        port_factory=_factory(port, events),
        now=NOW,
    )

    assert result.outcome is Slice3MutationOutcome.UNKNOWN
    assert result.reason_code == "create_outcome_unknown"
    raw = path.read_text(encoding="utf-8")
    assert "withheld exchange exception text" not in raw
    with pytest.raises(Slice3MutationBlocked, match="create_claim_consumed"):
        gate.execute_create(
            plan,
            pre_create=_pre_create(),
            port_factory=_factory(port, events),
            now=NOW,
        )
    assert events.count("port.create_order") == 1


def test_pre_create_active_order_or_nonflat_position_blocks_before_client(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plan = _live_plan()
    store = _RecordingStore(tmp_path / "slice3-claims.jsonl", events)
    gate = Slice3MutationGate(store)
    port = _RecordingPort(events)
    gate.reserve_action_claims(plan, now=NOW)
    unsafe = replace(
        _pre_create(),
        exact_product_active_order_count=1,
    )

    with pytest.raises(Slice3MutationBlocked, match="pre_create_active_orders"):
        gate.execute_create(
            plan,
            pre_create=unsafe,
            port_factory=_factory(port, events),
            now=NOW,
        )

    assert "port.construct" not in events
    assert "port.create_order" not in events


def test_gate_cancel_uses_verified_exchange_id_exactly_once(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plan = _live_plan()
    store = _RecordingStore(tmp_path / "slice3-claims.jsonl", events)
    gate = Slice3MutationGate(store)
    port = _RecordingPort(events)
    gate.reserve_action_claims(plan, now=NOW)
    _execute_create_for_gate(gate, plan, port, events)
    order = _order(
        status=OrderStatus.OPEN,
        filled="0",
        remaining="1",
        active_count=1,
    )
    position = _position(
        contracts="0",
        side=AdminFuturesPositionSide.FLAT,
        reference_price=None,
    )

    result = gate.execute_cancel(
        plan,
        order=order,
        position=position,
        port_factory=_factory(port, events),
        now=NOW,
    )

    assert result.outcome is Slice3MutationOutcome.ACCEPTED
    assert port.cancel_kwargs == {
        "client_order_id": CREATE_CLIENT_ORDER_ID,
        "verified_exchange_order_id": EXCHANGE_ORDER_ID,
    }
    assert events.index("store.claim.cancel") < events.index("port.construct")
    assert events.index("store.bind.cancel") < events.index("store.boundary.cancel")
    assert events.index("store.boundary.cancel") < events.index("port.cancel_order")
    with pytest.raises(Slice3MutationBlocked, match="cancel_claim_consumed"):
        gate.execute_cancel(
            plan,
            order=order,
            position=position,
            port_factory=_factory(port, events),
            now=NOW,
        )
    assert events.count("port.cancel_order") == 1


def test_gate_binds_fresh_position_to_preclaimed_close_before_client(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plan = _live_plan()
    store = _RecordingStore(tmp_path / "slice3-claims.jsonl", events)
    gate = Slice3MutationGate(store)
    port = _RecordingPort(events)
    position = _position(
        contracts="1",
        side=AdminFuturesPositionSide.LONG,
    )
    order = _order(
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        active_count=0,
    )

    gate.reserve_action_claims(plan, now=NOW)
    _execute_create_for_gate(gate, plan, port, events)
    result = gate.execute_close(
        plan,
        order=order,
        position=position,
        market=_market(),
        open_orders=_zero_open_orders(),
        port_factory=_factory(port, events),
        now=NOW,
    )

    assert result.outcome is Slice3MutationOutcome.ACCEPTED
    assert port.close_kwargs == {
        "client_order_id": CLOSE_CLIENT_ORDER_ID,
        "product_id": SLICE3_PRODUCT_ID,
        "size": "1",
    }
    assert events.index("store.claim.close") < events.index("store.bind.close")
    close_bind_index = events.index("store.bind.close")
    assert close_bind_index < events.index("port.construct", close_bind_index)
    assert events.index("store.boundary.close") < events.index("port.close_position")
    with pytest.raises(Slice3MutationBlocked, match="close_claim_not_preclaimed"):
        gate.execute_close(
            plan,
            order=order,
            position=position,
            market=_market(),
            open_orders=_zero_open_orders(),
            port_factory=_factory(port, events),
            now=NOW,
        )
    assert events.count("port.close_position") == 1


@pytest.mark.parametrize(
    ("position", "reason"),
    [
        (
            _position(
                contracts="1",
                side=AdminFuturesPositionSide.LONG,
                observed_at=NOW - timedelta(seconds=31),
            ),
            "position_stale",
        ),
        (
            _position(
                contracts="1",
                side=AdminFuturesPositionSide.SHORT,
            ),
            "position_side_invalid",
        ),
        (
            _position(
                contracts="1.01",
                side=AdminFuturesPositionSide.LONG,
            ),
            "position_delta_exceeds_scope",
        ),
        (
            _position(
                contracts="1",
                side=AdminFuturesPositionSide.LONG,
                reference_price="12.50",
            ),
            "close_cap",
        ),
    ],
)
def test_close_guards_fail_before_client_construction(
    tmp_path: Path,
    position: Slice3PositionObservation,
    reason: str,
) -> None:
    events: list[str] = []
    plan = _live_plan()
    store = _RecordingStore(tmp_path / "slice3-claims.jsonl", events)
    gate = Slice3MutationGate(store)
    port = _RecordingPort(events)
    gate.reserve_action_claims(plan, now=NOW)
    _execute_create_for_gate(gate, plan, port, events)
    order = _order(
        status=OrderStatus.FILLED,
        filled=str(position.contracts),
        remaining=str(Decimal("1") - Decimal(position.contracts)),
        active_count=0,
    )
    construction_count = events.count("port.construct")

    with pytest.raises((Slice3MutationBlocked, Slice3PlanError), match=reason):
        gate.execute_close(
            plan,
            order=order,
            position=position,
            market=_market(),
            open_orders=_zero_open_orders(),
            port_factory=_factory(port, events),
            now=NOW,
        )

    assert events.count("port.construct") == construction_count


@pytest.mark.parametrize(
    ("proof", "reason"),
    [
        (_zero_open_orders(active_order_count=1), "active_orders"),
        (
            _zero_open_orders(pagination_complete=False),
            "open_orders_incomplete",
        ),
        (
            _zero_open_orders(observed_at=NOW - timedelta(seconds=31)),
            "open_orders_stale",
        ),
    ],
)
def test_close_requires_fresh_product_wide_zero_active_order_proof(
    tmp_path: Path,
    proof: Slice3OpenOrderZeroProof,
    reason: str,
) -> None:
    events: list[str] = []
    plan = _live_plan()
    store = _RecordingStore(tmp_path / "slice3-claims.jsonl", events)
    gate = Slice3MutationGate(store)
    port = _RecordingPort(events)
    position = _position(
        contracts="1",
        side=AdminFuturesPositionSide.LONG,
    )
    order = _order(
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        active_count=0,
    )
    gate.reserve_action_claims(plan, now=NOW)
    _execute_create_for_gate(gate, plan, port, events)
    construction_count = events.count("port.construct")

    with pytest.raises(Slice3MutationBlocked, match=reason):
        gate.execute_close(
            plan,
            order=order,
            position=position,
            market=_market(),
            open_orders=proof,
            port_factory=_factory(port, events),
            now=NOW,
        )

    assert events.count("port.construct") == construction_count
    assert "port.close_position" not in events
    assert "port.close_position" not in events


def test_stale_pre_close_market_proof_blocks_before_client(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plan = _live_plan()
    store = _RecordingStore(tmp_path / "slice3-claims.jsonl", events)
    gate = Slice3MutationGate(store)
    port = _RecordingPort(events)
    position = _position(
        contracts="1",
        side=AdminFuturesPositionSide.LONG,
    )
    gate.reserve_action_claims(plan, now=NOW)
    _execute_create_for_gate(gate, plan, port, events)
    order = _order(
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        active_count=0,
    )
    construction_count = events.count("port.construct")

    with pytest.raises(Slice3MutationBlocked, match="market_stale"):
        gate.execute_close(
            plan,
            order=order,
            position=position,
            market=_market(observed_at=NOW - timedelta(seconds=31)),
            open_orders=_zero_open_orders(),
            port_factory=_factory(port, events),
            now=NOW,
        )

    assert events.count("port.construct") == construction_count
