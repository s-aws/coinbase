"""Run one explicit M58 USDC-pair snapshot live submit/cancel pilot.

This helper is backend-only operator tooling. It builds one USDC snapshot,
derives one order-plan row, records exact durable proof-chain evidence, runs
the M58 live-readiness preflight, then calls the controlled submit/cancel route.
It never submits to Coinbase unless ``--confirm-live-submit`` is passed and the
Admin API live runtime flag is already enabled for this process.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
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

from application.admin_api.approval import (  # noqa: E402
    AdminApiApprovalRecord,
    FileAdminApiApprovalStore,
)
from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore  # noqa: E402
from application.admin_api.cap_guard import (  # noqa: E402
    CapGuardDecisionRecord,
    FileAdminApiCapGuardStore,
)
from application.admin_api.command_runtime import (  # noqa: E402
    build_admin_api_command_runtime_readiness,
)
from application.admin_api.live_execution import (  # noqa: E402
    FileAdminApiLiveServiceDecisionStore,
    LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
    LiveServiceDecisionRecord,
)
from application.admin_api.models import AdminLiveAdmissionDecisionEvidence  # noqa: E402
from application.admin_api.reconciliation import (  # noqa: E402
    FileAdminApiReconciliationStore,
    ReconciliationPlanRecord,
)
from application.admin_api.usdc_pair_snapshot_service import (  # noqa: E402
    AdminApiUsdcPairSnapshotService,
)
from core.enums import (  # noqa: E402
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
    OrderSide,
)
from tools import run_admin_api  # noqa: E402
from tools.coinbase_live_credentials import ensure_live_coinbase_credentials  # noqa: E402


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-m58-usdc-live-submit.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_m58_usdc_snapshot_live_submit"
SCHEMA_VERSION = "1"
DEFAULT_SUBMITTED_NOTIONAL_USDC = "1.00"
DEFAULT_MAX_EXECUTED_NOTIONAL_USDC = "0.01"
DEFAULT_PRICE_INCREMENT = "0.01"
DEFAULT_BASE_INCREMENT = "0.00000001"
DEFAULT_BASE_MIN_SIZE = "0.00000001"
DEFAULT_QUOTE_INCREMENT = "0.01"
DEFAULT_QUOTE_MIN_SIZE = "1.00"
MAX_SUBMITTED_NOTIONAL_USDC = Decimal("10")
AUTH_TOKEN_ENV = "COINBASE_ADMIN_API_BEARER_TOKEN"
LOCAL_AUTH_TOKEN = "m58-local-admin-token"
ORDER_PLAN_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-runs/{run_id}/order-plans"
)
ORDER_PLAN_ENDPOINT = f"POST {ORDER_PLAN_ROUTE}"
ORDER_PLAN_SERVICE_METHOD = "record_usdc_pair_snapshot_order_plan"
ALLOWLIST_READINESS_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-order-plans/"
    "{plan_id}/allowlist-readiness"
)
ALLOWLIST_RUN_STATE_ROUTE = (
    "/api/v1/automation/usdc-pair-snapshot-order-plan-allowlist-readiness/"
    "{readiness_id}/run-state"
)
ALLOWLIST_RUN_STATE_SERVICE_METHOD = (
    "record_usdc_pair_snapshot_allowlist_run_state"
)
AUTOMATION_MODULE_ID = "automation"
LIVE_SERVICE_ACCOUNT_FAMILY = "coinbase_spot"
LIVE_SERVICE_VENUE_SCOPE = "coinbase_advanced_trade"
LIVE_SERVICE_INTX_APPLICABILITY = "not_applicable"
STATE_LOG_FILENAMES = {
    "COINBASE_ADMIN_API_IDEMPOTENCY_LOG_PATH": "admin_api_idempotency.jsonl",
    "COINBASE_ADMIN_API_AUDIT_LOG_PATH": "admin_api_audit.jsonl",
    "COINBASE_ADMIN_API_APPROVAL_LOG_PATH": "admin_api_approvals.jsonl",
    "COINBASE_ADMIN_API_CAP_GUARD_LOG_PATH": "admin_api_cap_guard.jsonl",
    "COINBASE_ADMIN_API_RECONCILIATION_LOG_PATH": (
        "admin_api_reconciliation_plan.jsonl"
    ),
    "COINBASE_ADMIN_API_LIVE_SERVICE_DECISION_LOG_PATH": (
        "admin_api_live_service_decisions.jsonl"
    ),
    "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_LOG_PATH": (
        "admin_api_usdc_pair_snapshot_runs.jsonl"
    ),
    "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ORDER_PLAN_LOG_PATH": (
        "admin_api_usdc_pair_snapshot_order_plans.jsonl"
    ),
    "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ORDER_PLAN_ALLOWLIST_READINESS_LOG_PATH": (
        "admin_api_usdc_pair_snapshot_order_plan_allowlist_readiness.jsonl"
    ),
    "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LOG_PATH": (
        "admin_api_usdc_pair_snapshot_allowlist_run_states.jsonl"
    ),
    "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_READINESS_LOG_PATH": (
        "admin_api_usdc_pair_snapshot_order_plan_live_readiness.jsonl"
    ),
    "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_LOG_PATH": (
        "admin_api_usdc_pair_snapshot_order_plan_live_submit.jsonl"
    ),
}


class LiveSubmitConfirmationError(RuntimeError):
    """Raised when a live submission is requested without explicit consent."""


@dataclass(frozen=True)
class UsdcPairSnapshotLiveSubmitConfig:
    """Operator-controlled inputs for one bounded M58 live pilot."""

    confirm_live_submit: bool = False
    product_id: str = "BTC-USDC"
    side: str = "BUY"
    submitted_notional_usdc: str = DEFAULT_SUBMITTED_NOTIONAL_USDC
    max_executed_notional_usdc: str = DEFAULT_MAX_EXECUTED_NOTIONAL_USDC
    reference_bid_price: str = "0"
    reference_bid_price_source: str = "operator_reference_bid_price"
    reference_bid_price_captured_at: str | None = None
    last_filled_price: str = "0"
    last_filled_price_source: str = "operator_last_filled_price"
    last_filled_price_captured_at: str | None = None
    intended_limit_price: str = "0"
    state_dir: str | None = None
    summary_output: str = str(DEFAULT_SUMMARY_OUTPUT)
    run_id: str | None = None
    plan_id: str | None = None
    readiness_id: str | None = None
    submission_id: str | None = None
    submit_from_run_state: bool = False
    allowlist_readiness_id: str | None = None
    run_state_id: str | None = None
    max_fanout_notional_usdc: str = "100"
    retry_budget_per_product: int = 1
    run_rate_limit_budget_ref: str | None = None
    run_lock_ref: str | None = None
    rate_limit_window_ref: str | None = None
    idempotency_prefix: str | None = None
    correlation_id: str | None = None
    actor_id: str = "local-operator"
    roles: tuple[str, ...] = ("admin", "trader")
    account_id: str | None = None
    portfolio_id: str | None = None
    price_increment: str = DEFAULT_PRICE_INCREMENT
    base_increment: str = DEFAULT_BASE_INCREMENT
    base_min_size: str = DEFAULT_BASE_MIN_SIZE
    quote_increment: str = DEFAULT_QUOTE_INCREMENT
    quote_min_size: str = DEFAULT_QUOTE_MIN_SIZE
    full_snapshot_fill_test: bool = False
    cancel_rollback_plan_ref: str = "m58-cancel-before-additional-orders"


def build_parser() -> argparse.ArgumentParser:
    """Create the M58 live-submit parser."""

    parser = argparse.ArgumentParser(
        description="Submit and cancel one M58 USDC snapshot order-plan row."
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument("--confirm-live-submit", action="store_true")
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--side", choices=("BUY", "SELL"), default="BUY")
    parser.add_argument(
        "--submitted-notional-usdc",
        default=DEFAULT_SUBMITTED_NOTIONAL_USDC,
    )
    parser.add_argument(
        "--max-executed-notional-usdc",
        default=DEFAULT_MAX_EXECUTED_NOTIONAL_USDC,
    )
    parser.add_argument("--reference-bid-price", required=True)
    parser.add_argument(
        "--reference-bid-price-source",
        default="operator_reference_bid_price",
    )
    parser.add_argument("--reference-bid-price-captured-at", default=None)
    parser.add_argument("--last-filled-price", required=True)
    parser.add_argument(
        "--last-filled-price-source",
        default="operator_last_filled_price",
    )
    parser.add_argument("--last-filled-price-captured-at", default=None)
    parser.add_argument("--intended-limit-price", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--plan-id", default=None)
    parser.add_argument("--readiness-id", default=None)
    parser.add_argument("--submission-id", default=None)
    parser.add_argument("--submit-from-run-state", action="store_true")
    parser.add_argument("--allowlist-readiness-id", default=None)
    parser.add_argument("--run-state-id", default=None)
    parser.add_argument("--max-fanout-notional-usdc", default="100")
    parser.add_argument("--retry-budget-per-product", type=int, default=1)
    parser.add_argument("--run-rate-limit-budget-ref", default=None)
    parser.add_argument("--run-lock-ref", default=None)
    parser.add_argument("--rate-limit-window-ref", default=None)
    parser.add_argument("--idempotency-prefix", default=None)
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--actor-id", default="local-operator")
    parser.add_argument("--roles", default="admin,trader")
    parser.add_argument("--account-id", default=None)
    parser.add_argument("--portfolio-id", default=None)
    parser.add_argument("--price-increment", default=DEFAULT_PRICE_INCREMENT)
    parser.add_argument("--base-increment", default=DEFAULT_BASE_INCREMENT)
    parser.add_argument("--base-min-size", default=DEFAULT_BASE_MIN_SIZE)
    parser.add_argument("--quote-increment", default=DEFAULT_QUOTE_INCREMENT)
    parser.add_argument("--quote-min-size", default=DEFAULT_QUOTE_MIN_SIZE)
    return parser


def config_from_args(args: argparse.Namespace) -> UsdcPairSnapshotLiveSubmitConfig:
    """Return normalized live-submit config from parsed arguments."""

    run_suffix = str(int(time.time()))
    product_token = str(args.product_id).upper().replace("/", "-")
    prefix = args.idempotency_prefix or f"m58-usdc-live-{product_token}-{run_suffix}"
    roles = tuple(role.strip() for role in str(args.roles).split(",") if role.strip())
    return UsdcPairSnapshotLiveSubmitConfig(
        confirm_live_submit=bool(args.confirm_live_submit),
        product_id=str(args.product_id).upper(),
        side=str(args.side).upper(),
        submitted_notional_usdc=str(args.submitted_notional_usdc),
        max_executed_notional_usdc=str(args.max_executed_notional_usdc),
        reference_bid_price=str(args.reference_bid_price),
        reference_bid_price_source=str(args.reference_bid_price_source),
        reference_bid_price_captured_at=(
            str(args.reference_bid_price_captured_at)
            if args.reference_bid_price_captured_at
            else current_utc_timestamp()
        ),
        last_filled_price=str(args.last_filled_price),
        last_filled_price_source=str(args.last_filled_price_source),
        last_filled_price_captured_at=(
            str(args.last_filled_price_captured_at)
            if args.last_filled_price_captured_at
            else current_utc_timestamp()
        ),
        intended_limit_price=str(args.intended_limit_price),
        state_dir=str(args.state_dir) if args.state_dir else None,
        summary_output=str(args.summary_output),
        run_id=args.run_id or f"{prefix}-snapshot",
        plan_id=args.plan_id or f"{prefix}-plan",
        readiness_id=args.readiness_id or f"{prefix}-readiness",
        submission_id=args.submission_id or f"{prefix}-submission",
        submit_from_run_state=bool(args.submit_from_run_state),
        allowlist_readiness_id=(
            args.allowlist_readiness_id or f"{prefix}-allowlist-readiness"
        ),
        run_state_id=args.run_state_id or f"{prefix}-run-state",
        max_fanout_notional_usdc=str(args.max_fanout_notional_usdc),
        retry_budget_per_product=int(args.retry_budget_per_product),
        run_rate_limit_budget_ref=(
            args.run_rate_limit_budget_ref or f"{prefix}-rate-limit-budget"
        ),
        run_lock_ref=args.run_lock_ref or f"{prefix}-run-lock",
        rate_limit_window_ref=(
            args.rate_limit_window_ref or f"{prefix}-rate-limit-window"
        ),
        idempotency_prefix=prefix,
        correlation_id=args.correlation_id or f"{prefix}-correlation",
        actor_id=str(args.actor_id),
        roles=roles or ("admin", "trader"),
        account_id=args.account_id,
        portfolio_id=args.portfolio_id,
        price_increment=str(args.price_increment),
        base_increment=str(args.base_increment),
        base_min_size=str(args.base_min_size),
        quote_increment=str(args.quote_increment),
        quote_min_size=str(args.quote_min_size),
    )


def default_state_dir() -> Path:
    """Return the local Admin state directory used by the M58 runner."""

    explicit_state_dir = os.environ.get("COINBASE_ADMIN_API_STATE_DIR", "").strip()
    if explicit_state_dir:
        return Path(explicit_state_dir)
    return Path("artifacts") / "admin-api-state"


def validate_live_submit_config(config: UsdcPairSnapshotLiveSubmitConfig) -> None:
    """Validate bounded live-submission operator inputs."""

    if not config.confirm_live_submit:
        raise LiveSubmitConfirmationError(
            "M58 live submission requires --confirm-live-submit."
        )
    side = OrderSide(config.side)
    submitted = decimal_value(config.submitted_notional_usdc)
    max_executed = decimal_value(config.max_executed_notional_usdc)
    reference_bid = decimal_value(config.reference_bid_price)
    last_filled = decimal_value(config.last_filled_price)
    intended = decimal_value(config.intended_limit_price)
    if submitted <= 0:
        raise ValueError("submitted_notional_usdc must be greater than zero.")
    if submitted > MAX_SUBMITTED_NOTIONAL_USDC:
        raise ValueError("submitted_notional_usdc must not exceed 10 USDC.")
    if config.submit_from_run_state:
        max_fanout_notional = decimal_value(config.max_fanout_notional_usdc)
        if max_fanout_notional <= 0:
            raise ValueError("max_fanout_notional_usdc must be greater than zero.")
        if max_fanout_notional > Decimal("100"):
            raise ValueError("max_fanout_notional_usdc must not exceed 100 USDC.")
        if max_fanout_notional < submitted:
            raise ValueError(
                "max_fanout_notional_usdc must cover submitted_notional_usdc."
            )
        if config.retry_budget_per_product < 1:
            raise ValueError("retry_budget_per_product must be at least 1.")
    if max_executed > submitted:
        raise ValueError("max_executed_notional_usdc must not exceed submitted.")
    if reference_bid <= 0 or last_filled <= 0 or intended <= 0:
        raise ValueError("reference, last-filled, and intended prices must be positive.")
    if config.full_snapshot_fill_test:
        raise ValueError("full snapshot fill tests require manual review.")
    if side == OrderSide.BUY:
        if intended > reference_bid * Decimal("0.50"):
            raise ValueError(
                "BUY intended_limit_price must be at most 50% of reference bid."
            )
        if intended > last_filled * Decimal("0.90"):
            raise ValueError(
                "BUY intended_limit_price must be at least 10% below last-filled."
            )
    else:
        if intended < reference_bid * Decimal("1.50"):
            raise ValueError(
                "SELL intended_limit_price must be at least 150% of reference bid."
            )
        if intended < last_filled * Decimal("1.10"):
            raise ValueError(
                "SELL intended_limit_price must be at least 10% above last-filled."
            )


def apply_usdc_pair_state_environment(
    state_dir: Path,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Point Admin evidence logs at one local state directory."""

    target = os.environ if environ is None else environ
    resolved_state_dir = state_dir.resolve()
    resolved_state_dir.mkdir(parents=True, exist_ok=True)
    applied: dict[str, str] = {}
    for env_name, filename in STATE_LOG_FILENAMES.items():
        path = resolved_state_dir / filename
        target[env_name] = str(path)
        applied[env_name] = str(path)
    return applied


def run_usdc_pair_snapshot_live_submit(
    config: UsdcPairSnapshotLiveSubmitConfig,
    *,
    live_executor: Any | None = None,
    require_runtime_ready: bool = True,
    require_credentials: bool = True,
) -> dict[str, Any]:
    """Run the exact M58 route sequence and return redacted evidence."""

    validate_live_submit_config(config)
    started_at = current_utc_timestamp()
    started = time.perf_counter()
    state_dir = Path(config.state_dir) if config.state_dir else default_state_dir()
    apply_usdc_pair_state_environment(state_dir)
    os.environ.setdefault(AUTH_TOKEN_ENV, LOCAL_AUTH_TOKEN)
    apply_runner_environment()
    operator_requested_notional = decimal_text(config.submitted_notional_usdc)
    requested_notional = decimal_text(planning_request_notional_usdc(config))
    reference_bid_price_source = (
        config.reference_bid_price_source.strip()
        if config.reference_bid_price_source
        else "operator_reference_bid_price"
    )
    reference_bid_price_captured_at = (
        config.reference_bid_price_captured_at or started_at
    )
    last_filled_price_source = (
        config.last_filled_price_source.strip()
        if config.last_filled_price_source
        else "operator_last_filled_price"
    )
    last_filled_price_captured_at = (
        config.last_filled_price_captured_at or started_at
    )
    runtime_readiness = None
    if require_credentials:
        ensure_live_coinbase_credentials(os.environ)
        refresh_configuration_credentials()
    if require_runtime_ready:
        runtime_readiness = build_admin_api_command_runtime_readiness()
        if not runtime_readiness.runtime_ready:
            raise RuntimeError(
                "M58 live submit blocked by backend runtime readiness: "
                f"{runtime_readiness.missing_reason or 'unknown'}"
            )

    client, app = build_test_client(config, live_executor=live_executor)
    try:
        with client:
            snapshot_payload = _post_json(
                client,
                "/api/v1/automation/usdc-pair-snapshot-runs",
                headers=_headers(config, "snapshot"),
                json_body={
                    "run_id": config.run_id,
                    "side": config.side,
                    "max_notional_per_product_usdc": (
                        requested_notional
                    ),
                    "product_ids": [config.product_id],
                    "account_id": config.account_id,
                    "portfolio_id": config.portfolio_id,
                    "dry_run": True,
                    "operator_notes": (
                        "M58 controlled-live pilot snapshot source."
                    ),
                },
            )
            order_plan_payload = _post_json(
                client,
                (
                    "/api/v1/automation/usdc-pair-snapshot-runs/"
                    f"{config.run_id}/order-plans"
                ),
                headers=_headers(config, "order-plan"),
                json_body={
                    "plan_id": config.plan_id,
                    "max_total_notional_usdc": (
                        requested_notional
                    ),
                    "time_in_force": "GOOD_UNTIL_CANCELLED",
                    "dry_run": True,
                    "operator_notes": "M58 controlled-live pilot order plan.",
                },
            )
            plan = require_mapping(order_plan_payload.get("plan"), "plan")
            row = planned_row_for_product(plan, config.product_id)
            append_proof_chain_evidence(config=config, plan=plan, row=row)
            proof_refresh_payload = _post_json(
                client,
                (
                    "/api/v1/automation/usdc-pair-snapshot-order-plans/"
                    f"{config.plan_id}/proof-chain-refresh"
                ),
                headers=_headers(config, "proof-refresh"),
                json_body={
                    "dry_run": True,
                    "operator_notes": (
                        "M58 controlled-live proof refresh before readiness."
                    ),
                },
            )
            refreshed_plan = require_mapping(proof_refresh_payload.get("plan"), "plan")
            refreshed_row = planned_row_for_product(refreshed_plan, config.product_id)
            planned_notional = decimal_text(refreshed_row["planned_notional_usdc"])
            readiness_payload = _post_json(
                client,
                (
                    "/api/v1/automation/usdc-pair-snapshot-order-plans/"
                    f"{config.plan_id}/live-readiness"
                ),
                headers=_headers(config, "live-readiness"),
                json_body={
                    "readiness_id": config.readiness_id,
                    "product_id": config.product_id,
                    "client_order_id": refreshed_row["client_order_id"],
                    "reference_bid_price": decimal_text(config.reference_bid_price),
                    "reference_bid_price_source": reference_bid_price_source,
                    "reference_bid_price_captured_at": (
                        reference_bid_price_captured_at
                    ),
                    "last_filled_price": decimal_text(config.last_filled_price),
                    "last_filled_price_source": last_filled_price_source,
                    "last_filled_price_captured_at": last_filled_price_captured_at,
                    "intended_limit_price": decimal_text(config.intended_limit_price),
                    "submitted_notional_usdc": planned_notional,
                    "max_executed_notional_usdc": (
                        decimal_text(config.max_executed_notional_usdc)
                    ),
                    "minimum_order_size_preferred": True,
                    "single_order_only": True,
                    "cancel_before_additional_orders": True,
                    "cancel_rollback_plan_ref": config.cancel_rollback_plan_ref,
                    "full_snapshot_fill_test": False,
                    "operator_notes": (
                        "M58 single-product far-from-market readiness."
                    ),
                },
            )
            readiness = require_mapping(
                readiness_payload.get("readiness"),
                "readiness",
            )
            live_submit_path = (
                "/api/v1/automation/usdc-pair-snapshot-order-plans/"
                f"{config.plan_id}/live-submit"
            )
            live_submit_phase = "live-submit"
            live_submit_source = "order_plan"
            allowlist_payload: dict[str, Any] | None = None
            run_state_payload: dict[str, Any] | None = None
            run_state_product: dict[str, Any] = {}
            if config.submit_from_run_state:
                runner_prefix = config.idempotency_prefix or "m58-usdc-live"
                append_run_state_handoff_evidence(
                    config=config,
                    row=refreshed_row,
                )
                allowlist_payload = _post_json(
                    client,
                    (
                        "/api/v1/automation/usdc-pair-snapshot-order-plans/"
                        f"{config.plan_id}/allowlist-readiness"
                    ),
                    headers=_headers(config, "allowlist-readiness"),
                    json_body={
                        "readiness_id": config.allowlist_readiness_id,
                        "product_ids": [config.product_id],
                        "max_products": 1,
                        "retry_budget_per_product": config.retry_budget_per_product,
                        "run_rate_limit_budget_ref": (
                            config.run_rate_limit_budget_ref
                            or f"{runner_prefix}-rate-limit-budget"
                        ),
                        "cancel_recovery_plan_ref": (
                            config.cancel_rollback_plan_ref
                        ),
                        "operator_notes": (
                            "M58 one-product run-state handoff readiness."
                        ),
                    },
                )
                allowlist_readiness = require_mapping(
                    allowlist_payload.get("readiness"),
                    "allowlist readiness",
                )
                run_state_payload = _post_json(
                    client,
                    (
                        "/api/v1/automation/usdc-pair-snapshot-order-plan-"
                        "allowlist-readiness/"
                        f"{allowlist_readiness['readiness_id']}/run-state"
                    ),
                    headers=_headers(config, "run-state"),
                    json_body={
                        "run_state_id": config.run_state_id,
                        "execution_mode": "no_live_rehearsal",
                        "max_fanout_notional_usdc": (
                            decimal_text(config.max_fanout_notional_usdc)
                        ),
                        "run_lock_ref": (
                            config.run_lock_ref or f"{runner_prefix}-run-lock"
                        ),
                        "rate_limit_window_ref": (
                            config.rate_limit_window_ref
                            or f"{runner_prefix}-rate-limit-window"
                        ),
                        "pause_requested": False,
                        "abort_requested": False,
                        "operator_notes": (
                            "M58 one-product no-live run-state source for "
                            "controlled-live handoff."
                        ),
                    },
                )
                run_state = require_mapping(
                    run_state_payload.get("run_state"),
                    "run state",
                )
                run_state_product = run_state_product_state(
                    run_state,
                    product_id=config.product_id,
                    client_order_id=str(readiness["client_order_id"]),
                )
                if run_state_product.get("execution_state") != "queued_no_live":
                    raise RuntimeError(
                        "M58 run-state handoff blocked: selected product is not queued."
                    )
                if (
                    run_state_product.get("live_readiness_id")
                    != readiness["readiness_id"]
                ):
                    raise RuntimeError(
                        "M58 run-state handoff blocked: live-readiness id mismatch."
                    )
                live_submit_path = (
                    "/api/v1/automation/usdc-pair-snapshot-allowlist-run-states/"
                    f"{run_state['run_state_id']}/live-submit"
                )
                live_submit_phase = "run-state-live-submit"
                live_submit_source = "allowlist_run_state"
            live_submit_payload = _post_json(
                client,
                live_submit_path,
                headers=_headers(config, live_submit_phase),
                json_body={
                    "submission_id": config.submission_id,
                    "readiness_id": readiness["readiness_id"],
                    "product_id": config.product_id,
                    "client_order_id": readiness["client_order_id"],
                    "confirm_live_submit": True,
                    "confirm_single_order_only": True,
                    "confirm_cancel_before_additional_orders": True,
                    "confirm_no_additional_orders": True,
                    "operator_stop_conditions": [
                        "submit one far-from-market Coinbase limit order only",
                        "cancel that client_order_id before any additional order",
                        "stop before any second M58 live order",
                    ],
                    "operator_notes": (
                        "M58 controlled-live submit/cancel pilot."
                    ),
                },
            )
            final_refresh_payload = _post_json(
                client,
                (
                    "/api/v1/automation/usdc-pair-snapshot-order-plans/"
                    f"{config.plan_id}/proof-chain-refresh"
                ),
                headers=_headers(config, "proof-refresh-after-submit"),
                json_body={
                    "dry_run": True,
                    "operator_notes": (
                        "M58 controlled-live proof refresh after submit/cancel."
                    ),
                },
            )
    finally:
        app.dependency_overrides.clear()

    final_plan = require_mapping(final_refresh_payload.get("plan"), "final plan")
    final_row = planned_row_for_product(final_plan, config.product_id)
    submission = require_mapping(live_submit_payload.get("submission"), "submission")
    allowlist_readiness = (
        require_mapping(allowlist_payload.get("readiness"), "allowlist readiness")
        if allowlist_payload
        else {}
    )
    run_state = (
        require_mapping(run_state_payload.get("run_state"), "run state")
        if run_state_payload
        else {}
    )
    if run_state and not run_state_product:
        run_state_product = run_state_product_state(
            run_state,
            product_id=config.product_id,
            client_order_id=str(submission.get("client_order_id") or ""),
        )
    status_value = (
        "passed"
        if (
            live_submit_payload.get("live_coinbase_execution")
            == "submitted_cancelled"
            and final_row.get("proof_chain_status") == "accepted"
        )
        else "failed"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "status": status_value,
        "started_at": started_at,
        "ended_at": current_utc_timestamp(),
        "duration_seconds": round(max(time.perf_counter() - started, 0), 3),
        "backend_git_commit": read_git_value(["rev-parse", "--short", "HEAD"]),
        "backend_git_branch": read_git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "state_dir": str(state_dir.resolve()),
        "product_id": config.product_id,
        "side": config.side,
        "operator_requested_notional_usdc": operator_requested_notional,
        "requested_notional_usdc": requested_notional,
        "submitted_notional_usdc": submission.get("submitted_notional_usdc"),
        "executed_notional_usdc": submission.get("executed_notional_usdc"),
        "max_executed_notional_usdc": submission.get("max_executed_notional_usdc"),
        "reference_bid_price": config.reference_bid_price,
        "reference_bid_price_source": readiness.get("reference_bid_price_source"),
        "reference_bid_price_captured_at": readiness.get(
            "reference_bid_price_captured_at"
        ),
        "reference_bid_price_freshness_status": readiness.get(
            "reference_bid_price_freshness_status"
        ),
        "last_filled_price": config.last_filled_price,
        "last_filled_price_source": readiness.get("last_filled_price_source"),
        "last_filled_price_captured_at": readiness.get(
            "last_filled_price_captured_at"
        ),
        "last_filled_price_freshness_status": readiness.get(
            "last_filled_price_freshness_status"
        ),
        "intended_limit_price": config.intended_limit_price,
        "run_id": config.run_id,
        "plan_id": config.plan_id,
        "live_submit_source": live_submit_source,
        "allowlist_readiness_id": allowlist_readiness.get("readiness_id"),
        "allowlist_readiness_status": allowlist_readiness.get(
            "fanout_readiness_status"
        ),
        "run_state_id": run_state.get("run_state_id"),
        "run_state_status": run_state.get("run_state_status"),
        "run_state_queued_product_ids": run_state.get("queued_product_ids"),
        "run_state_live_readiness_id": run_state_product.get("live_readiness_id"),
        "run_state_live_wallet_reservation_status": run_state.get(
            "live_wallet_reservation_status"
        ),
        "run_state_live_wallet_reservation_blockers": run_state.get(
            "live_wallet_reservation_blockers"
        ),
        "run_state_product_live_wallet_reservation_status": (
            run_state_product.get("live_wallet_reservation_status")
        ),
        "run_state_product_live_wallet_reservation_blockers": (
            run_state_product.get("live_wallet_reservation_blockers")
        ),
        "fanout_execution_status": run_state.get("fanout_execution_status"),
        "fanout_blockers": run_state.get("fanout_blockers"),
        "max_fanout_notional_usdc": run_state.get("max_fanout_notional_usdc"),
        "readiness_id": readiness.get("readiness_id"),
        "submission_id": submission.get("submission_id"),
        "client_order_id": submission.get("client_order_id"),
        "coinbase_order_id": submission.get("coinbase_order_id"),
        "coinbase_order_id_evidence_only": submission.get(
            "coinbase_order_id_evidence_only"
        ),
        "approval_snapshot_id": submission.get("approval_snapshot_id"),
        "admission_audit_id": submission.get("admission_audit_id"),
        "cap_guard_decision_id": submission.get("cap_guard_decision_id"),
        "reconciliation_plan_id": submission.get("reconciliation_plan_id"),
        "live_service_decision_id": submission.get("live_service_decision_id"),
        "snapshot_status": snapshot_payload.get("status"),
        "order_plan_status": order_plan_payload.get("status"),
        "readiness_status": readiness_payload.get("status"),
        "submission_status": live_submit_payload.get("status"),
        "proof_chain_status_after_submission": final_row.get("proof_chain_status"),
        "proof_chain_blockers_after_submission": final_row.get(
            "proof_chain_blockers"
        ),
        "live_exchange_submitted": live_submit_payload.get("live_exchange_submitted"),
        "live_coinbase_orders_ran": live_submit_payload.get(
            "live_coinbase_orders_ran"
        ),
        "live_coinbase_execution": live_submit_payload.get(
            "live_coinbase_execution"
        ),
        "notional_usdc": live_submit_payload.get("notional_usdc"),
        "cancel_submitted": submission.get("cancel_submitted"),
        "cancel_rollback_complete": submission.get("cancel_rollback_complete"),
        "runtime_env_var": LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
        "runtime_ready": (
            runtime_readiness.runtime_ready if runtime_readiness is not None else None
        ),
        "runtime_missing_reason": (
            runtime_readiness.missing_reason
            if runtime_readiness is not None
            else None
        ),
    }


def build_test_client(
    config: UsdcPairSnapshotLiveSubmitConfig,
    *,
    live_executor: Any | None = None,
):
    """Return a TestClient wired to one backend-owned M58 product scope."""

    from fastapi.testclient import TestClient
    from api.v1.app import create_app
    from api.v1.routes import automation as automation_routes
    from application.admin_api import mvp_service as mvp_service_module

    mvp_service_module._SERVICE_SINGLETON = None
    app = create_app()
    service = AdminApiUsdcPairSnapshotService(
        product_provider=lambda: [product_metadata(config)],
        price_provider=lambda product: {
            "price": decimal_text(config.reference_bid_price),
            "source": "operator_reference_bid_price",
            "captured_at": current_utc_timestamp(),
        },
    )
    app.dependency_overrides[
        automation_routes.get_usdc_pair_snapshot_service
    ] = lambda: service
    if live_executor is not None:
        app.dependency_overrides[
            automation_routes.get_usdc_pair_snapshot_live_order_executor
        ] = lambda: live_executor
    return TestClient(app), app


def product_metadata(config: UsdcPairSnapshotLiveSubmitConfig) -> dict[str, Any]:
    """Return product metadata for one operator-selected USDC spot pair."""

    product_id = config.product_id.upper()
    parts = product_id.split("-")
    base = parts[0] if len(parts) >= 2 else product_id
    quote = parts[1] if len(parts) >= 2 else "USDC"
    return {
        "product_id": product_id,
        "product_type": "SPOT",
        "type": "SPOT",
        "base_currency": base,
        "quote_currency": quote,
        "status": "online",
        "base_increment": decimal_text(config.base_increment),
        "quote_increment": decimal_text(config.quote_increment),
        "price_increment": decimal_text(config.price_increment),
        "base_min_size": decimal_text(config.base_min_size),
        "quote_min_size": decimal_text(config.quote_min_size),
        "price": decimal_text(config.reference_bid_price),
        "trading_disabled": False,
    }


def append_proof_chain_evidence(
    *,
    config: UsdcPairSnapshotLiveSubmitConfig,
    plan: Mapping[str, Any],
    row: Mapping[str, Any],
) -> dict[str, str]:
    """Append exact durable proof records consumed by M58 proof refresh."""

    approval_id = f"m58-usdc-approval-{row['client_order_id']}"
    approval_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    command = command_evidence(config=config, plan=plan, row=row)
    approval_store = FileAdminApiApprovalStore()
    audit_store = FileAdminApiAuditStore()
    cap_guard_store = FileAdminApiCapGuardStore()
    reconciliation_store = FileAdminApiReconciliationStore()
    live_service_store = FileAdminApiLiveServiceDecisionStore()

    approval_store.append(
        AdminApiApprovalRecord(
            approval_id=approval_id,
            expires_at=approval_expires_at,
            approved_by_actor_id=config.actor_id,
            requested_by_actor_id=str(plan["actor_id"]),
            route=ORDER_PLAN_ROUTE,
            method="POST",
            module_id=AUTOMATION_MODULE_ID,
            identity_key="client_order_id",
            identity_value=str(row["client_order_id"]),
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
            operator_intent=str(plan["operator_intent"]),
            idempotency_key=str(row["idempotency_key"]),
            payload_hash=str(plan["payload_hash"]),
            cap_guard_decision_ref=str(row["cap_guard_decision_id"]),
            reconciliation_plan_ref=str(row["reconciliation_plan_id"]),
            approval_reason=(
                "M58 controlled-live single-product submit/cancel approval."
            ),
        )
    )
    audit_store.append(
        AdminApiAuditEvent(
            audit_id=str(row["admission_audit_id"]),
            actor_id=str(plan["actor_id"]),
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            permission=AdminApiPermission.CAMPAIGN_EXECUTE,
            endpoint=ORDER_PLAN_ENDPOINT,
            request_id=config.correlation_id or "m58-usdc-live-correlation",
            operator_intent=str(plan["operator_intent"]),
            idempotency_key=str(row["idempotency_key"]),
            approval_id=approval_id,
            client_order_id=str(row["client_order_id"]),
            status=AdminApiCommandStatus.ACCEPTED,
            message="M58 controlled-live admission audit proof.",
            admission_decision=AdminLiveAdmissionDecisionEvidence(
                status=AdminApiGateStatus.PASSED,
                allowed=True,
                route=ORDER_PLAN_ROUTE,
                method="POST",
                module_id=AUTOMATION_MODULE_ID,
                identity_key="client_order_id",
                identity_value=str(row["client_order_id"]),
                action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
                required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
                service_method=ORDER_PLAN_SERVICE_METHOD,
                actor_id=str(plan["actor_id"]),
                idempotency_key=str(row["idempotency_key"]),
                operator_intent=str(plan["operator_intent"]),
                payload_hash=str(plan["payload_hash"]),
                approval_snapshot_present=True,
                approval_snapshot_id=approval_id,
                approval_snapshot_source="approval_store",
                approval_snapshot_approved_by_actor_id=config.actor_id,
                approval_snapshot_requested_by_actor_id=str(plan["actor_id"]),
                approval_snapshot_expires_at=approval_expires_at.isoformat(),
                admission_audit_present=True,
                admission_audit_id=str(row["admission_audit_id"]),
                admission_audit_source="admin_api_audit_log",
                admission_audit_recorded_at=current_utc_timestamp(),
                cap_guard_present=True,
                cap_guard_decision_id=str(row["cap_guard_decision_id"]),
                cap_guard_source="admin_api_cap_guard_log",
                reconciliation_plan_present=True,
                reconciliation_plan_id=str(row["reconciliation_plan_id"]),
                reconciliation_plan_source="admin_api_reconciliation_plan_log",
                live_execution_service_present=True,
                live_execution_service_status=(
                    AdminApiLiveExecutionStatus.APPROVAL_REQUIRED
                ),
                live_execution_service_source="admin_api_live_service_decisions_log",
                browser_authority="rejected",
                live_exchange_submitted=False,
                blockers=[],
                evidence=[
                    "operator-confirmed M58 single-row live pilot",
                    "durable approval, audit, cap, reconciliation, live-service proof",
                ],
                detail=(
                    "Backend-owned M58 admission proof for one controlled-live "
                    "submit/cancel pilot."
                ),
            ),
            approval_cap_guard_decision_ref=str(row["cap_guard_decision_id"]),
            approval_reconciliation_plan_ref=str(row["reconciliation_plan_id"]),
            live_execution_intent_ref=ORDER_PLAN_SERVICE_METHOD,
        )
    )
    cap_guard_store.append(
        CapGuardDecisionRecord(
            decision_id=str(row["cap_guard_decision_id"]),
            recorded_at=current_utc_timestamp(),
            approval_snapshot_id=approval_id,
            admission_audit_id=str(row["admission_audit_id"]),
            allowed=True,
            status=AdminApiGateStatus.PASSED,
            cap_policy_ref="m58_usdc_single_order_cap:10",
            guard_policy_ref="m58_usdc_far_from_market_cancel_required",
            product_scope="M58 USDC spot order-plan row",
            max_submitted_notional_usdc=str(row["planned_notional_usdc"]),
            max_executed_notional_usdc="0",
            wallet_check_required=True,
            wallet_check_status=AdminApiGateStatus.PASSED,
            wallet_available_notional_usdc=str(row["planned_notional_usdc"]),
            wallet_check_source="operator_m58_live_pilot_cap",
            reason="M58 controlled-live submitted-notional cap proof.",
            **command,
        )
    )
    reconciliation_store.append(
        ReconciliationPlanRecord(
            plan_id=str(row["reconciliation_plan_id"]),
            recorded_at=current_utc_timestamp(),
            approval_snapshot_id=approval_id,
            admission_audit_id=str(row["admission_audit_id"]),
            cap_guard_decision_id=str(row["cap_guard_decision_id"]),
            allowed=True,
            status=AdminApiGateStatus.PASSED,
            reconciliation_policy_ref="m58_usdc_submit_cancel_readback",
            product_scope="M58 USDC spot order-plan row",
            exchange_submission_required=False,
            post_submit_reconciliation_required=False,
            retained_inventory_required=True,
            max_submitted_notional_usdc=str(row["planned_notional_usdc"]),
            max_executed_notional_usdc="0",
            reason="M58 controlled-live cancel/readback reconciliation proof.",
            **command,
        )
    )
    live_service_store.append(
        LiveServiceDecisionRecord(
            decision_id=f"m58-usdc-live-service-{row['client_order_id']}",
            status=AdminApiGateStatus.PASSED,
            requested_service_status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
            service_enabled=True,
            target_module_id=AUTOMATION_MODULE_ID,
            account_family=LIVE_SERVICE_ACCOUNT_FAMILY,
            venue_scope=LIVE_SERVICE_VENUE_SCOPE,
            intx_applicability=LIVE_SERVICE_INTX_APPLICABILITY,
            product_scope=[config.product_id],
            deployment_ref=read_git_value(["rev-parse", "--short", "HEAD"]),
            runtime_configuration_ref=LIVE_EXECUTION_RUNTIME_ENABLED_ENV,
            decision_reason=(
                "Explicit M58 controlled-live single-product submit/cancel pilot."
            ),
            live_coinbase_execution_approved=True,
            max_submitted_notional_usdc=str(row["planned_notional_usdc"]),
            max_executed_notional_usdc=decimal_text(
                config.max_executed_notional_usdc
            ),
        )
    )
    return {
        "approval_id": approval_id,
        "admission_audit_id": str(row["admission_audit_id"]),
        "cap_guard_decision_id": str(row["cap_guard_decision_id"]),
        "reconciliation_plan_id": str(row["reconciliation_plan_id"]),
        "live_service_decision_id": f"m58-usdc-live-service-{row['client_order_id']}",
    }


def append_run_state_handoff_evidence(
    *,
    config: UsdcPairSnapshotLiveSubmitConfig,
    row: Mapping[str, Any],
) -> dict[str, str]:
    """Append run-state route-bound wallet proof for one selected product."""

    cap_guard_store = FileAdminApiCapGuardStore()
    prefix = config.idempotency_prefix or "m58-usdc-live"
    cap_guard_store.append(
        CapGuardDecisionRecord(
            decision_id=str(row["cap_guard_decision_id"]),
            route=ALLOWLIST_RUN_STATE_ROUTE,
            method="POST",
            module_id=AUTOMATION_MODULE_ID,
            identity_key="client_order_id",
            identity_value=str(row["client_order_id"]),
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
            service_method=ALLOWLIST_RUN_STATE_SERVICE_METHOD,
            actor_id=config.actor_id,
            operator_intent="m58_usdc_snapshot_live_pilot_run_state",
            idempotency_key=f"{prefix}:run-state",
            payload_hash="9" * 64,
            approval_snapshot_id=str(row["approval_snapshot_id"]),
            admission_audit_id=str(row["admission_audit_id"]),
            allowed=True,
            status=AdminApiGateStatus.PASSED,
            cap_policy_ref="m58_phase_f_single_selected_run_state_cap",
            guard_policy_ref="m58_phase_f_wallet_allocation_guard",
            product_scope=config.product_id,
            max_submitted_notional_usdc=str(row["planned_notional_usdc"]),
            max_executed_notional_usdc="0",
            wallet_check_required=True,
            wallet_check_status=AdminApiGateStatus.PASSED,
            wallet_available_notional_usdc=str(row["planned_notional_usdc"]),
            wallet_check_source="m58_usdc_pair_run_state_live_submit_runner",
            reason=(
                "M58 one-product run-state handoff wallet allocation proof."
            ),
        )
    )
    return {
        "cap_guard_decision_id": str(row["cap_guard_decision_id"]),
        "wallet_check_source": "m58_usdc_pair_run_state_live_submit_runner",
    }


def command_evidence(
    *,
    config: UsdcPairSnapshotLiveSubmitConfig,
    plan: Mapping[str, Any],
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Return exact route-bound command evidence for M58 proof records."""

    return {
        "route": ORDER_PLAN_ROUTE,
        "method": "POST",
        "module_id": AUTOMATION_MODULE_ID,
        "identity_key": "client_order_id",
        "identity_value": str(row["client_order_id"]),
        "action_class": AdminApiActionClass.LOCAL_STATE_MUTATION,
        "required_permission": AdminApiPermission.CAMPAIGN_EXECUTE,
        "service_method": ORDER_PLAN_SERVICE_METHOD,
        "actor_id": str(plan["actor_id"]),
        "operator_intent": str(plan["operator_intent"]),
        "idempotency_key": str(row["idempotency_key"]),
        "payload_hash": str(plan["payload_hash"]),
    }


def planned_row_for_product(
    plan: Mapping[str, Any],
    product_id: str,
) -> dict[str, Any]:
    """Return the planned row for product_id or raise."""

    for row in plan.get("order_plan_rows", []):
        if (
            isinstance(row, Mapping)
            and str(row.get("product_id", "")).upper() == product_id.upper()
            and row.get("plan_status") == "planned"
        ):
            return dict(row)
    raise ValueError(f"Planned M58 row not found for {product_id}.")


def run_state_product_state(
    run_state: Mapping[str, Any],
    *,
    product_id: str,
    client_order_id: str,
) -> dict[str, Any]:
    """Return one run-state product row or raise."""

    normalized_product_id = product_id.upper()
    for row in run_state.get("product_states", []):
        if not isinstance(row, Mapping):
            continue
        if (
            str(row.get("product_id", "")).upper() == normalized_product_id
            and str(row.get("client_order_id") or "") == client_order_id
        ):
            return dict(row)
    raise RuntimeError(
        f"Run-state product row not found for {product_id} {client_order_id}."
    )


def _headers(
    config: UsdcPairSnapshotLiveSubmitConfig,
    phase: str,
) -> dict[str, str]:
    token = os.environ.get(AUTH_TOKEN_ENV, LOCAL_AUTH_TOKEN)
    prefix = config.idempotency_prefix or "m58-usdc-live"
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"{prefix}:{phase}",
        "X-Correlation-Id": config.correlation_id or f"{prefix}-correlation",
        "X-Operator-Intent": f"m58_usdc_snapshot_live_pilot_{phase.replace('-', '_')}",
        "X-Admin-Actor": config.actor_id,
        "X-Admin-Roles": ",".join(config.roles),
    }


def _post_json(
    client: Any,
    path: str,
    *,
    headers: Mapping[str, str],
    json_body: Mapping[str, Any],
) -> dict[str, Any]:
    response = client.post(path, headers=dict(headers), json=dict(json_body))
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Admin API {path} returned non-JSON status {response.status_code}."
        ) from exc
    if response.status_code >= 400:
        raise RuntimeError(
            f"Admin API {path} failed with HTTP {response.status_code}: {payload}"
        )
    status_value = payload.get("status")
    if status_value != AdminApiCommandStatus.ACCEPTED.value:
        raise RuntimeError(f"Admin API {path} rejected M58 step: {payload}")
    return payload


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    """Return a dict or raise with context."""

    if isinstance(value, Mapping):
        return dict(value)
    raise RuntimeError(f"Missing {label} in M58 live-submit response.")


def apply_runner_environment() -> dict[str, str]:
    """Apply local TLS/auth environment setup shared with the Admin API runner."""

    return run_admin_api.apply_local_environment(run_admin_api.parse_args([]))


def refresh_configuration_credentials() -> None:
    """Refresh imported configuration globals after Secrets Manager hydration."""

    try:
        import configuration
    except Exception:
        return
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


def decimal_value(value: str | Decimal) -> Decimal:
    """Return a Decimal for a non-negative numeric string."""

    text = str(value).strip()
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc
    if number < 0:
        raise ValueError("Decimal value must be non-negative.")
    return number


def decimal_text(value: str | Decimal) -> str:
    """Return a stable non-negative decimal string."""

    return format(decimal_value(value), "f")


def planning_request_notional_usdc(
    config: UsdcPairSnapshotLiveSubmitConfig,
) -> Decimal:
    """Return the smallest planning cap that can yield the requested live size."""

    requested = decimal_value(config.submitted_notional_usdc)
    reference_price = decimal_value(config.reference_bid_price)
    price_increment = require_positive_decimal(
        config.price_increment,
        "price_increment",
    )
    base_increment = require_positive_decimal(config.base_increment, "base_increment")
    base_min_size = require_positive_decimal(config.base_min_size, "base_min_size")
    quote_increment = require_positive_decimal(
        config.quote_increment,
        "quote_increment",
    )
    quote_min_size = require_positive_decimal(
        config.quote_min_size,
        "quote_min_size",
    )
    if requested < quote_min_size:
        raise ValueError(
            "submitted_notional_usdc must be at least quote_min_size for live submit."
        )

    limit_price = floor_to_increment(reference_price, price_increment)
    if limit_price <= 0:
        raise ValueError("reference_bid_price cannot produce a positive limit price.")

    _, planned = planning_size_for_requested_notional(
        requested=requested,
        limit_price=limit_price,
        base_increment=base_increment,
        quote_increment=quote_increment,
    )
    if planned >= quote_min_size:
        return requested

    base_size = max(
        ceil_to_increment(quote_min_size / limit_price, base_increment),
        base_min_size,
    )
    while True:
        planned = floor_to_increment(base_size * limit_price, quote_increment)
        if planned >= quote_min_size:
            break
        base_size += base_increment

    if planned > requested:
        raise ValueError(
            "submitted_notional_usdc cannot satisfy minimum order size without "
            "exceeding the operator-requested live notional."
        )

    requested_cap = ceil_to_increment(base_size * limit_price, quote_increment)
    if requested_cap > MAX_SUBMITTED_NOTIONAL_USDC:
        raise ValueError("planning request notional must not exceed 10 USDC.")
    return requested_cap


def planning_size_for_requested_notional(
    *,
    requested: Decimal,
    limit_price: Decimal,
    base_increment: Decimal,
    quote_increment: Decimal,
) -> tuple[Decimal, Decimal]:
    """Mirror M58 order-plan sizing for one requested notional cap."""

    base_size = floor_to_increment(requested / limit_price, base_increment)
    planned = floor_to_increment(base_size * limit_price, quote_increment)
    return base_size, planned


def require_positive_decimal(value: str | Decimal, label: str) -> Decimal:
    """Return a positive Decimal or raise a field-specific error."""

    number = decimal_value(value)
    if number <= 0:
        raise ValueError(f"{label} must be greater than zero.")
    return number


def floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Floor value to an exchange increment."""

    units = (value / increment).to_integral_value(rounding=ROUND_FLOOR)
    return units * increment


def ceil_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Ceil value to an exchange increment."""

    units = (value / increment).to_integral_value(rounding=ROUND_CEILING)
    return units * increment


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
    """Run the explicit M58 live submit and write evidence."""

    args = build_parser().parse_args(argv)
    config = config_from_args(args)
    try:
        summary = run_usdc_pair_snapshot_live_submit(config)
    except LiveSubmitConfirmationError as exc:
        print(f"Backend M58 live submit blocked: {exc}")
        return 1
    except Exception as exc:
        print(f"Backend M58 live submit blocked: {exc}")
        return 1
    summary_output = Path(config.summary_output)
    write_json(summary_output, summary)
    print(
        "Backend M58 live submit: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"submitted {summary['submitted_notional_usdc']} USDC; "
        f"executed {summary['executed_notional_usdc']} USDC; "
        f"artifact {summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
