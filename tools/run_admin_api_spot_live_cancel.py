"""Run one explicit backend-owned Spot live cancel submission.

This tool is intentionally manual. It never submits a cancel to Coinbase unless
``--confirm-live-cancel`` is passed, and the request still flows through backend
Admin proof-chain evidence, live-service evidence, runtime opt-in, and audit
recording before the REST client is called.
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
    CANCEL_ORDER_ACTION_CLASS,
    CANCEL_ORDER_PERMISSION,
    CANCEL_ORDER_ROUTE,
    CANCEL_ORDER_SERVICE_METHOD,
    MANUAL_ORDER_MODULE_ID,
    MANUAL_ORDER_ROUTE,
    MANUAL_ORDER_SERVICE_METHOD,
    AdminMvpRequestContext,
    AdminMvpService,
    _payload_hash,
    get_admin_mvp_service,
)
from tools.run_admin_api_manual_order_live_submit import (  # noqa: E402
    LIVE_EXECUTION_ENV,
    MAX_DEFAULT_EXECUTED_NOTIONAL_USDC,
    MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC,
    apply_manual_live_submit_state_environment,
    apply_runner_environment,
    assert_live_credentials_present,
    current_utc_timestamp,
    default_state_dir,
    read_git_value,
    write_json,
)


DEFAULT_SUMMARY_OUTPUT = Path("artifacts") / "coinbase-backend-spot-live-cancel.json"
ARTIFACT_TYPE = "coinbase_admin_api_spot_live_cancel"
SCHEMA_VERSION = "1"
DEFAULT_SEED_PRODUCT_ID = "USDT-USDC"
DEFAULT_SEED_SIDE = "BUY"
DEFAULT_SEED_BASE_SIZE = "2.00"
DEFAULT_SEED_LIMIT_PRICE = "0.9980"
DEFAULT_SEED_TIME_IN_FORCE = "GTC"


class LiveCancelConfirmationError(RuntimeError):
    """Raised when the live cancel confirmation flag is missing."""


@dataclass(frozen=True)
class SpotLiveCancelConfig:
    """Operator-controlled inputs for one backend-owned Spot cancel."""

    confirm_live_cancel: bool = False
    seed_resting_order: bool = False
    client_order_id: str | None = None
    seed_product_id: str = DEFAULT_SEED_PRODUCT_ID
    seed_side: str = DEFAULT_SEED_SIDE
    seed_base_size: str = DEFAULT_SEED_BASE_SIZE
    seed_limit_price: str = DEFAULT_SEED_LIMIT_PRICE
    seed_time_in_force: str = DEFAULT_SEED_TIME_IN_FORCE
    seed_post_only: bool = True
    seed_max_submitted_notional_usdc: str = MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC
    seed_max_executed_notional_usdc: str = MAX_DEFAULT_EXECUTED_NOTIONAL_USDC
    idempotency_key: str = "spot-live-cancel"
    correlation_id: str = "spot-live-cancel-correlation"
    actor_id: str = "local-operator"
    roles: tuple[str, ...] = ("admin", "trader")
    backend_contract_ref: str | None = None
    state_dir: Path | None = None
    summary_output: Path = DEFAULT_SUMMARY_OUTPUT


def build_parser() -> argparse.ArgumentParser:
    """Create the Spot live-cancel parser."""

    parser = argparse.ArgumentParser(
        description="Cancel one Spot order through backend Admin gates."
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument(
        "--backend-contract-ref",
        default=None,
        help="Backend contract ref to record. Defaults to the current git commit.",
    )
    parser.add_argument("--confirm-live-cancel", action="store_true")
    parser.add_argument(
        "--seed-resting-order",
        action="store_true",
        help=(
            "Seed a small far-from-market GTC Spot order through Admin gates, "
            "then cancel that client_order_id."
        ),
    )
    parser.add_argument("--client-order-id", default=None)
    parser.add_argument("--seed-product-id", default=DEFAULT_SEED_PRODUCT_ID)
    parser.add_argument("--seed-side", choices=("BUY", "SELL"), default=DEFAULT_SEED_SIDE)
    parser.add_argument("--seed-base-size", default=DEFAULT_SEED_BASE_SIZE)
    parser.add_argument("--seed-limit-price", default=DEFAULT_SEED_LIMIT_PRICE)
    parser.add_argument("--seed-time-in-force", default=DEFAULT_SEED_TIME_IN_FORCE)
    parser.add_argument(
        "--seed-post-only",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--seed-max-submitted-notional-usdc",
        default=MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC,
    )
    parser.add_argument(
        "--seed-max-executed-notional-usdc",
        default=MAX_DEFAULT_EXECUTED_NOTIONAL_USDC,
    )
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--actor-id", default="local-operator")
    parser.add_argument("--roles", default="admin,trader")
    return parser


def config_from_args(args: argparse.Namespace) -> SpotLiveCancelConfig:
    """Return normalized Spot live-cancel configuration."""

    run_id = str(int(time.time()))
    idempotency_key = args.idempotency_key or f"spot-live-cancel-{run_id}"
    correlation_id = args.correlation_id or f"{idempotency_key}-correlation"
    roles = tuple(role.strip() for role in str(args.roles).split(",") if role.strip())
    return SpotLiveCancelConfig(
        confirm_live_cancel=bool(args.confirm_live_cancel),
        seed_resting_order=bool(args.seed_resting_order),
        client_order_id=text_value(args.client_order_id),
        seed_product_id=str(args.seed_product_id),
        seed_side=str(args.seed_side),
        seed_base_size=str(args.seed_base_size),
        seed_limit_price=str(args.seed_limit_price),
        seed_time_in_force=str(args.seed_time_in_force),
        seed_post_only=bool(args.seed_post_only),
        seed_max_submitted_notional_usdc=str(args.seed_max_submitted_notional_usdc),
        seed_max_executed_notional_usdc=str(args.seed_max_executed_notional_usdc),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        actor_id=str(args.actor_id),
        roles=roles or ("admin", "trader"),
        backend_contract_ref=args.backend_contract_ref,
        state_dir=args.state_dir,
        summary_output=args.summary_output,
    )


def build_spot_live_cancel_body(
    config: SpotLiveCancelConfig,
    client_order_id: str | None = None,
) -> dict[str, Any]:
    """Return the backend-controlled Spot cancel payload."""

    resolved_client_order_id = (
        text_value(client_order_id) or spot_cancel_target_client_order_id(config)
    )
    body = {
        "reason": "operator_requested_cancel",
        "operator_reason": "operator confirmed backend-controlled spot cancel",
        "manual_live_acknowledgement": True,
    }
    return {
        **body,
        "payload_hash": _payload_hash(
            {"client_order_id": resolved_client_order_id, **body}
        ),
    }


def run_spot_live_cancel(
    service: AdminMvpService,
    config: SpotLiveCancelConfig,
) -> dict[str, Any]:
    """Record backend evidence, submit one live cancel, and summarize."""

    validate_spot_live_cancel_config(config)
    seed_order: dict[str, Any] = {}
    client_order_id = spot_cancel_target_client_order_id(config)
    started_at = current_utc_timestamp()
    started = time.perf_counter()

    if config.seed_resting_order:
        seed_order = submit_spot_cancel_seed_order(service, config)
        client_order_id = seed_order_client_order_id(seed_order)
        if not seed_order_accepted(seed_order):
            command_suite = service.get_read_response(
                "/api/v1/spot/command-suite",
                {"client_order_id": client_order_id},
                build_request_context(config, f"{config.idempotency_key}-suite-read"),
            )
            audit = service.get_read_response(
                "/api/v1/admin/audit-workbench",
                {"module": "spot", "client_order_id": client_order_id},
                build_request_context(config, f"{config.idempotency_key}-audit-read"),
            )
            return build_summary(
                config=config,
                body=build_spot_live_cancel_body(config, client_order_id),
                seed_order=seed_order,
                started_at=started_at,
                duration_seconds=time.perf_counter() - started,
                live_decision={},
                proof_chain={},
                final_cancel=skipped_cancel_after_seed_failure(client_order_id),
                final_status_code=0,
                command_suite=command_suite.body,
                audit_workbench=audit.body,
            )

    body = build_spot_live_cancel_body(config, client_order_id)
    live_decision = record_spot_cancel_live_service_decision(service, config)
    proof_chain = service.record_spot_cancel_order_proof_chain(
        build_spot_cancel_proof_context(config, body, client_order_id),
        build_request_context(config, f"{config.idempotency_key}-proof-chain"),
    )
    final_cancel = service.cancel_order_by_client_order_id(
        client_order_id,
        body,
        build_request_context(config, config.idempotency_key),
    )
    command_suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        {"client_order_id": client_order_id},
        build_request_context(config, f"{config.idempotency_key}-suite-read"),
    )
    audit = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "spot", "client_order_id": client_order_id},
        build_request_context(config, f"{config.idempotency_key}-audit-read"),
    )

    return build_summary(
        config=config,
        body=body,
        seed_order=seed_order,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        live_decision=live_decision.body,
        proof_chain=proof_chain.body,
        final_cancel=final_cancel.body,
        final_status_code=final_cancel.status_code,
        command_suite=command_suite.body,
        audit_workbench=audit.body,
    )


def validate_spot_live_cancel_config(config: SpotLiveCancelConfig) -> None:
    """Validate Spot live-cancel operator inputs."""

    if not config.confirm_live_cancel:
        raise LiveCancelConfirmationError(
            "Spot live cancel requires --confirm-live-cancel."
        )
    client_order_id = spot_cancel_target_client_order_id(config)
    if not client_order_id and not config.seed_resting_order:
        raise ValueError("client_order_id is required unless --seed-resting-order is used.")
    if client_order_id and "/" in client_order_id:
        raise ValueError("client_order_id cannot contain '/'.")
    if config.seed_resting_order and text_value(config.client_order_id):
        raise ValueError(
            "client_order_id cannot be supplied with --seed-resting-order; "
            "the backend-generated seed order id is used for cancel."
        )
    if config.seed_resting_order:
        require_positive_decimal(config.seed_base_size, "seed_base_size")
        require_positive_decimal(config.seed_limit_price, "seed_limit_price")
        require_positive_decimal(
            config.seed_max_submitted_notional_usdc,
            "seed_max_submitted_notional_usdc",
        )
        require_positive_decimal(
            config.seed_max_executed_notional_usdc,
            "seed_max_executed_notional_usdc",
        )


def submit_spot_cancel_seed_order(
    service: AdminMvpService,
    config: SpotLiveCancelConfig,
) -> dict[str, Any]:
    """Submit one small resting Spot order that the cancel proof can target."""

    body = build_spot_cancel_seed_order_body(config)
    live_decision = record_spot_seed_live_service_decision(service, config)
    seed_context = build_seed_order_request_context(
        config,
        f"{config.idempotency_key}-seed-order",
    )
    first_submit = service.submit_manual_order(body, seed_context)
    admission = object_record(first_submit.body.get("admission_decision"))
    proof_chain_body: dict[str, Any] = {}
    final_submit = first_submit
    final_status_code = first_submit.status_code

    if admission:
        proof_chain = service.record_spot_manual_order_proof_chain(
            {
                "route": admission.get("route"),
                "method": admission.get("method"),
                "module_id": admission.get("module_id"),
                "identity_key": admission.get("identity_key"),
                "identity_value": admission.get("identity_value"),
                "action_class": admission.get("action_class"),
                "required_permission": admission.get("required_permission"),
                "service_method": admission.get("service_method"),
                "actor_id": admission.get("actor_id"),
                "operator_intent": admission.get("operator_intent"),
                "command_idempotency_key": admission.get("idempotency_key"),
                "payload_hash": admission.get("payload_hash"),
                "max_submitted_notional_usdc": config.seed_max_submitted_notional_usdc,
                "max_executed_notional_usdc": config.seed_max_executed_notional_usdc,
            },
            build_request_context(config, f"{config.idempotency_key}-seed-proof-chain"),
        )
        proof_chain_body = proof_chain.body
        final_submit = service.submit_manual_order(body, seed_context)
        final_status_code = final_submit.status_code

    return {
        "body": body,
        "client_order_id": seed_order_client_order_id_from_parts(
            final_submit.body,
            admission,
        ),
        "live_decision": live_decision.body,
        "first_submit": first_submit.body,
        "proof_chain": proof_chain_body,
        "final_submit": final_submit.body,
        "final_status_code": final_status_code,
    }


def build_spot_cancel_seed_order_body(
    config: SpotLiveCancelConfig,
) -> dict[str, Any]:
    """Return the resting Spot order payload used only to prove cancel."""

    return {
        "product_id": text_value(config.seed_product_id),
        "side": text_value(config.seed_side).upper(),
        "order_type": "LIMIT",
        "base_size": decimal_text(config.seed_base_size),
        "limit_price": decimal_text(config.seed_limit_price),
        "time_in_force": text_value(config.seed_time_in_force).upper() or "GTC",
        "post_only": bool(config.seed_post_only),
        "manual_live_acknowledgement": True,
    }


def record_spot_seed_live_service_decision(
    service: AdminMvpService,
    config: SpotLiveCancelConfig,
):
    """Record backend live-service evidence for the seed order route."""

    return service.record_live_service_decision(
        {
            "decision_id": f"{config.idempotency_key}-seed-live-service",
            "status": "passed",
            "requested_service_status": "approval_required",
            "service_enabled": True,
            "target_route": MANUAL_ORDER_ROUTE,
            "target_method": "POST",
            "target_module_id": MANUAL_ORDER_MODULE_ID,
            "target_service_method": MANUAL_ORDER_SERVICE_METHOD,
            "account_family": "spot",
            "venue_scope": "coinbase_advanced_trade",
            "product_scope": ["spot"],
            "live_coinbase_execution_approved": True,
            "max_submitted_notional_usdc": config.seed_max_submitted_notional_usdc,
            "max_executed_notional_usdc": config.seed_max_executed_notional_usdc,
            "decision_reason": (
                "Explicit operator-confirmed Admin MVP live cancel seed order."
            ),
        },
        build_request_context(config, f"{config.idempotency_key}-seed-live-service"),
    )


def build_seed_order_request_context(
    config: SpotLiveCancelConfig,
    idempotency_key: str,
) -> AdminMvpRequestContext:
    """Return Admin context for the backend-owned seed order command."""

    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id=config.correlation_id,
        operator_intent="spot_live_cancel_seed_order",
        actor_id=config.actor_id,
        roles=config.roles,
    )


def spot_cancel_target_client_order_id(config: SpotLiveCancelConfig) -> str:
    """Return the client_order_id to cancel."""

    explicit = text_value(config.client_order_id)
    if explicit:
        return explicit
    return ""


def seed_order_client_order_id(seed_order: Mapping[str, Any]) -> str:
    """Return the backend-generated client_order_id from seed evidence."""

    return text_value(seed_order.get("client_order_id"))


def seed_order_client_order_id_from_parts(
    final_submit: Mapping[str, Any],
    admission: Mapping[str, Any],
) -> str:
    """Return the seed order client id from submission or admission evidence."""

    return text_value(
        final_submit.get("client_order_id")
        or admission.get("identity_value")
    )


def seed_order_accepted(seed_order: Mapping[str, Any]) -> bool:
    """Return whether the optional seed order reached Coinbase."""

    final_submit = object_record(seed_order.get("final_submit"))
    return (
        seed_order.get("final_status_code") == 200
        and final_submit.get("status") == "accepted"
        and final_submit.get("live_exchange_submitted") is True
    )


def skipped_cancel_after_seed_failure(client_order_id: str) -> dict[str, Any]:
    """Return a skipped-cancel command summary when the seed order fails."""

    return {
        "status": "rejected",
        "failure_stage": "seed_order_failed",
        "message": "Spot live cancel seed order was not accepted; cancel skipped.",
        "client_order_id": client_order_id,
        "coinbase_cancel_submission_allowed": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "live_coinbase_execution": "not_run",
        "submitted_notional_usdc": "0",
        "notional_usdc": "0",
        "executed_notional_usdc": "0",
    }


def record_spot_cancel_live_service_decision(
    service: AdminMvpService,
    config: SpotLiveCancelConfig,
):
    """Record backend live-service evidence for this cancel route."""

    return service.record_live_service_decision(
        {
            "decision_id": f"{config.idempotency_key}-live-service",
            "status": "passed",
            "requested_service_status": "approval_required",
            "service_enabled": True,
            "target_route": CANCEL_ORDER_ROUTE,
            "target_method": "POST",
            "target_module_id": MANUAL_ORDER_MODULE_ID,
            "target_service_method": CANCEL_ORDER_SERVICE_METHOD,
            "account_family": "spot",
            "venue_scope": "coinbase_advanced_trade",
            "product_scope": ["spot"],
            "live_coinbase_execution_approved": True,
            "max_submitted_notional_usdc": "0",
            "max_executed_notional_usdc": "0",
            "decision_reason": "Explicit operator-confirmed Admin MVP live cancel.",
        },
        build_request_context(config, f"{config.idempotency_key}-live-service"),
    )


def build_spot_cancel_proof_context(
    config: SpotLiveCancelConfig,
    body: Mapping[str, Any],
    client_order_id: str,
) -> dict[str, Any]:
    """Return proof-chain context matching the cancel command."""

    return {
        "route": CANCEL_ORDER_ROUTE,
        "method": "POST",
        "module_id": MANUAL_ORDER_MODULE_ID,
        "identity_key": "client_order_id",
        "identity_value": client_order_id,
        "action_class": CANCEL_ORDER_ACTION_CLASS,
        "required_permission": CANCEL_ORDER_PERMISSION,
        "service_method": CANCEL_ORDER_SERVICE_METHOD,
        "actor_id": config.actor_id,
        "operator_intent": "spot_live_cancel",
        "command_idempotency_key": config.idempotency_key,
        "payload_hash": body.get("payload_hash"),
        "cancel_proof_reason": "Backend spot cancel proof-chain evidence.",
    }


def build_request_context(
    config: SpotLiveCancelConfig,
    idempotency_key: str,
) -> AdminMvpRequestContext:
    """Return Admin request context for one cancel phase."""

    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id=config.correlation_id,
        operator_intent="spot_live_cancel",
        actor_id=config.actor_id,
        roles=config.roles,
    )


def build_summary(
    *,
    config: SpotLiveCancelConfig,
    body: Mapping[str, Any],
    seed_order: Mapping[str, Any],
    started_at: str,
    duration_seconds: float,
    live_decision: Mapping[str, Any],
    proof_chain: Mapping[str, Any],
    final_cancel: Mapping[str, Any],
    final_status_code: int,
    command_suite: Mapping[str, Any],
    audit_workbench: Mapping[str, Any],
) -> dict[str, Any]:
    """Return redacted Spot cancel evidence."""

    cancel_result = object_record(final_cancel.get("coinbase_cancel_result"))
    seed_body = object_record(seed_order.get("body"))
    seed_final_submit = object_record(seed_order.get("final_submit"))
    seed_proof_chain = object_record(seed_order.get("proof_chain"))
    seed_notional = zero_normalized_decimal_text(
        seed_final_submit.get("notional_usdc")
        or seed_order_notional_usdc(seed_body)
    )
    cancel_client_order_id = cancel_summary_client_order_id(
        config,
        seed_order,
        final_cancel,
    )
    checks = spot_live_cancel_checks(
        config=config,
        body=body,
        seed_order=seed_order,
        live_decision=live_decision,
        proof_chain=proof_chain,
        final_cancel=final_cancel,
        final_status_code=final_status_code,
        command_suite=command_suite,
        audit_workbench=audit_workbench,
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
        "route": CANCEL_ORDER_ROUTE,
        "client_order_id": cancel_client_order_id,
        "payload_hash": body.get("payload_hash"),
        "seed_resting_order": bool(config.seed_resting_order),
        "seed_order_client_order_id": (
            seed_order.get("client_order_id") if config.seed_resting_order else None
        ),
        "seed_order_product_id": (
            seed_body.get("product_id") if config.seed_resting_order else None
        ),
        "seed_order_side": (
            seed_body.get("side") if config.seed_resting_order else None
        ),
        "seed_order_base_size": (
            seed_body.get("base_size") if config.seed_resting_order else None
        ),
        "seed_order_limit_price": (
            seed_body.get("limit_price") if config.seed_resting_order else None
        ),
        "seed_order_time_in_force": (
            seed_body.get("time_in_force") if config.seed_resting_order else None
        ),
        "seed_order_post_only": (
            seed_body.get("post_only") if config.seed_resting_order else None
        ),
        "seed_order_status": (
            seed_final_submit.get("status")
            if config.seed_resting_order
            else "not_requested"
        ),
        "seed_order_status_code": (
            seed_order.get("final_status_code") if config.seed_resting_order else None
        ),
        "seed_order_failure_stage": (
            seed_final_submit.get("failure_stage")
            if config.seed_resting_order
            else None
        ),
        "seed_order_proof_chain_status": (
            seed_proof_chain.get("proof_chain_status")
            if config.seed_resting_order
            else None
        ),
        "seed_order_coinbase_order_id": (
            seed_final_submit.get("coinbase_order_id")
            if config.seed_resting_order
            else None
        ),
        "seed_order_live_exchange_submitted": (
            bool(seed_final_submit.get("live_exchange_submitted"))
            if config.seed_resting_order
            else False
        ),
        "seed_order_live_coinbase_orders_ran": (
            bool(seed_final_submit.get("live_coinbase_orders_ran"))
            if config.seed_resting_order
            else False
        ),
        "seed_order_submitted_notional_usdc": (
            seed_notional if config.seed_resting_order else "0"
        ),
        "seed_order_notional_usdc": (
            seed_notional if config.seed_resting_order else "0"
        ),
        "seed_order_max_submitted_notional_usdc": (
            config.seed_max_submitted_notional_usdc
            if config.seed_resting_order
            else None
        ),
        "live_decision_status": live_decision_status(live_decision),
        "proof_chain_status": proof_chain.get("proof_chain_status"),
        "cancel_proof_chain_id": proof_chain.get("cancel_proof_chain_id"),
        "final_status": final_cancel.get("status"),
        "final_status_code": final_status_code,
        "failure_stage": final_cancel.get("failure_stage"),
        "message": final_cancel.get("message"),
        "coinbase_cancel_submission_allowed": bool(
            final_cancel.get("coinbase_cancel_submission_allowed")
        ),
        "coinbase_cancel_identity_used": final_cancel.get(
            "coinbase_cancel_identity_used"
        ),
        "operator_identity_key": final_cancel.get(
            "operator_identity_key",
            "client_order_id",
        ),
        "coinbase_cancel_initial_identity_used": final_cancel.get(
            "coinbase_cancel_initial_identity_used"
        ),
        "coinbase_cancel_initial_result_present": bool(
            object_record(final_cancel.get("coinbase_cancel_initial_result"))
        ),
        "coinbase_cancel_initial_result_success": bool(
            final_cancel.get("coinbase_cancel_initial_result_success")
        ),
        "coinbase_cancel_fallback_attempted": bool(
            final_cancel.get("coinbase_cancel_fallback_attempted")
        ),
        "coinbase_cancel_fallback_reason": final_cancel.get(
            "coinbase_cancel_fallback_reason"
        ),
        "coinbase_cancel_fallback_identity_used": final_cancel.get(
            "coinbase_cancel_fallback_identity_used"
        ),
        "coinbase_cancel_order_read_attempted": bool(
            final_cancel.get("coinbase_cancel_order_read_attempted")
        ),
        "coinbase_cancel_order_read_succeeded": bool(
            final_cancel.get("coinbase_cancel_order_read_succeeded")
        ),
        "exchange_order_id_present": bool(final_cancel.get("exchange_order_id_present")),
        "exchange_order_id_evidence_only": bool(
            final_cancel.get("exchange_order_id_evidence_only")
        ),
        "cancel_result_present": bool(cancel_result),
        "cancel_result_success": cancel_result_succeeded(cancel_result),
        "cancel_result_item_count": cancel_result_item_count(cancel_result),
        "live_exchange_submitted": bool(final_cancel.get("live_exchange_submitted")),
        "live_coinbase_orders_ran": bool(
            final_cancel.get("live_coinbase_orders_ran")
        ),
        "live_coinbase_execution": final_cancel.get(
            "live_coinbase_execution",
            "not_run",
        ),
        "submitted_notional_usdc": zero_normalized_decimal_text(
            final_cancel.get("submitted_notional_usdc", "0")
        ),
        "notional_usdc": zero_normalized_decimal_text(
            final_cancel.get("notional_usdc", "0")
        ),
        "executed_notional_usdc": zero_normalized_decimal_text(
            final_cancel.get("executed_notional_usdc", "0")
        ),
        "command_suite_status": command_suite.get("status"),
        "command_suite_live_enabled_command_count": command_suite.get(
            "live_enabled_command_count"
        ),
        "command_suite_executable_command_count": command_suite.get(
            "executable_command_count"
        ),
        "cancel_order_proof_chain_status": command_suite.get(
            "cancel_order_proof_chain_status"
        ),
        "cancel_order_missing_gate_count": command_suite.get(
            "cancel_order_missing_gate_count"
        ),
        "audit_event_count": audit_workbench.get("count", 0),
        "checks": checks,
    }


def spot_live_cancel_checks(
    *,
    config: SpotLiveCancelConfig,
    body: Mapping[str, Any],
    seed_order: Mapping[str, Any],
    live_decision: Mapping[str, Any],
    proof_chain: Mapping[str, Any],
    final_cancel: Mapping[str, Any],
    final_status_code: int,
    command_suite: Mapping[str, Any],
    audit_workbench: Mapping[str, Any],
    cancel_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return pass/fail checks for the Spot live-cancel artifact."""

    checks = [
        check("spot_confirm_live_cancel_requested", config.confirm_live_cancel),
        check(
            "spot_client_order_id_present",
            bool(cancel_summary_client_order_id(config, seed_order, final_cancel)),
        ),
        check("spot_cancel_payload_hash_present", bool(body.get("payload_hash"))),
        check("spot_cancel_acknowledged", body.get("manual_live_acknowledgement") is True),
        check("spot_live_service_recorded", live_decision_status(live_decision) == "passed"),
        check("spot_cancel_proof_chain_recorded", proof_chain.get("status") == "accepted"),
        check("spot_cancel_proof_chain_passed", proof_chain.get("proof_chain_status") == "passed"),
        check(
            "spot_live_cancel_accepted",
            final_status_code == 200 and final_cancel.get("status") == "accepted",
        ),
        check(
            "spot_cancel_submission_allowed",
            final_cancel.get("coinbase_cancel_submission_allowed") is True,
        ),
        check(
            "spot_cancel_operator_identity_client_order_id",
            final_cancel.get("operator_identity_key", "client_order_id")
            == "client_order_id",
        ),
        check("spot_cancel_result_success", cancel_result_succeeded(cancel_result)),
        check("spot_live_exchange_submitted", final_cancel.get("live_exchange_submitted") is True),
        check(
            "spot_live_coinbase_execution_submitted",
            final_cancel.get("live_coinbase_execution") == "submitted",
        ),
        check("spot_cancel_notional_zero", decimal_text_is_zero(final_cancel.get("notional_usdc", "0"))),
        check(
            "spot_command_suite_cancel_proof_chain_passed",
            command_suite.get("cancel_order_proof_chain_status") == "passed",
        ),
        check("spot_audit_workbench_readback", audit_workbench.get("count", 0) >= 1),
    ]
    if config.seed_resting_order:
        seed_body = object_record(seed_order.get("body"))
        seed_final_submit = object_record(seed_order.get("final_submit"))
        seed_proof_chain = object_record(seed_order.get("proof_chain"))
        seed_notional = seed_order_notional_usdc(seed_body)
        checks.extend(
            [
                check(
                    "spot_seed_order_client_order_id_matches_cancel_target",
                    seed_order.get("client_order_id")
                    == cancel_summary_client_order_id(
                        config,
                        seed_order,
                        final_cancel,
                    ),
                ),
                check(
                    "spot_seed_order_limit_gtc_requested",
                    seed_body.get("order_type") == "LIMIT"
                    and seed_body.get("time_in_force") not in {
                        "IOC",
                        "IMMEDIATE_OR_CANCEL",
                    },
                ),
                check(
                    "spot_seed_order_uses_base_size",
                    bool(text_value(seed_body.get("base_size"))),
                ),
                check(
                    "spot_seed_order_proof_chain_passed",
                    seed_proof_chain.get("proof_chain_status") == "passed",
                ),
                check("spot_seed_order_accepted", seed_order_accepted(seed_order)),
                check(
                    "spot_seed_order_live_exchange_submitted",
                    seed_final_submit.get("live_exchange_submitted") is True,
                ),
                check(
                    "spot_seed_order_notional_within_cap",
                    decimal_lte(
                        seed_notional,
                        config.seed_max_submitted_notional_usdc,
                    ),
                ),
            ]
        )
    return checks


def live_decision_status(live_decision: Mapping[str, Any]) -> str:
    """Return the nested live-service decision status."""

    decision = object_record(live_decision.get("decision"))
    return text_value(decision.get("status") or live_decision.get("status"))


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


def decimal_text_is_zero(value: Any) -> bool:
    """Return whether a value is numeric zero."""

    try:
        return Decimal(text_value(value)) == Decimal("0")
    except Exception:
        return False


def cancel_summary_client_order_id(
    config: SpotLiveCancelConfig,
    seed_order: Mapping[str, Any],
    final_cancel: Mapping[str, Any],
) -> str:
    """Return the client_order_id represented by the cancel summary."""

    return text_value(
        final_cancel.get("client_order_id")
        or seed_order_client_order_id(seed_order)
        or spot_cancel_target_client_order_id(config)
    )


def decimal_text(value: Any) -> str:
    """Return normalized decimal text."""

    try:
        return format(Decimal(text_value(value)), "f")
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid decimal value: {value!r}") from None


def require_positive_decimal(value: Any, field_name: str) -> None:
    """Validate that a field is a decimal greater than zero."""

    try:
        if Decimal(text_value(value)) <= Decimal("0"):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name} must be a positive decimal.") from None


def seed_order_notional_usdc(seed_body: Mapping[str, Any]) -> str:
    """Return the seed order notional implied by base size and limit."""

    base_size = Decimal(text_value(seed_body.get("base_size")) or "0")
    limit_price = Decimal(text_value(seed_body.get("limit_price")) or "0")
    return zero_normalized_decimal_text(base_size * limit_price)


def decimal_lte(left: Any, right: Any) -> bool:
    """Return whether one decimal-like value is less than or equal to another."""

    try:
        return Decimal(text_value(left)) <= Decimal(text_value(right))
    except (InvalidOperation, ValueError):
        return False


def zero_normalized_decimal_text(value: Any) -> str:
    """Return decimal text with all zero values normalized to ``0``."""

    text = text_value(value)
    return "0" if decimal_text_is_zero(text) else text


def truthy_value(value: Any) -> bool:
    """Return a permissive boolean for Coinbase success-like values."""

    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def object_record(value: Any) -> dict[str, Any]:
    """Return value as a mapping or an empty dict."""

    return dict(value) if isinstance(value, Mapping) else {}


def text_value(value: Any) -> str:
    """Return stripped text."""

    return str(value or "").strip()


def check(name: str, passed: bool) -> dict[str, Any]:
    """Return one readiness check row."""

    return {"name": name, "passed": bool(passed)}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the explicit Spot live cancel and write evidence."""

    config = config_from_args(build_parser().parse_args(argv))
    if not config.confirm_live_cancel:
        raise LiveCancelConfirmationError(
            "Spot live cancel requires --confirm-live-cancel."
        )
    assert_live_credentials_present(os.environ)
    if config.state_dir:
        apply_manual_live_submit_state_environment(config.state_dir)
    os.environ[LIVE_EXECUTION_ENV] = "1"
    apply_runner_environment()
    summary = run_spot_live_cancel(get_admin_mvp_service(), config)
    write_json(config.summary_output, summary)
    print(
        "Backend Spot live cancel: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"client_order_id {summary['client_order_id']}; "
        f"artifact {config.summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
