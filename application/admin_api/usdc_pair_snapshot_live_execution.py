"""Backend-only controlled-live executor for M58 USDC snapshot order plans."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os
from typing import Any, Iterable, Mapping, Sequence

from core.runtime_controller import (
    INFLIGHT_REST_CANCEL,
    INFLIGHT_REST_PLACE,
    get_runtime_controller,
)
from tools.coinbase_live_credentials import ensure_live_coinbase_credentials

from .command_runtime import (
    build_admin_api_command_runtime_readiness,
    load_admin_api_rest_client,
)


MISSING_EXECUTED_NOTIONAL_EVIDENCE_STATUS = "missing_or_invalid"
VERIFIED_EXECUTED_NOTIONAL_EVIDENCE_STATUS = "verified_decimal"


class UsdcPairSnapshotLiveExecutionError(RuntimeError):
    """Raised when controlled-live M58 execution must fail closed."""


class UsdcPairSnapshotLiveOrderExecutor:
    """Submit one far-from-market Coinbase order and cancel it immediately."""

    def submit_and_cancel(
        self,
        *,
        client_order_id: str,
        product_id: str,
        side: str,
        order_configuration: Mapping[str, Any],
        submitted_notional_usdc: str,
        max_executed_notional_usdc: str,
        cancel_client_order_id: str,
    ) -> dict[str, Any]:
        if cancel_client_order_id != client_order_id:
            raise UsdcPairSnapshotLiveExecutionError(
                "M58 live submit requires cancel by the same client_order_id."
            )

        self._hydrate_backend_coinbase_credentials()
        readiness = build_admin_api_command_runtime_readiness()
        if not readiness.runtime_ready:
            raise UsdcPairSnapshotLiveExecutionError(
                "M58 live submit blocked by backend runtime readiness: "
                f"{readiness.missing_reason or 'unknown'}"
            )
        binding = load_admin_api_rest_client()
        if not binding.available or binding.client is None:
            raise UsdcPairSnapshotLiveExecutionError(
                "M58 live submit blocked: Coinbase REST client unavailable."
            )

        controller = get_runtime_controller()
        submitted_at = datetime.now(timezone.utc).isoformat()
        with controller.track_inflight(INFLIGHT_REST_PLACE):
            submit_result = binding.client.create_order(
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                order_configuration=dict(order_configuration),
            )
        submit_result_data = _object_to_dict(submit_result)
        submit_success = _coinbase_create_order_success(
            submit_result,
            submit_result_data,
        )
        if submit_success is False:
            raise UsdcPairSnapshotLiveExecutionError(
                "M58 live submit rejected by Coinbase create_order."
            )

        coinbase_order_id = _coinbase_order_id(submit_result, submit_result_data)
        try:
            with controller.track_inflight(INFLIGHT_REST_CANCEL):
                cancel_result = binding.client.cancel_order(client_order_id)
            cancel_result_data = _cancel_result_to_dict(
                cancel_result,
                client_order_id=client_order_id,
            )
            cancel_submitted = _cancel_result_success(cancel_result)
            if not cancel_submitted and coinbase_order_id:
                fallback_cancel = getattr(
                    binding.client,
                    "cancel_order_by_exchange_order_id",
                    None,
                )
                if callable(fallback_cancel):
                    with controller.track_inflight(INFLIGHT_REST_CANCEL):
                        fallback_result = fallback_cancel(coinbase_order_id)
                    fallback_result_data = _cancel_result_to_dict(
                        fallback_result,
                        client_order_id=client_order_id,
                    )
                    fallback_submitted = _cancel_result_success(fallback_result)
                    cancel_result_data = {
                        "success": fallback_submitted,
                        "client_order_id": client_order_id,
                        "fallback_order_id": coinbase_order_id,
                        "initial_cancel_result": cancel_result_data,
                        "fallback_cancel_result": fallback_result_data,
                    }
                    cancel_submitted = fallback_submitted
            cancel_error = None
        except Exception as exc:
            cancel_result_data = {
                "success": False,
                "client_order_id": client_order_id,
                "error": str(exc),
            }
            cancel_submitted = False
            cancel_error = str(exc)

        cancelled_at = datetime.now(timezone.utc).isoformat()
        executed_notional_usdc = _coinbase_executed_notional_usdc(
            submit_result_data
        )
        if executed_notional_usdc == "0":
            executed_notional_usdc = _coinbase_executed_notional_usdc(
                cancel_result_data
            )
        cancel_rollback_complete = cancel_submitted and not _decimal_text_positive(
            executed_notional_usdc
        )
        live_execution = (
            "submitted_cancelled"
            if cancel_rollback_complete
            else "submitted_cancel_failed"
        )
        result = {
            "coinbase_order_id": coinbase_order_id,
            "submit_result": submit_result_data,
            "cancel_result": cancel_result_data,
            "submitted_at": submitted_at,
            "cancelled_at": cancelled_at,
            "order_configuration": dict(order_configuration),
            "live_exchange_submitted": True,
            "live_coinbase_orders_ran": True,
            "live_coinbase_execution": live_execution,
            "executed_notional_usdc": executed_notional_usdc,
            "submitted_notional_usdc": submitted_notional_usdc,
            "max_executed_notional_usdc": max_executed_notional_usdc,
            "cancel_submitted": cancel_submitted,
            "cancel_rollback_complete": cancel_rollback_complete,
        }
        if cancel_error:
            result["cancel_error"] = cancel_error
        return result

    @staticmethod
    def _hydrate_backend_coinbase_credentials() -> None:
        ensure_live_coinbase_credentials(os.environ)
        import configuration

        api_key = os.environ.get("COINBASE_API_KEY", "")
        api_secret = os.environ.get("COINBASE_API_SECRET", "")
        if getattr(configuration, "API_KEY", "") != api_key:
            configuration.API_KEY = api_key
            try:
                configuration.REST_CLIENT._real = None
            except Exception:
                pass
        if getattr(configuration, "API_SECRET", "") != api_secret:
            configuration.API_SECRET = api_secret
            try:
                configuration.REST_CLIENT._real = None
            except Exception:
                pass


class UsdcPairSnapshotLiveFanoutExecutor:
    """Submit queued orders one at a time, requiring cancel before continuing."""

    def __init__(
        self,
        order_executor: UsdcPairSnapshotLiveOrderExecutor | None = None,
    ) -> None:
        self._order_executor = order_executor or UsdcPairSnapshotLiveOrderExecutor()

    def submit_and_cancel_all(
        self,
        *,
        orders: Sequence[Mapping[str, Any]],
        max_orders_per_second: int = 5,
    ) -> dict[str, Any]:
        order_items = list(orders)
        if not order_items:
            raise UsdcPairSnapshotLiveExecutionError(
                "M58 live fan-out submit requires at least one queued order."
            )
        if max_orders_per_second <= 0:
            raise UsdcPairSnapshotLiveExecutionError(
                "M58 live fan-out submit requires a positive order rate cap."
            )
        if len(order_items) > max_orders_per_second:
            raise UsdcPairSnapshotLiveExecutionError(
                "M58 live fan-out submit exceeds "
                f"{max_orders_per_second} orders per second."
            )

        results: list[dict[str, Any]] = []
        for order in order_items:
            call = _fanout_order_call(order)
            execution = _object_to_dict(
                self._order_executor.submit_and_cancel(**call)
            )
            _ensure_fanout_execution_identity(execution, call)
            execution.setdefault("client_order_id", call["client_order_id"])
            execution.setdefault("product_id", call["product_id"])
            execution.setdefault("side", call["side"])
            execution.setdefault(
                "submitted_notional_usdc",
                call["submitted_notional_usdc"],
            )
            execution.setdefault(
                "max_executed_notional_usdc",
                call["max_executed_notional_usdc"],
            )
            (
                executed_notional_usdc,
                executed_notional_positive,
                executed_notional_valid,
            ) = _execution_executed_notional_evidence(execution)
            execution["executed_notional_usdc"] = executed_notional_usdc
            if not executed_notional_valid:
                execution["executed_notional_evidence_status"] = (
                    MISSING_EXECUTED_NOTIONAL_EVIDENCE_STATUS
                )
                execution["cancel_rollback_complete"] = False
                execution["live_coinbase_execution"] = "submitted_cancel_failed"
            else:
                execution["executed_notional_evidence_status"] = (
                    VERIFIED_EXECUTED_NOTIONAL_EVIDENCE_STATUS
                )
            results.append(execution)
            if (
                not executed_notional_valid
                or not _execution_cancel_rollback_complete(execution)
                or executed_notional_positive
            ):
                break

        cancel_submitted = (
            len(results) == len(order_items)
            and all(_execution_cancel_submitted(result) for result in results)
        )
        cancel_rollback_complete = (
            len(results) == len(order_items)
            and all(
                _execution_cancel_rollback_complete(result) for result in results
            )
        )
        return {
            "requested_order_count": len(order_items),
            "order_count": len(results),
            "orders": results,
            "submitted_notional_usdc": _decimal_sum_string(
                result.get("submitted_notional_usdc") for result in results
            ),
            "executed_notional_usdc": _executed_notional_sum_string(results),
            "executed_notional_evidence_status": (
                VERIFIED_EXECUTED_NOTIONAL_EVIDENCE_STATUS
                if all(
                    _execution_executed_notional_evidence(result)[2]
                    for result in results
                )
                else MISSING_EXECUTED_NOTIONAL_EVIDENCE_STATUS
            ),
            "max_executed_notional_usdc": _decimal_sum_string(
                result.get("max_executed_notional_usdc") for result in results
            ),
            "max_orders_per_second": max_orders_per_second,
            "cancel_submitted": cancel_submitted,
            "cancel_rollback_complete": cancel_rollback_complete,
            "additional_orders_blocked": True,
            "live_exchange_submitted": any(
                bool(result.get("live_exchange_submitted")) for result in results
            ),
            "live_coinbase_orders_ran": any(
                bool(result.get("live_coinbase_orders_ran")) for result in results
            ),
            "live_coinbase_execution": (
                "submitted_cancelled"
                if cancel_rollback_complete
                else "submitted_cancel_failed"
            ),
        }


def _fanout_order_call(order: Mapping[str, Any]) -> dict[str, Any]:
    client_order_id = _required_text(order, "client_order_id")
    cancel_client_order_id = str(
        order.get("cancel_client_order_id") or client_order_id
    ).strip()
    if cancel_client_order_id != client_order_id:
        raise UsdcPairSnapshotLiveExecutionError(
            "M58 live fan-out submit requires cancel by the same client_order_id."
        )
    order_configuration = order.get("order_configuration")
    if not isinstance(order_configuration, Mapping):
        raise UsdcPairSnapshotLiveExecutionError(
            "M58 live fan-out submit requires order_configuration evidence."
        )
    return {
        "client_order_id": client_order_id,
        "product_id": _required_text(order, "product_id"),
        "side": _required_text(order, "side"),
        "order_configuration": dict(order_configuration),
        "submitted_notional_usdc": _required_text(
            order,
            "submitted_notional_usdc",
        ),
        "max_executed_notional_usdc": _required_text(
            order,
            "max_executed_notional_usdc",
        ),
        "cancel_client_order_id": cancel_client_order_id,
    }


def _ensure_fanout_execution_identity(
    execution: Mapping[str, Any],
    call: Mapping[str, Any],
) -> None:
    mismatches: list[str] = []

    def check_text(
        field: str,
        observed: Any,
        expected: str,
        *,
        normalize_upper: bool = False,
    ) -> None:
        observed_text = _optional_text(observed)
        if not observed_text:
            return
        expected_text = str(expected).strip()
        left = observed_text.upper() if normalize_upper else observed_text
        right = expected_text.upper() if normalize_upper else expected_text
        if left != right:
            mismatches.append(field)

    check_text(
        "client_order_id",
        execution.get("client_order_id"),
        str(call["client_order_id"]),
    )
    check_text(
        "product_id",
        execution.get("product_id"),
        str(call["product_id"]),
        normalize_upper=True,
    )
    check_text(
        "side",
        execution.get("side"),
        str(call["side"]),
        normalize_upper=True,
    )
    for result_field in ("submit_result", "cancel_result"):
        result = execution.get(result_field)
        if isinstance(result, Mapping):
            check_text(
                f"{result_field}.client_order_id",
                result.get("client_order_id"),
                str(call["client_order_id"]),
            )

    if mismatches:
        raise UsdcPairSnapshotLiveExecutionError(
            "M58 live fan-out submit received mismatched execution evidence: "
            + ",".join(mismatches)
        )


def _optional_text(value: Any) -> str:
    enum_value = getattr(value, "value", None)
    return str(enum_value if enum_value is not None else value or "").strip()


def _required_text(order: Mapping[str, Any], key: str) -> str:
    value = order.get(key)
    text = _optional_text(value)
    if not text:
        raise UsdcPairSnapshotLiveExecutionError(
            f"M58 live fan-out submit requires {key}."
        )
    return text


def _execution_cancel_submitted(execution: Mapping[str, Any]) -> bool:
    if "cancel_submitted" in execution:
        return bool(execution.get("cancel_submitted"))
    cancel_result = execution.get("cancel_result")
    return _cancel_result_success(cancel_result) if cancel_result is not None else False


def _execution_cancel_rollback_complete(execution: Mapping[str, Any]) -> bool:
    if "cancel_rollback_complete" in execution:
        return bool(execution.get("cancel_rollback_complete"))
    return _execution_cancel_submitted(execution)


def _execution_executed_notional_positive(execution: Mapping[str, Any]) -> bool:
    return _execution_executed_notional_evidence(execution)[1]


def _execution_executed_notional_evidence(
    execution: Mapping[str, Any],
) -> tuple[str, bool, bool]:
    if (
        _optional_text(execution.get("executed_notional_evidence_status"))
        == MISSING_EXECUTED_NOTIONAL_EVIDENCE_STATUS
    ):
        return "0", False, False
    text = _optional_text(execution.get("executed_notional_usdc"))
    if not text:
        return "0", False, False
    try:
        decimal_value = Decimal(text)
    except (InvalidOperation, ValueError):
        return "0", False, False
    if decimal_value < 0:
        return "0", False, False
    return text, decimal_value > 0, True


def _decimal_text_positive(value: Any) -> bool:
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, ValueError) as exc:
        raise UsdcPairSnapshotLiveExecutionError(
            "M58 live fan-out submit requires valid executed notional evidence."
        ) from exc


def _decimal_sum_string(values: Iterable[Any]) -> str:
    total = Decimal("0")
    for value in values:
        try:
            total += Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise UsdcPairSnapshotLiveExecutionError(
                "M58 live fan-out submit requires valid notional evidence."
            ) from exc
    return str(total)


def _executed_notional_sum_string(
    executions: Iterable[Mapping[str, Any]],
) -> str:
    values: list[str] = []
    for execution in executions:
        text, _, valid = _execution_executed_notional_evidence(execution)
        if not valid:
            return "0"
        values.append(text)
    return _decimal_sum_string(values)


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return dict(converted) if isinstance(converted, Mapping) else {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _coinbase_create_order_success(
    result: Any,
    data: Mapping[str, Any],
) -> bool | None:
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


def _coinbase_order_id(result: Any, data: Mapping[str, Any]) -> str | None:
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


def _coinbase_executed_notional_usdc(data: Mapping[str, Any]) -> str:
    for evidence in _coinbase_order_evidence_mappings(data):
        for field in (
            "executed_notional_usdc",
            "filled_value",
            "executed_value",
            "filled_quote_value",
            "filled_quote_size",
        ):
            try:
                decimal_value = Decimal(str(evidence.get(field)))
            except (InvalidOperation, ValueError):
                continue
            if decimal_value >= 0:
                return str(decimal_value)
    return "0"


def _coinbase_order_evidence_mappings(
    data: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    mappings: list[Mapping[str, Any]] = [data]
    for key in ("success_response", "order", "order_response"):
        value = data.get(key)
        if isinstance(value, Mapping):
            mappings.append(value)
    return mappings


def _cancel_result_success(result: Any) -> bool:
    if isinstance(result, bool):
        return result
    if isinstance(result, Mapping):
        success = result.get("success")
        if isinstance(success, bool):
            return success
    return bool(result)


def _cancel_result_to_dict(result: Any, *, client_order_id: str) -> dict[str, Any]:
    if isinstance(result, bool):
        return {"success": result, "client_order_id": client_order_id}
    data = _object_to_dict(result)
    if "success" not in data:
        data["success"] = _cancel_result_success(result)
    data.setdefault("client_order_id", client_order_id)
    return data
