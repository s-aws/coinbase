"""Goal 10 eligibility and lifecycle policy primitives.

This module contains the no-retry six-category state-refresh reader and
identifier-minimized evidence returned to the durable coordinator. It never
opens historical Preview artifacts and never invokes Preview, Create, Cancel,
Close, or Reduce.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
from typing import Any, Protocol

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
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)

from .futures_order_preview import (
    FUTURES_PREVIEW_PRODUCT_ID,
    build_futures_order_preview_candidate,
)
from .futures_order_preview_r12 import (
    validate_r12_margin_collateral_evidence,
)
from .futures_portfolio_binding import (
    evaluate_futures_default_portfolio_binding,
)


FUTURES_MANUAL_GOAL_ID = "operator_futures_manual_order_lifecycle_v1"
FUTURES_MANUAL_ACTIVE_GOAL_ID = (
    "operator_futures_manual_order_lifecycle_default_profile_v2"
)
FUTURES_MANUAL_MAX_CANDIDATE_AGE_SECONDS = 30
FUTURES_MANUAL_ELIGIBILITY_CATEGORIES = (
    "api_key_permissions",
    "portfolio_catalog",
    "product",
    "best_bid_ask",
    "futures_positions",
    "futures_margin_collateral",
)
FUTURES_MANUAL_TERMINAL_ELIGIBILITY_DIAGNOSTICS = frozenset(
    {
        "operator_futures_manual_futures_positions_http_forbidden",
    }
)


def is_futures_manual_goal_terminal(
    eligibility_diagnostic_code: str,
) -> bool:
    """Return whether the persisted eligibility boundary closes this goal."""

    return (
        str(eligibility_diagnostic_code)
        in FUTURES_MANUAL_TERMINAL_ELIGIBILITY_DIAGNOSTICS
    )


def classify_futures_manual_candidate_freshness(
    candidate: Mapping[str, Any] | None,
    *,
    now: datetime,
) -> str:
    """Return a fixed, value-blind execution-freshness classification."""

    if candidate is None:
        return "operator_futures_manual_candidate_missing"
    observed_text = str(candidate.get("observed_at") or "").strip()
    try:
        observed_at = datetime.fromisoformat(
            observed_text.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return "operator_futures_manual_candidate_freshness_invalid"
    if (
        observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        return "operator_futures_manual_candidate_freshness_invalid"
    age_seconds = (
        now.astimezone(timezone.utc)
        - observed_at.astimezone(timezone.utc)
    ).total_seconds()
    if (
        age_seconds < 0
        or age_seconds > FUTURES_MANUAL_MAX_CANDIDATE_AGE_SECONDS
    ):
        return "operator_futures_manual_candidate_stale"
    return "operator_futures_manual_candidate_fresh"


@dataclass(frozen=True, slots=True)
class FuturesManualEligibilityResult:
    outcome: AdminFuturesManualEligibilityOutcome
    diagnostic_code: str
    category_attempts: dict[str, int]
    candidate: dict[str, str] | None
    portfolio_id_sha256: str | None
    evidence_sha256: str | None
    public_evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FuturesManualRequestContext:
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
    authorize_preview_create_and_safe_closeout: bool = False
    acknowledge_unknown_outcome_consumes_allowance: bool = False
    acknowledge_create_requires_accepted_identical_preview: bool = False
    acknowledge_cancel_is_only_for_exact_nonterminal_child: bool = False


@dataclass(frozen=True, slots=True)
class FuturesManualExecutionPlan:
    claim_id: str
    client_order_id: str
    candidate: dict[str, str]
    candidate_sha256: str
    eligibility_evidence_sha256: str


@dataclass(frozen=True, slots=True)
class FuturesManualGoalRecord:
    goal_id: str
    revision: int
    cycles_used: int
    active_cycle_number: int | None
    eligibility_outcome: AdminFuturesManualEligibilityOutcome | None
    eligibility_diagnostic_code: str
    category_attempts: dict[str, int]
    candidate: dict[str, str] | None
    candidate_sha256: str | None
    portfolio_id_sha256: str | None
    eligibility_evidence_sha256: str | None
    client_order_id: str | None
    preview_outcome: AdminFuturesManualCallOutcome
    preview_exchange_invoked: bool | None
    preview_id_sha256: str | None
    create_outcome: AdminFuturesManualCallOutcome
    create_exchange_invoked: bool | None
    exchange_order_id_sha256: str | None
    reconciliation_outcome: AdminFuturesManualCallOutcome
    reconciliation_exchange_invoked: bool | None
    order_status: str | None
    authoritatively_nonterminal: bool | None
    cancel_outcome: AdminFuturesManualCallOutcome
    cancel_exchange_invoked: bool | None
    diagnostic_code: str
    correlation_id: str | None
    audit_id: str | None
    updated_at: str | None


class FuturesManualLifecycleRepository(Protocol):
    def read(self) -> FuturesManualGoalRecord: ...

    def begin_eligibility_cycle(
        self,
        *,
        context: FuturesManualRequestContext,
    ) -> tuple[FuturesManualGoalRecord, int | None]: ...

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
        result: FuturesManualEligibilityResult,
        context: FuturesManualRequestContext,
    ) -> FuturesManualGoalRecord: ...

    def claim_preview(
        self,
        *,
        context: FuturesManualRequestContext,
    ) -> tuple[FuturesManualGoalRecord, FuturesManualExecutionPlan | None]: ...

    def mark_preview_exchange_invoked(self, *, claim_id: str) -> None: ...

    def finish_preview(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord: ...

    def claim_create(
        self,
        *,
        claim_id: str,
    ) -> FuturesManualGoalRecord: ...

    def mark_create_exchange_invoked(self, *, claim_id: str) -> None: ...

    def finish_create(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord: ...

    def finish_create_and_claim_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord: ...

    def claim_reconciliation(
        self,
        *,
        claim_id: str,
    ) -> FuturesManualGoalRecord: ...

    def mark_reconciliation_exchange_invoked(
        self,
        *,
        claim_id: str,
    ) -> None: ...

    def finish_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord: ...

    def finish_reconciliation_and_claim_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord: ...

    def claim_cancel(
        self,
        *,
        claim_id: str,
    ) -> FuturesManualGoalRecord: ...

    def mark_cancel_exchange_invoked(self, *, claim_id: str) -> None: ...

    def finish_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord: ...


class FuturesManualLifecycleError(ValueError):
    def __init__(self, code: str, *, http_status_code: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.http_status_code = http_status_code


class OperatorFuturesManualLifecycleService:
    """Coordinate one durable eligibility cycle or one terminal proof."""

    def __init__(
        self,
        *,
        repository: FuturesManualLifecycleRepository,
        eligibility_reader: FuturesManualEligibilityReader,
        exchange_executor: Any,
    ) -> None:
        self.repository = repository
        self.eligibility_reader = eligibility_reader
        self.exchange_executor = exchange_executor

    def read(self) -> FuturesManualGoalRecord:
        return self.repository.read()

    def refresh(
        self,
        *,
        context: FuturesManualRequestContext,
    ) -> FuturesManualGoalRecord:
        if (
            context.operator_intent
            != "refresh_one_futures_manual_eligibility_cycle"
            or not context.authorize_one_no_retry_six_category_cycle
            or not context.acknowledge_cycle_is_goal_global_and_limited_to_ten
            or not (
                context
                .acknowledge_unsuccessful_or_unknown_cycle_fails_closed
            )
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_refresh_confirmation_required",
                http_status_code=422,
            )
        record, cycle_number = self.repository.begin_eligibility_cycle(
            context=context
        )
        if cycle_number is None:
            return record
        result = self.eligibility_reader.run(
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
        context: FuturesManualRequestContext,
    ) -> FuturesManualGoalRecord:
        if (
            context.operator_intent
            != "preview_submit_and_safe_closeout_one_futures_order"
            or not context.authorize_preview_create_and_safe_closeout
            or not context.acknowledge_unknown_outcome_consumes_allowance
            or not (
                context
                .acknowledge_create_requires_accepted_identical_preview
            )
            or not (
                context
                .acknowledge_cancel_is_only_for_exact_nonterminal_child
            )
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_confirmation_required",
                http_status_code=422,
            )
        record, plan = self.repository.claim_preview(context=context)
        if plan is None:
            return record
        try:
            preview = self.exchange_executor.preview(
                plan.candidate,
                before_call=lambda: (
                    self.repository.mark_preview_exchange_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            preview = SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_manual_preview_outcome_unknown"
                ),
                preview_id_sha256=None,
                private_preview_id=None,
            )
        record = self.repository.finish_preview(
            claim_id=plan.claim_id,
            execution=preview,
        )
        if preview.outcome is not AdminFuturesManualCallOutcome.ACCEPTED:
            return record
        if not preview.private_preview_id:
            raise FuturesManualLifecycleError(
                "operator_futures_manual_preview_private_binding_missing"
            )

        self.repository.claim_create(claim_id=plan.claim_id)
        try:
            created = self.exchange_executor.create(
                candidate=plan.candidate,
                client_order_id=plan.client_order_id,
                private_preview_id=preview.private_preview_id,
                before_call=lambda: (
                    self.repository.mark_create_exchange_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            created = SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_manual_create_outcome_unknown"
                ),
                exchange_order_id_sha256=None,
                private_exchange_order_id=None,
            )
        if created.outcome is not AdminFuturesManualCallOutcome.ACCEPTED:
            return self.repository.finish_create(
                claim_id=plan.claim_id,
                execution=created,
            )
        if not created.private_exchange_order_id:
            raise FuturesManualLifecycleError(
                "operator_futures_manual_create_private_binding_missing"
            )

        self.repository.finish_create_and_claim_reconciliation(
            claim_id=plan.claim_id,
            execution=created,
        )
        try:
            reconciled = self.exchange_executor.reconcile(
                client_order_id=plan.client_order_id,
                private_exchange_order_id=(
                    created.private_exchange_order_id
                ),
                before_call=lambda: (
                    self.repository.mark_reconciliation_exchange_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            reconciled = SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_manual_reconciliation_outcome_unknown"
                ),
                order_status=None,
                authoritatively_nonterminal=False,
            )
        if (
            reconciled.outcome
            is not AdminFuturesManualCallOutcome.ACCEPTED
            or not reconciled.authoritatively_nonterminal
        ):
            return self.repository.finish_reconciliation(
                claim_id=plan.claim_id,
                execution=reconciled,
            )

        self.repository.finish_reconciliation_and_claim_cancel(
            claim_id=plan.claim_id,
            execution=reconciled,
        )
        try:
            cancelled = self.exchange_executor.cancel(
                client_order_id=plan.client_order_id,
                private_exchange_order_id=(
                    created.private_exchange_order_id
                ),
                before_call=lambda: (
                    self.repository.mark_cancel_exchange_invoked(
                        claim_id=plan.claim_id
                    )
                ),
            )
        except Exception:
            cancelled = SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_manual_cancel_outcome_unknown"
                ),
            )
        return self.repository.finish_cancel(
            claim_id=plan.claim_id,
            execution=cancelled,
        )


def _timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
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
        category: 0
        for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
    }


class _FuturesManualEligibilityReadError(Exception):
    """Carry only one fixed, value-blind read-boundary classification."""

    def __init__(self, diagnostic_code: str) -> None:
        self.diagnostic_code = diagnostic_code
        super().__init__(diagnostic_code)


def _eligibility_read_diagnostic(
    category: str,
    exc: Exception,
) -> str:
    prefix = f"operator_futures_manual_{category}"
    if isinstance(exc, HTTPError):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code == 401:
            suffix = "http_unauthorized"
        elif status_code == 403:
            suffix = "http_forbidden"
        elif status_code == 404:
            suffix = "http_not_found"
        elif status_code == 429:
            suffix = "http_rate_limited"
        elif (
            isinstance(status_code, int)
            and not isinstance(status_code, bool)
            and 400 <= status_code < 500
        ):
            suffix = "http_client_error"
        elif (
            isinstance(status_code, int)
            and not isinstance(status_code, bool)
            and 500 <= status_code < 600
        ):
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
    goal_id: str,
    outcome: AdminFuturesManualEligibilityOutcome,
    diagnostic_code: str,
    attempts: Mapping[str, int],
) -> FuturesManualEligibilityResult:
    public = {
        "goal_id": goal_id,
        "profile_alias": "Default",
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "contract_count": "1",
        "caps": {
            "opening_usdc": "100",
            "exposure_usdc": "150",
            "turnover_usdc": "300",
            "comparison": "strictly_less_than",
        },
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


def _candidate_diagnostic(exc: BaseException) -> str:
    if (
        type(exc) is ValueError
        and len(exc.args) == 1
        and exc.args[0]
        == "futures_preview_existing_product_exposure_blocked"
    ):
        return "operator_futures_manual_existing_exposure_ineligible"
    if (
        type(exc) is ValueError
        and len(exc.args) == 1
        and exc.args[0]
        in {
            "futures_preview_opening_cap_blocked",
            "futures_preview_exposure_cap_blocked",
            "futures_preview_buffered_close_cap_blocked",
            "futures_preview_turnover_cap_blocked",
        }
    ):
        return "operator_futures_manual_cap_ineligible"
    return "operator_futures_manual_product_or_market_ineligible"


class FuturesManualEligibilityReader:
    """Perform each approved V3 eligibility category at most once."""

    def __init__(
        self,
        *,
        rest_client: Any,
        now: Callable[[], datetime] | None = None,
        goal_id: str = FUTURES_MANUAL_GOAL_ID,
    ) -> None:
        self.rest_client = rest_client
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.goal_id = str(goal_id)

    def run(
        self,
        *,
        before_category: Callable[[str], None],
    ) -> FuturesManualEligibilityResult:
        attempts = _empty_attempts()

        def read(category: str, call: Callable[[], Any]) -> Any:
            if attempts[category] != 0:
                raise RuntimeError(
                    "operator_futures_manual_duplicate_category_read"
                )
            try:
                before_category(category)
                attempts[category] = 1
                return call()
            except Exception as exc:
                raise _FuturesManualEligibilityReadError(
                    _eligibility_read_diagnostic(category, exc)
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
                lambda: self.rest_client.get_futures_manual_eligibility_product(
                    FUTURES_PREVIEW_PRODUCT_ID
                ),
            )
            book = read(
                "best_bid_ask",
                lambda: self.rest_client.get_best_bid_ask(
                    product_ids=[FUTURES_PREVIEW_PRODUCT_ID]
                ),
            )
            # Bind freshness to receipt of the market observation itself.
            # Slower position or margin reads must age this timestamp rather
            # than make an older quote appear newly observed.
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
        except _FuturesManualEligibilityReadError as exc:
            return _blocked_result(
                goal_id=self.goal_id,
                outcome=AdminFuturesManualEligibilityOutcome.UNKNOWN,
                diagnostic_code=exc.diagnostic_code,
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
                raise ValueError(
                    "operator_futures_manual_portfolio_ineligible"
                )
        except Exception:
            return _blocked_result(
                goal_id=self.goal_id,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=(
                    "operator_futures_manual_portfolio_ineligible"
                ),
                attempts=attempts,
            )

        try:
            validate_r12_margin_collateral_evidence(margin)
        except Exception:
            return _blocked_result(
                goal_id=self.goal_id,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=(
                    "operator_futures_manual_margin_collateral_ineligible"
                ),
                attempts=attempts,
            )

        try:
            candidate = build_futures_order_preview_candidate(
                product=product if isinstance(product, Mapping) else {},
                book=book if isinstance(book, Mapping) else {},
                positions=positions,
                observed_at=observed_at,
            )
        except Exception as exc:
            return _blocked_result(
                goal_id=self.goal_id,
                outcome=AdminFuturesManualEligibilityOutcome.INELIGIBLE,
                diagnostic_code=_candidate_diagnostic(exc),
                attempts=attempts,
            )

        portfolio_hash = _sha256_text(binding.observed_portfolio_id)
        public = {
            "goal_id": self.goal_id,
            "profile_alias": "Default",
            "portfolio_type": "DEFAULT",
            "portfolio_id_sha256": portfolio_hash,
            "credential_can_view": True,
            "credential_can_trade": True,
            "selection_authority": (
                "cdp_api_key_permissioned_portfolio"
            ),
            "product_id": FUTURES_PREVIEW_PRODUCT_ID,
            "contract_count": "1",
            "caps": {
                "opening_usdc": "100",
                "exposure_usdc": "150",
                "turnover_usdc": "300",
                "comparison": "strictly_less_than",
            },
            "candidate": dict(candidate),
            "exact_v3_eligible": True,
            "diagnostic_code": "operator_futures_manual_exact_v3_eligible",
            "category_attempts": dict(attempts),
            "raw_responses_included": False,
            "private_identifiers_included": False,
            "exception_text_included": False,
        }
        evidence_hash = _canonical_sha256(public)
        return FuturesManualEligibilityResult(
            outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
            diagnostic_code="operator_futures_manual_exact_v3_eligible",
            category_attempts=dict(attempts),
            candidate=dict(candidate),
            portfolio_id_sha256=portfolio_hash,
            evidence_sha256=evidence_hash,
            public_evidence=public,
        )


__all__ = [
    "FUTURES_MANUAL_ELIGIBILITY_CATEGORIES",
    "FUTURES_MANUAL_ACTIVE_GOAL_ID",
    "FUTURES_MANUAL_GOAL_ID",
    "FUTURES_MANUAL_MAX_CANDIDATE_AGE_SECONDS",
    "FuturesManualExecutionPlan",
    "FuturesManualEligibilityReader",
    "FuturesManualEligibilityResult",
    "FuturesManualGoalRecord",
    "FuturesManualLifecycleError",
    "FuturesManualLifecycleRepository",
    "FuturesManualRequestContext",
    "OperatorFuturesManualLifecycleService",
    "classify_futures_manual_candidate_freshness",
]
