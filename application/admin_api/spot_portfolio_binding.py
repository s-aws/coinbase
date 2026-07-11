"""Fail-closed Coinbase credential binding for the approved Spot test profile."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


SPOT_PORTFOLIO_ID_ENV = "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID"
SPOT_PORTFOLIO_LABEL_ENV = "COINBASE_ADMIN_API_SPOT_PORTFOLIO_LABEL"
DEFAULT_SPOT_PORTFOLIO_LABEL = "Test"
EXPECTED_SPOT_PORTFOLIO_TYPE = "CONSUMER"


class SpotPortfolioBindingError(RuntimeError):
    """Raised when Coinbase credential scope does not match the approved profile."""


@dataclass(frozen=True, slots=True)
class SpotPortfolioBindingEvidence:
    """Authoritative credential-level Spot portfolio scope evidence."""

    ready: bool
    blocker: str | None
    expected_portfolio_id: str | None
    expected_portfolio_label: str
    expected_portfolio_type: str
    observed_portfolio_id: str | None
    observed_portfolio_label: str | None
    observed_portfolio_type: str | None
    can_view: bool | None
    can_trade: bool | None
    selection_authority: str = "cdp_api_key_permissioned_portfolio"
    request_portfolio_override_allowed: bool = False
    source: str = "coinbase_get_api_key_permissions"

    def to_dict(self) -> dict[str, Any]:
        """Return operator-safe evidence without credential material."""

        payload = asdict(self)
        payload.update(
            {
                "status": "matched" if self.ready else "blocked",
                "product_family": "SPOT",
                "portfolio_id": self.observed_portfolio_id,
                "profile_alias": self.expected_portfolio_label,
            }
        )
        return payload


def evaluate_spot_test_portfolio_binding(
    *,
    rest_client: Any,
    expected_portfolio_id: str | None,
    expected_portfolio_label: str = DEFAULT_SPOT_PORTFOLIO_LABEL,
) -> SpotPortfolioBindingEvidence:
    """Verify the Coinbase key is permissioned to the approved Test profile."""

    expected_id = _string_or_none(expected_portfolio_id)
    label = _string_or_none(expected_portfolio_label) or DEFAULT_SPOT_PORTFOLIO_LABEL
    if expected_id is None:
        return _evidence(
            blocker="spot_test_portfolio_id_missing",
            expected_portfolio_id=None,
            expected_portfolio_label=label,
        )

    permissions_getter = getattr(rest_client, "get_api_key_permissions", None)
    if not callable(permissions_getter):
        return _evidence(
            blocker="spot_test_portfolio_permissions_unavailable",
            expected_portfolio_id=expected_id,
            expected_portfolio_label=label,
        )

    try:
        permissions = _mapping(permissions_getter())
    except Exception:
        return _evidence(
            blocker="spot_test_portfolio_permissions_unavailable",
            expected_portfolio_id=expected_id,
            expected_portfolio_label=label,
        )

    observed_id = _string_or_none(permissions.get("portfolio_uuid"))
    observed_type = _string_or_none(permissions.get("portfolio_type"))
    if observed_type is not None:
        observed_type = observed_type.upper()
    can_view = _optional_bool(permissions.get("can_view"))
    can_trade = _optional_bool(permissions.get("can_trade"))

    observed_label = None
    portfolio_catalog_available = False
    portfolio_lister = getattr(rest_client, "list_portfolios", None)
    if callable(portfolio_lister):
        try:
            raw_portfolios = portfolio_lister()
            if isinstance(raw_portfolios, Mapping):
                raw_portfolios = raw_portfolios.get("portfolios") or []
            if isinstance(raw_portfolios, list):
                portfolio_catalog_available = True
                for raw_portfolio in raw_portfolios:
                    portfolio = _mapping(raw_portfolio)
                    portfolio_id = _string_or_none(
                        portfolio.get("uuid") or portfolio.get("portfolio_id")
                    )
                    if portfolio_id == observed_id:
                        observed_label = _string_or_none(portfolio.get("name"))
                        break
        except Exception:
            portfolio_catalog_available = False

    blocker = None
    if observed_id != expected_id:
        blocker = "spot_test_portfolio_mismatch"
    elif observed_type != EXPECTED_SPOT_PORTFOLIO_TYPE:
        blocker = "spot_test_portfolio_type_mismatch"
    elif not portfolio_catalog_available:
        blocker = "spot_test_portfolio_catalog_unavailable"
    elif observed_label != label:
        blocker = "spot_test_portfolio_label_mismatch"
    elif can_view is not True:
        blocker = "spot_test_portfolio_view_permission_missing"
    elif can_trade is not True:
        blocker = "spot_test_portfolio_trade_permission_missing"

    return _evidence(
        blocker=blocker,
        expected_portfolio_id=expected_id,
        expected_portfolio_label=label,
        observed_portfolio_id=observed_id,
        observed_portfolio_label=observed_label,
        observed_portfolio_type=observed_type,
        can_view=can_view,
        can_trade=can_trade,
    )


def require_spot_test_portfolio_binding(
    *,
    rest_client: Any,
    expected_portfolio_id: str | None,
    expected_portfolio_label: str = DEFAULT_SPOT_PORTFOLIO_LABEL,
) -> SpotPortfolioBindingEvidence:
    """Return matched evidence or raise before any Spot order mutation."""

    evidence = evaluate_spot_test_portfolio_binding(
        rest_client=rest_client,
        expected_portfolio_id=expected_portfolio_id,
        expected_portfolio_label=expected_portfolio_label,
    )
    if not evidence.ready:
        raise SpotPortfolioBindingError(evidence.blocker or "spot_test_portfolio_blocked")
    return evidence


def _evidence(
    *,
    blocker: str | None,
    expected_portfolio_id: str | None,
    expected_portfolio_label: str,
    observed_portfolio_id: str | None = None,
    observed_portfolio_label: str | None = None,
    observed_portfolio_type: str | None = None,
    can_view: bool | None = None,
    can_trade: bool | None = None,
) -> SpotPortfolioBindingEvidence:
    return SpotPortfolioBindingEvidence(
        ready=blocker is None,
        blocker=blocker,
        expected_portfolio_id=expected_portfolio_id,
        expected_portfolio_label=expected_portfolio_label,
        expected_portfolio_type=EXPECTED_SPOT_PORTFOLIO_TYPE,
        observed_portfolio_id=observed_portfolio_id,
        observed_portfolio_label=observed_portfolio_label,
        observed_portfolio_type=observed_portfolio_type,
        can_view=can_view,
        can_trade=can_trade,
    )


def _mapping(value: Any) -> dict[str, Any]:
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        value = converter()
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _string_or_none(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
