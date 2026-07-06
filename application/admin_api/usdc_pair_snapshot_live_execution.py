"""Backend-only controlled-live executor for M58 USDC snapshot order plans."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Mapping

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
        live_execution = (
            "submitted_cancelled"
            if cancel_submitted
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
            "executed_notional_usdc": "0",
            "submitted_notional_usdc": submitted_notional_usdc,
            "max_executed_notional_usdc": max_executed_notional_usdc,
            "cancel_submitted": cancel_submitted,
            "cancel_rollback_complete": cancel_submitted,
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
