"""Default-profile Futures full-fill follow-up activation.

This domain module owns the Goal 5 control plane and the one-contract,
opposite-side candidate policy.  It does not accept order terms from the
browser.  Coinbase invocation is delegated to the existing durable Futures
Preview/Create/reconciliation/Cancel lifecycle after PostgreSQL proves an
enabled attached intent and an authoritative full fill.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re
from typing import Any, Callable, Protocol

from core.enums import (
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)

from .futures_order_preview_r12 import (
    validate_r12_margin_collateral_evidence,
)
from .futures_portfolio_binding import (
    evaluate_futures_default_portfolio_binding,
)
from .operator_futures_follow_up_intent import (
    FuturesFollowUpIntentRecord,
)
from .operator_futures_manual_lifecycle import (
    FuturesManualEligibilityResult,
    FuturesManualGoalRecord,
    FuturesManualRequestContext,
)
from .operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS,
    FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES,
    FuturesProductPolicySelection,
    _canonical_sha256,
    _decimal_text,
    _margin_rate,
    _margin_validation_diagnostic,
    _mapping,
    _money_text,
    _nonnegative_decimal,
    _parse_timestamp,
    _positive_decimal,
    _read_diagnostic,
    _sha256_text,
    _timestamp,
    _top_of_book,
)


FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID = (
    "operator_futures_fill_triggered_follow_up_activation_v1"
)
FUTURES_FILL_TRIGGERED_OPERATOR_INTENT = (
    "control_futures_fill_triggered_follow_up"
)
FUTURES_FILL_TRIGGERED_REFRESH_INTENT = (
    "refresh_one_futures_fill_triggered_follow_up_eligibility_cycle"
)
FUTURES_FILL_TRIGGERED_EXECUTE_INTENT = (
    "preview_submit_and_safe_closeout_one_futures_fill_triggered_follow_up"
)
FUTURES_FILL_TRIGGERED_CAPS = {
    "opening_usdc": "100",
    "exposure_usdc": "150",
    "turnover_usdc": "300",
    "comparison": "strictly_less_than",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OPENING_CAP = Decimal("100")
_EXPOSURE_CAP = Decimal("150")
_TURNOVER_CAP = Decimal("300")
_CLOSE_BUFFER = Decimal("1.20")


class FuturesFillTriggeredControlState(str, Enum):
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"
    PAUSED = "PAUSED"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"


class FuturesFillTriggeredTriggerState(str, Enum):
    UNCLAIMED = "UNCLAIMED"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"

    @property
    def terminal(self) -> bool:
        return self in {
            FuturesFillTriggeredTriggerState.COMPLETED,
            FuturesFillTriggeredTriggerState.BLOCKED,
            FuturesFillTriggeredTriggerState.UNKNOWN,
        }


class FuturesFillTriggeredControlAction(str, Enum):
    ENABLE = "ENABLE"
    DISABLE = "DISABLE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    DRAIN = "DRAIN"


@dataclass(frozen=True, slots=True)
class FuturesFillTriggeredActivationRecord:
    goal_id: str
    source_client_order_id: str
    follow_up_intent_id: str
    control_state: FuturesFillTriggeredControlState
    trigger_state: FuturesFillTriggeredTriggerState
    revision: int
    delegated_live_authority: bool
    trigger_claim_id: str | None
    trigger_evidence_sha256: str | None
    lifecycle_revision: int
    child_client_order_id: str | None
    preview_outcome: str
    create_outcome: str
    reconciliation_outcome: str
    cancel_outcome: str
    diagnostic_code: str
    actor_id: str
    roles: tuple[str, ...]
    correlation_id: str
    audit_id: str
    recorded_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class FuturesFillTriggeredRequestContext:
    actor_id: str
    roles: tuple[str, ...]
    expected_revision: int
    idempotency_key: str
    correlation_id: str
    audit_id: str
    operator_intent: str


class FuturesFillTriggeredRepository(Protocol):
    def read(
        self, source_client_order_id: str
    ) -> FuturesFillTriggeredActivationRecord: ...

    def transition_control(self, **kwargs: Any) -> (
        FuturesFillTriggeredActivationRecord
    ): ...

    def claim_full_fill_trigger(
        self, *, source_client_order_id: str
    ) -> FuturesFillTriggeredActivationRecord | None: ...

    def finalize_trigger(self, **kwargs: Any) -> (
        FuturesFillTriggeredActivationRecord
    ): ...


def _position_binding(
    positions: Any,
    *,
    product_id: str,
) -> tuple[Decimal, str]:
    if isinstance(positions, Mapping):
        if product_id in positions:
            rows = [positions[product_id]]
        elif isinstance(positions.get("positions"), list):
            rows = list(positions["positions"])
        else:
            rows = list(positions.values())
    elif isinstance(positions, Sequence) and not isinstance(
        positions, (str, bytes, bytearray)
    ):
        rows = list(positions)
    else:
        rows = []
    matching: list[tuple[Decimal, str]] = []
    for raw in rows:
        row = _mapping(raw)
        observed_product = str(
            row.get("product_id")
            or getattr(raw, "product_id", "")
            or ""
        ).strip()
        if observed_product != product_id:
            continue
        raw_count = (
            row.get("number_of_contracts")
            if "number_of_contracts" in row
            else getattr(raw, "number_of_contracts", None)
        )
        count = _nonnegative_decimal(
            raw_count,
            "operator_futures_fill_triggered_position_binding_invalid",
        )
        side = str(
            row.get("position_side")
            or row.get("side")
            or getattr(raw, "position_side", "")
            or getattr(raw, "side", "")
            or ""
        ).strip().upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError(
                "operator_futures_fill_triggered_position_binding_invalid"
            )
        matching.append((count, side))
    if len(matching) != 1:
        raise ValueError(
            "operator_futures_fill_triggered_position_binding_invalid"
        )
    return matching[0]


def build_futures_follow_up_candidate(
    *,
    intent: FuturesFollowUpIntentRecord,
    selection: FuturesProductPolicySelection,
    product: Mapping[str, Any],
    book: Mapping[str, Any],
    positions: Any,
    available_margin_usdc: Any,
    observed_at: datetime,
    trigger_evidence_sha256: str,
) -> dict[str, str]:
    """Derive one passive opposite-side contract from fresh bound evidence."""

    if (
        not isinstance(intent, FuturesFollowUpIntentRecord)
        or intent.state != "ATTACHED"
        or intent.contract_count != "1"
        or intent.source_client_order_id != intent.root_client_order_id
        or intent.source_side not in {"BUY", "SELL"}
        or intent.derived_follow_up_side
        != ("SELL" if intent.source_side == "BUY" else "BUY")
        or not _SHA256_RE.fullmatch(trigger_evidence_sha256)
    ):
        raise ValueError(
            "operator_futures_fill_triggered_intent_binding_invalid"
        )
    if (
        selection.lifecycle != "ENABLED"
        or selection.product_id != intent.product_id
        or selection.product_id
        not in FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS
        or selection.policy_revision < 1
        or _SHA256_RE.fullmatch(selection.policy_sha256) is None
    ):
        raise ValueError(
            "operator_futures_fill_triggered_selection_invalid"
        )
    product_id = selection.product_id
    if (
        str(product.get("product_id") or "") != product_id
        or str(product.get("product_type") or "").upper() != "FUTURE"
        or str(product.get("status") or "").upper() not in {"", "ONLINE"}
        or any(
            product.get(field) is not False
            for field in ("trading_disabled", "view_only", "cancel_only")
        )
    ):
        raise ValueError(
            "operator_futures_fill_triggered_product_untradable"
        )
    session = _mapping(product.get("fcm_trading_session_details"))
    if (
        session.get("is_session_open") is not True
        or session.get("after_hours_order_entry_disabled")
        not in {True, False}
    ):
        raise ValueError(
            "operator_futures_fill_triggered_session_ineligible"
        )
    details = _mapping(product.get("future_product_details"))
    contract_code = str(details.get("contract_code") or "").strip().upper()
    if (
        contract_code != product_id.split("-", 1)[0]
        or str(details.get("venue") or "").strip().lower() != "cde"
        or str(details.get("risk_managed_by") or "").strip().upper()
        != "MANAGED_BY_FCM"
    ):
        raise ValueError(
            "operator_futures_fill_triggered_cfm_identity_invalid"
        )
    expiry = _parse_timestamp(
        details.get("contract_expiry"),
        "operator_futures_fill_triggered_expiry_invalid",
    )
    if expiry <= observed_at.astimezone(timezone.utc):
        raise ValueError(
            "operator_futures_fill_triggered_contract_expired"
        )
    expiry_type = str(
        details.get("contract_expiry_type") or ""
    ).strip().upper()
    if expiry_type not in {"EXPIRING", "PERPETUAL"}:
        raise ValueError(
            "operator_futures_fill_triggered_expiry_type_invalid"
        )
    contract_size = _positive_decimal(
        details.get("contract_size"),
        "operator_futures_fill_triggered_contract_size_invalid",
    )
    product_price = _positive_decimal(
        product.get("price"),
        "operator_futures_fill_triggered_product_price_invalid",
    )
    price_increment = _positive_decimal(
        product.get("price_increment"),
        "operator_futures_fill_triggered_price_increment_invalid",
    )
    base_increment = _positive_decimal(
        product.get("base_increment"),
        "operator_futures_fill_triggered_base_increment_invalid",
    )
    base_minimum = _nonnegative_decimal(
        product.get("base_min_size"),
        "operator_futures_fill_triggered_base_minimum_invalid",
    )
    if Decimal("1") < base_minimum or Decimal("1") % base_increment != 0:
        raise ValueError(
            "operator_futures_fill_triggered_one_contract_invalid"
        )
    intraday_rate = _margin_rate(
        details, field="intraday_margin_rate"
    )
    overnight_rate = _margin_rate(
        details, field="overnight_margin_rate"
    )
    worst_case_rate = max(intraday_rate, overnight_rate)
    best_bid, best_ask = _top_of_book(
        book=book,
        product_id=product_id,
        observed_at=observed_at,
    )
    if best_bid >= best_ask:
        raise ValueError(
            "operator_futures_fill_triggered_book_invalid"
        )
    side = intent.derived_follow_up_side
    limit_price = (
        best_ask + price_increment
        if side == "SELL"
        else best_bid - price_increment
    )
    if limit_price <= 0 or limit_price % price_increment != 0:
        raise ValueError(
            "operator_futures_fill_triggered_limit_price_invalid"
        )
    position_count, position_side = _position_binding(
        positions, product_id=product_id
    )
    required_position_side = "LONG" if side == "SELL" else "SHORT"
    if (
        position_count != Decimal("1")
        or position_side != required_position_side
    ):
        raise ValueError(
            "operator_futures_fill_triggered_position_binding_invalid"
        )
    reference_price = max(product_price, best_ask, limit_price)
    opening = reference_price * contract_size
    exposure = opening
    buffered_close = exposure * _CLOSE_BUFFER
    turnover = opening + buffered_close
    required_margin = opening * worst_case_rate
    available_margin = _positive_decimal(
        available_margin_usdc,
        "operator_futures_fill_triggered_available_margin_invalid",
    )
    if (
        opening >= _OPENING_CAP
        or exposure >= _EXPOSURE_CAP
        or buffered_close >= _EXPOSURE_CAP
        or turnover >= _TURNOVER_CAP
    ):
        raise ValueError(
            "operator_futures_fill_triggered_cap_ineligible"
        )
    if available_margin < required_margin:
        raise ValueError(
            "operator_futures_fill_triggered_margin_insufficient"
        )
    return {
        "product_id": product_id,
        "side": side,
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "contract_code": contract_code,
        "contract_size": _decimal_text(contract_size),
        "contract_expiry": _timestamp(expiry),
        "contract_expiry_type": expiry_type,
        "venue": "cde",
        "risk_managed_by": "MANAGED_BY_FCM",
        "product_price": _decimal_text(product_price),
        "reference_price": _decimal_text(reference_price),
        "reference_price_source": (
            "max_product_price_fresh_best_ask_and_passive_limit"
        ),
        "price_increment": _decimal_text(price_increment),
        "base_increment": _decimal_text(base_increment),
        "base_min_size": _decimal_text(base_minimum),
        "best_bid": _decimal_text(best_bid),
        "best_ask": _decimal_text(best_ask),
        "limit_price": _decimal_text(limit_price),
        "position_side": position_side,
        "position_contract_count": "1",
        "intraday_margin_rate": _decimal_text(intraday_rate),
        "overnight_margin_rate": _decimal_text(overnight_rate),
        "worst_case_margin_rate": _decimal_text(worst_case_rate),
        "required_margin_reference_usdc": _money_text(required_margin),
        "opening_reference_notional_usdc": _money_text(opening),
        "maximum_exposure_reference_notional_usdc": _money_text(exposure),
        "buffered_close_reference_notional_usdc": _money_text(
            buffered_close
        ),
        "branch_turnover_reference_notional_usdc": _money_text(turnover),
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "close_buffer_multiplier": "1.20",
        "product_policy_revision": str(selection.policy_revision),
        "product_policy_sha256": selection.policy_sha256,
        "source_client_order_id": intent.source_client_order_id,
        "root_client_order_id": intent.root_client_order_id,
        "follow_up_intent_id": intent.follow_up_intent_id,
        "trigger_evidence_sha256": trigger_evidence_sha256,
        "observed_at": _timestamp(observed_at),
    }


def _blocked_eligibility(
    *,
    intent: FuturesFollowUpIntentRecord | None,
    selection: FuturesProductPolicySelection | None,
    outcome: AdminFuturesManualEligibilityOutcome,
    diagnostic_code: str,
    attempts: Mapping[str, int],
) -> FuturesManualEligibilityResult:
    public = {
        "goal_id": FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
        "profile_alias": "Default",
        "product_id": (
            intent.product_id
            if intent is not None
            else selection.product_id
            if selection is not None
            else None
        ),
        "source_client_order_id": (
            intent.source_client_order_id
            if intent is not None
            else None
        ),
        "contract_count": "1",
        "caps": FUTURES_FILL_TRIGGERED_CAPS,
        "exact_v3_eligible": False,
        "diagnostic_code": diagnostic_code,
        "category_attempts": dict(attempts),
        "raw_responses_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }
    return FuturesManualEligibilityResult(
        outcome=outcome,
        diagnostic_code=diagnostic_code,
        category_attempts=dict(attempts),
        candidate=None,
        portfolio_id_sha256=None,
        evidence_sha256=_canonical_sha256(public),
        public_evidence=public,
    )


class FuturesFillTriggeredEligibilityReader:
    """Run one six-category Default-profile eligibility cycle."""

    def __init__(
        self,
        *,
        rest_client: Any,
        selection_reader: Callable[[], FuturesProductPolicySelection],
        intent_reader: Callable[[], FuturesFollowUpIntentRecord],
        trigger_evidence_reader: Callable[[], str],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.rest_client = rest_client
        self.selection_reader = selection_reader
        self.intent_reader = intent_reader
        self.trigger_evidence_reader = trigger_evidence_reader
        self.now = now or (lambda: datetime.now(timezone.utc))

    def run(
        self, *, before_category: Callable[[str], None]
    ) -> FuturesManualEligibilityResult:
        attempts = {
            category: 0
            for category in FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES
        }
        try:
            intent = self.intent_reader()
            selection = self.selection_reader()
            trigger_evidence = self.trigger_evidence_reader()
            if (
                intent.product_id != selection.product_id
                or not _SHA256_RE.fullmatch(trigger_evidence)
            ):
                raise ValueError
        except Exception:
            return _blocked_eligibility(
                intent=None,
                selection=None,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=(
                    "operator_futures_fill_triggered_binding_unavailable"
                ),
                attempts=attempts,
            )

        def read(category: str, call: Callable[[], Any]) -> Any:
            if attempts[category] != 0:
                raise RuntimeError(
                    "operator_futures_fill_triggered_duplicate_category_read"
                )
            try:
                before_category(category)
                attempts[category] = 1
                return call()
            except Exception as exc:
                raise RuntimeError(
                    _read_diagnostic(category, exc).replace(
                        "operator_futures_product_ticket_",
                        "operator_futures_fill_triggered_",
                        1,
                    )
                ) from None

        try:
            permissions = read(
                "api_key_permissions",
                self.rest_client.get_api_key_permissions,
            )
            portfolios = read(
                "portfolio_catalog",
                self.rest_client
                .get_futures_preview_eligibility_portfolios,
            )
            product = read(
                "product",
                lambda: self.rest_client
                .get_futures_manual_eligibility_product(
                    intent.product_id
                ),
            )
            book = read(
                "best_bid_ask",
                lambda: self.rest_client.get_best_bid_ask(
                    product_ids=[intent.product_id]
                ),
            )
            observed_at = self.now()
            positions = read(
                "futures_positions",
                self.rest_client.get_futures_positions,
            )
            margin = read(
                "futures_margin_collateral",
                self.rest_client
                .get_futures_manual_eligibility_margin_collateral_snapshot,
            )
        except RuntimeError as exc:
            return _blocked_eligibility(
                intent=intent,
                selection=selection,
                outcome=AdminFuturesManualEligibilityOutcome.UNKNOWN,
                diagnostic_code=str(exc.args[0]),
                attempts=attempts,
            )
        try:
            binding = evaluate_futures_default_portfolio_binding(
                permissions=permissions,
                portfolios=portfolios,
                observed_at=_timestamp(observed_at),
                permissions_read=True,
                portfolio_catalog_read=True,
            )
            if (
                not binding.read_ready
                or binding.can_view is not True
                or binding.can_trade is not True
                or not binding.observed_portfolio_id
            ):
                raise ValueError
        except Exception:
            return _blocked_eligibility(
                intent=intent,
                selection=selection,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=(
                    "operator_futures_fill_triggered_portfolio_ineligible"
                ),
                attempts=attempts,
            )
        try:
            available_margin = validate_r12_margin_collateral_evidence(
                margin
            )
        except Exception as exc:
            diagnostic = _margin_validation_diagnostic(exc, margin).replace(
                "operator_futures_product_ticket_",
                "operator_futures_fill_triggered_",
                1,
            )
            return _blocked_eligibility(
                intent=intent,
                selection=selection,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=diagnostic,
                attempts=attempts,
            )
        try:
            candidate = build_futures_follow_up_candidate(
                intent=intent,
                selection=selection,
                product=product if isinstance(product, Mapping) else {},
                book=book if isinstance(book, Mapping) else {},
                positions=positions,
                available_margin_usdc=available_margin,
                observed_at=observed_at,
                trigger_evidence_sha256=trigger_evidence,
            )
        except ValueError as exc:
            code = str(exc.args[0]) if len(exc.args) == 1 else ""
            if not code.startswith("operator_futures_fill_triggered_"):
                code = (
                    "operator_futures_fill_triggered_candidate_ineligible"
                )
            return _blocked_eligibility(
                intent=intent,
                selection=selection,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=code,
                attempts=attempts,
            )
        portfolio_hash = _sha256_text(binding.observed_portfolio_id)
        public = {
            "goal_id": FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
            "profile_alias": "Default",
            "portfolio_type": "DEFAULT",
            "portfolio_id_sha256": portfolio_hash,
            "credential_can_view": True,
            "credential_can_trade": True,
            "selection_authority": (
                "backend_enabled_futures_product_policy"
            ),
            "product_id": intent.product_id,
            "source_client_order_id": intent.source_client_order_id,
            "follow_up_intent_id": intent.follow_up_intent_id,
            "trigger_evidence_sha256": trigger_evidence,
            "contract_count": "1",
            "product_policy_revision": selection.policy_revision,
            "product_policy_sha256": selection.policy_sha256,
            "caps": FUTURES_FILL_TRIGGERED_CAPS,
            "candidate": candidate,
            "exact_v3_eligible": True,
            "diagnostic_code": (
                "operator_futures_fill_triggered_eligible"
            ),
            "category_attempts": dict(attempts),
            "raw_responses_included": False,
            "private_identifiers_included": False,
            "exception_text_included": False,
        }
        return FuturesManualEligibilityResult(
            outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
            diagnostic_code="operator_futures_fill_triggered_eligible",
            category_attempts=dict(attempts),
            candidate=candidate,
            portfolio_id_sha256=portfolio_hash,
            evidence_sha256=_canonical_sha256(public),
            public_evidence=public,
        )


def validate_futures_fill_triggered_eligibility_evidence(
    result: FuturesManualEligibilityResult,
) -> None:
    if result.outcome is not AdminFuturesManualEligibilityOutcome.ELIGIBLE:
        return
    public = result.public_evidence
    candidate = result.candidate
    if (
        candidate is None
        or public.get("goal_id")
        != FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID
        or public.get("profile_alias") != "Default"
        or public.get("portfolio_type") != "DEFAULT"
        or public.get("portfolio_id_sha256")
        != result.portfolio_id_sha256
        or public.get("credential_can_view") is not True
        or public.get("credential_can_trade") is not True
        or public.get("caps") != FUTURES_FILL_TRIGGERED_CAPS
        or public.get("candidate") != candidate
        or candidate.get("side") not in {"BUY", "SELL"}
        or candidate.get("contract_count") != "1"
        or candidate.get("source_client_order_id")
        != public.get("source_client_order_id")
        or candidate.get("follow_up_intent_id")
        != public.get("follow_up_intent_id")
        or candidate.get("trigger_evidence_sha256")
        != public.get("trigger_evidence_sha256")
        or public.get("exact_v3_eligible") is not True
        or public.get("diagnostic_code")
        != "operator_futures_fill_triggered_eligible"
    ):
        raise ValueError(
            "operator_futures_fill_triggered_eligible_evidence_invalid"
        )


class FuturesFillTriggeredExecutionCoordinator:
    """Bind one trigger claim to the existing single-use Futures lifecycle."""

    def __init__(self, *, ticket_service: Any) -> None:
        self.ticket_service = ticket_service

    def execute(
        self,
        activation: FuturesFillTriggeredActivationRecord,
    ) -> FuturesManualGoalRecord:
        claim_id = str(activation.trigger_claim_id or "")
        if (
            activation.trigger_state
            is not FuturesFillTriggeredTriggerState.CLAIMED
            or not claim_id
            or not activation.delegated_live_authority
        ):
            raise ValueError(
                "operator_futures_fill_triggered_claim_invalid"
            )
        lifecycle = self.ticket_service.read().lifecycle
        refresh_context = FuturesManualRequestContext(
            actor_id=activation.actor_id,
            roles=activation.roles,
            expected_revision=lifecycle.revision,
            idempotency_key=f"{claim_id}:eligibility",
            correlation_id=f"{claim_id}:eligibility",
            audit_id=activation.audit_id,
            operator_intent=FUTURES_FILL_TRIGGERED_REFRESH_INTENT,
            authorize_one_no_retry_six_category_cycle=True,
            acknowledge_cycle_is_goal_global_and_limited_to_ten=True,
            acknowledge_unsuccessful_or_unknown_cycle_fails_closed=True,
        )
        refreshed = self.ticket_service.refresh(
            context=refresh_context
        ).lifecycle
        if (
            refreshed.eligibility_outcome
            is not AdminFuturesManualEligibilityOutcome.ELIGIBLE
        ):
            return refreshed
        execute_context = FuturesManualRequestContext(
            actor_id=activation.actor_id,
            roles=activation.roles,
            expected_revision=refreshed.revision,
            idempotency_key=f"{claim_id}:execute",
            correlation_id=f"{claim_id}:execute",
            audit_id=activation.audit_id,
            operator_intent=FUTURES_FILL_TRIGGERED_EXECUTE_INTENT,
            authorize_preview_create_and_safe_closeout=True,
            acknowledge_unknown_outcome_consumes_allowance=True,
            acknowledge_create_requires_accepted_identical_preview=True,
            acknowledge_cancel_is_only_for_exact_nonterminal_child=True,
        )
        return self.ticket_service.execute(
            context=execute_context
        ).lifecycle


def _terminal_projection(
    lifecycle: FuturesManualGoalRecord,
) -> tuple[FuturesFillTriggeredTriggerState, str]:
    if any(
        outcome is AdminFuturesManualCallOutcome.UNKNOWN
        for outcome in (
            lifecycle.preview_outcome,
            lifecycle.create_outcome,
            lifecycle.reconciliation_outcome,
            lifecycle.cancel_outcome,
        )
    ):
        return (
            FuturesFillTriggeredTriggerState.UNKNOWN,
            "operator_futures_fill_triggered_outcome_unknown",
        )
    if (
        lifecycle.create_outcome
        is AdminFuturesManualCallOutcome.ACCEPTED
    ):
        return (
            FuturesFillTriggeredTriggerState.COMPLETED,
            "operator_futures_fill_triggered_child_created",
        )
    return (
        FuturesFillTriggeredTriggerState.BLOCKED,
        lifecycle.diagnostic_code
        or "operator_futures_fill_triggered_blocked",
    )


class FuturesFillTriggeredFollowUpService:
    """Expose local controls and dispatch exactly one full-fill trigger."""

    def __init__(
        self,
        *,
        repository: FuturesFillTriggeredRepository,
        coordinator: FuturesFillTriggeredExecutionCoordinator | None,
    ) -> None:
        self.repository = repository
        self.coordinator = coordinator

    def read(
        self, source_client_order_id: str
    ) -> FuturesFillTriggeredActivationRecord:
        return self.repository.read(source_client_order_id)

    def control(
        self,
        *,
        source_client_order_id: str,
        action: FuturesFillTriggeredControlAction,
        context: FuturesFillTriggeredRequestContext,
        authorize_one_preview_create_and_safe_closeout: bool = False,
        acknowledge_unknown_outcome_consumes_allowance: bool = False,
        acknowledge_child_terms_are_backend_derived: bool = False,
    ) -> FuturesFillTriggeredActivationRecord:
        if (
            context.operator_intent
            != FUTURES_FILL_TRIGGERED_OPERATOR_INTENT
        ):
            raise ValueError(
                "operator_futures_fill_triggered_operator_intent_invalid"
            )
        requires_authority = action in {
            FuturesFillTriggeredControlAction.ENABLE,
            FuturesFillTriggeredControlAction.RESUME,
        }
        if requires_authority and not (
            authorize_one_preview_create_and_safe_closeout
            and acknowledge_unknown_outcome_consumes_allowance
            and acknowledge_child_terms_are_backend_derived
        ):
            raise ValueError(
                "operator_futures_fill_triggered_confirmation_required"
            )
        return self.repository.transition_control(
            source_client_order_id=source_client_order_id,
            action=action,
            expected_revision=context.expected_revision,
            authorize_one_preview_create_and_safe_closeout=(
                authorize_one_preview_create_and_safe_closeout
            ),
            acknowledge_unknown_outcome_consumes_allowance=(
                acknowledge_unknown_outcome_consumes_allowance
            ),
            acknowledge_child_terms_are_backend_derived=(
                acknowledge_child_terms_are_backend_derived
            ),
            idempotency_key=context.idempotency_key,
            actor_id=context.actor_id,
            roles=context.roles,
            correlation_id=context.correlation_id,
            audit_id=context.audit_id,
        )

    def on_source_reconciled(
        self, source_client_order_id: str
    ) -> FuturesFillTriggeredActivationRecord | None:
        claimed = self.repository.claim_full_fill_trigger(
            source_client_order_id=source_client_order_id
        )
        if claimed is None:
            return None
        if self.coordinator is None:
            return self.repository.finalize_trigger(
                source_client_order_id=source_client_order_id,
                trigger_claim_id=claimed.trigger_claim_id,
                trigger_state=FuturesFillTriggeredTriggerState.BLOCKED,
                lifecycle=None,
                diagnostic_code=(
                    "operator_futures_fill_triggered_runtime_unavailable"
                ),
            )
        try:
            lifecycle = self.coordinator.execute(claimed)
            trigger_state, diagnostic = _terminal_projection(lifecycle)
        except Exception:
            lifecycle = None
            trigger_state = FuturesFillTriggeredTriggerState.UNKNOWN
            diagnostic = (
                "operator_futures_fill_triggered_coordination_unknown"
            )
        return self.repository.finalize_trigger(
            source_client_order_id=source_client_order_id,
            trigger_claim_id=claimed.trigger_claim_id,
            trigger_state=trigger_state,
            lifecycle=lifecycle,
            diagnostic_code=diagnostic,
        )


__all__ = [
    "FUTURES_FILL_TRIGGERED_EXECUTE_INTENT",
    "FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID",
    "FUTURES_FILL_TRIGGERED_OPERATOR_INTENT",
    "FUTURES_FILL_TRIGGERED_REFRESH_INTENT",
    "FuturesFillTriggeredActivationRecord",
    "FuturesFillTriggeredControlAction",
    "FuturesFillTriggeredControlState",
    "FuturesFillTriggeredEligibilityReader",
    "FuturesFillTriggeredExecutionCoordinator",
    "FuturesFillTriggeredFollowUpService",
    "FuturesFillTriggeredRequestContext",
    "FuturesFillTriggeredTriggerState",
    "build_futures_follow_up_candidate",
    "validate_futures_fill_triggered_eligibility_evidence",
]
