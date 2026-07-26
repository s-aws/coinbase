"""Goal 13 canonical Futures Hotpoint execution primitives.

This module keeps Hotpoint trigger evidence separate from final exchange
terms.  A trigger may select one backend-owned BUY parent, but the six-category
Default-profile refresh remains the sole source of the immutable Preview/Create
candidate.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
import hashlib
import json
import re
from types import SimpleNamespace
from typing import Any
import uuid

from core.enums import (
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)
from core.runtime_controller import (
    INFLIGHT_REST_CANCEL,
    INFLIGHT_REST_PLACE,
    get_runtime_controller,
)

from .operator_futures_manual_lifecycle import (
    FUTURES_MANUAL_ELIGIBILITY_CATEGORIES,
    FUTURES_MANUAL_MAX_CANDIDATE_AGE_SECONDS,
    FUTURES_MANUAL_MARGIN_SUBREADS,
    FuturesManualEligibilityResult,
    FuturesHotpointExternalCommandReadback,
    FuturesManualGoalRecord,
    FuturesManualLifecycleError,
    FuturesManualLifecycleRepository,
    FuturesManualRequestContext,
)
from .operator_futures_product_ticket import (
    FuturesProductPolicySelection,
    FuturesProductTicketEligibilityReader,
)
from .operator_hotpoint_control import (
    FUTURES_HOTPOINT_GOAL_ID,
    FUTURES_HOTPOINT_SCOPE_POLICY,
    HOTPOINT_CONTROL_OPERATOR_INTENT,
    HOTPOINT_RUN_OPERATOR_INTENT,
    HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
    HotpointControlAction,
    HotpointCancelState,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointWindowState,
    OperatorHotpointControlError,
    OperatorHotpointControlRecord,
    OperatorHotpointControlRepository,
    OperatorHotpointControlService,
    OperatorHotpointRequestContext,
)


FUTURES_HOTPOINT_PRODUCT_ID = "AVP-20DEC30-CDE"
FUTURES_HOTPOINT_POLICY_REVISION = 1
FUTURES_HOTPOINT_POLICY_BINDING = {
    "goal_id": FUTURES_HOTPOINT_GOAL_ID,
    "profile_alias": "Default",
    "product_id": FUTURES_HOTPOINT_PRODUCT_ID,
    "side": "BUY",
    "contract_count": "1",
    "order_type": "LIMIT_GTC",
    "post_only": True,
    "opening_cap_usdc": "100",
    "exposure_cap_usdc": "150",
    "turnover_cap_usdc": "300",
    "comparison": "strictly_less_than",
    "session_policy": "open_24x7_gtc_compatible",
}
FUTURES_HOTPOINT_POLICY_SHA256 = hashlib.sha256(
    json.dumps(
        FUTURES_HOTPOINT_POLICY_BINDING,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
).hexdigest()

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_ORDER_STATUSES = frozenset(
    {"FILLED", "CANCELLED", "EXPIRED", "FAILED"}
)
_NONTERMINAL_ORDER_STATUSES = frozenset(
    {"PENDING", "OPEN", "QUEUED", "CANCEL_QUEUED", "EDIT_QUEUED"}
)
_CANCEL_ELIGIBLE_ORDER_STATUSES = frozenset({"OPEN"})
_DEFERRED_ORDER_STATUSES = frozenset(
    {"PENDING", "QUEUED", "EDIT_QUEUED"}
)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        return dict(attributes)
    return {}


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def validate_futures_hotpoint_candidate(
    candidate: Mapping[str, Any],
) -> dict[str, str]:
    """Validate immutable Goal13 policy/session fields without new reads."""

    code = "operator_futures_hotpoint_candidate_invalid"
    exact = {
        str(key): str(value)
        for key, value in dict(candidate).items()
    }
    try:
        limit_price = Decimal(exact["limit_price"])
        contract_size = Decimal(exact["contract_size"])
        product_price = Decimal(exact["product_price"])
        reference_price = Decimal(exact["reference_price"])
        price_increment = Decimal(exact["price_increment"])
        best_bid = Decimal(exact["best_bid"])
        best_ask = Decimal(exact["best_ask"])
        opening = Decimal(exact["opening_reference_notional_usdc"])
        exposure = Decimal(
            exact["maximum_exposure_reference_notional_usdc"]
        )
        buffered = Decimal(
            exact["buffered_close_reference_notional_usdc"]
        )
        turnover = Decimal(
            exact["branch_turnover_reference_notional_usdc"]
        )
        observed_at = datetime.fromisoformat(
            exact["observed_at"].replace("Z", "+00:00")
        )
        session_observed_at = datetime.fromisoformat(
            exact["session_observed_at"].replace("Z", "+00:00")
        )
        contract_expiry = datetime.fromisoformat(
            exact["contract_expiry"].replace("Z", "+00:00")
        )
        maintenance_start_text = exact["maintenance_start"]
        maintenance_end_text = exact["maintenance_end"]
        maintenance_start = (
            datetime.fromisoformat(
                maintenance_start_text.replace("Z", "+00:00")
            )
            if maintenance_start_text
            else None
        )
        maintenance_end = (
            datetime.fromisoformat(
                maintenance_end_text.replace("Z", "+00:00")
            )
            if maintenance_end_text
            else None
        )
    except (InvalidOperation, KeyError, TypeError, ValueError):
        raise ValueError(code) from None
    if (
        any(
            not value.is_finite() or value <= 0
            for value in (
                limit_price,
                contract_size,
                product_price,
                reference_price,
                price_increment,
                best_bid,
                best_ask,
                opening,
                exposure,
                buffered,
                turnover,
            )
        )
        or best_bid >= best_ask
        or reference_price != max(product_price, best_ask)
        or limit_price != best_bid - price_increment
        or limit_price % price_increment != 0
        or opening != reference_price * contract_size
        or exposure != opening
        or buffered != exposure * Decimal("1.20")
        or turnover != opening + buffered
        or opening >= Decimal("100")
        or exposure >= Decimal("150")
        or buffered >= Decimal("150")
        or turnover >= Decimal("300")
        or exact.get("product_id") != FUTURES_HOTPOINT_PRODUCT_ID
        or exact.get("side") != "BUY"
        or exact.get("order_type") != "LIMIT_GTC"
        or exact.get("post_only") != "true"
        or exact.get("contract_count") != "1"
        or exact.get("reference_price_source")
        != "max_product_price_and_fresh_best_ask"
        or exact.get("close_buffer_multiplier") != "1.20"
        or exact.get("opening_cap_usdc") != "100"
        or exact.get("exposure_cap_usdc") != "150"
        or exact.get("turnover_cap_usdc") != "300"
        or exact.get("product_policy_revision")
        != str(FUTURES_HOTPOINT_POLICY_REVISION)
        or exact.get("product_policy_sha256")
        != FUTURES_HOTPOINT_POLICY_SHA256
        or exact.get("hotpoint_session_compatibility")
        != "OPEN_24X7_GTC"
        or exact.get("session_state")
        != "FCM_TRADING_SESSION_STATE_OPEN"
        or exact.get("session_is_open") != "true"
        or exact.get("after_hours_order_entry_disabled") != "false"
        or exact.get("twenty_four_by_seven") != "true"
        or exact.get("session_closed_reason")
        not in {
            "",
            "FCM_TRADING_SESSION_CLOSED_REASON_UNSPECIFIED",
        }
        or not exact.get("hotpoint_parent_client_order_id")
        or not exact.get("hotpoint_window_id")
        or _SHA256_RE.fullmatch(
            exact.get("hotpoint_trigger_evidence_sha256", "")
        )
        is None
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or session_observed_at.tzinfo is None
        or session_observed_at.utcoffset() is None
        or contract_expiry.tzinfo is None
        or contract_expiry.utcoffset() is None
        or contract_expiry <= observed_at
        or contract_expiry <= session_observed_at
        or bool(maintenance_start) != bool(maintenance_end)
        or (
            maintenance_start is not None
            and (
                maintenance_start.tzinfo is None
                or maintenance_start.utcoffset() is None
                or maintenance_end is None
                or maintenance_end.tzinfo is None
                or maintenance_end.utcoffset() is None
                or maintenance_start >= maintenance_end
                or maintenance_start
                <= observed_at.astimezone(timezone.utc)
                < maintenance_end
            )
        )
    ):
        raise ValueError(code)
    return exact


def validate_futures_hotpoint_candidate_execution_window(
    candidate: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, str]:
    """Recheck stored market/session/expiry evidence at an SDK boundary."""

    code = "operator_futures_hotpoint_candidate_execution_window_invalid"
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(code)
    exact = validate_futures_hotpoint_candidate(candidate)
    try:
        observed_at = datetime.fromisoformat(
            exact["observed_at"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        session_observed_at = datetime.fromisoformat(
            exact["session_observed_at"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        contract_expiry = datetime.fromisoformat(
            exact["contract_expiry"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        maintenance_start = (
            datetime.fromisoformat(
                exact["maintenance_start"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if exact["maintenance_start"]
            else None
        )
        maintenance_end = (
            datetime.fromisoformat(
                exact["maintenance_end"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if exact["maintenance_end"]
            else None
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError(code) from None
    exact_now = now.astimezone(timezone.utc)
    market_age = (exact_now - observed_at).total_seconds()
    session_age = (
        exact_now - session_observed_at
    ).total_seconds()
    if (
        market_age < 0
        or market_age > FUTURES_MANUAL_MAX_CANDIDATE_AGE_SECONDS
        or session_age < 0
        or session_age > FUTURES_MANUAL_MAX_CANDIDATE_AGE_SECONDS
        or contract_expiry <= exact_now
        or (
            maintenance_start is not None
            and maintenance_end is not None
            and maintenance_start <= exact_now < maintenance_end
        )
    ):
        raise ValueError(code)
    return exact


def validate_futures_hotpoint_product_session(
    product: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    """Require documented open-session evidence compatible with resting GTC."""

    exact = _mapping(product)
    session = _mapping(exact.get("fcm_trading_session_details"))
    details = _mapping(exact.get("future_product_details"))
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("operator_futures_hotpoint_session_ineligible")
    observed_at = observed_at.astimezone(timezone.utc)
    closed_reason = str(session.get("closed_reason") or "").strip().upper()
    if closed_reason not in {
        "",
        "FCM_TRADING_SESSION_CLOSED_REASON_UNSPECIFIED",
    }:
        raise ValueError("operator_futures_hotpoint_session_ineligible")
    maintenance = _mapping(session.get("maintenance"))
    maintenance_start = str(
        maintenance.get("start_time") or ""
    ).strip()
    maintenance_end = str(
        maintenance.get("end_time") or ""
    ).strip()
    if bool(maintenance_start) != bool(maintenance_end):
        raise ValueError("operator_futures_hotpoint_session_ineligible")
    if maintenance_start:
        try:
            starts_at = datetime.fromisoformat(
                maintenance_start.replace("Z", "+00:00")
            )
            ends_at = datetime.fromisoformat(
                maintenance_end.replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            raise ValueError(
                "operator_futures_hotpoint_session_ineligible"
            ) from None
        if (
            starts_at.tzinfo is None
            or starts_at.utcoffset() is None
            or ends_at.tzinfo is None
            or ends_at.utcoffset() is None
        ):
            raise ValueError("operator_futures_hotpoint_session_ineligible")
        starts_at = starts_at.astimezone(timezone.utc)
        ends_at = ends_at.astimezone(timezone.utc)
        if starts_at >= ends_at or starts_at <= observed_at < ends_at:
            raise ValueError("operator_futures_hotpoint_session_ineligible")
    if (
        str(exact.get("status") or "").upper() != "ONLINE"
        or exact.get("trading_disabled") is not False
        or exact.get("view_only") is not False
        or exact.get("cancel_only") is not False
        or details.get("twenty_four_by_seven") is not True
        or session.get("is_session_open") is not True
        or session.get("after_hours_order_entry_disabled") is not False
        or session.get("session_state")
        != "FCM_TRADING_SESSION_STATE_OPEN"
    ):
        raise ValueError("operator_futures_hotpoint_session_ineligible")


def _futures_hotpoint_session_candidate_evidence(
    product: Mapping[str, Any],
) -> dict[str, str]:
    """Extract only fixed, documented session boundaries for later recheck."""

    exact = _mapping(product)
    session = _mapping(exact.get("fcm_trading_session_details"))
    details = _mapping(exact.get("future_product_details"))
    maintenance = _mapping(session.get("maintenance"))

    def timestamp(value: Any) -> str:
        parsed = datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")
        )
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(
                "operator_futures_hotpoint_session_ineligible"
            )
        return parsed.astimezone(timezone.utc).isoformat()

    maintenance_start = str(
        maintenance.get("start_time") or ""
    ).strip()
    maintenance_end = str(
        maintenance.get("end_time") or ""
    ).strip()
    if bool(maintenance_start) != bool(maintenance_end):
        raise ValueError("operator_futures_hotpoint_session_ineligible")
    return {
        "contract_expiry": timestamp(details.get("contract_expiry")),
        "session_state": str(
            session.get("session_state") or ""
        ).strip(),
        "session_is_open": (
            "true" if session.get("is_session_open") is True else "false"
        ),
        "after_hours_order_entry_disabled": (
            "true"
            if session.get("after_hours_order_entry_disabled") is True
            else "false"
        ),
        "session_closed_reason": str(
            session.get("closed_reason") or ""
        ).strip().upper(),
        "twenty_four_by_seven": (
            "true"
            if details.get("twenty_four_by_seven") is True
            else "false"
        ),
        "maintenance_start": (
            timestamp(maintenance_start) if maintenance_start else ""
        ),
        "maintenance_end": (
            timestamp(maintenance_end) if maintenance_end else ""
        ),
    }


def validate_futures_hotpoint_eligibility_evidence(
    result: FuturesManualEligibilityResult,
) -> None:
    """Validate the complete Goal13 evidence/candidate binding pre-persistence."""

    code = "operator_futures_hotpoint_eligible_evidence_invalid"
    if (
        not isinstance(result, FuturesManualEligibilityResult)
        or result.outcome
        is not AdminFuturesManualEligibilityOutcome.ELIGIBLE
        or result.diagnostic_code
        != "operator_futures_hotpoint_exact_v3_eligible"
        or result.candidate is None
        or _SHA256_RE.fullmatch(
            str(result.portfolio_id_sha256 or "")
        )
        is None
        or _SHA256_RE.fullmatch(str(result.evidence_sha256 or ""))
        is None
    ):
        raise ValueError(code)
    try:
        candidate = validate_futures_hotpoint_candidate(
            result.candidate
        )
    except Exception:
        raise ValueError(code) from None
    public = dict(result.public_evidence)
    parent_id = candidate.get("hotpoint_parent_client_order_id", "")
    window_id = candidate.get("hotpoint_window_id", "")
    trigger_hash = candidate.get(
        "hotpoint_trigger_evidence_sha256",
        "",
    )
    expected_attempts = {
        category: 1
        for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
    }
    expected_margin_subreads = {
        subread: 1 for subread in FUTURES_MANUAL_MARGIN_SUBREADS
    }
    try:
        opening = Decimal(
            candidate["opening_reference_notional_usdc"]
        )
        exposure = Decimal(
            candidate["maximum_exposure_reference_notional_usdc"]
        )
        buffered = Decimal(
            candidate["buffered_close_reference_notional_usdc"]
        )
        turnover = Decimal(
            candidate["branch_turnover_reference_notional_usdc"]
        )
    except (InvalidOperation, KeyError, TypeError, ValueError):
        raise ValueError(code) from None
    if (
        any(
            not value.is_finite() or value <= 0
            for value in (opening, exposure, buffered, turnover)
        )
        or opening >= Decimal("100")
        or exposure >= Decimal("150")
        or buffered >= Decimal("150")
        or turnover >= Decimal("300")
        or candidate.get("product_id") != FUTURES_HOTPOINT_PRODUCT_ID
        or candidate.get("side") != "BUY"
        or candidate.get("order_type") != "LIMIT_GTC"
        or candidate.get("post_only") != "true"
        or candidate.get("contract_count") != "1"
        or candidate.get("opening_cap_usdc") != "100"
        or candidate.get("exposure_cap_usdc") != "150"
        or candidate.get("turnover_cap_usdc") != "300"
        or candidate.get("product_policy_revision")
        != str(FUTURES_HOTPOINT_POLICY_REVISION)
        or candidate.get("product_policy_sha256")
        != FUTURES_HOTPOINT_POLICY_SHA256
        or candidate.get("hotpoint_session_compatibility")
        != "OPEN_24X7_GTC"
        or not parent_id
        or not window_id
        or _SHA256_RE.fullmatch(trigger_hash) is None
        or result.category_attempts != expected_attempts
        or public.get("goal_id") != FUTURES_HOTPOINT_GOAL_ID
        or public.get("profile_alias") != "Default"
        or public.get("portfolio_type") != "DEFAULT"
        or public.get("portfolio_id_sha256")
        != result.portfolio_id_sha256
        or public.get("credential_can_view") is not True
        or public.get("credential_can_trade") is not True
        or public.get("selection_authority")
        != "backend_futures_hotpoint_v2_policy"
        or public.get("product_id") != FUTURES_HOTPOINT_PRODUCT_ID
        or public.get("contract_count") != "1"
        or public.get("caps")
        != {
            "opening_usdc": "100",
            "exposure_usdc": "150",
            "turnover_usdc": "300",
            "comparison": "strictly_less_than",
        }
        or public.get("candidate") != candidate
        or public.get("parent_client_order_id_sha256")
        != hashlib.sha256(parent_id.encode("utf-8")).hexdigest()
        or public.get("window_id_sha256")
        != hashlib.sha256(window_id.encode("utf-8")).hexdigest()
        or public.get("trigger_evidence_sha256") != trigger_hash
        or public.get("exact_v3_eligible") is not True
        or public.get("diagnostic_code")
        != "operator_futures_hotpoint_exact_v3_eligible"
        or public.get("category_attempts") != expected_attempts
        or public.get("margin_subread_attempts")
        != expected_margin_subreads
        or public.get("raw_responses_included") is not False
        or public.get("private_identifiers_included") is not False
        or public.get("exception_text_included") is not False
        or _canonical_sha256(public) != result.evidence_sha256
    ):
        raise ValueError(code)


@dataclass(frozen=True, slots=True)
class FuturesHotpointTriggerBinding:
    parent_client_order_id: str
    window_id: str
    trigger_evidence_sha256: str

    def validate(self) -> "FuturesHotpointTriggerBinding":
        if (
            not str(self.parent_client_order_id or "").strip()
            or not str(self.window_id or "").strip()
            or _SHA256_RE.fullmatch(
                str(self.trigger_evidence_sha256 or "")
            )
            is None
        ):
            raise ValueError(
                "operator_futures_hotpoint_trigger_binding_invalid"
            )
        return self


class _SessionCheckingRestClient:
    def __init__(
        self,
        delegate: Any,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self.delegate = delegate
        self.now = now
        self.session_ineligible = False
        self.session_evidence: dict[str, str] | None = None
        self.session_observed_at: str | None = None
        self.market_observed_at: str | None = None

    def get_futures_manual_eligibility_product(
        self,
        product_id: str,
    ) -> Any:
        value = self.delegate.get_futures_manual_eligibility_product(
            product_id
        )
        try:
            validate_futures_hotpoint_product_session(
                _mapping(value),
                now=self.now(),
            )
            self.session_evidence = (
                _futures_hotpoint_session_candidate_evidence(
                    _mapping(value)
                )
            )
            observed = self.now()
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise ValueError
            self.session_observed_at = (
                observed.astimezone(timezone.utc).isoformat()
            )
        except ValueError:
            self.session_ineligible = True
            self.session_observed_at = None
            raise
        return value

    def get_best_bid_ask(self, *, product_ids: list[str]) -> Any:
        value = self.delegate.get_best_bid_ask(
            product_ids=product_ids
        )
        try:
            pricebooks = _mapping(value).get("pricebooks")
            if not isinstance(pricebooks, list) or len(pricebooks) != 1:
                raise ValueError
            row = _mapping(pricebooks[0])
            if row.get("product_id") != FUTURES_HOTPOINT_PRODUCT_ID:
                raise ValueError
            market_time = datetime.fromisoformat(
                str(row.get("time") or "").replace("Z", "+00:00")
            )
            if (
                market_time.tzinfo is None
                or market_time.utcoffset() is None
            ):
                raise ValueError
            self.market_observed_at = (
                market_time.astimezone(timezone.utc).isoformat()
            )
        except (TypeError, ValueError):
            self.market_observed_at = None
        return value

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


class FuturesHotpointEligibilityReader:
    """Run the established six reads and bind one Hotpoint trigger."""

    def __init__(
        self,
        *,
        rest_client: Any,
        trigger: FuturesHotpointTriggerBinding,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.trigger = trigger.validate()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.rest_client = _SessionCheckingRestClient(
            rest_client,
            now=self.now,
        )

    def run(
        self,
        *,
        before_category: Callable[[str], None],
        before_margin_subread: Callable[[str], None],
    ) -> FuturesManualEligibilityResult:
        margin_subread_attempts = {
            subread: 0 for subread in FUTURES_MANUAL_MARGIN_SUBREADS
        }

        def mark_margin_subread(subread: str) -> None:
            if (
                subread not in margin_subread_attempts
                or margin_subread_attempts[subread] != 0
            ):
                raise RuntimeError(
                    "operator_futures_hotpoint_duplicate_margin_subread"
                )
            before_margin_subread(subread)
            margin_subread_attempts[subread] = 1

        delegate = FuturesProductTicketEligibilityReader(
            rest_client=self.rest_client,
            selection_reader=lambda: FuturesProductPolicySelection(
                product_id=FUTURES_HOTPOINT_PRODUCT_ID,
                policy_revision=FUTURES_HOTPOINT_POLICY_REVISION,
                policy_sha256=FUTURES_HOTPOINT_POLICY_SHA256,
                lifecycle="ENABLED",
            ),
            now=self.now,
        )
        result = delegate.run(
            before_category=before_category,
            before_margin_subread=mark_margin_subread,
        )
        diagnostic = str(result.diagnostic_code)
        if self.rest_client.session_ineligible:
            diagnostic = "operator_futures_hotpoint_session_ineligible"
        elif diagnostic.startswith("operator_futures_product_ticket_"):
            diagnostic = diagnostic.replace(
                "operator_futures_product_ticket_",
                "operator_futures_hotpoint_",
                1,
            )

        candidate = (
            {str(key): str(value) for key, value in result.candidate.items()}
            if result.candidate is not None
            else None
        )
        outcome = result.outcome
        if self.rest_client.session_ineligible:
            outcome = AdminFuturesManualEligibilityOutcome.INELIGIBLE
            candidate = None
        if candidate is not None:
            if (
                self.rest_client.market_observed_at is None
                or self.rest_client.session_evidence is None
                or self.rest_client.session_observed_at is None
                or
                candidate.get("product_id") != FUTURES_HOTPOINT_PRODUCT_ID
                or candidate.get("side") != "BUY"
                or candidate.get("contract_count") != "1"
                or candidate.get("order_type") != "LIMIT_GTC"
                or candidate.get("post_only") != "true"
                or candidate.get("product_policy_revision")
                != str(FUTURES_HOTPOINT_POLICY_REVISION)
                or candidate.get("product_policy_sha256")
                != FUTURES_HOTPOINT_POLICY_SHA256
            ):
                outcome = AdminFuturesManualEligibilityOutcome.INELIGIBLE
                diagnostic = (
                    "operator_futures_hotpoint_candidate_policy_ineligible"
                )
                candidate = None
            else:
                candidate.update(
                    {
                        # The executable freshness anchor is the documented
                        # pricebook timestamp, not the later local receipt
                        # time used by the shared eligibility reader.
                        "observed_at": (
                            self.rest_client.market_observed_at
                        ),
                        "session_observed_at": (
                            self.rest_client.session_observed_at
                        ),
                        **self.rest_client.session_evidence,
                        "hotpoint_parent_client_order_id": (
                            self.trigger.parent_client_order_id
                        ),
                        "hotpoint_window_id": self.trigger.window_id,
                        "hotpoint_trigger_evidence_sha256": (
                            self.trigger.trigger_evidence_sha256
                        ),
                        "hotpoint_session_compatibility": (
                            "OPEN_24X7_GTC"
                        ),
                    }
                )
                diagnostic = (
                    "operator_futures_hotpoint_exact_v3_eligible"
                )

        public = {
            "goal_id": FUTURES_HOTPOINT_GOAL_ID,
            "profile_alias": "Default",
            "portfolio_type": (
                "DEFAULT" if result.portfolio_id_sha256 else None
            ),
            "portfolio_id_sha256": result.portfolio_id_sha256,
            "credential_can_view": bool(
                result.portfolio_id_sha256
                and outcome
                is AdminFuturesManualEligibilityOutcome.ELIGIBLE
            ),
            "credential_can_trade": bool(
                result.portfolio_id_sha256
                and outcome
                is AdminFuturesManualEligibilityOutcome.ELIGIBLE
            ),
            "selection_authority": (
                "backend_futures_hotpoint_v2_policy"
            ),
            "product_id": FUTURES_HOTPOINT_PRODUCT_ID,
            "contract_count": "1",
            "caps": {
                "opening_usdc": "100",
                "exposure_usdc": "150",
                "turnover_usdc": "300",
                "comparison": "strictly_less_than",
            },
            "candidate": candidate,
            "parent_client_order_id_sha256": hashlib.sha256(
                self.trigger.parent_client_order_id.encode("utf-8")
            ).hexdigest(),
            "window_id_sha256": hashlib.sha256(
                self.trigger.window_id.encode("utf-8")
            ).hexdigest(),
            "trigger_evidence_sha256": (
                self.trigger.trigger_evidence_sha256
            ),
            "exact_v3_eligible": bool(
                candidate is not None
                and outcome
                is AdminFuturesManualEligibilityOutcome.ELIGIBLE
            ),
            "diagnostic_code": diagnostic,
            "category_attempts": dict(result.category_attempts),
            "margin_subread_attempts": dict(
                margin_subread_attempts
            ),
            "raw_responses_included": False,
            "private_identifiers_included": False,
            "exception_text_included": False,
        }
        return FuturesManualEligibilityResult(
            outcome=outcome,
            diagnostic_code=diagnostic,
            category_attempts=dict(result.category_attempts),
            candidate=candidate,
            portfolio_id_sha256=(
                result.portfolio_id_sha256
                if candidate is not None
                else None
            ),
            evidence_sha256=_canonical_sha256(public),
            public_evidence=public,
        )


@dataclass(frozen=True, slots=True)
class FuturesHotpointReconciliationExecution:
    outcome: AdminFuturesManualCallOutcome
    diagnostic_code: str
    exchange_order_id_sha256: str | None
    order_status: str | None
    authoritatively_nonterminal: bool | None
    public_evidence: dict[str, Any]
    private_exchange_order_id: str | None = None


class FuturesHotpointExactCloseoutExecutor:
    """Resolve one exact Goal13 child from one complete List Orders page."""

    def __init__(
        self,
        *,
        rest_client: Any,
        configured_portfolio_id: str,
    ) -> None:
        self.rest_client = rest_client
        try:
            self.configured_portfolio_id = str(
                uuid.UUID(str(configured_portfolio_id))
            )
        except (AttributeError, TypeError, ValueError):
            raise ValueError(
                "operator_futures_hotpoint_default_portfolio_invalid"
            ) from None

    @staticmethod
    def _unknown(
        exchange_hash: str | None = None,
    ) -> FuturesHotpointReconciliationExecution:
        return FuturesHotpointReconciliationExecution(
            outcome=AdminFuturesManualCallOutcome.UNKNOWN,
            diagnostic_code=(
                "operator_futures_hotpoint_reconciliation_outcome_unknown"
            ),
            exchange_order_id_sha256=exchange_hash,
            order_status=None,
            authoritatively_nonterminal=None,
            public_evidence={
                "exchange_order_id_sha256": exchange_hash,
                "raw_response_included": False,
                "private_identifiers_included": False,
                "exception_text_included": False,
            },
            private_exchange_order_id=None,
        )

    def reconcile(
        self,
        *,
        candidate: Mapping[str, Any],
        client_order_id: str,
        expected_exchange_order_id_sha256: str | None,
        reconciliation_catalog_end_at: str,
        before_call: Callable[[], None],
    ) -> FuturesHotpointReconciliationExecution:
        exact = {str(key): str(value) for key, value in candidate.items()}
        child_id = str(client_order_id or "").strip()
        expected_hash = str(
            expected_exchange_order_id_sha256 or ""
        ).lower()
        if expected_hash and _SHA256_RE.fullmatch(expected_hash) is None:
            return self._unknown()
        try:
            if (
                not child_id
                or exact.get("product_id")
                != FUTURES_HOTPOINT_PRODUCT_ID
                or exact.get("side") != "BUY"
                or exact.get("contract_count") != "1"
                or exact.get("order_type") != "LIMIT_GTC"
                or exact.get("post_only") != "true"
                or not exact.get("observed_at")
            ):
                raise ValueError("candidate_invalid")
            starts_at = datetime.fromisoformat(
                exact["observed_at"].replace("Z", "+00:00")
            )
            ends_at = datetime.fromisoformat(
                str(reconciliation_catalog_end_at or "")
                .strip()
                .replace("Z", "+00:00")
            )
            if (
                starts_at.tzinfo is None
                or starts_at.utcoffset() is None
                or ends_at.tzinfo is None
                or ends_at.utcoffset() is None
                or starts_at.astimezone(timezone.utc)
                >= ends_at.astimezone(timezone.utc)
            ):
                raise ValueError("catalog_window_invalid")
            response = self.rest_client.list_orders(
                order_status=None,
                product_ids=[FUTURES_HOTPOINT_PRODUCT_ID],
                product_type="FUTURE",
                order_side="BUY",
                order_types="LIMIT",
                time_in_forces="GOOD_UNTIL_CANCELLED",
                limit=100,
                start_date=exact["observed_at"],
                end_date=str(reconciliation_catalog_end_at),
                cursor=None,
                before_sdk_call=before_call,
            )
            page = _mapping(response)
            if page.get("has_next") is not False:
                raise ValueError("incomplete_page")
            raw_orders = page.get("orders")
            if not isinstance(raw_orders, list):
                raise ValueError("orders_invalid")
            rows = [_mapping(item) for item in raw_orders]
            if any(
                row.get("product_id") != FUTURES_HOTPOINT_PRODUCT_ID
                for row in rows
            ):
                raise ValueError("product_scope_invalid")
            matches = [
                row
                for row in rows
                if str(row.get("client_order_id") or "") == child_id
            ]
            if len(matches) != 1:
                raise ValueError("identity_ambiguous")
            row = matches[0]
            exchange_order_id = str(row.get("order_id") or "").strip()
            exchange_hash = hashlib.sha256(
                exchange_order_id.encode("utf-8")
            ).hexdigest()
            configuration = _mapping(row.get("order_configuration"))
            gtc = _mapping(configuration.get("limit_limit_gtc"))
            if (
                not exchange_order_id
                or row.get("side") != "BUY"
                or str(row.get("order_type") or "").upper() != "LIMIT"
                or str(row.get("time_in_force") or "").upper()
                != "GOOD_UNTIL_CANCELLED"
                or Decimal(str(gtc.get("base_size"))) != Decimal("1")
                or Decimal(str(gtc.get("limit_price")))
                != Decimal(exact["limit_price"])
                or gtc.get("post_only") is not True
                or (expected_hash and exchange_hash != expected_hash)
            ):
                raise ValueError("order_binding_invalid")
            status = str(row.get("status") or "").upper()
            if status not in (
                _TERMINAL_ORDER_STATUSES
                | _NONTERMINAL_ORDER_STATUSES
            ):
                raise ValueError("status_invalid")
            return FuturesHotpointReconciliationExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_hotpoint_reconciliation_accepted"
                ),
                exchange_order_id_sha256=exchange_hash,
                order_status=status,
                authoritatively_nonterminal=(
                    status in _NONTERMINAL_ORDER_STATUSES
                ),
                public_evidence={
                    "client_order_id": child_id,
                    "product_id": FUTURES_HOTPOINT_PRODUCT_ID,
                    "side": "BUY",
                    "contract_count": "1",
                    "order_type": "LIMIT_GTC",
                    "post_only": True,
                    "status": status,
                    "exchange_order_id_sha256": exchange_hash,
                    "raw_response_included": False,
                    "private_identifiers_included": False,
                    "exception_text_included": False,
                },
                private_exchange_order_id=exchange_order_id,
            )
        except Exception:
            return self._unknown(expected_hash or None)


@dataclass(frozen=True, slots=True)
class OperatorFuturesHotpointReadback:
    """Sanitized combined authority for the routed Goal13 workspace."""

    goal_id: str
    revision: int
    control_revision: int
    lifecycle_revision: int
    control: OperatorHotpointControlRecord
    lifecycle: FuturesManualGoalRecord
    allowed_actions: tuple[str, ...]
    cancel_disposition: str | None
    diagnostic_code: str
    trigger_fill_count: int
    trigger_evidence_sha256: str | None
    window_id_sha256: str | None
    latest_external_command: (
        FuturesHotpointExternalCommandReadback | None
    ) = None


def _operator_context_valid(
    context: OperatorHotpointRequestContext,
    *,
    intent: str,
) -> bool:
    roles = {
        str(role).strip().lower()
        for role in getattr(context, "roles", ())
    }
    return bool(
        isinstance(context, OperatorHotpointRequestContext)
        and context.operator_intent == intent
        and str(context.actor_id or "").strip()
        and str(context.idempotency_key or "").strip()
        and str(context.correlation_id or "").strip()
        and str(context.audit_id or "").strip()
        and {"admin", "trader"}.intersection(roles)
    )


def _map_lifecycle_errors(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except FuturesManualLifecycleError as exc:
            raise OperatorHotpointControlError(
                exc.code,
                exc.http_status_code,
            ) from None

    return wrapped


class OperatorFuturesHotpointV2Service:
    """Coordinate trigger, six reads, Preview/Create, and exact closeout."""

    goal_id = FUTURES_HOTPOINT_GOAL_ID
    policy = FUTURES_HOTPOINT_SCOPE_POLICY
    control_available = True
    placement_execution_available = True
    cancel_execution_available = True

    def __init__(
        self,
        *,
        control_service: OperatorHotpointControlService,
        control_repository: OperatorHotpointControlRepository,
        lifecycle_repository: FuturesManualLifecycleRepository,
        eligibility_reader_factory: Callable[
            [FuturesHotpointTriggerBinding],
            FuturesHotpointEligibilityReader,
        ],
        exchange_executor: Any,
        closeout_executor: FuturesHotpointExactCloseoutExecutor,
        runtime_controller_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.control_service = control_service
        self.control_repository = control_repository
        self.lifecycle_repository = lifecycle_repository
        self.eligibility_reader_factory = eligibility_reader_factory
        self.exchange_executor = exchange_executor
        self.closeout_executor = closeout_executor
        self.runtime_controller_factory = (
            runtime_controller_factory or get_runtime_controller
        )
        self.lifecycle_repository.recover_hotpoint_external_commands()
        self.recover_cross_coordinator_state()

    def recover_cross_coordinator_state(self) -> None:
        """Close stale control authority after lifecycle restart recovery."""

        lifecycle = self.lifecycle_repository.read()
        if any(
            outcome is not AdminFuturesManualCallOutcome.NOT_RUN
            for outcome in (
                lifecycle.preview_outcome,
                lifecycle.create_outcome,
                lifecycle.reconciliation_outcome,
                lifecycle.cancel_outcome,
            )
        ):
            self.control_repository.close_futures_control_after_attempt()

    def _runtime_controller(self) -> Any:
        try:
            controller = self.runtime_controller_factory()
            if (
                not callable(getattr(controller, "check_admission", None))
                or not callable(
                    getattr(controller, "track_inflight", None)
                )
            ):
                raise TypeError
            return controller
        except Exception:
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_runtime_unavailable",
                503,
            ) from None

    @staticmethod
    def _check_runtime_admission(
        controller: Any,
        category: str,
    ) -> None:
        try:
            controller.check_admission(category)
        except Exception:
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_runtime_not_admitting",
                503,
            ) from None

    @contextmanager
    def _runtime_scope(self, category: str):
        controller = self._runtime_controller()
        self._check_runtime_admission(controller, category)
        try:
            with controller.track_inflight(category):
                yield controller
        except OperatorHotpointControlError:
            raise
        except Exception:
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_runtime_unavailable",
                503,
            ) from None

    @classmethod
    def _mark_runtime_call_boundary(
        cls,
        *,
        controller: Any,
        category: str,
        marker: Callable[[], None],
    ) -> None:
        cls._check_runtime_admission(controller, category)
        marker()

    @staticmethod
    def _snapshot(
        state: OperatorFuturesHotpointReadback,
    ) -> dict[str, Any]:
        return json.loads(
            json.dumps(
                asdict(state),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        )

    @staticmethod
    def _state_from_snapshot(
        snapshot: Mapping[str, Any],
    ) -> OperatorFuturesHotpointReadback:
        try:
            exact = dict(snapshot)
            control_raw = dict(exact["control"])
            control_raw.update(
                {
                    "kill_switch_state": HotpointKillSwitchState(
                        control_raw["kill_switch_state"]
                    ),
                    "window_state": HotpointWindowState(
                        control_raw["window_state"]
                    ),
                    "create_state": HotpointCreateState(
                        control_raw["create_state"]
                    ),
                    "cancel_state": HotpointCancelState(
                        control_raw["cancel_state"]
                    ),
                    "roles": tuple(control_raw.get("roles") or ()),
                }
            )
            lifecycle_raw = dict(exact["lifecycle"])
            eligibility_outcome = lifecycle_raw.get(
                "eligibility_outcome"
            )
            lifecycle_raw["eligibility_outcome"] = (
                AdminFuturesManualEligibilityOutcome(
                    eligibility_outcome
                )
                if eligibility_outcome is not None
                else None
            )
            for field in (
                "preview_outcome",
                "create_outcome",
                "reconciliation_outcome",
                "cancel_outcome",
            ):
                lifecycle_raw[field] = AdminFuturesManualCallOutcome(
                    lifecycle_raw[field]
                )
            return OperatorFuturesHotpointReadback(
                goal_id=str(exact["goal_id"]),
                revision=int(exact["revision"]),
                control_revision=int(exact["control_revision"]),
                lifecycle_revision=int(exact["lifecycle_revision"]),
                control=OperatorHotpointControlRecord(**control_raw),
                lifecycle=FuturesManualGoalRecord(**lifecycle_raw),
                allowed_actions=tuple(exact["allowed_actions"]),
                cancel_disposition=exact.get("cancel_disposition"),
                diagnostic_code=str(exact["diagnostic_code"]),
                trigger_fill_count=int(exact["trigger_fill_count"]),
                trigger_evidence_sha256=exact.get(
                    "trigger_evidence_sha256"
                ),
                window_id_sha256=exact.get("window_id_sha256"),
                latest_external_command=(
                    FuturesHotpointExternalCommandReadback(
                        **dict(exact["latest_external_command"])
                    )
                    if exact.get("latest_external_command") is not None
                    else None
                ),
            )
        except Exception:
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_command_snapshot_invalid",
                503,
            ) from None

    def _resolve_external_claim(
        self,
        claim: Any,
    ) -> OperatorFuturesHotpointReadback | None:
        if claim.status == "NEW":
            return None
        if claim.status == "SUCCESS" and claim.result_snapshot is not None:
            return self._state_from_snapshot(claim.result_snapshot)
        if claim.status == "FAILED":
            raise OperatorHotpointControlError(
                str(claim.error_code),
                int(claim.http_status_code),
            )
        if claim.status == "UNKNOWN":
            raise OperatorHotpointControlError(
                str(claim.error_code),
                int(claim.http_status_code),
            )
        if claim.status == "IN_PROGRESS":
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_command_outcome_unknown",
                503,
            )
        raise OperatorHotpointControlError(
            "operator_futures_hotpoint_command_result_invalid",
            503,
        )

    def _finish_external_success(
        self,
        *,
        command_id: str,
        state: OperatorFuturesHotpointReadback,
    ) -> OperatorFuturesHotpointReadback:
        command = state.latest_external_command
        if command is None or command.status != "IN_PROGRESS":
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_command_readback_invalid",
                503,
            )
        terminal_state = replace(
            state,
            latest_external_command=replace(
                command,
                status="SUCCESS",
                diagnostic_code=(
                    "operator_futures_hotpoint_command_succeeded"
                ),
            ),
        )
        self.lifecycle_repository.finish_hotpoint_external_command(
            command_id=command_id,
            outcome="SUCCESS",
            result_snapshot=self._snapshot(terminal_state),
            error_code=None,
            http_status_code=None,
        )
        return terminal_state

    def _finish_external_failure(
        self,
        *,
        command_id: str,
        error_code: str,
        http_status_code: int,
        unknown: bool = False,
    ) -> None:
        normalized_error = str(error_code or "").strip()
        if normalized_error.startswith("operator_futures_manual_"):
            normalized_error = normalized_error.replace(
                "operator_futures_manual_",
                "operator_futures_hotpoint_",
                1,
            )
        if (
            re.fullmatch(
                r"operator_futures_hotpoint_[a-z0-9_]+",
                normalized_error,
            )
            is None
            or len(normalized_error) > 128
        ):
            normalized_error = (
                "operator_futures_hotpoint_command_failed"
            )
        self.lifecycle_repository.finish_hotpoint_external_command(
            command_id=command_id,
            outcome="UNKNOWN" if unknown else "FAILED",
            result_snapshot=None,
            error_code=normalized_error,
            http_status_code=http_status_code,
        )

    def _terminalize_external_exception(
        self,
        *,
        command_id: str,
        error_code: str,
        http_status_code: int,
        default_unknown_code: str | None = None,
    ) -> OperatorHotpointControlError | None:
        """Never label an entered, unterminated exchange boundary FAILED."""

        try:
            lifecycle = self.lifecycle_repository.read()
        except Exception:
            lifecycle = None
        if lifecycle is not None:
            for step in (
                "cancel",
                "reconciliation",
                "create",
                "preview",
            ):
                if (
                    getattr(lifecycle, f"{step}_outcome")
                    is AdminFuturesManualCallOutcome.CLAIMED
                    and getattr(
                        lifecycle,
                        f"{step}_exchange_invoked",
                    )
                    is True
                ):
                    unknown_code = (
                        "operator_futures_hotpoint_"
                        f"{step}_terminal_persistence_unknown"
                    )
                    self._finish_external_failure(
                        command_id=command_id,
                        error_code=unknown_code,
                        http_status_code=503,
                        unknown=True,
                    )
                    return OperatorHotpointControlError(
                        unknown_code,
                        503,
                    )
        if default_unknown_code is not None:
            self._finish_external_failure(
                command_id=command_id,
                error_code=default_unknown_code,
                http_status_code=503,
                unknown=True,
            )
            return OperatorHotpointControlError(
                default_unknown_code,
                503,
            )
        self._finish_external_failure(
            command_id=command_id,
            error_code=error_code,
            http_status_code=http_status_code,
        )
        return None

    @staticmethod
    def _cancel_disposition(
        lifecycle: FuturesManualGoalRecord,
        *,
        cancel_invocation_sealed: bool = False,
    ) -> str | None:
        if (
            lifecycle.reconciliation_outcome
            is AdminFuturesManualCallOutcome.ACCEPTED
            and lifecycle.authoritatively_nonterminal is False
        ):
            if lifecycle.order_status in _TERMINAL_ORDER_STATUSES:
                return "NOT_REQUIRED"
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_reconciliation_state_invalid",
                503,
            )
        if (
            cancel_invocation_sealed
            and lifecycle.cancel_outcome
            is AdminFuturesManualCallOutcome.NOT_RUN
        ):
            return "ALREADY_CANCEL_REQUESTED"
        if (
            lifecycle.reconciliation_outcome
            is not AdminFuturesManualCallOutcome.ACCEPTED
        ):
            return None
        if lifecycle.authoritatively_nonterminal is True:
            if lifecycle.order_status in _CANCEL_ELIGIBLE_ORDER_STATUSES:
                return "REQUIRED"
            if lifecycle.order_status in _DEFERRED_ORDER_STATUSES:
                return "DEFERRED_TRANSITIONAL"
            if lifecycle.order_status == "CANCEL_QUEUED":
                return "ALREADY_CANCEL_REQUESTED"
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_reconciliation_state_invalid",
                503,
            )
        raise OperatorHotpointControlError(
            "operator_futures_hotpoint_reconciliation_state_invalid",
            503,
        )

    @classmethod
    def _allowed_actions(
        cls,
        control: OperatorHotpointControlRecord,
        lifecycle: FuturesManualGoalRecord,
        *,
        trigger_fill_count: int,
        trigger_evidence_sha256: str | None,
        cancel_invocation_sealed: bool = False,
    ) -> tuple[str, ...]:
        actions: list[str] = []
        no_attempt = (
            lifecycle.preview_outcome
            is AdminFuturesManualCallOutcome.NOT_RUN
        )
        if no_attempt:
            if (
                control.kill_switch_state
                is HotpointKillSwitchState.DISABLED
                and control.window_state is HotpointWindowState.NONE
            ):
                actions.append("ENABLE")
            if (
                control.kill_switch_state
                is HotpointKillSwitchState.ENABLED
            ):
                actions.append("DISABLE")
                if control.window_state is HotpointWindowState.NONE:
                    actions.append("ARM")
                elif control.window_state is HotpointWindowState.ARMED:
                    actions.append("DISARM")
                    if (
                        trigger_fill_count == 3
                        and trigger_evidence_sha256 is not None
                        and lifecycle.active_cycle_number is None
                        and lifecycle.cycles_used < 10
                    ):
                        actions.append("RUN_ONCE")
        if (
            lifecycle.client_order_id
            and lifecycle.execution_claim_id
            and lifecycle.create_outcome
            in {
                AdminFuturesManualCallOutcome.ACCEPTED,
                AdminFuturesManualCallOutcome.UNKNOWN,
            }
            and (
                lifecycle.create_outcome
                is AdminFuturesManualCallOutcome.ACCEPTED
                or lifecycle.create_exchange_invoked is True
            )
            and lifecycle.reconciliation_outcome
            is AdminFuturesManualCallOutcome.NOT_RUN
            and not cancel_invocation_sealed
        ):
            actions.append("SAFE_CLOSEOUT")
        return tuple(actions)

    def read(self) -> OperatorFuturesHotpointReadback:
        control = self.control_service.read()
        lifecycle = self.lifecycle_repository.read()
        trigger_unavailable = False
        try:
            trigger = (
                self.control_repository.read_futures_trigger_readback()
            )
        except ValueError as exc:
            if str(exc) not in {
                "operator_futures_hotpoint_parent_projection_invalid",
                "operator_futures_hotpoint_fill_conservation_invalid",
                "operator_hotpoint_fill_evidence_invalid",
            }:
                raise
            trigger_unavailable = True
            trigger = {
                "trigger_fill_count": 0,
                "trigger_evidence_sha256": None,
                "window_id_sha256": (
                    hashlib.sha256(
                        str(control.window_id).encode("utf-8")
                    ).hexdigest()
                    if control.window_id is not None
                    else None
                ),
            }
        trigger_fill_count = trigger.get("trigger_fill_count")
        trigger_evidence_sha256 = trigger.get(
            "trigger_evidence_sha256"
        )
        window_id_sha256 = trigger.get("window_id_sha256")
        cancel_invocation_sealed = (
            self.lifecycle_repository.is_cancel_invocation_sealed()
        )
        latest_external_command = (
            self.lifecycle_repository
            .read_latest_hotpoint_external_command()
        )
        if (
            control.goal_id != FUTURES_HOTPOINT_GOAL_ID
            or lifecycle.goal_id != FUTURES_HOTPOINT_GOAL_ID
            or type(trigger_fill_count) is not int
            or not 0 <= trigger_fill_count <= 3
            or (
                trigger_fill_count == 3
                and _SHA256_RE.fullmatch(
                    str(trigger_evidence_sha256 or "")
                )
                is None
            )
            or (
                trigger_fill_count != 3
                and trigger_evidence_sha256 is not None
            )
            or (
                control.window_id is not None
                and _SHA256_RE.fullmatch(
                    str(window_id_sha256 or "")
                )
                is None
            )
        ):
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_goal_binding_invalid",
                503,
            )
        diagnostic = (
            "operator_futures_cancel_invocation_already_sealed"
            if (
                cancel_invocation_sealed
                and lifecycle.cancel_outcome
                is AdminFuturesManualCallOutcome.NOT_RUN
            )
            else "operator_futures_hotpoint_trigger_evidence_unavailable"
            if trigger_unavailable
            else lifecycle.diagnostic_code
            if (
                lifecycle.cycles_used > 0
                or lifecycle.preview_outcome
                is not AdminFuturesManualCallOutcome.NOT_RUN
            )
            else control.diagnostic_code
        )
        return OperatorFuturesHotpointReadback(
            goal_id=FUTURES_HOTPOINT_GOAL_ID,
            revision=control.revision,
            control_revision=control.revision,
            lifecycle_revision=lifecycle.revision,
            control=control,
            lifecycle=lifecycle,
            allowed_actions=(
                ()
                if trigger_unavailable
                else self._allowed_actions(
                    control,
                    lifecycle,
                    trigger_fill_count=trigger_fill_count,
                    trigger_evidence_sha256=trigger_evidence_sha256,
                    cancel_invocation_sealed=cancel_invocation_sealed,
                )
            ),
            cancel_disposition=self._cancel_disposition(
                lifecycle,
                cancel_invocation_sealed=cancel_invocation_sealed,
            ),
            diagnostic_code=diagnostic,
            trigger_fill_count=trigger_fill_count,
            trigger_evidence_sha256=trigger_evidence_sha256,
            window_id_sha256=window_id_sha256,
            latest_external_command=latest_external_command,
        )

    def list_eligible_parents(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, str]], int]:
        return self.control_service.list_eligible_parents(
            limit=limit,
            offset=offset,
        )

    def control(
        self,
        *,
        action: HotpointControlAction,
        expected_revision: int,
        confirm_control_action: bool,
        authorize_one_bounded_trigger_window: bool = False,
        acknowledge_unknown_outcome_consumes_create_allowance: bool = False,
        acknowledge_backend_derives_child_terms: bool = False,
        context: OperatorHotpointRequestContext,
        parent_client_order_id: str | None = None,
    ) -> OperatorFuturesHotpointReadback:
        lifecycle = self.lifecycle_repository.read()
        if (
            lifecycle.preview_outcome
            is not AdminFuturesManualCallOutcome.NOT_RUN
            and action
            in {HotpointControlAction.ENABLE, HotpointControlAction.ARM}
        ):
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_attempt_already_consumed",
                409,
            )
        self.control_service.control(
            action=action,
            expected_revision=expected_revision,
            confirm_control_action=confirm_control_action,
            authorize_one_bounded_trigger_window=(
                authorize_one_bounded_trigger_window
            ),
            acknowledge_unknown_outcome_consumes_create_allowance=(
                acknowledge_unknown_outcome_consumes_create_allowance
            ),
            acknowledge_backend_derives_child_terms=(
                acknowledge_backend_derives_child_terms
            ),
            context=context,
            parent_client_order_id=parent_client_order_id,
        )
        return self.read()

    @staticmethod
    def _lifecycle_context(
        *,
        context: OperatorHotpointRequestContext,
        expected_revision: int,
        suffix: str,
        refresh: bool,
    ) -> FuturesManualRequestContext:
        return FuturesManualRequestContext(
            actor_id=context.actor_id,
            roles=context.roles,
            expected_revision=expected_revision,
            idempotency_key=f"{context.idempotency_key}:{suffix}",
            correlation_id=context.correlation_id,
            audit_id=context.audit_id,
            operator_intent=(
                "refresh_one_futures_hotpoint_eligibility_cycle"
                if refresh
                else "preview_one_futures_hotpoint_child"
            ),
            authorize_one_no_retry_six_category_cycle=refresh,
            acknowledge_cycle_is_goal_global_and_limited_to_ten=refresh,
            acknowledge_unsuccessful_or_unknown_cycle_fails_closed=refresh,
            authorize_preview_create_and_safe_closeout=not refresh,
            acknowledge_unknown_outcome_consumes_allowance=not refresh,
            acknowledge_create_requires_accepted_identical_preview=(
                not refresh
            ),
            acknowledge_cancel_is_only_for_exact_nonterminal_child=False,
        )

    @staticmethod
    def _external_command_context(
        *,
        context: OperatorHotpointRequestContext,
        expected_revision: int,
    ) -> FuturesManualRequestContext:
        return FuturesManualRequestContext(
            actor_id=context.actor_id,
            roles=context.roles,
            expected_revision=expected_revision,
            idempotency_key=context.idempotency_key,
            correlation_id=context.correlation_id,
            audit_id=context.audit_id,
            operator_intent=context.operator_intent,
        )

    @staticmethod
    def _unknown_eligibility(
        *,
        binding: FuturesHotpointTriggerBinding,
        attempts: Mapping[str, int],
        margin_subread_attempts: Mapping[str, int],
    ) -> FuturesManualEligibilityResult:
        public = {
            "goal_id": FUTURES_HOTPOINT_GOAL_ID,
            "profile_alias": "Default",
            "product_id": FUTURES_HOTPOINT_PRODUCT_ID,
            "contract_count": "1",
            "caps": {
                "opening_usdc": "100",
                "exposure_usdc": "150",
                "turnover_usdc": "300",
                "comparison": "strictly_less_than",
            },
            "parent_client_order_id_sha256": hashlib.sha256(
                binding.parent_client_order_id.encode("utf-8")
            ).hexdigest(),
            "window_id_sha256": hashlib.sha256(
                binding.window_id.encode("utf-8")
            ).hexdigest(),
            "trigger_evidence_sha256": (
                binding.trigger_evidence_sha256
            ),
            "exact_v3_eligible": False,
            "diagnostic_code": (
                "operator_futures_hotpoint_eligibility_read_unknown"
            ),
            "category_attempts": dict(attempts),
            "margin_subread_attempts": dict(
                margin_subread_attempts
            ),
            "raw_responses_included": False,
            "private_identifiers_included": False,
            "exception_text_included": False,
        }
        return FuturesManualEligibilityResult(
            outcome=AdminFuturesManualEligibilityOutcome.UNKNOWN,
            diagnostic_code=(
                "operator_futures_hotpoint_eligibility_read_unknown"
            ),
            category_attempts={
                str(key): int(value)
                for key, value in attempts.items()
            },
            candidate=None,
            portfolio_id_sha256=None,
            evidence_sha256=_canonical_sha256(public),
            public_evidence=public,
        )

    def _finish_preinvoke_unknown(
        self,
        *,
        claim_id: str,
        step: str,
    ) -> FuturesManualGoalRecord:
        return self.lifecycle_repository.finish_unentered_claim_unknown(
            claim_id=claim_id,
            step=step,
            diagnostic_code=(
                f"operator_futures_hotpoint_{step}_preinvoke_unknown"
            ),
        )

    def _close_attempt(self) -> None:
        self.control_repository.close_futures_control_after_attempt()

    @_map_lifecycle_errors
    def run_once(
        self,
        *,
        expected_revision: int,
        expected_parent_client_order_id: str,
        confirm_bounded_trigger_evaluation: bool,
        authorize_one_no_retry_six_category_cycle: bool,
        acknowledge_cycle_is_goal_global_and_limited_to_ten: bool,
        acknowledge_unsuccessful_or_unknown_cycle_fails_closed: bool,
        authorize_one_preview_and_conditional_identical_create: bool,
        acknowledge_unknown_preview_or_create_consumes_allowance: bool,
        acknowledge_create_requires_accepted_identical_preview: bool,
        context: OperatorHotpointRequestContext,
    ) -> OperatorFuturesHotpointReadback:
        if (
            not _operator_context_valid(
                context,
                intent=HOTPOINT_RUN_OPERATOR_INTENT,
            )
            or type(expected_revision) is not int
            or expected_revision < 0
            or not str(expected_parent_client_order_id or "").strip()
            or confirm_bounded_trigger_evaluation is not True
            or authorize_one_no_retry_six_category_cycle is not True
            or acknowledge_cycle_is_goal_global_and_limited_to_ten
            is not True
            or acknowledge_unsuccessful_or_unknown_cycle_fails_closed
            is not True
            or authorize_one_preview_and_conditional_identical_create
            is not True
            or acknowledge_unknown_preview_or_create_consumes_allowance
            is not True
            or acknowledge_create_requires_accepted_identical_preview
            is not True
        ):
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_run_authority_invalid",
                422,
            )
        self._check_runtime_admission(
            self._runtime_controller(),
            INFLIGHT_REST_PLACE,
        )
        external_command_id: str | None = None
        try:
            external_context = self._external_command_context(
                context=context,
                expected_revision=expected_revision,
            )
            external_claim = (
                self.lifecycle_repository.claim_hotpoint_external_command(
                    action="RUN_ONCE",
                    context=external_context,
                    request_payload={
                        "expected_revision": expected_revision,
                        "expected_parent_client_order_id": (
                            expected_parent_client_order_id
                        ),
                        "confirm_bounded_trigger_evaluation": (
                            confirm_bounded_trigger_evaluation
                        ),
                        "authorize_one_no_retry_six_category_cycle": (
                            authorize_one_no_retry_six_category_cycle
                        ),
                        (
                            "acknowledge_cycle_is_goal_global_and_"
                            "limited_to_ten"
                        ): (
                            acknowledge_cycle_is_goal_global_and_limited_to_ten
                        ),
                        (
                            "acknowledge_unsuccessful_or_unknown_cycle_"
                            "fails_closed"
                        ): (
                            acknowledge_unsuccessful_or_unknown_cycle_fails_closed
                        ),
                        (
                            "authorize_one_preview_and_conditional_"
                            "identical_create"
                        ): (
                            authorize_one_preview_and_conditional_identical_create
                        ),
                        (
                            "acknowledge_unknown_preview_or_create_"
                            "consumes_allowance"
                        ): (
                            acknowledge_unknown_preview_or_create_consumes_allowance
                        ),
                        (
                            "acknowledge_create_requires_accepted_"
                            "identical_preview"
                        ): (
                            acknowledge_create_requires_accepted_identical_preview
                        ),
                    },
                )
            )
            replay = self._resolve_external_claim(external_claim)
            if replay is not None:
                return replay
            external_command_id = external_claim.command_id
            try:
                _claimed_control, binding = (
                    self.control_repository.claim_futures_trigger(
                        expected_revision=expected_revision,
                        expected_parent_client_order_id=(
                            expected_parent_client_order_id
                        ),
                        idempotency_key=context.idempotency_key,
                        actor_id=context.actor_id,
                        roles=context.roles,
                        correlation_id=context.correlation_id,
                        audit_id=context.audit_id,
                    )
                )
            except ValueError:
                raise OperatorHotpointControlError(
                    "operator_futures_hotpoint_trigger_claim_rejected",
                    409,
                ) from None
            lifecycle = self.lifecycle_repository.read()
            refresh_context = self._lifecycle_context(
                context=context,
                expected_revision=lifecycle.revision,
                suffix="eligibility",
                refresh=True,
            )
            _cycle_claim, cycle_number = (
                self.lifecycle_repository.begin_eligibility_cycle(
                    context=refresh_context
                )
            )
            if cycle_number is None:
                return self._finish_external_success(
                    command_id=external_command_id,
                    state=self.read(),
                )
            reader = self.eligibility_reader_factory(binding)
            try:
                with self._runtime_scope(
                    INFLIGHT_REST_PLACE
                ) as runtime_controller:
                    eligibility = reader.run(
                        before_category=lambda category: (
                            self._check_runtime_admission(
                                runtime_controller,
                                INFLIGHT_REST_PLACE,
                            ),
                            self.lifecycle_repository
                            .claim_eligibility_category(
                                cycle_number=cycle_number,
                                category=category,
                            ),
                        ),
                        before_margin_subread=lambda subread: (
                            self._check_runtime_admission(
                                runtime_controller,
                                INFLIGHT_REST_PLACE,
                            ),
                            self.lifecycle_repository
                            .claim_margin_subread(
                                cycle_number=cycle_number,
                                subread=subread,
                            ),
                        ),
                    )
            except Exception:
                boundary = self.lifecycle_repository.read()
                attempts = boundary.category_attempts
                eligibility = self._unknown_eligibility(
                    binding=binding,
                    attempts=attempts,
                    margin_subread_attempts=(
                        boundary.margin_subread_attempts
                    ),
                )
            eligible = self.lifecycle_repository.finish_eligibility_cycle(
                cycle_number=cycle_number,
                result=eligibility,
                context=refresh_context,
            )
            if (
                eligible.eligibility_outcome
                is not AdminFuturesManualEligibilityOutcome.ELIGIBLE
            ):
                return self._finish_external_success(
                    command_id=external_command_id,
                    state=self.read(),
                )
            if not self.control_repository.revalidate_futures_trigger(
                binding
            ):
                raise OperatorHotpointControlError(
                    "operator_futures_hotpoint_trigger_revalidation_failed",
                    409,
                )
            execute_context = self._lifecycle_context(
                context=context,
                expected_revision=eligible.revision,
                suffix="attempt",
                refresh=False,
            )
            _preview_claim, plan = self.lifecycle_repository.claim_preview(
                context=execute_context
            )
            if plan is None:
                return self._finish_external_success(
                    command_id=external_command_id,
                    state=self.read(),
                )
            if not self.control_repository.revalidate_futures_trigger(
                binding
            ):
                self._finish_preinvoke_unknown(
                    claim_id=plan.claim_id,
                    step="preview",
                )
                self._close_attempt()
                return self._finish_external_success(
                    command_id=external_command_id,
                    state=self.read(),
                )
            try:
                with self._runtime_scope(
                    INFLIGHT_REST_PLACE
                ) as runtime_controller:
                    preview = self.exchange_executor.preview(
                        plan.candidate,
                        before_call=lambda: (
                            self._mark_runtime_call_boundary(
                                controller=runtime_controller,
                                category=INFLIGHT_REST_PLACE,
                                marker=lambda: (
                                    self.lifecycle_repository
                                    .mark_preview_exchange_invoked(
                                        claim_id=plan.claim_id
                                    )
                                ),
                            )
                        ),
                    )
            except Exception:
                preview = SimpleNamespace(
                    outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                    diagnostic_code=(
                        "operator_futures_hotpoint_preview_outcome_unknown"
                    ),
                    preview_id_sha256=None,
                    private_preview_id=None,
                )
            boundary = self.lifecycle_repository.read()
            if boundary.preview_exchange_invoked is not True:
                self._finish_preinvoke_unknown(
                    claim_id=plan.claim_id,
                    step="preview",
                )
                self._close_attempt()
                return self._finish_external_success(
                    command_id=external_command_id,
                    state=self.read(),
                )
            if (
                getattr(preview, "outcome", None)
                is not AdminFuturesManualCallOutcome.ACCEPTED
                or not str(
                    getattr(preview, "private_preview_id", "") or ""
                ).strip()
            ):
                if (
                    getattr(preview, "outcome", None)
                    is AdminFuturesManualCallOutcome.ACCEPTED
                ):
                    preview = SimpleNamespace(
                        outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                        diagnostic_code=(
                            "operator_futures_hotpoint_preview_outcome_unknown"
                        ),
                        preview_id_sha256=None,
                    )
                self.lifecycle_repository.finish_preview(
                    claim_id=plan.claim_id,
                    execution=preview,
                )
                self._close_attempt()
                return self._finish_external_success(
                    command_id=external_command_id,
                    state=self.read(),
                )
            private_preview_id = str(
                getattr(preview, "private_preview_id", "") or ""
            )
            preview_id_sha256 = str(
                getattr(preview, "preview_id_sha256", "") or ""
            ).lower()
            if (
                _SHA256_RE.fullmatch(preview_id_sha256) is None
                or hashlib.sha256(
                    private_preview_id.encode("utf-8")
                ).hexdigest()
                != preview_id_sha256
            ):
                self.lifecycle_repository.finish_preview(
                    claim_id=plan.claim_id,
                    execution=SimpleNamespace(
                        outcome=(
                            AdminFuturesManualCallOutcome.UNKNOWN
                        ),
                        diagnostic_code=(
                            "operator_futures_hotpoint_preview_"
                            "identity_binding_invalid"
                        ),
                        preview_id_sha256=None,
                    ),
                )
                self._close_attempt()
                return self._finish_external_success(
                    command_id=external_command_id,
                    state=self.read(),
                )
            try:
                self.lifecycle_repository.finish_preview_and_claim_create(
                    claim_id=plan.claim_id,
                    execution=preview,
                )
            except FuturesManualLifecycleError as exc:
                if exc.code not in {
                    "operator_futures_manual_candidate_stale",
                    "operator_futures_manual_candidate_binding_invalid",
                }:
                    raise
                blocked_preview = SimpleNamespace(
                    outcome=preview.outcome,
                    preview_id_sha256=preview.preview_id_sha256,
                    diagnostic_code=(
                        "operator_futures_hotpoint_preview_accepted_"
                        "create_blocked_stale_or_binding"
                    ),
                )
                self.lifecycle_repository.finish_preview(
                    claim_id=plan.claim_id,
                    execution=blocked_preview,
                )
                self._close_attempt()
                return self._finish_external_success(
                    command_id=external_command_id,
                    state=self.read(),
                )
            try:
                with self._runtime_scope(
                    INFLIGHT_REST_PLACE
                ) as runtime_controller:
                    def mark_create_boundary() -> None:
                        boundary = self.lifecycle_repository.read()
                        if (
                            boundary.preview_id_sha256
                            != hashlib.sha256(
                                private_preview_id.encode("utf-8")
                            ).hexdigest()
                        ):
                            raise FuturesManualLifecycleError(
                                "operator_futures_hotpoint_create_"
                                "preview_binding_invalid"
                            )
                        self._mark_runtime_call_boundary(
                            controller=runtime_controller,
                            category=INFLIGHT_REST_PLACE,
                            marker=lambda: (
                                self.lifecycle_repository
                                .mark_create_exchange_invoked(
                                    claim_id=plan.claim_id
                                )
                            ),
                        )

                    created = self.exchange_executor.create(
                        candidate=plan.candidate,
                        client_order_id=plan.client_order_id,
                        private_preview_id=private_preview_id,
                        before_call=mark_create_boundary,
                    )
            except Exception:
                created = SimpleNamespace(
                    outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                    diagnostic_code=(
                        "operator_futures_hotpoint_create_outcome_unknown"
                    ),
                    exchange_order_id_sha256=None,
                    private_exchange_order_id=None,
                )
            boundary = self.lifecycle_repository.read()
            if boundary.create_exchange_invoked is not True:
                self._finish_preinvoke_unknown(
                    claim_id=plan.claim_id,
                    step="create",
                )
            else:
                self.lifecycle_repository.finish_create(
                    claim_id=plan.claim_id,
                    execution=created,
                )
            self._close_attempt()
            return self._finish_external_success(
                command_id=external_command_id,
                state=self.read(),
            )
        except OperatorHotpointControlError as exc:
            if external_command_id is not None:
                terminal = self._terminalize_external_exception(
                    command_id=external_command_id,
                    error_code=exc.code,
                    http_status_code=exc.http_status_code,
                )
                if terminal is not None:
                    raise terminal from None
            raise
        except FuturesManualLifecycleError as exc:
            if external_command_id is not None:
                terminal = self._terminalize_external_exception(
                    command_id=external_command_id,
                    error_code=exc.code,
                    http_status_code=exc.http_status_code,
                )
                if terminal is not None:
                    raise terminal from None
            raise
        except Exception:
            if external_command_id is not None:
                terminal = self._terminalize_external_exception(
                    command_id=external_command_id,
                    error_code=(
                        "operator_futures_hotpoint_run_unavailable"
                    ),
                    http_status_code=503,
                    default_unknown_code=(
                        "operator_futures_hotpoint_run_unavailable"
                    ),
                )
                assert terminal is not None
                raise terminal from None
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_run_unavailable",
                503,
            ) from None

    def _safe_closeout_claimed(
        self,
        *,
        state: OperatorFuturesHotpointReadback,
        expected_revision: int,
        expected_child_client_order_id: str,
        context: FuturesManualRequestContext,
        runtime_controller: Any,
    ) -> OperatorFuturesHotpointReadback:
        lifecycle = state.lifecycle
        if (
            state.revision != expected_revision
            or lifecycle.client_order_id
            != expected_child_client_order_id
            or not lifecycle.execution_claim_id
            or lifecycle.candidate is None
            or "SAFE_CLOSEOUT" not in state.allowed_actions
        ):
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_closeout_not_authorized",
                409,
            )
        claim_id = lifecycle.execution_claim_id
        claimed = self.lifecycle_repository.claim_reconciliation(
            claim_id=claim_id,
            context=context,
        )
        if not claimed.reconciliation_catalog_end_at:
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_reconciliation_window_missing",
                503,
            )
        try:
            reconciled = self.closeout_executor.reconcile(
                candidate=claimed.candidate or {},
                client_order_id=expected_child_client_order_id,
                expected_exchange_order_id_sha256=(
                    claimed.exchange_order_id_sha256
                ),
                reconciliation_catalog_end_at=(
                    claimed.reconciliation_catalog_end_at
                ),
                before_call=lambda: (
                    self._mark_runtime_call_boundary(
                        controller=runtime_controller,
                        category=INFLIGHT_REST_CANCEL,
                        marker=lambda: (
                            self.lifecycle_repository
                            .mark_reconciliation_exchange_invoked(
                                claim_id=claim_id
                            )
                        ),
                    )
                ),
            )
        except Exception:
            reconciled = FuturesHotpointReconciliationExecution(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_hotpoint_reconciliation_outcome_unknown"
                ),
                exchange_order_id_sha256=(
                    claimed.exchange_order_id_sha256
                ),
                order_status=None,
                authoritatively_nonterminal=None,
                public_evidence={},
            )
        boundary = self.lifecycle_repository.read()
        if boundary.reconciliation_exchange_invoked is not True:
            self._finish_preinvoke_unknown(
                claim_id=claim_id,
                step="reconciliation",
            )
            return self.read()
        if (
            reconciled.outcome
            is not AdminFuturesManualCallOutcome.ACCEPTED
            or reconciled.authoritatively_nonterminal is not True
            or reconciled.order_status
            not in _CANCEL_ELIGIBLE_ORDER_STATUSES
        ):
            self.lifecycle_repository.finish_reconciliation(
                claim_id=claim_id,
                execution=reconciled,
            )
            return self.read()
        if not reconciled.private_exchange_order_id:
            unknown = FuturesHotpointReconciliationExecution(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_hotpoint_reconciliation_outcome_unknown"
                ),
                exchange_order_id_sha256=(
                    reconciled.exchange_order_id_sha256
                ),
                order_status=None,
                authoritatively_nonterminal=None,
                public_evidence={},
            )
            self.lifecycle_repository.finish_reconciliation(
                claim_id=claim_id,
                execution=unknown,
            )
            return self.read()
        private_exchange_order_id = str(
            reconciled.private_exchange_order_id
        )
        raw_exchange_hash = hashlib.sha256(
            private_exchange_order_id.encode("utf-8")
        ).hexdigest()
        reconciled_exchange_hash = str(
            reconciled.exchange_order_id_sha256 or ""
        ).lower()
        if (
            _SHA256_RE.fullmatch(reconciled_exchange_hash) is None
            or raw_exchange_hash != reconciled_exchange_hash
            or (
                claimed.exchange_order_id_sha256 is not None
                and raw_exchange_hash
                != claimed.exchange_order_id_sha256
            )
        ):
            self.lifecycle_repository.finish_reconciliation(
                claim_id=claim_id,
                execution=FuturesHotpointReconciliationExecution(
                    outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                    diagnostic_code=(
                        "operator_futures_hotpoint_reconciliation_"
                        "identity_binding_invalid"
                    ),
                    exchange_order_id_sha256=(
                        claimed.exchange_order_id_sha256
                    ),
                    order_status=None,
                    authoritatively_nonterminal=None,
                    public_evidence={},
                ),
            )
            return self.read()
        self.lifecycle_repository.finish_reconciliation_and_claim_cancel(
            claim_id=claim_id,
            execution=reconciled,
        )
        cancel_boundary_failure: str | None = None

        def mark_cancel_boundary() -> None:
            nonlocal cancel_boundary_failure
            try:
                boundary = self.lifecycle_repository.read()
                if (
                    boundary.exchange_order_id_sha256
                    != raw_exchange_hash
                    or reconciled_exchange_hash != raw_exchange_hash
                ):
                    raise FuturesManualLifecycleError(
                        "operator_futures_hotpoint_cancel_"
                        "identity_binding_invalid"
                    )
                self._mark_runtime_call_boundary(
                    controller=runtime_controller,
                    category=INFLIGHT_REST_CANCEL,
                    marker=lambda: (
                        self.lifecycle_repository
                        .mark_cancel_exchange_invoked(
                            claim_id=claim_id
                        )
                    ),
                )
            except FuturesManualLifecycleError as exc:
                if exc.code == (
                    "operator_futures_cancel_invocation_already_sealed"
                ):
                    cancel_boundary_failure = exc.code
                raise

        try:
            cancelled = self.exchange_executor.cancel(
                candidate=claimed.candidate,
                client_order_id=expected_child_client_order_id,
                private_exchange_order_id=(
                    private_exchange_order_id
                ),
                before_call=mark_cancel_boundary,
            )
        except Exception:
            cancelled = SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_hotpoint_cancel_outcome_unknown"
                ),
                exchange_order_id_sha256=(
                    reconciled.exchange_order_id_sha256
                ),
            )
        boundary = self.lifecycle_repository.read()
        if boundary.cancel_exchange_invoked is not True:
            if cancel_boundary_failure == (
                "operator_futures_cancel_invocation_already_sealed"
            ):
                self.lifecycle_repository.release_cancel_invocation_conflict(
                    claim_id=claim_id,
                )
            else:
                self._finish_preinvoke_unknown(
                    claim_id=claim_id,
                    step="cancel",
                )
        else:
            self.lifecycle_repository.finish_cancel(
                claim_id=claim_id,
                execution=cancelled,
            )
        return self.read()

    @_map_lifecycle_errors
    def safe_closeout(
        self,
        *,
        expected_revision: int,
        expected_child_client_order_id: str,
        authorize_one_exact_no_retry_reconciliation: bool,
        acknowledge_unknown_reconciliation_consumes_allowance: bool,
        confirm_exact_child_safe_closeout: bool,
        acknowledge_cancel_only_exact_authoritatively_nonterminal_child: bool,
        acknowledge_unknown_outcome_consumes_cancel_allowance: bool,
        context: OperatorHotpointRequestContext,
    ) -> OperatorFuturesHotpointReadback:
        if (
            not _operator_context_valid(
                context,
                intent=HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
            )
            or type(expected_revision) is not int
            or expected_revision < 0
            or not str(expected_child_client_order_id or "").strip()
            or authorize_one_exact_no_retry_reconciliation is not True
            or acknowledge_unknown_reconciliation_consumes_allowance
            is not True
            or confirm_exact_child_safe_closeout is not True
            or acknowledge_cancel_only_exact_authoritatively_nonterminal_child
            is not True
            or acknowledge_unknown_outcome_consumes_cancel_allowance
            is not True
        ):
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_closeout_authority_invalid",
                422,
            )
        self._check_runtime_admission(
            self._runtime_controller(),
            INFLIGHT_REST_CANCEL,
        )
        external_command_id: str | None = None
        try:
            external_context = self._external_command_context(
                context=context,
                expected_revision=expected_revision,
            )
            external_claim = (
                self.lifecycle_repository.claim_hotpoint_external_command(
                    action="SAFE_CLOSEOUT",
                    context=external_context,
                    request_payload={
                        "expected_revision": expected_revision,
                        "expected_child_client_order_id": (
                            expected_child_client_order_id
                        ),
                        "authorize_one_exact_no_retry_reconciliation": (
                            authorize_one_exact_no_retry_reconciliation
                        ),
                        (
                            "acknowledge_unknown_reconciliation_"
                            "consumes_allowance"
                        ): (
                            acknowledge_unknown_reconciliation_consumes_allowance
                        ),
                        "confirm_exact_child_safe_closeout": (
                            confirm_exact_child_safe_closeout
                        ),
                        (
                            "acknowledge_cancel_only_exact_authoritatively_"
                            "nonterminal_child"
                        ): (
                            acknowledge_cancel_only_exact_authoritatively_nonterminal_child
                        ),
                        (
                            "acknowledge_unknown_outcome_consumes_"
                            "cancel_allowance"
                        ): (
                            acknowledge_unknown_outcome_consumes_cancel_allowance
                        ),
                    },
                )
            )
            replay = self._resolve_external_claim(external_claim)
            if replay is not None:
                return replay
            external_command_id = external_claim.command_id
            with self._runtime_scope(
                INFLIGHT_REST_CANCEL
            ) as runtime_controller:
                state = self._safe_closeout_claimed(
                    state=self.read(),
                    expected_revision=expected_revision,
                    expected_child_client_order_id=(
                        expected_child_client_order_id
                    ),
                    context=external_context,
                    runtime_controller=runtime_controller,
                )
            return self._finish_external_success(
                command_id=external_command_id,
                state=state,
            )
        except OperatorHotpointControlError as exc:
            if external_command_id is not None:
                terminal = self._terminalize_external_exception(
                    command_id=external_command_id,
                    error_code=exc.code,
                    http_status_code=exc.http_status_code,
                )
                if terminal is not None:
                    raise terminal from None
            raise
        except FuturesManualLifecycleError as exc:
            if external_command_id is not None:
                terminal = self._terminalize_external_exception(
                    command_id=external_command_id,
                    error_code=exc.code,
                    http_status_code=exc.http_status_code,
                )
                if terminal is not None:
                    raise terminal from None
            raise
        except Exception:
            if external_command_id is not None:
                terminal = self._terminalize_external_exception(
                    command_id=external_command_id,
                    error_code=(
                        "operator_futures_hotpoint_closeout_unavailable"
                    ),
                    http_status_code=503,
                    default_unknown_code=(
                        "operator_futures_hotpoint_closeout_unavailable"
                    ),
                )
                assert terminal is not None
                raise terminal from None
            raise OperatorHotpointControlError(
                "operator_futures_hotpoint_closeout_unavailable",
                503,
            ) from None


__all__ = [
    "FUTURES_HOTPOINT_GOAL_ID",
    "FUTURES_HOTPOINT_POLICY_BINDING",
    "FUTURES_HOTPOINT_POLICY_REVISION",
    "FUTURES_HOTPOINT_POLICY_SHA256",
    "FUTURES_HOTPOINT_PRODUCT_ID",
    "FuturesHotpointEligibilityReader",
    "FuturesHotpointExactCloseoutExecutor",
    "FuturesHotpointReconciliationExecution",
    "FuturesHotpointTriggerBinding",
    "OperatorFuturesHotpointReadback",
    "OperatorFuturesHotpointV2Service",
    "validate_futures_hotpoint_candidate",
    "validate_futures_hotpoint_product_session",
    "validate_futures_hotpoint_eligibility_evidence",
]
