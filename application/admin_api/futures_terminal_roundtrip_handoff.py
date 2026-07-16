"""Pure, private-free R8-to-Slice3 plan and activation construction.

The accepted Preview identifiers exist only in the producer callback's memory.
This module proves that the callback value redacts exactly to the immutable R8
terminal, then builds the short-lived Slice3 plan.  It performs no filesystem
write, credential hydration, Coinbase call, or exchange mutation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from application.admin_api.futures_order_preview import (
    FUTURES_PREVIEW_ACTOR_ID,
    FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING,
    FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING,
    FUTURES_PREVIEW_R7_TERMINAL_BINDING,
    FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
    FUTURES_PREVIEW_R8_POST_PREVIEW_DIAGNOSTIC_BINDING,
    _withhold_r8_private_accepted_evidence,
    canonical_sha256,
)
from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_ACTOR_ID,
    SLICE3_LIVE_POLICY,
    SLICE3_MAX_PREVIEW_TTL,
    SLICE3_METHOD,
    SLICE3_PERMISSION,
    SLICE3_PRODUCT_ID,
    SLICE3_ROLES,
    SLICE3_ROUTE,
    SLICE3_SERVICE_METHOD,
    Slice3AcceptedPreview,
    Slice3CapEvidence,
    Slice3CreateRequest,
    Slice3DirectiveKind,
    Slice3ExecutionAuthority,
    Slice3MarginWindowEvidence,
    Slice3Plan,
    Slice3PortfolioBinding,
    Slice3ReadSlot,
)
from application.admin_api.futures_terminal_roundtrip_activation import (
    Slice3AcceptedR8Binding,
    Slice3ActivationManifest,
)
from application.admin_api.futures_terminal_roundtrip_admission import (
    Slice3AdmissionAuthorityBundle,
    Slice3AdmissionEvidenceKind,
    Slice3AdmissionSeal,
    build_slice3_execution_authority,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (
    Slice3CoinbaseAccountBinding,
)
from core.enums import OrderSide, TimeInForce


R8_SLICE3_HANDOFF_MAX_AGE = timedelta(seconds=60)
R8_SLICE3_MARKET_MAX_AGE = timedelta(seconds=30)
R8_SLICE3_MARKET_MAX_FUTURE_SKEW = timedelta(seconds=5)
# Coinbase's public Advanced Trade Preview/Create documentation currently
# publishes no preview_id expiry field or TTL.  Production must remain None;
# a future code/audit cycle may bind a documented response contract hash.
COINBASE_ADVANCED_TRADE_PREVIEW_EXPIRY_CONTRACT_SHA256: str | None = None
_EXPECTED_MARGIN_ROWS = (
    (
        "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
        "MARGIN_WINDOW_TYPE_INTRADAY",
    ),
    (
        "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
        "MARGIN_WINDOW_TYPE_UNSPECIFIED",
    ),
)
_EXPECTED_POLICY_ROWS = (
    ("retail_regular", "MARGIN_WINDOW_TYPE_UNSPECIFIED"),
    ("retail_intraday_margin_1", "MARGIN_WINDOW_TYPE_INTRADAY"),
)
_EXPECTED_ATTEMPTS = {
    "preview_order": 1,
    "retry": 0,
    "fallback": 0,
    "create_order": 0,
    "cancel_order": 0,
    "close_position": 0,
    "reduce_position": 0,
}
_EXPECTED_READS = {
    "api_key_permissions": 1,
    "portfolio_catalog": 1,
    "product": 1,
    "best_bid_ask": 1,
    "futures_positions": 1,
    "futures_margin_collateral": 1,
}
_EXPECTED_SOURCE_READS = {
    "get_futures_balance_summary": 1,
    "get_intraday_margin_setting": 1,
    "get_current_margin_window": 2,
    "list_futures_sweeps": 1,
}
_EXPECTED_NO_LIVE_POSTURE = {
    "order_creation_authorized": False,
    "order_cancellation_authorized": False,
    "position_close_authorized": False,
    "position_reduce_authorized": False,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "execution_marker_created": False,
    "attempt_ledger_created": False,
    "runtime_created": False,
}
_EXPECTED_ARTIFACTS = {
    "execution_marker_created": False,
    "attempt_ledger_created": False,
    "runtime_created": False,
}
_EXPECTED_SEAL_CAPS = {
    "opening_reference_notional_usdc": "100",
    "concurrent_exposure_usdc": "150",
    "buffered_close_reference_notional_usdc": "150",
    "branch_turnover_reference_notional_usdc": "300",
    "close_buffer_multiplier": "1.20",
    "comparison": "strictly_less_than",
}
_EXPECTED_EPHEMERAL_FIELDS = frozenset(
    {
        "actor_id",
        "artifact_type",
        "artifacts",
        "attempt_counters",
        "bff_authority",
        "browser_authority",
        "candidate",
        "candidate_sha256",
        "canonicalization",
        "claim_sha256",
        "completed_at",
        "correlation_id",
        "evidence_sha256",
        "exchange_submission_attempt_count",
        "executed_notional_usdc",
        "hash_algorithm",
        "idempotency_key",
        "live_coinbase_execution",
        "live_coinbase_read_ran",
        "live_execution",
        "margin_collateral_evidence",
        "margin_collateral_evidence_sha256",
        "margin_setting_evidence",
        "margin_setting_evidence_sha256",
        "margin_windows_policy_evidence",
        "margin_windows_policy_evidence_sha256",
        "market_evidence",
        "market_evidence_sha256",
        "outcome",
        "permission_evidence",
        "permission_evidence_sha256",
        "portfolio_binding",
        "portfolio_catalog_evidence",
        "portfolio_catalog_sha256",
        "portfolio_id",
        "portfolio_type",
        "position_evidence",
        "position_evidence_sha256",
        "post_preview_diagnostic_binding",
        "post_preview_stage_evidence",
        "post_preview_stage_evidence_sha256",
        "predecessor_binding",
        "preview_request",
        "preview_request_sha256",
        "preview_response",
        "preview_response_schema_binding",
        "preview_response_sha256",
        "product_evidence",
        "product_evidence_sha256",
        "product_id",
        "profile_label",
        "read_counters",
        "read_only",
        "reserved_at",
        "roles",
        "schema_version",
        "seal_ready_plan",
        "seal_ready_plan_sha256",
        "status",
        "submitted_notional_usdc",
        "type",
    }
)
_SHA256_HEX = frozenset("0123456789abcdef")


class R8Slice3HandoffError(ValueError):
    """Sanitized fail-closed R8 handoff classification."""


@dataclass(frozen=True, slots=True)
class _ValidatedR8PlanInputs:
    ephemeral: dict[str, Any]
    persisted: dict[str, Any]
    current: datetime
    accepted_at: datetime
    expires_at: datetime
    expiry_source: str
    expiry_evidence_sha256: str
    correlation_id: str
    idempotency_key: str
    portfolio_id: str
    available_margin: str
    intraday_margin_setting: str
    candidate: dict[str, Any]
    request: dict[str, Any]
    response: dict[str, Any]
    liquidation_evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _Slice3PlanComponents:
    portfolio: Slice3PortfolioBinding
    preview: Slice3AcceptedPreview
    create: Slice3CreateRequest
    caps: Slice3CapEvidence
    close_client_order_id: str


def _mapping(value: object, reason: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise R8Slice3HandoffError(reason)
    return dict(value)


def _sequence(value: object, reason: str) -> list[Any]:
    if not isinstance(value, list):
        raise R8Slice3HandoffError(reason)
    return list(value)


def _decimal(value: object, reason: str) -> Decimal:
    if isinstance(value, bool):
        raise R8Slice3HandoffError(reason)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise R8Slice3HandoffError(reason) from None
    if not result.is_finite():
        raise R8Slice3HandoffError(reason)
    return result


def _aware(value: object, reason: str) -> datetime:
    if not isinstance(value, str):
        raise R8Slice3HandoffError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise R8Slice3HandoffError(reason) from None
    if parsed.tzinfo is None:
        raise R8Slice3HandoffError(reason)
    return parsed.astimezone(timezone.utc)


def _sha256(value: object, reason: str) -> str:
    if not (isinstance(value, str) and len(value) == 64 and set(value) <= _SHA256_HEX):
        raise R8Slice3HandoffError(reason)
    return value


def _load_documented_preview_expiry_evidence(
    *,
    response: Mapping[str, Any],
    accepted_at: datetime,
) -> Mapping[str, Any] | None:
    """Return no evidence until Coinbase publishes an authoritative contract."""

    del response, accepted_at
    return None


def _validate_documented_preview_expiry(
    *,
    response: Mapping[str, Any],
    accepted_at: datetime,
    current: datetime,
) -> tuple[datetime, str, str]:
    evidence_value = _load_documented_preview_expiry_evidence(
        response=response,
        accepted_at=accepted_at,
    )
    if evidence_value is None:
        raise R8Slice3HandoffError("slice3_handoff_preview_expiry_unavailable")
    evidence = _mapping(
        evidence_value,
        "slice3_handoff_preview_expiry_invalid",
    )
    if set(evidence) != {
        "schema_version",
        "source",
        "response_field",
        "accepted_at",
        "expires_at",
        "source_contract_sha256",
        "raw_response_included",
        "identifier_values_included",
    }:
        raise R8Slice3HandoffError("slice3_handoff_preview_expiry_invalid")
    contract_sha256 = COINBASE_ADVANCED_TRADE_PREVIEW_EXPIRY_CONTRACT_SHA256
    if contract_sha256 is None:
        raise R8Slice3HandoffError("slice3_handoff_preview_expiry_unavailable")
    _sha256(contract_sha256, "slice3_handoff_preview_expiry_invalid")
    if not (
        evidence.get("schema_version") == "slice3-preview-expiry-evidence-v1"
        and evidence.get("source") == "coinbase_documented_preview_response"
        and evidence.get("response_field") == "preview_expires_at"
        and evidence.get("accepted_at") == accepted_at.isoformat()
        and evidence.get("source_contract_sha256") == contract_sha256
        and evidence.get("raw_response_included") is False
        and evidence.get("identifier_values_included") is False
    ):
        raise R8Slice3HandoffError("slice3_handoff_preview_expiry_invalid")
    expires_at = _aware(
        evidence.get("expires_at"),
        "slice3_handoff_preview_expiry_invalid",
    )
    if (
        expires_at <= current
        or expires_at <= accepted_at
        or expires_at - accepted_at > SLICE3_MAX_PREVIEW_TTL
    ):
        raise R8Slice3HandoffError("slice3_handoff_preview_expiry_invalid")
    return (
        expires_at,
        "coinbase_documented_preview_response",
        canonical_sha256(evidence),
    )


def _uuid4(value: object, reason: str) -> str:
    if not isinstance(value, str):
        raise R8Slice3HandoffError(reason)
    parsed: UUID | None = None
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError):
        pass
    if parsed is None or parsed.version != 4 or str(parsed) != value.lower():
        raise R8Slice3HandoffError(reason)
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str] | frozenset[str],
    reason: str,
) -> None:
    if set(value) != set(expected):
        raise R8Slice3HandoffError(reason)


def _validate_nested_hash(
    evidence: Mapping[str, Any],
    field: str,
    hash_field: str,
    reason: str,
) -> None:
    value = _mapping(evidence.get(field), reason)
    observed = _sha256(evidence.get(hash_field), reason)
    if observed != canonical_sha256(value):
        raise R8Slice3HandoffError(reason)


def _validate_evidence_hash(value: Mapping[str, Any], reason: str) -> None:
    observed = value.get("evidence_sha256")
    if not isinstance(observed, str) or observed != canonical_sha256(
        {key: item for key, item in value.items() if key != "evidence_sha256"}
    ):
        raise R8Slice3HandoffError(reason)


def _uuid4_text(factory: Callable[[], UUID | str]) -> str:
    try:
        value = factory()
        parsed = value if isinstance(value, UUID) else UUID(str(value))
    except Exception:
        raise R8Slice3HandoffError("slice3_handoff_client_order_id_invalid") from None
    if parsed.version != 4 or str(parsed) != str(value).lower():
        raise R8Slice3HandoffError("slice3_handoff_client_order_id_invalid")
    return str(parsed)


def _validate_exact_r8_pair(
    ephemeral: Mapping[str, Any],
    persisted: Mapping[str, Any],
) -> None:
    _exact_keys(
        ephemeral,
        _EXPECTED_EPHEMERAL_FIELDS,
        "slice3_handoff_ephemeral_shape_invalid",
    )
    _exact_keys(
        persisted,
        _EXPECTED_EPHEMERAL_FIELDS
        | {
            "correlation_id_sha256",
            "idempotency_key_sha256",
            "preview_id_sha256",
            "portfolio_id_sha256",
        },
        "slice3_handoff_terminal_shape_invalid",
    )
    for field in ("correlation_id", "idempotency_key"):
        private_value = ephemeral.get(field)
        if (
            not isinstance(private_value, str)
            or persisted.get(field) != "withheld"
            or persisted.get(f"{field}_sha256")
            != hashlib.sha256(private_value.encode("utf-8")).hexdigest()
        ):
            raise R8Slice3HandoffError(
                "slice3_handoff_private_redaction_invalid"
            )
    if (
        ephemeral.get("schema_version") != "1"
        or ephemeral.get("type") != "admin_futures_order_preview"
        or ephemeral.get("artifact_type") != FUTURES_PREVIEW_R8_ARTIFACT_TYPE
        or ephemeral.get("status") != "accepted"
        or ephemeral.get("outcome") != "accepted"
        or persisted.get("artifact_type") != FUTURES_PREVIEW_R8_ARTIFACT_TYPE
        or persisted.get("status") != "accepted"
        or persisted.get("outcome") != "accepted"
    ):
        raise R8Slice3HandoffError("slice3_handoff_r8_not_accepted")
    _validate_evidence_hash(ephemeral, "slice3_handoff_ephemeral_hash_invalid")
    _validate_evidence_hash(persisted, "slice3_handoff_terminal_hash_invalid")
    try:
        expected = _withhold_r8_private_accepted_evidence(ephemeral)
    except Exception:
        raise R8Slice3HandoffError("slice3_handoff_private_redaction_invalid") from None
    if expected != dict(persisted):
        raise R8Slice3HandoffError("slice3_handoff_terminal_mismatch")
    preview = _mapping(
        ephemeral.get("preview_response"),
        "slice3_handoff_preview_response_invalid",
    )
    preview_id = preview.get("preview_id")
    portfolio_id = ephemeral.get("portfolio_id")
    if not (
        isinstance(preview_id, str)
        and preview_id
        and isinstance(portfolio_id, str)
        and portfolio_id
        and persisted.get("portfolio_id") == "withheld"
        and _mapping(
            persisted.get("preview_response"),
            "slice3_handoff_terminal_mismatch",
        ).get("preview_id")
        == "withheld"
        and persisted.get("preview_id_sha256")
        == hashlib.sha256(preview_id.encode("utf-8")).hexdigest()
        and persisted.get("portfolio_id_sha256")
        == hashlib.sha256(portfolio_id.encode("utf-8")).hexdigest()
    ):
        raise R8Slice3HandoffError("slice3_handoff_private_redaction_invalid")


def _validate_r8_top_contract(
    evidence: Mapping[str, Any],
) -> tuple[datetime, str, str]:
    accepted_at = _aware(
        evidence.get("completed_at"),
        "slice3_handoff_completed_at_invalid",
    )
    reserved_at = _aware(
        evidence.get("reserved_at"),
        "slice3_handoff_reserved_at_invalid",
    )
    correlation_id = _uuid4(
        evidence.get("correlation_id"),
        "slice3_handoff_correlation_id_invalid",
    )
    idempotency_key = _uuid4(
        evidence.get("idempotency_key"),
        "slice3_handoff_idempotency_key_invalid",
    )
    if correlation_id == idempotency_key:
        raise R8Slice3HandoffError("slice3_handoff_identifier_collision")
    if (
        reserved_at > accepted_at
        or evidence.get("predecessor_binding") != FUTURES_PREVIEW_R7_TERMINAL_BINDING
        or evidence.get("actor_id") != FUTURES_PREVIEW_ACTOR_ID
        or evidence.get("actor_id") != SLICE3_ACTOR_ID
        or evidence.get("roles") != list(SLICE3_ROLES)
        or evidence.get("profile_label") != "Default"
        or evidence.get("portfolio_type") != "DEFAULT"
        or evidence.get("product_id") != SLICE3_PRODUCT_ID
        or evidence.get("attempt_counters") != _EXPECTED_ATTEMPTS
        or evidence.get("read_counters") != _EXPECTED_READS
        or evidence.get("exchange_submission_attempt_count") != 0
        or evidence.get("submitted_notional_usdc") != "0"
        or evidence.get("executed_notional_usdc") != "0"
        or evidence.get("live_execution") != "not_run"
        or evidence.get("live_coinbase_execution") != "not_run"
        or evidence.get("live_coinbase_read_ran") is not True
        or evidence.get("read_only") is not True
        or evidence.get("browser_authority") != "display_only"
        or evidence.get("bff_authority") != "forward_only_no_execution"
        or evidence.get("artifacts") != _EXPECTED_ARTIFACTS
        or evidence.get("post_preview_stage_evidence") is not None
        or evidence.get("post_preview_stage_evidence_sha256") is not None
        or evidence.get("canonicalization") != "sorted_keys_compact_utf8_json"
        or evidence.get("hash_algorithm") != "sha256"
    ):
        raise R8Slice3HandoffError("slice3_handoff_scope_invalid")
    _sha256(evidence.get("claim_sha256"), "slice3_handoff_claim_hash_invalid")
    for field, hash_field in (
        ("permission_evidence", "permission_evidence_sha256"),
        ("portfolio_catalog_evidence", "portfolio_catalog_sha256"),
        ("product_evidence", "product_evidence_sha256"),
        ("market_evidence", "market_evidence_sha256"),
        ("position_evidence", "position_evidence_sha256"),
        ("margin_collateral_evidence", "margin_collateral_evidence_sha256"),
        ("margin_setting_evidence", "margin_setting_evidence_sha256"),
        (
            "margin_windows_policy_evidence",
            "margin_windows_policy_evidence_sha256",
        ),
        ("candidate", "candidate_sha256"),
        ("preview_request", "preview_request_sha256"),
        ("preview_response", "preview_response_sha256"),
        ("seal_ready_plan", "seal_ready_plan_sha256"),
    ):
        _validate_nested_hash(
            evidence,
            field,
            hash_field,
            f"slice3_handoff_{field}_hash_invalid",
        )
    return accepted_at, correlation_id, idempotency_key


def _validate_r8_source_observation_times(
    evidence: Mapping[str, Any],
    *,
    accepted_at: datetime,
) -> None:
    """Reprove the producer's ordered, bounded source-observation timeline."""

    portfolio = _mapping(
        evidence.get("portfolio_binding"),
        "slice3_handoff_portfolio_invalid",
    )
    candidate = _mapping(
        evidence.get("candidate"),
        "slice3_handoff_candidate_invalid",
    )
    market = _mapping(
        evidence.get("market_evidence"),
        "slice3_handoff_market_invalid",
    )
    portfolio_at = _aware(
        portfolio.get("observed_at"),
        "slice3_handoff_portfolio_invalid",
    )
    candidate_at = _aware(
        candidate.get("observed_at"),
        "slice3_handoff_candidate_invalid",
    )
    market_at = _aware(
        market.get("exchange_observed_at"),
        "slice3_handoff_market_invalid",
    )
    if (
        candidate_at > accepted_at
        or accepted_at - candidate_at > R8_SLICE3_HANDOFF_MAX_AGE
    ):
        raise R8Slice3HandoffError("slice3_handoff_candidate_invalid")
    if (
        portfolio_at > candidate_at
        or accepted_at - portfolio_at > R8_SLICE3_HANDOFF_MAX_AGE
    ):
        raise R8Slice3HandoffError("slice3_handoff_portfolio_invalid")
    market_age = candidate_at - market_at
    if (
        market_age < -R8_SLICE3_MARKET_MAX_FUTURE_SKEW
        or market_age > R8_SLICE3_MARKET_MAX_AGE
    ):
        raise R8Slice3HandoffError("slice3_handoff_market_invalid")


def _validate_portfolio_contract(
    evidence: Mapping[str, Any],
    *,
    accepted_at: datetime,
) -> str:
    portfolio_id = evidence.get("portfolio_id")
    if not isinstance(portfolio_id, str) or not portfolio_id:
        raise R8Slice3HandoffError("slice3_handoff_portfolio_invalid")
    binding = _mapping(
        evidence.get("portfolio_binding"),
        "slice3_handoff_portfolio_invalid",
    )
    _exact_keys(
        binding,
        {
            "account_family",
            "bff_authority",
            "blocker",
            "browser_authority",
            "can_trade",
            "can_view",
            "command_authority_granted",
            "credential_trade_permission_present",
            "expected_portfolio_label",
            "expected_portfolio_type",
            "freshness_status",
            "live_coinbase_execution_authorized",
            "observed_at",
            "observed_portfolio_id",
            "observed_portfolio_label",
            "observed_portfolio_type",
            "permissions_error_present",
            "permissions_read_ran",
            "portfolio_catalog_error_present",
            "portfolio_catalog_read_ran",
            "portfolio_id",
            "product_family",
            "profile_alias",
            "read_authorized",
            "ready",
            "request_portfolio_override_allowed",
            "selection_authority",
            "source",
            "status",
        },
        "slice3_handoff_portfolio_invalid",
    )
    _aware(
        binding.get("observed_at"),
        "slice3_handoff_portfolio_invalid",
    )
    expected_binding = {
        "account_family": "coinbase_futures_us_cfm",
        "bff_authority": "forward_only_no_execution",
        "blocker": None,
        "browser_authority": "display_only",
        "can_trade": True,
        "can_view": True,
        "command_authority_granted": False,
        "credential_trade_permission_present": True,
        "expected_portfolio_label": "Default",
        "expected_portfolio_type": "DEFAULT",
        "freshness_status": "backend_rest_fresh",
        "live_coinbase_execution_authorized": False,
        "observed_portfolio_id": portfolio_id,
        "observed_portfolio_label": "Default",
        "observed_portfolio_type": "DEFAULT",
        "permissions_error_present": False,
        "permissions_read_ran": True,
        "portfolio_catalog_error_present": False,
        "portfolio_catalog_read_ran": True,
        "portfolio_id": portfolio_id,
        "product_family": "FUTURES_PERPETUALS",
        "profile_alias": "Default",
        "read_authorized": True,
        "ready": True,
        "request_portfolio_override_allowed": False,
        "selection_authority": "cdp_api_key_permissioned_portfolio",
        "source": "coinbase_api_key_permissions_and_portfolio_catalog",
        "status": "matched",
    }
    if any(
        binding.get(key) != value for key, value in expected_binding.items()
    ):
        raise R8Slice3HandoffError("slice3_handoff_portfolio_invalid")

    permission = _mapping(
        evidence.get("permission_evidence"),
        "slice3_handoff_permission_invalid",
    )
    if permission != {
        "portfolio_id": portfolio_id,
        "portfolio_type": "DEFAULT",
        "can_view": True,
        "can_trade": True,
        "selection_authority": "cdp_api_key_permissioned_portfolio",
        "sanitized": True,
        "raw_response_included": False,
    }:
        raise R8Slice3HandoffError("slice3_handoff_permission_invalid")
    catalog = _mapping(
        evidence.get("portfolio_catalog_evidence"),
        "slice3_handoff_portfolio_catalog_invalid",
    )
    if catalog != {
        "selected_portfolio_id": portfolio_id,
        "selected_portfolio_label": "Default",
        "selected_portfolio_type": "DEFAULT",
        "exact_match_count": 1,
        "sanitized": True,
        "raw_response_included": False,
    }:
        raise R8Slice3HandoffError("slice3_handoff_portfolio_catalog_invalid")
    return portfolio_id


def _validate_margin_pair(evidence: Mapping[str, Any]) -> tuple[str, str]:
    margin = _mapping(
        evidence.get("margin_collateral_evidence"),
        "slice3_handoff_margin_invalid",
    )
    _exact_keys(
        margin,
        {
            "status",
            "account_family",
            "source",
            "source_read_attempts",
            "available_margin_usdc",
            "intraday_margin_window_measure",
            "intraday_margin_setting",
            "current_margin_windows",
            "futures_sweep_count",
            "sanitized",
            "raw_response_included",
        },
        "slice3_handoff_margin_invalid",
    )
    if (
        margin.get("status") != "ready"
        or margin.get("account_family") != "coinbase_futures_us_cfm"
        or margin.get("source") != "backend_rest_client"
        or margin.get("source_read_attempts") != _EXPECTED_SOURCE_READS
        or not isinstance(margin.get("intraday_margin_setting"), Mapping)
        or margin.get("futures_sweep_count") != 0
        or margin.get("sanitized") is not True
        or margin.get("raw_response_included") is not False
    ):
        raise R8Slice3HandoffError("slice3_handoff_margin_invalid")
    setting_container = _mapping(
        margin.get("intraday_margin_setting"),
        "slice3_handoff_margin_setting_invalid",
    )
    setting = setting_container.get("setting")
    if (
        set(setting_container) != {"setting"}
        or setting
        not in {
            "INTRADAY_MARGIN_SETTING_STANDARD",
            "INTRADAY_MARGIN_SETTING_INTRADAY",
        }
    ):
        raise R8Slice3HandoffError("slice3_handoff_margin_setting_invalid")
    measure = _mapping(
        margin.get("intraday_margin_window_measure"),
        "slice3_handoff_margin_invalid",
    )
    if (
        set(measure)
        != {
            "margin_window_type",
            "maintenance_margin_usdc",
            "liquidation_buffer_usdc",
        }
        or measure.get("margin_window_type") != "FCM_MARGIN_WINDOW_TYPE_INTRADAY"
        or _decimal(
            measure.get("maintenance_margin_usdc"),
            "slice3_handoff_margin_invalid",
        )
        < 0
        or _decimal(
            measure.get("liquidation_buffer_usdc"),
            "slice3_handoff_margin_invalid",
        )
        < 0
    ):
        raise R8Slice3HandoffError("slice3_handoff_margin_invalid")
    rows: list[dict[str, Any]] = []
    for row_value in _sequence(
        margin.get("current_margin_windows"),
        "slice3_handoff_margin_pair_invalid",
    ):
        row = _mapping(row_value, "slice3_handoff_margin_pair_invalid")
        rows.append(row)
    expected_rows = [
        {
            "profile": profile,
            "margin_window_type": window,
            "is_intraday_margin_killswitch_enabled": False,
            "is_intraday_margin_enrollment_killswitch_enabled": False,
        }
        for profile, window in _EXPECTED_MARGIN_ROWS
    ]
    if rows != expected_rows:
        raise R8Slice3HandoffError("slice3_handoff_margin_pair_invalid")
    policy = _mapping(
        evidence.get("margin_windows_policy_evidence"),
        "slice3_handoff_margin_policy_invalid",
    )
    expected_policy = {
        "schema_version": "3",
        "policy_id": "slice2_preview_margin_window_exact_pair_policy_v3",
        "stage": "margin_collateral_validation",
        "source": "backend_rest_client.get_current_margin_window",
        "field_path": "current_margin_windows",
        "enum_authority": "official_coinbase_advanced_trade_api_docs",
        "profile_state_policy_authority": (
            "operator_defined_slice_2_preview_only_not_coinbase_documented"
        ),
        "profile_state_mapping_documented_by_coinbase": False,
        "pair_policy_mode": "exact_profile_state_pair",
        "eligibility_scope": "slice_2_preview_only",
        "r5_attempt_authority_granted": False,
        "r6_attempt_authority_granted": False,
        "execution_allowed": False,
        "create_order_eligibility_granted": False,
        "later_live_eligibility_granted": False,
        "container_present": True,
        "container_type": "sequence",
        "expected_row_count": 2,
        "row_count_bucket": "expected_two",
        "classification": "ready",
        "failing_policy_row_index": None,
        "recognized_profile": None,
        "failing_field": None,
        "failing_value_type": None,
        "margin_window_policy_satisfied": True,
        "rows": [
            {
                "policy_row_index": index,
                "recognized_profile": profile,
                "observed_token": window,
                "documented_allowlist_match": True,
                "operator_policy_match": True,
                "classification": "accepted",
            }
            for index, (profile, window) in enumerate(_EXPECTED_POLICY_ROWS)
        ],
        "sanitized": True,
        "raw_response_included": False,
        "external_exception_text_included": False,
        "unknown_identifier_values_included": False,
    }
    if policy != expected_policy:
        raise R8Slice3HandoffError("slice3_handoff_margin_policy_invalid")
    margin_setting = _mapping(
        evidence.get("margin_setting_evidence"),
        "slice3_handoff_margin_setting_invalid",
    )
    if margin_setting != {
        "stage": "margin_collateral_validation",
        "source": "backend_rest_client.get_intraday_margin_setting",
        "field_path": "intraday_margin_setting.setting",
        "enum_authority": "official_coinbase_advanced_trade_api_docs",
        "container_present": True,
        "container_type": "mapping",
        "field_present": True,
        "value_type": "string",
        "token_form": "safe_enum_token",
        "observed_token": setting,
        "allowlist_match": True,
        "operationally_resolved": True,
        "classification": "recognized_string",
        "unexpected_field_count": 0,
        "sanitized": True,
        "raw_response_included": False,
    }:
        raise R8Slice3HandoffError("slice3_handoff_margin_setting_invalid")
    available = margin.get("available_margin_usdc")
    if _decimal(available, "slice3_handoff_margin_invalid") <= 0:
        raise R8Slice3HandoffError("slice3_handoff_margin_invalid")
    return str(available), str(setting)


def _validate_preflight_contracts(
    evidence: Mapping[str, Any],
    *,
    accepted_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    product = _mapping(
        evidence.get("product_evidence"),
        "slice3_handoff_product_invalid",
    )
    _exact_keys(
        product,
        {
            "product_id",
            "display_name",
            "product_type",
            "status",
            "price",
            "price_increment",
            "base_increment",
            "base_min_size",
            "trading_disabled",
            "view_only",
            "cancel_only",
            "future_product_details",
            "sanitized",
            "raw_response_included",
        },
        "slice3_handoff_product_invalid",
    )
    details = _mapping(
        product.get("future_product_details"),
        "slice3_handoff_product_invalid",
    )
    if (
        product.get("product_id") != SLICE3_PRODUCT_ID
        or product.get("display_name") != "AVAX PERP"
        or product.get("product_type") != "FUTURE"
        or product.get("status") != ""
        or _decimal(product.get("price"), "slice3_handoff_product_invalid") <= 0
        or product.get("price_increment") != "0.01"
        or product.get("base_increment") != "1"
        or product.get("base_min_size") != "1"
        or product.get("trading_disabled") is not False
        or product.get("view_only") is not False
        or product.get("cancel_only") is not False
        or product.get("sanitized") is not True
        or product.get("raw_response_included") is not False
        or details
        != {
            "contract_size": "10",
            "contract_code": "AVP",
            "group_description": "Avalanche Perp Futures",
            "group_short_description": "Avalanche Perp",
            "venue": "cde",
            "risk_managed_by": "MANAGED_BY_FCM",
            "contract_expiry": "2030-12-20T16:00:00Z",
            "contract_expiry_type": "EXPIRING",
        }
    ):
        raise R8Slice3HandoffError("slice3_handoff_product_invalid")

    market = _mapping(
        evidence.get("market_evidence"),
        "slice3_handoff_market_invalid",
    )
    _exact_keys(
        market,
        {
            "product_id",
            "best_bid",
            "best_ask",
            "exchange_observed_at",
            "sanitized",
            "raw_response_included",
        },
        "slice3_handoff_market_invalid",
    )
    best_bid = _decimal(market.get("best_bid"), "slice3_handoff_market_invalid")
    best_ask = _decimal(market.get("best_ask"), "slice3_handoff_market_invalid")
    _aware(
        market.get("exchange_observed_at"),
        "slice3_handoff_market_invalid",
    )
    if (
        market.get("product_id") != SLICE3_PRODUCT_ID
        or best_bid <= 0
        or best_ask <= best_bid
        or market.get("sanitized") is not True
        or market.get("raw_response_included") is not False
    ):
        raise R8Slice3HandoffError("slice3_handoff_market_invalid")

    position = _mapping(
        evidence.get("position_evidence"),
        "slice3_handoff_position_invalid",
    )
    if position != {
        "product_id": SLICE3_PRODUCT_ID,
        "observed_contract_count": "0",
        "sanitized": True,
        "raw_response_included": False,
    }:
        raise R8Slice3HandoffError("slice3_handoff_position_invalid")
    return product, market


def _validate_candidate_and_preview(
    evidence: Mapping[str, Any],
    *,
    accepted_at: datetime,
    product: Mapping[str, Any],
    market: Mapping[str, Any],
    available_margin: str,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    candidate = _mapping(
        evidence.get("candidate"),
        "slice3_handoff_candidate_invalid",
    )
    _exact_keys(
        candidate,
        {
            "product_id",
            "contract_count",
            "contract_size",
            "side",
            "order_type",
            "post_only",
            "limit_price",
            "reference_price",
            "opening_reference_notional_usdc",
            "maximum_exposure_reference_notional_usdc",
            "buffered_close_reference_notional_usdc",
            "branch_turnover_reference_notional_usdc",
            "opening_cap_usdc",
            "exposure_cap_usdc",
            "turnover_cap_usdc",
            "close_buffer_multiplier",
            "observed_concurrent_exposure_usdc",
            "best_bid",
            "best_ask",
            "product_price",
            "price_increment",
            "reference_price_source",
            "product_classification",
            "contract_code",
            "venue",
            "risk_managed_by",
            "contract_expiry",
            "contract_expiry_type",
            "observed_at",
        },
        "slice3_handoff_candidate_invalid",
    )
    reference_price = _decimal(
        candidate.get("reference_price"),
        "slice3_handoff_candidate_invalid",
    )
    opening = _decimal(
        candidate.get("opening_reference_notional_usdc"),
        "slice3_handoff_candidate_invalid",
    )
    maximum_exposure = _decimal(
        candidate.get("maximum_exposure_reference_notional_usdc"),
        "slice3_handoff_candidate_invalid",
    )
    buffered_close = _decimal(
        candidate.get("buffered_close_reference_notional_usdc"),
        "slice3_handoff_candidate_invalid",
    )
    turnover = _decimal(
        candidate.get("branch_turnover_reference_notional_usdc"),
        "slice3_handoff_candidate_invalid",
    )
    details = _mapping(
        product.get("future_product_details"),
        "slice3_handoff_candidate_invalid",
    )
    _aware(
        candidate.get("observed_at"),
        "slice3_handoff_candidate_invalid",
    )
    if (
        candidate.get("product_id") != SLICE3_PRODUCT_ID
        or candidate.get("contract_count") != "1"
        or candidate.get("contract_size") != "10"
        or candidate.get("side") != "BUY"
        or candidate.get("order_type") != "LIMIT_GTC"
        or candidate.get("post_only") != "true"
        or _decimal(
            candidate.get("limit_price"),
            "slice3_handoff_candidate_invalid",
        )
        <= 0
        or reference_price
        != max(
            _decimal(product.get("price"), "slice3_handoff_candidate_invalid"),
            _decimal(market.get("best_ask"), "slice3_handoff_candidate_invalid"),
        )
        or opening != reference_price * Decimal("10")
        or maximum_exposure != opening
        or _decimal(
            candidate.get("observed_concurrent_exposure_usdc"),
            "slice3_handoff_candidate_invalid",
        )
        != opening
        or buffered_close != maximum_exposure * Decimal("1.20")
        or turnover != opening + buffered_close
        or opening >= Decimal("100")
        or maximum_exposure >= Decimal("150")
        or buffered_close >= Decimal("150")
        or turnover >= Decimal("300")
        or candidate.get("opening_cap_usdc") != "100"
        or candidate.get("exposure_cap_usdc") != "150"
        or candidate.get("turnover_cap_usdc") != "300"
        or candidate.get("close_buffer_multiplier") != "1.20"
        or candidate.get("best_bid") != market.get("best_bid")
        or candidate.get("best_ask") != market.get("best_ask")
        or candidate.get("product_price") != product.get("price")
        or candidate.get("price_increment") != product.get("price_increment")
        or candidate.get("reference_price_source")
        != "max_product_price_and_fresh_best_ask"
        or candidate.get("product_classification") != "PERP_STYLE_FUTURE"
        or candidate.get("contract_code") != details.get("contract_code")
        or candidate.get("venue") != details.get("venue")
        or candidate.get("risk_managed_by") != details.get("risk_managed_by")
        or candidate.get("contract_expiry") != details.get("contract_expiry")
        or candidate.get("contract_expiry_type") != details.get("contract_expiry_type")
    ):
        raise R8Slice3HandoffError("slice3_handoff_candidate_invalid")

    request = _mapping(
        evidence.get("preview_request"),
        "slice3_handoff_preview_request_invalid",
    )
    configuration = _mapping(
        request.get("order_configuration"),
        "slice3_handoff_preview_request_invalid",
    )
    limit = _mapping(
        configuration.get("limit_limit_gtc"),
        "slice3_handoff_preview_request_invalid",
    )
    if (
        set(request) != {"product_id", "side", "order_configuration"}
        or request.get("product_id") != SLICE3_PRODUCT_ID
        or request.get("side") != "BUY"
        or set(configuration) != {"limit_limit_gtc"}
        or limit
        != {
            "base_size": "1",
            "limit_price": candidate.get("limit_price"),
            "post_only": True,
        }
    ):
        raise R8Slice3HandoffError("slice3_handoff_preview_request_invalid")

    response = _mapping(
        evidence.get("preview_response"),
        "slice3_handoff_preview_response_invalid",
    )
    expected_response_fields = {
        "preview_id",
        "errs",
        "warning",
        "order_total",
        "commission_total",
        "quote_size",
        "base_size",
        "best_bid",
        "best_ask",
        "order_margin_total",
        "margin_ratio_data",
        "liquidation_evidence_source",
        "candidate_binding",
    }
    if "predicted_liquidation_price" in response:
        expected_response_fields.add("predicted_liquidation_price")
    _exact_keys(
        response,
        expected_response_fields,
        "slice3_handoff_preview_response_invalid",
    )
    preview_id = response.get("preview_id")
    commission = _decimal(
        response.get("commission_total"),
        "slice3_handoff_preview_response_invalid",
    )
    order_margin = _decimal(
        response.get("order_margin_total"),
        "slice3_handoff_preview_response_invalid",
    )
    order_total = _decimal(
        response.get("order_total"),
        "slice3_handoff_preview_response_invalid",
    )
    quote_size = _decimal(
        response.get("quote_size"),
        "slice3_handoff_preview_response_invalid",
    )
    if (
        not isinstance(preview_id, str)
        or not preview_id
        or response.get("errs") != []
        or response.get("warning") != []
        or response.get("base_size") != "1"
        or response.get("best_bid") != market.get("best_bid")
        or response.get("best_ask") != market.get("best_ask")
        or order_total <= 0
        or quote_size <= 0
        or commission < 0
        or order_margin <= 0
        or _decimal(available_margin, "slice3_handoff_margin_invalid")
        <= order_margin + commission
        or evidence.get("preview_response_schema_binding")
        != FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING
    ):
        raise R8Slice3HandoffError("slice3_handoff_preview_response_invalid")

    binding = _mapping(
        response.get("candidate_binding"),
        "slice3_handoff_preview_response_invalid",
    )
    expected_binding = {
        "status": "matched",
        "contract_count": "1",
        "authoritative_opening_reference_notional_usdc": str(
            candidate["opening_reference_notional_usdc"]
        ),
        "maximum_exposure_reference_notional_usdc": str(
            candidate["maximum_exposure_reference_notional_usdc"]
        ),
        "buffered_close_reference_notional_usdc": str(
            candidate["buffered_close_reference_notional_usdc"]
        ),
        "branch_turnover_reference_notional_usdc": str(
            candidate["branch_turnover_reference_notional_usdc"]
        ),
        "reference_rule": (
            "max_candidate_reference_preview_ask_contract_notional_"
            "order_total_plus_fee_quote_size_plus_fee"
        ),
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "comparison": "strictly_less_than",
    }
    authoritative_opening = max(
        opening,
        _decimal(market["best_ask"], "slice3_handoff_preview_response_invalid")
        * Decimal("10"),
        order_total + commission,
        quote_size + commission,
    )
    if (
        binding != expected_binding
        or _decimal(
            binding.get("authoritative_opening_reference_notional_usdc"),
            "slice3_handoff_preview_response_invalid",
        )
        != authoritative_opening
        or authoritative_opening != opening
    ):
        raise R8Slice3HandoffError("slice3_handoff_preview_response_invalid")

    ratios = _mapping(
        response.get("margin_ratio_data"),
        "slice3_handoff_preview_response_invalid",
    )
    if set(ratios) != {"current_margin_ratio", "projected_margin_ratio"} or any(
        _decimal(value, "slice3_handoff_preview_response_invalid") < 0
        for value in ratios.values()
    ):
        raise R8Slice3HandoffError("slice3_handoff_preview_response_invalid")
    liquidation_source = response.get("liquidation_evidence_source")
    liquidation_evidence: dict[str, Any] = {"margin_ratio_data": ratios}
    if "predicted_liquidation_price" in response:
        if (
            liquidation_source != "margin_ratio_data_and_predicted_liquidation_price"
            or _decimal(
                response.get("predicted_liquidation_price"),
                "slice3_handoff_preview_response_invalid",
            )
            <= 0
        ):
            raise R8Slice3HandoffError("slice3_handoff_preview_response_invalid")
        liquidation_evidence["predicted_liquidation_price"] = response[
            "predicted_liquidation_price"
        ]
    elif liquidation_source != "margin_ratio_data":
        raise R8Slice3HandoffError("slice3_handoff_preview_response_invalid")
    return candidate, request, response, liquidation_evidence


def _validate_seal_contract(
    evidence: Mapping[str, Any],
    *,
    portfolio_id: str,
    candidate: Mapping[str, Any],
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    liquidation_evidence: Mapping[str, Any],
) -> None:
    if (
        evidence.get("post_preview_diagnostic_binding")
        != FUTURES_PREVIEW_R8_POST_PREVIEW_DIAGNOSTIC_BINDING
    ):
        raise R8Slice3HandoffError("slice3_handoff_diagnostic_binding_invalid")
    seal = _mapping(
        evidence.get("seal_ready_plan"),
        "slice3_handoff_seal_plan_invalid",
    )
    _exact_keys(
        seal,
        {
            "schema_version",
            "slice_id",
            "actor_id",
            "roles",
            "correlation_id",
            "idempotency_key",
            "predecessor_binding",
            "profile_binding",
            "product_id",
            "contract_count",
            "candidate",
            "preview_request",
            "preview_request_sha256",
            "authoritative_preview",
            "caps",
            "attempt_policy",
            "preflight_evidence_hashes",
            "no_live_posture",
            "canonicalization",
            "hash_algorithm",
            "margin_window_policy_binding",
            "preview_response_schema_binding",
            "post_preview_diagnostic_binding",
        },
        "slice3_handoff_seal_plan_invalid",
    )
    if (
        seal.get("schema_version") != "1"
        or seal.get("slice_id") != FUTURES_PREVIEW_R8_ARTIFACT_TYPE
        or seal.get("actor_id") != evidence.get("actor_id")
        or seal.get("roles") != evidence.get("roles")
        or seal.get("correlation_id") != evidence.get("correlation_id")
        or seal.get("idempotency_key") != evidence.get("idempotency_key")
        or seal.get("predecessor_binding") != FUTURES_PREVIEW_R7_TERMINAL_BINDING
        or seal.get("product_id") != SLICE3_PRODUCT_ID
        or seal.get("contract_count") != "1"
        or seal.get("candidate") != dict(candidate)
        or seal.get("preview_request") != dict(request)
        or seal.get("preview_request_sha256") != canonical_sha256(request)
        or seal.get("caps") != _EXPECTED_SEAL_CAPS
        or seal.get("attempt_policy") != _EXPECTED_ATTEMPTS
        or seal.get("no_live_posture") != _EXPECTED_NO_LIVE_POSTURE
        or seal.get("canonicalization") != "sorted_keys_compact_utf8_json"
        or seal.get("hash_algorithm") != "sha256"
        or seal.get("margin_window_policy_binding")
        != FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING
        or seal.get("preview_response_schema_binding")
        != FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING
        or seal.get("post_preview_diagnostic_binding")
        != FUTURES_PREVIEW_R8_POST_PREVIEW_DIAGNOSTIC_BINDING
    ):
        raise R8Slice3HandoffError("slice3_handoff_seal_plan_invalid")
    profile = _mapping(
        seal.get("profile_binding"),
        "slice3_handoff_seal_plan_invalid",
    )
    if profile != {
        "profile_label": "Default",
        "portfolio_type": "DEFAULT",
        "portfolio_id": portfolio_id,
        "selection_authority": "cdp_api_key_permissioned_portfolio",
        "request_portfolio_override_allowed": False,
    }:
        raise R8Slice3HandoffError("slice3_handoff_seal_plan_invalid")
    preflight = _mapping(
        seal.get("preflight_evidence_hashes"),
        "slice3_handoff_seal_plan_invalid",
    )
    expected_preflight = {
        "permissions": evidence.get("permission_evidence_sha256"),
        "portfolio_catalog": evidence.get("portfolio_catalog_sha256"),
        "product": evidence.get("product_evidence_sha256"),
        "market": evidence.get("market_evidence_sha256"),
        "positions": evidence.get("position_evidence_sha256"),
        "margin_collateral": evidence.get("margin_collateral_evidence_sha256"),
        "margin_windows_policy_evidence": evidence.get(
            "margin_windows_policy_evidence_sha256"
        ),
    }
    if preflight != expected_preflight:
        raise R8Slice3HandoffError("slice3_handoff_seal_plan_invalid")
    authoritative = _mapping(
        seal.get("authoritative_preview"),
        "slice3_handoff_seal_plan_invalid",
    )
    _exact_keys(
        authoritative,
        {
            "preview_id",
            "preview_response",
            "preview_response_sha256",
            "candidate_binding",
            "commission_total",
            "order_margin_total",
            "liquidation_evidence_source",
            "liquidation_evidence",
            "margin_collateral_evidence_sha256",
        },
        "slice3_handoff_seal_plan_invalid",
    )
    if (
        authoritative.get("preview_id") != response.get("preview_id")
        or authoritative.get("preview_response") != dict(response)
        or authoritative.get("preview_response_sha256")
        != evidence.get("preview_response_sha256")
        or authoritative.get("candidate_binding") != response.get("candidate_binding")
        or authoritative.get("commission_total") != response.get("commission_total")
        or authoritative.get("order_margin_total") != response.get("order_margin_total")
        or authoritative.get("liquidation_evidence_source")
        != response.get("liquidation_evidence_source")
        or authoritative.get("liquidation_evidence") != dict(liquidation_evidence)
        or authoritative.get("margin_collateral_evidence_sha256")
        != evidence.get("margin_collateral_evidence_sha256")
    ):
        raise R8Slice3HandoffError("slice3_handoff_seal_plan_invalid")


def _liquidation_evidence_sha256(
    response: Mapping[str, Any],
    liquidation_evidence: Mapping[str, Any],
) -> str:
    return canonical_sha256(
        {
            "source": response["liquidation_evidence_source"],
            "evidence": dict(liquidation_evidence),
            "preview_response_schema_binding": dict(
                FUTURES_PREVIEW_R7_RESPONSE_SCHEMA_BINDING
            ),
        }
    )


def _fee_funding_evidence_sha256(
    evidence: Mapping[str, Any],
    response: Mapping[str, Any],
) -> str:
    return canonical_sha256(
        {
            "commission_total": response["commission_total"],
            "order_margin_total": response["order_margin_total"],
            "available_margin_usdc": _mapping(
                evidence["margin_collateral_evidence"],
                "slice3_handoff_margin_invalid",
            )["available_margin_usdc"],
            "funding_rule": (
                "available_margin_strictly_greater_than_order_margin_plus_commission"
            ),
        }
    )


def _build_execution_authority(
    evidence: Mapping[str, Any],
    *,
    authorization_sha256: str,
    adapter_evidence_sha256: str,
    accepted_at: datetime,
    correlation_id: str,
    idempotency_key: str,
    portfolio_id: str,
    candidate: Mapping[str, Any],
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    liquidation_evidence: Mapping[str, Any],
) -> Slice3ExecutionAuthority:
    authorization_hash = _sha256(
        authorization_sha256,
        "slice3_handoff_authorization_sha256_invalid",
    )
    adapter_hash = _sha256(
        adapter_evidence_sha256,
        "slice3_handoff_adapter_evidence_sha256_invalid",
    )
    approval = {
        "authorization_sha256": authorization_hash,
        "actor_id": SLICE3_ACTOR_ID,
        "roles": list(SLICE3_ROLES),
    }
    admission = {
        "product_id": SLICE3_PRODUCT_ID,
        "contract_count": "1",
        "side": "BUY",
        "portfolio_id_sha256": hashlib.sha256(portfolio_id.encode("utf-8")).hexdigest(),
        "permission_evidence_sha256": evidence["permission_evidence_sha256"],
        "portfolio_catalog_sha256": evidence["portfolio_catalog_sha256"],
        "preview_request_sha256": evidence["preview_request_sha256"],
    }
    cap_guard = {
        "opening_reference_notional_usdc": candidate["opening_reference_notional_usdc"],
        "maximum_exposure_reference_notional_usdc": candidate[
            "maximum_exposure_reference_notional_usdc"
        ],
        "buffered_close_reference_notional_usdc": candidate[
            "buffered_close_reference_notional_usdc"
        ],
        "branch_turnover_reference_notional_usdc": candidate[
            "branch_turnover_reference_notional_usdc"
        ],
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "comparison": "strictly_less_than",
    }
    reconciliation = {
        "directives": [directive.value for directive in Slice3DirectiveKind],
        "read_slots": [slot.value for slot in Slice3ReadSlot],
        "read_attempt_limit_per_slot": 1,
        "polling_allowed": False,
        "pagination_allowed": False,
        "retry_allowed": False,
        "fallback_allowed": False,
        "redirect_allowed": False,
    }
    live_service = {
        "route": SLICE3_ROUTE,
        "method": SLICE3_METHOD,
        "service_method": SLICE3_SERVICE_METHOD,
        "permission": SLICE3_PERMISSION,
        "live_policy_sha256": canonical_sha256(SLICE3_LIVE_POLICY.sanitized_evidence()),
    }
    return Slice3ExecutionAuthority(
        actor_id=SLICE3_ACTOR_ID,
        roles=SLICE3_ROLES,
        correlation_id=correlation_id,
        preview_idempotency_key=idempotency_key,
        authorization_sha256=authorization_hash,
        route=SLICE3_ROUTE,
        method=SLICE3_METHOD,
        service_method=SLICE3_SERVICE_METHOD,
        permission=SLICE3_PERMISSION,
        approval_evidence_sha256=canonical_sha256(approval),
        admission_evidence_sha256=canonical_sha256(admission),
        cap_guard_evidence_sha256=canonical_sha256(cap_guard),
        reconciliation_evidence_sha256=canonical_sha256(reconciliation),
        live_service_evidence_sha256=canonical_sha256(live_service),
        adapter_evidence_sha256=adapter_hash,
        product_evidence_sha256=str(evidence["product_evidence_sha256"]),
        market_evidence_sha256=str(evidence["market_evidence_sha256"]),
        margin_collateral_evidence_sha256=str(
            evidence["margin_collateral_evidence_sha256"]
        ),
        liquidation_evidence_sha256=_liquidation_evidence_sha256(
            response,
            liquidation_evidence,
        ),
        fee_funding_evidence_sha256=_fee_funding_evidence_sha256(
            evidence,
            response,
        ),
        observed_at=accepted_at,
    )


def _validate_r8_plan_inputs(
    *,
    ephemeral_evidence: Mapping[str, Any],
    persisted_terminal: Mapping[str, Any],
    now: datetime,
) -> _ValidatedR8PlanInputs:
    ephemeral = _mapping(
        ephemeral_evidence,
        "slice3_handoff_ephemeral_invalid",
    )
    persisted = _mapping(
        persisted_terminal,
        "slice3_handoff_terminal_invalid",
    )
    _validate_exact_r8_pair(ephemeral, persisted)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise R8Slice3HandoffError("slice3_handoff_now_invalid")
    current = now.astimezone(timezone.utc)
    accepted_at, correlation_id, idempotency_key = _validate_r8_top_contract(ephemeral)
    _validate_r8_source_observation_times(
        ephemeral,
        accepted_at=accepted_at,
    )
    age = current - accepted_at
    if age < timedelta(0) or age >= R8_SLICE3_HANDOFF_MAX_AGE:
        raise R8Slice3HandoffError("slice3_handoff_stale")
    portfolio_id = _validate_portfolio_contract(
        ephemeral,
        accepted_at=accepted_at,
    )
    product, market = _validate_preflight_contracts(
        ephemeral,
        accepted_at=accepted_at,
    )
    available_margin, intraday_margin_setting = _validate_margin_pair(ephemeral)
    candidate, request, response, liquidation_evidence = (
        _validate_candidate_and_preview(
            ephemeral,
            accepted_at=accepted_at,
            product=product,
            market=market,
            available_margin=available_margin,
        )
    )
    _validate_seal_contract(
        ephemeral,
        portfolio_id=portfolio_id,
        candidate=candidate,
        request=request,
        response=response,
        liquidation_evidence=liquidation_evidence,
    )
    expires_at, expiry_source, expiry_evidence_sha256 = (
        _validate_documented_preview_expiry(
            response=response,
            accepted_at=accepted_at,
            current=current,
        )
    )
    return _ValidatedR8PlanInputs(
        ephemeral=ephemeral,
        persisted=persisted,
        current=current,
        accepted_at=accepted_at,
        expires_at=expires_at,
        expiry_source=expiry_source,
        expiry_evidence_sha256=expiry_evidence_sha256,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        portfolio_id=portfolio_id,
        available_margin=available_margin,
        intraday_margin_setting=intraday_margin_setting,
        candidate=dict(candidate),
        request=dict(request),
        response=dict(response),
        liquidation_evidence=dict(liquidation_evidence),
    )


def _build_slice3_plan_components(
    validated: _ValidatedR8PlanInputs,
    *,
    client_order_id_factory: Callable[[], UUID | str],
) -> _Slice3PlanComponents:
    preview_id = str(validated.response["preview_id"])
    create_id = _uuid4_text(client_order_id_factory)
    close_id = _uuid4_text(client_order_id_factory)
    if create_id == close_id:
        raise R8Slice3HandoffError("slice3_handoff_client_order_id_collision")
    create = Slice3CreateRequest(
        client_order_id=create_id,
        preview_id=preview_id,
        product_id=SLICE3_PRODUCT_ID,
        side=OrderSide.BUY,
        base_size="1",
        limit_price=str(validated.candidate["limit_price"]),
        post_only=True,
        time_in_force=TimeInForce.GTC,
    )
    preview = Slice3AcceptedPreview.from_request(
        accepted=True,
        preview_id=preview_id,
        preview_request=validated.request,
        accepted_at=validated.accepted_at,
        expires_at=validated.expires_at,
        evidence_sha256=str(validated.persisted["evidence_sha256"]),
        expiry_source=validated.expiry_source,
        expiry_evidence_sha256=validated.expiry_evidence_sha256,
        candidate_contract_size="10",
        candidate_limit_price=str(validated.candidate["limit_price"]),
        candidate_reference_price=str(validated.candidate["reference_price"]),
        candidate_opening_reference_usdc=str(
            validated.candidate["opening_reference_notional_usdc"]
        ),
        commission_total=str(validated.response["commission_total"]),
        order_margin_total=str(validated.response["order_margin_total"]),
        available_margin_usdc=validated.available_margin,
    )
    caps = Slice3CapEvidence(
        opening_reference_usdc=str(
            validated.candidate["opening_reference_notional_usdc"]
        ),
        maximum_concurrent_exposure_usdc=str(
            validated.candidate["maximum_exposure_reference_notional_usdc"]
        ),
        conservative_close_usdc=str(
            validated.candidate["buffered_close_reference_notional_usdc"]
        ),
        branch_turnover_usdc=str(
            validated.candidate["branch_turnover_reference_notional_usdc"]
        ),
    )
    portfolio = Slice3PortfolioBinding(
        portfolio_id=validated.portfolio_id,
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
        observed_at=validated.accepted_at,
        permission_evidence_sha256=str(
            validated.ephemeral["permission_evidence_sha256"]
        ),
        portfolio_catalog_sha256=str(validated.ephemeral["portfolio_catalog_sha256"]),
    )
    return _Slice3PlanComponents(
        portfolio=portfolio,
        preview=preview,
        create=create,
        caps=caps,
        close_client_order_id=close_id,
    )


def _assemble_slice3_plan(
    validated: _ValidatedR8PlanInputs,
    components: _Slice3PlanComponents,
    *,
    execution_authority: Slice3ExecutionAuthority,
    backend_revision: str,
    openapi_revision: str,
) -> Slice3Plan:
    return Slice3Plan.build(
        policy=SLICE3_LIVE_POLICY,
        execution_authority=execution_authority,
        margin_windows=Slice3MarginWindowEvidence(
            retail_regular="MARGIN_WINDOW_TYPE_UNSPECIFIED",
            retail_intraday_margin_1="MARGIN_WINDOW_TYPE_INTRADAY",
            intraday_margin_setting=validated.intraday_margin_setting,
            intraday_margin_killswitch_enabled=False,
            intraday_margin_enrollment_killswitch_enabled=False,
        ),
        portfolio=components.portfolio,
        preview=components.preview,
        create=components.create,
        caps=components.caps,
        close_client_order_id=components.close_client_order_id,
        baseline_position_contracts="0",
        baseline_position_sha256=str(validated.ephemeral["position_evidence_sha256"]),
        backend_revision=backend_revision,
        openapi_revision=openapi_revision,
        now=validated.current,
    )


def build_slice3_plan_from_r8(
    *,
    ephemeral_evidence: Mapping[str, Any],
    persisted_terminal: Mapping[str, Any],
    authorization_sha256: str,
    adapter_evidence_sha256: str,
    now: datetime,
    backend_revision: str,
    openapi_revision: str,
    client_order_id_factory: Callable[[], UUID | str] = uuid4,
) -> Slice3Plan:
    """Build the legacy synthetic-authority plan for offline compatibility."""

    try:
        validated = _validate_r8_plan_inputs(
            ephemeral_evidence=ephemeral_evidence,
            persisted_terminal=persisted_terminal,
            now=now,
        )
        components = _build_slice3_plan_components(
            validated,
            client_order_id_factory=client_order_id_factory,
        )
        authority = _build_execution_authority(
            validated.ephemeral,
            authorization_sha256=authorization_sha256,
            adapter_evidence_sha256=adapter_evidence_sha256,
            accepted_at=validated.accepted_at,
            correlation_id=validated.correlation_id,
            idempotency_key=validated.idempotency_key,
            portfolio_id=validated.portfolio_id,
            candidate=validated.candidate,
            request=validated.request,
            response=validated.response,
            liquidation_evidence=validated.liquidation_evidence,
        )
        return _assemble_slice3_plan(
            validated,
            components,
            execution_authority=authority,
            backend_revision=backend_revision,
            openapi_revision=openapi_revision,
        )
    except R8Slice3HandoffError:
        raise
    except Exception:
        raise R8Slice3HandoffError("slice3_handoff_invalid") from None


def build_slice3_admitted_plan_from_r8(
    *,
    ephemeral_evidence: Mapping[str, Any],
    persisted_terminal: Mapping[str, Any],
    accepted_r8_binding: Slice3AcceptedR8Binding,
    account_binding: Slice3CoinbaseAccountBinding,
    authorization_sha256: str,
    now: datetime,
    backend_revision: str,
    openapi_revision: str,
    client_order_id_factory: Callable[[], UUID | str] = uuid4,
) -> tuple[Slice3Plan, Slice3AdmissionAuthorityBundle]:
    """Build the sole live-admissible plan from exact R8/session evidence."""

    try:
        validated = _validate_r8_plan_inputs(
            ephemeral_evidence=ephemeral_evidence,
            persisted_terminal=persisted_terminal,
            now=now,
        )
        if not isinstance(accepted_r8_binding, Slice3AcceptedR8Binding):
            raise R8Slice3HandoffError("slice3_handoff_r8_binding_invalid")
        expected_r8_binding = Slice3AcceptedR8Binding.from_accepted_evidence(
            artifact_file_sha256=accepted_r8_binding.artifact_file_sha256,
            evidence=validated.persisted,
        )
        if expected_r8_binding != accepted_r8_binding:
            raise R8Slice3HandoffError("slice3_handoff_r8_binding_mismatch")
        if not isinstance(account_binding, Slice3CoinbaseAccountBinding):
            raise R8Slice3HandoffError("slice3_handoff_account_binding_invalid")
        account_binding.validate()
        if not (
            account_binding.portfolio_id == validated.portfolio_id
            and account_binding.permission_evidence_sha256
            == validated.ephemeral["permission_evidence_sha256"]
            and account_binding.portfolio_catalog_sha256
            == validated.ephemeral["portfolio_catalog_sha256"]
        ):
            raise R8Slice3HandoffError("slice3_handoff_account_binding_mismatch")
        components = _build_slice3_plan_components(
            validated,
            client_order_id_factory=client_order_id_factory,
        )
        authority_bundle = build_slice3_execution_authority(
            authorization_sha256=authorization_sha256,
            accepted_r8_binding=accepted_r8_binding,
            account_binding=account_binding,
            portfolio=components.portfolio,
            create=components.create,
            preview=components.preview,
            caps=components.caps,
            correlation_id=validated.correlation_id,
            preview_idempotency_key=validated.idempotency_key,
            close_client_order_id=components.close_client_order_id,
            product_evidence_sha256=str(validated.ephemeral["product_evidence_sha256"]),
            market_evidence_sha256=str(validated.ephemeral["market_evidence_sha256"]),
            margin_collateral_evidence_sha256=str(
                validated.ephemeral["margin_collateral_evidence_sha256"]
            ),
            liquidation_evidence_sha256=_liquidation_evidence_sha256(
                validated.response,
                validated.liquidation_evidence,
            ),
            fee_funding_evidence_sha256=_fee_funding_evidence_sha256(
                validated.ephemeral,
                validated.response,
            ),
            now=validated.current,
        )
        plan = _assemble_slice3_plan(
            validated,
            components,
            execution_authority=authority_bundle.authority,
            backend_revision=backend_revision,
            openapi_revision=openapi_revision,
        )
        authority_bundle.validate_plan(plan, now=validated.current)
        return plan, authority_bundle
    except R8Slice3HandoffError:
        raise
    except Exception:
        raise R8Slice3HandoffError("slice3_handoff_admission_invalid") from None


def _file_sha256(module_name: str) -> str:
    try:
        module = importlib.import_module(module_name)
        path = Path(str(module.__file__)).resolve()
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        raise R8Slice3HandoffError("slice3_handoff_module_hash_unavailable") from None


def _action_schema_sha256() -> str:
    return _file_sha256("application.admin_api.futures_terminal_roundtrip")


def _read_schema_sha256() -> str:
    return _file_sha256("application.admin_api.futures_terminal_roundtrip_reads")


def build_slice3_activation_manifest(
    *,
    plan: Slice3Plan,
    persisted_terminal: Mapping[str, Any],
    r8_artifact_file_sha256: str,
    admission_seal: Slice3AdmissionSeal,
    authorization_text: str | bytes,
    now: datetime,
) -> Slice3ActivationManifest:
    """Bind exact code/schema/auth bytes for the already-built live plan."""

    try:
        if not isinstance(plan, Slice3Plan) or plan.policy != SLICE3_LIVE_POLICY:
            raise R8Slice3HandoffError("slice3_handoff_activation_policy_invalid")
        plan.validate_at(now)
        if isinstance(authorization_text, str):
            authorization_bytes = authorization_text.encode("utf-8")
        elif isinstance(authorization_text, bytes):
            authorization_bytes = authorization_text
        else:
            raise R8Slice3HandoffError("slice3_handoff_authorization_text_invalid")
        if hashlib.sha256(authorization_bytes).hexdigest() != (
            plan.execution_authority.authorization_sha256
        ):
            raise R8Slice3HandoffError("slice3_handoff_authorization_binding_mismatch")
        r8_binding = Slice3AcceptedR8Binding.from_accepted_evidence(
            artifact_file_sha256=r8_artifact_file_sha256,
            evidence=persisted_terminal,
        )
        if not isinstance(admission_seal, Slice3AdmissionSeal):
            raise R8Slice3HandoffError("slice3_handoff_admission_binding_invalid")
        admission_seal.chain.validate_at(now)
        operator_request_records = [
            record
            for record in admission_seal.chain.records
            if record.kind is Slice3AdmissionEvidenceKind.OPERATOR_REQUEST
        ]
        if len(operator_request_records) != 1:
            raise R8Slice3HandoffError("slice3_handoff_admission_binding_invalid")
        operator_request = operator_request_records[0].evidence()
        if not (
            admission_seal.chain.plan_sha256 == plan.plan_sha256
            and admission_seal.chain.authorization_sha256
            == plan.execution_authority.authorization_sha256
            and admission_seal.chain.expires_at == plan.risk_off_expires_at
            and admission_seal.chain_sha256 == admission_seal.chain.chain_sha256
            and operator_request.get("accepted_r8_binding_sha256")
            == canonical_sha256(r8_binding.sanitized_evidence())
            and admission_seal.mode == 0o400
            and admission_seal.owner_uid == os.geteuid()
            and admission_seal.link_count == 1
            and admission_seal.size > 0
            and admission_seal.device >= 0
            and admission_seal.inode > 0
            and admission_seal.mtime_ns > 0
        ):
            raise R8Slice3HandoffError("slice3_handoff_admission_binding_invalid")
        admission_record_sha256 = _sha256(
            admission_seal.record_sha256,
            "slice3_handoff_admission_binding_invalid",
        )
        admission_artifact_file_sha256 = _sha256(
            admission_seal.artifact_file_sha256,
            "slice3_handoff_admission_binding_invalid",
        )
        return Slice3ActivationManifest.build(
            r8_binding=r8_binding,
            slice3_plan_sha256=plan.plan_sha256,
            authorization_text=authorization_text,
            backend_revision=plan.backend_revision,
            openapi_revision=plan.openapi_revision,
            core_module_sha256=_file_sha256(
                "application.admin_api.futures_terminal_roundtrip"
            ),
            port_module_sha256=_file_sha256(
                "application.admin_api.futures_terminal_roundtrip_coinbase"
            ),
            orchestrator_module_sha256=_file_sha256(
                "application.admin_api.futures_terminal_roundtrip_orchestrator"
            ),
            admission_module_sha256=_file_sha256(
                "application.admin_api.futures_terminal_roundtrip_admission"
            ),
            admission_chain_sha256=admission_seal.chain_sha256,
            admission_record_sha256=admission_record_sha256,
            admission_artifact_file_sha256=(admission_artifact_file_sha256),
            action_journal_schema_sha256=_action_schema_sha256(),
            read_journal_schema_sha256=_read_schema_sha256(),
            terminal_evidence_schema_sha256=_file_sha256(
                "application.admin_api.futures_terminal_roundtrip_terminal"
            ),
            slice3_live_policy_sha256=canonical_sha256(
                SLICE3_LIVE_POLICY.sanitized_evidence()
            ),
            now=now,
            expires_at=plan.risk_off_expires_at,
        )
    except R8Slice3HandoffError:
        raise
    except Exception:
        raise R8Slice3HandoffError(
            "slice3_handoff_activation_manifest_invalid"
        ) from None


__all__ = [
    "R8Slice3HandoffError",
    "R8_SLICE3_HANDOFF_MAX_AGE",
    "build_slice3_activation_manifest",
    "build_slice3_admitted_plan_from_r8",
    "build_slice3_plan_from_r8",
]
