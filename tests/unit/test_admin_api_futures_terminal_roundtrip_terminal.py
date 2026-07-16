from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_LIVE_POLICY,
    SLICE3_PRODUCT_ID,
    Slice3AcceptedPreview,
    Slice3ActionKind,
    Slice3CapEvidence,
    Slice3CreateRequest,
    Slice3ExecutionAuthority,
    Slice3MarginWindowEvidence,
    Slice3Plan,
    Slice3PortfolioBinding,
    Slice3PositionObservation,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (
    Slice3ExactOrderEvidence,
    Slice3MarginSummary,
    Slice3OpenOrderZeroProof,
)
from application.admin_api.futures_terminal_roundtrip_terminal import (
    Slice3ActionTerminalBinding,
    Slice3TerminalEvidenceError,
    Slice3TerminalRoundtripEvidence,
)
from core.enums import (
    AdminFuturesPositionSide,
    OrderSide,
    OrderStatus,
    TimeInForce,
)
from application.admin_api.futures_terminal_roundtrip import (
    Slice3OrderObservation,
    Slice3OrderResolutionSource,
)


NOW = datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc)
CREATE_ID = "00000000-0000-4000-8000-000000000401"
CLOSE_ID = "00000000-0000-4000-8000-000000000402"
CREATE_EXCHANGE_ID = "private-create-exchange-401"
CLOSE_EXCHANGE_ID = "private-close-exchange-402"
PREVIEW_ID = "private-preview-401"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


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
        accepted_at=NOW - timedelta(seconds=10),
        expires_at=NOW + timedelta(minutes=5),
        evidence_sha256=SHA_A,
        expiry_source="coinbase_documented_preview_response",
        expiry_evidence_sha256=SHA_B,
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
            correlation_id="00000000-0000-4000-8000-000000000411",
            preview_idempotency_key="00000000-0000-4000-8000-000000000412",
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
        ),
        margin_windows=Slice3MarginWindowEvidence(
            retail_regular="MARGIN_WINDOW_TYPE_UNSPECIFIED",
            retail_intraday_margin_1="MARGIN_WINDOW_TYPE_INTRADAY",
        ),
        portfolio=Slice3PortfolioBinding(
            portfolio_id="private-portfolio-401",
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
        baseline_position_sha256=SHA_B,
        backend_revision="backend-revision",
        openapi_revision="openapi-revision",
        now=NOW,
    )


def _exact_order(
    *,
    client_id: str,
    exchange_id: str,
    side: OrderSide,
    status: OrderStatus,
    filled: str,
    remaining: str,
    filled_value: str,
    total_fees: str,
    configuration_sha256: str,
) -> Slice3ExactOrderEvidence:
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
            active_order_count=0,
            observed_at=NOW,
            resolution_source=(Slice3OrderResolutionSource.AUTHORITATIVE_ORDER_READ),
            exact_client_order_match_count=1,
        ),
        side=side,
        filled_value=filled_value,
        total_fees=total_fees,
        number_of_fills=0 if Decimal(filled) == 0 else 1,
        order_configuration_sha256=configuration_sha256,
    )


def _position() -> Slice3PositionObservation:
    return Slice3PositionObservation(
        authoritative=True,
        product_id=SLICE3_PRODUCT_ID,
        side=AdminFuturesPositionSide.FLAT,
        contracts="0",
        reference_price=None,
        contract_size="10",
        observed_at=NOW,
        snapshot_sha256=SHA_C,
    )


def _open_zero() -> Slice3OpenOrderZeroProof:
    return Slice3OpenOrderZeroProof(
        authoritative=True,
        pagination_complete=True,
        scope="exact_product_active_transitional_orders",
        product_id=SLICE3_PRODUCT_ID,
        exact_product_active_order_count=0,
        observed_at=NOW,
        snapshot_sha256="d" * 64,
    )


def _margin() -> Slice3MarginSummary:
    return Slice3MarginSummary(
        status="ready",
        account_family="coinbase_futures_us_cfm",
        available_margin_usdc="250",
        total_usd_balance_usdc="500",
        initial_margin_usdc="40",
        liquidation_threshold_usdc="80",
        retail_regular_margin_window="MARGIN_WINDOW_TYPE_UNSPECIFIED",
        retail_intraday_margin_window="MARGIN_WINDOW_TYPE_INTRADAY",
        observed_at=NOW,
        snapshot_sha256="e" * 64,
    )


def _outcome(action: Slice3ActionKind) -> Slice3ActionTerminalBinding:
    return Slice3ActionTerminalBinding(
        action=action,
        terminal_event="outcome",
        record_sha256={
            Slice3ActionKind.CREATE: "1" * 64,
            Slice3ActionKind.CANCEL: "2" * 64,
            Slice3ActionKind.CLOSE: "3" * 64,
        }[action],
        outcome="accepted",
        reason_code=f"{action.value}_accepted",
    )


def _retired(
    action: Slice3ActionKind,
    reason: str,
) -> Slice3ActionTerminalBinding:
    return Slice3ActionTerminalBinding(
        action=action,
        terminal_event="retired_not_required",
        record_sha256=("4" if action is Slice3ActionKind.CANCEL else "5") * 64,
        outcome=None,
        reason_code=reason,
    )


def test_partial_cancel_close_terminal_evidence_is_exact_and_private_free() -> None:
    plan = _plan()
    opening = _exact_order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0.25",
        remaining="0.75",
        filled_value="16",
        total_fees="0.02",
        configuration_sha256=(
            Slice3TerminalRoundtripEvidence.opening_configuration_sha256(plan)
        ),
    )
    close = _exact_order(
        client_id=CLOSE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="0.25",
        remaining="0",
        filled_value="16.02",
        total_fees="0.03",
        configuration_sha256=Slice3TerminalRoundtripEvidence.close_configuration_sha256(
            Decimal("0.25")
        ),
    )

    evidence = Slice3TerminalRoundtripEvidence.build(
        plan=plan,
        opening_order=opening,
        close_order=close,
        final_position=_position(),
        final_open_orders=_open_zero(),
        final_margin=_margin(),
        create_action=_outcome(Slice3ActionKind.CREATE),
        cancel_action=_outcome(Slice3ActionKind.CANCEL),
        close_action=_outcome(Slice3ActionKind.CLOSE),
        read_journal_sha256="6" * 64,
        completed_at=NOW,
    )

    evidence.validate(plan, now=NOW)
    assert evidence.total_fees == Decimal("0.05")
    assert evidence.branch_executed_value == Decimal("32.02")
    serialized = json.dumps(evidence.sanitized_evidence(), sort_keys=True)
    for private in (
        CREATE_ID,
        CLOSE_ID,
        CREATE_EXCHANGE_ID,
        CLOSE_EXCHANGE_ID,
        PREVIEW_ID,
        "private-portfolio-401",
    ):
        assert private not in serialized


def test_zero_fill_cancel_requires_close_claim_retirement() -> None:
    plan = _plan()
    opening = _exact_order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0",
        remaining="1",
        filled_value="0",
        total_fees="0",
        configuration_sha256=(
            Slice3TerminalRoundtripEvidence.opening_configuration_sha256(plan)
        ),
    )
    kwargs = dict(
        plan=plan,
        opening_order=opening,
        close_order=None,
        final_position=_position(),
        final_open_orders=_open_zero(),
        final_margin=_margin(),
        create_action=_outcome(Slice3ActionKind.CREATE),
        cancel_action=_outcome(Slice3ActionKind.CANCEL),
        close_action=_retired(
            Slice3ActionKind.CLOSE,
            "close_not_required_zero_exposure",
        ),
        read_journal_sha256="6" * 64,
        completed_at=NOW,
    )

    evidence = Slice3TerminalRoundtripEvidence.build(**kwargs)
    evidence.validate(plan, now=NOW)

    with pytest.raises(
        Slice3TerminalEvidenceError,
        match="close_action_not_retired",
    ):
        replace(
            evidence,
            close_action=_outcome(Slice3ActionKind.CLOSE),
        ).validate(plan, now=NOW)


def test_terminal_rejects_close_identity_size_and_fee_drift() -> None:
    plan = _plan()
    opening = _exact_order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        filled_value="64",
        total_fees="0.10",
        configuration_sha256=(
            Slice3TerminalRoundtripEvidence.opening_configuration_sha256(plan)
        ),
    )
    close = _exact_order(
        client_id=CREATE_ID,
        exchange_id=CLOSE_EXCHANGE_ID,
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        filled="1",
        remaining="0",
        filled_value="64.20",
        total_fees="0.11",
        configuration_sha256=Slice3TerminalRoundtripEvidence.close_configuration_sha256(
            Decimal("1")
        ),
    )

    with pytest.raises(
        Slice3TerminalEvidenceError,
        match="close_order_identity_invalid",
    ):
        Slice3TerminalRoundtripEvidence.build(
            plan=plan,
            opening_order=opening,
            close_order=close,
            final_position=_position(),
            final_open_orders=_open_zero(),
            final_margin=_margin(),
            create_action=_outcome(Slice3ActionKind.CREATE),
            cancel_action=_retired(
                Slice3ActionKind.CANCEL,
                "cancel_not_required_filled_branch",
            ),
            close_action=_outcome(Slice3ActionKind.CLOSE),
            read_journal_sha256="6" * 64,
            completed_at=NOW,
        )


def test_terminal_requires_fresh_margin_exact_pair_and_explicit_no_funding() -> None:
    plan = _plan()
    opening = _exact_order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELLED,
        filled="0",
        remaining="1",
        filled_value="0",
        total_fees="0",
        configuration_sha256=(
            Slice3TerminalRoundtripEvidence.opening_configuration_sha256(plan)
        ),
    )
    evidence = Slice3TerminalRoundtripEvidence.build(
        plan=plan,
        opening_order=opening,
        close_order=None,
        final_position=_position(),
        final_open_orders=_open_zero(),
        final_margin=_margin(),
        create_action=_outcome(Slice3ActionKind.CREATE),
        cancel_action=_outcome(Slice3ActionKind.CANCEL),
        close_action=_retired(
            Slice3ActionKind.CLOSE,
            "close_not_required_zero_exposure",
        ),
        read_journal_sha256="6" * 64,
        completed_at=NOW,
    )

    with pytest.raises(Slice3TerminalEvidenceError, match="margin_stale"):
        replace(
            evidence,
            final_margin=replace(_margin(), observed_at=NOW - timedelta(seconds=31)),
        ).validate(plan, now=NOW)
    with pytest.raises(Slice3TerminalEvidenceError, match="funding_binding"):
        replace(evidence, funding_required=True).validate(plan, now=NOW)


def test_explicit_create_rejection_proves_restored_baseline_without_order() -> None:
    plan = _plan()
    create_rejected = Slice3ActionTerminalBinding(
        action=Slice3ActionKind.CREATE,
        terminal_event="outcome",
        record_sha256="1" * 64,
        outcome="rejected",
        reason_code="create_rejected",
    )

    evidence = Slice3TerminalRoundtripEvidence.build(
        plan=plan,
        opening_order=None,
        close_order=None,
        final_position=_position(),
        final_open_orders=_open_zero(),
        final_margin=_margin(),
        create_action=create_rejected,
        cancel_action=_retired(
            Slice3ActionKind.CANCEL,
            "cancel_not_required_create_rejected",
        ),
        close_action=_retired(
            Slice3ActionKind.CLOSE,
            "close_not_required_create_rejected",
        ),
        read_journal_sha256="6" * 64,
        completed_at=NOW,
    )

    assert evidence.total_fees == 0
    assert evidence.branch_executed_value == 0
    assert evidence.sanitized_evidence()["opening_order"] is None

    with pytest.raises(
        Slice3TerminalEvidenceError,
        match="opening_order_missing",
    ):
        replace(
            evidence,
            create_action=replace(
                create_rejected,
                outcome="unknown",
                reason_code="create_outcome_unknown",
            ),
        ).validate(plan, now=NOW)


def test_terminal_failed_opening_can_retire_unneeded_cancel_and_close() -> None:
    plan = _plan()
    opening = _exact_order(
        client_id=CREATE_ID,
        exchange_id=CREATE_EXCHANGE_ID,
        side=OrderSide.BUY,
        status=OrderStatus.FAILED,
        filled="0",
        remaining="1",
        filled_value="0",
        total_fees="0",
        configuration_sha256=(
            Slice3TerminalRoundtripEvidence.opening_configuration_sha256(plan)
        ),
    )

    evidence = Slice3TerminalRoundtripEvidence.build(
        plan=plan,
        opening_order=opening,
        close_order=None,
        final_position=_position(),
        final_open_orders=_open_zero(),
        final_margin=_margin(),
        create_action=_outcome(Slice3ActionKind.CREATE),
        cancel_action=_retired(
            Slice3ActionKind.CANCEL,
            "cancel_not_required_terminal_branch",
        ),
        close_action=_retired(
            Slice3ActionKind.CLOSE,
            "close_not_required_zero_exposure",
        ),
        read_journal_sha256="6" * 64,
        completed_at=NOW,
    )

    evidence.validate(plan, now=NOW)
