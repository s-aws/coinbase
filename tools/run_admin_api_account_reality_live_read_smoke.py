"""Run a read-only Admin API account reality smoke with live Coinbase reads.

This smoke verifies the local backend can read Spot wallet and US CFM Futures
account evidence through the Admin service. It never submits Coinbase orders and
redacts account balances from the written artifact.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, MutableMapping, Sequence
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

from application.admin_api.mvp_service import AdminMvpRequestContext, get_admin_mvp_service
from tools import run_admin_api


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-account-reality-live-read-smoke.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_account_reality_live_read_smoke"
SCHEMA_VERSION = "1"
LIVE_COINBASE_EXECUTION = "not_run"
NOTIONAL_USDC = "0"


def build_parser() -> argparse.ArgumentParser:
    """Create the account reality live-read smoke parser."""

    parser = argparse.ArgumentParser(
        description="Run a no-order Admin API account reality live-read smoke."
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument(
        "--backend-contract-ref",
        default=None,
        help="Backend contract ref to record. Defaults to the current git commit.",
    )
    return parser


def apply_runner_environment() -> dict[str, str]:
    """Apply the same local TLS/auth environment setup as the Admin API runner."""

    return run_admin_api.apply_local_environment(run_admin_api.parse_args([]))


def build_request_context() -> AdminMvpRequestContext:
    """Return a read-only smoke request context."""

    return AdminMvpRequestContext(
        idempotency_key="account-reality-live-read-smoke",
        correlation_id=f"account-reality-live-read-smoke-{int(time.time())}",
        operator_intent="account_reality_live_read_smoke",
        actor_id="local-operator",
        roles=("admin", "trader"),
    )


def read_admin_surfaces(service: Any) -> dict[str, Any]:
    """Read the backend-owned Admin surfaces needed for account reality evidence."""

    context = build_request_context()
    routes = {
        "wallet": "/api/v1/admin/wallet",
        "futures_account": "/api/v1/futures/account",
        "futures_positions": "/api/v1/futures/positions",
        "futures_risk_proofs": "/api/v1/futures/risk-proofs",
        "futures_command_suite": "/api/v1/futures/command-suite",
    }
    return {
        name: service.get_read_response(route, {}, context)
        for name, route in routes.items()
    }


def build_smoke_summary(
    *,
    read_results: Mapping[str, Any],
    applied_environment: Mapping[str, str],
    started_at: str,
    ended_at: str,
    duration_seconds: float,
    backend_git_commit: str,
    backend_git_branch: str,
    backend_contract_ref: str,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Return redacted account reality smoke evidence."""

    bodies = {name: result.body for name, result in read_results.items()}
    checks = account_reality_checks(read_results, bodies)
    status = "passed" if all(check["passed"] for check in checks) else "failed"
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": round(max(duration_seconds, 0), 3),
        "wait_sleep_seconds": 0,
        "backend_git_commit": backend_git_commit,
        "backend_git_branch": backend_git_branch,
        "backend_contract_ref": backend_contract_ref,
        "credentials_present": credentials_present(environ),
        "truststore_status": applied_environment.get(run_admin_api.OS_TRUSTSTORE_ENV),
        "checks": checks,
        "wallet": redact_wallet_evidence(bodies["wallet"]),
        "futures_account": redact_futures_account_evidence(bodies["futures_account"]),
        "futures_positions": redact_futures_positions_evidence(
            bodies["futures_positions"]
        ),
        "futures_risk_proofs": redact_risk_proof_evidence(
            bodies["futures_risk_proofs"]
        ),
        "futures_command_suite": redact_command_suite_evidence(
            bodies["futures_command_suite"]
        ),
        "live_coinbase_execution": LIVE_COINBASE_EXECUTION,
        "notional_usdc": NOTIONAL_USDC,
    }


def account_reality_checks(
    read_results: Mapping[str, Any],
    bodies: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return pass/fail checks for account reality readiness."""

    wallet = bodies["wallet"]
    futures_account = bodies["futures_account"]
    futures_positions = bodies["futures_positions"]
    risk_proofs = bodies["futures_risk_proofs"]
    command_suite = bodies["futures_command_suite"]
    readiness = object_record(wallet.get("readiness"))
    funding = object_record(futures_account.get("funding"))
    funding_value = object_record(funding.get("value"))
    liquidation = object_record(futures_account.get("liquidation"))
    liquidation_value = object_record(liquidation.get("value"))
    reduce_close = object_record(futures_account.get("reduce_only_close_only"))
    reduce_close_value = object_record(reduce_close.get("value"))
    return [
        check("wallet_http_ok", read_results["wallet"].status_code == 200),
        check(
            "wallet_account_reality_ready",
            object_record(wallet.get("account_reality")).get("status") == "ready",
        ),
        check(
            "wallet_futures_risk_input_ready",
            object_record(wallet.get("futures_risk_input")).get("status") == "ready",
        ),
        check(
            "futures_account_scope_ready",
            readiness.get("futures_account_scope_ready") is True,
        ),
        check(
            "futures_observed_position_scope_ready",
            readiness.get("futures_observed_position_scope_ready") is True,
        ),
        check(
            "futures_positions_http_ok",
            read_results["futures_positions"].status_code == 200,
        ),
        check(
            "futures_positions_scope_readback",
            futures_positions.get("type") == "admin_futures_positions"
            and int(futures_positions.get("count") or 0) > 0,
        ),
        check(
            "futures_positions_read_only",
            futures_positions.get("read_only") is True,
        ),
        check(
            "futures_margin_collateral_ready",
            readiness.get("futures_margin_collateral_ready") is True,
        ),
        check(
            "futures_usable_for_risk",
            readiness.get("usable_for_futures_risk") is True,
        ),
        check(
            "futures_account_collateral_ready",
            object_record(futures_account.get("collateral")).get("status") == "ready",
        ),
        check(
            "futures_account_margin_ready",
            object_record(futures_account.get("margin")).get("status") == "ready",
        ),
        check(
            "futures_account_funding_ready",
            funding.get("status") == "ready"
            and funding_value.get("funding_applicability") == "not_applicable_us_cfm"
            and funding_value.get("funding_required") is False
            and funding_value.get("intx_applicability") == "not_applicable_us_account",
        ),
        check(
            "futures_account_liquidation_ready",
            liquidation.get("status") == "ready"
            and liquidation_value.get("liquidation_threshold_present") is True
            and liquidation_value.get("liquidation_buffer_present") is True,
        ),
        check(
            "futures_account_reduce_close_ready",
            reduce_close.get("status") == "ready"
            and reduce_close_value.get("backend_derives_close_reduce_side") is True
            and int(reduce_close_value.get("position_side_observed_count") or 0) > 0,
        ),
        check("futures_risk_proofs_ready", risk_proofs.get("status") == "ready"),
        check(
            "futures_risk_proofs_generated",
            risk_proofs.get("proof_records_generated_from_account_snapshot") is True,
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
            "no_live_coinbase_orders_ran",
            all(body.get("live_coinbase_orders_ran") is False for body in bodies.values()),
        ),
    ]


def check(name: str, passed: bool) -> dict[str, Any]:
    """Return one readiness check row."""

    return {"name": name, "passed": bool(passed)}


def redact_wallet_evidence(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return wallet readiness without account balances."""

    risk_input = object_record(body.get("futures_risk_input"))
    return {
        "status": body.get("status"),
        "account_reality_status": object_record(body.get("account_reality")).get(
            "status"
        ),
        "readiness": object_record(body.get("readiness")),
        "futures_risk_input_status": risk_input.get("status"),
        "futures_risk_input_currency": risk_input.get("currency"),
        "futures_available_notional_present": bool(
            str(risk_input.get("available_notional_usdc") or "").strip()
        ),
        "live_coinbase_orders_ran": body.get("live_coinbase_orders_ran"),
    }


def redact_futures_account_evidence(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return futures account readiness without margin or balance values."""

    collateral = object_record(body.get("collateral"))
    margin = object_record(body.get("margin"))
    funding = object_record(body.get("funding"))
    funding_value = object_record(funding.get("value"))
    liquidation = object_record(body.get("liquidation"))
    liquidation_value = object_record(liquidation.get("value"))
    reduce_close = object_record(body.get("reduce_only_close_only"))
    reduce_close_value = object_record(reduce_close.get("value"))
    return {
        "account_readiness": object_record(body.get("account_readiness")),
        "collateral_status": collateral.get("status"),
        "collateral_source": collateral.get("source"),
        "margin_status": margin.get("status"),
        "margin_source": margin.get("source"),
        "funding_status": funding.get("status"),
        "funding_source": funding.get("source"),
        "funding_applicability": funding_value.get("funding_applicability"),
        "funding_required": funding_value.get("funding_required"),
        "intx_applicability": funding_value.get("intx_applicability"),
        "liquidation_status": liquidation.get("status"),
        "liquidation_source": liquidation.get("source"),
        "liquidation_threshold_present": liquidation_value.get(
            "liquidation_threshold_present"
        ),
        "liquidation_buffer_present": liquidation_value.get(
            "liquidation_buffer_present"
        ),
        "reduce_only_close_only_status": reduce_close.get("status"),
        "reduce_only_close_only_source": reduce_close.get("source"),
        "position_side_observed_count": reduce_close_value.get(
            "position_side_observed_count"
        ),
        "backend_derives_close_reduce_side": reduce_close_value.get(
            "backend_derives_close_reduce_side"
        ),
        "command_routes_mode": body.get("command_routes_mode"),
        "live_coinbase_orders_ran": body.get("live_coinbase_orders_ran"),
    }


def redact_futures_positions_evidence(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return Futures position scope without size, price, or raw position values."""

    items = body.get("items") if isinstance(body.get("items"), list) else []
    redacted_items = []
    for item in items:
        record = object_record(item)
        redacted_items.append(
            {
                "position_key": record.get("position_key"),
                "product_id": record.get("product_id"),
                "position_side_present": bool(str(record.get("position_side") or "")),
                "source": record.get("source"),
                "updated_at_present": bool(record.get("updated_at")),
            }
        )
    return {
        "type": body.get("type"),
        "count": body.get("count"),
        "position_scope_present": bool(redacted_items),
        "product_scope": [
            item["product_id"] for item in redacted_items if item.get("product_id")
        ],
        "position_side_present": any(
            item["position_side_present"] for item in redacted_items
        ),
        "items": redacted_items,
        "read_only": body.get("read_only"),
        "command_routes_mode": body.get("command_routes_mode"),
        "live_coinbase_orders_ran": body.get("live_coinbase_orders_ran"),
    }


def redact_risk_proof_evidence(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return futures risk proof readiness without balance values."""

    return {
        "status": body.get("status"),
        "count": body.get("count"),
        "proof_records_created": body.get("proof_records_created"),
        "proof_records_generated_from_account_snapshot": body.get(
            "proof_records_generated_from_account_snapshot"
        ),
        "command_routes_mode": body.get("command_routes_mode"),
        "live_coinbase_orders_ran": body.get("live_coinbase_orders_ran"),
    }


def redact_command_suite_evidence(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return Futures command-suite readiness without account values."""

    return {
        "status": body.get("status"),
        "command_routes_mode": body.get("command_routes_mode"),
        "resolved_backend_contracts": body.get("resolved_backend_contracts"),
        "missing_backend_contracts": body.get("missing_backend_contracts"),
        "futures_risk_proof_count": body.get("futures_risk_proof_count"),
        "blocked_command_count": body.get("blocked_command_count"),
        "executable_command_count": body.get("executable_command_count"),
        "live_coinbase_orders_ran": body.get("live_coinbase_orders_ran"),
    }


def credentials_present(environ: Mapping[str, str]) -> bool:
    """Return whether Coinbase REST credentials are available."""

    return bool(environ.get("COINBASE_API_KEY") and environ.get("COINBASE_API_SECRET"))


def object_record(value: Any) -> dict[str, Any]:
    """Return value as a mapping or an empty dict."""

    return dict(value) if isinstance(value, Mapping) else {}


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    """Write stable JSON evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    """Run read-only account reality checks and write smoke evidence."""

    args = build_parser().parse_args(argv)
    started_at = current_utc_timestamp()
    started = time.perf_counter()
    applied_environment = apply_runner_environment()
    read_results = read_admin_surfaces(get_admin_mvp_service())
    ended_at = current_utc_timestamp()
    backend_git_commit = read_git_value(["rev-parse", "--short", "HEAD"])
    summary = build_smoke_summary(
        read_results=read_results,
        applied_environment=applied_environment,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=time.perf_counter() - started,
        backend_git_commit=backend_git_commit,
        backend_git_branch=read_git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        backend_contract_ref=args.backend_contract_ref or backend_git_commit,
        environ=os.environ,
    )
    write_json(args.summary_output, summary)
    print(
        "Backend account reality live-read smoke: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"notional {summary['notional_usdc']} USDC; "
        f"artifact {args.summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
