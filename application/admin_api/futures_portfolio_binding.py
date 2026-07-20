"""Pure Default-profile binding evidence for Futures/Perpetual reads.

The evaluator consumes already-read Coinbase evidence.  It deliberately has no
REST client dependency and cannot perform Coinbase I/O or grant command/live
execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .futures_public_projection import canonical_futures_timestamp


DEFAULT_FUTURES_PROFILE_ALIAS = "Default"
DEFAULT_FUTURES_PORTFOLIO_TYPE = "DEFAULT"

PERMISSIONS_UNAVAILABLE = "futures_default_portfolio_permissions_unavailable"
PERMISSIONED_PORTFOLIO_MISSING = (
    "futures_default_permissioned_portfolio_missing"
)
PORTFOLIO_TYPE_MISMATCH = "futures_default_portfolio_type_mismatch"
PORTFOLIO_CATALOG_UNAVAILABLE = (
    "futures_default_portfolio_catalog_unavailable"
)
PORTFOLIO_CATALOG_AMBIGUOUS = "futures_default_portfolio_catalog_ambiguous"
PORTFOLIO_LABEL_MISMATCH = "futures_default_portfolio_label_mismatch"
VIEW_PERMISSION_MISSING = "futures_default_portfolio_view_permission_missing"
OBSERVED_AT_MISSING = "futures_default_portfolio_observed_at_missing"


@dataclass(frozen=True, slots=True)
class FuturesDefaultPortfolioBindingEvidence:
    """Operator-safe evidence for one permissioned Default portfolio."""

    read_ready: bool
    blocker: str | None
    observed_at: str
    observed_portfolio_id: str | None
    observed_profile_alias: str | None
    observed_portfolio_type: str | None
    observed_catalog_portfolio_type: str | None
    can_view: bool | None
    can_trade: bool | None
    permissions_read: bool
    portfolio_catalog_read: bool
    permissions_error_present: bool
    portfolio_catalog_error_present: bool
    expected_profile_alias: str = DEFAULT_FUTURES_PROFILE_ALIAS
    expected_portfolio_type: str = DEFAULT_FUTURES_PORTFOLIO_TYPE
    selection_authority: str = "cdp_api_key_permissioned_portfolio"
    request_portfolio_override_allowed: bool = False
    source: str = "coinbase_api_key_permissions_and_portfolio_catalog"

    def to_dict(self) -> dict[str, Any]:
        """Return internal evidence, including the exact enforcement binding."""

        return {
            "status": "matched" if self.read_ready else "blocked",
            "ready": self.read_ready,
            "blocker": self.blocker,
            "read_authorized": self.read_ready,
            "expected_portfolio_label": self.expected_profile_alias,
            "expected_portfolio_type": self.expected_portfolio_type,
            "observed_portfolio_id": self.observed_portfolio_id,
            "observed_portfolio_label": self.observed_profile_alias,
            "observed_portfolio_type": self.observed_portfolio_type,
            "can_view": self.can_view,
            "can_trade": self.can_trade,
            "selection_authority": self.selection_authority,
            "request_portfolio_override_allowed": (
                self.request_portfolio_override_allowed
            ),
            "source": self.source,
            "freshness_status": (
                "backend_rest_fresh"
                if self.read_ready
                else "backend_rest_blocked"
            ),
            "observed_at": self.observed_at,
            "permissions_read_ran": self.permissions_read,
            "portfolio_catalog_read_ran": self.portfolio_catalog_read,
            "permissions_error_present": self.permissions_error_present,
            "portfolio_catalog_error_present": (
                self.portfolio_catalog_error_present
            ),
            "account_family": "coinbase_futures_us_cfm",
            "product_family": "FUTURES_PERPETUALS",
            "profile_alias": self.expected_profile_alias,
            "portfolio_id": self.observed_portfolio_id,
            "credential_trade_permission_present": self.can_trade is True,
            # Credential capability is not command or live authority.
            "command_authority_granted": False,
            "live_coinbase_execution_authorized": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }


def serialize_public_futures_portfolio_binding(
    evidence: Any,
) -> dict[str, Any]:
    """Project exact binding evidence without exposing a portfolio UUID.

    Coinbase selection and command admission retain the concrete identifier in
    the internal evidence object.  Operator read models need the binding result,
    profile label/type, permissions, freshness, and blocker classification, but
    never the credential-scoped identifier itself.
    """

    converter = getattr(evidence, "to_dict", None)
    if callable(converter):
        payload = dict(converter())
    elif isinstance(evidence, Mapping):
        payload = dict(evidence)
    else:
        payload = {}
    allowed_blockers = {
        PERMISSIONS_UNAVAILABLE,
        PERMISSIONED_PORTFOLIO_MISSING,
        PORTFOLIO_TYPE_MISMATCH,
        PORTFOLIO_CATALOG_UNAVAILABLE,
        PORTFOLIO_CATALOG_AMBIGUOUS,
        PORTFOLIO_LABEL_MISMATCH,
        VIEW_PERMISSION_MISSING,
        OBSERVED_AT_MISSING,
        "futures_default_portfolio_rest_client_unavailable",
        "futures_default_portfolio_live_read_required",
        "futures_coinbase_read_not_authorized",
        "futures_default_portfolio_evidence_unavailable",
    }
    canonical_observed_at = canonical_futures_timestamp(payload.get("observed_at"))
    observed_at = canonical_observed_at or "1970-01-01T00:00:00Z"
    permissions_read = payload.get("permissions_read_ran") is True
    portfolio_catalog_read = payload.get("portfolio_catalog_read_ran") is True
    permissions_error_present = payload.get("permissions_error_present") is True
    portfolio_catalog_error_present = (
        payload.get("portfolio_catalog_error_present") is True
    )
    can_view = (
        payload.get("can_view") if isinstance(payload.get("can_view"), bool) else None
    )
    can_trade = (
        payload.get("can_trade")
        if isinstance(payload.get("can_trade"), bool)
        else None
    )
    matched = bool(
        payload.get("status") == "matched"
        and payload.get("ready") is True
        and payload.get("read_authorized") is True
        and payload.get("observed_portfolio_label") == "Default"
        and payload.get("observed_portfolio_type") == "DEFAULT"
        and can_view is True
        and permissions_read
        and portfolio_catalog_read
        and not permissions_error_present
        and not portfolio_catalog_error_present
        and canonical_observed_at is not None
    )
    blocker = _string_or_none(payload.get("blocker"))
    if matched:
        blocker = None
    elif canonical_observed_at is None:
        blocker = OBSERVED_AT_MISSING
    elif blocker not in allowed_blockers:
        blocker = "futures_default_portfolio_evidence_unavailable"
    source = _string_or_none(payload.get("source"))
    if source not in {
        "coinbase_api_key_permissions_and_portfolio_catalog",
        "backend_rest_unavailable",
        "backend_admin_read_contract",
        "backend_admin_api_local_evidence",
    }:
        source = "backend_rest_unavailable"
    freshness_status = _string_or_none(payload.get("freshness_status"))
    allowed_freshness = {
        "backend_rest_fresh",
        "backend_rest_blocked",
        "local_default_not_connected",
        "offline_fixture",
        "local_sanitized_evidence",
    }
    if freshness_status not in allowed_freshness:
        freshness_status = "local_default_not_connected"
    if matched:
        freshness_status = "backend_rest_fresh"
    return {
        "status": "matched" if matched else "blocked",
        "ready": matched,
        "blocker": blocker,
        "expected_portfolio_label": "Default",
        "expected_portfolio_type": "DEFAULT",
        "observed_portfolio_id": None,
        "observed_portfolio_label": "Default" if matched else None,
        "observed_portfolio_type": "DEFAULT" if matched else None,
        "can_view": can_view,
        "can_trade": can_trade,
        "read_authorized": matched,
        "selection_authority": "cdp_api_key_permissioned_portfolio",
        "request_portfolio_override_allowed": False,
        "source": source,
        "freshness_status": freshness_status,
        "observed_at": observed_at,
        "permissions_read_ran": permissions_read,
        "portfolio_catalog_read_ran": portfolio_catalog_read,
        "permissions_error_present": permissions_error_present,
        "portfolio_catalog_error_present": portfolio_catalog_error_present,
        "account_family": "coinbase_futures_us_cfm",
        "product_family": "FUTURES_PERPETUALS",
        "profile_alias": "Default",
        "portfolio_id": None,
        "portfolio_id_withheld": True,
        "credential_trade_permission_present": can_trade is True,
        "command_authority_granted": False,
        "live_coinbase_execution_authorized": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    }


def evaluate_futures_default_portfolio_binding(
    *,
    permissions: Any,
    portfolios: Any,
    observed_at: str,
    permissions_read: bool,
    portfolio_catalog_read: bool,
    permissions_error: str | None = None,
    portfolio_catalog_error: str | None = None,
) -> FuturesDefaultPortfolioBindingEvidence:
    """Evaluate preloaded Coinbase evidence without performing any I/O.

    Read readiness requires the credential-permissioned UUID to resolve to one
    and only one catalog row whose type/name are exactly ``DEFAULT``/``Default``,
    plus explicit view permission. Trade permission is raw credential evidence
    only and never implies command or live-execution authority.
    """

    permission_record = _mapping(permissions)
    permissioned_portfolio_id = _string_or_none(
        permission_record.get("portfolio_uuid")
        or permission_record.get("portfolio_id")
    )
    permissioned_portfolio_type = _string_or_none(
        permission_record.get("portfolio_type")
        or permission_record.get("type")
    )
    can_view = _strict_optional_bool(permission_record.get("can_view"))
    can_trade = _strict_optional_bool(permission_record.get("can_trade"))
    normalized_observed_at = _string_or_none(observed_at) or ""
    permission_error_present = _error_present(permissions_error)
    catalog_error_present = _error_present(portfolio_catalog_error)

    catalog_rows = _portfolio_rows(portfolios)
    matching_rows = [
        row
        for row in catalog_rows
        if _portfolio_id(row) == permissioned_portfolio_id
        and permissioned_portfolio_id is not None
    ]
    matched_row = matching_rows[0] if len(matching_rows) == 1 else {}
    observed_alias = _string_or_none(
        matched_row.get("name") or matched_row.get("portfolio_name")
    )
    catalog_portfolio_type = _string_or_none(
        matched_row.get("type") or matched_row.get("portfolio_type")
    )

    blocker: str | None = None
    if not permissions_read or permission_error_present:
        blocker = PERMISSIONS_UNAVAILABLE
    elif permissioned_portfolio_id is None:
        blocker = PERMISSIONED_PORTFOLIO_MISSING
    elif permissioned_portfolio_type != DEFAULT_FUTURES_PORTFOLIO_TYPE:
        blocker = PORTFOLIO_TYPE_MISMATCH
    elif not portfolio_catalog_read or catalog_error_present:
        blocker = PORTFOLIO_CATALOG_UNAVAILABLE
    elif not matching_rows:
        blocker = PERMISSIONED_PORTFOLIO_MISSING
    elif len(matching_rows) != 1:
        blocker = PORTFOLIO_CATALOG_AMBIGUOUS
    elif catalog_portfolio_type != DEFAULT_FUTURES_PORTFOLIO_TYPE:
        blocker = PORTFOLIO_TYPE_MISMATCH
    elif observed_alias != DEFAULT_FUTURES_PROFILE_ALIAS:
        blocker = PORTFOLIO_LABEL_MISMATCH
    elif can_view is not True:
        blocker = VIEW_PERMISSION_MISSING
    elif canonical_futures_timestamp(normalized_observed_at) is None:
        blocker = OBSERVED_AT_MISSING

    read_ready = blocker is None

    return FuturesDefaultPortfolioBindingEvidence(
        read_ready=read_ready,
        blocker=blocker,
        observed_at=normalized_observed_at,
        observed_portfolio_id=permissioned_portfolio_id,
        observed_profile_alias=observed_alias,
        observed_portfolio_type=permissioned_portfolio_type,
        observed_catalog_portfolio_type=catalog_portfolio_type,
        can_view=can_view,
        can_trade=can_trade,
        permissions_read=bool(permissions_read),
        portfolio_catalog_read=bool(portfolio_catalog_read),
        permissions_error_present=permission_error_present,
        portfolio_catalog_error_present=catalog_error_present,
    )


def _mapping(value: Any) -> dict[str, Any]:
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        try:
            value = converter()
        except Exception:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _portfolio_rows(value: Any) -> list[dict[str, Any]]:
    normalized = _mapping(value)
    if normalized:
        candidates = normalized.get("portfolios")
    else:
        candidates = value
    if not isinstance(candidates, Sequence) or isinstance(
        candidates,
        (str, bytes, bytearray),
    ):
        return []
    rows: list[dict[str, Any]] = []
    for item in candidates:
        row = _mapping(item)
        if row:
            rows.append(row)
    return rows


def _portfolio_id(record: Mapping[str, Any]) -> str | None:
    return _string_or_none(
        record.get("uuid") or record.get("portfolio_uuid") or record.get("portfolio_id")
    )


def _string_or_none(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _strict_optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _error_present(value: str | None) -> bool:
    return _string_or_none(value) is not None
