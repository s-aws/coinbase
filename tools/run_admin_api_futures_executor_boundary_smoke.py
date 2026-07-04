"""Record and verify US CFM Futures executor-boundary evidence.

This smoke records backend-owned Futures/Perpetual live-service and
live-adapter decision evidence, submits one valid route-bound Futures draft,
then submits explicitly confirmed Futures place and cancel requests plus one
Futures reconciliation execution request. It verifies the draft is rejected at
the disabled executor boundary, the confirmed exchange requests are rejected
before Coinbase because the local no-live runtime remains disabled, and
reconciliation records local evidence without Coinbase or exchange mutation.
It is intentionally no-live.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
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
    AdminMvpCommandStatus,
    AdminMvpRequestContext,
    AdminMvpService,
    get_admin_mvp_service,
)
from tools import run_admin_api  # noqa: E402
from tools.run_admin_api_manual_order_live_submit import (  # noqa: E402
    apply_manual_live_submit_state_environment,
    default_state_dir,
)


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-futures-executor-boundary-smoke.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_futures_executor_boundary_smoke"
SCHEMA_VERSION = "1"
LIVE_COINBASE_EXECUTION = "not_run"
NOTIONAL_USDC = "0"
FUTURES_MODULE_ID = "futures_perpetuals"
FUTURES_ACCOUNT_FAMILY = "coinbase_futures_us_cfm"
FUTURES_INTX_APPLICABILITY = "not_applicable_us_account"
FUTURES_PRODUCT_ID = "AVP-20DEC30-CDE"
FUTURES_MAX_SUBMITTED_NOTIONAL_USDC = "100.00"
FUTURES_MAX_EXECUTED_NOTIONAL_USDC = "100.00"
FUTURES_COMMAND_ROUTE = "/api/v1/futures/orders"
FUTURES_COMMAND_SERVICE_METHOD = "place_futures_order"
FUTURES_CANCEL_CLIENT_ORDER_ID = "futures-executor-boundary-client-order"
FUTURES_CANCEL_COMMAND_ROUTE = (
    f"/api/v1/futures/orders/{FUTURES_CANCEL_CLIENT_ORDER_ID}/cancel"
)
FUTURES_RECONCILIATION_POSITION_KEY = "futures_position:runtime:BIP-20DEC30-CDE"
FUTURES_RECONCILIATION_COMMAND_ROUTE = (
    f"/api/v1/futures/positions/{FUTURES_RECONCILIATION_POSITION_KEY}/reconciliation"
)
FUTURES_SERVICE_DECISION_ID = "futures-us-cfm-live-service"
FUTURES_ADAPTER_DECISIONS = (
    (
        "futures-us-cfm-place-adapter",
        "/api/v1/futures/orders",
        "place_futures_order",
    ),
    (
        "futures-us-cfm-close-reduce-adapter",
        "/api/v1/futures/positions/{position_key}/close-reduce",
        "close_or_reduce_futures_position",
    ),
    (
        "futures-us-cfm-cancel-adapter",
        "/api/v1/futures/orders/{client_order_id}/cancel",
        "cancel_futures_order",
    ),
    (
        "futures-us-cfm-reconcile-adapter",
        "/api/v1/futures/positions/{position_key}/reconciliation",
        "reconcile_futures_position",
    ),
)


@dataclass(frozen=True)
class FuturesBoundarySmokeConfig:
    """Operator-independent inputs for the no-live boundary smoke."""

    state_dir: Path
    summary_output: Path
    backend_contract_ref: str | None
    product_id: str = FUTURES_PRODUCT_ID
    limit_price: str = "0.50"
    size: str = "1"
    actor_id: str = "local-operator"
    roles: tuple[str, ...] = ("admin", "trader")


def build_parser() -> argparse.ArgumentParser:
    """Create the Futures executor-boundary smoke parser."""

    parser = argparse.ArgumentParser(
        description="Record no-live US CFM Futures executor-boundary evidence."
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument(
        "--backend-contract-ref",
        default=None,
        help="Backend contract ref to record. Defaults to the current git commit.",
    )
    parser.add_argument("--product-id", default=FUTURES_PRODUCT_ID)
    parser.add_argument("--limit-price", default="0.50")
    parser.add_argument("--size", default="1")
    parser.add_argument("--actor-id", default="local-operator")
    parser.add_argument("--roles", default="admin,trader")
    return parser


def config_from_args(args: argparse.Namespace) -> FuturesBoundarySmokeConfig:
    """Return normalized smoke configuration from parsed arguments."""

    roles = tuple(role.strip() for role in str(args.roles).split(",") if role.strip())
    return FuturesBoundarySmokeConfig(
        state_dir=args.state_dir,
        summary_output=args.summary_output,
        backend_contract_ref=args.backend_contract_ref,
        product_id=str(args.product_id),
        limit_price=str(args.limit_price),
        size=str(args.size),
        actor_id=str(args.actor_id),
        roles=roles or ("admin", "trader"),
    )


def apply_runner_environment(config: FuturesBoundarySmokeConfig) -> dict[str, str]:
    """Apply local Admin API environment and durable state paths."""

    os.environ.pop("COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED", None)
    os.environ.pop("COINBASE_ADMIN_LIVE_COINBASE_EXECUTION", None)
    applied = run_admin_api.apply_local_environment(run_admin_api.parse_args([]))
    applied.update(apply_manual_live_submit_state_environment(config.state_dir))
    applied["COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED"] = "disabled"
    return applied


def build_context(
    config: FuturesBoundarySmokeConfig,
    idempotency_key: str,
) -> AdminMvpRequestContext:
    """Return an Admin request context for one smoke phase."""

    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id="futures-executor-boundary-smoke",
        operator_intent="futures_executor_boundary_smoke",
        actor_id=config.actor_id,
        roles=config.roles,
    )


def record_futures_live_service_decision(
    service: AdminMvpService,
    config: FuturesBoundarySmokeConfig,
) -> Any:
    """Record backend-owned US CFM Futures live-service evidence."""

    return service.record_live_service_decision(
        {
            "decision_id": FUTURES_SERVICE_DECISION_ID,
            "status": "passed",
            "requested_service_status": "approval_required",
            "service_enabled": True,
            "target_module_id": FUTURES_MODULE_ID,
            "account_family": FUTURES_ACCOUNT_FAMILY,
            "venue_scope": FUTURES_ACCOUNT_FAMILY,
            "intx_applicability": FUTURES_INTX_APPLICABILITY,
            "product_scope": [config.product_id],
            "live_coinbase_execution_approved": True,
            "max_submitted_notional_usdc": FUTURES_MAX_SUBMITTED_NOTIONAL_USDC,
            "max_executed_notional_usdc": FUTURES_MAX_EXECUTED_NOTIONAL_USDC,
            "deployment_ref": "coinbase-local",
            "runtime_configuration_ref": "coinbase-local-runtime",
            "decision_reason": (
                "Record US CFM Futures/Perpetual backend live-service evidence "
                "for local Admin operation."
            ),
        },
        build_context(config, FUTURES_SERVICE_DECISION_ID),
    )


def record_futures_live_adapter_decisions(
    service: AdminMvpService,
    config: FuturesBoundarySmokeConfig,
) -> list[Any]:
    """Record backend-owned US CFM Futures live-adapter evidence."""

    results = []
    for decision_id, route, service_method in FUTURES_ADAPTER_DECISIONS:
        results.append(
            service.record_live_adapter_decision(
                {
                    "decision_id": decision_id,
                    "status": "passed",
                    "requested_adapter_status": "approval_required",
                    "target_route": route,
                    "target_method": "POST",
                    "target_module_id": FUTURES_MODULE_ID,
                    "target_service_method": service_method,
                    "account_family": FUTURES_ACCOUNT_FAMILY,
                    "venue_scope": FUTURES_ACCOUNT_FAMILY,
                    "intx_applicability": FUTURES_INTX_APPLICABILITY,
                    "product_scope": [config.product_id],
                    "adapter_reference": f"AdminApiCommandService.{service_method}",
                    "adapter_constructed": True,
                    "adapter_enabled": True,
                    "live_coinbase_execution_approved": True,
                    "max_submitted_notional_usdc": FUTURES_MAX_SUBMITTED_NOTIONAL_USDC,
                    "max_executed_notional_usdc": FUTURES_MAX_EXECUTED_NOTIONAL_USDC,
                    "construction_review_ref": "futures-us-cfm-adapter-construction-review",
                    "decision_reason": (
                        "Record US CFM Futures/Perpetual backend live-adapter "
                        "evidence for local Admin operation."
                    ),
                },
                build_context(config, decision_id),
            )
        )
    return results


def build_futures_place_body(config: FuturesBoundarySmokeConfig) -> dict[str, Any]:
    """Return a valid no-live Futures place draft payload."""

    return {
        "product_id": config.product_id,
        "side": "BUY",
        "order_type": "LIMIT",
        "limit_price": config.limit_price,
        "size": config.size,
    }


def build_confirmed_futures_place_body(
    config: FuturesBoundarySmokeConfig,
) -> dict[str, Any]:
    """Return a confirmed Futures place payload for no-live runtime rejection."""

    body = build_futures_place_body(config)
    body.update(
        {
            "dry_run": False,
            "manual_live_acknowledgement": True,
        }
    )
    return body


def build_confirmed_futures_cancel_body(
    config: FuturesBoundarySmokeConfig,
) -> dict[str, Any]:
    """Return a confirmed Futures cancel payload for no-live runtime rejection."""

    return {
        "product_id": config.product_id,
        "dry_run": False,
        "manual_live_acknowledgement": True,
    }


def build_futures_reconciliation_boundary_body() -> dict[str, Any]:
    """Return a Futures reconciliation payload for local execution evidence."""

    return {
        "reconciliation_reason": "executor_boundary_reconciliation_review",
        "dry_run": False,
        "manual_live_acknowledgement": True,
    }


def run_futures_boundary_smoke(
    service: AdminMvpService,
    config: FuturesBoundarySmokeConfig,
) -> dict[str, Any]:
    """Record decisions, submit draft/confirmed commands, and return evidence."""

    started_at = current_utc_timestamp()
    started = time.perf_counter()
    live_service = record_futures_live_service_decision(service, config)
    adapters = record_futures_live_adapter_decisions(service, config)
    suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        build_context(config, "futures-executor-boundary-suite-read"),
    )
    draft = service.submit_futures_command(
        FUTURES_COMMAND_ROUTE,
        build_futures_place_body(config),
        build_context(config, "futures-executor-boundary-place-draft"),
    )
    confirmed = service.submit_futures_command(
        FUTURES_COMMAND_ROUTE,
        build_confirmed_futures_place_body(config),
        build_context(config, "futures-executor-boundary-confirmed-place"),
    )
    confirmed_cancel = service.submit_futures_command(
        FUTURES_CANCEL_COMMAND_ROUTE,
        build_confirmed_futures_cancel_body(config),
        build_context(config, "futures-executor-boundary-confirmed-cancel"),
    )
    reconciliation = service.submit_futures_command(
        FUTURES_RECONCILIATION_COMMAND_ROUTE,
        build_futures_reconciliation_boundary_body(),
        build_context(config, "futures-executor-boundary-reconciliation"),
    )
    audit = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": FUTURES_MODULE_ID},
        build_context(config, "futures-executor-boundary-audit-read"),
    )
    return build_summary(
        config=config,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        live_service=live_service,
        adapters=adapters,
        command_suite=suite.body,
        command_result=draft.body,
        command_status_code=draft.status_code,
        confirmed_command_result=confirmed.body,
        confirmed_command_status_code=confirmed.status_code,
        confirmed_cancel_command_result=confirmed_cancel.body,
        confirmed_cancel_command_status_code=confirmed_cancel.status_code,
        reconciliation_command_result=reconciliation.body,
        reconciliation_command_status_code=reconciliation.status_code,
        audit_workbench=audit.body,
    )


def build_summary(
    *,
    config: FuturesBoundarySmokeConfig,
    started_at: str,
    duration_seconds: float,
    live_service: Any,
    adapters: Sequence[Any],
    command_suite: Mapping[str, Any],
    command_result: Mapping[str, Any],
    command_status_code: int,
    confirmed_command_result: Mapping[str, Any],
    confirmed_command_status_code: int,
    confirmed_cancel_command_result: Mapping[str, Any],
    confirmed_cancel_command_status_code: int,
    reconciliation_command_result: Mapping[str, Any],
    reconciliation_command_status_code: int,
    audit_workbench: Mapping[str, Any],
) -> dict[str, Any]:
    """Return redacted Futures executor-boundary smoke evidence."""

    live_decision = object_record(command_suite.get("futures_live_decision_evidence"))
    checks = futures_boundary_checks(
        live_service=live_service,
        adapters=adapters,
        command_suite=command_suite,
        command_result=command_result,
        command_status_code=command_status_code,
        confirmed_command_result=confirmed_command_result,
        confirmed_command_status_code=confirmed_command_status_code,
        confirmed_cancel_command_result=confirmed_cancel_command_result,
        confirmed_cancel_command_status_code=confirmed_cancel_command_status_code,
        reconciliation_command_result=reconciliation_command_result,
        reconciliation_command_status_code=reconciliation_command_status_code,
        audit_workbench=audit_workbench,
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
        "state_dir": str(config.state_dir),
        "product_id": config.product_id,
        "checks": checks,
        "service_decision_id": FUTURES_SERVICE_DECISION_ID,
        "adapter_decision_ids": [item[0] for item in FUTURES_ADAPTER_DECISIONS],
        "command_suite_status": command_suite.get("status"),
        "command_routes_mode": command_suite.get("command_routes_mode"),
        "missing_backend_contracts": command_suite.get("missing_backend_contracts"),
        "resolved_backend_contracts": command_suite.get("resolved_backend_contracts"),
        "futures_risk_proof_count": command_suite.get("futures_risk_proof_count"),
        "blocked_command_count": command_suite.get("blocked_command_count"),
        "executable_command_count": command_suite.get("executable_command_count"),
        "service_decision_status": live_decision.get("service_decision_status"),
        "adapter_decision_ready_count": live_decision.get("adapter_decision_ready_count"),
        "adapter_decision_missing_count": live_decision.get(
            "adapter_decision_missing_count"
        ),
        "executor_boundary_status": live_decision.get("executor_boundary_status"),
        "executor_boundary_ready": live_decision.get("executor_boundary_ready"),
        "first_blocker": live_decision.get("first_blocker"),
        "command_status": command_result.get("status"),
        "command_status_code": command_status_code,
        "failure_stage": command_result.get("failure_stage"),
        "executor_decision_id": command_result.get("executor_decision_id"),
        "confirmed_command_status": confirmed_command_result.get("status"),
        "confirmed_command_status_code": confirmed_command_status_code,
        "confirmed_failure_stage": confirmed_command_result.get("failure_stage"),
        "confirmed_submission_event_id": confirmed_command_result.get(
            "submission_event_id"
        ),
        "confirmed_submitted_notional_usdc": confirmed_command_result.get(
            "submitted_notional_usdc"
        ),
        "confirmed_live_exchange_submitted": bool(
            confirmed_command_result.get("live_exchange_submitted")
        ),
        "confirmed_live_coinbase_orders_ran": bool(
            confirmed_command_result.get("live_coinbase_orders_ran")
        ),
        "confirmed_cancel_command_status": confirmed_cancel_command_result.get(
            "status"
        ),
        "confirmed_cancel_command_status_code": confirmed_cancel_command_status_code,
        "confirmed_cancel_failure_stage": confirmed_cancel_command_result.get(
            "failure_stage"
        ),
        "confirmed_cancel_submission_event_id": confirmed_cancel_command_result.get(
            "submission_event_id"
        ),
        "confirmed_cancel_client_order_id": confirmed_cancel_command_result.get(
            "client_order_id"
        ),
        "confirmed_cancel_submitted_notional_usdc": confirmed_cancel_command_result.get(
            "submitted_notional_usdc"
        ),
        "confirmed_cancel_live_exchange_submitted": bool(
            confirmed_cancel_command_result.get("live_exchange_submitted")
        ),
        "confirmed_cancel_live_coinbase_orders_ran": bool(
            confirmed_cancel_command_result.get("live_coinbase_orders_ran")
        ),
        "reconciliation_command_status": reconciliation_command_result.get("status"),
        "reconciliation_command_status_code": reconciliation_command_status_code,
        "reconciliation_failure_stage": reconciliation_command_result.get(
            "failure_stage"
        ),
        "reconciliation_submission_event_id": reconciliation_command_result.get(
            "submission_event_id"
        ),
        "reconciliation_execution_id": reconciliation_command_result.get(
            "futures_reconciliation_execution_id"
        ),
        "reconciliation_plan_id": reconciliation_command_result.get(
            "reconciliation_plan_id"
        ),
        "reconciliation_plan_created": bool(
            reconciliation_command_result.get("reconciliation_plan_created")
        ),
        "reconciliation_position_key": reconciliation_command_result.get(
            "identity_value"
        ),
        "reconciliation_execution_allowed": bool(
            reconciliation_command_result.get("reconciliation_execution_allowed")
        ),
        "reconciliation_execution_ran": bool(
            reconciliation_command_result.get("reconciliation_execution_ran")
        ),
        "reconciliation_plan_required": bool(
            reconciliation_command_result.get("reconciliation_plan_required")
        ),
        "reconciliation_local_state_mutated": bool(
            reconciliation_command_result.get("local_state_mutated")
        ),
        "reconciliation_exchange_state_mutated": bool(
            reconciliation_command_result.get("exchange_state_mutated")
        ),
        "reconciliation_live_exchange_submitted": bool(
            reconciliation_command_result.get("live_exchange_submitted")
        ),
        "reconciliation_live_coinbase_orders_ran": bool(
            reconciliation_command_result.get("live_coinbase_orders_ran")
        ),
        "audit_event_count": audit_workbench.get("count"),
        "live_exchange_submitted": bool(command_result.get("live_exchange_submitted")),
        "live_coinbase_orders_ran": bool(command_result.get("live_coinbase_orders_ran"))
        or bool(confirmed_command_result.get("live_coinbase_orders_ran"))
        or bool(confirmed_cancel_command_result.get("live_coinbase_orders_ran"))
        or bool(reconciliation_command_result.get("live_coinbase_orders_ran")),
        "live_coinbase_execution": LIVE_COINBASE_EXECUTION,
        "notional_usdc": NOTIONAL_USDC,
    }


def futures_boundary_checks(
    *,
    live_service: Any,
    adapters: Sequence[Any],
    command_suite: Mapping[str, Any],
    command_result: Mapping[str, Any],
    command_status_code: int,
    confirmed_command_result: Mapping[str, Any],
    confirmed_command_status_code: int,
    confirmed_cancel_command_result: Mapping[str, Any],
    confirmed_cancel_command_status_code: int,
    reconciliation_command_result: Mapping[str, Any],
    reconciliation_command_status_code: int,
    audit_workbench: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return pass/fail checks for disabled executor-boundary readiness."""

    live_decision = object_record(command_suite.get("futures_live_decision_evidence"))
    return [
        check("futures_live_service_recorded", live_service.status_code == 200),
        check(
            "futures_live_adapters_recorded",
            len(adapters) == len(FUTURES_ADAPTER_DECISIONS)
            and all(result.status_code == 200 for result in adapters),
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
            "futures_service_decision_ready",
            live_decision.get("service_decision_status") == "ready",
        ),
        check(
            "futures_all_adapters_ready",
            live_decision.get("adapter_decision_missing_count") == 0,
        ),
        check(
            "futures_executor_boundary_ready",
            live_decision.get("executor_boundary_ready") is True,
        ),
        check(
            "futures_executor_disabled_blocker",
            live_decision.get("first_blocker") == "futures_executor_live_disabled",
        ),
        check(
            "futures_place_rejected_at_executor",
            command_status_code == 400
            and command_result.get("failure_stage")
            == "futures_executor_live_disabled",
        ),
        check(
            "futures_confirmed_place_rejected_before_coinbase",
            confirmed_command_status_code == 400
            and confirmed_command_result.get("failure_stage")
            == "futures_live_runtime_disabled"
            and confirmed_command_result.get("submitted_notional_usdc") == "0"
            and confirmed_command_result.get("live_exchange_submitted") is False
            and confirmed_command_result.get("live_coinbase_orders_ran") is False,
        ),
        check(
            "futures_executor_event_recorded",
            bool(command_result.get("executor_decision_id")),
        ),
        check(
            "futures_confirmed_place_event_recorded",
            bool(confirmed_command_result.get("submission_event_id")),
        ),
        check(
            "futures_confirmed_cancel_rejected_before_coinbase",
            confirmed_cancel_command_status_code == 400
            and confirmed_cancel_command_result.get("failure_stage")
            == "futures_live_runtime_disabled"
            and confirmed_cancel_command_result.get("submitted_notional_usdc") == "0"
            and confirmed_cancel_command_result.get("client_order_id")
            == FUTURES_CANCEL_CLIENT_ORDER_ID
            and confirmed_cancel_command_result.get("live_exchange_submitted") is False
            and confirmed_cancel_command_result.get("live_coinbase_orders_ran") is False,
        ),
        check(
            "futures_confirmed_cancel_event_recorded",
            bool(confirmed_cancel_command_result.get("submission_event_id")),
        ),
        check(
            "futures_reconciliation_execution_recorded",
            reconciliation_command_status_code == 200
            and reconciliation_command_result.get("command") == "futures_reconcile"
            and reconciliation_command_result.get("mutation_family")
            == "futures_reconciliation_execution"
            and reconciliation_command_result.get("status")
            == AdminMvpCommandStatus.ACCEPTED.value
            and reconciliation_command_result.get("failure_stage") is None
            and bool(
                reconciliation_command_result.get(
                    "futures_reconciliation_execution_id"
                )
            )
            and bool(reconciliation_command_result.get("reconciliation_plan_id"))
            and reconciliation_command_result.get("reconciliation_plan_created") is True,
        ),
        check(
            "futures_reconciliation_execution_no_coinbase",
            reconciliation_command_result.get("reconciliation_execution_allowed")
            is True
            and reconciliation_command_result.get("reconciliation_execution_ran")
            is True
            and reconciliation_command_result.get("local_state_mutated") is True
            and reconciliation_command_result.get("exchange_state_mutated") is False
            and reconciliation_command_result.get("live_exchange_submitted") is False
            and reconciliation_command_result.get("live_coinbase_orders_ran") is False,
        ),
        check("futures_audit_workbench_readback", audit_workbench.get("count", 0) >= 1),
        check(
            "no_live_coinbase_orders_ran",
            command_result.get("live_coinbase_orders_ran") is False
            and confirmed_command_result.get("live_coinbase_orders_ran") is False
            and confirmed_cancel_command_result.get("live_coinbase_orders_ran")
            is False
            and reconciliation_command_result.get("live_coinbase_orders_ran") is False,
        ),
    ]


def check(name: str, passed: bool) -> dict[str, Any]:
    """Return one readiness check row."""

    return {"name": name, "passed": bool(passed)}


def object_record(value: Any) -> dict[str, Any]:
    """Return value as a mapping or an empty dict."""

    return dict(value) if isinstance(value, Mapping) else {}


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    """Write stable JSON evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def read_git_value(args: Sequence[str], fallback: str = "unknown") -> str:
    """Return a git value or fallback when git evidence is unavailable."""

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


def current_utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the no-live Futures boundary smoke and write evidence."""

    config = config_from_args(build_parser().parse_args(argv))
    apply_runner_environment(config)
    summary = run_futures_boundary_smoke(get_admin_mvp_service(), config)
    write_json(config.summary_output, summary)
    print(
        "Backend Futures executor-boundary smoke: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"notional {summary['notional_usdc']} USDC; "
        f"artifact {config.summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
