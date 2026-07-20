"""Value-blind public projection for local Futures operator reads.

This module is pure: it performs no Coinbase I/O, persistence, command
admission, or exchange mutation.  It converts already-owned backend evidence
into the small scalar contract allowed to cross the Admin API boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import re
from typing import Any, Mapping

from core.enums import (
    AdminFuturesEvidenceSource,
    AdminFuturesEvidenceStatus,
    AdminFuturesPositionSide,
    OrderSide,
)


FUTURES_POSITION_KEY_PATTERN = re.compile(r"^fpos_[0-9a-f]{64}$")
FUTURES_PRODUCT_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,63}$")
FUTURES_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
FUTURES_CANONICAL_DECIMAL_PATTERN = re.compile(
    r"^-?(?:0|[1-9]\d*)(?:\.\d*[1-9])?$"
)
FUTURES_MARGIN_AMOUNT_LABEL_PATTERN = re.compile(
    r"^amount:(?:0|[1-9]\d*)(?:\.\d*[1-9])?:(?:USD|USDC)$"
)
FUTURES_POSITION_PNL_LABEL_PATTERN = re.compile(
    r"^pnl:-?(?:0|[1-9]\d*)(?:\.\d*[1-9])?:(?:USD|USDC)$"
)
FUTURES_POSITION_KEY_POLICY = "opaque_backend_token"

_POSITION_KEY_DOMAIN = b"coinbase-admin-futures-position-v1\0"
_UNBOUND_RUNTIME_SCOPE = "local-runtime-single-profile"
_DECIMAL_INPUT_MAX_LENGTH = 128
_DECIMAL_MAX_DIGITS = 64
_DECIMAL_MAX_ADJUSTED_EXPONENT = 64
_MARGIN_TYPES = frozenset({"CROSS", "ISOLATED", "INTRADAY", "OVERNIGHT"})
_POSITION_SOURCES = frozenset(
    {
        AdminFuturesEvidenceSource.BACKEND_REST_CLIENT.value,
        AdminFuturesEvidenceSource.RUNTIME_ORDERBOOK.value,
        AdminFuturesEvidenceSource.RUNTIME_POSITIONS.value,
        AdminFuturesEvidenceSource.DASHBOARD_ENGINE_STATE.value,
    }
)
_EVIDENCE_NAMES = frozenset(
    {
        "collateral",
        "margin",
        "funding",
        "liquidation",
        "reduce_only_close_only",
        "position_pnl",
    }
)
_ACCOUNT_REALITY_STATUSES = frozenset(
    {"ready", "unavailable", "offline_fixture", "stale", "blocked"}
)
_ACCOUNT_REALITY_SOURCES = frozenset(
    {
        "backend_rest_client",
        "backend_rest_unavailable",
        "backend_admin_mvp",
        "backend_admin_api_local_evidence",
        "backend_admin_read_contract",
    }
)


class FuturesPublicProjectionError(ValueError):
    """Fixed, value-blind rejection at the public Futures boundary."""


def is_opaque_futures_position_key(value: Any) -> bool:
    """Return whether ``value`` is one canonical public position token."""

    return isinstance(value, str) and FUTURES_POSITION_KEY_PATTERN.fullmatch(value) is not None


def opaque_futures_position_key(
    *,
    product_id: Any,
    portfolio_identity: Any,
) -> str:
    """Hash private scope plus product identity into a stable public token."""

    safe_product_id = public_futures_product_id(product_id)
    private_scope = _private_scope_text(portfolio_identity)
    digest = hashlib.sha256(
        _POSITION_KEY_DOMAIN
        + private_scope.encode("utf-8", errors="strict")
        + b"\0"
        + safe_product_id.encode("ascii")
    ).hexdigest()
    return f"fpos_{digest}"


def public_futures_product_id(value: Any) -> str:
    """Return a bounded canonical Futures product id or fail closed."""

    if not isinstance(value, str) or value != value.strip():
        raise FuturesPublicProjectionError("futures_product_id_invalid")
    if FUTURES_PRODUCT_ID_PATTERN.fullmatch(value) is None:
        raise FuturesPublicProjectionError("futures_product_id_invalid")
    return value


def public_futures_product_scope(values: Any) -> list[str]:
    """Return a stable de-duplicated allowlist of valid Futures product ids."""

    if not isinstance(values, (list, tuple)):
        return []
    projected: list[str] = []
    for value in values[:500]:
        try:
            product_id = public_futures_product_id(value)
        except FuturesPublicProjectionError:
            continue
        if product_id not in projected:
            projected.append(product_id)
    return projected


def canonical_futures_decimal(
    value: Any,
    *,
    nonnegative: bool = False,
) -> str | None:
    """Return one finite, bounded, non-exponent decimal string."""

    if value is None or isinstance(value, bool):
        return None
    text = str(value)
    if (
        not text
        or text != text.strip()
        or len(text) > _DECIMAL_INPUT_MAX_LENGTH
    ):
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or (nonnegative and parsed < 0):
        return None
    digits = parsed.as_tuple().digits
    if len(digits) > _DECIMAL_MAX_DIGITS:
        return None
    if parsed and abs(parsed.adjusted()) > _DECIMAL_MAX_ADJUSTED_EXPONENT:
        return None
    if parsed == 0:
        return "0"
    canonical = format(parsed, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if (
        len(canonical) > _DECIMAL_INPUT_MAX_LENGTH
        or FUTURES_CANONICAL_DECIMAL_PATTERN.fullmatch(canonical) is None
    ):
        return None
    return canonical


def canonical_futures_timestamp(value: Any) -> str | None:
    """Return one UTC RFC3339 timestamp without value-bearing fallback text."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and FUTURES_RFC3339_PATTERN.fullmatch(value):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    rendered = parsed.astimezone(timezone.utc).isoformat()
    if rendered.endswith("+00:00"):
        rendered = rendered[:-6] + "Z"
    if ".000000Z" in rendered:
        rendered = rendered.replace(".000000Z", "Z")
    return rendered


def project_futures_position(
    *,
    product_id: Any,
    position: Any,
    portfolio_identity: Any = None,
    product_metadata: Any = None,
    mandatory_fee_per_contract: Any = None,
    source: Any,
) -> dict[str, Any]:
    """Project one hostile/raw position onto the public scalar allowlist."""

    if not isinstance(position, Mapping):
        raise FuturesPublicProjectionError("futures_position_invalid")
    safe_product_id = public_futures_product_id(product_id)
    claimed_product_id = position.get("product_id")
    if claimed_product_id is not None and claimed_product_id != safe_product_id:
        raise FuturesPublicProjectionError("futures_position_product_scope_mismatch")

    raw_portfolio_identity = _first_text(
        position.get("portfolio_uuid"),
        position.get("portfolio_id"),
        position.get("retail_portfolio_id"),
    )
    supplied_portfolio_identity = _first_text(portfolio_identity)
    if (
        supplied_portfolio_identity is not None
        and raw_portfolio_identity is not None
        and supplied_portfolio_identity != raw_portfolio_identity
    ):
        raise FuturesPublicProjectionError("futures_position_portfolio_scope_mismatch")
    effective_portfolio_identity = (
        supplied_portfolio_identity
        or raw_portfolio_identity
        or _UNBOUND_RUNTIME_SCOPE
    )
    canonical_key = opaque_futures_position_key(
        product_id=safe_product_id,
        portfolio_identity=effective_portfolio_identity,
    )
    existing_key = position.get("position_key")
    if (
        is_opaque_futures_position_key(existing_key)
        and supplied_portfolio_identity is None
        and raw_portfolio_identity is None
    ):
        canonical_key = str(existing_key)

    net_size = canonical_futures_decimal(position.get("net_size"))
    side = _position_side(position, net_size=net_size)
    number_of_contracts = _number_of_contracts(position, net_size=net_size)
    open_side, close_side = _open_close_sides(side)
    source_value = _source_value(source)
    margin_amount_label = _money_label(
        prefix="amount",
        value=position.get("margin_amt") or position.get("margin_amount"),
        nonnegative=True,
        unavailable="margin_amount_unavailable",
    )
    if margin_amount_label == "margin_amount_unavailable":
        existing_margin_label = position.get("margin_amount_label")
        normalized_margin_label = _existing_money_label(
            existing_margin_label,
            prefix="amount",
            nonnegative=True,
        )
        if normalized_margin_label is not None:
            margin_amount_label = normalized_margin_label
    position_pnl_label = _money_label(
        prefix="pnl",
        value=(
            position.get("unrealized_pnl")
            if position.get("unrealized_pnl") is not None
            else position.get("realized_pnl")
        ),
        nonnegative=False,
        unavailable="position_pnl_unavailable",
    )
    if position_pnl_label == "position_pnl_unavailable":
        existing_pnl_label = position.get("position_pnl_label")
        normalized_pnl_label = _existing_money_label(
            existing_pnl_label,
            prefix="pnl",
            nonnegative=False,
        )
        if normalized_pnl_label is not None:
            position_pnl_label = normalized_pnl_label
    product_metadata_label = _product_metadata_label(
        product_metadata=(
            product_metadata
            if product_metadata is not None
            else position.get("product_metadata")
        ),
        product_id=safe_product_id,
    )
    if (
        product_metadata_label == "product_metadata_unavailable"
        and position.get("product_metadata_label")
        == "product_metadata:verified_futures_product"
    ):
        product_metadata_label = "product_metadata:verified_futures_product"

    return {
        "position_key": canonical_key,
        "product_id": safe_product_id,
        "product_type": "FUTURE",
        "position_side": side,
        "number_of_contracts": number_of_contracts,
        "net_size": net_size,
        "entry_price": canonical_futures_decimal(
            position.get("entry_price"),
            nonnegative=True,
        ),
        "entry_vwap": canonical_futures_decimal(
            position.get("entry_vwap"),
            nonnegative=True,
        ),
        "current_price": canonical_futures_decimal(
            position.get("current_price"),
            nonnegative=True,
        ),
        "margin_type": _margin_type(position.get("margin_type")),
        "margin_amount_label": margin_amount_label,
        "leverage": canonical_futures_decimal(
            position.get("leverage"),
            nonnegative=True,
        ),
        "liquidation_buffer_percentage": canonical_futures_decimal(
            position.get("liquidation_buffer_percentage"),
            nonnegative=True,
        ),
        "position_pnl_label": position_pnl_label,
        "product_metadata_label": product_metadata_label,
        "open_order_side": open_side,
        "close_order_side": close_side,
        "reduce_only_order_side": close_side,
        "close_only_order_side": close_side,
        "mandatory_fee_per_contract": canonical_futures_decimal(
            mandatory_fee_per_contract,
            nonnegative=True,
        ),
        "source": source_value,
        "updated_at": canonical_futures_timestamp(position.get("updated_at")),
    }


def public_futures_evidence(
    *,
    name: Any,
    status: Any,
    source: Any,
    value: Any = None,
) -> dict[str, Any]:
    """Return fixed value-blind account evidence with no arbitrary payload."""

    normalized_name = str(name or "")
    if normalized_name not in _EVIDENCE_NAMES:
        raise FuturesPublicProjectionError("futures_evidence_name_invalid")
    normalized_status = _evidence_status(status)
    normalized_source = _evidence_source(source)
    value_label = f"{normalized_name}_{normalized_status}"
    selected_money = _selected_account_money(normalized_name, value)
    if normalized_status == AdminFuturesEvidenceStatus.OBSERVED.value and selected_money:
        value_label = f"{value_label}:{selected_money}"
    return {
        "name": normalized_name,
        "status": normalized_status,
        "source": normalized_source,
        "value_label": value_label,
    }


def public_futures_portfolio_scope(
    *,
    source: Any,
    freshness_status: Any,
) -> dict[str, Any]:
    """Return exact profile labels while withholding the concrete portfolio id."""

    allowed_sources = {
        "backend_rest_client",
        "backend_rest_unavailable",
        "backend_admin_mvp",
        "backend_admin_api_local_evidence",
        "backend_admin_read_contract",
    }
    normalized_source = str(source or "")
    if normalized_source not in allowed_sources:
        normalized_source = "backend_rest_unavailable"
    allowed_freshness = {
        "backend_rest_fresh",
        "backend_rest_blocked",
        "local_default_not_connected",
        "offline_fixture",
        "local_sanitized_evidence",
    }
    normalized_freshness = str(freshness_status or "")
    if normalized_freshness not in allowed_freshness:
        normalized_freshness = "local_default_not_connected"
    return {
        "portfolio_id": None,
        "portfolio_name": "Default",
        "portfolio_type": "DEFAULT",
        "portfolio_id_withheld": True,
        "source": normalized_source,
        "freshness_status": normalized_freshness,
    }


def public_futures_account_reality(value: Any) -> dict[str, Any]:
    """Project account reality onto fixed, identifier-free classifications."""

    evidence = value if isinstance(value, Mapping) else {}
    status = str(evidence.get("status") or "").strip()
    if status not in _ACCOUNT_REALITY_STATUSES:
        status = "unavailable"
    source = str(evidence.get("source") or "").strip()
    if source not in _ACCOUNT_REALITY_SOURCES:
        source = "backend_rest_unavailable"
    return {
        "status": status,
        "source": source,
    }


def public_futures_account_readiness(value: Any) -> dict[str, bool]:
    """Return only Futures readiness booleans, failing non-booleans closed."""

    evidence = value if isinstance(value, Mapping) else {}
    return {
        key: evidence.get(key) is True
        for key in (
            "futures_account_scope_ready",
            "futures_default_profile_bound",
            "futures_observed_position_scope_ready",
            "usable_for_futures_risk",
            "futures_margin_collateral_ready",
        )
    }


def _private_scope_text(value: Any) -> str:
    normalized = _first_text(value)
    if normalized is None or len(normalized) > 512:
        return _UNBOUND_RUNTIME_SCOPE
    return normalized


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value and value == value.strip():
            return value
    return None


def _position_side(
    position: Mapping[str, Any],
    *,
    net_size: str | None,
) -> str:
    for key in ("position_side", "side", "position_direction"):
        value = position.get(key)
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in {
                AdminFuturesPositionSide.LONG.value,
                AdminFuturesPositionSide.SHORT.value,
                AdminFuturesPositionSide.FLAT.value,
            }:
                return normalized
    if net_size is not None:
        numeric = Decimal(net_size)
        if numeric > 0:
            return AdminFuturesPositionSide.LONG.value
        if numeric < 0:
            return AdminFuturesPositionSide.SHORT.value
        return AdminFuturesPositionSide.FLAT.value
    return AdminFuturesPositionSide.UNKNOWN.value


def _number_of_contracts(
    position: Mapping[str, Any],
    *,
    net_size: str | None,
) -> str | None:
    for key in ("number_of_contracts", "contracts", "size"):
        canonical = canonical_futures_decimal(
            position.get(key),
            nonnegative=True,
        )
        if canonical is not None:
            return canonical
    if net_size is None:
        return None
    return canonical_futures_decimal(abs(Decimal(net_size)), nonnegative=True)


def _open_close_sides(side: str) -> tuple[str | None, str | None]:
    if side == AdminFuturesPositionSide.LONG.value:
        return OrderSide.BUY.value, OrderSide.SELL.value
    if side == AdminFuturesPositionSide.SHORT.value:
        return OrderSide.SELL.value, OrderSide.BUY.value
    return None, None


def _margin_type(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in _MARGIN_TYPES else "UNKNOWN"


def _money_label(
    *,
    prefix: str,
    value: Any,
    nonnegative: bool,
    unavailable: str,
) -> str:
    if not isinstance(value, Mapping):
        return unavailable
    amount = canonical_futures_decimal(
        value.get("value") if value.get("value") is not None else value.get("amount"),
        nonnegative=nonnegative,
    )
    currency = str(value.get("currency") or "").strip().upper()
    if amount is None or currency not in {"USD", "USDC"}:
        return unavailable
    return f"{prefix}:{amount}:{currency}"


def _existing_money_label(
    value: Any,
    *,
    prefix: str,
    nonnegative: bool,
) -> str | None:
    if not isinstance(value, str) or len(value) > 160:
        return None
    pattern = (
        FUTURES_MARGIN_AMOUNT_LABEL_PATTERN
        if prefix == "amount"
        else FUTURES_POSITION_PNL_LABEL_PATTERN
    )
    if pattern.fullmatch(value) is None:
        return None
    label_prefix, amount, currency = value.split(":", 2)
    if label_prefix != prefix:
        return None
    canonical_amount = canonical_futures_decimal(amount, nonnegative=nonnegative)
    if canonical_amount is None or canonical_amount != amount:
        return None
    return f"{prefix}:{canonical_amount}:{currency}"


def _product_metadata_label(*, product_metadata: Any, product_id: str) -> str:
    if not isinstance(product_metadata, Mapping):
        return "product_metadata_unavailable"
    metadata_product_id = product_metadata.get("product_id")
    if metadata_product_id is not None and metadata_product_id != product_id:
        return "product_metadata_unavailable"
    product_type = str(
        product_metadata.get("product_type")
        or product_metadata.get("type")
        or ""
    ).strip().upper()
    if product_type != "FUTURE":
        return "product_metadata_unavailable"
    return "product_metadata:verified_futures_product"


def _selected_account_money(name: str, value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    selected_keys = {
        "collateral": (
            "available_margin",
            "total_usd_balance",
            "futures_buying_power",
        ),
        "margin": ("initial_margin", "maintenance_margin"),
        "liquidation": (
            "liquidation_buffer",
            "liquidation_threshold",
            "liquidation_buffer_amount",
        ),
        "position_pnl": ("unrealized_pnl", "realized_pnl"),
    }.get(name, ())
    for key in selected_keys:
        label = _money_label(
            prefix="amount",
            value=value.get(key),
            nonnegative=(name != "position_pnl"),
            unavailable="",
        )
        if label:
            return label
    return None


def _source_value(value: Any) -> str:
    normalized = value.value if isinstance(value, AdminFuturesEvidenceSource) else str(value or "")
    return (
        normalized
        if normalized in _POSITION_SOURCES
        else AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE.value
    )


def _evidence_status(value: Any) -> str:
    normalized = value.value if isinstance(value, AdminFuturesEvidenceStatus) else str(value or "")
    normalized = {
        "ready": AdminFuturesEvidenceStatus.OBSERVED.value,
        "blocked": AdminFuturesEvidenceStatus.UNAVAILABLE.value,
    }.get(normalized, normalized)
    if normalized not in {item.value for item in AdminFuturesEvidenceStatus}:
        return AdminFuturesEvidenceStatus.UNAVAILABLE.value
    return normalized


def _evidence_source(value: Any) -> str:
    normalized = value.value if isinstance(value, AdminFuturesEvidenceSource) else str(value or "")
    if normalized not in {item.value for item in AdminFuturesEvidenceSource}:
        return AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE.value
    return normalized
