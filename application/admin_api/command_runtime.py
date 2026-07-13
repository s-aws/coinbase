"""Runtime dependency composition for Admin API command services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_UP
import os
from threading import Lock
from typing import Any, Callable
import uuid

from core.action_condition_guard import (
    SPOT_STANDING_MARKET_SOURCES,
    rest_credentials_configured,
)
from core.enums import OrderOwnershipProvenance
from core.exceptions import ControlledChildPrePlacementError
from core.runtime_controller import (
    INFLIGHT_FILL_PROCESSING,
    get_runtime_controller,
)
from logging_service import get_logger

from .command_service import AdminApiCommandDependencies, AdminApiCommandService
from .live_execution import LIVE_EXECUTION_RUNTIME_ENABLED_ENV
from .spot_portfolio_binding import (
    DEFAULT_SPOT_PORTFOLIO_LABEL,
    SPOT_PORTFOLIO_ID_ENV,
    SPOT_PORTFOLIO_LABEL_ENV,
    evaluate_spot_test_portfolio_binding,
)


ORDER_EVENT_STREAM_DISABLED_ENV = "COINBASE_ADMIN_API_ORDER_EVENT_STREAM_DISABLED"
INTENTIONAL_FILL_FEE_MAX_AGE_SECONDS = 300
INTENTIONAL_FILL_TARGET_MAXIMUM = Decimal("0.05")
INTENTIONAL_FILL_TARGET_SAFETY_MULTIPLIER = Decimal("1.25")
INTENTIONAL_FILL_TARGET_PROFIT_BUFFER = Decimal("0.001")

logger = get_logger("AdminApiCommandRuntime")

_order_event_stream_lock = Lock()
_order_event_stream_publisher: Any | None = None


@dataclass(frozen=True, slots=True)
class AdminApiRestClientBinding:
    """Bound REST client plus availability evidence."""

    client: Any | None
    available: bool


@dataclass(frozen=True, slots=True)
class AdminApiCommandRuntimeReadiness:
    """Backend command-runtime readiness for controlled-live Admin API placement."""

    live_runtime_enabled: bool
    rest_client_available: bool
    runtime_ready: bool
    missing_reason: str | None
    spot_portfolio_scope: dict[str, Any]
    source: str = "application/admin_api/command_runtime.py"


def _spot_portfolio_scope(rest_client: Any | None) -> dict[str, Any]:
    return evaluate_spot_test_portfolio_binding(
        rest_client=rest_client,
        expected_portfolio_id=os.environ.get(SPOT_PORTFOLIO_ID_ENV),
        expected_portfolio_label=(
            os.environ.get(SPOT_PORTFOLIO_LABEL_ENV, "").strip()
            or DEFAULT_SPOT_PORTFOLIO_LABEL
        ),
    ).to_dict()


def admin_api_live_runtime_enabled() -> bool:
    """Return whether backend Admin API live runtime wiring is enabled."""

    return os.environ.get(LIVE_EXECUTION_RUNTIME_ENABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def admin_api_order_event_stream_disabled() -> bool:
    """Return whether Admin API should fail before order-event publishing."""

    return os.environ.get(ORDER_EVENT_STREAM_DISABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def load_admin_api_rest_client() -> AdminApiRestClientBinding:
    """Load the canonical Coinbase REST client when Admin API live runtime is on."""

    if not admin_api_live_runtime_enabled() or not rest_credentials_configured():
        return AdminApiRestClientBinding(client=None, available=False)

    try:
        import configuration

        client = configuration.get_rest_client()
    except Exception as exc:
        logger.warning("Admin API REST client unavailable: %s", exc)
        return AdminApiRestClientBinding(client=None, available=False)

    return AdminApiRestClientBinding(client=client, available=client is not None)


def build_admin_api_command_runtime_readiness() -> AdminApiCommandRuntimeReadiness:
    """Return fail-closed command-runtime evidence for controlled-live placement."""

    live_runtime_enabled = admin_api_live_runtime_enabled()
    if not live_runtime_enabled:
        return AdminApiCommandRuntimeReadiness(
            live_runtime_enabled=False,
            rest_client_available=False,
            runtime_ready=False,
            missing_reason="live_runtime_disabled",
            spot_portfolio_scope=_spot_portfolio_scope(None),
        )
    if not rest_credentials_configured():
        return AdminApiCommandRuntimeReadiness(
            live_runtime_enabled=True,
            rest_client_available=False,
            runtime_ready=False,
            missing_reason="coinbase_rest_credentials_missing",
            spot_portfolio_scope=_spot_portfolio_scope(None),
        )

    rest_client = load_admin_api_rest_client()
    if not rest_client.available:
        return AdminApiCommandRuntimeReadiness(
            live_runtime_enabled=True,
            rest_client_available=False,
            runtime_ready=False,
            missing_reason="coinbase_rest_client_unavailable",
            spot_portfolio_scope=_spot_portfolio_scope(None),
        )
    portfolio_scope = _spot_portfolio_scope(rest_client.client)
    if portfolio_scope["status"] != "matched":
        return AdminApiCommandRuntimeReadiness(
            live_runtime_enabled=True,
            rest_client_available=True,
            runtime_ready=False,
            missing_reason=portfolio_scope.get("blocker")
            or "spot_test_portfolio_blocked",
            spot_portfolio_scope=portfolio_scope,
        )
    return AdminApiCommandRuntimeReadiness(
        live_runtime_enabled=True,
        rest_client_available=True,
        runtime_ready=True,
        missing_reason=None,
        spot_portfolio_scope=portfolio_scope,
    )


def get_admin_api_order_event_stream_publisher() -> Any | None:
    """Return the shared durable order-event publisher for Admin API placement."""

    if admin_api_order_event_stream_disabled():
        return None

    global _order_event_stream_publisher
    if _order_event_stream_publisher is not None:
        return _order_event_stream_publisher

    with _order_event_stream_lock:
        if _order_event_stream_publisher is not None:
            return _order_event_stream_publisher
        try:
            import database.order as order_db
            from business.order_event_stream import OrderEventStreamPublisher

            _order_event_stream_publisher = OrderEventStreamPublisher(order_db)
        except Exception as exc:
            logger.warning("Admin API order_event_stream publisher unavailable: %s", exc)
            _order_event_stream_publisher = None
        return _order_event_stream_publisher


def log_admin_api_command(level: str, message: str) -> None:
    """Write Admin API command-service runtime messages through canonical logging."""

    log_method = getattr(logger, str(level).strip().lower(), logger.info)
    log_method(message)


def get_admin_api_spot_market_reference(
    product_id: str,
    *,
    rest_client: Any | None = None,
) -> dict[str, Any] | None:
    """Return a fresh backend-owned ticker or Coinbase REST best bid."""

    try:
        import dashboard_server

        bridge = getattr(dashboard_server, "stealth_order_bridge", None)
        manager = getattr(bridge, "stealth_manager", None) if bridge else None
        market_cache = getattr(manager, "_market_cache", None)
        if isinstance(market_cache, dict):
            market = market_cache.get(product_id)
            if isinstance(market, dict):
                source = str(market.get("source") or "").lower()
                best_bid = market.get("best_bid") or market.get("bid")
                best_ask = market.get("best_ask") or market.get("ask")
                if source == "ticker" and best_bid is not None:
                    return {
                        "product_id": product_id,
                        "best_bid": str(best_bid),
                        "best_ask": (
                            str(best_ask) if best_ask is not None else None
                        ),
                        "source": source,
                        "observed_at": market.get("time"),
                    }
    except Exception as exc:
        logger.warning("Admin API Spot market reference unavailable: %s", exc)

    if rest_client is None:
        return None
    try:
        sdk_getter = getattr(rest_client, "get_sdk_client", None)
        sdk_client = sdk_getter() if callable(sdk_getter) else rest_client
        best_bid_ask = getattr(sdk_client, "get_best_bid_ask", None)
        if not callable(best_bid_ask):
            return None
        response = best_bid_ask(product_ids=[product_id])
        record = _runtime_object_record(response)
        pricebooks = [
            _runtime_object_record(item)
            for item in _runtime_list_value(record.get("pricebooks"))
        ]
        matching = [
            item
            for item in pricebooks
            if str(item.get("product_id") or "") == product_id
        ]
        if len(matching) != 1:
            return None
        bids = [
            _runtime_object_record(item)
            for item in _runtime_list_value(matching[0].get("bids"))
        ]
        if not bids:
            return None
        asks = [
            _runtime_object_record(item)
            for item in _runtime_list_value(matching[0].get("asks"))
        ]
        if not asks:
            return None
        best_bid = bids[0].get("price")
        best_ask = asks[0].get("price")
        observed_at = matching[0].get("time")
        if best_bid is None or best_ask is None or observed_at is None:
            return None
        return {
            "product_id": product_id,
            "best_bid": str(best_bid),
            "best_ask": str(best_ask),
            "source": "coinbase_rest_best_bid",
            "observed_at": observed_at,
        }
    except Exception as exc:
        logger.warning("Admin API Coinbase REST best bid unavailable: %s", exc)
        return None


def _runtime_object_record(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return dict(converted) if isinstance(converted, Mapping) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _runtime_list_value(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


class AdminApiOrderRootRuntimeRegistrar:
    """Persist one owned Admin Spot root before its Coinbase REST submit."""

    source = "canonical_order_engine.order_parent"

    def __init__(self, order_engine: Any) -> None:
        self.order_engine = order_engine

    def register_manual_spot_root(
        self,
        *,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str,
        retail_portfolio_id: str,
        correlation_id: str | None = None,
        audit_id: str | None = None,
        target_movement_override: str | float | None = None,
    ) -> dict[str, Any]:
        engine = self.order_engine
        db_module = getattr(engine, "db_module", None)
        insert_order_parent = getattr(db_module, "insert_order_parent", None)
        if not callable(insert_order_parent):
            raise RuntimeError("order_parent_insert_unavailable")

        order = {
            "client_order_id": client_order_id,
            "product_id": product_id,
            "order_side": side,
            "base_size": base_size,
            "limit_price": limit_price,
            "status": "PENDING",
            "retail_portfolio_id": retail_portfolio_id,
        }
        resolve_profit_target = getattr(engine, "resolve_profit_target", None)
        if not callable(resolve_profit_target):
            raise RuntimeError("order_root_profit_target_unavailable")
        if target_movement_override is None:
            target_movement = resolve_profit_target(order)
            target_movement_source = "canonical_orderbook_profit_target"
        else:
            target_movement = float(target_movement_override)
            if target_movement <= 0:
                raise RuntimeError(
                    "intentional_fill_target_movement_override_invalid"
                )
            target_movement_source = "fee_aware_intentional_fill_target"
        max_order_replacement = int(
            getattr(
                getattr(engine, "orderbook", None),
                "default_max_order_replacement",
                0,
            )
        )
        parent_row_id = insert_order_parent(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            size=float(base_size),
            price=float(limit_price),
            target_movement=float(target_movement),
            target_movement_type="P",
            max_order_replacement=max_order_replacement,
            current_order_replacement=0,
            status="PENDING",
            retail_portfolio_id=retail_portfolio_id,
            correlation_id=correlation_id,
            audit_id=audit_id,
            ownership_provenance=(
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT
            ),
        )
        if parent_row_id is None:
            raise RuntimeError("order_parent_insert_returned_no_id")

        seed_parent_cache = getattr(engine, "_seed_parent_order_cache_from_db", None)
        if not callable(seed_parent_cache) or not seed_parent_cache(client_order_id):
            raise RuntimeError("order_parent_cache_hydration_failed")
        return {
            "registered": True,
            "source": self.source,
            "parent_row_id": parent_row_id,
            "client_order_id": client_order_id,
            "retail_portfolio_id": retail_portfolio_id,
            "target_movement": str(target_movement),
            "target_movement_type": "P",
            "target_movement_source": target_movement_source,
            "max_order_replacement": max_order_replacement,
            "ownership_provenance": (
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            ),
        }

    def build_intentional_fill_target_movement(
        self,
        *,
        product_id: str,
        side: str,
        base_size: Any,
        entry_limit_price: Any,
    ) -> dict[str, Any]:
        """Return a fresh fee-safe target for one approved hidden exit child."""

        engine = self.order_engine
        fee_manager = getattr(engine, "fee_manager", None)
        profit_validator = getattr(engine, "profit_validator", None)
        orderbook = getattr(engine, "orderbook", None)
        try:
            replacement_policy = getattr(orderbook, "should_replace", None)
            filled_replacement_enabled = bool(
                isinstance(replacement_policy, Mapping)
                and replacement_policy.get("FILLED") is True
            )
        except Exception:
            filled_replacement_enabled = False
        if not filled_replacement_enabled:
            return {
                "ready": False,
                "blocker": "intentional_fill_filled_replacement_disabled",
                "filled_follow_up_replacement_enabled": False,
            }
        if fee_manager is None or profit_validator is None:
            return {
                "ready": False,
                "blocker": "intentional_fill_fee_runtime_unavailable",
            }
        freshness_getter = getattr(fee_manager, "validate_fee_freshness", None)
        fee_rate_getter = getattr(
            fee_manager,
            "get_profit_validation_fee_rate",
            None,
        )
        profitability_getter = getattr(profit_validator, "is_profitable", None)
        if not all(
            callable(item)
            for item in (
                freshness_getter,
                fee_rate_getter,
                profitability_getter,
            )
        ):
            return {
                "ready": False,
                "blocker": "intentional_fill_fee_runtime_unavailable",
            }

        freshness = dict(
            freshness_getter(
                max_age_seconds=INTENTIONAL_FILL_FEE_MAX_AGE_SECONDS
            )
            or {}
        )
        if freshness.get("is_fresh") is not True:
            return {
                "ready": False,
                "blocker": "intentional_fill_fee_data_stale",
                "fee_freshness": freshness,
            }

        try:
            fee_rate = Decimal(
                str(
                    fee_rate_getter(
                        product_id=product_id,
                        post_only=False,
                    )
                )
            )
            entry_price = Decimal(str(entry_limit_price))
            order_size = Decimal(str(base_size))
            minimum_factor = Decimal(
                str(
                    getattr(
                        fee_manager,
                        "TARGET_MOVEMENT_MIN_FACTOR",
                        "0.75",
                    )
                )
            )
        except (ArithmeticError, TypeError, ValueError):
            return {
                "ready": False,
                "blocker": "intentional_fill_fee_target_inputs_invalid",
            }
        if not all(
            value.is_finite() and value > 0
            for value in (entry_price, order_size, minimum_factor)
        ) or not fee_rate.is_finite() or fee_rate <= 0 or fee_rate >= 1:
            return {
                "ready": False,
                "blocker": "intentional_fill_fee_target_inputs_invalid",
            }

        break_even_movement = (Decimal("2") * fee_rate) / (
            Decimal("1") - fee_rate
        )
        minimum_effective_target = (
            break_even_movement
            * INTENTIONAL_FILL_TARGET_SAFETY_MULTIPLIER
            + INTENTIONAL_FILL_TARGET_PROFIT_BUFFER
        )
        root_target = (
            minimum_effective_target / minimum_factor
        ).quantize(Decimal("0.000001"), rounding=ROUND_UP)
        if root_target > INTENTIONAL_FILL_TARGET_MAXIMUM:
            return {
                "ready": False,
                "blocker": "intentional_fill_fee_safe_target_exceeds_maximum",
                "fee_rate": str(fee_rate),
                "computed_target_movement": str(root_target),
                "maximum_target_movement": str(
                    INTENTIONAL_FILL_TARGET_MAXIMUM
                ),
                "fee_freshness": freshness,
            }

        minimum_follow_up_price = entry_price * (
            Decimal("1") + root_target * minimum_factor
        )
        profitability = dict(
            profitability_getter(
                filled_price=float(entry_price),
                follow_up_price=float(minimum_follow_up_price),
                side=str(side or "").upper(),
                order_size=float(order_size),
                product_id=product_id,
                triggered_by_fill=True,
                post_only=False,
            )
            or {}
        )
        if profitability.get("is_profitable") is not True:
            return {
                "ready": False,
                "blocker": "intentional_fill_profitability_preflight_failed",
                "fee_rate": str(fee_rate),
                "computed_target_movement": str(root_target),
                "minimum_follow_up_price": str(minimum_follow_up_price),
                "fee_freshness": freshness,
                "profitability": profitability,
            }

        return {
            "ready": True,
            "blocker": None,
            "source": "runtime_fee_manager_profit_validator",
            "target_movement": str(root_target),
            "target_movement_type": "P",
            "minimum_effective_target_movement": str(
                root_target * minimum_factor
            ),
            "minimum_target_movement_factor": str(minimum_factor),
            "minimum_follow_up_price": str(minimum_follow_up_price),
            "fee_rate": str(fee_rate),
            "fee_freshness": freshness,
            "profitability_preflight_passed": True,
            "filled_follow_up_replacement_enabled": True,
            "profitability": profitability,
        }

    def mark_submission_status(
        self,
        *,
        client_order_id: str,
        status: str,
        exchange_order_id: str | None = None,
    ) -> None:
        updater = getattr(
            getattr(self.order_engine, "db_module", None),
            "update_order_parent_status",
            None,
        )
        if not callable(updater):
            raise RuntimeError("order_parent_status_update_unavailable")
        if exchange_order_id is None:
            updater(client_order_id, status)
            return
        rows_updated = updater(
            client_order_id,
            status,
            exchange_order_id=exchange_order_id,
        )
        if int(rows_updated or 0) != 1:
            raise RuntimeError("order_parent_exchange_identity_update_failed")

    def read_registered_order(self, client_order_id: str) -> dict[str, Any] | None:
        getter = getattr(
            getattr(self.order_engine, "db_module", None),
            "get_parent_order",
            None,
        )
        if not callable(getter):
            raise RuntimeError("order_parent_read_unavailable")
        row = getter(client_order_id)
        return dict(row) if isinstance(row, dict) else None

    def get_unresolved_admin_manual_root_submissions(
        self,
        retail_portfolio_id: str,
    ) -> list[dict[str, Any]]:
        """Return durable nonterminal Admin roots for restart-safe admission."""

        getter = getattr(
            getattr(self.order_engine, "db_module", None),
            "get_unresolved_admin_manual_root_submissions",
            None,
        )
        if not callable(getter):
            raise RuntimeError("unresolved_admin_root_read_unavailable")
        rows = getter(retail_portfolio_id)
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise RuntimeError("unresolved_admin_root_read_invalid")
        return [dict(row) for row in rows]


def get_admin_api_order_root_registrar() -> Any | None:
    """Return the canonical embedded engine's root registrar when available."""

    try:
        import dashboard_server

        bridge = getattr(dashboard_server, "stealth_order_bridge", None)
        order_engine = getattr(bridge, "order_engine", None) if bridge else None
        if order_engine is None:
            return None
        return AdminApiOrderRootRuntimeRegistrar(order_engine)
    except Exception as exc:
        logger.warning("Admin API order root registrar unavailable: %s", exc)
        return None


class AdminApiFillFollowUpRuntimeExecutor:
    """Backend adapter for the existing filled-order follow-up engine path."""

    source = "dashboard_server.stealth_order_bridge.order_engine.handle_filled_order"

    def __init__(self, order_engine: Any) -> None:
        self.order_engine = order_engine

    def trigger_filled_follow_up(
        self,
        *,
        order: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        handle_filled_order = getattr(self.order_engine, "handle_filled_order", None)
        if not callable(handle_filled_order):
            raise RuntimeError("order_engine_handle_filled_order_unavailable")
        controller = get_runtime_controller()
        with controller.track_inflight(INFLIGHT_FILL_PROCESSING):
            handle_filled_order(dict(order))
        client_order_id = str(order.get("client_order_id") or "")
        claim_state_after = None
        orderbook = getattr(self.order_engine, "orderbook", None)
        claim_state = getattr(orderbook, "follow_up_claim_state", None)
        if callable(claim_state) and client_order_id:
            claim_state_after = claim_state("filled", client_order_id)
        return {
            "status": "executed",
            "source": self.source,
            "client_order_id": client_order_id or None,
            "audit_correlation_id": context.get("audit_correlation_id"),
            "execution_scope": "local_stealth_follow_up",
            "exchange_submission_mode": "hidden_stealth_order_no_exchange_submit",
            "order_engine_handle_filled_order_called": True,
            "claim_acquired": claim_state_after in {"processing", "done"},
            "claim_state_after": claim_state_after,
            "coinbase_order_submit_ran": False,
            "coinbase_order_cancel_submitted": False,
            "live_coinbase_orders_ran": False,
            "live_exchange_submitted": False,
            "exchange_state_mutated": False,
        }


def get_admin_api_fill_follow_up_executor() -> Any | None:
    """Return the runtime fill-follow-up executor when the bridge is available."""

    try:
        import dashboard_server

        bridge = getattr(dashboard_server, "stealth_order_bridge", None)
        order_engine = getattr(bridge, "order_engine", None) if bridge else None
        handle_filled_order = getattr(order_engine, "handle_filled_order", None)
        if order_engine is None or not callable(handle_filled_order):
            return None
        return AdminApiFillFollowUpRuntimeExecutor(order_engine)
    except Exception as exc:
        logger.warning("Admin API fill follow-up executor unavailable: %s", exc)
        return None


class AdminApiControlledFirstChildRuntimeAdapter:
    """Route-facing adapter for one deterministic Admin first-child proof.

    This adapter does not broaden automatic stealth behavior. It delegates the
    durable preparation and the single placement to the canonical manager and
    only returns exact evidence from that same in-memory lifecycle object.
    """

    source = "dashboard_server.stealth_order_bridge.stealth_manager"

    def __init__(
        self,
        stealth_manager: Any,
        *,
        market_reference_getter: (
            Callable[[str], dict[str, Any] | None] | None
        ) = None,
    ) -> None:
        self.stealth_manager = stealth_manager
        self.market_reference_getter = (
            market_reference_getter or get_admin_api_spot_market_reference
        )

    @staticmethod
    def _decimal_text(value: Any) -> str:
        number = Decimal(str(value))
        if not number.is_finite():
            raise RuntimeError("controlled_child_numeric_evidence_invalid")
        return format(number, "f")

    @staticmethod
    def _observed_at(value: Any) -> datetime:
        if isinstance(value, datetime):
            observed = value
        elif isinstance(value, str) and value.strip():
            observed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        else:
            raise RuntimeError("controlled_child_market_timestamp_missing")
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise RuntimeError("controlled_child_market_timestamp_not_aware")
        return observed.astimezone(timezone.utc)

    def submit_controlled_first_child(
        self,
        *,
        stealth_order_id: str,
        expected_root_client_order_id: str,
        expected_portfolio_id: str,
        submitted_limit_price: str,
        max_notional_usdc: str,
        approval_snapshot_id: str,
        admission_audit_id: str,
        cap_guard_decision_id: str,
        reconciliation_plan_id: str,
        controlled_batch_id: str,
        controlled_batch_slot: int,
        controlled_plan_sha256: str | None = None,
        expected_prior_preparation_sha256: str | None = None,
    ) -> dict[str, Any]:
        manager = self.stealth_manager
        try:
            market = self.market_reference_getter("BTC-USDC")
            if not isinstance(market, Mapping):
                raise RuntimeError("controlled_child_fresh_bid_missing")
            try:
                market_bid = Decimal(str(market.get("best_bid") or "0"))
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise RuntimeError("controlled_child_fresh_bid_missing") from exc
            if not market_bid.is_finite() or market_bid <= 0:
                raise RuntimeError("controlled_child_fresh_bid_missing")
            market_observed_at = self._observed_at(market.get("observed_at"))
            market_source = str(market.get("source") or "").strip().lower()
            if market_source not in SPOT_STANDING_MARKET_SOURCES:
                raise RuntimeError("controlled_child_market_source_invalid")
        except Exception as exc:
            raise ControlledChildPrePlacementError(
                str(exc),
                stage="market_reference",
                cause_type=type(exc).__name__,
                stealth_order_id=stealth_order_id,
            ) from exc

        try:
            preparation_kwargs: dict[str, Any] = {}
            if controlled_plan_sha256 is not None:
                preparation_kwargs["controlled_plan_sha256"] = (
                    controlled_plan_sha256
                )
            authority = manager.prepare_controlled_admin_first_child_reveal(
                stealth_order_id=stealth_order_id,
                expected_root_client_order_id=expected_root_client_order_id,
                expected_portfolio_id=expected_portfolio_id,
                submitted_limit_price=float(Decimal(str(submitted_limit_price))),
                max_notional_usdc=float(Decimal(str(max_notional_usdc))),
                market_bid=self._decimal_text(market_bid),
                market_source=market_source,
                market_observed_at=market_observed_at,
                approval_snapshot_id=approval_snapshot_id,
                admission_audit_id=admission_audit_id,
                cap_guard_decision_id=cap_guard_decision_id,
                reconciliation_plan_id=reconciliation_plan_id,
                batch_id=controlled_batch_id,
                batch_slot=controlled_batch_slot,
                expected_prior_preparation_sha256=(
                    expected_prior_preparation_sha256
                ),
                **preparation_kwargs,
            )
        except Exception as exc:
            raise ControlledChildPrePlacementError(
                str(exc),
                stage="preparation",
                cause_type=type(exc).__name__,
                stealth_order_id=stealth_order_id,
            ) from exc

        try:
            prepared_price = Decimal(str(authority.prepared_limit_price))
            requested_price = Decimal(str(submitted_limit_price))
            if prepared_price != requested_price:
                raise RuntimeError(
                    "controlled_child_limit_price_not_increment_aligned"
                )
        except Exception as exc:
            raise ControlledChildPrePlacementError(
                str(exc),
                stage="price_alignment",
                cause_type=type(exc).__name__,
                stealth_order_id=stealth_order_id,
            ) from exc

        placed_client_order_id = manager.reveal_order_slice(
            stealth_order_id,
            controlled_admin_authority=authority,
        )
        state = manager._get_stealth_order(stealth_order_id)
        state = state if isinstance(state, dict) else {}
        events = list(state.get("revealed_orders") or [])
        latest_event = events[-1] if events and isinstance(events[-1], dict) else {}
        placement_succeeded = bool(
            placed_client_order_id == stealth_order_id
            and latest_event.get("placement_success") is True
            and str(latest_event.get("placed_order_id") or "") == stealth_order_id
            and str(latest_event.get("exchange_order_id") or "")
        )
        placement_attempted = bool(
            placement_succeeded
            or (
                latest_event
                and str(latest_event.get("placement_status") or "").lower()
                in {"placed", "failed"}
                and not str(latest_event.get("placement_error") or "").startswith(
                    "Pre-submission hook blocked:"
                )
            )
        )
        if not placement_succeeded:
            return {
                "placed_client_order_id": placed_client_order_id,
                "exchange_order_id": latest_event.get("exchange_order_id"),
                "product_id": str(state.get("product_id") or ""),
                "side": str(state.get("side") or "").upper(),
                "base_size": self._decimal_text(authority.total_size),
                "submitted_limit_price": str(submitted_limit_price),
                "post_only": False,
                "placement_attempted": placement_attempted,
                "placement_succeeded": False,
                "placement_error": latest_event.get("placement_error"),
                "reference_notional_usdc": self._decimal_text(
                    authority.reference_notional_usdc
                ),
                **(
                    {"controlled_plan_sha256": controlled_plan_sha256}
                    if controlled_plan_sha256 is not None
                    else {}
                ),
            }
        return {
            "placed_client_order_id": stealth_order_id,
            "exchange_order_id": str(latest_event["exchange_order_id"]),
            "product_id": str(state.get("product_id") or ""),
            "side": str(state.get("side") or "").upper(),
            "base_size": self._decimal_text(authority.total_size),
            "submitted_limit_price": str(submitted_limit_price),
            "post_only": False,
            "placement_attempted": True,
            "placement_succeeded": True,
            "reference_notional_usdc": self._decimal_text(
                authority.reference_notional_usdc
            ),
            **(
                {"controlled_plan_sha256": controlled_plan_sha256}
                if controlled_plan_sha256 is not None
                else {}
            ),
        }

    def read_controlled_first_child(
        self,
        *,
        stealth_order_id: str,
        expected_root_client_order_id: str,
        expected_portfolio_id: str,
        controlled_batch_id: str,
        controlled_batch_slot: int,
        controlled_plan_sha256: str | None = None,
    ) -> dict[str, Any]:
        from database.order import get_parent_order

        expected_child_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                (
                    "coinbase://filled-follow-up/"
                    f"{expected_root_client_order_id}/"
                    f"{expected_root_client_order_id}"
                ),
            )
        )
        if stealth_order_id != expected_child_id:
            raise RuntimeError("controlled_child_not_deterministic_first_child")
        child_row = get_parent_order(stealth_order_id)
        root_row = get_parent_order(expected_root_client_order_id)
        state = self.stealth_manager._get_stealth_order(stealth_order_id)
        if not all(isinstance(item, dict) for item in (child_row, root_row, state)):
            raise RuntimeError("controlled_child_state_missing")
        preparation = (
            (state.get("anchor_repricing_state_json") or {}).get(
                "controlled_admin_first_child_reveal_preparation"
            )
            or {}
        )
        events = list(state.get("revealed_orders") or [])
        latest_event = events[-1] if events and isinstance(events[-1], dict) else {}
        active_state = state.get("anchor_repricing_state_json") or {}
        active_client_order_id = str(
            active_state.get("active_placement_client_order_id") or ""
        )
        active_exchange_order_id = str(
            active_state.get("active_exchange_order_id") or ""
        )
        exact = bool(
            str(child_row.get("client_order_id") or "") == stealth_order_id
            and str(child_row.get("parent_order_id") or "")
            == expected_root_client_order_id
            and str(child_row.get("product_id") or "") == "BTC-USDC"
            and str(child_row.get("side") or "").upper() == "SELL"
            and str(child_row.get("ownership_provenance") or "")
            == OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
            and str(child_row.get("retail_portfolio_id") or "")
            == expected_portfolio_id
            and str(root_row.get("client_order_id") or "")
            == expected_root_client_order_id
            and root_row.get("parent_order_id") is None
            and str(root_row.get("product_id") or "") == "BTC-USDC"
            and str(root_row.get("side") or "").upper() == "BUY"
            and str(root_row.get("status") or "").upper() == "FILLED"
            and str(root_row.get("ownership_provenance") or "")
            == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            and str(root_row.get("retail_portfolio_id") or "")
            == expected_portfolio_id
            and str(child_row.get("correlation_id") or "")
            == str(root_row.get("correlation_id") or "")
            and str(child_row.get("audit_id") or "")
            == str(root_row.get("audit_id") or "")
            and str(state.get("stealth_order_id") or "") == stealth_order_id
            and str(state.get("parent_order_id") or "")
            == expected_root_client_order_id
            and str(state.get("product_id") or "") == "BTC-USDC"
            and str(state.get("side") or "").upper() == "SELL"
            and str(state.get("status") or "").upper() == "REVEALED"
            and preparation.get("batch_id") == controlled_batch_id
            and preparation.get("batch_slot") == controlled_batch_slot
            and (
                controlled_plan_sha256 is None
                or preparation.get("controlled_plan_sha256")
                == controlled_plan_sha256
            )
            and active_client_order_id == stealth_order_id
            and active_exchange_order_id
            and str(child_row.get("exchange_order_id") or "")
            == active_exchange_order_id
            and len(events) == 1
            and latest_event.get("placement_success") is True
            and str(latest_event.get("placed_order_id") or "")
            == stealth_order_id
            and str(latest_event.get("exchange_order_id") or "")
            == active_exchange_order_id
        )
        if not exact:
            raise RuntimeError("controlled_child_state_mismatch")
        return {
            "stealth_order_id": stealth_order_id,
            "root_client_order_id": expected_root_client_order_id,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "retail_portfolio_id": expected_portfolio_id,
            "status": "REVEALED",
            "active_placement_client_order_id": active_client_order_id,
            "active_exchange_order_id": active_exchange_order_id,
            "executed_size": self._decimal_text(state.get("executed_size") or 0),
            **(
                {
                    "controlled_plan_sha256": preparation.get(
                        "controlled_plan_sha256"
                    )
                }
                if controlled_plan_sha256 is not None
                else {}
            ),
        }

    def reconcile_controlled_first_child_terminal(
        self,
        *,
        stealth_order_id: str,
        authoritative_status: str,
        executed_size: str,
        exchange_order_id: str,
    ) -> dict[str, Any]:
        from core.enums import StealthOrderStatus

        if str(authoritative_status or "").upper() != "CANCELLED":
            raise RuntimeError("controlled_child_terminal_status_not_cancelled")
        state = self.stealth_manager._get_stealth_order(stealth_order_id)
        state = state if isinstance(state, dict) else {}
        active_value = state.get("anchor_repricing_state_json")
        active = active_value if isinstance(active_value, Mapping) else {}
        size = Decimal(str(executed_size))
        if not size.is_finite() or size < 0:
            raise RuntimeError("controlled_child_executed_size_invalid")
        active_placement_matches = bool(
            str(state.get("status") or "").upper() == "REVEALED"
            and str(active.get("active_placement_client_order_id") or "")
            == stealth_order_id
            and str(active.get("active_exchange_order_id") or "")
            == exchange_order_id
        )
        if not active_placement_matches:
            # The exchange-event worker can persist the exact terminal child
            # before the synchronous cancel command reaches this step.
            events = state.get("revealed_orders") or []
            events = events if isinstance(events, list) else []
            latest_event = (
                events[-1]
                if events and isinstance(events[-1], dict)
                else {}
            )
            try:
                local_executed_size = Decimal(str(state["executed_size"]))
            except (InvalidOperation, KeyError, TypeError, ValueError):
                local_executed_size = Decimal("NaN")
            clear_state_fields = {
                "active_placement_client_order_id",
                "active_exchange_order_id",
                "active_exchange_price",
            }
            already_reconciled = bool(
                stealth_order_id
                and exchange_order_id
                and str(state.get("stealth_order_id") or "")
                == stealth_order_id
                and str(state.get("status") or "").upper() == "CANCELLED"
                and local_executed_size.is_finite()
                and local_executed_size == size
                and clear_state_fields.issubset(active)
                and active.get("active_placement_client_order_id") is None
                and active.get("active_exchange_order_id") is None
                and active.get("active_exchange_price") is None
                and len(events) == 1
                and latest_event.get("placement_success") is True
                and str(latest_event.get("placed_order_id") or "")
                == stealth_order_id
                and str(latest_event.get("exchange_order_id") or "")
                == exchange_order_id
            )
            if already_reconciled:
                return {
                    "local_status": "CANCELLED",
                    "active_placement_cleared": True,
                    "exchange_order_id": exchange_order_id,
                    "already_reconciled": True,
                }
            raise RuntimeError("controlled_child_active_placement_mismatch")
        self.stealth_manager.update_execution(
            stealth_order_id,
            float(size),
            StealthOrderStatus.CANCELLED.value,
        )
        reconciled = self.stealth_manager._get_stealth_order(stealth_order_id)
        reconciled = reconciled if isinstance(reconciled, dict) else {}
        reconciled_active = reconciled.get("anchor_repricing_state_json") or {}
        cleared = bool(
            str(reconciled.get("status") or "").upper() == "CANCELLED"
            and not reconciled_active.get("active_placement_client_order_id")
            and not reconciled_active.get("active_exchange_order_id")
            and reconciled_active.get("active_exchange_price") is None
        )
        if not cleared:
            raise RuntimeError("controlled_child_local_reconciliation_unproven")
        return {
            "local_status": "CANCELLED",
            "active_placement_cleared": True,
            "exchange_order_id": exchange_order_id,
        }


def get_admin_api_controlled_first_child_runtime(
    *,
    market_reference_getter: Callable[[str], dict[str, Any] | None] | None = None,
) -> Any | None:
    """Return the canonical embedded manager adapter when it is available."""

    try:
        import dashboard_server

        bridge = getattr(dashboard_server, "stealth_order_bridge", None)
        manager = getattr(bridge, "stealth_manager", None) if bridge else None
        if manager is None:
            return None
        return AdminApiControlledFirstChildRuntimeAdapter(
            manager,
            market_reference_getter=market_reference_getter,
        )
    except Exception as exc:
        logger.warning("Admin API controlled first-child runtime unavailable: %s", exc)
        return None


def build_admin_api_command_dependencies(
    *,
    read_service_getter: Callable[[], Any | None] | None = None,
) -> AdminApiCommandDependencies:
    """Compose backend-owned dependencies for the shared Admin API command service."""

    live_runtime_enabled = admin_api_live_runtime_enabled()
    credentials_configured = rest_credentials_configured()
    rest_client = (
        load_admin_api_rest_client()
        if live_runtime_enabled and credentials_configured
        else AdminApiRestClientBinding(client=None, available=False)
    )
    portfolio_scope = (
        _spot_portfolio_scope(rest_client.client)
        if rest_client.available
        else None
    )
    if not live_runtime_enabled:
        missing_reason = "live_runtime_disabled"
    elif not credentials_configured:
        missing_reason = "coinbase_rest_credentials_missing"
    elif not rest_client.available:
        missing_reason = "coinbase_rest_client_unavailable"
    elif portfolio_scope is None or portfolio_scope["status"] != "matched":
        missing_reason = (
            (portfolio_scope or {}).get("blocker")
            or "spot_test_portfolio_blocked"
        )
    else:
        missing_reason = None

    def spot_market_reference(product_id: str) -> dict[str, Any] | None:
        return get_admin_api_spot_market_reference(
            product_id,
            rest_client=rest_client.client,
        )

    return AdminApiCommandDependencies(
        rest_client=rest_client.client,
        rest_client_available=rest_client.available,
        live_runtime_enabled=live_runtime_enabled,
        command_runtime_ready=missing_reason is None,
        command_runtime_missing_reason=missing_reason,
        spot_portfolio_id=os.environ.get(SPOT_PORTFOLIO_ID_ENV),
        spot_portfolio_label=(
            os.environ.get(SPOT_PORTFOLIO_LABEL_ENV, "").strip()
            or DEFAULT_SPOT_PORTFOLIO_LABEL
        ),
        spot_market_reference_getter=spot_market_reference,
        order_root_registrar_getter=get_admin_api_order_root_registrar,
        runtime_controller_factory=get_runtime_controller,
        add_log_entry=log_admin_api_command,
        order_event_publisher_getter=get_admin_api_order_event_stream_publisher,
        fill_follow_up_executor_getter=get_admin_api_fill_follow_up_executor,
        stealth_order_runtime_getter=lambda: (
            get_admin_api_controlled_first_child_runtime(
                market_reference_getter=spot_market_reference,
            )
        ),
        read_service_getter=read_service_getter,
        uuid_factory=lambda: str(uuid.uuid4()),
    )


def build_admin_api_command_service(
    *,
    read_service_getter: Callable[[], Any | None] | None = None,
) -> AdminApiCommandService:
    """Build the route-facing Admin API command-service boundary."""

    return AdminApiCommandService(
        build_admin_api_command_dependencies(
            read_service_getter=read_service_getter
        )
    )
