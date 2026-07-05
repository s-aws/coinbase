"""Read back Spot live-order evidence by client_order_id.

This tool is read-only. It does not submit, cancel, move, reconcile, or mutate
Coinbase orders. The operator-facing identity remains ``client_order_id``; the
exchange ``order_id`` is used only as backend evidence to read fills.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
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

from application.admin_api.mvp_service import get_admin_mvp_service  # noqa: E402
from tools import run_admin_api  # noqa: E402
from tools.coinbase_live_credentials import ensure_live_coinbase_credentials  # noqa: E402
from tools.run_admin_api_manual_order_live_submit import (  # noqa: E402
    decimal_text,
    decimal_value,
)


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-spot-live-order-readback.json"
)
DEFAULT_SUBMISSION_ARTIFACT = (
    Path("artifacts") / "coinbase-backend-manual-live-submit.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_spot_live_order_readback"
SCHEMA_VERSION = "1"
DEFAULT_ORDER_STATUSES = ("FILLED", "OPEN", "CANCELLED", "EXPIRED", "FAILED")
LIVE_ORDER_ARTIFACT_TYPES = {
    "coinbase_admin_api_manual_order_live_submit",
    "coinbase_admin_api_spot_live_cancel",
}


@dataclass(frozen=True)
class SpotLiveOrderReadbackConfig:
    """Operator-controlled inputs for one read-only Spot order proof."""

    client_order_id: str | None = None
    product_id: str | None = None
    summary_output: Path = DEFAULT_SUMMARY_OUTPUT
    submission_artifact: Path = DEFAULT_SUBMISSION_ARTIFACT
    backend_contract_ref: str | None = None
    order_statuses: tuple[str, ...] = DEFAULT_ORDER_STATUSES
    fill_limit: int = 100
    require_submission_artifact: bool = False


@dataclass(frozen=True)
class OrderReadResult:
    """Normalized order-read evidence for one client_order_id."""

    attempted: bool
    succeeded: bool
    order: dict[str, Any] | None
    error: str | None


@dataclass(frozen=True)
class FillReadResult:
    """Normalized fill-read evidence for one exchange order id."""

    attempted: bool
    succeeded: bool
    fills: list[dict[str, Any]]
    has_next: bool
    error: str | None


def build_parser() -> argparse.ArgumentParser:
    """Create the Spot order-readback parser."""

    parser = argparse.ArgumentParser(
        description="Read Spot live order/fill evidence through backend Coinbase reads."
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--submission-artifact", type=Path, default=DEFAULT_SUBMISSION_ARTIFACT)
    parser.add_argument("--backend-contract-ref", default=None)
    parser.add_argument("--client-order-id", default=None)
    parser.add_argument("--product-id", default=None)
    parser.add_argument("--order-status", action="append", dest="order_statuses")
    parser.add_argument("--fill-limit", type=int, default=100)
    return parser


def config_from_args(args: argparse.Namespace) -> SpotLiveOrderReadbackConfig:
    """Return normalized order-readback configuration."""

    artifact_data = read_optional_json_object(args.submission_artifact)
    client_order_id = optional_text(args.client_order_id) or artifact_client_order_id(
        artifact_data
    )
    product_id = optional_text(args.product_id) or artifact_product_id(artifact_data)
    order_statuses = tuple(
        status.strip().upper()
        for status in (args.order_statuses or DEFAULT_ORDER_STATUSES)
        if status and status.strip()
    )
    return SpotLiveOrderReadbackConfig(
        client_order_id=client_order_id,
        product_id=product_id,
        summary_output=args.summary_output,
        submission_artifact=args.submission_artifact,
        backend_contract_ref=args.backend_contract_ref,
        order_statuses=order_statuses or DEFAULT_ORDER_STATUSES,
        fill_limit=max(int(args.fill_limit or 100), 1),
        require_submission_artifact=True,
    )


def run_spot_live_order_readback(
    rest_client: Any,
    config: SpotLiveOrderReadbackConfig,
) -> dict[str, Any]:
    """Read Spot order/fill evidence and return a redacted proof artifact."""

    started_at = current_utc_timestamp()
    started = time.perf_counter()
    submission_artifact = read_optional_json_object(config.submission_artifact)
    effective_config = config_with_submission_defaults(config, submission_artifact)
    order_read = read_order_by_client_order_id(rest_client, effective_config)
    order = order_read.order or {}
    exchange_order_id = text_value(
        order.get("order_id")
        or order.get("exchange_order_id")
        or order.get("coinbase_order_id")
        or artifact_exchange_order_id(submission_artifact)
    )
    product_id = (
        text_value(order.get("product_id"))
        or text_value(effective_config.product_id)
        or artifact_product_id(submission_artifact)
        or ""
    )
    fill_read = read_fills_for_exchange_order(
        rest_client,
        exchange_order_id=exchange_order_id,
        product_id=product_id,
        limit=effective_config.fill_limit,
    )
    return build_summary(
        config=effective_config,
        submission_artifact=submission_artifact,
        started_at=started_at,
        duration_seconds=time.perf_counter() - started,
        order_read=order_read,
        fill_read=fill_read,
        exchange_order_id=exchange_order_id,
        product_id=product_id,
    )


def config_with_submission_defaults(
    config: SpotLiveOrderReadbackConfig,
    submission_artifact: Mapping[str, Any],
) -> SpotLiveOrderReadbackConfig:
    """Return config with missing order identity filled from live evidence."""

    client_order_id = optional_text(config.client_order_id) or artifact_client_order_id(
        submission_artifact
    )
    product_id = optional_text(config.product_id) or artifact_product_id(
        submission_artifact
    )
    return replace(config, client_order_id=client_order_id, product_id=product_id)


def read_order_by_client_order_id(
    rest_client: Any,
    config: SpotLiveOrderReadbackConfig,
) -> OrderReadResult:
    """Read recent orders and return the one matching client_order_id."""

    client_order_id = text_value(config.client_order_id)
    if not client_order_id:
        return OrderReadResult(False, False, None, "client_order_id_required")
    method = getattr(rest_client, "list_orders", None)
    if not callable(method):
        return OrderReadResult(False, False, None, "list_orders_unavailable")
    first_error = None
    attempted = False
    for status in config.order_statuses:
        attempted = True
        try:
            response = method(order_status=[status])
        except Exception as exc:
            first_error = first_error or type(exc).__name__
            continue
        order = find_order_by_client_order_id(order_records(response), client_order_id)
        if order is not None:
            return OrderReadResult(True, True, order, None)
    return OrderReadResult(attempted, first_error is None, None, first_error)


def read_fills_for_exchange_order(
    rest_client: Any,
    *,
    exchange_order_id: str,
    product_id: str,
    limit: int,
) -> FillReadResult:
    """Read fill records for one exchange order id."""

    if not exchange_order_id:
        return FillReadResult(False, False, [], False, "exchange_order_id_missing")
    method = getattr(rest_client, "list_fills", None)
    if not callable(method):
        return FillReadResult(False, False, [], False, "list_fills_unavailable")
    try:
        response = method(order_id=exchange_order_id, limit=limit)
    except Exception as exc:
        return FillReadResult(True, False, [], False, type(exc).__name__)
    data = object_record(response)
    fills = [
        object_record(fill)
        for fill in list_value(data.get("fills"))
        if isinstance(object_record(fill), dict)
    ]
    return FillReadResult(
        True,
        True,
        fills,
        bool(data.get("has_next")),
        None,
    )


def build_summary(
    *,
    config: SpotLiveOrderReadbackConfig,
    submission_artifact: Mapping[str, Any],
    started_at: str,
    duration_seconds: float,
    order_read: OrderReadResult,
    fill_read: FillReadResult,
    exchange_order_id: str,
    product_id: str,
) -> dict[str, Any]:
    """Return redacted Spot order/fill readback evidence."""

    order = order_read.order or {}
    order_status = text_value(order.get("status") or order.get("order_status"))
    fill_summary = summarize_fills(
        fill_read.fills,
        exchange_order_id=exchange_order_id,
        product_id=product_id,
    )
    submission_summary = summarize_submission_artifact(
        submission_artifact,
        client_order_id=text_value(config.client_order_id),
        product_id=product_id,
        exchange_order_id=exchange_order_id,
    )
    checks = spot_live_order_readback_checks(
        config=config,
        order_read=order_read,
        fill_read=fill_read,
        exchange_order_id=exchange_order_id,
        fill_summary=fill_summary,
        submission_summary=submission_summary,
    )
    fill_count = int(fill_summary["fill_count"])
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "status": "passed" if all(check["passed"] for check in checks) else "failed",
        "started_at": started_at,
        "ended_at": current_utc_timestamp(),
        "duration_seconds": round(max(duration_seconds, 0), 3),
        "wait_sleep_seconds": 0,
        "backend_git_commit": read_git_value(["rev-parse", "--short", "HEAD"]),
        "backend_git_branch": read_git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "backend_contract_ref": config.backend_contract_ref
        or read_git_value(["rev-parse", "--short", "HEAD"]),
        "client_order_id": text_value(config.client_order_id),
        "product_id": product_id,
        "order_status": order_status,
        "order_read_attempted": order_read.attempted,
        "order_read_succeeded": order_read.succeeded,
        "order_read_error": order_read.error,
        "order_found": order_read.order is not None,
        "exchange_order_id_present": bool(exchange_order_id),
        "exchange_order_id_evidence_only": True,
        "exchange_order_id": exchange_order_id,
        "fill_read_attempted": fill_read.attempted,
        "fill_read_succeeded": fill_read.succeeded,
        "fill_read_error": fill_read.error,
        "fill_count": fill_count,
        "fill_read_status": "filled" if fill_count > 0 else "not_filled",
        "fill_order_id_matches_exchange_order_id": fill_summary[
            "all_fills_match_exchange_order_id"
        ],
        "fill_product_id_matches_order": fill_summary["all_fills_match_product_id"],
        "fill_trade_id_present_count": fill_summary["trade_id_present_count"],
        "fill_entry_id_present_count": fill_summary["entry_id_present_count"],
        "fills_have_more_pages": fill_read.has_next,
        "executed_notional_usdc": fill_summary["executed_notional_usdc"],
        "submitted_notional_usdc": "0",
        "notional_usdc": "0",
        "live_coinbase_execution": "not_run",
        "live_coinbase_read_ran": order_read.attempted or fill_read.attempted,
        "live_coinbase_orders_ran": False,
        "read_only": True,
        "operator_identity_key": "client_order_id",
        **submission_summary,
        "checks": checks,
    }


def spot_live_order_readback_checks(
    *,
    config: SpotLiveOrderReadbackConfig,
    order_read: OrderReadResult,
    fill_read: FillReadResult,
    exchange_order_id: str,
    fill_summary: Mapping[str, Any],
    submission_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return pass/fail checks for the Spot readback artifact."""

    has_fills = int(fill_summary["fill_count"]) > 0
    checks = [
        check("spot_client_order_id_present", bool(text_value(config.client_order_id))),
        check("spot_order_read_attempted", order_read.attempted),
        check("spot_order_read_succeeded", order_read.succeeded),
        check("spot_order_matched_client_order_id", order_read.order is not None),
        check("spot_exchange_order_id_present", bool(exchange_order_id)),
        check("spot_exchange_order_id_evidence_only", True),
        check("spot_fill_read_attempted", fill_read.attempted),
        check("spot_fill_read_succeeded", fill_read.succeeded),
        check(
            "spot_fills_match_exchange_order_id_when_present",
            not has_fills or bool(fill_summary["all_fills_match_exchange_order_id"]),
        ),
        check(
            "spot_fills_match_product_id_when_present",
            not has_fills or bool(fill_summary["all_fills_match_product_id"]),
        ),
        check("spot_live_coinbase_orders_not_run", True),
    ]
    if not config.require_submission_artifact:
        return checks
    checks.extend(
        [
            check(
                "spot_submission_artifact_present",
                submission_summary.get("submission_artifact_present") is True,
            ),
            check(
                "spot_submission_artifact_type",
                submission_summary.get("submission_artifact_type")
                in LIVE_ORDER_ARTIFACT_TYPES,
            ),
            check(
                "spot_submission_artifact_passed",
                submission_summary.get("submission_artifact_status") == "passed",
            ),
            check(
                "spot_submission_artifact_matches_client_order_id",
                submission_summary.get("submission_artifact_matches_client_order_id")
                is True,
            ),
            check(
                "spot_submission_artifact_matches_product_id",
                submission_summary.get("submission_artifact_matches_product_id") is True,
            ),
            check(
                "spot_submission_artifact_live_submitted",
                submission_summary.get("submission_artifact_live_exchange_submitted")
                is True
                and submission_summary.get(
                    "submission_artifact_live_coinbase_execution"
                )
                == "submitted"
                and submission_summary.get(
                    "submission_artifact_live_coinbase_orders_ran"
                )
                is True,
            ),
            check(
                "spot_submission_artifact_exchange_order_id_matches_readback",
                submission_summary.get(
                    "submission_artifact_exchange_order_id_matches_readback"
                )
                is True,
            ),
        ]
    )
    return checks


def summarize_submission_artifact(
    submission_artifact: Mapping[str, Any],
    *,
    client_order_id: str,
    product_id: str,
    exchange_order_id: str,
) -> dict[str, Any]:
    """Return proof that readback belongs to prior live Spot submission."""

    submitted_client_order_id = artifact_client_order_id(submission_artifact) or ""
    submitted_product_id = artifact_product_id(submission_artifact) or ""
    submitted_exchange_order_id = artifact_exchange_order_id(submission_artifact) or ""
    artifact_live_execution = artifact_live_coinbase_execution(submission_artifact)
    return {
        "submission_artifact_present": bool(submission_artifact),
        "submission_artifact_type": text_value(submission_artifact.get("artifact_type")),
        "submission_artifact_status": text_value(submission_artifact.get("status")),
        "submission_artifact_client_order_id": submitted_client_order_id,
        "submission_artifact_matches_client_order_id": bool(client_order_id)
        and submitted_client_order_id == client_order_id,
        "submission_artifact_product_id": submitted_product_id,
        "submission_artifact_matches_product_id": bool(product_id)
        and submitted_product_id == product_id,
        "submission_artifact_exchange_order_id": submitted_exchange_order_id,
        "submission_artifact_exchange_order_id_present": bool(submitted_exchange_order_id),
        "submission_artifact_exchange_order_id_evidence_only": bool(
            submitted_exchange_order_id
        ),
        "submission_artifact_exchange_order_id_matches_readback": bool(
            submitted_exchange_order_id
        )
        and submitted_exchange_order_id == exchange_order_id,
        "submission_artifact_live_exchange_submitted": (
            bool(submission_artifact.get("live_exchange_submitted"))
            or bool(submission_artifact.get("seed_order_live_exchange_submitted"))
        ),
        "submission_artifact_live_coinbase_execution": artifact_live_execution,
        "submission_artifact_live_coinbase_orders_ran": (
            bool(submission_artifact.get("live_coinbase_orders_ran"))
            or bool(submission_artifact.get("seed_order_live_coinbase_orders_ran"))
        ),
        "submission_artifact_proof_chain_status": text_value(
            submission_artifact.get("proof_chain_status")
            or submission_artifact.get("seed_order_proof_chain_status")
        ),
        "submission_artifact_approval_snapshot_id": text_value(
            submission_artifact.get("approval_snapshot_id")
        ),
        "submission_artifact_admission_audit_id": text_value(
            submission_artifact.get("admission_audit_id")
        ),
        "submission_artifact_cap_guard_decision_id": text_value(
            submission_artifact.get("cap_guard_decision_id")
        ),
        "submission_artifact_reconciliation_plan_id": text_value(
            submission_artifact.get("reconciliation_plan_id")
        ),
    }


def artifact_client_order_id(artifact: Mapping[str, Any]) -> str | None:
    """Return the client_order_id from a Spot live artifact shape."""

    return optional_text(
        artifact.get("client_order_id")
        or artifact.get("seed_order_client_order_id")
    )


def artifact_product_id(artifact: Mapping[str, Any]) -> str | None:
    """Return the product id from a Spot live artifact shape."""

    return optional_text(artifact.get("product_id") or artifact.get("seed_order_product_id"))


def artifact_exchange_order_id(artifact: Mapping[str, Any]) -> str | None:
    """Return exchange order evidence from a Spot live artifact shape."""

    return optional_text(
        artifact.get("exchange_order_id")
        or artifact.get("coinbase_order_id")
        or artifact.get("seed_order_coinbase_order_id")
    )


def artifact_live_coinbase_execution(artifact: Mapping[str, Any]) -> str:
    """Return the live execution posture represented by a Spot live artifact."""

    if bool(artifact.get("live_exchange_submitted")) or bool(
        artifact.get("seed_order_live_exchange_submitted")
    ):
        return "submitted"
    return text_value(artifact.get("live_coinbase_execution"))


def summarize_fills(
    fills: Sequence[Mapping[str, Any]],
    *,
    exchange_order_id: str,
    product_id: str,
) -> dict[str, Any]:
    """Return aggregate fill evidence without account values."""

    executed_notional = Decimal("0")
    normalized_fills = [object_record(fill) for fill in fills]
    exchange_order_ids = {
        text_value(fill.get("order_id") or fill.get("exchange_order_id"))
        for fill in normalized_fills
    }
    non_empty_exchange_order_ids = {item for item in exchange_order_ids if item}
    product_ids = {text_value(fill.get("product_id")) for fill in normalized_fills}
    non_empty_product_ids = {item for item in product_ids if item}
    for fill in normalized_fills:
        executed_notional += fill_notional_usdc(fill)
    return {
        "fill_count": len(normalized_fills),
        "trade_id_present_count": sum(1 for fill in normalized_fills if fill.get("trade_id")),
        "entry_id_present_count": sum(1 for fill in normalized_fills if fill.get("entry_id")),
        "all_fills_match_exchange_order_id": (
            bool(normalized_fills) and non_empty_exchange_order_ids == {exchange_order_id}
        ),
        "all_fills_match_product_id": (
            not product_id
            or (bool(normalized_fills) and non_empty_product_ids == {product_id})
        ),
        "executed_notional_usdc": decimal_text(executed_notional),
    }


def fill_notional_usdc(fill: Mapping[str, Any]) -> Decimal:
    """Return quote notional value for one Spot fill."""

    filled_value = first_decimal(fill, ("filled_value", "quote_size", "quote_value"))
    if filled_value is not None:
        return filled_value
    size = first_decimal(fill, ("size", "filled_size", "base_size"))
    if boolish(fill.get("size_in_quote")) and size is not None:
        return size
    price = first_decimal(fill, ("price", "fill_price", "average_filled_price"))
    if size is None or price is None:
        return Decimal("0")
    return size * price


def first_decimal(source: Mapping[str, Any], fields: Sequence[str]) -> Decimal | None:
    """Return the first non-negative Decimal found in source fields."""

    for field in fields:
        value = source.get(field)
        if value in (None, ""):
            continue
        try:
            return decimal_value(str(value))
        except ValueError:
            continue
    return None


def order_records(response: Any) -> list[dict[str, Any]]:
    """Return order records from a Coinbase list_orders response."""

    data = object_record(response)
    return [object_record(order) for order in list_value(data.get("orders"))]


def find_order_by_client_order_id(
    orders: Sequence[Mapping[str, Any]],
    client_order_id: str,
) -> dict[str, Any] | None:
    """Return the first order matching client_order_id."""

    for order in orders:
        if text_value(order.get("client_order_id")) == client_order_id:
            return dict(order)
    return None


def read_optional_json_object(path: Path) -> dict[str, Any]:
    """Read an optional JSON object from disk."""

    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def object_record(value: Any) -> dict[str, Any]:
    """Return a dictionary for mapping or object-like values."""

    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return dict(converted) if isinstance(converted, Mapping) else {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def list_value(value: Any) -> list[Any]:
    """Return a list value or an empty list."""

    return list(value) if isinstance(value, Sequence) and not isinstance(value, str) else []


def text_value(value: Any) -> str:
    """Return stripped text."""

    return str(value or "").strip()


def optional_text(value: Any) -> str | None:
    """Return stripped optional text."""

    text = text_value(value)
    return text or None


def boolish(value: Any) -> bool:
    """Return true for bool or text booleans from Coinbase payloads."""

    if isinstance(value, bool):
        return value
    return text_value(value).lower() in {"true", "1", "yes"}


def check(name: str, passed: bool) -> dict[str, Any]:
    """Return one check row."""

    return {"name": name, "passed": bool(passed)}


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


def assert_live_read_credentials_present(environ: MutableMapping[str, str]) -> None:
    """Hydrate live-read Coinbase credentials before service construction."""

    ensure_live_coinbase_credentials(environ)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the read-only Spot live order readback and write evidence."""

    config = config_from_args(build_parser().parse_args(argv))
    assert_live_read_credentials_present(os.environ)
    run_admin_api.apply_local_environment(run_admin_api.parse_args([]))
    service = get_admin_mvp_service()
    summary = run_spot_live_order_readback(service.dependencies.rest_client, config)
    write_json(config.summary_output, summary)
    print(
        "Backend Spot live order readback: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"read {summary['live_coinbase_read_ran']}; "
        f"executed {summary['executed_notional_usdc']} USDC; "
        f"artifact {config.summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
