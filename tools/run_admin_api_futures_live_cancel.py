"""Run one explicit US CFM Futures/Perpetual live cancel submission.

This tool is intentionally manual. It never submits a cancel to Coinbase unless
``--confirm-live-cancel`` is passed, and the request still flows through backend
Admin Futures service evidence, live-adapter decisions, runtime opt-in, and
audit recording before the REST client is called.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.mvp_service import (  # noqa: E402
    AdminMvpRequestContext,
    AdminMvpService,
    get_admin_mvp_service,
)
from tools.run_admin_api_futures_executor_boundary_smoke import (  # noqa: E402
    FUTURES_ACCOUNT_FAMILY,
    FUTURES_ADAPTER_DECISIONS,
    FUTURES_MODULE_ID,
    FUTURES_PRODUCT_ID,
    FUTURES_SERVICE_DECISION_ID,
    record_futures_live_adapter_decisions,
    record_futures_live_service_decision,
)
from tools.run_admin_api_futures_live_submit import (  # noqa: E402
    check,
    current_utc_timestamp,
    read_git_value,
    write_json,
)
from tools.run_admin_api_manual_order_live_submit import (  # noqa: E402
    LIVE_EXECUTION_ENV,
    apply_manual_live_submit_state_environment,
    apply_runner_environment,
    assert_live_credentials_present,
    default_state_dir,
)


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-futures-live-cancel.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_futures_live_cancel"
SCHEMA_VERSION = "1"


class LiveCancelConfirmationError(RuntimeError):
    """Raised when the live cancel confirmation flag is missing."""


@dataclass(frozen=True)
class FuturesLiveCancelConfig:
    """Operator-controlled inputs for one backend-owned Futures cancel."""

    confirm_live_cancel: bool = False
    state_dir: Path | None = None
    summary_output: Path = DEFAULT_SUMMARY_OUTPUT
    backend_contract_ref: str | None = None
    client_order_id: str | None = None
    product_id: str = FUTURES_PRODUCT_ID
    idempotency_key: str = "futures-live-cancel"
    correlation_id: str = "futures-live-cancel-correlation"
    actor_id: str = "local-operator"
    roles: tuple[str, ...] = ("admin", "trader")


def build_parser() -> argparse.ArgumentParser:
    """Create the Futures live cancel parser."""

    parser = argparse.ArgumentParser(
        description="Cancel one US CFM Futures order through backend Admin gates."
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument(
        "--backend-contract-ref",
        default=None,
        help="Backend contract ref to record. Defaults to the current git commit.",
    )
    parser.add_argument("--confirm-live-cancel", action="store_true")
    parser.add_argument("--client-order-id", required=True)
    parser.add_argument("--product-id", default=FUTURES_PRODUCT_ID)
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--actor-id", default="local-operator")
    parser.add_argument("--roles", default="admin,trader")
    return parser


def config_from_args(args: argparse.Namespace) -> FuturesLiveCancelConfig:
    """Return normalized Futures live cancel configuration."""

    run_id = str(int(time.time()))
    client_order_id = str(args.client_order_id).strip()
    idempotency_key = args.idempotency_key or f"futures-live-cancel-{run_id}"
    correlation_id = args.correlation_id or f"{idempotency_key}-correlation"
    roles = tuple(role.strip() for role in str(args.roles).split(",") if role.strip())
    return FuturesLiveCancelConfig(
        confirm_live_cancel=bool(args.confirm_live_cancel),
        state_dir=args.state_dir,
        summary_output=args.summary_output,
        backend_contract_ref=args.backend_contract_ref,
        client_order_id=client_order_id,
        product_id=str(args.product_id),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        actor_id=str(args.actor_id),
        roles=roles or ("admin", "trader"),
    )


def build_futures_live_cancel_body(
    config: FuturesLiveCancelConfig,
) -> dict[str, Any]:
    """Return the backend-controlled Futures cancel payload."""

    return {
        "product_id": config.product_id,
        "dry_run": False,
        "manual_live_acknowledgement": True,
        "operator_reason": "operator confirmed backend-controlled futures cancel",
    }


def run_futures_live_cancel(
    service: AdminMvpService,
    config: FuturesLiveCancelConfig,
) -> dict[str, Any]:
    """Record backend evidence, submit one live cancel, and summarize."""

    validate_futures_live_cancel_config(config)
    body = build_futures_live_cancel_body(config)
    started_at = current_utc_timestamp()
    started = time.perf_counter()

    live_service = record_futures_live_service_decision(service, config)
    adapters = record_futures_live_adapter_decisions(service, config)
    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        build_request_context(config, f"{config.idempotency_key}-suite-read"),
    )
    route = futures_live_cancel_route(config)
    final_submit = service.submit_futures_command(
        route,
        body,
        build_request_context(config, config.idempotency_key),
    )
    audit = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": FUTURES_MODULE_ID, "client_order_id": config.client_order_id},
        build_request_context(config, f"{config.idempotency_key}-audit-read"),
    )

    return build_summary(
        config=config,
        body=body,
        route=route,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        live_service=live_service,
        adapters=adapters,
        command_suite=command_suite.body,
        final_submit=final_submit.body,
        final_status_code=final_submit.status_code,
        audit_workbench=audit.body,
    )


def validate_futures_live_cancel_config(config: FuturesLiveCancelConfig) -> None:
    """Validate Futures live-cancel operator inputs."""

    if not config.confirm_live_cancel:
        raise LiveCancelConfirmationError(
            "Futures live cancel requires --confirm-live-cancel."
        )
    if not text_value(config.client_order_id):
        raise ValueError("client_order_id is required.")
    if "/" in text_value(config.client_order_id):
        raise ValueError("client_order_id cannot contain '/'.")
    if not text_value(config.product_id):
        raise ValueError("product_id is required.")


def futures_live_cancel_route(config: FuturesLiveCancelConfig) -> str:
    """Return the Admin Futures cancel route for the client_order_id."""

    return f"/api/v1/futures/orders/{config.client_order_id}/cancel"


def build_request_context(
    config: FuturesLiveCancelConfig,
    idempotency_key: str,
) -> AdminMvpRequestContext:
    """Return Admin request context for one cancel phase."""

    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id=config.correlation_id,
        operator_intent="futures_live_cancel",
        actor_id=config.actor_id,
        roles=config.roles,
    )


def build_summary(
    *,
    config: FuturesLiveCancelConfig,
    body: Mapping[str, Any],
    route: str,
    started_at: str,
    duration_seconds: float,
    live_service: Any,
    adapters: Sequence[Any],
    command_suite: Mapping[str, Any],
    final_submit: Mapping[str, Any],
    final_status_code: int,
    audit_workbench: Mapping[str, Any],
) -> dict[str, Any]:
    """Return redacted Futures cancel evidence."""

    submitted_notional = zero_normalized_decimal_text(
        final_submit.get("submitted_notional_usdc") or "0"
    )
    notional = zero_normalized_decimal_text(
        final_submit.get("notional_usdc") or submitted_notional
    )
    cancel_result = object_record(final_submit.get("coinbase_cancel_result"))
    checks = futures_live_cancel_checks(
        config=config,
        body=body,
        live_service=live_service,
        adapters=adapters,
        command_suite=command_suite,
        final_submit=final_submit,
        final_status_code=final_status_code,
        audit_workbench=audit_workbench,
        notional_usdc=notional,
        cancel_result=cancel_result,
    )
    status = "passed" if all(item["passed"] for item in checks) else "failed"
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "status": status,
        "started_at": started_at,
        "ended_at": current_utc_timestamp(),
        "duration_seconds": round(max(duration_seconds, 0), 3),
        "wait_sleep_seconds": 0,
        "backend_git_commit": read_git_value(["rev-parse", "--short", "HEAD"]),
        "backend_git_branch": read_git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "backend_contract_ref": config.backend_contract_ref
        or read_git_value(["rev-parse", "--short", "HEAD"]),
        "confirm_live_cancel": config.confirm_live_cancel,
        "state_dir": str(config.state_dir) if config.state_dir else None,
        "route": route,
        "product_id": body.get("product_id"),
        "account_family": FUTURES_ACCOUNT_FAMILY,
        "client_order_id": text_value(config.client_order_id),
        "service_decision_id": FUTURES_SERVICE_DECISION_ID,
        "service_decision_status": getattr(live_service, "body", {}).get("status"),
        "adapter_decision_ids": [item[0] for item in FUTURES_ADAPTER_DECISIONS],
        "adapter_decision_count": len(adapters),
        "command_suite_status": command_suite.get("status"),
        "command_routes_mode": command_suite.get("command_routes_mode"),
        "missing_backend_contracts": command_suite.get("missing_backend_contracts"),
        "final_status": final_submit.get("status"),
        "final_status_code": final_status_code,
        "failure_stage": final_submit.get("failure_stage"),
        "message": final_submit.get("message"),
        "submission_event_id": final_submit.get("submission_event_id"),
        "coinbase_cancel_submission_allowed": bool(
            final_submit.get("coinbase_cancel_submission_allowed")
        ),
        "cancel_result_present": bool(cancel_result),
        "cancel_result_success": cancel_result_succeeded(cancel_result),
        "cancel_result_item_count": cancel_result_item_count(cancel_result),
        "live_exchange_submitted": bool(final_submit.get("live_exchange_submitted")),
        "live_coinbase_orders_ran": bool(final_submit.get("live_coinbase_orders_ran")),
        "live_coinbase_execution": final_submit.get(
            "live_coinbase_execution",
            "not_run",
        ),
        "submitted_notional_usdc": submitted_notional,
        "notional_usdc": notional,
        "executed_notional_usdc": zero_normalized_decimal_text(
            final_submit.get("executed_notional_usdc") or "0"
        ),
        "exchange_order_id_evidence_only": bool(
            final_submit.get("exchange_order_id_evidence_only")
        ),
        "audit_event_count": audit_workbench.get("count"),
        "checks": checks,
    }


def futures_live_cancel_checks(
    *,
    config: FuturesLiveCancelConfig,
    body: Mapping[str, Any],
    live_service: Any,
    adapters: Sequence[Any],
    command_suite: Mapping[str, Any],
    final_submit: Mapping[str, Any],
    final_status_code: int,
    audit_workbench: Mapping[str, Any],
    notional_usdc: str,
    cancel_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return pass/fail checks for the Futures live-cancel artifact."""

    return [
        check("futures_confirm_live_cancel_requested", config.confirm_live_cancel),
        check("futures_client_order_id_present", bool(text_value(config.client_order_id))),
        check("futures_cancel_product_id_present", bool(text_value(body.get("product_id")))),
        check("futures_cancel_acknowledged", body.get("manual_live_acknowledgement") is True),
        check("futures_cancel_notional_zero", decimal_text_is_zero(notional_usdc)),
        check("futures_live_service_recorded", getattr(live_service, "status_code", 0) == 200),
        check(
            "futures_live_adapters_recorded",
            len(adapters) == len(FUTURES_ADAPTER_DECISIONS)
            and all(getattr(result, "status_code", 0) == 200 for result in adapters),
        ),
        check(
            "futures_command_suite_evidence_ready",
            command_suite.get("status") == "evidence_ready",
        ),
        check(
            "futures_command_suite_no_missing_contracts",
            command_suite.get("missing_backend_contracts") == [],
        ),
        check(
            "futures_live_cancel_accepted",
            final_status_code == 200 and final_submit.get("status") == "accepted",
        ),
        check(
            "futures_cancel_submission_allowed",
            final_submit.get("coinbase_cancel_submission_allowed") is True,
        ),
        check("futures_cancel_result_success", cancel_result_succeeded(cancel_result)),
        check(
            "futures_live_exchange_submitted",
            final_submit.get("live_exchange_submitted") is True,
        ),
        check(
            "futures_live_coinbase_execution_submitted",
            final_submit.get("live_coinbase_execution") == "submitted",
        ),
        check(
            "futures_exchange_order_id_evidence_only",
            final_submit.get("exchange_order_id_evidence_only") is True,
        ),
        check("futures_audit_workbench_readback", audit_workbench.get("count", 0) >= 1),
    ]


def cancel_result_succeeded(result: Mapping[str, Any]) -> bool:
    """Return whether a Coinbase cancel result reports success."""

    if not result:
        return False
    success = result.get("success")
    if success is not None:
        return truthy_value(success)
    results = result.get("results")
    if isinstance(results, Sequence) and not isinstance(results, (str, bytes, bytearray)):
        items = [object_record(item) for item in results]
        return bool(items) and all(cancel_result_item_succeeded(item) for item in items)
    return bool(result)


def cancel_result_item_succeeded(item: Mapping[str, Any]) -> bool:
    """Return whether one Coinbase cancel result item reports success."""

    success = item.get("success")
    return bool(item) if success is None else truthy_value(success)


def cancel_result_item_count(result: Mapping[str, Any]) -> int:
    """Return the number of cancel result records."""

    results = result.get("results")
    if isinstance(results, Sequence) and not isinstance(results, (str, bytes, bytearray)):
        return len(results)
    return 1 if result else 0


def truthy_value(value: Any) -> bool:
    """Return a permissive boolean for Coinbase success-like values."""

    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def zero_normalized_decimal_text(value: Any) -> str:
    """Return decimal text with all zero values normalized to ``0``."""

    text = text_value(value)
    return "0" if decimal_text_is_zero(text) else text


def decimal_text_is_zero(value: Any) -> bool:
    """Return whether a value is numeric zero."""

    try:
        return Decimal(text_value(value)) == Decimal("0")
    except (InvalidOperation, ValueError):
        return False


def object_record(value: Any) -> dict[str, Any]:
    """Return value as a mapping or an empty dict."""

    return dict(value) if isinstance(value, Mapping) else {}


def text_value(value: Any) -> str:
    """Return stripped text."""

    return str(value or "").strip()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the explicit Futures live cancel and write evidence."""

    config = config_from_args(build_parser().parse_args(argv))
    if not config.confirm_live_cancel:
        raise LiveCancelConfirmationError(
            "Futures live cancel requires --confirm-live-cancel."
        )
    assert_live_credentials_present(os.environ)
    if config.state_dir:
        apply_manual_live_submit_state_environment(config.state_dir)
    os.environ[LIVE_EXECUTION_ENV] = "1"
    apply_runner_environment()
    summary = run_futures_live_cancel(get_admin_mvp_service(), config)
    write_json(config.summary_output, summary)
    print(
        "Backend Futures live cancel: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"client_order_id {summary['client_order_id']}; "
        f"artifact {config.summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
