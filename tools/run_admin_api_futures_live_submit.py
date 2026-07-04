"""Run one explicit capped US CFM Futures/Perpetual live submission.

This tool is intentionally manual. It never submits to Coinbase unless
``--confirm-live-submit`` is passed, and the order still flows through the
backend Admin Futures service, live-service decision, live-adapter decisions,
runtime opt-in, cap evidence, and audit recording before the REST client is
called.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
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
    FUTURES_COMMAND_ROUTE,
    FUTURES_MODULE_ID,
    FUTURES_PRODUCT_ID,
    FUTURES_SERVICE_DECISION_ID,
    record_futures_live_adapter_decisions,
    record_futures_live_service_decision,
)
from tools.run_admin_api_manual_order_live_submit import (  # noqa: E402
    LIVE_EXECUTION_ENV,
    LiveSubmitConfirmationError,
    apply_manual_live_submit_state_environment,
    apply_runner_environment,
    assert_live_credentials_present,
    decimal_text,
    decimal_value,
    default_state_dir,
)


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-futures-live-submit.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_futures_live_submit"
SCHEMA_VERSION = "1"
DEFAULT_LIMIT_PRICE = "1"
DEFAULT_SIZE = "1"
MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC = "3.10"
MAX_DEFAULT_EXECUTED_NOTIONAL_USDC = "1.00"
MIN_DEFAULT_NOTIONAL_USDC = "1.00"


@dataclass(frozen=True)
class FuturesLiveSubmitConfig:
    """Operator-controlled inputs for one bounded Futures live submission."""

    confirm_live_submit: bool = False
    state_dir: Path | None = None
    summary_output: Path = DEFAULT_SUMMARY_OUTPUT
    backend_contract_ref: str | None = None
    product_id: str = FUTURES_PRODUCT_ID
    limit_price: str = DEFAULT_LIMIT_PRICE
    size: str = DEFAULT_SIZE
    idempotency_key: str = "futures-live-submit"
    correlation_id: str = "futures-live-submit-correlation"
    actor_id: str = "local-operator"
    roles: tuple[str, ...] = ("admin", "trader")
    max_submitted_notional_usdc: str = MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC
    max_executed_notional_usdc: str = MAX_DEFAULT_EXECUTED_NOTIONAL_USDC
    leverage: str | None = None
    margin_type: str | None = None
    retail_portfolio_id: str | None = None


def build_parser() -> argparse.ArgumentParser:
    """Create the Futures live-submit parser."""

    parser = argparse.ArgumentParser(
        description="Submit one capped US CFM Futures order through backend Admin gates."
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument(
        "--backend-contract-ref",
        default=None,
        help="Backend contract ref to record. Defaults to the current git commit.",
    )
    parser.add_argument("--confirm-live-submit", action="store_true")
    parser.add_argument("--product-id", default=FUTURES_PRODUCT_ID)
    parser.add_argument("--limit-price", default=DEFAULT_LIMIT_PRICE)
    parser.add_argument("--size", default=DEFAULT_SIZE)
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--actor-id", default="local-operator")
    parser.add_argument("--roles", default="admin,trader")
    parser.add_argument(
        "--max-submitted-notional-usdc",
        default=MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC,
    )
    parser.add_argument(
        "--max-executed-notional-usdc",
        default=MAX_DEFAULT_EXECUTED_NOTIONAL_USDC,
    )
    parser.add_argument("--leverage", default=None)
    parser.add_argument("--margin-type", default=None)
    parser.add_argument("--retail-portfolio-id", default=None)
    return parser


def config_from_args(args: argparse.Namespace) -> FuturesLiveSubmitConfig:
    """Return normalized Futures live-submit configuration."""

    run_id = str(int(time.time()))
    idempotency_key = args.idempotency_key or f"futures-live-submit-{run_id}"
    correlation_id = args.correlation_id or f"{idempotency_key}-correlation"
    roles = tuple(role.strip() for role in str(args.roles).split(",") if role.strip())
    return FuturesLiveSubmitConfig(
        confirm_live_submit=bool(args.confirm_live_submit),
        state_dir=args.state_dir,
        summary_output=args.summary_output,
        backend_contract_ref=args.backend_contract_ref,
        product_id=str(args.product_id),
        limit_price=str(args.limit_price),
        size=str(args.size),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        actor_id=str(args.actor_id),
        roles=roles or ("admin", "trader"),
        max_submitted_notional_usdc=str(args.max_submitted_notional_usdc),
        max_executed_notional_usdc=str(args.max_executed_notional_usdc),
        leverage=optional_text(args.leverage),
        margin_type=optional_text(args.margin_type),
        retail_portfolio_id=optional_text(args.retail_portfolio_id),
    )


def build_futures_live_submit_body(config: FuturesLiveSubmitConfig) -> dict[str, Any]:
    """Return the bounded buy-limit Futures place payload."""

    body: dict[str, Any] = {
        "product_id": config.product_id,
        "side": "BUY",
        "order_type": "LIMIT",
        "limit_price": decimal_text(config.limit_price),
        "size": decimal_text(config.size),
        "post_only": False,
        "dry_run": False,
        "manual_live_acknowledgement": True,
    }
    for field, value in {
        "leverage": config.leverage,
        "margin_type": config.margin_type,
        "retail_portfolio_id": config.retail_portfolio_id,
    }.items():
        if value:
            body[field] = value
    return body


def run_futures_live_submit(
    service: AdminMvpService,
    config: FuturesLiveSubmitConfig,
) -> dict[str, Any]:
    """Record backend evidence, submit one live Futures order, and summarize."""

    validate_futures_live_submit_config(config)
    body = build_futures_live_submit_body(config)
    started_at = current_utc_timestamp()
    started = time.perf_counter()

    live_service = record_futures_live_service_decision(service, config)
    adapters = record_futures_live_adapter_decisions(service, config)
    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        build_request_context(config, f"{config.idempotency_key}-suite-read"),
    )
    final_submit = service.submit_futures_command(
        FUTURES_COMMAND_ROUTE,
        body,
        build_request_context(config, config.idempotency_key),
    )
    audit = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": FUTURES_MODULE_ID},
        build_request_context(config, f"{config.idempotency_key}-audit-read"),
    )

    return build_summary(
        config=config,
        body=body,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        live_service=live_service,
        adapters=adapters,
        command_suite=command_suite.body,
        final_submit=final_submit.body,
        final_status_code=final_submit.status_code,
        audit_workbench=audit.body,
    )


def validate_futures_live_submit_config(config: FuturesLiveSubmitConfig) -> None:
    """Validate bounded Futures live-submission operator inputs."""

    if not config.confirm_live_submit:
        raise LiveSubmitConfirmationError(
            "Futures live submission requires --confirm-live-submit."
        )
    limit_price = decimal_value(config.limit_price)
    size = decimal_value(config.size)
    if limit_price <= 0:
        raise ValueError("limit_price must be greater than zero.")
    if size <= 0:
        raise ValueError("size must be greater than zero.")
    notional = futures_notional_usdc(config)
    if notional < decimal_value(MIN_DEFAULT_NOTIONAL_USDC):
        raise ValueError("Futures live submit notional must be at least 1.00 USDC.")
    if notional > decimal_value(config.max_submitted_notional_usdc):
        raise ValueError(
            "Futures live submit notional must not exceed max_submitted_notional_usdc."
        )


def build_request_context(
    config: FuturesLiveSubmitConfig,
    idempotency_key: str,
) -> AdminMvpRequestContext:
    """Return Admin request context for one Futures live-submit phase."""

    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id=config.correlation_id,
        operator_intent="futures_live_submit",
        actor_id=config.actor_id,
        roles=config.roles,
    )


def build_summary(
    *,
    config: FuturesLiveSubmitConfig,
    body: Mapping[str, Any],
    started_at: str,
    duration_seconds: float,
    live_service: Any,
    adapters: Sequence[Any],
    command_suite: Mapping[str, Any],
    final_submit: Mapping[str, Any],
    final_status_code: int,
    audit_workbench: Mapping[str, Any],
) -> dict[str, Any]:
    """Return redacted Futures live-submit evidence."""

    submitted_notional = str(
        final_submit.get("submitted_notional_usdc") or decimal_text(futures_notional_usdc(config))
    )
    notional = str(final_submit.get("notional_usdc") or submitted_notional)
    checks = futures_live_submit_checks(
        config=config,
        body=body,
        live_service=live_service,
        adapters=adapters,
        command_suite=command_suite,
        final_submit=final_submit,
        final_status_code=final_status_code,
        audit_workbench=audit_workbench,
        notional_usdc=notional,
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
        "confirm_live_submit": config.confirm_live_submit,
        "state_dir": str(config.state_dir) if config.state_dir else None,
        "product_id": body.get("product_id"),
        "account_family": FUTURES_ACCOUNT_FAMILY,
        "side": body.get("side"),
        "order_type": body.get("order_type"),
        "limit_price": body.get("limit_price"),
        "size": body.get("size"),
        "max_submitted_notional_usdc": config.max_submitted_notional_usdc,
        "max_executed_notional_usdc": config.max_executed_notional_usdc,
        "client_order_id": str(final_submit.get("client_order_id") or ""),
        "exchange_order_id_present": bool(
            final_submit.get("exchange_order_id") or final_submit.get("coinbase_order_id")
        ),
        "exchange_order_id_evidence_only": bool(
            final_submit.get("exchange_order_id_evidence_only")
        ),
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
        "live_exchange_submitted": bool(final_submit.get("live_exchange_submitted")),
        "live_coinbase_orders_ran": bool(final_submit.get("live_coinbase_orders_ran")),
        "live_coinbase_execution": final_submit.get("live_coinbase_execution", "not_run"),
        "submitted_notional_usdc": submitted_notional,
        "notional_usdc": notional,
        "paired_sell_required": False,
        "audit_event_count": audit_workbench.get("count"),
        "checks": checks,
    }


def futures_live_submit_checks(
    *,
    config: FuturesLiveSubmitConfig,
    body: Mapping[str, Any],
    live_service: Any,
    adapters: Sequence[Any],
    command_suite: Mapping[str, Any],
    final_submit: Mapping[str, Any],
    final_status_code: int,
    audit_workbench: Mapping[str, Any],
    notional_usdc: str,
) -> list[dict[str, Any]]:
    """Return pass/fail checks for the Futures live-submit artifact."""

    notional = decimal_value(notional_usdc)
    return [
        check("futures_confirm_live_submit_requested", config.confirm_live_submit),
        check("futures_buy_order_only", body.get("side") == "BUY"),
        check("futures_limit_order_required", body.get("order_type") == "LIMIT"),
        check(
            "futures_notional_within_runner_bounds",
            decimal_value(MIN_DEFAULT_NOTIONAL_USDC)
            <= notional
            <= decimal_value(config.max_submitted_notional_usdc),
        ),
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
            "futures_live_submit_accepted",
            final_status_code == 200 and final_submit.get("status") == "accepted",
        ),
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
        check("futures_no_paired_sell_required", True),
        check("futures_audit_workbench_readback", audit_workbench.get("count", 0) >= 1),
    ]


def check(name: str, passed: bool) -> dict[str, Any]:
    """Return one readiness check row."""

    return {"name": name, "passed": bool(passed)}


def futures_notional_usdc(config: FuturesLiveSubmitConfig) -> Decimal:
    """Return the submitted Futures notional for this runner config."""

    return decimal_value(config.size) * decimal_value(config.limit_price)


def optional_text(value: object) -> str | None:
    """Return a stripped optional string."""

    text = str(value or "").strip()
    return text or None


def current_utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_git_value(args: Sequence[str], fallback: str = "unknown") -> str:
    """Return a git value or fallback when unavailable."""

    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except FileNotFoundError:
        return fallback
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else fallback


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write stable JSON evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the explicit Futures live submit and write evidence."""

    config = config_from_args(build_parser().parse_args(argv))
    if not config.confirm_live_submit:
        raise LiveSubmitConfirmationError(
            "Futures live submission requires --confirm-live-submit."
        )
    assert_live_credentials_present(os.environ)
    if config.state_dir:
        apply_manual_live_submit_state_environment(config.state_dir)
    os.environ[LIVE_EXECUTION_ENV] = "1"
    apply_runner_environment()
    summary = run_futures_live_submit(get_admin_mvp_service(), config)
    write_json(config.summary_output, summary)
    print(
        "Backend Futures live submit: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"notional {summary['notional_usdc']} USDC; "
        f"artifact {config.summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
