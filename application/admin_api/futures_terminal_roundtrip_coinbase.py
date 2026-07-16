"""Dormant, injected Coinbase facade for the sealed Slice 3 roundtrip.

This module constructs no credentials, SDK object, route, runner, or live
client.  It only narrows an already-injected delegate to the exact Slice 3
product and one-use Create, Cancel, and Close calls.  Raw delegate responses
are normalized in memory and are never returned or serialized.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_MAX_READ_AGE,
    SLICE3_MAX_RISK_OFF_TTL,
    SLICE3_PRODUCT_ID,
    Slice3MutationOutcome,
    Slice3MutationResult,
    Slice3MarketReference,
    Slice3OpenOrderZeroProof,
    Slice3OrderObservation,
    Slice3OrderResolutionSource,
    Slice3PositionObservation,
)
from core.enums import AdminFuturesPositionSide, OrderSide, OrderStatus


SLICE3_COINBASE_PRODUCT_ID = SLICE3_PRODUCT_ID
SLICE3_COINBASE_API_BASE_URL = "api.coinbase.com"
SLICE3_COINBASE_HTTP_TIMEOUT_SECONDS = 30
SLICE3_COINBASE_CA_BUNDLE = (
    "/usr/local/lib/python3.13/site-packages/certifi/cacert.pem"
)
_SLICE3_OPENING_SIZE = Decimal("1")
_SLICE3_CONTRACT_SIZE = Decimal("10")
_ORDER_PAGE_LIMIT = 100
_EXPECTED_MARGIN_SOURCE_READ_ATTEMPTS = {
    "get_futures_balance_summary": 1,
    "get_intraday_margin_setting": 1,
    "get_current_margin_window": 2,
    "list_futures_sweeps": 1,
}
_MUTATION_REASONS = frozenset(
    {
        "create_accepted",
        "create_explicitly_rejected",
        "create_outcome_unknown",
        "cancel_accepted",
        "cancel_explicitly_rejected",
        "cancel_outcome_unknown",
        "close_accepted",
        "close_explicitly_rejected",
        "close_outcome_unknown",
    }
)
_EXCHANGE_ORDER_STATUSES = frozenset(
    {
        OrderStatus.PENDING,
        OrderStatus.OPEN,
        OrderStatus.QUEUED,
        OrderStatus.CANCEL_QUEUED,
        OrderStatus.EDIT_QUEUED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
        OrderStatus.FAILED,
    }
)
_ACTIVE_EXCHANGE_ORDER_STATUSES = (
    OrderStatus.PENDING,
    OrderStatus.OPEN,
    OrderStatus.QUEUED,
    OrderStatus.CANCEL_QUEUED,
    OrderStatus.EDIT_QUEUED,
)
_DOCUMENTED_CONFIGURATION_SUPERSET_FIELDS = frozenset(
    {"quote_size", "rfq_disabled"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RETRY_POLICY_FIELDS = ("connect", "read", "redirect", "status", "other")


class Slice3CoinbasePortError(RuntimeError):
    """Raised before an exchange call when the sealed port scope is invalid."""


class Slice3CoinbaseReadError(RuntimeError):
    """Sanitized read failure that never carries delegate exception text."""


class _NormalizationError(ValueError):
    """Private sentinel whose fixed text is never returned to the caller."""


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _private_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        if isinstance(converted, Mapping):
            return {str(key): item for key, item in converted.items()}
    raise _NormalizationError("invalid_mapping")


def _private_identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
    ):
        raise _NormalizationError("invalid_identifier")
    return value


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise _NormalizationError("invalid_decimal")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _NormalizationError("invalid_decimal") from exc
    if not normalized.is_finite():
        raise _NormalizationError("invalid_decimal")
    return normalized


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _NormalizationError("invalid_timestamp")
    return value.astimezone(timezone.utc)


def _coinbase_utc_timestamp(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _side_text(value: object) -> str:
    if isinstance(value, OrderSide):
        return value.value
    if isinstance(value, str):
        return value
    raise _NormalizationError("invalid_side")


def _opening_configuration(limit_price: Decimal | str) -> dict[str, object]:
    return {
        "limit_limit_gtc": {
            "base_size": "1",
            "limit_price": str(limit_price),
            "post_only": True,
        }
    }


def _close_configuration(size: Decimal) -> dict[str, object]:
    return {"market_market_ioc": {"base_size": _decimal_text(size)}}


def _configuration_matches_documented_response(
    observed: object,
    expected: Mapping[str, object],
) -> bool:
    """Match one submitted branch plus Coinbase-documented response fields."""

    try:
        observed_configuration = _mapping(observed)
        expected_configuration = _mapping(expected)
        if len(expected_configuration) != 1 or (
            set(observed_configuration) != set(expected_configuration)
        ):
            return False
        branch = next(iter(expected_configuration))
        if branch not in {"limit_limit_gtc", "market_market_ioc"}:
            return False
        observed_branch = _mapping(observed_configuration[branch])
        expected_branch = _mapping(expected_configuration[branch])
        observed_fields = set(observed_branch)
        expected_fields = set(expected_branch)
        if not expected_fields.issubset(observed_fields) or not (
            observed_fields
            <= expected_fields | _DOCUMENTED_CONFIGURATION_SUPERSET_FIELDS
        ):
            return False
        for field_name, expected_value in expected_branch.items():
            observed_value = observed_branch.get(field_name)
            if type(observed_value) is not type(expected_value) or (
                observed_value != expected_value
            ):
                return False
        if "quote_size" in observed_branch:
            quote_size = observed_branch["quote_size"]
            if (
                not isinstance(quote_size, str)
                or quote_size != quote_size.strip()
                or len(quote_size) > 128
            ):
                return False
            if quote_size and _decimal(quote_size) < 0:
                return False
        if "rfq_disabled" in observed_branch and type(
            observed_branch["rfq_disabled"]
        ) is not bool:
            return False
    except Exception:
        return False
    return True


def _transport_policy_snapshot(
    delegate: object,
) -> tuple[int, int, tuple[tuple[str, int, int], ...]]:
    """Prove and fingerprint the canonical SDK's zero-retry transport."""

    sdk_client = getattr(delegate, "_client", None)
    session = getattr(sdk_client, "session", None)
    adapters = getattr(session, "adapters", None)
    if (
        sdk_client is None
        or session is None
        or getattr(sdk_client, "base_url", None)
        != SLICE3_COINBASE_API_BASE_URL
        or type(getattr(sdk_client, "timeout", None)) is not int
        or sdk_client.timeout != SLICE3_COINBASE_HTTP_TIMEOUT_SECONDS
        or getattr(sdk_client, "rate_limit_headers", None) is not False
        or not isinstance(adapters, Mapping)
        or set(adapters) != {"http://", "https://"}
        or getattr(session, "trust_env", None) is not False
        or getattr(session, "verify", None) != SLICE3_COINBASE_CA_BUNDLE
        or getattr(session, "proxies", None) != {}
        or type(getattr(session, "max_redirects", None)) is not int
        or session.max_redirects != 0
    ):
        raise _NormalizationError("invalid_transport_policy")
    fingerprints: list[tuple[str, int, int]] = []
    for prefix, adapter in sorted(adapters.items(), key=lambda item: str(item[0])):
        if not isinstance(prefix, str) or adapter is None:
            raise _NormalizationError("invalid_transport_policy")
        retry = getattr(adapter, "max_retries", None)
        total = getattr(retry, "total", None)
        if retry is None or isinstance(total, bool) or total != 0:
            raise _NormalizationError("invalid_transport_policy")
        for field_name in _RETRY_POLICY_FIELDS:
            value = getattr(retry, field_name, None)
            if value is not None and (
                isinstance(value, bool)
                and value is not False
                or not isinstance(value, bool)
                and value != 0
            ):
                raise _NormalizationError("invalid_transport_policy")
        fingerprints.append((prefix, id(adapter), id(retry)))
    return id(sdk_client), id(session), tuple(fingerprints)


def sanitized_mutation_evidence(
    result: Slice3MutationResult,
) -> dict[str, object]:
    """Return the only persistence-safe view of a port mutation result."""

    if (
        not isinstance(result, Slice3MutationResult)
        or result.reason_code not in _MUTATION_REASONS
    ):
        raise Slice3CoinbasePortError("slice3_mutation_result_invalid")
    return {
        "schema_version": "slice3-coinbase-mutation-result-v1",
        "outcome": result.outcome.value,
        "reason_code": result.reason_code,
        "exchange_order_id_present": result.exchange_order_id is not None,
        "raw_response_included": False,
        "identifier_values_included": False,
    }


@dataclass(frozen=True)
class Slice3CoinbaseAccountBinding:
    """In-memory proof that Preview and Slice 3 share one Default session."""

    portfolio_id: str = field(repr=False)
    session_binding_token: str = field(repr=False)
    permission_evidence_sha256: str
    portfolio_catalog_sha256: str
    adapter_evidence_sha256: str
    credential_source: str = "secrets_manager"
    credential_secret_id: str = "coinbase"
    credential_region: str = "us-east-1"

    @classmethod
    def build(
        cls,
        *,
        portfolio_id: str,
        session_binding_token: str,
        permission_evidence_sha256: str,
        portfolio_catalog_sha256: str,
    ) -> Slice3CoinbaseAccountBinding:
        portfolio = _private_identifier(portfolio_id)
        token = _private_identifier(session_binding_token)
        try:
            parsed = UUID(token)
        except (TypeError, ValueError, AttributeError):
            raise Slice3CoinbasePortError(
                "slice3_coinbase_account_binding_invalid"
            ) from None
        if parsed.version != 4 or str(parsed) != token.lower():
            raise Slice3CoinbasePortError("slice3_coinbase_account_binding_invalid")
        for value in (
            permission_evidence_sha256,
            portfolio_catalog_sha256,
        ):
            if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
                raise Slice3CoinbasePortError("slice3_coinbase_account_binding_invalid")
        evidence = {
            "schema_version": "slice3-coinbase-account-adapter-v1",
            "portfolio_id_sha256": _private_sha256(portfolio),
            "session_binding_token_sha256": _private_sha256(token),
            "permission_evidence_sha256": permission_evidence_sha256,
            "portfolio_catalog_sha256": portfolio_catalog_sha256,
            "credential_binding": {
                "source": "secrets_manager",
                "secret_id": "coinbase",
                "region": "us-east-1",
            },
            "same_session_preview_and_slice3": True,
            "raw_identifier_values_included": False,
        }
        return cls(
            portfolio_id=portfolio,
            session_binding_token=token,
            permission_evidence_sha256=permission_evidence_sha256,
            portfolio_catalog_sha256=portfolio_catalog_sha256,
            adapter_evidence_sha256=_canonical_sha256(evidence),
        )

    @property
    def portfolio_id_sha256(self) -> str:
        return _private_sha256(self.portfolio_id)

    @property
    def session_binding_token_sha256(self) -> str:
        return _private_sha256(self.session_binding_token)

    @property
    def credential_binding(self) -> dict[str, str]:
        return {
            "source": self.credential_source,
            "secret_id": self.credential_secret_id,
            "region": self.credential_region,
        }

    def sanitized_evidence(self) -> dict[str, object]:
        return {
            "schema_version": "slice3-coinbase-account-binding-v1",
            "portfolio_id_sha256": self.portfolio_id_sha256,
            "session_binding_token_sha256": (self.session_binding_token_sha256),
            "permission_evidence_sha256": self.permission_evidence_sha256,
            "portfolio_catalog_sha256": self.portfolio_catalog_sha256,
            "credential_binding": self.credential_binding,
            "adapter_evidence_sha256": self.adapter_evidence_sha256,
            "same_session_preview_and_slice3": True,
            "raw_identifier_values_included": False,
        }

    def validate(self) -> None:
        rebuilt = Slice3CoinbaseAccountBinding.build(
            portfolio_id=self.portfolio_id,
            session_binding_token=self.session_binding_token,
            permission_evidence_sha256=self.permission_evidence_sha256,
            portfolio_catalog_sha256=self.portfolio_catalog_sha256,
        )
        if self != rebuilt:
            raise Slice3CoinbasePortError("slice3_coinbase_account_binding_invalid")


@dataclass(frozen=True)
class Slice3ExactOrderEvidence:
    """Strict order/fee binding with identifiers retained only in memory."""

    observation: Slice3OrderObservation = field(repr=False)
    side: OrderSide
    filled_value: str
    total_fees: str
    number_of_fills: int
    order_configuration_sha256: str
    side_exact: bool = True
    configuration_exact: bool = True
    raw_response_included: bool = False
    identifier_values_included: bool = False

    def sanitized_evidence(self) -> dict[str, object]:
        observation = self.observation
        return {
            "schema_version": "slice3-exact-order-evidence-v1",
            "authoritative": observation.authoritative,
            "pagination_complete": observation.pagination_complete,
            "product_id": observation.product_id,
            "client_order_id_sha256": _private_sha256(observation.client_order_id),
            "exchange_order_id_sha256": (
                None
                if observation.exchange_order_id is None
                else _private_sha256(observation.exchange_order_id)
            ),
            "side": self.side.value,
            "status": observation.status.value,
            "filled_contracts": _decimal_text(observation.filled),
            "remaining_contracts": _decimal_text(observation.remaining),
            "active_order_count": observation.active_order_count,
            "observed_at": observation.observed_at.astimezone(timezone.utc).isoformat(),
            "resolution_source": observation.resolution_source.value,
            "exact_client_order_match_count": (
                observation.exact_client_order_match_count
            ),
            "filled_value": self.filled_value,
            "total_fees": self.total_fees,
            "number_of_fills": self.number_of_fills,
            "order_configuration_sha256": (self.order_configuration_sha256),
            "side_exact": self.side_exact,
            "configuration_exact": self.configuration_exact,
            "raw_response_included": self.raw_response_included,
            "identifier_values_included": self.identifier_values_included,
        }


@dataclass(frozen=True)
class Slice3MarginSummary:
    """Fixed allowlist of US CFM margin values needed by Slice 3."""

    status: str
    account_family: str
    available_margin_usdc: str
    total_usd_balance_usdc: str
    initial_margin_usdc: str
    liquidation_threshold_usdc: str
    retail_regular_margin_window: str
    retail_intraday_margin_window: str
    observed_at: datetime
    snapshot_sha256: str
    intraday_margin_setting: str = "INTRADAY_MARGIN_SETTING_STANDARD"
    intraday_margin_killswitch_enabled: bool = False
    intraday_margin_enrollment_killswitch_enabled: bool = False
    raw_response_included: bool = False
    identifier_values_included: bool = False

    def sanitized_evidence(self) -> dict[str, object]:
        return {
            "schema_version": "slice3-margin-summary-v1",
            "status": self.status,
            "account_family": self.account_family,
            "available_margin_usdc": self.available_margin_usdc,
            "total_usd_balance_usdc": self.total_usd_balance_usdc,
            "initial_margin_usdc": self.initial_margin_usdc,
            "liquidation_threshold_usdc": self.liquidation_threshold_usdc,
            "retail_regular_margin_window": (self.retail_regular_margin_window),
            "retail_intraday_margin_window": (self.retail_intraday_margin_window),
            "intraday_margin_setting": self.intraday_margin_setting,
            "intraday_margin_killswitch_enabled": (
                self.intraday_margin_killswitch_enabled
            ),
            "intraday_margin_enrollment_killswitch_enabled": (
                self.intraday_margin_enrollment_killswitch_enabled
            ),
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "snapshot_sha256": self.snapshot_sha256,
            "raw_response_included": self.raw_response_included,
            "identifier_values_included": self.identifier_values_included,
        }


class StrictSlice3CoinbasePort:
    """At-most-once exact-scope facade over an injected Coinbase delegate."""

    def __init__(
        self,
        delegate: object,
        *,
        create_client_order_id: str,
        close_client_order_id: str,
        preview_id: str,
        limit_price: Decimal | str,
        contract_size: Decimal | str,
        order_lookup_start_at: datetime,
        order_lookup_end_at: datetime,
        account_binding: Slice3CoinbaseAccountBinding,
        expected_portfolio_id_sha256: str,
        expected_permission_evidence_sha256: str,
        expected_portfolio_catalog_sha256: str,
        expected_adapter_evidence_sha256: str,
    ) -> None:
        try:
            create_id = _private_identifier(create_client_order_id)
            close_id = _private_identifier(close_client_order_id)
            preview = _private_identifier(preview_id)
            limit_text = str(limit_price)
            limit = _decimal(limit_price)
            contract = _decimal(contract_size)
            if (
                delegate is None
                or create_id == close_id
                or not limit_text
                or limit_text != limit_text.strip()
                or limit <= 0
                or contract != _SLICE3_CONTRACT_SIZE
                or not isinstance(account_binding, Slice3CoinbaseAccountBinding)
            ):
                raise _NormalizationError("invalid_binding")
            account_binding.validate()
            if not (
                account_binding.portfolio_id_sha256 == expected_portfolio_id_sha256
                and account_binding.permission_evidence_sha256
                == expected_permission_evidence_sha256
                and account_binding.portfolio_catalog_sha256
                == expected_portfolio_catalog_sha256
                and account_binding.adapter_evidence_sha256
                == expected_adapter_evidence_sha256
            ):
                raise _NormalizationError("invalid_account_binding")
        except Exception:
            raise Slice3CoinbasePortError(
                "slice3_coinbase_account_binding_invalid"
            ) from None
        try:
            lookup_start = _aware_utc(order_lookup_start_at)
            lookup_end = _aware_utc(order_lookup_end_at)
            if (
                lookup_end <= lookup_start
                or lookup_end - lookup_start > SLICE3_MAX_RISK_OFF_TTL
            ):
                raise _NormalizationError("invalid_order_lookup_window")
        except Exception:
            raise Slice3CoinbasePortError(
                "slice3_coinbase_order_lookup_window_invalid"
            ) from None
        try:
            transport_policy_snapshot = _transport_policy_snapshot(delegate)
        except Exception:
            raise Slice3CoinbasePortError(
                "slice3_coinbase_transport_policy_invalid"
            ) from None
        self._delegate = delegate
        self._delegate_identity = id(delegate)
        self._account_binding = account_binding
        self._expected_portfolio_id_sha256 = expected_portfolio_id_sha256
        self._expected_permission_evidence_sha256 = expected_permission_evidence_sha256
        self._expected_portfolio_catalog_sha256 = expected_portfolio_catalog_sha256
        self._expected_adapter_evidence_sha256 = expected_adapter_evidence_sha256
        self._transport_policy_snapshot = transport_policy_snapshot
        self._create_client_order_id = create_id
        self._close_client_order_id = close_id
        self._preview_id = preview
        self._limit_price_text = limit_text
        self._contract_size = contract
        self._order_lookup_start_at = lookup_start
        self._order_lookup_end_at = lookup_end
        self._attempts = {"create": 0, "cancel": 0, "close": 0}
        self._close_size: Decimal | None = None

    def __repr__(self) -> str:
        return "<StrictSlice3CoinbasePort dormant injected>"

    def _consume(self, action: str) -> None:
        if self._attempts[action] != 0:
            raise Slice3CoinbasePortError(f"slice3_{action}_attempt_consumed")
        self._attempts[action] = 1

    def _assert_account_binding(self) -> None:
        try:
            self._account_binding.validate()
            valid = bool(
                id(self._delegate) == self._delegate_identity
                and self._account_binding.portfolio_id_sha256
                == self._expected_portfolio_id_sha256
                and self._account_binding.permission_evidence_sha256
                == self._expected_permission_evidence_sha256
                and self._account_binding.portfolio_catalog_sha256
                == self._expected_portfolio_catalog_sha256
                and self._account_binding.adapter_evidence_sha256
                == self._expected_adapter_evidence_sha256
            )
        except Exception:
            valid = False
        if not valid:
            raise Slice3CoinbasePortError("slice3_coinbase_account_binding_invalid")
        try:
            current_transport = _transport_policy_snapshot(self._delegate)
        except Exception:
            raise Slice3CoinbasePortError(
                "slice3_coinbase_transport_policy_invalid"
            ) from None
        if current_transport != self._transport_policy_snapshot:
            raise Slice3CoinbasePortError("slice3_coinbase_transport_policy_invalid")

    def _call_delegate(self, method: str, **kwargs: object) -> object:
        self._assert_account_binding()
        operation = getattr(self._delegate, method, None)
        if not callable(operation):
            raise Slice3CoinbasePortError("slice3_coinbase_account_binding_invalid")
        return operation(**kwargs)

    @staticmethod
    def _unknown(action: str) -> Slice3MutationResult:
        return Slice3MutationResult(
            outcome=Slice3MutationOutcome.UNKNOWN,
            reason_code=f"{action}_outcome_unknown",
        )

    @staticmethod
    def _rejected(action: str) -> Slice3MutationResult:
        return Slice3MutationResult(
            outcome=Slice3MutationOutcome.REJECTED,
            reason_code=f"{action}_explicitly_rejected",
        )

    @staticmethod
    def _accepted(
        action: str,
        exchange_order_id: str,
    ) -> Slice3MutationResult:
        return Slice3MutationResult(
            outcome=Slice3MutationOutcome.ACCEPTED,
            reason_code=f"{action}_accepted",
            exchange_order_id=exchange_order_id,
        )

    def create_order(
        self,
        *,
        client_order_id: str,
        product_id: str,
        side: str,
        order_configuration: Mapping[str, object],
        preview_id: str,
    ) -> Slice3MutationResult:
        """Submit one exact Preview-bound BUY limit GTC Create."""

        self._assert_account_binding()
        expected_configuration = _opening_configuration(self._limit_price_text)
        if (
            client_order_id != self._create_client_order_id
            or product_id != SLICE3_COINBASE_PRODUCT_ID
            or side != OrderSide.BUY.value
            or not isinstance(order_configuration, Mapping)
            or dict(order_configuration) != expected_configuration
            or preview_id != self._preview_id
        ):
            raise Slice3CoinbasePortError("slice3_create_scope_invalid")
        self._consume("create")
        request = {
            "client_order_id": self._create_client_order_id,
            "product_id": SLICE3_COINBASE_PRODUCT_ID,
            "side": OrderSide.BUY.value,
            "order_configuration": expected_configuration,
            "preview_id": self._preview_id,
        }
        try:
            response = self._call_delegate("create_order", **request)
            return self._normalize_create_response(response)
        except Exception:
            return self._unknown("create")

    def _normalize_create_response(self, response: object) -> Slice3MutationResult:
        data = _mapping(response)
        if data.get("success") is False:
            return self._rejected("create")
        if data.get("success") is not True:
            return self._unknown("create")
        accepted = _mapping(data.get("success_response"))
        exchange_id = _private_identifier(accepted.get("order_id"))
        if (
            accepted.get("client_order_id") != self._create_client_order_id
            or accepted.get("product_id") != SLICE3_COINBASE_PRODUCT_ID
            or accepted.get("side") != OrderSide.BUY.value
            or exchange_id == self._create_client_order_id
        ):
            return self._unknown("create")
        return self._accepted("create", exchange_id)

    def cancel_order(
        self,
        *,
        client_order_id: str,
        verified_exchange_order_id: str,
    ) -> Slice3MutationResult:
        """Submit one canonical-wrapper Cancel with both exact identities."""

        self._assert_account_binding()
        try:
            exchange_id = _private_identifier(verified_exchange_order_id)
        except Exception:
            raise Slice3CoinbasePortError("slice3_cancel_scope_invalid") from None
        if (
            client_order_id != self._create_client_order_id
            or exchange_id == self._create_client_order_id
        ):
            raise Slice3CoinbasePortError("slice3_cancel_scope_invalid")
        self._consume("cancel")
        try:
            response = self._call_delegate(
                "cancel_order",
                client_order_id=self._create_client_order_id,
                verified_exchange_order_id=exchange_id,
                return_evidence=True,
            )
            return self._normalize_cancel_response(response, exchange_id)
        except Exception:
            return self._unknown("cancel")

    def _normalize_cancel_response(
        self,
        response: object,
        exchange_order_id: str,
    ) -> Slice3MutationResult:
        data = _mapping(response)
        identity_exact = (
            data.get("identity_match") is True
            and type(data.get("result_count")) is int
            and data.get("result_count") == 1
            and data.get("operator_identity_key") == "client_order_id"
            and data.get("operator_identity_value") == self._create_client_order_id
            and data.get("exchange_order_id_evidence_only") is True
            and data.get("exchange_order_id") == exchange_order_id
            and data.get("submitted_identity_key") == "exchange_order_id"
        )
        if not identity_exact:
            return self._unknown("cancel")
        if (
            data.get("outcome") == "succeeded"
            and data.get("succeeded") is True
            and data.get("explicit_rejection") is False
        ):
            return self._accepted("cancel", exchange_order_id)
        if (
            data.get("outcome") == "explicitly_rejected"
            and data.get("succeeded") is False
            and data.get("explicit_rejection") is True
        ):
            return self._rejected("cancel")
        return self._unknown("cancel")

    def close_position(
        self,
        *,
        client_order_id: str,
        product_id: str,
        size: Decimal | str,
    ) -> Slice3MutationResult:
        """Submit one exact-product Close; Reduce is deliberately absent."""

        self._assert_account_binding()
        try:
            close_size = _decimal(size)
        except Exception:
            raise Slice3CoinbasePortError("slice3_close_scope_invalid") from None
        if (
            client_order_id != self._close_client_order_id
            or product_id != SLICE3_COINBASE_PRODUCT_ID
            or close_size <= 0
            or close_size > _SLICE3_OPENING_SIZE
        ):
            raise Slice3CoinbasePortError("slice3_close_scope_invalid")
        self._consume("close")
        self._close_size = close_size
        try:
            response = self._call_delegate(
                "close_position",
                client_order_id=self._close_client_order_id,
                product_id=SLICE3_COINBASE_PRODUCT_ID,
                size=_decimal_text(close_size),
            )
            return self._normalize_close_response(response)
        except Exception:
            return self._unknown("close")

    def _normalize_close_response(self, response: object) -> Slice3MutationResult:
        data = _mapping(response)
        if data.get("success") is False:
            return self._rejected("close")
        if data.get("success") is not True:
            return self._unknown("close")
        accepted = _mapping(data.get("success_response"))
        exchange_id = _private_identifier(accepted.get("order_id"))
        if (
            accepted.get("client_order_id") != self._close_client_order_id
            or accepted.get("product_id") != SLICE3_COINBASE_PRODUCT_ID
            or accepted.get("side") != OrderSide.SELL.value
            or exchange_id == self._close_client_order_id
        ):
            return self._unknown("close")
        return self._accepted("close", exchange_id)

    def read_exact_order(
        self,
        *,
        client_order_id: str,
        exchange_order_id: str,
        observed_at: datetime,
        expected_close_size: Decimal | str | None = None,
    ) -> Slice3ExactOrderEvidence:
        """Read one exact order once with no pagination or ambiguous match."""

        self._assert_account_binding()
        try:
            observed = _aware_utc(observed_at)
            exchange_id = _private_identifier(exchange_order_id)
            if client_order_id == self._create_client_order_id:
                if expected_close_size is not None:
                    raise _NormalizationError("invalid_order_scope")
                expected_side = OrderSide.BUY
                expected_configuration = _opening_configuration(self._limit_price_text)
                expected_size = _SLICE3_OPENING_SIZE
            elif client_order_id == self._close_client_order_id:
                durable_close_size = (
                    None
                    if expected_close_size is None
                    else _decimal(expected_close_size)
                )
                close_size = self._close_size or durable_close_size
                if (
                    close_size is None
                    or close_size <= 0
                    or close_size > _SLICE3_OPENING_SIZE
                    or (
                        self._close_size is not None
                        and durable_close_size is not None
                        and durable_close_size != self._close_size
                    )
                ):
                    raise _NormalizationError("invalid_order_scope")
                expected_side = OrderSide.SELL
                expected_configuration = _close_configuration(close_size)
                expected_size = close_size
            else:
                raise _NormalizationError("invalid_order_scope")
            if exchange_id == client_order_id:
                raise _NormalizationError("invalid_order_identity")
            response = self._call_delegate(
                "list_orders",
                order_ids=[exchange_id],
                product_ids=[SLICE3_COINBASE_PRODUCT_ID],
                limit=_ORDER_PAGE_LIMIT,
                product_type="FUTURE",
            )
            data = _mapping(response)
            if data.get("has_next") is not False or data.get("cursor") not in {
                None,
                "",
            }:
                raise _NormalizationError("incomplete_order_page")
            rows = data.get("orders")
            if not isinstance(rows, list) or len(rows) != 1:
                raise _NormalizationError("ambiguous_order_page")
            row = _mapping(rows[0])
            evidence = self._normalize_order_row(
                row,
                client_order_id=client_order_id,
                exchange_order_id=exchange_id,
                expected_side=expected_side,
                expected_configuration=expected_configuration,
                expected_size=expected_size,
                observed_at=observed,
                resolution_source=(
                    Slice3OrderResolutionSource.AUTHORITATIVE_ORDER_READ
                ),
            )
        except Exception:
            raise Slice3CoinbaseReadError("slice3_order_read_unavailable") from None
        return evidence

    def resolve_exact_order_by_client_order_id(
        self,
        *,
        client_order_id: str,
        observed_at: datetime,
    ) -> Slice3ExactOrderEvidence:
        """Resolve an unknown Create from one exact-product order page."""

        self._assert_account_binding()
        return self._resolve_exact_order_by_client_order_id(
            client_order_id=client_order_id,
            observed_at=observed_at,
            expected_client_order_id=self._create_client_order_id,
            expected_side=OrderSide.BUY,
            expected_configuration=_opening_configuration(self._limit_price_text),
            expected_size=_SLICE3_OPENING_SIZE,
        )

    def resolve_exact_close_order_by_client_order_id(
        self,
        *,
        client_order_id: str,
        observed_at: datetime,
        expected_close_size: Decimal | str | None = None,
    ) -> Slice3ExactOrderEvidence:
        """Resolve an unknown Close from one exact-product order page."""

        self._assert_account_binding()
        try:
            durable_close_size = (
                None if expected_close_size is None else _decimal(expected_close_size)
            )
        except Exception:
            raise Slice3CoinbaseReadError("slice3_order_read_unavailable") from None
        close_size = self._close_size or durable_close_size
        if (
            close_size is None
            or close_size <= 0
            or close_size > _SLICE3_OPENING_SIZE
            or (
                self._close_size is not None
                and durable_close_size is not None
                and durable_close_size != self._close_size
            )
        ):
            raise Slice3CoinbaseReadError("slice3_order_read_unavailable")
        return self._resolve_exact_order_by_client_order_id(
            client_order_id=client_order_id,
            observed_at=observed_at,
            expected_client_order_id=self._close_client_order_id,
            expected_side=OrderSide.SELL,
            expected_configuration=_close_configuration(close_size),
            expected_size=close_size,
        )

    def _resolve_exact_order_by_client_order_id(
        self,
        *,
        client_order_id: str,
        observed_at: datetime,
        expected_client_order_id: str,
        expected_side: OrderSide,
        expected_configuration: Mapping[str, object],
        expected_size: Decimal,
    ) -> Slice3ExactOrderEvidence:
        """Resolve one sealed client identity from one complete page."""

        try:
            observed = _aware_utc(observed_at)
            if (
                client_order_id != expected_client_order_id
                or observed < self._order_lookup_start_at
                or observed >= self._order_lookup_end_at
            ):
                raise _NormalizationError("invalid_order_scope")
            data = _mapping(
                self._call_delegate(
                    "list_orders",
                    product_ids=[SLICE3_COINBASE_PRODUCT_ID],
                    limit=_ORDER_PAGE_LIMIT,
                    start_date=_coinbase_utc_timestamp(
                        self._order_lookup_start_at
                    ),
                    end_date=_coinbase_utc_timestamp(self._order_lookup_end_at),
                    product_type="FUTURE",
                )
            )
            if data.get("has_next") is not False or data.get("cursor") not in {
                None,
                "",
            }:
                raise _NormalizationError("incomplete_order_page")
            raw_rows = data.get("orders")
            if not isinstance(raw_rows, list):
                raise _NormalizationError("invalid_order_page")
            rows = [_mapping(row) for row in raw_rows]
            for row in rows:
                if row.get("product_id") != SLICE3_COINBASE_PRODUCT_ID:
                    raise _NormalizationError("order_product_scope_invalid")
                try:
                    status = OrderStatus(str(row.get("status")))
                except ValueError as exc:
                    raise _NormalizationError("order_status_scope_invalid") from exc
                if status not in _EXCHANGE_ORDER_STATUSES:
                    raise _NormalizationError("order_status_scope_invalid")
            matches = [
                row
                for row in rows
                if row.get("client_order_id") == expected_client_order_id
            ]
            if len(matches) != 1:
                raise _NormalizationError("order_client_match_invalid")
            row = matches[0]
            exchange_id = _private_identifier(row.get("order_id"))
            if exchange_id == expected_client_order_id:
                raise _NormalizationError("invalid_order_identity")
            evidence = self._normalize_order_row(
                row,
                client_order_id=expected_client_order_id,
                exchange_order_id=exchange_id,
                expected_side=expected_side,
                expected_configuration=expected_configuration,
                expected_size=expected_size,
                observed_at=observed,
                resolution_source=(
                    Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
                ),
            )
        except Exception:
            raise Slice3CoinbaseReadError("slice3_order_read_unavailable") from None
        return evidence

    def _normalize_order_row(
        self,
        row: Mapping[str, Any],
        *,
        client_order_id: str,
        exchange_order_id: str,
        expected_side: OrderSide,
        expected_configuration: Mapping[str, object],
        expected_size: Decimal,
        observed_at: datetime,
        resolution_source: Slice3OrderResolutionSource,
    ) -> Slice3ExactOrderEvidence:
        if (
            row.get("client_order_id") != client_order_id
            or row.get("order_id") != exchange_order_id
            or row.get("product_id") != SLICE3_COINBASE_PRODUCT_ID
            or _side_text(row.get("side")) != expected_side.value
            or not _configuration_matches_documented_response(
                row.get("order_configuration"),
                expected_configuration,
            )
        ):
            raise _NormalizationError("order_binding_invalid")
        try:
            status = OrderStatus(str(row.get("status")))
        except ValueError as exc:
            raise _NormalizationError("order_status_invalid") from exc
        if status not in _EXCHANGE_ORDER_STATUSES:
            raise _NormalizationError("order_status_invalid")
        filled = _decimal(row.get("filled_size"))
        filled_value = _decimal(row.get("filled_value"))
        total_fees = _decimal(row.get("total_fees"))
        raw_fill_count = row.get("number_of_fills")
        if isinstance(raw_fill_count, bool):
            raise _NormalizationError("order_fill_count_invalid")
        try:
            number_of_fills = int(str(raw_fill_count))
        except (TypeError, ValueError) as exc:
            raise _NormalizationError("order_fill_count_invalid") from exc
        if str(number_of_fills) != str(raw_fill_count) or number_of_fills < 0:
            raise _NormalizationError("order_fill_count_invalid")
        if (
            filled < 0
            or filled > expected_size
            or filled_value < 0
            or total_fees < 0
            or (filled == 0 and (filled_value != 0 or number_of_fills != 0))
            or (filled > 0 and (filled_value <= 0 or number_of_fills <= 0))
        ):
            raise _NormalizationError("order_fill_evidence_invalid")
        remaining = expected_size - filled
        if status is OrderStatus.FILLED and remaining != 0:
            raise _NormalizationError("order_status_fill_invalid")
        if status in _ACTIVE_EXCHANGE_ORDER_STATUSES and remaining <= 0:
            raise _NormalizationError("order_status_fill_invalid")
        active_count = 1 if status in _ACTIVE_EXCHANGE_ORDER_STATUSES else 0
        observation = Slice3OrderObservation(
            authoritative=True,
            pagination_complete=True,
            product_id=SLICE3_COINBASE_PRODUCT_ID,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            status=status,
            filled_contracts=_decimal_text(filled),
            remaining_contracts=_decimal_text(remaining),
            active_order_count=active_count,
            observed_at=observed_at,
            resolution_source=resolution_source,
            exact_client_order_match_count=1,
        )
        return Slice3ExactOrderEvidence(
            observation=observation,
            side=expected_side,
            filled_value=_decimal_text(filled_value),
            total_fees=_decimal_text(total_fees),
            number_of_fills=number_of_fills,
            order_configuration_sha256=_canonical_sha256(dict(expected_configuration)),
        )

    def read_position(self, *, observed_at: datetime) -> Slice3PositionObservation:
        """Normalize one exact-product long position or authoritative flat."""

        self._assert_account_binding()
        try:
            observed = _aware_utc(observed_at)
            data = _mapping(self._call_delegate("list_futures_positions"))
            if set(data) != {"positions"}:
                raise _NormalizationError("position_response_shape_invalid")
            rows = data.get("positions")
            if not isinstance(rows, list):
                raise _NormalizationError("position_rows_invalid")
            normalized_rows = [_mapping(row) for row in rows]
            matches = [
                row
                for row in normalized_rows
                if row.get("product_id") == SLICE3_COINBASE_PRODUCT_ID
            ]
            if len(matches) > 1:
                raise _NormalizationError("position_ambiguous")
            if not matches:
                side = AdminFuturesPositionSide.FLAT
                contracts = Decimal("0")
                reference: Decimal | None = None
            else:
                row = matches[0]
                if row.get("side") != AdminFuturesPositionSide.LONG.value:
                    raise _NormalizationError("position_side_invalid")
                side = AdminFuturesPositionSide.LONG
                contracts = _decimal(row.get("number_of_contracts"))
                reference = _decimal(row.get("current_price"))
                if contracts <= 0 or contracts > _SLICE3_OPENING_SIZE or reference <= 0:
                    raise _NormalizationError("position_value_invalid")
            snapshot = {
                "authoritative": True,
                "pagination_complete": True,
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "side": side.value,
                "contracts": _decimal_text(contracts),
                "reference_price": (
                    None if reference is None else _decimal_text(reference)
                ),
                "contract_size": _decimal_text(self._contract_size),
                "observed_at": observed.isoformat(),
            }
            position = Slice3PositionObservation(
                authoritative=True,
                product_id=SLICE3_COINBASE_PRODUCT_ID,
                side=side,
                contracts=_decimal_text(contracts),
                reference_price=(
                    None if reference is None else _decimal_text(reference)
                ),
                contract_size=_decimal_text(self._contract_size),
                observed_at=observed,
                snapshot_sha256=_canonical_sha256(snapshot),
            )
        except Exception:
            raise Slice3CoinbaseReadError("slice3_position_read_unavailable") from None
        return position

    def prove_zero_open_orders(
        self,
        *,
        observed_at: datetime,
    ) -> Slice3OpenOrderZeroProof:
        """Read one finite active/transitional page; callers require count zero."""

        self._assert_account_binding()
        try:
            observed = _aware_utc(observed_at)
            data = _mapping(
                self._call_delegate(
                    "list_orders",
                    order_status=[
                        status.value for status in _ACTIVE_EXCHANGE_ORDER_STATUSES
                    ],
                    product_ids=[SLICE3_COINBASE_PRODUCT_ID],
                    limit=_ORDER_PAGE_LIMIT,
                    product_type="FUTURE",
                )
            )
            rows = data.get("orders")
            if (
                data.get("has_next") is not False
                or data.get("cursor") not in {None, ""}
                or not isinstance(rows, list)
            ):
                raise _NormalizationError("open_order_zero_not_proved")
            normalized_rows = [_mapping(row) for row in rows]
            for row in normalized_rows:
                if row.get("product_id") != SLICE3_COINBASE_PRODUCT_ID:
                    raise _NormalizationError("open_order_product_scope_invalid")
                try:
                    status = OrderStatus(str(row.get("status")))
                except ValueError as exc:
                    raise _NormalizationError("open_order_status_invalid") from exc
                if status not in _ACTIVE_EXCHANGE_ORDER_STATUSES:
                    raise _NormalizationError("open_order_status_invalid")
            active_count = len(normalized_rows)
            snapshot = {
                "authoritative": True,
                "pagination_complete": True,
                "scope": "exact_product_active_transitional_orders",
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "order_status": [
                    status.value for status in _ACTIVE_EXCHANGE_ORDER_STATUSES
                ],
                "exact_product_active_order_count": active_count,
                "observed_at": observed.isoformat(),
            }
            proof = Slice3OpenOrderZeroProof(
                authoritative=True,
                pagination_complete=True,
                scope="exact_product_active_transitional_orders",
                product_id=SLICE3_COINBASE_PRODUCT_ID,
                exact_product_active_order_count=active_count,
                observed_at=observed,
                snapshot_sha256=_canonical_sha256(snapshot),
            )
        except Exception:
            raise Slice3CoinbaseReadError(
                "slice3_open_order_proof_unavailable"
            ) from None
        return proof

    def read_market_reference(
        self,
        *,
        observed_at: datetime,
    ) -> Slice3MarketReference:
        """Read one exact-product uncrossed book and use its best ask."""

        self._assert_account_binding()
        try:
            observed = _aware_utc(observed_at)
            data = _mapping(
                self._call_delegate(
                    "get_best_bid_ask", product_ids=[SLICE3_COINBASE_PRODUCT_ID]
                )
            )
            raw_books = data.get("pricebooks")
            if not isinstance(raw_books, list) or len(raw_books) != 1:
                raise _NormalizationError("market_book_ambiguous")
            book = _mapping(raw_books[0])
            if book.get("product_id") != SLICE3_COINBASE_PRODUCT_ID:
                raise _NormalizationError("market_product_invalid")
            raw_book_time = book.get("time")
            if not isinstance(raw_book_time, str):
                raise _NormalizationError("market_time_missing")
            book_time = _aware_utc(
                datetime.fromisoformat(raw_book_time.replace("Z", "+00:00"))
            )
            market_age = observed - book_time
            if market_age.total_seconds() < 0 or market_age > SLICE3_MAX_READ_AGE:
                raise _NormalizationError("market_time_stale")
            raw_bids = book.get("bids")
            raw_asks = book.get("asks")
            if (
                not isinstance(raw_bids, list)
                or not isinstance(raw_asks, list)
                or not raw_bids
                or not raw_asks
            ):
                raise _NormalizationError("market_sides_missing")
            bid = _decimal(_mapping(raw_bids[0]).get("price"))
            ask = _decimal(_mapping(raw_asks[0]).get("price"))
            if bid <= 0 or ask <= 0 or bid >= ask:
                raise _NormalizationError("market_book_crossed")
            snapshot = {
                "authoritative": True,
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "best_bid": _decimal_text(bid),
                "best_ask": _decimal_text(ask),
                "reference_rule": "best_ask_conservative_close_reference",
                "exchange_observed_at": book_time.isoformat(),
                "observed_at": observed.isoformat(),
            }
            market = Slice3MarketReference(
                authoritative=True,
                product_id=SLICE3_COINBASE_PRODUCT_ID,
                reference_price=_decimal_text(ask),
                observed_at=observed,
                snapshot_sha256=_canonical_sha256(snapshot),
            )
        except Exception:
            raise Slice3CoinbaseReadError("slice3_market_read_unavailable") from None
        return market

    def read_margin_summary(
        self,
        *,
        observed_at: datetime,
    ) -> Slice3MarginSummary:
        """Return a strict allowlist from the injected US CFM margin reader."""

        self._assert_account_binding()
        try:
            observed = _aware_utc(observed_at)
            data = _mapping(
                self._call_delegate("get_futures_margin_collateral_snapshot")
            )
            if (
                data.get("status") != "ready"
                or data.get("account_family") != "coinbase_futures_us_cfm"
                or data.get("source") != "backend_rest_client"
                or not isinstance(data.get("source_read_attempts"), Mapping)
                or dict(data["source_read_attempts"])
                != _EXPECTED_MARGIN_SOURCE_READ_ATTEMPTS
                or any(
                    type(value) is not int
                    for value in data["source_read_attempts"].values()
                )
                or data.get("intx_applicability") != "not_applicable_us_account"
                or data.get("futures_sweeps") != []
                or data.get("errors") != []
            ):
                raise _NormalizationError("margin_status_invalid")
            balances = _mapping(data.get("balance_summary"))
            available = self._usd_value(balances, "available_margin")
            total = self._usd_value(balances, "total_usd_balance")
            initial = self._usd_value(balances, "initial_margin")
            liquidation = self._usd_value(
                balances,
                "liquidation_threshold",
            )
            windows = data.get("current_margin_windows")
            setting_container = _mapping(data.get("intraday_margin_setting"))
            setting = setting_container.get("setting")
            if (
                set(setting_container) != {"setting"}
                or setting
                not in {
                    "INTRADAY_MARGIN_SETTING_STANDARD",
                    "INTRADAY_MARGIN_SETTING_INTRADAY",
                }
            ):
                raise _NormalizationError("margin_setting_invalid")
            if not isinstance(windows, list) or len(windows) != 2:
                raise _NormalizationError("margin_windows_invalid")
            by_profile: dict[str, str] = {}
            for raw_window in windows:
                window = _mapping(raw_window)
                profile = window.get("profile")
                if (
                    profile
                    not in {
                        "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
                        "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
                    }
                    or profile in by_profile
                    or window.get("status") != "ready"
                    or window.get("is_intraday_margin_killswitch_enabled")
                    is not False
                    or window.get(
                        "is_intraday_margin_enrollment_killswitch_enabled"
                    )
                    is not False
                ):
                    raise _NormalizationError("margin_windows_invalid")
                margin_window = _mapping(window.get("margin_window"))
                margin_type = margin_window.get("margin_window_type")
                if not isinstance(margin_type, str):
                    raise _NormalizationError("margin_windows_invalid")
                by_profile[profile] = margin_type
            if by_profile != {
                "MARGIN_PROFILE_TYPE_RETAIL_REGULAR": (
                    "MARGIN_WINDOW_TYPE_UNSPECIFIED"
                ),
                "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1": (
                    "MARGIN_WINDOW_TYPE_INTRADAY"
                ),
            }:
                raise _NormalizationError("margin_windows_invalid")
            snapshot = {
                "status": "ready",
                "account_family": "coinbase_futures_us_cfm",
                "available_margin_usdc": _decimal_text(available),
                "total_usd_balance_usdc": _decimal_text(total),
                "initial_margin_usdc": _decimal_text(initial),
                "liquidation_threshold_usdc": _decimal_text(liquidation),
                "retail_regular_margin_window": ("MARGIN_WINDOW_TYPE_UNSPECIFIED"),
                "retail_intraday_margin_window": ("MARGIN_WINDOW_TYPE_INTRADAY"),
                "intraday_margin_setting": setting,
                "intraday_margin_killswitch_enabled": False,
                "intraday_margin_enrollment_killswitch_enabled": False,
                "observed_at": observed.isoformat(),
            }
            summary = Slice3MarginSummary(
                status="ready",
                account_family="coinbase_futures_us_cfm",
                available_margin_usdc=_decimal_text(available),
                total_usd_balance_usdc=_decimal_text(total),
                initial_margin_usdc=_decimal_text(initial),
                liquidation_threshold_usdc=_decimal_text(liquidation),
                retail_regular_margin_window=("MARGIN_WINDOW_TYPE_UNSPECIFIED"),
                retail_intraday_margin_window=("MARGIN_WINDOW_TYPE_INTRADAY"),
                observed_at=observed,
                snapshot_sha256=_canonical_sha256(snapshot),
                intraday_margin_setting=str(setting),
                intraday_margin_killswitch_enabled=False,
                intraday_margin_enrollment_killswitch_enabled=False,
            )
        except Exception:
            raise Slice3CoinbaseReadError("slice3_margin_read_unavailable") from None
        return summary

    @staticmethod
    def _usd_value(
        balances: Mapping[str, Any],
        field_name: str,
    ) -> Decimal:
        money = _mapping(balances.get(field_name))
        if money.get("currency") != "USD":
            raise _NormalizationError("margin_currency_invalid")
        value = _decimal(money.get("value"))
        if value < 0:
            raise _NormalizationError("margin_value_invalid")
        return value
