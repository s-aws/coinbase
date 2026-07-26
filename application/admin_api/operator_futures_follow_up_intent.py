"""Backend-owned attachment of one Futures follow-up intent.

This module is deliberately local-only.  It derives a fixed opposite-side,
one-contract intent from a durable Default-profile Futures order projection.
It never refreshes Coinbase, invokes an exchange adapter, or creates a child.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Mapping, Protocol

from .operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS,
)


FUTURES_FOLLOW_UP_INTENT_GOAL_ID = (
    "operator_futures_follow_up_intent_attachment_v1"
)
FUTURES_FOLLOW_UP_OPERATOR_INTENT = "attach_futures_follow_up_intent"
FUTURES_FOLLOW_UP_REASON_CODE = "FULL_FILL_OPPOSITE_ONE_CONTRACT"
FUTURES_FOLLOW_UP_CONTRACT_COUNT = "1"
FUTURES_FOLLOW_UP_ALLOWED_STATUS = "OPEN"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class FuturesFollowUpIntentRequestContext:
    actor_id: str
    roles: tuple[str, ...]
    idempotency_key: str
    correlation_id: str
    audit_id: str
    operator_intent: str
    reason_code: str
    acknowledge_future_materialization_requires_fresh_authorization: bool
    acknowledge_no_coinbase_call_or_child_creation: bool


@dataclass(frozen=True, slots=True)
class FuturesFollowUpIntentEligibility:
    eligible: bool
    blockers: tuple[str, ...]
    source_found: bool
    source_product_configured: bool
    source_status_open: bool
    source_authoritatively_nonterminal: bool
    source_exactly_one_contract: bool
    source_side_valid: bool
    follow_up_intent_absent: bool
    product_id: str | None
    source_side: str | None
    derived_follow_up_side: str | None
    contract_count: str | None
    source_status: str | None
    source_observed_at: str | None
    source_evidence_sha256: str | None


@dataclass(frozen=True, slots=True)
class FuturesFollowUpIntentRecord:
    goal_id: str
    follow_up_intent_id: str
    source_client_order_id: str
    root_client_order_id: str
    product_id: str
    source_side: str
    derived_follow_up_side: str
    contract_count: str
    state: str
    source_status_at_attach: str
    source_observed_at: str
    source_evidence_sha256: str
    reason_code: str
    correlation_id: str
    audit_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class FuturesFollowUpIntentReadback:
    goal_id: str
    source_client_order_id: str
    eligibility: FuturesFollowUpIntentEligibility
    follow_up_intent: FuturesFollowUpIntentRecord | None
    coinbase_calls: int = 0
    child_created: bool = False
    raw_responses_included: bool = False
    private_identifiers_included: bool = False
    exception_text_included: bool = False


class FuturesFollowUpIntentRepository(Protocol):
    def read(
        self,
        source_client_order_id: str,
    ) -> tuple[dict[str, Any] | None, FuturesFollowUpIntentRecord | None]: ...

    def attach(
        self,
        *,
        context: FuturesFollowUpIntentRequestContext,
        source_client_order_id: str,
        expected_source_observed_at: str,
        expected_source_evidence_sha256: str,
    ) -> tuple[FuturesFollowUpIntentRecord, bool]: ...


def futures_follow_up_source_evidence_sha256(
    projection: Mapping[str, Any],
) -> str:
    """Hash only the fixed source fields required by the attachment policy."""

    payload = {
        "client_order_id": str(
            projection.get("client_order_id") or ""
        ).strip(),
        "product_id": str(projection.get("product_id") or "").strip(),
        "side": str(projection.get("side") or "").strip().upper(),
        "status": str(projection.get("status") or "").strip().upper(),
        "size": (
            str(projection.get("size")).strip()
            if projection.get("size") is not None
            else None
        ),
        "observed_at": str(
            projection.get("observed_at") or ""
        ).strip(),
        "exchange_order_id_sha256": str(
            projection.get("exchange_order_id_sha256") or ""
        ).strip(),
        "authoritatively_nonterminal": (
            projection.get("authoritatively_nonterminal") is True
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def evaluate_futures_follow_up_intent_eligibility(
    projection: Mapping[str, Any] | None,
    *,
    intent_attached: bool,
) -> FuturesFollowUpIntentEligibility:
    if projection is None:
        return FuturesFollowUpIntentEligibility(
            eligible=False,
            blockers=("source_order_not_found",),
            source_found=False,
            source_product_configured=False,
            source_status_open=False,
            source_authoritatively_nonterminal=False,
            source_exactly_one_contract=False,
            source_side_valid=False,
            follow_up_intent_absent=not intent_attached,
            product_id=None,
            source_side=None,
            derived_follow_up_side=None,
            contract_count=None,
            source_status=None,
            source_observed_at=None,
            source_evidence_sha256=None,
        )

    product_id = str(projection.get("product_id") or "").strip()
    source_side = str(projection.get("side") or "").strip().upper()
    source_status = str(projection.get("status") or "").strip().upper()
    observed_at = str(projection.get("observed_at") or "").strip() or None
    source_product_configured = (
        product_id in FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS
    )
    source_status_open = source_status == FUTURES_FOLLOW_UP_ALLOWED_STATUS
    source_authoritatively_nonterminal = (
        projection.get("authoritatively_nonterminal") is True
    )
    source_side_valid = source_side in {"BUY", "SELL"}
    source_exactly_one_contract = _is_exactly_one_contract(
        projection.get("size")
    )
    derived_side = (
        "SELL"
        if source_side == "BUY"
        else "BUY"
        if source_side == "SELL"
        else None
    )
    evidence_sha256 = futures_follow_up_source_evidence_sha256(projection)

    if intent_attached:
        blockers = ("futures_follow_up_intent_already_attached",)
    else:
        blocker_items: list[str] = []
        if not source_product_configured:
            blocker_items.append("source_product_not_configured")
        if not source_status_open:
            blocker_items.append("source_status_not_open")
        if not source_authoritatively_nonterminal:
            blocker_items.append(
                "source_not_authoritatively_nonterminal"
            )
        if not source_exactly_one_contract:
            blocker_items.append("source_not_exactly_one_contract")
        if not source_side_valid:
            blocker_items.append("source_side_invalid")
        if observed_at is None:
            blocker_items.append("source_observation_missing")
        exchange_hash = str(
            projection.get("exchange_order_id_sha256") or ""
        ).strip()
        if not _SHA256_RE.fullmatch(exchange_hash):
            blocker_items.append("source_exchange_binding_invalid")
        blockers = tuple(blocker_items)

    return FuturesFollowUpIntentEligibility(
        eligible=not blockers,
        blockers=blockers,
        source_found=True,
        source_product_configured=source_product_configured,
        source_status_open=source_status_open,
        source_authoritatively_nonterminal=(
            source_authoritatively_nonterminal
        ),
        source_exactly_one_contract=source_exactly_one_contract,
        source_side_valid=source_side_valid,
        follow_up_intent_absent=not intent_attached,
        product_id=product_id or None,
        source_side=source_side or None,
        derived_follow_up_side=derived_side,
        contract_count=(
            FUTURES_FOLLOW_UP_CONTRACT_COUNT
            if source_exactly_one_contract
            else None
        ),
        source_status=source_status or None,
        source_observed_at=observed_at,
        source_evidence_sha256=evidence_sha256,
    )


def _is_exactly_one_contract(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return Decimal(str(value).strip()) == Decimal("1")
    except (InvalidOperation, ValueError):
        return False


class OperatorFuturesFollowUpIntentService:
    def __init__(self, *, repository: FuturesFollowUpIntentRepository) -> None:
        self.repository = repository

    def read(self, source_client_order_id: str) -> FuturesFollowUpIntentReadback:
        exact_source = str(source_client_order_id or "").strip()
        if not exact_source:
            raise ValueError(
                "operator_futures_follow_up_intent_source_invalid"
            )
        projection, intent = self.repository.read(exact_source)
        eligibility = evaluate_futures_follow_up_intent_eligibility(
            projection,
            intent_attached=intent is not None,
        )
        return FuturesFollowUpIntentReadback(
            goal_id=FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
            source_client_order_id=exact_source,
            eligibility=eligibility,
            follow_up_intent=intent,
        )

    def attach(
        self,
        *,
        context: FuturesFollowUpIntentRequestContext,
        source_client_order_id: str,
        expected_source_observed_at: str,
        expected_source_evidence_sha256: str,
    ) -> tuple[FuturesFollowUpIntentReadback, bool]:
        exact_source = str(source_client_order_id or "").strip()
        if not exact_source:
            raise ValueError(
                "operator_futures_follow_up_intent_source_invalid"
            )
        if context.operator_intent != FUTURES_FOLLOW_UP_OPERATOR_INTENT:
            raise ValueError(
                "operator_futures_follow_up_intent_operator_intent_invalid"
            )
        if context.reason_code != FUTURES_FOLLOW_UP_REASON_CODE:
            raise ValueError(
                "operator_futures_follow_up_intent_reason_code_invalid"
            )
        if (
            not context
            .acknowledge_future_materialization_requires_fresh_authorization
            or not context.acknowledge_no_coinbase_call_or_child_creation
        ):
            raise ValueError(
                "operator_futures_follow_up_intent_confirmation_required"
            )
        exact_observed_at = str(expected_source_observed_at or "").strip()
        exact_evidence = str(
            expected_source_evidence_sha256 or ""
        ).strip()
        if not exact_observed_at or not _SHA256_RE.fullmatch(exact_evidence):
            raise ValueError(
                "operator_futures_follow_up_intent_source_binding_invalid"
            )
        intent, replayed = self.repository.attach(
            context=context,
            source_client_order_id=exact_source,
            expected_source_observed_at=exact_observed_at,
            expected_source_evidence_sha256=exact_evidence,
        )
        projection, stored_intent = self.repository.read(exact_source)
        if stored_intent != intent:
            raise ValueError(
                "operator_futures_follow_up_intent_readback_mismatch"
            )
        eligibility = evaluate_futures_follow_up_intent_eligibility(
            projection,
            intent_attached=True,
        )
        return (
            FuturesFollowUpIntentReadback(
                goal_id=FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
                source_client_order_id=exact_source,
                eligibility=eligibility,
                follow_up_intent=intent,
            ),
            replayed,
        )


__all__ = [
    "FUTURES_FOLLOW_UP_ALLOWED_STATUS",
    "FUTURES_FOLLOW_UP_CONTRACT_COUNT",
    "FUTURES_FOLLOW_UP_INTENT_GOAL_ID",
    "FUTURES_FOLLOW_UP_OPERATOR_INTENT",
    "FUTURES_FOLLOW_UP_REASON_CODE",
    "FuturesFollowUpIntentEligibility",
    "FuturesFollowUpIntentReadback",
    "FuturesFollowUpIntentRecord",
    "FuturesFollowUpIntentRequestContext",
    "OperatorFuturesFollowUpIntentService",
    "evaluate_futures_follow_up_intent_eligibility",
    "futures_follow_up_source_evidence_sha256",
]
