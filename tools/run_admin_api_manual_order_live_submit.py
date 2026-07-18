"""Historical direct-service manual-order regression helpers.

The installed CLI mutation path is source-disabled. Operators use the
authenticated Admin UI/API manual Spot LIMIT/GTC workflow; no CLI flag,
credential, or service-singleton configuration can enable this entrypoint.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.mvp_service import (  # noqa: E402
    APPROVAL_LOG_PATH_ENV,
    AUDIT_LOG_PATH_ENV,
    CAP_GUARD_LOG_PATH_ENV,
    IDEMPOTENCY_LOG_PATH_ENV,
    LIVE_ADAPTER_DECISION_LOG_PATH_ENV,
    LIVE_SERVICE_DECISION_LOG_PATH_ENV,
    RECONCILIATION_LOG_PATH_ENV,
    AdminMvpRequestContext,
    AdminMvpService,
)
from application.admin_api.idempotency import (  # noqa: E402
    FileIdempotencyStore,
    IdempotencyRecord,
)
from application.admin_api.models import (  # noqa: E402
    AdminApiCommandResponse,
    AdminLiveAdmissionDecisionEvidence,
)
from core.enums import (  # noqa: E402
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiPermission,
)
from core.coinbase_execution_authority import (  # noqa: E402
    SOURCE_DISABLED_COINBASE_EXECUTION_ERROR,
)
from tools import run_admin_api  # noqa: E402
from tools.coinbase_live_credentials import ensure_live_coinbase_credentials  # noqa: E402


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-manual-order-live-submit.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_manual_order_live_submit"
SCHEMA_VERSION = "1"
LIVE_EXECUTION_ENV = "COINBASE_ADMIN_LIVE_COINBASE_EXECUTION"
MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC = "3.10"
MAX_DEFAULT_EXECUTED_NOTIONAL_USDC = "1.00"
DEFAULT_QUOTE_SIZE = "1.00"
DEFAULT_LIMIT_PRICE = "1000000.00"
RUNNER_COMMAND_IDEMPOTENCY_FILENAME = "admin_api_runner_command_idempotency.jsonl"
STATE_LOG_FILENAMES = {
    APPROVAL_LOG_PATH_ENV: "admin_api_approvals.jsonl",
    IDEMPOTENCY_LOG_PATH_ENV: "admin_api_idempotency.jsonl",
    AUDIT_LOG_PATH_ENV: "admin_api_audit.jsonl",
    CAP_GUARD_LOG_PATH_ENV: "admin_api_cap_guard.jsonl",
    RECONCILIATION_LOG_PATH_ENV: "admin_api_reconciliation_plan.jsonl",
    LIVE_SERVICE_DECISION_LOG_PATH_ENV: "admin_api_live_service_decisions.jsonl",
    LIVE_ADAPTER_DECISION_LOG_PATH_ENV: "admin_api_live_adapter_decisions.jsonl",
}


class LiveSubmitConfirmationError(RuntimeError):
    """Raised when a live submission is requested without explicit consent."""


class LiveSubmitCapExceededError(RuntimeError):
    """Raised when local live evidence would exceed the submitted cap."""


@dataclass(frozen=True)
class ManualLiveSubmitConfig:
    """Operator-controlled inputs for one bounded manual live submission."""

    confirm_live_submit: bool = False
    product_id: str = "BTC-USDC"
    side: str = "BUY"
    quote_size: str = DEFAULT_QUOTE_SIZE
    limit_price: str = DEFAULT_LIMIT_PRICE
    time_in_force: str = "IOC"
    idempotency_key: str = "manual-live-submit"
    correlation_id: str = "manual-live-submit-correlation"
    actor_id: str = "local-operator"
    roles: tuple[str, ...] = ("admin", "trader")
    max_submitted_notional_usdc: str = MAX_DEFAULT_SUBMITTED_NOTIONAL_USDC
    max_executed_notional_usdc: str = MAX_DEFAULT_EXECUTED_NOTIONAL_USDC
    state_dir: str | None = None


def build_parser() -> argparse.ArgumentParser:
    """Create the source-disabled compatibility parser."""

    return argparse.ArgumentParser(
        description=(
            "Historical direct-service manual submit is source-disabled. "
            "Use the installed authenticated Admin UI/API workflow."
        )
    )


def config_from_args(args: argparse.Namespace) -> ManualLiveSubmitConfig:
    """Return normalized live-submit configuration from parsed arguments."""

    run_id = str(int(time.time()))
    idempotency_key = args.idempotency_key or f"manual-live-submit-{run_id}"
    correlation_id = args.correlation_id or f"{idempotency_key}-correlation"
    roles = tuple(role.strip() for role in str(args.roles).split(",") if role.strip())
    return ManualLiveSubmitConfig(
        confirm_live_submit=bool(args.confirm_live_submit),
        product_id=str(args.product_id),
        side=str(args.side),
        quote_size=str(args.quote_size),
        limit_price=str(args.limit_price),
        time_in_force=str(args.time_in_force),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        actor_id=str(args.actor_id),
        roles=roles or ("admin", "trader"),
        max_submitted_notional_usdc=str(args.max_submitted_notional_usdc),
        max_executed_notional_usdc=str(args.max_executed_notional_usdc),
        state_dir=str(args.state_dir) if args.state_dir else None,
    )


def default_state_dir() -> Path:
    """Return the local Admin state directory used by the deployed MVP."""

    explicit_state_dir = os.environ.get("COINBASE_ADMIN_API_STATE_DIR", "").strip()
    if explicit_state_dir:
        return Path(explicit_state_dir)

    local_root = Path("C:/coinbase-local")
    if local_root.exists():
        return local_root / "state"
    return Path("artifacts") / "admin-api-state"


def apply_manual_live_submit_state_environment(
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


def build_manual_order_body(config: ManualLiveSubmitConfig) -> dict[str, Any]:
    """Return the bounded limit-IOC manual-order payload."""

    return {
        "product_id": config.product_id,
        "side": config.side,
        "order_type": "LIMIT",
        "quote_size": decimal_text(config.quote_size),
        "limit_price": decimal_text(config.limit_price),
        "time_in_force": config.time_in_force,
        "post_only": False,
        "manual_live_acknowledgement": True,
    }


def run_manual_live_submit(
    service: AdminMvpService,
    config: ManualLiveSubmitConfig,
) -> dict[str, Any]:
    """Run the backend proof chain and final live submit."""

    validate_live_submit_config(config)
    body = build_manual_order_body(config)
    started_at = current_utc_timestamp()
    started = time.perf_counter()

    with runner_command_idempotency_store(config.state_dir) as command_store:
        live_decision = record_manual_live_service_decision(service, config)
        command_context = build_request_context(config, config.idempotency_key)
        first_submit = service.submit_manual_order(body, command_context)
        admission = object_record(first_submit.body.get("admission_decision"))
        if not admission:
            return build_summary(
                config=config,
                body=body,
                started_at=started_at,
                duration_seconds=time.perf_counter() - started,
                live_decision=live_decision.body,
                first_submit=first_submit.body,
                proof_chain={},
                final_submit=first_submit.body,
                final_status_code=first_submit.status_code,
            )

        persist_runner_no_live_first_pass(
            command_store,
            first_submit.body,
        )
        proof_context = {
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
        }
        proof_chain = service.record_spot_manual_order_proof_chain(
            {
                **proof_context,
                "max_submitted_notional_usdc": config.max_submitted_notional_usdc,
                "max_executed_notional_usdc": config.max_executed_notional_usdc,
            },
            build_request_context(config, f"{config.idempotency_key}-proof-chain"),
            command_idempotency_store=command_store,
        )
    final_submit = service.submit_manual_order(body, command_context)
    return build_summary(
        config=config,
        body=body,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        live_decision=live_decision.body,
        first_submit=first_submit.body,
        proof_chain=proof_chain.body,
        final_submit=final_submit.body,
        final_status_code=final_submit.status_code,
    )


@contextmanager
def runner_command_idempotency_store(
    state_dir: str | Path | None,
):
    """Yield a FileIdempotencyStore isolated from MVP evidence JSONL."""

    if state_dir is not None:
        yield FileIdempotencyStore(
            Path(state_dir).resolve() / RUNNER_COMMAND_IDEMPOTENCY_FILENAME
        )
        return
    with TemporaryDirectory(prefix="coinbase-admin-runner-command-") as temp_dir:
        yield FileIdempotencyStore(
            Path(temp_dir) / RUNNER_COMMAND_IDEMPOTENCY_FILENAME
        )


def persist_runner_no_live_first_pass(
    command_store: FileIdempotencyStore,
    first_pass_body: Mapping[str, Any],
) -> AdminApiCommandResponse:
    """Persist one exact typed no-live first pass for composite proof binding."""

    response_payload = {
        field_name: first_pass_body[field_name]
        for field_name in AdminApiCommandResponse.model_fields
        if field_name in first_pass_body
    }
    if not response_payload.get("admission_decision"):
        proof_context = object_record(first_pass_body.get("proof_context"))
        response_payload["admission_decision"] = (
            AdminLiveAdmissionDecisionEvidence(
                status=AdminApiGateStatus.BLOCKED,
                allowed=False,
                route=str(proof_context.get("route") or ""),
                method=str(proof_context.get("method") or ""),
                module_id=str(proof_context.get("module_id") or ""),
                identity_key=str(proof_context.get("identity_key") or ""),
                identity_value=str(proof_context.get("identity_value") or ""),
                action_class=proof_context.get("action_class"),
                required_permission=proof_context.get("required_permission"),
                service_method=str(proof_context.get("service_method") or ""),
                actor_id=str(proof_context.get("actor_id") or ""),
                idempotency_key=str(
                    proof_context.get("command_idempotency_key") or ""
                ),
                operator_intent=str(proof_context.get("operator_intent") or ""),
                payload_hash=str(proof_context.get("payload_hash") or ""),
                live_exchange_submitted=False,
                detail="Backend runner no-live first-pass command context.",
            ).model_dump(mode="json")
        )
    response = AdminApiCommandResponse.model_validate(response_payload)
    admission = response.admission_decision
    route_contracts = {
        "/api/v1/orders": (
            AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            AdminApiPermission.ORDER_CREATE,
            "place_manual_order",
            "POST /api/v1/orders",
        ),
        "/api/v1/orders/{client_order_id}/cancel": (
            AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            AdminApiPermission.ORDER_CANCEL,
            "cancel_order_by_client_order_id",
            f"POST /api/v1/orders/{response.client_order_id}/cancel",
        ),
    }
    route_contract = route_contracts.get(admission.route if admission else "")
    if (
        response.status != AdminApiCommandStatus.NOT_IMPLEMENTED
        or response.live_exchange_submitted is not False
        or response.live_coinbase_orders_ran is not False
        or response.client_order_id is None
        or response.idempotency_key is None
        or admission is None
        or admission.allowed is not False
        or admission.status != AdminApiGateStatus.BLOCKED
        or admission.live_exchange_submitted is not False
        or route_contract is None
        or response.action_class != route_contract[0]
        or response.required_permission != route_contract[1]
        or response.service_method != route_contract[2]
        or admission.action_class != route_contract[0]
        or admission.required_permission != route_contract[1]
        or admission.service_method != route_contract[2]
        or admission.identity_key != "client_order_id"
        or admission.identity_value != response.client_order_id
        or admission.idempotency_key != response.idempotency_key
        or not admission.actor_id
        or not admission.operator_intent
        or len(admission.payload_hash) != 64
        or any(
            character not in "0123456789abcdef"
            for character in admission.payload_hash
        )
    ):
        raise RuntimeError("runner_no_live_first_pass_binding_invalid")
    endpoint = route_contract[3]
    if command_store.get_record(response.idempotency_key) is not None:
        raise RuntimeError("runner_command_idempotency_key_already_recorded")
    command_store.put_record(
        IdempotencyRecord(
            idempotency_key=response.idempotency_key,
            payload_hash=admission.payload_hash,
            client_order_id=response.client_order_id,
            status=response.status,
            response=response.model_dump(mode="json"),
            actor_id=admission.actor_id,
            endpoint=endpoint,
        )
    )
    return response


def validate_live_submit_config(config: ManualLiveSubmitConfig) -> None:
    """Validate bounded live-submission operator inputs."""

    if not config.confirm_live_submit:
        raise LiveSubmitConfirmationError(
            "Manual live submission requires --confirm-live-submit."
        )
    quote_size = decimal_value(config.quote_size)
    if quote_size < Decimal("1.00"):
        raise ValueError("quote_size must be at least 1.00 USDC for this MVP runner.")
    max_submitted = decimal_value(config.max_submitted_notional_usdc)
    if quote_size > max_submitted:
        raise ValueError("quote_size must not exceed max_submitted_notional_usdc.")
    assert_manual_submitted_notional_within_cumulative_cap(config, quote_size)
    if decimal_value(config.limit_price) <= 0:
        raise ValueError("limit_price must be greater than zero.")


def assert_manual_submitted_notional_within_cumulative_cap(
    config: ManualLiveSubmitConfig,
    quote_size: Decimal,
) -> None:
    """Fail before Coinbase if a live submit would exceed local cap evidence."""

    if not config.state_dir:
        return
    prior_submitted = live_place_submitted_notional_from_state_dir(Path(config.state_dir))
    max_submitted = decimal_value(config.max_submitted_notional_usdc)
    attempted_total = prior_submitted + quote_size
    if attempted_total > max_submitted:
        raise LiveSubmitCapExceededError(
            "Manual live submit would exceed submitted notional cap: "
            f"prior={decimal_text(prior_submitted)} USDC, "
            f"order={decimal_text(quote_size)} USDC, "
            f"cap={decimal_text(max_submitted)} USDC."
        )


def live_place_submitted_notional_from_state_dir(state_dir: Path) -> Decimal:
    """Return accepted live-place notional already recorded in Admin state."""

    audit_log = state_dir / "admin_api_audit.jsonl"
    total = Decimal("0")
    if not audit_log.exists():
        return total
    for entry in iter_jsonl_objects(audit_log):
        record = object_record(entry.get("record"))
        if record.get("action_class") != "live_exchange_place":
            continue
        if record.get("status") != "accepted":
            continue
        if record.get("live_exchange_submitted") is not True:
            continue
        if record.get("live_coinbase_orders_ran") is not True:
            continue
        total += decimal_value(
            record.get("submitted_notional_usdc")
            or record.get("notional_usdc")
            or "0"
        )
    return total


def iter_jsonl_objects(path: Path):
    """Yield JSON object rows from a local Admin state JSONL file."""

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, Mapping):
                yield parsed


def record_manual_live_service_decision(
    service: AdminMvpService,
    config: ManualLiveSubmitConfig,
):
    """Record backend live-service evidence for this manual order route."""

    return service.record_live_service_decision(
        {
            "decision_id": f"{config.idempotency_key}-live-service",
            "status": "passed",
            "requested_service_status": "approval_required",
            "service_enabled": True,
            "target_route": "/api/v1/orders",
            "target_method": "POST",
            "target_module_id": "spot_operations",
            "target_service_method": "place_manual_order",
            "account_family": "spot",
            "venue_scope": "coinbase_advanced_trade",
            "product_scope": [config.product_id],
            "live_coinbase_execution_approved": True,
            "max_submitted_notional_usdc": config.max_submitted_notional_usdc,
            "max_executed_notional_usdc": config.max_executed_notional_usdc,
            "decision_reason": "Explicit operator-confirmed Admin MVP live submit.",
        },
        build_request_context(config, f"{config.idempotency_key}-live-service"),
    )


def build_request_context(
    config: ManualLiveSubmitConfig,
    idempotency_key: str,
) -> AdminMvpRequestContext:
    """Return Admin request context for one runner phase."""

    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id=config.correlation_id,
        operator_intent="manual_live_submit",
        actor_id=config.actor_id,
        roles=config.roles,
    )


def build_summary(
    *,
    config: ManualLiveSubmitConfig,
    body: Mapping[str, Any],
    started_at: str,
    duration_seconds: float,
    live_decision: Mapping[str, Any],
    first_submit: Mapping[str, Any],
    proof_chain: Mapping[str, Any],
    final_submit: Mapping[str, Any],
    final_status_code: int,
) -> dict[str, Any]:
    """Return redacted live-submit evidence."""

    live_exchange_submitted = bool(final_submit.get("live_exchange_submitted"))
    live_orders_ran = bool(final_submit.get("live_coinbase_orders_ran"))
    status = "passed" if final_status_code == 200 and live_orders_ran else "failed"
    admission = object_record(final_submit.get("admission_decision"))
    submitted_notional = decimal_text(
        final_submit.get("submitted_notional_usdc")
        or final_submit.get("notional_usdc")
        or body.get("quote_size")
        or "0"
    )
    executed_notional = decimal_text(final_submit.get("executed_notional_usdc") or "0")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "status": status,
        "started_at": started_at,
        "ended_at": current_utc_timestamp(),
        "duration_seconds": round(max(duration_seconds, 0), 3),
        "backend_git_commit": read_git_value(["rev-parse", "--short", "HEAD"]),
        "backend_git_branch": read_git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "confirm_live_submit": config.confirm_live_submit,
        "product_id": body.get("product_id"),
        "side": body.get("side"),
        "order_type": body.get("order_type"),
        "time_in_force": body.get("time_in_force"),
        "quote_size": body.get("quote_size"),
        "limit_price": body.get("limit_price"),
        "max_submitted_notional_usdc": config.max_submitted_notional_usdc,
        "max_executed_notional_usdc": config.max_executed_notional_usdc,
        "state_dir": config.state_dir,
        "client_order_id": str(
            final_submit.get("client_order_id")
            or admission.get("identity_value")
            or first_submit.get("client_order_id")
            or ""
        ),
        "coinbase_order_id": str(final_submit.get("coinbase_order_id") or ""),
        "live_decision_status": object_record(live_decision.get("decision")).get("status"),
        "first_status": first_submit.get("status"),
        "first_status_code": first_submit.get("status_code"),
        "proof_chain_status": proof_chain.get("proof_chain_status"),
        "approval_request_id": proof_chain.get("approval_request_id"),
        "approval_snapshot_id": proof_chain.get("approval_snapshot_id"),
        "admission_audit_id": proof_chain.get("admission_audit_id"),
        "cap_guard_decision_id": proof_chain.get("cap_guard_decision_id"),
        "reconciliation_plan_id": proof_chain.get("reconciliation_plan_id"),
        "proof_chain_audit_id": proof_chain.get("audit_id"),
        "command_idempotency_key": (
            proof_chain.get("command_idempotency_key") or config.idempotency_key
        ),
        "proof_chain_idempotency_key": proof_chain.get("idempotency_key"),
        "correlation_id": proof_chain.get("correlation_id") or config.correlation_id,
        "payload_hash": proof_chain.get("payload_hash") or admission.get("payload_hash"),
        "final_status": final_submit.get("status"),
        "final_status_code": final_status_code,
        "failure_stage": final_submit.get("failure_stage"),
        "message": final_submit.get("message"),
        "live_exchange_submitted": live_exchange_submitted,
        "live_coinbase_orders_ran": live_orders_ran,
        "live_coinbase_execution": final_submit.get("live_coinbase_execution", "not_run"),
        "notional_usdc": final_submit.get("notional_usdc", body.get("quote_size", "0")),
        "submitted_notional_usdc": submitted_notional,
        "executed_notional_usdc": executed_notional,
        "paired_sell_required": final_submit.get("paired_sell_required"),
    }


def apply_runner_environment() -> dict[str, str]:
    """Apply local TLS/auth environment setup shared with the Admin API runner."""

    return run_admin_api.apply_local_environment(run_admin_api.parse_args([]))


def assert_live_credentials_present(environ: MutableMapping[str, str]) -> None:
    """Hydrate live Coinbase credentials before service construction."""

    ensure_live_coinbase_credentials(environ)


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


def object_record(value: Any) -> dict[str, Any]:
    """Return a dictionary for object-like values."""

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


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write stable JSON evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Fail closed before credential, service, state, or SDK access."""

    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments in (["-h"], ["--help"]):
        parser.parse_args(arguments)
    parser.error(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
