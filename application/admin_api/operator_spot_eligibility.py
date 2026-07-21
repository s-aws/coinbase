"""Pure orchestration for the approved operator Spot eligibility reads."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Protocol
from uuid import UUID, uuid5


SPOT_ELIGIBILITY_PRODUCT_ID = "BTC-USDC"
SPOT_ELIGIBILITY_CREATE_ONLY_GOAL_KEY = (
    "operator_spot_automation_single_child_execution_adapter_v1"
)
SPOT_ELIGIBILITY_PREVIEW_GATED_GOAL_KEY = (
    "operator_spot_automation_preview_gated_successor_candidate_v2"
)
_SPOT_ELIGIBILITY_GOAL_KEYS = frozenset(
    {
        SPOT_ELIGIBILITY_CREATE_ONLY_GOAL_KEY,
        SPOT_ELIGIBILITY_PREVIEW_GATED_GOAL_KEY,
    }
)
_SPOT_ELIGIBILITY_CLIENT_ORDER_NAMESPACE = UUID(
    "af243a31-5934-52e2-b540-8d7b101d82ca"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DIAGNOSTIC_PATTERN = re.compile(r"^[a-z0-9_]+$")
_DEFAULT_FRESHNESS = timedelta(seconds=60)
_BEST_BID_ASK_FRESHNESS = timedelta(seconds=30)
_ACTIVE_ORDER_CATALOG_FRESHNESS = timedelta(seconds=30)


class ApprovedSpotEligibilityCategory(str, Enum):
    """The sealed categories allowed in one eligibility cycle."""

    API_KEY_PERMISSIONS = "API_KEY_PERMISSIONS"
    PORTFOLIO_CATALOG = "PORTFOLIO_CATALOG"
    ACCOUNT_WALLET_BALANCES = "ACCOUNT_WALLET_BALANCES"
    PRODUCT_METADATA = "PRODUCT_METADATA"
    BEST_BID_ASK = "BEST_BID_ASK"
    FEE_SUMMARY = "FEE_SUMMARY"
    EXACT_ORDER_RECONCILIATION = "EXACT_ORDER_RECONCILIATION"
    ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG = "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG"


APPROVED_SPOT_ELIGIBILITY_ORDER = (
    ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS,
    ApprovedSpotEligibilityCategory.PORTFOLIO_CATALOG,
    ApprovedSpotEligibilityCategory.ACCOUNT_WALLET_BALANCES,
    ApprovedSpotEligibilityCategory.PRODUCT_METADATA,
    ApprovedSpotEligibilityCategory.BEST_BID_ASK,
    ApprovedSpotEligibilityCategory.FEE_SUMMARY,
    ApprovedSpotEligibilityCategory.EXACT_ORDER_RECONCILIATION,
    ApprovedSpotEligibilityCategory.ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG,
)


class SpotEligibilityReadOutcome(str, Enum):
    """Sanitized terminal outcome for a category or cycle."""

    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


def _require_aware(value: datetime, *, code: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(code)
    if value.utcoffset() is None:
        raise ValueError(code)


def _require_canonical_uuid(value: str, *, code: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if str(parsed) != value:
        raise ValueError(code)


def _require_sha256(value: str, *, code: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(code)


def _require_diagnostic(value: str) -> None:
    if (
        not isinstance(value, str)
        or _DIAGNOSTIC_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("spot_eligibility_diagnostic_invalid")


def _category_diagnostic_codes(
    category: ApprovedSpotEligibilityCategory,
    outcome: SpotEligibilityReadOutcome,
) -> frozenset[str]:
    prefix = f"automation_spot_eligibility_{category.value.lower()}_"
    if outcome is SpotEligibilityReadOutcome.SUCCEEDED:
        suffixes = ("succeeded",)
    elif outcome is SpotEligibilityReadOutcome.REJECTED:
        suffixes = ("rejected", "stale", "future")
    else:
        suffixes = ("unknown",)
    return frozenset(f"{prefix}{suffix}" for suffix in suffixes)


def _require_category_diagnostic(
    value: str,
    *,
    category: ApprovedSpotEligibilityCategory,
    outcome: SpotEligibilityReadOutcome,
) -> None:
    _require_diagnostic(value)
    if value not in _category_diagnostic_codes(category, outcome):
        raise ValueError("spot_eligibility_diagnostic_invalid")


def _require_cycle_diagnostic(
    value: str,
    *,
    outcome: SpotEligibilityReadOutcome,
    attempted: tuple[ApprovedSpotEligibilityCategory, ...],
) -> None:
    _require_diagnostic(value)
    normalized_outcome = outcome.value.lower()
    allowed = {
        f"automation_spot_eligibility_{normalized_outcome}",
        f"automation_spot_eligibility_cycle_{normalized_outcome}",
    }
    if attempted:
        allowed.update(_category_diagnostic_codes(attempted[-1], outcome))
    if value not in allowed:
        raise ValueError("spot_eligibility_diagnostic_invalid")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def derive_spot_eligibility_client_order_id(
    *,
    run_id: str,
    plan_sha256: str,
    goal_key: str = SPOT_ELIGIBILITY_CREATE_ONLY_GOAL_KEY,
) -> str:
    """Derive the single stable child identity for an approved plan."""

    _require_canonical_uuid(run_id, code="spot_eligibility_run_id_invalid")
    _require_sha256(plan_sha256, code="spot_eligibility_plan_hash_invalid")
    if goal_key not in _SPOT_ELIGIBILITY_GOAL_KEYS:
        raise ValueError("spot_eligibility_goal_key_invalid")
    identity = f"{goal_key}:{run_id}:{plan_sha256}"
    return str(uuid5(_SPOT_ELIGIBILITY_CLIENT_ORDER_NAMESPACE, identity))


@dataclass(frozen=True, slots=True)
class SpotEligibilityRunContext:
    """Immutable run and plan identity presented to the coordinator."""

    run_id: str
    definition_id: str
    definition_revision: int
    plan_sha256: str
    portfolio_id_sha256: str
    correlation_id: str
    goal_key: str = SPOT_ELIGIBILITY_CREATE_ONLY_GOAL_KEY

    def __post_init__(self) -> None:
        _require_canonical_uuid(
            self.run_id,
            code="spot_eligibility_run_id_invalid",
        )
        _require_canonical_uuid(
            self.definition_id,
            code="spot_eligibility_definition_id_invalid",
        )
        if (
            type(self.definition_revision) is not int
            or self.definition_revision < 1
        ):
            raise ValueError("spot_eligibility_definition_revision_invalid")
        _require_sha256(
            self.plan_sha256,
            code="spot_eligibility_plan_hash_invalid",
        )
        _require_sha256(
            self.portfolio_id_sha256,
            code="spot_eligibility_portfolio_hash_invalid",
        )
        if self.goal_key not in _SPOT_ELIGIBILITY_GOAL_KEYS:
            raise ValueError("spot_eligibility_goal_key_invalid")
        if (
            not isinstance(self.correlation_id, str)
            or not self.correlation_id.strip()
            or len(self.correlation_id) > 255
            or not self.correlation_id.isprintable()
        ):
            raise ValueError("spot_eligibility_correlation_id_invalid")


@dataclass(frozen=True, slots=True)
class SpotEligibilityReadContext:
    """Exact identity and scope supplied to every approved read."""

    run_id: str
    definition_id: str
    definition_revision: int
    plan_sha256: str
    portfolio_id_sha256: str
    correlation_id: str
    cycle_number: int
    product_id: str
    client_order_id: str
    goal_key: str = SPOT_ELIGIBILITY_CREATE_ONLY_GOAL_KEY

    def __post_init__(self) -> None:
        SpotEligibilityRunContext(
            run_id=self.run_id,
            definition_id=self.definition_id,
            definition_revision=self.definition_revision,
            plan_sha256=self.plan_sha256,
            portfolio_id_sha256=self.portfolio_id_sha256,
            correlation_id=self.correlation_id,
            goal_key=self.goal_key,
        )
        if type(self.cycle_number) is not int or self.cycle_number < 1:
            raise ValueError("spot_eligibility_cycle_number_invalid")
        if self.product_id != SPOT_ELIGIBILITY_PRODUCT_ID:
            raise ValueError("spot_eligibility_product_invalid")
        _require_canonical_uuid(
            self.client_order_id,
            code="spot_eligibility_client_order_id_invalid",
        )


@dataclass(frozen=True, slots=True)
class SpotEligibilityReadResult:
    """Sanitized evidence and exact request accounting from one read."""

    outcome: SpotEligibilityReadOutcome
    eligible: bool
    logical_call_count: int
    http_request_count: int | None
    call_count_exact: bool
    observed_at: datetime
    evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, SpotEligibilityReadOutcome):
            raise ValueError("spot_eligibility_read_outcome_invalid")
        if type(self.eligible) is not bool:
            raise ValueError("spot_eligibility_read_result_invalid")
        if type(self.logical_call_count) is not int or self.logical_call_count != 1:
            raise ValueError("spot_eligibility_logical_call_count_invalid")
        if type(self.call_count_exact) is not bool:
            raise ValueError("spot_eligibility_call_count_exact_invalid")
        _require_aware(
            self.observed_at,
            code="spot_eligibility_observed_at_invalid",
        )
        if self.evidence_sha256 is not None:
            _require_sha256(
                self.evidence_sha256,
                code="spot_eligibility_evidence_hash_invalid",
            )
        if self.outcome is SpotEligibilityReadOutcome.UNKNOWN:
            if (
                self.eligible
                or self.call_count_exact
                or self.http_request_count is not None
                or self.evidence_sha256 is not None
            ):
                raise ValueError("spot_eligibility_read_accounting_invalid")
            return
        if (
            not self.call_count_exact
            or type(self.http_request_count) is not int
            or self.http_request_count < 0
        ):
            raise ValueError("spot_eligibility_read_accounting_invalid")
        if self.outcome is SpotEligibilityReadOutcome.SUCCEEDED:
            if (
                not self.eligible
                or self.http_request_count < 1
                or self.evidence_sha256 is None
            ):
                raise ValueError("spot_eligibility_read_result_invalid")
        elif self.eligible:
            raise ValueError("spot_eligibility_read_result_invalid")


@dataclass(frozen=True, slots=True)
class SpotEligibilityCategoryClaim:
    """Ledger claim authorizing one category invocation."""

    cycle_number: int
    category: ApprovedSpotEligibilityCategory
    claimed_at: datetime

    def __post_init__(self) -> None:
        if type(self.cycle_number) is not int or self.cycle_number < 1:
            raise ValueError("spot_eligibility_cycle_number_invalid")
        if not isinstance(self.category, ApprovedSpotEligibilityCategory):
            raise ValueError("spot_eligibility_category_invalid")
        _require_aware(
            self.claimed_at,
            code="spot_eligibility_claimed_at_invalid",
        )


@dataclass(frozen=True, slots=True)
class SpotEligibilityCategoryResult:
    """Sanitized final result written for one consumed category claim."""

    category: ApprovedSpotEligibilityCategory
    outcome: SpotEligibilityReadOutcome
    eligible: bool
    logical_call_count: int
    http_request_count: int | None
    call_count_exact: bool
    observed_at: datetime
    fresh_until: datetime | None
    evidence_sha256: str | None
    diagnostic_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.category, ApprovedSpotEligibilityCategory):
            raise ValueError("spot_eligibility_category_invalid")
        if not isinstance(self.outcome, SpotEligibilityReadOutcome):
            raise ValueError("spot_eligibility_result_outcome_invalid")
        if type(self.eligible) is not bool:
            raise ValueError("spot_eligibility_result_invalid")
        if type(self.logical_call_count) is not int or self.logical_call_count != 1:
            raise ValueError("spot_eligibility_logical_call_count_invalid")
        if type(self.call_count_exact) is not bool:
            raise ValueError("spot_eligibility_call_count_exact_invalid")
        _require_aware(
            self.observed_at,
            code="spot_eligibility_observed_at_invalid",
        )
        if self.fresh_until is not None:
            _require_aware(
                self.fresh_until,
                code="spot_eligibility_fresh_until_invalid",
            )
        if self.evidence_sha256 is not None:
            _require_sha256(
                self.evidence_sha256,
                code="spot_eligibility_evidence_hash_invalid",
            )
        _require_category_diagnostic(
            self.diagnostic_code,
            category=self.category,
            outcome=self.outcome,
        )
        if self.outcome is SpotEligibilityReadOutcome.UNKNOWN:
            if (
                self.eligible
                or self.call_count_exact
                or self.http_request_count is not None
                or self.fresh_until is not None
                or self.evidence_sha256 is not None
            ):
                raise ValueError("spot_eligibility_result_accounting_invalid")
            return
        if (
            not self.call_count_exact
            or type(self.http_request_count) is not int
            or self.http_request_count < 0
        ):
            raise ValueError("spot_eligibility_result_accounting_invalid")
        if self.outcome is SpotEligibilityReadOutcome.SUCCEEDED:
            if (
                not self.eligible
                or self.http_request_count < 1
                or self.fresh_until is None
                or self.evidence_sha256 is None
            ):
                raise ValueError("spot_eligibility_result_invalid")
        elif self.eligible:
            raise ValueError("spot_eligibility_result_invalid")


@dataclass(frozen=True, slots=True)
class SpotEligibilityCycleResult:
    """Sanitized aggregate result for one fixed-order cycle."""

    cycle_number: int
    outcome: SpotEligibilityReadOutcome
    eligible: bool
    attempted_categories: tuple[ApprovedSpotEligibilityCategory, ...]
    completed_categories: tuple[ApprovedSpotEligibilityCategory, ...]
    logical_call_count: int
    coinbase_api_call_count: int | None
    call_count_exact: bool
    fresh_until: datetime | None
    client_order_id: str
    diagnostic_code: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if type(self.cycle_number) is not int or self.cycle_number < 1:
            raise ValueError("spot_eligibility_cycle_number_invalid")
        if not isinstance(self.outcome, SpotEligibilityReadOutcome):
            raise ValueError("spot_eligibility_cycle_outcome_invalid")
        if type(self.eligible) is not bool or type(self.replayed) is not bool:
            raise ValueError("spot_eligibility_cycle_result_invalid")
        attempted_count = len(self.attempted_categories)
        if self.attempted_categories != APPROVED_SPOT_ELIGIBILITY_ORDER[
            :attempted_count
        ]:
            raise ValueError("spot_eligibility_attempt_order_invalid")
        completed_count = len(self.completed_categories)
        if self.completed_categories != APPROVED_SPOT_ELIGIBILITY_ORDER[
            :completed_count
        ]:
            raise ValueError("spot_eligibility_completion_order_invalid")
        if completed_count > attempted_count:
            raise ValueError("spot_eligibility_completion_count_invalid")
        if (
            type(self.logical_call_count) is not int
            or self.logical_call_count != attempted_count
        ):
            raise ValueError("spot_eligibility_logical_call_count_invalid")
        if type(self.call_count_exact) is not bool:
            raise ValueError("spot_eligibility_call_count_exact_invalid")
        if self.call_count_exact:
            if (
                type(self.coinbase_api_call_count) is not int
                or self.coinbase_api_call_count < 0
                or self.coinbase_api_call_count < completed_count
            ):
                raise ValueError("spot_eligibility_cycle_accounting_invalid")
        elif self.coinbase_api_call_count is not None:
            raise ValueError("spot_eligibility_cycle_accounting_invalid")
        if self.fresh_until is not None:
            _require_aware(
                self.fresh_until,
                code="spot_eligibility_fresh_until_invalid",
            )
        _require_canonical_uuid(
            self.client_order_id,
            code="spot_eligibility_client_order_id_invalid",
        )
        _require_cycle_diagnostic(
            self.diagnostic_code,
            outcome=self.outcome,
            attempted=self.attempted_categories,
        )
        if self.outcome is SpotEligibilityReadOutcome.SUCCEEDED:
            if (
                not self.eligible
                or attempted_count != len(APPROVED_SPOT_ELIGIBILITY_ORDER)
                or completed_count != attempted_count
                or not self.call_count_exact
                or self.fresh_until is None
            ):
                raise ValueError("spot_eligibility_cycle_result_invalid")
        elif self.outcome is SpotEligibilityReadOutcome.UNKNOWN:
            if (
                self.eligible
                or self.call_count_exact
                or self.coinbase_api_call_count is not None
                or self.fresh_until is not None
            ):
                raise ValueError("spot_eligibility_cycle_result_invalid")
        elif (
            self.eligible
            or not self.call_count_exact
            or self.coinbase_api_call_count is None
            or attempted_count == 0
            or completed_count != attempted_count - 1
        ):
            raise ValueError("spot_eligibility_cycle_result_invalid")


@dataclass(frozen=True, slots=True)
class SpotEligibilityCycleClaim:
    """Ledger response for a new cycle or an idempotent replay."""

    cycle_number: int
    client_order_id: str
    started_at: datetime
    replayed: bool = False
    terminal_result: SpotEligibilityCycleResult | None = None

    def __post_init__(self) -> None:
        if type(self.cycle_number) is not int or self.cycle_number < 1:
            raise ValueError("spot_eligibility_cycle_number_invalid")
        _require_canonical_uuid(
            self.client_order_id,
            code="spot_eligibility_client_order_id_invalid",
        )
        _require_aware(
            self.started_at,
            code="spot_eligibility_started_at_invalid",
        )
        if type(self.replayed) is not bool:
            raise ValueError("spot_eligibility_replay_flag_invalid")
        if not self.replayed and self.terminal_result is not None:
            raise ValueError("spot_eligibility_replay_result_invalid")
        if self.terminal_result is not None and (
            self.terminal_result.cycle_number != self.cycle_number
            or self.terminal_result.client_order_id != self.client_order_id
        ):
            raise ValueError("spot_eligibility_cycle_claim_mismatch")


class ApprovedSpotEligibilityReader(Protocol):
    """Only the eight reads approved for this bounded coordinator."""

    def read_api_key_permissions(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult: ...

    def read_portfolio_catalog(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult: ...

    def read_account_wallet_balances(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult: ...

    def read_product_metadata(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult: ...

    def read_best_bid_ask(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult: ...

    def read_fee_summary(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult: ...

    def read_exact_order_reconciliation(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult: ...

    def read_account_active_spot_order_catalog(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult: ...


class SpotEligibilityLedger(Protocol):
    """Atomic cycle and category boundaries required by the coordinator."""

    def claim_or_resume_cycle(
        self,
        context: SpotEligibilityRunContext,
    ) -> SpotEligibilityCycleClaim: ...

    def claim_category(
        self,
        context: SpotEligibilityRunContext,
        category: ApprovedSpotEligibilityCategory,
    ) -> SpotEligibilityCategoryClaim: ...

    def finalize_category(
        self,
        context: SpotEligibilityRunContext,
        claim: SpotEligibilityCategoryClaim,
        result: SpotEligibilityCategoryResult,
    ) -> None: ...


class SpotEligibilityCoordinatorConflict(RuntimeError):
    """Fixed, sanitized conflict emitted before any category invocation."""

    def __init__(self, code: str) -> None:
        _require_diagnostic(code)
        self.code = code
        super().__init__(code)


class SpotEligibilityCoordinator:
    """Run one claimed eligibility cycle in a fail-short fixed order."""

    def __init__(
        self,
        *,
        ledger: SpotEligibilityLedger,
        reader: ApprovedSpotEligibilityReader | None = None,
        reader_factory: Callable[[], ApprovedSpotEligibilityReader] | None = None,
        now_factory: Callable[[], datetime] = _utc_now,
        default_freshness: timedelta = _DEFAULT_FRESHNESS,
        best_bid_ask_freshness: timedelta = _BEST_BID_ASK_FRESHNESS,
        active_order_catalog_freshness: timedelta = (
            _ACTIVE_ORDER_CATALOG_FRESHNESS
        ),
    ) -> None:
        self._require_freshness(default_freshness)
        self._require_freshness(best_bid_ask_freshness)
        self._require_freshness(active_order_catalog_freshness)
        if (reader is None) is (reader_factory is None):
            raise ValueError("spot_eligibility_reader_binding_invalid")
        if reader_factory is not None and not callable(reader_factory):
            raise ValueError("spot_eligibility_reader_binding_invalid")
        self._ledger = ledger
        self._reader = reader
        self._reader_factory = reader_factory
        self._now_factory = now_factory
        self._default_freshness = default_freshness
        self._best_bid_ask_freshness = best_bid_ask_freshness
        self._active_order_catalog_freshness = active_order_catalog_freshness

    @staticmethod
    def _require_freshness(value: timedelta) -> None:
        if not isinstance(value, timedelta) or value <= timedelta(0):
            raise ValueError("spot_eligibility_freshness_invalid")

    def run(
        self,
        context: SpotEligibilityRunContext,
    ) -> SpotEligibilityCycleResult:
        if not isinstance(context, SpotEligibilityRunContext):
            raise ValueError("spot_eligibility_context_invalid")
        cycle = self._ledger.claim_or_resume_cycle(context)
        if not isinstance(cycle, SpotEligibilityCycleClaim):
            raise ValueError("spot_eligibility_cycle_claim_invalid")
        client_order_id = derive_spot_eligibility_client_order_id(
            run_id=context.run_id,
            plan_sha256=context.plan_sha256,
            goal_key=context.goal_key,
        )
        if cycle.client_order_id != client_order_id:
            raise ValueError("spot_eligibility_cycle_claim_mismatch")
        if cycle.replayed:
            if cycle.terminal_result is None:
                raise SpotEligibilityCoordinatorConflict(
                    "automation_spot_eligibility_cycle_in_progress"
                )
            return replace(cycle.terminal_result, replayed=True)

        reader = self._reader
        if reader is None:
            try:
                assert self._reader_factory is not None
                reader = self._reader_factory()
                required_reader_methods = (
                    "read_api_key_permissions",
                    "read_portfolio_catalog",
                    "read_account_wallet_balances",
                    "read_product_metadata",
                    "read_best_bid_ask",
                    "read_fee_summary",
                    "read_exact_order_reconciliation",
                    "read_account_active_spot_order_catalog",
                )
                if reader is None or any(
                    not callable(getattr(reader, method_name, None))
                    for method_name in required_reader_methods
                ):
                    raise TypeError
            except Exception:
                category = (
                    ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS
                )
                claim = self._ledger.claim_category(context, category)
                if (
                    not isinstance(claim, SpotEligibilityCategoryClaim)
                    or claim.cycle_number != cycle.cycle_number
                    or claim.category is not category
                ):
                    raise ValueError("spot_eligibility_cycle_claim_mismatch")
                rejected = SpotEligibilityCategoryResult(
                    category=category,
                    outcome=SpotEligibilityReadOutcome.REJECTED,
                    eligible=False,
                    logical_call_count=1,
                    http_request_count=0,
                    call_count_exact=True,
                    observed_at=claim.claimed_at,
                    fresh_until=None,
                    evidence_sha256=None,
                    diagnostic_code=(
                        "automation_spot_eligibility_"
                        "api_key_permissions_rejected"
                    ),
                )
                self._ledger.finalize_category(context, claim, rejected)
                return self._aggregate(
                    cycle=cycle,
                    finalized=(rejected,),
                )

        read_context = SpotEligibilityReadContext(
            run_id=context.run_id,
            definition_id=context.definition_id,
            definition_revision=context.definition_revision,
            plan_sha256=context.plan_sha256,
            portfolio_id_sha256=context.portfolio_id_sha256,
            correlation_id=context.correlation_id,
            cycle_number=cycle.cycle_number,
            product_id=SPOT_ELIGIBILITY_PRODUCT_ID,
            client_order_id=client_order_id,
            goal_key=context.goal_key,
        )
        operations = (
            (
                ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS,
                reader.read_api_key_permissions,
            ),
            (
                ApprovedSpotEligibilityCategory.PORTFOLIO_CATALOG,
                reader.read_portfolio_catalog,
            ),
            (
                ApprovedSpotEligibilityCategory.ACCOUNT_WALLET_BALANCES,
                reader.read_account_wallet_balances,
            ),
            (
                ApprovedSpotEligibilityCategory.PRODUCT_METADATA,
                reader.read_product_metadata,
            ),
            (
                ApprovedSpotEligibilityCategory.BEST_BID_ASK,
                reader.read_best_bid_ask,
            ),
            (
                ApprovedSpotEligibilityCategory.FEE_SUMMARY,
                reader.read_fee_summary,
            ),
            (
                ApprovedSpotEligibilityCategory.EXACT_ORDER_RECONCILIATION,
                reader.read_exact_order_reconciliation,
            ),
            (
                ApprovedSpotEligibilityCategory.ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG,
                reader.read_account_active_spot_order_catalog,
            ),
        )

        finalized: list[SpotEligibilityCategoryResult] = []
        for category, operation in operations:
            claim = self._ledger.claim_category(context, category)
            if (
                not isinstance(claim, SpotEligibilityCategoryClaim)
                or claim.cycle_number != cycle.cycle_number
                or claim.category is not category
            ):
                raise ValueError("spot_eligibility_cycle_claim_mismatch")
            result = self._invoke_once(
                category=category,
                claim=claim,
                read_context=read_context,
                operation=operation,
            )
            self._ledger.finalize_category(context, claim, result)
            finalized.append(result)
            if (
                result.outcome is not SpotEligibilityReadOutcome.SUCCEEDED
                or not result.eligible
            ):
                break

        return self._aggregate(
            cycle=cycle,
            finalized=tuple(finalized),
        )

    def _invoke_once(
        self,
        *,
        category: ApprovedSpotEligibilityCategory,
        claim: SpotEligibilityCategoryClaim,
        read_context: SpotEligibilityReadContext,
        operation: Callable[
            [SpotEligibilityReadContext],
            SpotEligibilityReadResult,
        ],
    ) -> SpotEligibilityCategoryResult:
        try:
            read_result = operation(read_context)
            if not isinstance(read_result, SpotEligibilityReadResult):
                raise TypeError
            now = self._now_factory()
            _require_aware(now, code="spot_eligibility_clock_invalid")
            return self._normalize_result(
                category=category,
                read_result=read_result,
                now=now,
            )
        except Exception:
            return self._unknown_result(category=category, claim=claim)

    @staticmethod
    def _unknown_result(
        *,
        category: ApprovedSpotEligibilityCategory,
        claim: SpotEligibilityCategoryClaim,
    ) -> SpotEligibilityCategoryResult:
        return SpotEligibilityCategoryResult(
            category=category,
            outcome=SpotEligibilityReadOutcome.UNKNOWN,
            eligible=False,
            logical_call_count=1,
            http_request_count=None,
            call_count_exact=False,
            observed_at=claim.claimed_at,
            fresh_until=None,
            evidence_sha256=None,
            diagnostic_code=(
                f"automation_spot_eligibility_{category.value.lower()}_unknown"
            ),
        )

    def _normalize_result(
        self,
        *,
        category: ApprovedSpotEligibilityCategory,
        read_result: SpotEligibilityReadResult,
        now: datetime,
    ) -> SpotEligibilityCategoryResult:
        suffix = read_result.outcome.value.lower()
        outcome = read_result.outcome
        eligible = read_result.eligible

        if read_result.outcome is SpotEligibilityReadOutcome.UNKNOWN:
            return SpotEligibilityCategoryResult(
                category=category,
                outcome=read_result.outcome,
                eligible=False,
                logical_call_count=read_result.logical_call_count,
                http_request_count=None,
                call_count_exact=False,
                observed_at=read_result.observed_at,
                fresh_until=None,
                evidence_sha256=None,
                diagnostic_code=(
                    f"automation_spot_eligibility_{category.value.lower()}_unknown"
                ),
            )
        if read_result.observed_at > now:
            return SpotEligibilityCategoryResult(
                category=category,
                outcome=SpotEligibilityReadOutcome.REJECTED,
                eligible=False,
                logical_call_count=read_result.logical_call_count,
                http_request_count=read_result.http_request_count,
                call_count_exact=read_result.call_count_exact,
                observed_at=read_result.observed_at,
                fresh_until=None,
                evidence_sha256=read_result.evidence_sha256,
                diagnostic_code=(
                    f"automation_spot_eligibility_{category.value.lower()}_future"
                ),
            )

        freshness = self._freshness_for(category)
        fresh_until = read_result.observed_at + freshness
        if now >= fresh_until:
            suffix = "stale"
            outcome = SpotEligibilityReadOutcome.REJECTED
            eligible = False

        return SpotEligibilityCategoryResult(
            category=category,
            outcome=outcome,
            eligible=eligible,
            logical_call_count=read_result.logical_call_count,
            http_request_count=read_result.http_request_count,
            call_count_exact=read_result.call_count_exact,
            observed_at=read_result.observed_at,
            fresh_until=fresh_until,
            evidence_sha256=read_result.evidence_sha256,
            diagnostic_code=(
                f"automation_spot_eligibility_{category.value.lower()}_{suffix}"
            ),
        )

    def _freshness_for(
        self,
        category: ApprovedSpotEligibilityCategory,
    ) -> timedelta:
        if category is ApprovedSpotEligibilityCategory.BEST_BID_ASK:
            return self._best_bid_ask_freshness
        if (
            category
            is ApprovedSpotEligibilityCategory.ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG
        ):
            return self._active_order_catalog_freshness
        return self._default_freshness

    @staticmethod
    def _aggregate(
        *,
        cycle: SpotEligibilityCycleClaim,
        finalized: tuple[SpotEligibilityCategoryResult, ...],
    ) -> SpotEligibilityCycleResult:
        terminal = finalized[-1]
        succeeded = tuple(
            item.category
            for item in finalized
            if item.outcome is SpotEligibilityReadOutcome.SUCCEEDED
            and item.eligible
        )
        eligible = len(succeeded) == len(APPROVED_SPOT_ELIGIBILITY_ORDER)
        outcome = (
            SpotEligibilityReadOutcome.SUCCEEDED
            if eligible
            else terminal.outcome
        )
        exact = all(item.call_count_exact for item in finalized)
        call_count = (
            sum(item.http_request_count or 0 for item in finalized)
            if exact
            else None
        )
        fresh_values = tuple(
            item.fresh_until
            for item in finalized
            if item.fresh_until is not None
        )
        fresh_until = (
            min(fresh_values)
            if fresh_values and outcome is not SpotEligibilityReadOutcome.UNKNOWN
            else None
        )
        diagnostic = (
            "automation_spot_eligibility_succeeded"
            if eligible
            else terminal.diagnostic_code
        )
        return SpotEligibilityCycleResult(
            cycle_number=cycle.cycle_number,
            outcome=outcome,
            eligible=eligible,
            attempted_categories=tuple(item.category for item in finalized),
            completed_categories=succeeded,
            logical_call_count=sum(
                item.logical_call_count for item in finalized
            ),
            coinbase_api_call_count=call_count,
            call_count_exact=exact,
            fresh_until=fresh_until,
            client_order_id=cycle.client_order_id,
            diagnostic_code=diagnostic,
        )
