"""Sanitized terminal proof for the bounded Slice 3 roundtrip.

The proof is deliberately separate from the mutation and read facades.  It
accepts only already-normalized evidence, validates the exact opening and
optional risk-off Close, and serializes hashes rather than identifier values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Literal

from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_EXPOSURE_CAP_USDC,
    SLICE3_MAX_READ_AGE,
    SLICE3_OPENING_CAP_USDC,
    SLICE3_PRODUCT_ID,
    SLICE3_TURNOVER_CAP_USDC,
    Slice3ActionKind,
    Slice3Plan,
    Slice3PositionObservation,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (
    Slice3ExactOrderEvidence,
    Slice3MarginSummary,
    Slice3OpenOrderZeroProof,
)
from core.enums import AdminFuturesPositionSide, OrderSide, OrderStatus


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REASON = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")


class Slice3TerminalEvidenceError(ValueError):
    """Raised when terminal evidence cannot prove the sealed safe exit."""


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decimal(value: object, reason: str) -> Decimal:
    if isinstance(value, bool):
        raise Slice3TerminalEvidenceError(reason)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Slice3TerminalEvidenceError(reason) from exc
    if not result.is_finite() or result < 0:
        raise Slice3TerminalEvidenceError(reason)
    return result


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _fresh(observed_at: datetime, now: datetime, reason: str) -> None:
    if observed_at.tzinfo is None or now.tzinfo is None:
        raise Slice3TerminalEvidenceError(f"{reason}_timestamp_invalid")
    age = now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)
    if age.total_seconds() < 0 or age > SLICE3_MAX_READ_AGE:
        raise Slice3TerminalEvidenceError(reason)


@dataclass(frozen=True)
class Slice3ActionTerminalBinding:
    """Hash-only terminal state of one preclaimed mutation action."""

    action: Slice3ActionKind
    terminal_event: Literal["outcome", "retired_not_required"]
    record_sha256: str
    outcome: Literal["accepted", "rejected", "unknown"] | None
    reason_code: str

    def validate(self) -> None:
        if not isinstance(self.action, Slice3ActionKind):
            raise Slice3TerminalEvidenceError("action_binding_action_invalid")
        if _SHA256.fullmatch(self.record_sha256) is None:
            raise Slice3TerminalEvidenceError("action_binding_hash_invalid")
        if _REASON.fullmatch(self.reason_code) is None:
            raise Slice3TerminalEvidenceError("action_binding_reason_invalid")
        if self.terminal_event == "outcome":
            if self.outcome not in {"accepted", "rejected", "unknown"}:
                raise Slice3TerminalEvidenceError("action_binding_outcome_invalid")
        elif self.outcome is not None:
            raise Slice3TerminalEvidenceError("action_binding_retirement_invalid")

    def sanitized_evidence(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "terminal_event": self.terminal_event,
            "record_sha256": self.record_sha256,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class Slice3HaltedReconciliationEvidence:
    """Sanitized last-known safety state for one immutable HALTED result."""

    plan_sha256: str
    mutation_began: bool
    final_reconciliation_attempted: bool
    final_reconciliation_complete: bool
    restored_baseline: bool
    position: Slice3PositionObservation | None
    open_orders: Slice3OpenOrderZeroProof | None
    margin: Slice3MarginSummary | None
    completed_at: datetime

    @staticmethod
    def _valid_position(
        value: object,
        *,
        plan: Slice3Plan,
        now: datetime,
    ) -> Slice3PositionObservation | None:
        if not isinstance(value, Slice3PositionObservation):
            return None
        try:
            value.validate(plan, now=now)
        except Exception:
            return None
        return value

    @staticmethod
    def _valid_open_orders(
        value: object,
        *,
        now: datetime,
    ) -> Slice3OpenOrderZeroProof | None:
        if not isinstance(value, Slice3OpenOrderZeroProof):
            return None
        count = value.exact_product_active_order_count
        if not (
            value.authoritative is True
            and value.pagination_complete is True
            and value.scope == "exact_product_active_transitional_orders"
            and value.product_id == SLICE3_PRODUCT_ID
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count >= 0
            and isinstance(value.snapshot_sha256, str)
            and _SHA256.fullmatch(value.snapshot_sha256) is not None
            and isinstance(value.observed_at, datetime)
            and value.raw_response_included is False
            and value.identifier_values_included is False
        ):
            return None
        try:
            _fresh(value.observed_at, now, "halted_open_orders_stale")
        except Slice3TerminalEvidenceError:
            return None
        return value

    @staticmethod
    def _valid_margin(
        value: object,
        *,
        plan: Slice3Plan,
        now: datetime,
    ) -> Slice3MarginSummary | None:
        if not isinstance(value, Slice3MarginSummary):
            return None
        if not (
            value.status == "ready"
            and value.account_family == "coinbase_futures_us_cfm"
            and value.retail_regular_margin_window
            == plan.margin_windows.retail_regular
            and value.retail_intraday_margin_window
            == plan.margin_windows.retail_intraday_margin_1
            and isinstance(value.snapshot_sha256, str)
            and _SHA256.fullmatch(value.snapshot_sha256) is not None
            and isinstance(value.observed_at, datetime)
            and value.raw_response_included is False
            and value.identifier_values_included is False
        ):
            return None
        try:
            _fresh(value.observed_at, now, "halted_margin_stale")
            for amount in (
                value.available_margin_usdc,
                value.total_usd_balance_usdc,
                value.initial_margin_usdc,
                value.liquidation_threshold_usdc,
            ):
                _decimal(amount, "halted_margin_amount_invalid")
        except Slice3TerminalEvidenceError:
            return None
        return value

    @classmethod
    def build(
        cls,
        *,
        plan: Slice3Plan,
        mutation_began: bool,
        final_reconciliation_attempted: bool,
        position: Slice3PositionObservation | None,
        open_orders: Slice3OpenOrderZeroProof | None,
        margin: Slice3MarginSummary | None,
        completed_at: datetime,
    ) -> "Slice3HaltedReconciliationEvidence":
        if type(mutation_began) is not bool or type(final_reconciliation_attempted) is not bool:
            raise Slice3TerminalEvidenceError("halted_reconciliation_state_invalid")
        if completed_at.tzinfo is None:
            raise Slice3TerminalEvidenceError("halted_reconciliation_time_invalid")
        if final_reconciliation_attempted:
            normalized_position = cls._valid_position(
                position,
                plan=plan,
                now=completed_at,
            )
            normalized_open_orders = cls._valid_open_orders(
                open_orders,
                now=completed_at,
            )
            normalized_margin = cls._valid_margin(
                margin,
                plan=plan,
                now=completed_at,
            )
        else:
            normalized_position = None
            normalized_open_orders = None
            normalized_margin = None
        complete = bool(
            final_reconciliation_attempted
            and normalized_position is not None
            and normalized_open_orders is not None
            and normalized_margin is not None
        )
        restored = bool(
            complete
            and normalized_position is not None
            and normalized_position.side is AdminFuturesPositionSide.FLAT
            and normalized_position.contract_delta == plan.baseline_position_contracts
            and normalized_open_orders is not None
            and normalized_open_orders.exact_product_active_order_count == 0
        )
        evidence = cls(
            plan_sha256=plan.plan_sha256,
            mutation_began=mutation_began,
            final_reconciliation_attempted=final_reconciliation_attempted,
            final_reconciliation_complete=complete,
            restored_baseline=restored,
            position=normalized_position,
            open_orders=normalized_open_orders,
            margin=normalized_margin,
            completed_at=completed_at,
        )
        evidence.validate(plan=plan, now=completed_at)
        return evidence

    def validate(self, *, plan: Slice3Plan, now: datetime) -> None:
        if (
            self.plan_sha256 != plan.plan_sha256
            or _SHA256.fullmatch(plan.plan_sha256) is None
        ):
            raise Slice3TerminalEvidenceError("halted_reconciliation_plan_invalid")
        if (
            type(self.mutation_began) is not bool
            or type(self.final_reconciliation_attempted) is not bool
            or type(self.final_reconciliation_complete) is not bool
            or type(self.restored_baseline) is not bool
            or self.completed_at.tzinfo is None
            or now.tzinfo is None
            or self.completed_at.astimezone(timezone.utc)
            > now.astimezone(timezone.utc)
        ):
            raise Slice3TerminalEvidenceError("halted_reconciliation_state_invalid")
        if (
            self.position is not None
            and self._valid_position(self.position, plan=plan, now=now) is None
        ) or (
            self.open_orders is not None
            and self._valid_open_orders(self.open_orders, now=now) is None
        ) or (
            self.margin is not None
            and self._valid_margin(self.margin, plan=plan, now=now) is None
        ):
            raise Slice3TerminalEvidenceError("halted_reconciliation_proof_invalid")
        present = (
            self.position is not None,
            self.open_orders is not None,
            self.margin is not None,
        )
        expected_complete = bool(
            self.final_reconciliation_attempted and all(present)
        )
        expected_restored = bool(
            expected_complete
            and self.position is not None
            and self.position.side is AdminFuturesPositionSide.FLAT
            and self.position.contract_delta == plan.baseline_position_contracts
            and self.open_orders is not None
            and self.open_orders.exact_product_active_order_count == 0
        )
        if (
            self.final_reconciliation_complete is not expected_complete
            or self.restored_baseline is not expected_restored
            or (not self.final_reconciliation_attempted and any(present))
        ):
            raise Slice3TerminalEvidenceError("halted_reconciliation_state_invalid")

    def _position_evidence(self) -> dict[str, object]:
        if self.position is None:
            return {
                "proof_status": "unknown",
                "product_id": SLICE3_PRODUCT_ID,
                "side": None,
                "contracts": None,
                "baseline_delta_contracts": None,
                "contract_size": None,
                "observed_at": None,
                "snapshot_sha256": None,
            }
        contracts = self.position.contract_delta
        return {
            "proof_status": "proven",
            "product_id": self.position.product_id,
            "side": self.position.side.value,
            "contracts": _decimal_text(contracts),
            "baseline_delta_contracts": _decimal_text(contracts),
            "contract_size": _decimal_text(
                _decimal(
                    self.position.contract_size,
                    "halted_position_contract_size_invalid",
                )
            ),
            "observed_at": self.position.observed_at.astimezone(timezone.utc).isoformat(),
            "snapshot_sha256": self.position.snapshot_sha256,
        }

    def _open_order_evidence(self) -> dict[str, object]:
        if self.open_orders is None:
            return {
                "proof_status": "unknown",
                "product_id": SLICE3_PRODUCT_ID,
                "active_order_count": None,
                "observed_at": None,
                "snapshot_sha256": None,
            }
        return {
            "proof_status": "proven",
            "product_id": self.open_orders.product_id,
            "active_order_count": (
                self.open_orders.exact_product_active_order_count
            ),
            "observed_at": self.open_orders.observed_at.astimezone(
                timezone.utc
            ).isoformat(),
            "snapshot_sha256": self.open_orders.snapshot_sha256,
        }

    def _margin_evidence(self) -> dict[str, object]:
        if self.margin is None:
            return {
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
        return {
            "proof_status": "proven",
            "status": self.margin.status,
            "account_family": self.margin.account_family,
            "available_margin_usdc": _decimal_text(
                _decimal(
                    self.margin.available_margin_usdc,
                    "halted_margin_amount_invalid",
                )
            ),
            "total_usd_balance_usdc": _decimal_text(
                _decimal(
                    self.margin.total_usd_balance_usdc,
                    "halted_margin_amount_invalid",
                )
            ),
            "initial_margin_usdc": _decimal_text(
                _decimal(
                    self.margin.initial_margin_usdc,
                    "halted_margin_amount_invalid",
                )
            ),
            "liquidation_threshold_usdc": _decimal_text(
                _decimal(
                    self.margin.liquidation_threshold_usdc,
                    "halted_margin_amount_invalid",
                )
            ),
            "observed_at": self.margin.observed_at.astimezone(timezone.utc).isoformat(),
            "snapshot_sha256": self.margin.snapshot_sha256,
        }

    def sanitized_evidence(
        self,
        *,
        plan: Slice3Plan,
        now: datetime,
    ) -> dict[str, object]:
        self.validate(plan=plan, now=now)
        evidence: dict[str, object] = {
            "schema_version": "slice3-halted-reconciliation-evidence-v1",
            "status": "halted",
            "plan_sha256": self.plan_sha256,
            "mutation_began": self.mutation_began,
            "final_reconciliation_attempted": (
                self.final_reconciliation_attempted
            ),
            "final_reconciliation_complete": self.final_reconciliation_complete,
            "restored_baseline": self.restored_baseline,
            "position": self._position_evidence(),
            "open_orders": self._open_order_evidence(),
            "margin": self._margin_evidence(),
            "completed_at": self.completed_at.astimezone(timezone.utc).isoformat(),
            "raw_response_included": False,
            "identifier_values_included": False,
            "exception_text_included": False,
        }
        evidence["evidence_sha256"] = _canonical_sha256(evidence)
        return evidence


@dataclass(frozen=True)
class Slice3TerminalRoundtripEvidence:
    """Exact restored-baseline proof with no raw private identifiers."""

    plan_sha256: str
    opening_order: Slice3ExactOrderEvidence | None
    close_order: Slice3ExactOrderEvidence | None
    final_position: Slice3PositionObservation
    final_open_orders: Slice3OpenOrderZeroProof
    final_margin: Slice3MarginSummary
    create_action: Slice3ActionTerminalBinding
    cancel_action: Slice3ActionTerminalBinding
    close_action: Slice3ActionTerminalBinding
    read_journal_sha256: str
    completed_at: datetime
    funding_required: bool = False
    funding_applicability: str = "not_applicable_us_cfm"
    source_currency: str = "USD"
    cap_accounting_unit: str = "USDC"
    currency_treatment: str = (
        "operator_defined_usd_usdc_unit_parity_for_existing_v3_caps"
    )

    @staticmethod
    def opening_configuration_sha256(plan: Slice3Plan) -> str:
        return _canonical_sha256(
            dict(plan.create.preview_request()["order_configuration"])
        )

    @staticmethod
    def close_configuration_sha256(size: Decimal) -> str:
        text = format(size.normalize(), "f")
        return _canonical_sha256({"market_market_ioc": {"base_size": text}})

    @classmethod
    def build(
        cls,
        *,
        plan: Slice3Plan,
        opening_order: Slice3ExactOrderEvidence | None,
        close_order: Slice3ExactOrderEvidence | None,
        final_position: Slice3PositionObservation,
        final_open_orders: Slice3OpenOrderZeroProof,
        final_margin: Slice3MarginSummary,
        create_action: Slice3ActionTerminalBinding,
        cancel_action: Slice3ActionTerminalBinding,
        close_action: Slice3ActionTerminalBinding,
        read_journal_sha256: str,
        completed_at: datetime,
    ) -> "Slice3TerminalRoundtripEvidence":
        evidence = cls(
            plan_sha256=plan.plan_sha256,
            opening_order=opening_order,
            close_order=close_order,
            final_position=final_position,
            final_open_orders=final_open_orders,
            final_margin=final_margin,
            create_action=create_action,
            cancel_action=cancel_action,
            close_action=close_action,
            read_journal_sha256=read_journal_sha256,
            completed_at=completed_at,
        )
        evidence.validate(plan, now=completed_at)
        return evidence

    @property
    def total_fees(self) -> Decimal:
        opening = (
            Decimal("0")
            if self.opening_order is None
            else _decimal(
                self.opening_order.total_fees,
                "opening_fee_invalid",
            )
        )
        close = (
            Decimal("0")
            if self.close_order is None
            else _decimal(self.close_order.total_fees, "close_fee_invalid")
        )
        return opening + close

    @property
    def branch_executed_value(self) -> Decimal:
        opening = (
            Decimal("0")
            if self.opening_order is None
            else _decimal(
                self.opening_order.filled_value,
                "opening_value_invalid",
            )
        )
        close = (
            Decimal("0")
            if self.close_order is None
            else _decimal(self.close_order.filled_value, "close_value_invalid")
        )
        return opening + close

    @staticmethod
    def _validate_financial_order(
        evidence: Slice3ExactOrderEvidence,
        *,
        expected_client_order_id: str,
        expected_side: OrderSide,
        expected_configuration_sha256: str,
        identity_reason: str,
    ) -> None:
        order = evidence.observation
        if (
            order.authoritative is not True
            or order.pagination_complete is not True
            or order.product_id != SLICE3_PRODUCT_ID
            or order.client_order_id != expected_client_order_id
            or evidence.side is not expected_side
            or evidence.order_configuration_sha256 != expected_configuration_sha256
            or order.active_order_count != 0
        ):
            raise Slice3TerminalEvidenceError(identity_reason)
        filled = order.filled
        remaining = order.remaining
        filled_value = _decimal(evidence.filled_value, f"{identity_reason}_value")
        fees = _decimal(evidence.total_fees, f"{identity_reason}_fee")
        if (
            filled < 0
            or remaining < 0
            or not isinstance(evidence.number_of_fills, int)
            or isinstance(evidence.number_of_fills, bool)
            or evidence.number_of_fills < 0
            or (filled == 0 and (filled_value != 0 or evidence.number_of_fills != 0))
            or (filled > 0 and (filled_value <= 0 or evidence.number_of_fills <= 0))
            or fees < 0
        ):
            raise Slice3TerminalEvidenceError(f"{identity_reason}_financial_invalid")

    def validate(self, plan: Slice3Plan, *, now: datetime) -> None:
        if self.plan_sha256 != plan.plan_sha256:
            raise Slice3TerminalEvidenceError("terminal_plan_binding_invalid")
        if _SHA256.fullmatch(self.read_journal_sha256) is None:
            raise Slice3TerminalEvidenceError("read_journal_hash_invalid")
        if self.completed_at.tzinfo is None or now.tzinfo is None:
            raise Slice3TerminalEvidenceError("terminal_time_invalid")
        if self.completed_at.astimezone(timezone.utc) > now.astimezone(timezone.utc):
            raise Slice3TerminalEvidenceError("terminal_time_in_future")
        for expected, binding in (
            (Slice3ActionKind.CREATE, self.create_action),
            (Slice3ActionKind.CANCEL, self.cancel_action),
            (Slice3ActionKind.CLOSE, self.close_action),
        ):
            binding.validate()
            if binding.action is not expected:
                raise Slice3TerminalEvidenceError("action_binding_order_invalid")
        if self.create_action.terminal_event != "outcome":
            raise Slice3TerminalEvidenceError("create_action_not_terminal")

        if self.opening_order is None:
            if self.create_action.outcome != "rejected":
                raise Slice3TerminalEvidenceError("opening_order_missing")
            if self.close_order is not None:
                raise Slice3TerminalEvidenceError("unexpected_close_order")
            if not (
                self.cancel_action.terminal_event == "retired_not_required"
                and self.cancel_action.reason_code
                == "cancel_not_required_create_rejected"
                and self.close_action.terminal_event == "retired_not_required"
                and self.close_action.reason_code
                == "close_not_required_create_rejected"
            ):
                raise Slice3TerminalEvidenceError(
                    "create_rejected_action_retirement_invalid"
                )
            filled = Decimal("0")
        else:
            self._validate_financial_order(
                self.opening_order,
                expected_client_order_id=plan.create.client_order_id,
                expected_side=OrderSide.BUY,
                expected_configuration_sha256=(self.opening_configuration_sha256(plan)),
                identity_reason="opening_order_identity_invalid",
            )
            opening = self.opening_order.observation
            filled = opening.filled
            remaining = opening.remaining
            if filled + remaining != Decimal("1") or opening.status not in {
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.EXPIRED,
                OrderStatus.FAILED,
            }:
                raise Slice3TerminalEvidenceError("opening_order_terminal_invalid")

            if filled == 0:
                if self.close_order is not None:
                    raise Slice3TerminalEvidenceError("unexpected_close_order")
                if (
                    self.close_action.terminal_event != "retired_not_required"
                    or self.close_action.reason_code
                    != "close_not_required_zero_exposure"
                ):
                    raise Slice3TerminalEvidenceError("close_action_not_retired")
            else:
                if self.close_order is None:
                    raise Slice3TerminalEvidenceError("close_order_missing")
                if self.close_action.terminal_event != "outcome":
                    raise Slice3TerminalEvidenceError("close_action_not_terminal")
                self._validate_financial_order(
                    self.close_order,
                    expected_client_order_id=plan.close_client_order_id,
                    expected_side=OrderSide.SELL,
                    expected_configuration_sha256=(
                        self.close_configuration_sha256(filled)
                    ),
                    identity_reason="close_order_identity_invalid",
                )
                close = self.close_order.observation
                if (
                    close.status is not OrderStatus.FILLED
                    or close.filled != filled
                    or close.remaining != 0
                ):
                    raise Slice3TerminalEvidenceError("close_order_size_invalid")

            if opening.status is OrderStatus.FILLED:
                if (
                    self.cancel_action.terminal_event != "retired_not_required"
                    or self.cancel_action.reason_code
                    != "cancel_not_required_filled_branch"
                ):
                    raise Slice3TerminalEvidenceError("cancel_action_not_retired")
            elif self.cancel_action.terminal_event == "retired_not_required":
                if self.cancel_action.reason_code != (
                    "cancel_not_required_terminal_branch"
                ):
                    raise Slice3TerminalEvidenceError("cancel_action_not_retired")
            elif self.cancel_action.terminal_event != "outcome":
                raise Slice3TerminalEvidenceError("cancel_action_not_terminal")

        try:
            self.final_position.validate(plan, now=now)
        except Exception as exc:
            raise Slice3TerminalEvidenceError("final_position_invalid") from exc
        if not (
            self.final_position.side is AdminFuturesPositionSide.FLAT
            and self.final_position.contract_delta == plan.baseline_position_contracts
        ):
            raise Slice3TerminalEvidenceError("final_position_not_flat")

        open_zero = self.final_open_orders
        if not (
            open_zero.authoritative is True
            and open_zero.pagination_complete is True
            and open_zero.scope == "exact_product_active_transitional_orders"
            and open_zero.product_id == SLICE3_PRODUCT_ID
            and open_zero.exact_product_active_order_count == 0
            and _SHA256.fullmatch(open_zero.snapshot_sha256) is not None
        ):
            raise Slice3TerminalEvidenceError("final_open_orders_invalid")
        _fresh(open_zero.observed_at, now, "final_open_orders_stale")

        margin = self.final_margin
        if not (
            margin.status == "ready"
            and margin.account_family == "coinbase_futures_us_cfm"
            and margin.retail_regular_margin_window == "MARGIN_WINDOW_TYPE_UNSPECIFIED"
            and margin.retail_intraday_margin_window == "MARGIN_WINDOW_TYPE_INTRADAY"
            and _SHA256.fullmatch(margin.snapshot_sha256) is not None
        ):
            raise Slice3TerminalEvidenceError("final_margin_invalid")
        _fresh(margin.observed_at, now, "margin_stale")
        for value in (
            margin.available_margin_usdc,
            margin.total_usd_balance_usdc,
            margin.initial_margin_usdc,
            margin.liquidation_threshold_usdc,
        ):
            _decimal(value, "final_margin_value_invalid")

        if not (
            self.funding_required is False
            and self.funding_applicability == "not_applicable_us_cfm"
            and self.source_currency == "USD"
            and self.cap_accounting_unit == "USDC"
            and self.currency_treatment
            == "operator_defined_usd_usdc_unit_parity_for_existing_v3_caps"
        ):
            raise Slice3TerminalEvidenceError("funding_binding_invalid")

        opening_value = (
            Decimal("0")
            if self.opening_order is None
            else _decimal(
                self.opening_order.filled_value,
                "opening_value_invalid",
            )
        )
        close_value = (
            Decimal("0")
            if self.close_order is None
            else _decimal(self.close_order.filled_value, "close_value_invalid")
        )
        close_fee = (
            Decimal("0")
            if self.close_order is None
            else _decimal(self.close_order.total_fees, "close_fee_invalid")
        )
        if opening_value >= SLICE3_OPENING_CAP_USDC:
            raise Slice3TerminalEvidenceError("terminal_opening_cap_invalid")
        if close_value + close_fee >= SLICE3_EXPOSURE_CAP_USDC:
            raise Slice3TerminalEvidenceError("terminal_close_cap_invalid")
        if self.branch_executed_value + self.total_fees >= SLICE3_TURNOVER_CAP_USDC:
            raise Slice3TerminalEvidenceError("terminal_turnover_cap_invalid")

    def sanitized_evidence(self) -> dict[str, object]:
        evidence: dict[str, object] = {
            "schema_version": "slice3-terminal-roundtrip-evidence-v2",
            "status": "restored_baseline",
            "plan_sha256": self.plan_sha256,
            "opening_order": (
                None
                if self.opening_order is None
                else self.opening_order.sanitized_evidence()
            ),
            "close_order": (
                None
                if self.close_order is None
                else self.close_order.sanitized_evidence()
            ),
            "actions": {
                "create": self.create_action.sanitized_evidence(),
                "cancel": self.cancel_action.sanitized_evidence(),
                "close": self.close_action.sanitized_evidence(),
            },
            "final_position": self.final_position.sanitized_evidence(),
            "final_open_orders": self.final_open_orders.sanitized_evidence(),
            "final_margin": self.final_margin.sanitized_evidence(),
            "total_fees": format(self.total_fees, "f"),
            "branch_executed_value": format(
                self.branch_executed_value,
                "f",
            ),
            "funding_required": self.funding_required,
            "funding_applicability": self.funding_applicability,
            "source_currency": self.source_currency,
            "cap_accounting_unit": self.cap_accounting_unit,
            "currency_treatment": self.currency_treatment,
            "read_journal_sha256": self.read_journal_sha256,
            "completed_at": self.completed_at.astimezone(timezone.utc).isoformat(),
            "raw_response_included": False,
            "identifier_values_included": False,
        }
        evidence["evidence_sha256"] = _canonical_sha256(evidence)
        return evidence


__all__ = [
    "Slice3ActionTerminalBinding",
    "Slice3HaltedReconciliationEvidence",
    "Slice3TerminalEvidenceError",
    "Slice3TerminalRoundtripEvidence",
]
