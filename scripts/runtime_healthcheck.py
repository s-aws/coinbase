#!/usr/bin/env python3.14
"""Wait for the dashboard runtime authority to report a safe paused state."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from typing import Any
from uuid import uuid4

from websockets import connect
from websockets.exceptions import WebSocketException

from core.enums import EngineState, OperatorOutcome, OperatorRpcMethod


def _positive_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "timeout must be a number"
        ) from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and greater than zero")
    return timeout


def _default_healthcheck_url() -> str:
    configured = os.getenv("DEPLOYMENT_HEALTHCHECK_URL")
    if configured:
        return configured
    port = os.getenv("DASHBOARD_SERVER_PORT", "8765")
    return f"ws://127.0.0.1:{port}"


def validate_paused_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the stable health fields or raise for an unsafe response."""

    if payload.get("outcome") != OperatorOutcome.SUCCEEDED.value:
        raise RuntimeError("operator status result was not successful")
    if payload.get("engine_state") != EngineState.PAUSED.value:
        raise RuntimeError(
            "engine is not paused: "
            f"state={payload.get('engine_state')!r}"
        )
    if payload.get("is_admitting") is not False:
        raise RuntimeError("paused engine is unexpectedly admitting work")
    if payload.get("is_stopping") is not False:
        raise RuntimeError("paused engine is unexpectedly stopping")
    if payload.get("startup_pause_pending") is not False:
        raise RuntimeError("startup pause has not reached its stable PAUSED state")
    if payload.get("total_inflight") != 0:
        raise RuntimeError(
            "paused engine still has in-flight work: "
            f"{payload.get('total_inflight')!r}"
        )
    return {
        "engine_state": payload["engine_state"],
        "is_admitting": payload["is_admitting"],
        "is_stopping": payload["is_stopping"],
        "startup_pause_pending": payload["startup_pause_pending"],
        "total_inflight": payload["total_inflight"],
    }


def summarize_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the administrative fields needed for a pre-start probe."""

    if payload.get("outcome") != OperatorOutcome.SUCCEEDED.value:
        raise RuntimeError("operator status result was not successful")
    return {
        "engine_state": payload.get("engine_state"),
        "is_admitting": payload.get("is_admitting"),
        "is_stopping": payload.get("is_stopping"),
        "startup_pause_pending": payload.get("startup_pause_pending"),
        "total_inflight": payload.get("total_inflight"),
    }


async def _request_status(url: str, timeout_seconds: float) -> dict[str, Any]:
    per_operation_timeout = min(2.0, timeout_seconds)
    request_id = str(uuid4())
    async with connect(
        url,
        open_timeout=per_operation_timeout,
        close_timeout=1.0,
    ) as websocket:
        await asyncio.wait_for(
            websocket.send(json.dumps({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": OperatorRpcMethod.RUNTIME_STATUS.value,
                "params": {},
            })),
            timeout=per_operation_timeout,
        )
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("correlated runtime status was not received")
            raw_message = await asyncio.wait_for(
                websocket.recv(),
                timeout=min(per_operation_timeout, remaining),
            )
            try:
                payload = json.loads(raw_message)
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("jsonrpc") != "2.0" or payload.get("id") != request_id:
                continue
            if "error" in payload:
                error = payload.get("error") or {}
                raise RuntimeError(
                    "operator status request failed: "
                    f"{error.get('message', 'unknown JSON-RPC error')}"
                )
            result = payload.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("operator status response omitted its result")
            return result


async def wait_for_paused_runtime(
    url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Poll until startup reaches stable PAUSED or the deadline expires."""

    if not url.startswith(("ws://", "wss://")):
        raise ValueError("healthcheck URL must use ws:// or wss://")

    deadline = time.monotonic() + timeout_seconds
    last_detail = "dashboard has not accepted a connection"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "runtime did not reach stable PAUSED before timeout; "
                f"last observation: {last_detail}"
            )
        try:
            payload = await _request_status(url, min(remaining, 2.0))
            state = payload.get("engine_state")
            if state == EngineState.PAUSED.value:
                try:
                    return validate_paused_status(payload)
                except RuntimeError as exc:
                    last_detail = str(exc)
            elif state == EngineState.STARTING.value:
                last_detail = "engine is still STARTING"
            else:
                raise RuntimeError(
                    "runtime entered an unsafe state before paused health: "
                    f"{state!r}"
                )
        except (OSError, TimeoutError, asyncio.TimeoutError, WebSocketException) as exc:
            last_detail = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(min(0.25, max(0.0, deadline - time.monotonic())))


async def wait_for_runtime_status(
    url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Wait for any valid administrative status response."""

    if not url.startswith(("ws://", "wss://")):
        raise ValueError("healthcheck URL must use ws:// or wss://")

    deadline = time.monotonic() + timeout_seconds
    last_detail = "dashboard has not accepted a connection"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "runtime status probe timed out; "
                f"last observation: {last_detail}"
            )
        try:
            payload = await _request_status(url, min(remaining, 2.0))
            return summarize_status(payload)
        except (OSError, TimeoutError, asyncio.TimeoutError, WebSocketException) as exc:
            last_detail = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(min(0.25, max(0.0, deadline - time.monotonic())))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for operator runtime status to report stable PAUSED health.",
    )
    parser.add_argument("--url", default=_default_healthcheck_url())
    parser.add_argument(
        "--probe",
        action="store_true",
        help="return the first valid admin status without requiring PAUSED",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=_positive_timeout,
        default=os.getenv("DEPLOYMENT_HEALTH_TIMEOUT_SECONDS", "60"),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        if args.probe:
            status = asyncio.run(
                wait_for_runtime_status(args.url, args.timeout_seconds)
            )
        else:
            status = asyncio.run(
                wait_for_paused_runtime(args.url, args.timeout_seconds)
            )
    except (RuntimeError, TimeoutError, ValueError) as exc:
        raise SystemExit(f"runtime healthcheck: {exc}") from exc
    print(json.dumps(status, sort_keys=True))


if __name__ == "__main__":
    main()
