"""Goal 11 Futures position eligibility and durable coordination.

Only backend-owned selection, one mutually exclusive Close/Reduce claim, exact
order/position reconciliation, and conditional exact-order Cancel are exposed.
Raw Coinbase payloads and private identifiers never enter durable/public state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from types import SimpleNamespace
from typing import Any, Literal, Protocol

from requests.exceptions import (
    ConnectTimeout,
    ConnectionError as RequestsConnectionError,
    HTTPError,
    ProxyError,
    ReadTimeout,
    SSLError,
    Timeout,
)

from core.enums import (
    AdminFuturesPositionCallOutcome,
    AdminFuturesPositionEligibilityOutcome,
)

from .futures_order_preview_r12 import (
    validate_r12_margin_collateral_evidence,
)
from .futures_portfolio_binding import (
    evaluate_futures_default_portfolio_binding,
)
from .futures_public_projection import (
    FuturesPublicProjectionError,
    is_opaque_futures_position_key,
    opaque_futures_position_key,
    public_futures_product_id,
)


FUTURES_POSITION_GOAL_ID = (
    "operator_futures_position_close_reduce_and_reconciliation_v1"
)
FUTURES_POSITION_MAX_SELECTION_AGE_SECONDS = 30
FUTURES_POSITION_ELIGIBILITY_CATEGORIES = (
    "api_key_permissions",
    "portfolio_catalog",
    "futures_positions",
    "product",
    "best_bid_ask",
    "futures_margin_collateral",
)
FUTURES_POSITION_MODES = ("CLOSE_FULL", "REDUCE_ONE_CONTRACT")
_FUTURES_POSITION_CREDENTIAL_SCOPE = "local-runtime-single-profile"


@dataclass(frozen=True, slots=True)
class FuturesPositionEligibilityResult:
    outcome: AdminFuturesPositionEligibilityOutcome
    diagnostic_code: str
    category_attempts: dict[str, int]
    selection: dict[str, str] | None
    portfolio_id_sha256: str | None
    evidence_sha256: str | None
    public_evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FuturesPositionRequestContext:
    actor_id: str
    roles: tuple[str, ...]
    expected_revision: int
    idempotency_key: str
    correlation_id: str
    audit_id: str
    operator_intent: str
    authorize_one_no_retry_six_category_cycle: bool = False
    acknowledge_cycle_is_goal_global_and_limited_to_ten: bool = False
    acknowledge_unsuccessful_or_unknown_cycle_fails_closed: bool = False
    authorize_exact_selected_position_action: bool = False
    acknowledge_action_is_mutually_exclusive_and_single_use: bool = False
    acknowledge_unknown_outcome_consumes_allowance: bool = False
    acknowledge_exact_order_cancel_only: bool = False


@dataclass(frozen=True, slots=True)
class FuturesPositionExecutionPlan:
    claim_id: str
    client_order_id: str
    mode: Literal["CLOSE_FULL", "REDUCE_ONE_CONTRACT"]
    product_id: str
    position_key: str
    action_size: str | None
    expected_contracts: str
    close_side: Literal["BUY", "SELL"]
    portfolio_id_sha256: str


@dataclass(frozen=True, slots=True)
class FuturesPositionGoalRecord:
    goal_id: str
    revision: int
    cycles_used: int
    active_cycle_number: int | None
    eligibility_outcome: AdminFuturesPositionEligibilityOutcome | None
    eligibility_diagnostic_code: str
    category_attempts: dict[str, int]
    selection: dict[str, str] | None
    selection_sha256: str | None
    portfolio_id_sha256: str | None
    eligibility_evidence_sha256: str | None
    selected_mode: str | None
    client_order_id: str | None
    action_outcome: AdminFuturesPositionCallOutcome
    action_exchange_invoked: bool | None
    exchange_order_id_sha256: str | None
    order_reconciliation_outcome: AdminFuturesPositionCallOutcome
    order_reconciliation_exchange_invoked: bool | None
    order_status: str | None
    authoritatively_nonterminal: bool | None
    position_reconciliation_outcome: AdminFuturesPositionCallOutcome
    position_reconciliation_exchange_invoked: bool | None
    remaining_contracts: str | None
    cancel_outcome: AdminFuturesPositionCallOutcome
    cancel_exchange_invoked: bool | None
    diagnostic_code: str
    correlation_id: str | None
    audit_id: str | None
    updated_at: str | None


class FuturesPositionLifecycleRepository(Protocol):
    def read(self) -> FuturesPositionGoalRecord: ...

    def begin_eligibility_cycle(
        self,
        *,
        context: FuturesPositionRequestContext,
        position_key: str,
    ) -> tuple[FuturesPositionGoalRecord, int | None]: ...

    def claim_eligibility_category(
        self,
        *,
        cycle_number: int,
        category: str,
    ) -> None: ...

    def finish_eligibility_cycle(
        self,
        *,
        cycle_number: int,
        result: FuturesPositionEligibilityResult,
        context: FuturesPositionRequestContext,
    ) -> FuturesPositionGoalRecord: ...

    def claim_action(
        self,
        *,
        context: FuturesPositionRequestContext,
        mode: str,
    ) -> tuple[FuturesPositionGoalRecord, FuturesPositionExecutionPlan | None]: ...

    def mark_action_exchange_invoked(self, *, claim_id: str) -> None: ...

    def finish_action(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord: ...

    def finish_action_and_claim_order_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord: ...

    def mark_order_reconciliation_invoked(self, *, claim_id: str) -> None: ...

    def finish_order_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord: ...

    def finish_order_and_claim_position_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord: ...

    def mark_position_reconciliation_invoked(self, *, claim_id: str) -> None: ...

    def finish_position_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord: ...

    def finish_position_and_claim_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord: ...

    def mark_cancel_exchange_invoked(self, *, claim_id: str) -> None: ...

    def release_cancel_invocation_conflict(
        self,
        *,
        claim_id: str,
    ) -> FuturesPositionGoalRecord: ...

    def is_cancel_invocation_sealed(self) -> bool: ...

    def finish_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord: ...


class FuturesPositionLifecycleError(ValueError):
    def __init__(self, code: str, *, http_status_code: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.http_status_code = http_status_code


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _empty_attempts() -> dict[str, int]:
    return {
        category: 0 for category in FUTURES_POSITION_ELIGIBILITY_CATEGORIES
    }


def classify_futures_position_selection_freshness(
    selection: Mapping[str, Any] | None,
    *,
    now: datetime,
) -> str:
    if selection is None:
        return "operator_futures_position_selection_missing"
    try:
        observed = datetime.fromisoformat(
            str(selection.get("observed_at") or "").replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return "operator_futures_position_selection_freshness_invalid"
    if (
        observed.tzinfo is None
        or observed.utcoffset() is None
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        return "operator_futures_position_selection_freshness_invalid"
    age = (
        now.astimezone(timezone.utc) - observed.astimezone(timezone.utc)
    ).total_seconds()
    if age < 0 or age > FUTURES_POSITION_MAX_SELECTION_AGE_SECONDS:
        return "operator_futures_position_selection_stale"
    return "operator_futures_position_selection_fresh"


class _EligibilityReadError(Exception):
    def __init__(self, diagnostic_code: str) -> None:
        self.diagnostic_code = diagnostic_code
        super().__init__(diagnostic_code)


def _eligibility_read_diagnostic(category: str, exc: Exception) -> str:
    prefix = f"operator_futures_position_{category}"
    if isinstance(exc, HTTPError):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        suffix = {
            401: "http_unauthorized",
            403: "http_forbidden",
            404: "http_not_found",
            429: "http_rate_limited",
        }.get(status_code)
        if suffix is None:
            if isinstance(status_code, int) and 400 <= status_code < 500:
                suffix = "http_client_error"
            elif isinstance(status_code, int) and 500 <= status_code < 600:
                suffix = "http_server_error"
            else:
                suffix = "http_unclassified"
    elif isinstance(exc, ConnectTimeout):
        suffix = "connect_timeout"
    elif isinstance(exc, ReadTimeout):
        suffix = "read_timeout"
    elif isinstance(exc, SSLError):
        suffix = "tls_failure"
    elif isinstance(exc, ProxyError):
        suffix = "proxy_failure"
    elif isinstance(exc, RequestsConnectionError):
        suffix = "connection_failure"
    elif isinstance(exc, Timeout):
        suffix = "timeout"
    elif isinstance(exc, (KeyError, TypeError, ValueError)):
        suffix = "schema_invalid"
    elif type(exc).__name__ == "AuthenticationError":
        suffix = "authentication_unavailable"
    else:
        suffix = "read_unknown"
    return f"{prefix}_{suffix}"


def _blocked_result(
    *,
    outcome: AdminFuturesPositionEligibilityOutcome,
    diagnostic_code: str,
    attempts: Mapping[str, int],
) -> FuturesPositionEligibilityResult:
    public = {
        "goal_id": FUTURES_POSITION_GOAL_ID,
        "profile_alias": "Default",
        "exact_position_eligible": False,
        "diagnostic_code": diagnostic_code,
        "category_attempts": dict(attempts),
        "raw_responses_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }
    return FuturesPositionEligibilityResult(
        outcome=outcome,
        diagnostic_code=diagnostic_code,
        category_attempts=dict(attempts),
        selection=None,
        portfolio_id_sha256=None,
        evidence_sha256=_canonical_sha256(public),
        public_evidence=public,
    )


def _position_items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        raise ValueError("futures_positions_invalid")
    nested = value.get("positions")
    if isinstance(nested, list):
        items: list[Mapping[str, Any]] = []
        for item in nested:
            if isinstance(item, Mapping):
                items.append(dict(item))
                continue
            attributes = getattr(item, "__dict__", None)
            if isinstance(attributes, Mapping):
                items.append(dict(attributes))
                continue
            raise ValueError("futures_position_row_invalid")
        return items
    items: list[Mapping[str, Any]] = []
    for product_id, item in value.items():
        if isinstance(item, Mapping):
            normalized = dict(item)
        else:
            attributes = getattr(item, "__dict__", None)
            if not isinstance(attributes, Mapping):
                raise ValueError("futures_position_row_invalid")
            normalized = dict(attributes)
        normalized.setdefault("product_id", product_id)
        items.append(normalized)
    return items


def _contracts(position: Mapping[str, Any]) -> Decimal:
    raw = position.get("number_of_contracts")
    if raw is None:
        raw = position.get("net_size")
    try:
        value = abs(Decimal(str(raw)))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("futures_position_contracts_invalid") from None
    if not value.is_finite() or value <= 0 or value != value.to_integral():
        raise ValueError("futures_position_contracts_invalid")
    return value


def _position_side(position: Mapping[str, Any]) -> Literal["LONG", "SHORT"]:
    raw = str(position.get("side") or "").strip().upper()
    if raw in {"LONG", "SHORT"}:
        return raw
    try:
        net = Decimal(str(position.get("net_size")))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("futures_position_side_invalid") from None
    if net > 0:
        return "LONG"
    if net < 0:
        return "SHORT"
    raise ValueError("futures_position_side_invalid")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _best_prices(book: Any, *, product_id: str) -> tuple[str, str]:
    if not isinstance(book, Mapping):
        raise ValueError("futures_best_bid_ask_invalid")
    books = book.get("pricebooks")
    if not isinstance(books, list):
        raise ValueError("futures_best_bid_ask_invalid")
    selected = next(
        (
            item
            for item in books
            if isinstance(item, Mapping)
            and item.get("product_id") == product_id
        ),
        None,
    )
    if selected is None:
        raise ValueError("futures_best_bid_ask_invalid")
    bids = selected.get("bids")
    asks = selected.get("asks")
    try:
        bid = Decimal(str(bids[0]["price"]))
        ask = Decimal(str(asks[0]["price"]))
    except (IndexError, KeyError, InvalidOperation, TypeError, ValueError):
        raise ValueError("futures_best_bid_ask_invalid") from None
    if (
        not bid.is_finite()
        or not ask.is_finite()
        or bid <= 0
        or ask <= 0
        or bid > ask
    ):
        raise ValueError("futures_best_bid_ask_invalid")
    return _decimal_text(bid), _decimal_text(ask)


class FuturesPositionEligibilityReader:
    """Read the six approved categories once and bind one selected position."""

    def __init__(
        self,
        *,
        rest_client: Any,
        position_key: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.rest_client = rest_client
        self.position_key = position_key
        self.now = now or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        before_category: Callable[[str], None],
    ) -> FuturesPositionEligibilityResult:
        attempts = _empty_attempts()

        def read(category: str, call: Callable[[], Any]) -> Any:
            if attempts[category] != 0:
                raise RuntimeError(
                    "operator_futures_position_duplicate_category_read"
                )
            try:
                before_category(category)
                attempts[category] = 1
                return call()
            except Exception as exc:
                raise _EligibilityReadError(
                    _eligibility_read_diagnostic(category, exc)
                ) from None

        try:
            permissions = read(
                "api_key_permissions",
                self.rest_client.get_api_key_permissions,
            )
            portfolios = read(
                "portfolio_catalog",
                self.rest_client.get_futures_preview_eligibility_portfolios,
            )
            positions = read(
                "futures_positions",
                self.rest_client.get_futures_positions,
            )
        except _EligibilityReadError as exc:
            return _blocked_result(
                outcome=AdminFuturesPositionEligibilityOutcome.UNKNOWN,
                diagnostic_code=exc.diagnostic_code,
                attempts=attempts,
            )

        observed_at = self.now()
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
                raise ValueError("futures_default_portfolio_ineligible")
            if not is_opaque_futures_position_key(self.position_key):
                raise ValueError("futures_position_key_invalid")
            selected: Mapping[str, Any] | None = None
            for position in _position_items(positions):
                product_id = public_futures_product_id(
                    position.get("product_id")
                )
                raw_position_portfolio = str(
                    position.get("portfolio_uuid")
                    or position.get("portfolio_id")
                    or position.get("retail_portfolio_id")
                    or ""
                ).strip()
                if (
                    raw_position_portfolio
                    and raw_position_portfolio
                    != binding.observed_portfolio_id
                ):
                    raise ValueError(
                        "futures_position_portfolio_scope_mismatch"
                    )
                key = opaque_futures_position_key(
                    product_id=product_id,
                    portfolio_identity=(
                        raw_position_portfolio
                        or _FUTURES_POSITION_CREDENTIAL_SCOPE
                    ),
                )
                if key == self.position_key:
                    selected = position
                    break
            if selected is None:
                raise ValueError("futures_position_not_found")
            product_id = public_futures_product_id(selected.get("product_id"))
            contracts = _contracts(selected)
            side = _position_side(selected)
        except (FuturesPublicProjectionError, ValueError):
            return _blocked_result(
                outcome=AdminFuturesPositionEligibilityOutcome.INELIGIBLE,
                diagnostic_code=(
                    "operator_futures_position_selection_ineligible"
                ),
                attempts=attempts,
            )

        try:
            product = read(
                "product",
                lambda: self.rest_client.get_futures_manual_eligibility_product(
                    product_id
                ),
            )
            book = read(
                "best_bid_ask",
                lambda: self.rest_client.get_best_bid_ask(
                    product_ids=[product_id]
                ),
            )
            market_observed_at = self.now()
            margin = read(
                "futures_margin_collateral",
                self.rest_client
                .get_futures_manual_eligibility_margin_collateral_snapshot,
            )
        except _EligibilityReadError as exc:
            return _blocked_result(
                outcome=AdminFuturesPositionEligibilityOutcome.UNKNOWN,
                diagnostic_code=exc.diagnostic_code,
                attempts=attempts,
            )

        try:
            if (
                not isinstance(product, Mapping)
                or product.get("product_id") != product_id
                or product.get("product_type") != "FUTURE"
                or product.get("trading_disabled") is True
                or product.get("view_only") is True
                or product.get("cancel_only") is True
            ):
                raise ValueError("futures_position_product_ineligible")
            validate_r12_margin_collateral_evidence(margin)
            bid, ask = _best_prices(book, product_id=product_id)
        except Exception:
            return _blocked_result(
                outcome=AdminFuturesPositionEligibilityOutcome.INELIGIBLE,
                diagnostic_code=(
                    "operator_futures_position_risk_or_market_ineligible"
                ),
                attempts=attempts,
            )

        close_side: Literal["BUY", "SELL"] = (
            "SELL" if side == "LONG" else "BUY"
        )
        selection = {
            "position_key": self.position_key,
            "product_id": product_id,
            "position_side": side,
            "close_side": close_side,
            "current_contracts": _decimal_text(contracts),
            "full_close_size": _decimal_text(contracts),
            "bounded_reduce_size": "1" if contracts > 1 else "",
            "best_bid": bid,
            "best_ask": ask,
            "observed_at": _timestamp(market_observed_at),
        }
        portfolio_hash = _sha256_text(binding.observed_portfolio_id)
        public = {
            "goal_id": FUTURES_POSITION_GOAL_ID,
            "profile_alias": "Default",
            "portfolio_id_sha256": portfolio_hash,
            "credential_can_view": True,
            "credential_can_trade": True,
            "selection": selection,
            "margin_collateral_validated": True,
            "exact_position_eligible": True,
            "diagnostic_code": (
                "operator_futures_position_exact_position_eligible"
            ),
            "category_attempts": dict(attempts),
            "raw_responses_included": False,
            "private_identifiers_included": False,
            "exception_text_included": False,
        }
        return FuturesPositionEligibilityResult(
            outcome=AdminFuturesPositionEligibilityOutcome.ELIGIBLE,
            diagnostic_code=(
                "operator_futures_position_exact_position_eligible"
            ),
            category_attempts=dict(attempts),
            selection=selection,
            portfolio_id_sha256=portfolio_hash,
            evidence_sha256=_canonical_sha256(public),
            public_evidence=public,
        )


class OperatorFuturesPositionLifecycleService:
    """Coordinate one durable eligibility cycle or one Goal 11 action."""

    def __init__(
        self,
        *,
        repository: FuturesPositionLifecycleRepository,
        eligibility_reader_factory: Callable[
            [str], FuturesPositionEligibilityReader
        ],
        exchange_executor: Any,
    ) -> None:
        self.repository = repository
        self.eligibility_reader_factory = eligibility_reader_factory
        self.exchange_executor = exchange_executor

    def read(self) -> FuturesPositionGoalRecord:
        record = self.repository.read()
        if (
            record.cancel_exchange_invoked is not True
            and self.repository.is_cancel_invocation_sealed()
        ):
            return replace(
                record,
                cancel_outcome=(
                    AdminFuturesPositionCallOutcome.NOT_RUN
                ),
                cancel_exchange_invoked=None,
                diagnostic_code=(
                    "operator_futures_cancel_invocation_already_sealed"
                ),
            )
        return record

    def refresh(
        self,
        *,
        context: FuturesPositionRequestContext,
        position_key: str,
    ) -> FuturesPositionGoalRecord:
        if (
            context.operator_intent
            != "refresh_one_futures_position_eligibility_cycle"
            or not context.authorize_one_no_retry_six_category_cycle
            or not context.acknowledge_cycle_is_goal_global_and_limited_to_ten
            or not context.acknowledge_unsuccessful_or_unknown_cycle_fails_closed
            or not is_opaque_futures_position_key(position_key)
        ):
            raise FuturesPositionLifecycleError(
                "operator_futures_position_refresh_confirmation_required",
                http_status_code=422,
            )
        record, cycle_number = self.repository.begin_eligibility_cycle(
            context=context,
            position_key=position_key,
        )
        if cycle_number is None:
            return record
        result = self.eligibility_reader_factory(position_key).run(
            before_category=lambda category: (
                self.repository.claim_eligibility_category(
                    cycle_number=cycle_number,
                    category=category,
                )
            )
        )
        return self.repository.finish_eligibility_cycle(
            cycle_number=cycle_number,
            result=result,
            context=context,
        )

    def execute(
        self,
        *,
        context: FuturesPositionRequestContext,
        mode: str,
    ) -> FuturesPositionGoalRecord:
        if (
            context.operator_intent
            != "authorize_one_futures_position_close_or_reduce"
            or mode not in FUTURES_POSITION_MODES
            or not context.authorize_exact_selected_position_action
            or not context.acknowledge_action_is_mutually_exclusive_and_single_use
            or not context.acknowledge_unknown_outcome_consumes_allowance
            or not context.acknowledge_exact_order_cancel_only
        ):
            raise FuturesPositionLifecycleError(
                "operator_futures_position_confirmation_required",
                http_status_code=422,
            )
        record, plan = self.repository.claim_action(
            context=context,
            mode=mode,
        )
        if plan is None:
            return record
        try:
            action = self.exchange_executor.close_or_reduce(
                plan=plan,
                before_call=lambda: (
                    self.repository.mark_action_exchange_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            action = SimpleNamespace(
                outcome=AdminFuturesPositionCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_position_action_outcome_unknown"
                ),
                exchange_order_id_sha256=None,
                private_exchange_order_id=None,
            )
        if (
            action.outcome
            is AdminFuturesPositionCallOutcome.ACCEPTED
            and not action.private_exchange_order_id
        ):
            action = SimpleNamespace(
                outcome=AdminFuturesPositionCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_position_action_outcome_unknown"
                ),
                exchange_order_id_sha256=None,
                private_exchange_order_id=None,
            )
        if action.outcome is not AdminFuturesPositionCallOutcome.ACCEPTED:
            return self.repository.finish_action(
                claim_id=plan.claim_id,
                execution=action,
            )
        self.repository.finish_action_and_claim_order_reconciliation(
            claim_id=plan.claim_id,
            execution=action,
        )
        try:
            order = self.exchange_executor.reconcile_order(
                plan=plan,
                private_exchange_order_id=action.private_exchange_order_id,
                before_call=lambda: (
                    self.repository.mark_order_reconciliation_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            order = SimpleNamespace(
                outcome=AdminFuturesPositionCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_position_order_reconciliation_unknown"
                ),
                order_status=None,
                authoritatively_nonterminal=False,
            )
        if order.outcome is not AdminFuturesPositionCallOutcome.ACCEPTED:
            return self.repository.finish_order_reconciliation(
                claim_id=plan.claim_id,
                execution=order,
            )
        self.repository.finish_order_and_claim_position_reconciliation(
            claim_id=plan.claim_id,
            execution=order,
        )
        try:
            position = self.exchange_executor.reconcile_position(
                plan=plan,
                before_call=lambda: (
                    self.repository.mark_position_reconciliation_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            position = SimpleNamespace(
                outcome=AdminFuturesPositionCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_position_position_reconciliation_unknown"
                ),
                remaining_contracts=None,
            )
        if (
            position.outcome
            is not AdminFuturesPositionCallOutcome.ACCEPTED
            or not order.authoritatively_nonterminal
        ):
            return self.repository.finish_position_reconciliation(
                claim_id=plan.claim_id,
                execution=position,
            )
        self.repository.finish_position_and_claim_cancel(
            claim_id=plan.claim_id,
            execution=position,
        )
        cancel_boundary_failure: str | None = None

        def mark_cancel_boundary() -> None:
            nonlocal cancel_boundary_failure
            try:
                self.repository.mark_cancel_exchange_invoked(
                    claim_id=plan.claim_id
                )
            except FuturesPositionLifecycleError as exc:
                if exc.code == (
                    "operator_futures_cancel_invocation_already_sealed"
                ):
                    cancel_boundary_failure = exc.code
                raise

        try:
            cancel = self.exchange_executor.cancel(
                plan=plan,
                private_exchange_order_id=action.private_exchange_order_id,
                before_call=mark_cancel_boundary,
            )
        except Exception:
            cancel = SimpleNamespace(
                outcome=AdminFuturesPositionCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_position_cancel_outcome_unknown"
                ),
            )
        if cancel_boundary_failure == (
            "operator_futures_cancel_invocation_already_sealed"
        ):
            return self.repository.release_cancel_invocation_conflict(
                claim_id=plan.claim_id,
            )
        return self.repository.finish_cancel(
            claim_id=plan.claim_id,
            execution=cancel,
        )


__all__ = [
    "FUTURES_POSITION_ELIGIBILITY_CATEGORIES",
    "FUTURES_POSITION_GOAL_ID",
    "FUTURES_POSITION_MAX_SELECTION_AGE_SECONDS",
    "FUTURES_POSITION_MODES",
    "FuturesPositionEligibilityReader",
    "FuturesPositionEligibilityResult",
    "FuturesPositionExecutionPlan",
    "FuturesPositionGoalRecord",
    "FuturesPositionLifecycleError",
    "FuturesPositionLifecycleRepository",
    "FuturesPositionRequestContext",
    "OperatorFuturesPositionLifecycleService",
    "classify_futures_position_selection_freshness",
]
