"""Run one explicit US CFM Futures/Perpetual live close/reduce submission.

This tool is intentionally manual. It never submits to Coinbase unless
``--confirm-live-close-reduce`` is passed, and the request still flows through
backend Admin Futures service evidence, live-adapter decisions, runtime opt-in,
cap evidence, and audit recording before the REST client is called.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
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
    futures_contract_size_for_product,
    futures_place_notional_usdc,
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
    default_futures_limit_price,
    futures_audit_proof_chain_matches,
    futures_audit_proof_chain_summary,
    futures_live_submit_product_metadata,
    live_submit_summary_as_command_result,
    read_optional_json_object,
    read_git_value,
    refresh_summary_backend_identity,
    refreshed_live_submit_checks,
    write_json,
)
from tools.run_admin_api_manual_order_live_submit import (  # noqa: E402
    LIVE_EXECUTION_ENV,
    apply_manual_live_submit_state_environment,
    apply_runner_environment,
    assert_live_credentials_present,
    decimal_text,
    decimal_value,
    default_state_dir,
)


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-futures-live-close-reduce.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_futures_live_close_reduce"
SCHEMA_VERSION = "1"
DEFAULT_LIMIT_PRICE = None
DEFAULT_SIZE = "1"
MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC = "100.00"
MAX_DEFAULT_EXECUTED_NOTIONAL_USDC = "100.00"
MIN_DEFAULT_NOTIONAL_USDC = "1.00"


class LiveCloseReduceConfirmationError(RuntimeError):
    """Raised when the live close/reduce confirmation flag is missing."""


@dataclass(frozen=True)
class FuturesLiveCloseReduceConfig:
    """Operator-controlled inputs for one bounded Futures close/reduce."""

    confirm_live_close_reduce: bool = False
    refresh_existing_artifact: bool = False
    state_dir: Path | None = None
    summary_output: Path = DEFAULT_SUMMARY_OUTPUT
    backend_contract_ref: str | None = None
    refresh_client_order_id: str | None = None
    product_id: str = FUTURES_PRODUCT_ID
    position_key: str | None = None
    limit_price: str | None = DEFAULT_LIMIT_PRICE
    size: str = DEFAULT_SIZE
    idempotency_key: str = "futures-live-close-reduce"
    correlation_id: str = "futures-live-close-reduce-correlation"
    actor_id: str = "local-operator"
    roles: tuple[str, ...] = ("admin", "trader")
    max_submitted_notional_usdc: str = MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC
    max_executed_notional_usdc: str = MAX_DEFAULT_EXECUTED_NOTIONAL_USDC


def build_parser() -> argparse.ArgumentParser:
    """Create the Futures live close/reduce parser."""

    parser = argparse.ArgumentParser(
        description="Submit one US CFM Futures close/reduce through backend Admin gates."
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument(
        "--backend-contract-ref",
        default=None,
        help="Backend contract ref to record. Defaults to the current git commit.",
    )
    parser.add_argument("--confirm-live-close-reduce", action="store_true")
    parser.add_argument(
        "--refresh-existing-artifact",
        action="store_true",
        help=(
            "Refresh Audit Workbench proof-chain readback for an existing "
            "live close/reduce artifact without submitting another request."
        ),
    )
    parser.add_argument(
        "--client-order-id",
        default=None,
        help="Existing client_order_id to refresh when the artifact is missing.",
    )
    parser.add_argument("--product-id", default=FUTURES_PRODUCT_ID)
    parser.add_argument("--position-key", default=None)
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
    return parser


def config_from_args(args: argparse.Namespace) -> FuturesLiveCloseReduceConfig:
    """Return normalized Futures live close/reduce configuration."""

    run_id = str(int(time.time()))
    idempotency_key = args.idempotency_key or f"futures-live-close-reduce-{run_id}"
    correlation_id = args.correlation_id or f"{idempotency_key}-correlation"
    roles = tuple(role.strip() for role in str(args.roles).split(",") if role.strip())
    return FuturesLiveCloseReduceConfig(
        confirm_live_close_reduce=bool(args.confirm_live_close_reduce),
        refresh_existing_artifact=bool(args.refresh_existing_artifact),
        state_dir=args.state_dir,
        summary_output=args.summary_output,
        backend_contract_ref=args.backend_contract_ref,
        refresh_client_order_id=optional_text(args.client_order_id),
        product_id=str(args.product_id),
        position_key=optional_text(args.position_key),
        limit_price=optional_text(args.limit_price),
        size=str(args.size),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        actor_id=str(args.actor_id),
        roles=roles or ("admin", "trader"),
        max_submitted_notional_usdc=str(args.max_submitted_notional_usdc),
        max_executed_notional_usdc=str(args.max_executed_notional_usdc),
    )


def build_futures_live_close_reduce_body(
    config: FuturesLiveCloseReduceConfig,
) -> dict[str, Any]:
    """Return the bounded Futures close/reduce payload."""

    if config.limit_price is None:
        raise ValueError("limit_price must be resolved before building the payload.")
    position_key = config.position_key or position_key_for_product(config.product_id)
    return {
        "position_key": position_key,
        "product_id": config.product_id,
        "limit_price": decimal_text(config.limit_price),
        "size": decimal_text(config.size),
        "dry_run": False,
        "manual_live_acknowledgement": True,
        "operator_reason": "operator confirmed backend-controlled futures close/reduce",
    }


def run_futures_live_close_reduce(
    service: AdminMvpService,
    config: FuturesLiveCloseReduceConfig,
) -> dict[str, Any]:
    """Record backend evidence, submit one live close/reduce, and summarize."""

    validate_futures_live_close_reduce_config(config)
    product_metadata = futures_live_submit_product_metadata(service, config.product_id)
    resolved_config = resolve_futures_live_close_reduce_config(
        config,
        product_metadata,
    )
    body = build_futures_live_close_reduce_body(resolved_config)
    validate_futures_live_close_reduce_body(body)
    started_at = current_utc_timestamp()
    started = time.perf_counter()

    live_service = record_futures_live_service_decision(service, resolved_config)
    adapters = record_futures_live_adapter_decisions(service, resolved_config)
    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        build_request_context(resolved_config, f"{resolved_config.idempotency_key}-suite-read"),
    )
    position_read = service.get_read_response(
        f"/api/v1/futures/positions/{resolved_config.position_key}",
        {},
        build_request_context(
            resolved_config,
            f"{resolved_config.idempotency_key}-position-read",
        ),
    )
    final_submit = service.submit_futures_command(
        f"/api/v1/futures/positions/{resolved_config.position_key}/close-reduce",
        body,
        build_request_context(resolved_config, resolved_config.idempotency_key),
    )
    audit = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {
            "module": FUTURES_MODULE_ID,
            "client_order_id": final_submit.body.get("client_order_id"),
        },
        build_request_context(resolved_config, f"{resolved_config.idempotency_key}-audit-read"),
    )

    return build_summary(
        config=resolved_config,
        body=body,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        product_metadata=product_metadata,
        live_service=live_service,
        adapters=adapters,
        command_suite=command_suite.body,
        position_read=position_read.body,
        final_submit=final_submit.body,
        final_status_code=final_submit.status_code,
        audit_workbench=audit.body,
    )


def refresh_existing_futures_live_close_reduce_summary(
    service: AdminMvpService,
    config: FuturesLiveCloseReduceConfig,
) -> dict[str, Any]:
    """Refresh proof-chain readback for a prior live close/reduce artifact."""

    summary = read_optional_json_object(config.summary_output)
    if summary.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("summary_output must be a Futures live close/reduce artifact.")
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
    return refreshed_live_close_reduce_summary(
        summary,
        audit_workbench=audit.body,
        audit_proof_chain=audit_proof_chain,
        backend_contract_ref=config.backend_contract_ref,
    )


def build_refresh_request_context(
    config: FuturesLiveCloseReduceConfig,
    client_order_id: str,
) -> AdminMvpRequestContext:
    """Return Admin context for no-live close/reduce artifact refresh."""

    return AdminMvpRequestContext(
        idempotency_key=f"{client_order_id}-refresh-audit-readback",
        correlation_id=config.correlation_id,
        operator_intent="futures_live_close_reduce_artifact_refresh",
        actor_id=config.actor_id,
        roles=config.roles,
    )


def validate_futures_live_close_reduce_config(
    config: FuturesLiveCloseReduceConfig,
) -> None:
    """Validate bounded Futures live close/reduce operator inputs."""

    if not config.confirm_live_close_reduce:
        raise LiveCloseReduceConfirmationError(
            "Futures live close/reduce requires --confirm-live-close-reduce."
        )
    if decimal_value(config.size) <= 0:
        raise ValueError("size must be greater than zero.")
    if config.limit_price is not None and decimal_value(config.limit_price) <= 0:
        raise ValueError("limit_price must be greater than zero.")
    if not str(config.product_id or "").strip():
        raise ValueError("product_id is required.")


def validate_futures_live_close_reduce_body(body: Mapping[str, Any]) -> None:
    """Validate the resolved Futures close/reduce payload shape."""

    if not str(body.get("position_key") or "").strip():
        raise ValueError("position_key is required.")
    if not str(body.get("product_id") or "").strip():
        raise ValueError("product_id is required.")
    if decimal_value(str(body.get("limit_price") or "0")) <= 0:
        raise ValueError("limit_price must be greater than zero.")
    if decimal_value(str(body.get("size") or "0")) <= 0:
        raise ValueError("size must be greater than zero.")


def resolve_futures_live_close_reduce_config(
    config: FuturesLiveCloseReduceConfig,
    product_metadata: Mapping[str, Any],
) -> FuturesLiveCloseReduceConfig:
    """Return config with route identity and metadata-derived price evidence."""

    position_key = config.position_key or position_key_for_product(config.product_id)
    limit_price = config.limit_price or default_futures_limit_price(
        product_metadata,
        side="SELL",
    )
    return replace(config, position_key=position_key, limit_price=limit_price)


def build_request_context(
    config: FuturesLiveCloseReduceConfig,
    idempotency_key: str,
) -> AdminMvpRequestContext:
    """Return Admin request context for one close/reduce phase."""

    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id=config.correlation_id,
        operator_intent="futures_live_close_reduce",
        actor_id=config.actor_id,
        roles=config.roles,
    )


def build_summary(
    *,
    config: FuturesLiveCloseReduceConfig,
    body: Mapping[str, Any],
    started_at: str,
    duration_seconds: float,
    product_metadata: Mapping[str, Any],
    live_service: Any,
    adapters: Sequence[Any],
    command_suite: Mapping[str, Any],
    position_read: Mapping[str, Any],
    final_submit: Mapping[str, Any],
    final_status_code: int,
    audit_workbench: Mapping[str, Any],
) -> dict[str, Any]:
    """Return redacted Futures close/reduce evidence."""

    submitted_notional = str(
        final_submit.get("submitted_notional_usdc")
        or decimal_text(futures_notional_usdc(body))
    )
    notional = str(final_submit.get("notional_usdc") or submitted_notional)
    audit_proof_chain = futures_audit_proof_chain_summary(
        audit_workbench,
        final_submit,
    )
    checks = futures_live_close_reduce_checks(
        config=config,
        body=body,
        live_service=live_service,
        adapters=adapters,
        command_suite=command_suite,
        position_read=position_read,
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
        "confirm_live_close_reduce": config.confirm_live_close_reduce,
        "state_dir": str(config.state_dir) if config.state_dir else None,
        "position_key": body.get("position_key"),
        "product_id": body.get("product_id"),
        "account_family": FUTURES_ACCOUNT_FAMILY,
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
        "position_read_found": bool(position_read.get("found")),
        "position_read_product_id": object_record(position_read.get("position")).get(
            "product_id"
        ),
        "position_read_side_present": position_side_present(
            object_record(position_read.get("position"))
        ),
        "position_read_contracts_at_least_requested": position_contracts_at_least_requested(
            object_record(position_read.get("position")),
            body,
        ),
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
        "audit_event_count": audit_workbench.get("count"),
        **audit_proof_chain,
        "checks": checks,
    }


def refreshed_live_close_reduce_summary(
    summary: Mapping[str, Any],
    *,
    audit_workbench: Mapping[str, Any],
    audit_proof_chain: Mapping[str, Any],
    backend_contract_ref: str | None = None,
) -> dict[str, Any]:
    """Return an existing close/reduce summary with refreshed audit fields."""

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


def futures_live_close_reduce_checks(
    *,
    config: FuturesLiveCloseReduceConfig,
    body: Mapping[str, Any],
    live_service: Any,
    adapters: Sequence[Any],
    command_suite: Mapping[str, Any],
    position_read: Mapping[str, Any],
    final_submit: Mapping[str, Any],
    final_status_code: int,
    audit_workbench: Mapping[str, Any],
    audit_proof_chain: Mapping[str, Any],
    notional_usdc: str,
) -> list[dict[str, Any]]:
    """Return pass/fail checks for the close/reduce artifact."""

    notional = decimal_value(notional_usdc)
    position = object_record(position_read.get("position"))
    return [
        check(
            "futures_confirm_live_close_reduce_requested",
            config.confirm_live_close_reduce,
        ),
        check("futures_position_key_present", bool(body.get("position_key"))),
        check("futures_product_id_present", bool(body.get("product_id"))),
        check(
            "futures_close_reduce_position_readback",
            position_read.get("found") is True
            and position.get("product_id") == body.get("product_id"),
        ),
        check("futures_close_reduce_position_side_present", position_side_present(position)),
        check(
            "futures_close_reduce_position_contracts_cover_request",
            position_contracts_at_least_requested(position, body),
        ),
        check(
            "futures_close_reduce_notional_within_runner_bounds",
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
            "futures_live_close_reduce_accepted",
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
        check("futures_audit_workbench_readback", audit_workbench.get("count", 0) >= 1),
        check(
            "futures_audit_workbench_proof_chain_readback",
            futures_audit_proof_chain_matches(audit_proof_chain),
        ),
    ]


def futures_notional_usdc(body: Mapping[str, Any]) -> Decimal:
    """Return the backend-owned Futures notional for close/reduce evidence."""

    return futures_place_notional_usdc(body)


def position_key_for_product(product_id: str) -> str:
    """Return the Admin position key for a configured product id."""

    return f"futures_position:runtime:{product_id}"


def optional_text(value: object) -> str | None:
    """Return a stripped optional string."""

    text = str(value or "").strip()
    return text or None


def object_record(value: Any) -> dict[str, Any]:
    """Return value as a mapping or an empty dict."""

    return dict(value) if isinstance(value, Mapping) else {}


def position_side_present(position: Mapping[str, Any]) -> bool:
    """Return whether the position read exposes a usable side."""

    return str(position.get("position_side") or "").strip().upper() not in {"", "UNKNOWN"}


def position_contracts_at_least_requested(
    position: Mapping[str, Any],
    body: Mapping[str, Any],
) -> bool:
    """Return whether the observed contracts cover the requested close size."""

    observed = decimal_value(str(position.get("number_of_contracts") or "0"))
    requested = decimal_value(str(body.get("size") or "0"))
    return requested > 0 and observed >= requested


def main(argv: Sequence[str] | None = None) -> int:
    """Run the explicit Futures live close/reduce and write evidence."""

    config = config_from_args(build_parser().parse_args(argv))
    if not config.confirm_live_close_reduce and not config.refresh_existing_artifact:
        raise LiveCloseReduceConfirmationError(
            "Futures live close/reduce requires --confirm-live-close-reduce."
        )
    if not config.refresh_existing_artifact:
        assert_live_credentials_present(os.environ)
    if config.state_dir:
        apply_manual_live_submit_state_environment(config.state_dir)
    if not config.refresh_existing_artifact:
        os.environ[LIVE_EXECUTION_ENV] = "1"
    apply_runner_environment()
    service = get_admin_mvp_service()
    summary = (
        refresh_existing_futures_live_close_reduce_summary(service, config)
        if config.refresh_existing_artifact
        else run_futures_live_close_reduce(service, config)
    )
    write_json(config.summary_output, summary)
    print(
        "Backend Futures live close/reduce: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"notional {summary['notional_usdc']} USDC; "
        f"artifact {config.summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
