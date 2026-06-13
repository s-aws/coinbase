"""Shared Admin API command service.

FastAPI routes and legacy dashboard compatibility adapters call this service
instead of implementing placement or cancellation separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
import uuid

from calculation.formatter import safe_float
from core.action_condition_guard import ActionConditionGuard
from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
    EventSourceChannel,
    EventStreamType,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductCapability,
    ProductType,
    StealthMutationKind,
    TargetMovementType,
)
from core.exceptions import CoinbaseAPIError, OrderCreationError
from core.product_capability import evaluate_product_capability
from core.runtime_controller import (
    INFLIGHT_REST_CANCEL,
    INFLIGHT_REST_PLACE,
    get_runtime_controller,
)

from .approval import evaluate_live_execution_gate
from .models import (
    AdminApiCommandResponse,
    CampaignExecutionCommand,
    CancelOrderCommand,
    ManualOrderCommand,
    MovementRepriceCommand,
    SpotSweepAutomationRunCommand,
    StealthCancelCommand,
)


def _noop_log(_level: str, _message: str) -> None:
    return None


def _empty_budget() -> dict[str, float]:
    return {}


def _insert_order_parent(**kwargs: Any) -> Any:
    from database.order import insert_order_parent

    return insert_order_parent(**kwargs)


def _update_order_parent_status(client_order_id: str, status: str) -> Any:
    from database.order import update_order_parent_status

    return update_order_parent_status(client_order_id, status)


@dataclass(slots=True)
class AdminApiCommandDependencies:
    """Runtime dependencies required by live command execution."""

    rest_client: Any = None
    rest_client_available: bool = False
    runtime_controller_factory: Callable[[], Any] = get_runtime_controller
    add_log_entry: Callable[[str, str], None] = _noop_log
    order_event_publisher_getter: Callable[[], Any | None] = lambda: None
    planned_budget_fetcher: Callable[[], dict[str, float]] = _empty_budget
    lot_authority_evaluator_getter: Callable[[], Any | None] = lambda: None
    uuid_factory: Callable[[], str] = field(default_factory=lambda: lambda: str(uuid.uuid4()))
    insert_order_parent: Callable[..., Any] = _insert_order_parent
    update_order_parent_status: Callable[[str, str], Any] = _update_order_parent_status


def direct_spot_live_acknowledged(order_params: Mapping[str, Any]) -> bool:
    """Return True when a raw direct spot order includes manual live consent."""

    direct_ack = order_params.get("manual_live_acknowledgement")
    if direct_ack is None:
        direct_ack = order_params.get("manual_live_acknowledged")
    if isinstance(direct_ack, str):
        return direct_ack.strip().lower() in {"true", "yes", "1"}
    return bool(direct_ack)


def coinbase_order_response_to_dict(result: Any) -> dict[str, Any]:
    """Normalize Coinbase order response objects without losing nested fields."""

    converter = getattr(result, "to_dict", None)
    if callable(converter):
        data = converter()
    elif isinstance(result, Mapping):
        data = dict(result)
    elif hasattr(result, "__dict__"):
        data = dict(result.__dict__)
    else:
        data = {}
    return data if isinstance(data, dict) else {}


def coinbase_order_response_success(
    result: Any,
    data: Mapping[str, Any],
) -> bool | None:
    """Return Coinbase success evidence when available."""

    success_attr = getattr(result, "success", None)
    if isinstance(success_attr, bool):
        return success_attr
    success = data.get("success")
    if isinstance(success, bool):
        return success
    if data.get("success_response"):
        return True
    if data.get("error_response") or data.get("failure_reason"):
        return False
    return None


def coinbase_order_response_error_message(result: Any, data: Mapping[str, Any]) -> str:
    """Extract a Coinbase error message from SDK response shapes."""

    error_response = (
        data.get("error_response")
        or getattr(result, "error_response", None)
    )
    if isinstance(error_response, Mapping):
        return str(
            error_response.get("message")
            or error_response.get("error")
            or "Unknown error"
        )
    message = getattr(error_response, "message", None)
    if message:
        return str(message)
    error = getattr(error_response, "error", None)
    if error:
        return str(error)
    failure_reason = data.get("failure_reason")
    if failure_reason:
        return str(failure_reason)
    return "Unknown error"


def coinbase_order_response_order_id(
    result: Any,
    data: Mapping[str, Any],
) -> str | None:
    """Extract exchange-native order id evidence from SDK response shapes."""

    order_id = getattr(result, "order_id", None)
    if order_id:
        return str(order_id)
    success_response = data.get("success_response")
    if isinstance(success_response, Mapping) and success_response.get("order_id"):
        return str(success_response["order_id"])
    if data.get("order_id"):
        return str(data["order_id"])
    order = data.get("order")
    if isinstance(order, Mapping) and order.get("order_id"):
        return str(order["order_id"])
    return None


def publish_direct_order_submission_event(
    *,
    publisher_getter: Callable[[], Any | None],
    client_order_id: str,
    order_id: str | None,
    order_params: Mapping[str, Any],
    order_configuration: Mapping[str, Any],
) -> bool:
    """Publish durable submission evidence for direct manual placement."""

    publisher = publisher_getter()
    if publisher is None or not getattr(publisher, "enabled", False):
        return False

    inner_key = next(iter(order_configuration), None)
    inner = order_configuration.get(inner_key, {}) if inner_key else {}
    payload = {
        "client_order_id": client_order_id,
        "order_id": order_id,
        "product_id": order_params.get("product_id"),
        "side": order_params.get("side"),
        "order_configuration_type": inner_key,
        "order_configuration": order_configuration,
        "base_size": inner.get("base_size"),
        "quote_size": inner.get("quote_size"),
        "limit_price": inner.get("limit_price"),
        "post_only": inner.get("post_only"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    key = f"dashboard_submit:{client_order_id}:{order_id or ''}"
    return bool(
        publisher.publish_event(
            event_type=EventStreamType.ORDER_SUBMITTED.value,
            source_channel=EventSourceChannel.REST_SUBMIT.value,
            payload=payload,
            idempotency_key=key,
            status_to=OrderStatus.PENDING.value,
        )
    )


def manual_order_response_to_dashboard_payload(
    response: AdminApiCommandResponse,
) -> dict[str, Any]:
    """Translate the shared service response to the legacy dashboard payload."""

    status = "success" if response.status == AdminApiCommandStatus.ACCEPTED else "error"
    payload: dict[str, Any] = {
        "type": "order_response",
        "status": status,
        "message": response.message,
    }
    if response.client_order_id:
        payload["client_order_id"] = response.client_order_id
    if response.coinbase_order_id:
        payload["order_id"] = response.coinbase_order_id
    if response.submission_event_recorded is not None:
        payload["submission_event_recorded"] = response.submission_event_recorded
    if response.audit_command:
        payload["audit_command"] = response.audit_command
    if response.guard:
        payload["guard"] = response.guard
    if isinstance(response.data, Mapping):
        payload.update(response.data)
    return payload


def cancel_response_to_dashboard_payload(
    response: AdminApiCommandResponse,
) -> dict[str, Any]:
    """Translate the shared cancel response to the legacy dashboard payload."""

    status = "success" if response.status == AdminApiCommandStatus.ACCEPTED else "error"
    payload: dict[str, Any] = {
        "type": "cancel_response",
        "status": status,
        "message": response.message,
    }
    if response.client_order_id:
        payload["client_order_id"] = response.client_order_id
    if response.data is not None:
        payload["data"] = response.data
    return payload


def hotpoint_test_order_response_to_dashboard_payload(
    response: AdminApiCommandResponse,
) -> dict[str, Any]:
    """Translate shared hotpoint test placement responses to dashboard JSON."""

    success = response.status == AdminApiCommandStatus.ACCEPTED
    payload: dict[str, Any] = {
        "type": "place_hotpoint_test_order_response",
        "success": success,
    }
    if response.client_order_id:
        payload["client_order_id"] = response.client_order_id
    if response.coinbase_order_id:
        payload["order_id"] = response.coinbase_order_id
    if response.submission_event_recorded is not None:
        payload["submission_event_recorded"] = response.submission_event_recorded
    if response.guard:
        payload["guard"] = response.guard
    if isinstance(response.data, Mapping):
        payload.update(response.data)
    if not success:
        payload.setdefault("error", response.failure_stage or "rejected")
        payload.setdefault("message", response.message)
    return payload


class AdminApiCommandService:
    """Shared command-service boundary for enterprise API work."""

    def __init__(self, dependencies: AdminApiCommandDependencies | None = None) -> None:
        self.dependencies = dependencies or AdminApiCommandDependencies()

    def place_manual_order(self, command: ManualOrderCommand) -> AdminApiCommandResponse:
        """Place a manual order through the existing guarded REST path."""

        if not command.allow_live_execution:
            gate = evaluate_live_execution_gate(allow_live_execution=False)
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.NOT_IMPLEMENTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_manual_order",
                message=(
                    "Manual order placement requires enterprise auth, "
                    "idempotency, approval, and cap gates before live execution."
                ),
                client_order_id=command.request.client_order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                guard=gate.model_dump(),
                failure_stage="approval",
            )

        deps = self.dependencies
        client_order_id = command.request.client_order_id or deps.uuid_factory()
        order_params, order_configuration = self._manual_order_payload(command)

        if not deps.rest_client_available:
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message="REST client not available",
                failure_stage="rest_client",
            )

        try:
            product_id = order_params.get("product_id")
            inner_key = next(iter(order_configuration), None)
            inner = order_configuration.get(inner_key, {}) if inner_key else {}
            raw_size = inner.get("base_size")
            raw_quote_size = inner.get("quote_size")
            raw_price = inner.get("limit_price")

            capability = evaluate_product_capability(
                product_id=product_id,
                capability=ProductCapability.DIRECT_PLACEMENT,
            )
            if not capability.allowed:
                message = (
                    "Order rejected by product capability policy: "
                    f"{capability.reason}"
                )
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    data={"capability": capability.to_dict()},
                    failure_stage="product_capability",
                )

            if (
                capability.product_type == ProductType.SPOT.value
                and not direct_spot_live_acknowledged(order_params)
            ):
                reason = (
                    "Direct spot place_order is a live manual order surface; "
                    "set params.manual_live_acknowledgement=true before REST submission."
                )
                guard_failure = {
                    "condition": ActionConditionType.MANUAL_LIVE_ACKNOWLEDGEMENT.value,
                    "block_category": (
                        ActionConditionType.MANUAL_LIVE_ACKNOWLEDGEMENT.value
                    ),
                    "reason": reason,
                    "product_id": product_id,
                    "product_type": capability.product_type,
                    "side": order_params.get("side"),
                    "client_order_id": client_order_id,
                    "phase": ActionGuardPhase.PLANNING.value,
                    "manual_live_acknowledgement_required": True,
                }
                message = f"Order rejected by manual live acknowledgement: {reason}"
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    guard=guard_failure,
                    failure_stage="manual_live_acknowledgement",
                )

            approved_base_size = None
            if raw_size is not None:
                from calculation.size_validation import validate_and_quantize_size

                size_check = validate_and_quantize_size(
                    raw_size,
                    product_id=product_id,
                    price=float(raw_price) if raw_price is not None else None,
                )
                if not size_check:
                    raise OrderCreationError(
                        f"Order rejected at boundary: {size_check.reason}",
                        client_order_id=client_order_id,
                    )
                inner["base_size"] = str(size_check.size)
                approved_base_size = size_check.size

            quote_size = safe_float(raw_quote_size, default=None)
            if raw_quote_size is not None:
                from calculation.size_validation import validate_quote_size

                quote_check = validate_quote_size(raw_quote_size, product_id=product_id)
                if not quote_check:
                    raise OrderCreationError(
                        f"Order rejected at boundary: {quote_check.reason}",
                        client_order_id=client_order_id,
                    )
                inner["quote_size"] = str(quote_check.size)
                quote_size = quote_check.size

            if approved_base_size is not None or quote_size is not None:
                action_guard = ActionConditionGuard(
                    planned_budget_fetcher=deps.planned_budget_fetcher,
                    lot_authority_evaluator=deps.lot_authority_evaluator_getter(),
                )
                if capability.product_type == ProductType.SPOT.value:
                    if not action_guard.has_applicable_notional_cap(
                        phase=ActionGuardPhase.PLANNING,
                        product_id=product_id,
                        side=order_params.get("side"),
                    ):
                        reason = (
                            "Direct spot place_order requires an explicit "
                            "planning-phase max_notional action-condition cap "
                            "before REST submission."
                        )
                        guard_failure = {
                            "condition": (
                                ActionConditionType.DIRECT_SPOT_CAP_REQUIRED.value
                            ),
                            "block_category": (
                                ActionConditionType.DIRECT_SPOT_CAP_REQUIRED.value
                            ),
                            "reason": reason,
                            "product_id": product_id,
                            "product_type": capability.product_type,
                            "side": order_params.get("side"),
                            "client_order_id": client_order_id,
                            "phase": ActionGuardPhase.PLANNING.value,
                            "max_notional_cap_required": True,
                        }
                        message = (
                            "Order rejected by direct spot cap policy: "
                            f"{reason}"
                        )
                        deps.add_log_entry("WARNING", message)
                        return self._place_rejected(
                            command=command,
                            client_order_id=client_order_id,
                            message=message,
                            guard=guard_failure,
                            failure_stage="direct_spot_cap_required",
                        )
                    if (
                        str(order_params.get("side") or "").upper()
                        == OrderSide.SELL.value
                        and not action_guard.requires_known_inventory_for_sell(
                            phase=ActionGuardPhase.PLANNING,
                            product_id=product_id,
                            side=order_params.get("side"),
                        )
                    ):
                        reason = (
                            "Direct spot SELL requires the "
                            "known_inventory_available action-condition guard "
                            "before REST submission."
                        )
                        guard_failure = {
                            "condition": (
                                ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
                            ),
                            "block_category": (
                                ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
                            ),
                            "reason": reason,
                            "product_id": product_id,
                            "product_type": capability.product_type,
                            "side": order_params.get("side"),
                            "client_order_id": client_order_id,
                            "phase": ActionGuardPhase.PLANNING.value,
                            "known_inventory_available_required": True,
                        }
                        message = (
                            "Order rejected by direct spot SELL authority policy: "
                            f"{reason}"
                        )
                        deps.add_log_entry("WARNING", message)
                        return self._place_rejected(
                            command=command,
                            client_order_id=client_order_id,
                            message=message,
                            guard=guard_failure,
                            failure_stage="known_inventory_required",
                        )

                guard_ok, guard_failure = action_guard.evaluate(
                    phase=ActionGuardPhase.PLANNING,
                    product_id=product_id,
                    side=order_params.get("side"),
                    size=approved_base_size,
                    limit_price=safe_float(raw_price, default=0.0),
                    quote_size=quote_size,
                    client_order_id=client_order_id,
                )
                if not guard_ok:
                    reason = (guard_failure or {}).get("reason", "blocked")
                    message = f"Order rejected by action-condition guard: {reason}"
                    deps.add_log_entry("WARNING", message)
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=message,
                        guard=guard_failure,
                        failure_stage="action_condition_guard",
                    )

            submission_event_publisher = None
            if capability.product_type == ProductType.SPOT.value:
                submission_event_publisher = deps.order_event_publisher_getter()
                if submission_event_publisher is None or not getattr(
                    submission_event_publisher,
                    "enabled",
                    False,
                ):
                    reason = (
                        "Direct spot place_order requires local durable "
                        "order_event_stream audit before REST submission."
                    )
                    guard_failure = {
                        "condition": ActionConditionType.DURABLE_AUDIT_AVAILABLE.value,
                        "block_category": (
                            ActionConditionType.DURABLE_AUDIT_AVAILABLE.value
                        ),
                        "reason": reason,
                        "product_id": product_id,
                        "product_type": capability.product_type,
                        "side": order_params.get("side"),
                        "client_order_id": client_order_id,
                        "phase": ActionGuardPhase.PLANNING.value,
                        "durable_audit_required": True,
                    }
                    message = (
                        "Order rejected by direct spot durable audit policy: "
                        f"{reason}"
                    )
                    deps.add_log_entry("WARNING", message)
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=message,
                        guard=guard_failure,
                        failure_stage="durable_audit_required",
                    )

            controller = deps.runtime_controller_factory()
            with controller.track_inflight(INFLIGHT_REST_PLACE):
                result = deps.rest_client.create_order(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    side=order_params.get("side"),
                    order_configuration=order_configuration,
                )

            result_dict = coinbase_order_response_to_dict(result)
            response_success = coinbase_order_response_success(result, result_dict)
            if response_success is False:
                error_msg = coinbase_order_response_error_message(result, result_dict)
                raise CoinbaseAPIError(
                    f"Order creation failed: {error_msg}",
                    api_error_code="order_creation_failed",
                )

            order_id = coinbase_order_response_order_id(result, result_dict)
            submission_event_recorded = publish_direct_order_submission_event(
                publisher_getter=lambda: (
                    submission_event_publisher
                    or deps.order_event_publisher_getter()
                ),
                client_order_id=client_order_id,
                order_id=order_id,
                order_params=order_params,
                order_configuration=order_configuration,
            )
            deps.add_log_entry(
                "INFO",
                f"Order created: {order_params.get('product_id')} {order_params.get('side')}",
            )
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_manual_order",
                message="Order created",
                client_order_id=client_order_id,
                coinbase_order_id=order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                live_exchange_submitted=True,
                submission_event_recorded=submission_event_recorded,
                audit_command=(
                    "python tools\\run_spot_direct_order_audit.py "
                    f"--client-order-id {client_order_id}"
                ),
            )
        except CoinbaseAPIError as exc:
            deps.add_log_entry("ERROR", f"API error: {exc}")
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message=str(exc),
                failure_stage="coinbase_rest",
            )
        except Exception as exc:
            raise OrderCreationError(
                f"Failed to place order: {exc}",
                client_order_id=client_order_id,
            ) from exc

    def cancel_order_by_client_order_id(
        self,
        command: CancelOrderCommand,
    ) -> AdminApiCommandResponse:
        """Cancel a live order through the project ``cancel_order(client_order_id)`` wrapper."""

        if not command.allow_live_execution:
            gate = evaluate_live_execution_gate(allow_live_execution=False)
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.NOT_IMPLEMENTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method="cancel_order_by_client_order_id",
                message=(
                    "Cancel requires enterprise auth, idempotency, and rate/cap "
                    "gates before live execution."
                ),
                client_order_id=command.client_order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                guard=gate.model_dump(),
                failure_stage="approval",
            )

        deps = self.dependencies
        client_order_id = command.client_order_id
        if not deps.rest_client_available:
            return self._cancel_rejected(
                command=command,
                message="REST client not available",
                failure_stage="rest_client",
            )
        if not client_order_id:
            return self._cancel_rejected(
                command=command,
                message=(
                    "Missing client_order_id; pass client_order_id, not "
                    "order_id, to dashboard cancel_order."
                ),
                failure_stage="validation",
            )

        try:
            controller = deps.runtime_controller_factory()
            with controller.track_inflight(INFLIGHT_REST_CANCEL):
                result = deps.rest_client.cancel_order(client_order_id)

            if result is False:
                message = "Order cancellation was not accepted by Coinbase"
                deps.add_log_entry(
                    "WARNING",
                    f"{message}: client_order_id={client_order_id}",
                )
                return AdminApiCommandResponse(
                    status=AdminApiCommandStatus.REJECTED,
                    action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                    required_permission=AdminApiPermission.ORDER_CANCEL,
                    service_method="cancel_order_by_client_order_id",
                    message=message,
                    client_order_id=client_order_id,
                    correlation_id=command.envelope.correlation_id,
                    idempotency_key=command.envelope.idempotency_key,
                    live_exchange_submitted=True,
                    data=result,
                    failure_stage="coinbase_rest",
                )

            deps.add_log_entry("INFO", f"Order cancelled: client_order_id={client_order_id}")
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method="cancel_order_by_client_order_id",
                message="Order cancelled",
                client_order_id=client_order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                live_exchange_submitted=True,
                data=result,
            )
        except Exception as exc:
            deps.add_log_entry("ERROR", f"Order cancellation failed: {exc}")
            return self._cancel_rejected(
                command=command,
                message=str(exc),
                failure_stage="coinbase_rest",
            )

    def cancel_stealth_order_by_stealth_order_id(
        self,
        command: StealthCancelCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a stealth lifecycle cancel command through the live gate.

        This contract is keyed by ``stealth_order_id``. Active placement client
        ids and Coinbase order ids remain evidence only until the stealth
        lifecycle path owns the exchange handling and local-state reconciliation.
        """

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="cancel_stealth_order_by_stealth_order_id",
            message=(
                "Stealth cancel requires enterprise auth, idempotency, audit, "
                "approval, cap/rate gates, and exchange-reality reconciliation "
                "before live execution."
            ),
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "stealth_order_id": command.stealth_order_id,
                "reason": command.request.reason,
                "identity_key": "stealth_order_id",
                "active_placement_client_order_id": None,
                "exchange_order_id_evidence_only": True,
            },
            failure_stage="approval",
        )

    def reprice_stealth_order_by_stealth_order_id(
        self,
        command: MovementRepriceCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a stealth reprice command through the live-disabled gate.

        This Admin API contract is keyed by ``stealth_order_id`` and does not
        invoke the live dashboard repricer. Future live enablement must enter
        through the existing cancel/reprice/reconcile path so revealed exchange
        placements and local stealth state stay in sync.
        """

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="reprice_stealth_order_by_stealth_order_id",
            message=(
                "Stealth reprice requires enterprise auth, idempotency, audit, "
                "approval, cap/rate gates, mutation-claim coordination, and "
                "exchange-reality reconciliation before live execution."
            ),
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "stealth_order_id": command.stealth_order_id,
                "reason": command.request.reason,
                "identity_key": "stealth_order_id",
                "mutation_kind": StealthMutationKind.REPRICE.value,
                "active_placement_client_order_id": None,
                "exchange_order_id_evidence_only": True,
                "cooldown_cleared": False,
                "stealth_manager_invoked": False,
            },
            failure_stage="approval",
        )

    def execute_spot_campaign(
        self,
        command: CampaignExecutionCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a future spot campaign execution command through the live gate."""

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
            service_method="execute_spot_campaign",
            message=(
                "Spot campaign execution requires enterprise auth, "
                "idempotency, approval, caps, and campaign safety gates before "
                "live execution."
            ),
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "campaign_id": command.request.campaign_id,
                "side": command.request.side.value,
                "dry_run": command.request.dry_run,
                "product_count": len(command.request.product_ids or []),
                "manual_live_acknowledgement": (
                    command.request.manual_live_acknowledgement
                ),
            },
            failure_stage="approval",
        )

    def run_spot_sweep_automation(
        self,
        command: SpotSweepAutomationRunCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a future spot sweep automation run through the live gate."""

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.SPOT_SWEEP_EXECUTE,
            service_method="run_spot_sweep_automation",
            message=(
                "Spot sweep automation requires enterprise scheduling, "
                "idempotency, approval, caps, run-limit, recovery, and "
                "reconciliation gates before live execution."
            ),
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "sweep_config_id": command.request.sweep_config_id,
                "side": command.request.side.value,
                "dry_run": command.request.dry_run,
                "run_if_due": command.request.run_if_due,
                "max_runs": command.request.max_runs,
                "max_products": command.request.max_products,
                "max_planned_orders": command.request.max_planned_orders,
                "repeat_every_hours": command.request.repeat_every_hours,
                "quote_notional_per_product": (
                    command.request.quote_notional_per_product
                ),
                "max_total_notional_per_run": (
                    command.request.max_total_notional_per_run
                ),
                "max_notional_per_order": command.request.max_notional_per_order,
                "manual_live_acknowledgement": (
                    command.request.manual_live_acknowledgement
                ),
                "sweep_runner_invoked": False,
            },
            failure_stage="approval",
        )

    def place_hotpoint_test_order(self, command: ManualOrderCommand) -> AdminApiCommandResponse:
        """Place a hotpoint seed order through the shared guarded path."""

        if not command.allow_live_execution:
            gate = evaluate_live_execution_gate(allow_live_execution=False)
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.NOT_IMPLEMENTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_hotpoint_test_order",
                message=(
                    "Hotpoint test placement requires enterprise auth, "
                    "idempotency, approval, and cap gates before live execution."
                ),
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                guard=gate.model_dump(),
                failure_stage="approval",
            )

        deps = self.dependencies
        client_order_id = deps.uuid_factory()
        request = command.request
        product_id = request.product_id
        side = request.side.value if isinstance(request.side, OrderSide) else str(request.side)
        raw_price = safe_float(request.limit_price, default=0.0)
        raw_size = request.base_size

        if not (product_id and side and raw_price and raw_price > 0 and raw_size is not None):
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message="Invalid hotpoint test order payload",
                failure_stage="invalid_payload",
                service_method="place_hotpoint_test_order",
            )

        if not deps.rest_client_available:
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message="REST client not available",
                failure_stage="rest_client_unavailable",
                service_method="place_hotpoint_test_order",
            )

        parent_row_inserted = False
        try:
            capability = evaluate_product_capability(
                product_id=product_id,
                capability=ProductCapability.HOTPOINT_AUTO_PLACEMENT,
            )
            if not capability.allowed:
                message = (
                    "Hotpoint test order rejected by product capability policy: "
                    f"{capability.reason}"
                )
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    data={
                        "error": "product_capability_blocked",
                        "capability": capability.to_dict(),
                    },
                    failure_stage="product_capability_blocked",
                    service_method="place_hotpoint_test_order",
                )

            from calculation.size_validation import validate_and_quantize_size

            size_check = validate_and_quantize_size(
                raw_size,
                product_id=product_id,
                price=raw_price,
            )
            if not size_check:
                message = (
                    "Hotpoint test order rejected at boundary: "
                    f"{size_check.reason}"
                )
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    data={"error": "size_validation_failed"},
                    failure_stage="size_validation_failed",
                    service_method="place_hotpoint_test_order",
                )
            approved_size = size_check.size

            guard_ok, guard_failure = ActionConditionGuard(
                planned_budget_fetcher=deps.planned_budget_fetcher,
                lot_authority_evaluator=deps.lot_authority_evaluator_getter(),
            ).evaluate(
                phase=ActionGuardPhase.PLANNING,
                product_id=product_id,
                side=side,
                size=approved_size,
                limit_price=raw_price,
                client_order_id=client_order_id,
            )
            if not guard_ok:
                reason = (guard_failure or {}).get("reason", "blocked")
                message = (
                    "Hotpoint test order rejected by action-condition guard: "
                    f"{reason}"
                )
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    guard=guard_failure,
                    data={"error": "action_condition_guard_blocked"},
                    failure_stage="action_condition_guard_blocked",
                    service_method="place_hotpoint_test_order",
                )

            parent_id = deps.insert_order_parent(
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                size=approved_size,
                price=raw_price,
                target_movement=0.0,
                target_movement_type=TargetMovementType.PERCENTAGE.value,
                max_order_replacement=0,
                current_order_replacement=0,
                status=OrderStatus.PENDING.value,
                parent_order_id=None,
                allow_partial_fills=False,
                enable_hotpoint_replication=True,
                auto_placed_by_hotpoint=False,
            )
            if parent_id is None:
                raise OrderCreationError(
                    "failed to pre-insert hotpoint test parent order",
                    client_order_id=client_order_id,
                )
            parent_row_inserted = True

            order_configuration = {
                "limit_limit_gtc": {
                    "base_size": str(approved_size),
                    "limit_price": str(raw_price),
                    "post_only": False,
                },
            }
            controller = deps.runtime_controller_factory()
            with controller.track_inflight(INFLIGHT_REST_PLACE):
                result = deps.rest_client.limit_order_gtc(
                    product_id=product_id,
                    side=side,
                    base_size=str(approved_size),
                    limit_price=str(raw_price),
                    client_order_id=client_order_id,
                    post_only=False,
                )

            result_dict = coinbase_order_response_to_dict(result)
            response_success = coinbase_order_response_success(result, result_dict)
            if response_success is False:
                error_msg = coinbase_order_response_error_message(result, result_dict)
                raise CoinbaseAPIError(
                    f"Hotpoint test order creation failed: {error_msg}",
                    api_error_code="hotpoint_test_order_creation_failed",
                )

            order_id = coinbase_order_response_order_id(result, result_dict)
            submission_event_recorded = publish_direct_order_submission_event(
                publisher_getter=deps.order_event_publisher_getter,
                client_order_id=client_order_id,
                order_id=order_id,
                order_params={"product_id": product_id, "side": side},
                order_configuration=order_configuration,
            )
            deps.add_log_entry(
                "INFO",
                (
                    "Hotpoint test order placed: "
                    f"{client_order_id} {product_id} {side} {approved_size}@{raw_price}"
                ),
            )
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_hotpoint_test_order",
                message="Hotpoint test order placed",
                client_order_id=client_order_id,
                coinbase_order_id=order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                live_exchange_submitted=True,
                submission_event_recorded=submission_event_recorded,
            )
        except CoinbaseAPIError as exc:
            deps.add_log_entry("ERROR", f"Hotpoint test order API error: {exc}")
            if parent_row_inserted:
                self._mark_hotpoint_parent_failed(deps, client_order_id)
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message=str(exc),
                data={"error": str(exc)},
                failure_stage="coinbase_rest",
                service_method="place_hotpoint_test_order",
            )
        except Exception:
            if parent_row_inserted:
                self._mark_hotpoint_parent_failed(deps, client_order_id)
            raise

    def _manual_order_payload(
        self,
        command: ManualOrderCommand,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        request = command.request
        order_params = {
            "product_id": request.product_id,
            "side": request.side.value if isinstance(request.side, OrderSide) else str(request.side),
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
        }
        if command.order_configuration_override is not None:
            return order_params, dict(command.order_configuration_override)

        if request.order_type == OrderType.MARKET:
            inner: dict[str, Any] = {}
            if request.base_size is not None:
                inner["base_size"] = request.base_size
            if request.quote_size is not None:
                inner["quote_size"] = request.quote_size
            return order_params, {"market_market_ioc": inner}

        inner = {
            "base_size": request.base_size,
            "limit_price": request.limit_price,
            "post_only": request.post_only,
        }
        if request.quote_size is not None:
            inner["quote_size"] = request.quote_size
        return order_params, {"limit_limit_gtc": {k: v for k, v in inner.items() if v is not None}}

    def _place_rejected(
        self,
        *,
        command: ManualOrderCommand,
        client_order_id: str,
        message: str,
        failure_stage: str,
        guard: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        service_method: str = "place_manual_order",
    ) -> AdminApiCommandResponse:
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method=service_method,
            message=message,
            client_order_id=client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            guard=guard,
            data=data,
            failure_stage=failure_stage,
        )

    def _mark_hotpoint_parent_failed(
        self,
        deps: AdminApiCommandDependencies,
        client_order_id: str,
    ) -> None:
        try:
            deps.update_order_parent_status(client_order_id, OrderStatus.FAILED.value)
        except Exception as update_exc:
            deps.add_log_entry(
                "ERROR",
                f"failed to mark hotpoint test order parent FAILED: {update_exc}",
            )

    def _cancel_rejected(
        self,
        *,
        command: CancelOrderCommand,
        message: str,
        failure_stage: str,
    ) -> AdminApiCommandResponse:
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="cancel_order_by_client_order_id",
            message=message,
            client_order_id=command.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            failure_stage=failure_stage,
        )
