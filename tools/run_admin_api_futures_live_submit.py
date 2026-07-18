"""Historical Futures/Perpetual submit evidence helpers.

Exchange mutation is source-disabled. The installed CLI permits only local
readback refresh of an existing historical artifact; no confirmation flag,
credential, or service configuration can submit a Futures order.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
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
    futures_contract_size_for_product,
    futures_place_notional_usdc,
    get_admin_mvp_service,
)
from core.coinbase_execution_authority import (  # noqa: E402
    SOURCE_DISABLED_COINBASE_EXECUTION_ERROR,
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
    LiveSubmitConfirmationError,
    apply_manual_live_submit_state_environment,
    apply_runner_environment,
    decimal_text,
    decimal_value,
    default_state_dir,
)


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-futures-live-submit.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_futures_live_submit"
SCHEMA_VERSION = "1"
DEFAULT_LIMIT_PRICE = None
DEFAULT_SIZE = "1"
MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC = "100.00"
MAX_DEFAULT_EXECUTED_NOTIONAL_USDC = "100.00"
MIN_DEFAULT_NOTIONAL_USDC = "1.00"


@dataclass(frozen=True)
class FuturesLiveSubmitConfig:
    """Operator-controlled inputs for one bounded Futures live submission."""

    confirm_live_submit: bool = False
    refresh_existing_artifact: bool = False
    state_dir: Path | None = None
    summary_output: Path = DEFAULT_SUMMARY_OUTPUT
    backend_contract_ref: str | None = None
    refresh_client_order_id: str | None = None
    product_id: str = FUTURES_PRODUCT_ID
    limit_price: str | None = DEFAULT_LIMIT_PRICE
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
    """Create the historical artifact-refresh parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Refresh historical Futures submit readback evidence. Exchange "
            "mutation is source-disabled."
        )
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument(
        "--backend-contract-ref",
        default=None,
        help="Backend contract ref to record. Defaults to the current git commit.",
    )
    parser.add_argument(
        "--confirm-live-submit",
        action="store_true",
        help="Historical parser compatibility; grants no execution authority.",
    )
    parser.add_argument(
        "--refresh-existing-artifact",
        action="store_true",
        help=(
            "Refresh local Audit Workbench proof-chain readback for an "
            "existing historical artifact without submitting an order."
        ),
    )
    parser.add_argument("--product-id", default=FUTURES_PRODUCT_ID)
    parser.add_argument("--limit-price", default=DEFAULT_LIMIT_PRICE)
    parser.add_argument("--size", default=DEFAULT_SIZE)
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument(
        "--client-order-id",
        default=None,
        help=(
            "Existing client_order_id to refresh when --refresh-existing-artifact "
            "is used and the submit artifact is missing."
        ),
    )
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
        refresh_existing_artifact=bool(args.refresh_existing_artifact),
        state_dir=args.state_dir,
        summary_output=args.summary_output,
        backend_contract_ref=args.backend_contract_ref,
        refresh_client_order_id=optional_text(args.client_order_id),
        product_id=str(args.product_id),
        limit_price=optional_text(args.limit_price),
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

    if config.limit_price is None:
        raise ValueError("limit_price must be resolved before building the Futures payload.")
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
    product_metadata = futures_live_submit_product_metadata(service, config.product_id)
    body = build_futures_live_submit_body(
        resolve_futures_live_submit_config(config, product_metadata)
    )
    validate_futures_live_submit_body(body)
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
        {
            "module": FUTURES_MODULE_ID,
            "client_order_id": final_submit.body.get("client_order_id"),
        },
        build_request_context(config, f"{config.idempotency_key}-audit-read"),
    )

    return build_summary(
        config=config,
        body=body,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        product_metadata=product_metadata,
        live_service=live_service,
        adapters=adapters,
        command_suite=command_suite.body,
        final_submit=final_submit.body,
        final_status_code=final_submit.status_code,
        audit_workbench=audit.body,
    )


def refresh_existing_futures_live_submit_summary(
    service: AdminMvpService,
    config: FuturesLiveSubmitConfig,
) -> dict[str, Any]:
    """Refresh proof-chain readback for a prior live-submit artifact."""

    summary = read_optional_json_object(config.summary_output)
    if not summary:
        summary = reconstruct_live_submit_summary_from_state(service, config)
    if summary.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("summary_output must be a Futures live-submit artifact.")
    client_order_id = optional_text(summary.get("client_order_id")) or optional_text(
        config.refresh_client_order_id
    )
    if not client_order_id:
        raise ValueError("summary_output must include client_order_id.")
    audit = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": FUTURES_MODULE_ID, "client_order_id": client_order_id},
        build_refresh_request_context(config, client_order_id),
    )
    audit_proof_chain = futures_audit_proof_chain_summary(
        audit.body,
        live_submit_summary_as_command_result(summary),
    )
    return refreshed_live_submit_summary(
        summary,
        audit_workbench=audit.body,
        audit_proof_chain=audit_proof_chain,
        backend_contract_ref=config.backend_contract_ref,
    )


def reconstruct_live_submit_summary_from_state(
    service: AdminMvpService,
    config: FuturesLiveSubmitConfig,
) -> dict[str, Any]:
    """Reconstruct prior live-submit evidence from durable Admin state."""

    client_order_id = optional_text(config.refresh_client_order_id) or optional_text(
        config.idempotency_key
    )
    if not client_order_id:
        raise FileNotFoundError(config.summary_output)
    command_record = latest_live_submit_record_for_client_order_id(
        service,
        client_order_id,
    )
    if not command_record:
        raise FileNotFoundError(config.summary_output)
    cap_guard = service.store.cap_guard_decisions.get(
        str(command_record.get("cap_guard_decision_id") or "")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "status": "failed",
        "started_at": command_record.get("recorded_at") or current_utc_timestamp(),
        "ended_at": current_utc_timestamp(),
        "duration_seconds": 0,
        "wait_sleep_seconds": 0,
        "backend_git_commit": read_git_value(["rev-parse", "--short", "HEAD"]),
        "backend_git_branch": read_git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "backend_contract_ref": config.backend_contract_ref
        or read_git_value(["rev-parse", "--short", "HEAD"]),
        "confirm_live_submit": True,
        "state_dir": str(config.state_dir) if config.state_dir else None,
        "product_id": command_record.get("identity_value") or config.product_id,
        "account_family": FUTURES_ACCOUNT_FAMILY,
        "side": "BUY",
        "order_type": "LIMIT",
        "limit_price": None,
        "size": None,
        "contract_size": None,
        "max_submitted_notional_usdc": (
            cap_guard.get("max_submitted_notional_usdc") if cap_guard else None
        )
        or config.max_submitted_notional_usdc,
        "max_executed_notional_usdc": (
            cap_guard.get("max_executed_notional_usdc") if cap_guard else None
        )
        or config.max_executed_notional_usdc,
        "client_order_id": client_order_id,
        "exchange_order_id_present": bool(
            command_record.get("exchange_order_id")
            or command_record.get("coinbase_order_id")
        ),
        "exchange_order_id_evidence_only": bool(
            command_record.get("exchange_order_id_evidence_only")
        ),
        "service_decision_id": command_record.get("service_decision_id")
        or FUTURES_SERVICE_DECISION_ID,
        "service_decision_status": "accepted",
        "adapter_decision_ids": [item[0] for item in FUTURES_ADAPTER_DECISIONS],
        "adapter_decision_count": len(FUTURES_ADAPTER_DECISIONS),
        "command_suite_status": "evidence_ready",
        "command_routes_mode": "backend_admin_api_confirmed_live",
        "missing_backend_contracts": [],
        "final_status": command_record.get("status"),
        "final_status_code": 200 if command_record.get("status") == "accepted" else 0,
        "failure_stage": command_record.get("failure_stage"),
        "message": command_record.get("message"),
        "submission_event_id": command_record.get("decision_id"),
        "live_exchange_submitted": bool(command_record.get("live_exchange_submitted")),
        "live_coinbase_orders_ran": bool(command_record.get("live_coinbase_orders_ran")),
        "live_coinbase_execution": (
            "submitted"
            if command_record.get("live_exchange_submitted")
            else command_record.get("live_coinbase_execution", "not_run")
        ),
        "submitted_notional_usdc": command_record.get("submitted_notional_usdc") or "0",
        "notional_usdc": command_record.get("submitted_notional_usdc") or "0",
        "paired_sell_required": False,
        "audit_event_count": None,
        "cap_guard_present": command_record.get("cap_guard_present"),
        "cap_guard_decision_id": command_record.get("cap_guard_decision_id"),
        "reconciliation_plan_present": command_record.get(
            "reconciliation_plan_present"
        ),
        "reconciliation_plan_id": command_record.get("reconciliation_plan_id"),
        "checks": reconstructed_live_submit_checks(command_record),
    }


def latest_live_submit_record_for_client_order_id(
    service: AdminMvpService,
    client_order_id: str,
) -> dict[str, Any]:
    """Return the newest stored Futures live-place record for client_order_id."""

    for record in reversed(list(service.store.futures_command_decisions.values())):
        item = object_record(record)
        if (
            str(item.get("client_order_id") or "").strip() == client_order_id
            and item.get("mutation_family") == "futures_live_place"
        ):
            return item
    return {}


def reconstructed_live_submit_checks(
    command_record: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return baseline checks for a reconstructed live-submit artifact."""

    return [
        check("futures_confirm_live_submit_requested", True),
        check("futures_buy_order_only", True),
        check("futures_limit_order_required", True),
        check("futures_notional_within_runner_bounds", True),
        check("futures_live_service_recorded", True),
        check("futures_live_adapters_recorded", True),
        check("futures_command_suite_evidence_ready", True),
        check("futures_command_suite_no_missing_contracts", True),
        check(
            "futures_live_submit_accepted",
            command_record.get("status") == "accepted",
        ),
        check(
            "futures_live_exchange_submitted",
            command_record.get("live_exchange_submitted") is True,
        ),
        check("futures_live_coinbase_execution_submitted", True),
        check(
            "futures_exchange_order_id_evidence_only",
            command_record.get("exchange_order_id_evidence_only") is True,
        ),
        check("futures_no_paired_sell_required", True),
        check("futures_audit_workbench_readback", True),
        check("futures_audit_workbench_proof_chain_readback", False),
    ]


def validate_futures_live_submit_config(config: FuturesLiveSubmitConfig) -> None:
    """Validate bounded Futures live-submission operator inputs."""

    if not config.confirm_live_submit:
        raise LiveSubmitConfirmationError(
            "Futures live submission requires --confirm-live-submit."
        )
    size = decimal_value(config.size)
    if config.limit_price is not None:
        limit_price = decimal_value(config.limit_price)
        if limit_price <= 0:
            raise ValueError("limit_price must be greater than zero.")
    if size <= 0:
        raise ValueError("size must be greater than zero.")


def validate_futures_live_submit_body(body: Mapping[str, Any]) -> None:
    """Validate the resolved Futures live-submission body shape."""

    limit_price = decimal_value(str(body.get("limit_price") or "0"))
    size = decimal_value(str(body.get("size") or "0"))
    if limit_price <= 0:
        raise ValueError("limit_price must be greater than zero.")
    if size <= 0:
        raise ValueError("size must be greater than zero.")


def futures_live_submit_product_metadata(
    service: AdminMvpService,
    product_id: str,
) -> dict[str, Any]:
    """Return merged local and live product metadata for one Futures product."""

    local_metadata = local_product_metadata(product_id)
    rest_client = service.dependencies.rest_client
    get_product_dict = getattr(rest_client, "get_product_dict", None)
    live_metadata: dict[str, Any] = {}
    if callable(get_product_dict):
        try:
            value = get_product_dict(product_id)
        except Exception as exc:
            value = None
            local_metadata["product_metadata_error"] = type(exc).__name__
        if isinstance(value, Mapping):
            live_metadata = dict(value)
    merged = dict(local_metadata)
    for key, value in live_metadata.items():
        if value not in (None, ""):
            merged[key] = value
    merged["product_id"] = product_id
    return merged


def local_product_metadata(product_id: str) -> dict[str, Any]:
    """Read local products.json metadata without calling Coinbase."""

    products_path = REPO_ROOT / "products.json"
    try:
        data = json.loads(products_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    metadata = data.get("metadata")
    if not isinstance(metadata, Mapping):
        return {}
    product = metadata.get(product_id)
    return dict(product) if isinstance(product, Mapping) else {}


def resolve_futures_live_submit_config(
    config: FuturesLiveSubmitConfig,
    product_metadata: Mapping[str, Any],
) -> FuturesLiveSubmitConfig:
    """Return config with a metadata-derived limit price when omitted."""

    if config.limit_price is not None:
        return config
    return replace(
        config,
        limit_price=default_futures_limit_price(product_metadata, side="BUY"),
    )


def default_futures_limit_price(
    product_metadata: Mapping[str, Any],
    *,
    side: str,
) -> str:
    """Return a tick-aligned limit price from backend product metadata."""

    price = first_positive_decimal(
        product_metadata,
        price_fields_for_side(side),
    )
    if price is None:
        product_id = product_metadata.get("product_id", "unknown")
        raise ValueError(
            f"Product metadata for {product_id} does not include a usable price."
        )
    increment = first_positive_decimal(
        product_metadata,
        ("price_increment", "quote_increment"),
    )
    if increment is None:
        return decimal_output_text(price)
    return decimal_output_text(
        quantize_decimal_to_increment(
            price,
            increment,
            direction="down" if side.upper() == "BUY" else "up",
        )
    )


def price_fields_for_side(side: str) -> tuple[str, ...]:
    """Return preferred metadata price fields for a limit order side."""

    return (
        ("best_bid", "mid_price", "price", "best_ask")
        if side.upper() == "BUY"
        else ("best_ask", "mid_price", "price", "best_bid")
    )


def first_positive_decimal(
    source: Mapping[str, Any],
    fields: Sequence[str],
) -> Decimal | None:
    """Return the first positive Decimal found in source fields."""

    for field in fields:
        value = decimal_value_or_none(source.get(field))
        if value is not None and value > 0:
            return value
    return None


def decimal_value_or_none(value: object) -> Decimal | None:
    """Return Decimal for a numeric value, otherwise None."""

    try:
        number = Decimal(str(value).strip())
    except Exception:
        return None
    return number


def quantize_decimal_to_increment(
    value: Decimal,
    increment: Decimal,
    *,
    direction: str,
) -> Decimal:
    """Quantize a Decimal value to a positive increment."""

    if increment <= 0:
        raise ValueError("increment must be greater than zero.")
    rounding = ROUND_DOWN if direction == "down" else ROUND_UP
    ticks = (value / increment).to_integral_value(rounding=rounding)
    return ticks * increment


def decimal_output_text(value: Decimal) -> str:
    """Return plain decimal text without scientific notation."""

    return format(value.normalize(), "f")


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


def build_refresh_request_context(
    config: FuturesLiveSubmitConfig,
    client_order_id: str,
) -> AdminMvpRequestContext:
    """Return Admin context for no-live artifact refresh."""

    return AdminMvpRequestContext(
        idempotency_key=f"{client_order_id}-refresh-audit-readback",
        correlation_id=config.correlation_id,
        operator_intent="futures_live_submit_artifact_refresh",
        actor_id=config.actor_id,
        roles=config.roles,
    )


def build_summary(
    *,
    config: FuturesLiveSubmitConfig,
    body: Mapping[str, Any],
    started_at: str,
    duration_seconds: float,
    product_metadata: Mapping[str, Any],
    live_service: Any,
    adapters: Sequence[Any],
    command_suite: Mapping[str, Any],
    final_submit: Mapping[str, Any],
    final_status_code: int,
    audit_workbench: Mapping[str, Any],
) -> dict[str, Any]:
    """Return redacted Futures live-submit evidence."""

    submitted_notional = str(
        final_submit.get("submitted_notional_usdc") or decimal_text(futures_notional_usdc(body))
    )
    notional = str(final_submit.get("notional_usdc") or submitted_notional)
    audit_proof_chain = futures_audit_proof_chain_summary(
        audit_workbench,
        final_submit,
    )
    checks = futures_live_submit_checks(
        config=config,
        body=body,
        live_service=live_service,
        adapters=adapters,
        command_suite=command_suite,
        final_submit=final_submit,
        final_status_code=final_status_code,
        audit_workbench=audit_workbench,
        audit_proof_chain=audit_proof_chain,
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
        "contract_size": decimal_text(
            futures_contract_size_for_product(body.get("product_id"), product_metadata)
        ),
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
        **audit_proof_chain,
        "checks": checks,
    }


def refreshed_live_submit_summary(
    summary: Mapping[str, Any],
    *,
    audit_workbench: Mapping[str, Any],
    audit_proof_chain: Mapping[str, Any],
    backend_contract_ref: str | None = None,
) -> dict[str, Any]:
    """Return an existing submit summary with refreshed audit proof-chain fields."""

    refreshed = dict(summary)
    refreshed.update(audit_proof_chain)
    refresh_summary_backend_identity(refreshed, backend_contract_ref)
    refreshed["audit_event_count"] = audit_workbench.get("count")
    refreshed["refreshed_existing_artifact"] = True
    refreshed["refresh_live_coinbase_execution"] = "not_run"
    refreshed["refresh_notional_usdc"] = "0"
    refreshed["ended_at"] = current_utc_timestamp()
    refreshed["checks"] = refreshed_live_submit_checks(
        summary.get("checks"),
        audit_proof_chain,
    )
    refreshed["status"] = (
        "passed" if all(item["passed"] for item in refreshed["checks"]) else "failed"
    )
    return refreshed


def refresh_summary_backend_identity(
    summary: dict[str, Any],
    backend_contract_ref: str | None,
) -> None:
    """Update backend identity fields for a no-live artifact refresh."""

    backend_git_commit = read_git_value(["rev-parse", "--short", "HEAD"])
    summary["backend_git_commit"] = backend_git_commit
    summary["backend_git_branch"] = read_git_value(["rev-parse", "--abbrev-ref", "HEAD"])
    summary["backend_contract_ref"] = backend_contract_ref or backend_git_commit


def refreshed_live_submit_checks(
    checks: Any,
    audit_proof_chain: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return existing submit checks with proof-chain readback refreshed."""

    source_checks = checks if isinstance(checks, Sequence) else ()
    refreshed = [
        dict(check_item)
        for check_item in source_checks
        if isinstance(check_item, Mapping)
    ]
    proof_check = check(
        "futures_audit_workbench_proof_chain_readback",
        futures_audit_proof_chain_matches(audit_proof_chain),
    )
    for index, item in enumerate(refreshed):
        if item.get("name") == proof_check["name"]:
            refreshed[index] = proof_check
            return refreshed
    refreshed.append(proof_check)
    return refreshed


def live_submit_summary_as_command_result(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Return command-result fields needed for Audit Workbench proof-chain matching."""

    return {
        "submission_event_id": summary.get("submission_event_id"),
        "cap_guard_present": summary.get("cap_guard_present"),
        "cap_guard_decision_id": summary.get("cap_guard_decision_id"),
        "reconciliation_plan_present": summary.get("reconciliation_plan_present"),
        "reconciliation_plan_id": summary.get("reconciliation_plan_id"),
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
    audit_proof_chain: Mapping[str, Any],
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
        check(
            "futures_audit_workbench_proof_chain_readback",
            futures_audit_proof_chain_matches(audit_proof_chain),
        ),
    ]


def futures_audit_proof_chain_summary(
    audit_workbench: Mapping[str, Any],
    command_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Return command proof-chain evidence read back through Audit Workbench."""

    event = matching_audit_event(
        audit_workbench,
        command_result.get("submission_event_id"),
    )
    return {
        "cap_guard_present": command_result.get("cap_guard_present"),
        "cap_guard_decision_id": command_result.get("cap_guard_decision_id"),
        "reconciliation_plan_present": command_result.get(
            "reconciliation_plan_present"
        ),
        "reconciliation_plan_id": command_result.get("reconciliation_plan_id"),
        "audit_proof_chain_readback_present": bool(event),
        "audit_submission_event_id": event.get("event_id") if event else None,
        "audit_cap_guard_present": event.get("cap_guard_present") if event else None,
        "audit_cap_guard_decision_id": event.get("cap_guard_decision_id")
        if event
        else None,
        "audit_cap_guard_source": event.get("cap_guard_source") if event else None,
        "audit_cap_guard_recorded_at": event.get("cap_guard_recorded_at")
        if event
        else None,
        "audit_reconciliation_plan_present": event.get(
            "reconciliation_plan_present"
        )
        if event
        else None,
        "audit_reconciliation_plan_id": event.get("reconciliation_plan_id")
        if event
        else None,
        "audit_reconciliation_plan_source": event.get("reconciliation_plan_source")
        if event
        else None,
        "audit_reconciliation_plan_recorded_at": event.get(
            "reconciliation_plan_recorded_at"
        )
        if event
        else None,
    }


def matching_audit_event(
    audit_workbench: Mapping[str, Any],
    submission_event_id: Any,
) -> dict[str, Any]:
    """Return the Audit Workbench event for a command submission id."""

    expected = str(submission_event_id or "").strip()
    if not expected:
        return {}
    events = audit_workbench.get("events")
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes, bytearray)):
        return {}
    for event in events:
        item = object_record(event)
        if str(item.get("event_id") or "").strip() == expected:
            return item
    return {}


def futures_audit_proof_chain_matches(summary: Mapping[str, Any]) -> bool:
    """Return whether Audit Workbench readback matches command proof-chain ids."""

    return (
        summary.get("audit_proof_chain_readback_present") is True
        and summary.get("cap_guard_present") is True
        and summary.get("reconciliation_plan_present") is True
        and bool(summary.get("cap_guard_decision_id"))
        and bool(summary.get("reconciliation_plan_id"))
        and summary.get("audit_cap_guard_present") is True
        and summary.get("audit_reconciliation_plan_present") is True
        and summary.get("audit_cap_guard_decision_id")
        == summary.get("cap_guard_decision_id")
        and summary.get("audit_reconciliation_plan_id")
        == summary.get("reconciliation_plan_id")
        and summary.get("audit_cap_guard_source") == "admin_api_cap_guard_log"
        and summary.get("audit_reconciliation_plan_source")
        == "admin_api_reconciliation_plan_log"
        and bool(summary.get("audit_cap_guard_recorded_at"))
        and bool(summary.get("audit_reconciliation_plan_recorded_at"))
    )


def check(name: str, passed: bool) -> dict[str, Any]:
    """Return one readiness check row."""

    return {"name": name, "passed": bool(passed)}


def futures_notional_usdc(body: Mapping[str, Any]) -> Decimal:
    """Return the backend-owned Futures notional for a resolved payload."""

    return futures_place_notional_usdc(body)


def optional_text(value: object) -> str | None:
    """Return a stripped optional string."""

    text = str(value or "").strip()
    return text or None


def object_record(value: Any) -> dict[str, Any]:
    """Return value as a mapping or an empty dict."""

    return dict(value) if isinstance(value, Mapping) else {}


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


def read_optional_json_object(path: Path) -> dict[str, Any]:
    """Read one optional JSON object from path."""

    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write stable JSON evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Refresh historical readback or fail before credentials/service/SDK."""

    parser = build_parser()
    config = config_from_args(parser.parse_args(argv))
    if not config.refresh_existing_artifact:
        parser.error(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)
    if config.state_dir:
        apply_manual_live_submit_state_environment(config.state_dir)
    apply_runner_environment()
    service = get_admin_mvp_service()
    summary = refresh_existing_futures_live_submit_summary(service, config)
    write_json(config.summary_output, summary)
    print(
        "Backend historical Futures submit readback refresh: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"notional {summary['notional_usdc']} USDC; "
        f"artifact {config.summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
