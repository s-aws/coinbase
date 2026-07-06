"""Read back M58 USDC snapshot live submit/cancel evidence.

This tool is read-only against Coinbase. It verifies one prior M58 live
submission by exchange order id, proves the order is cancelled/non-filled, and
can append local recovery evidence when the exchange readback proves a prior
cancel-failed record is now cancelled.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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

from application.admin_api.usdc_pair_snapshot import (  # noqa: E402
    FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
    UsdcPairSnapshotOrderPlanLiveSubmitRecord,
)
from tools import run_admin_api  # noqa: E402
from tools.coinbase_live_credentials import ensure_live_coinbase_credentials  # noqa: E402
from tools.run_admin_api_usdc_pair_snapshot_live_submit import (  # noqa: E402
    apply_usdc_pair_state_environment,
    default_state_dir,
    refresh_configuration_credentials,
)


DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-m58-usdc-live-readback.json"
)
DEFAULT_SUBMISSION_ARTIFACT = (
    Path("artifacts") / "coinbase-backend-m58-usdc-live-submit.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_m58_usdc_snapshot_live_readback"
SCHEMA_VERSION = "1"
LIVE_SUBMISSION_ARTIFACT_TYPES = {
    "coinbase_admin_api_m58_usdc_snapshot_live_submit",
    "coinbase_admin_api_m58_usdc_snapshot_live_cancel_recovery",
}
CANCELLED_STATUSES = {"CANCELLED", "CANCELED"}


@dataclass(frozen=True)
class UsdcPairSnapshotLiveReadbackConfig:
    """Operator-controlled inputs for one M58 readback."""

    submission_id: str | None = None
    submission_artifact: Path = DEFAULT_SUBMISSION_ARTIFACT
    summary_output: Path = DEFAULT_SUMMARY_OUTPUT
    state_dir: Path | None = None
    append_recovery_record: bool = False
    require_submission_artifact: bool = False
    open_order_limit: int = 20


@dataclass(frozen=True)
class M58OrderRead:
    """Normalized exchange order read evidence."""

    attempted: bool
    succeeded: bool
    order: dict[str, Any] | None
    error: str | None


@dataclass(frozen=True)
class M58OpenOrderRead:
    """Normalized open-order read evidence."""

    attempted: bool
    succeeded: bool
    orders: list[dict[str, Any]]
    error: str | None


def build_parser() -> argparse.ArgumentParser:
    """Create the M58 live-readback parser."""

    parser = argparse.ArgumentParser(
        description="Read back one M58 USDC snapshot live submit/cancel order."
    )
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument(
        "--submission-artifact",
        type=Path,
        default=DEFAULT_SUBMISSION_ARTIFACT,
    )
    parser.add_argument("--submission-id", default=None)
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument("--append-recovery-record", action="store_true")
    parser.add_argument("--open-order-limit", type=int, default=20)
    return parser


def config_from_args(args: argparse.Namespace) -> UsdcPairSnapshotLiveReadbackConfig:
    """Return normalized readback config from parsed args."""

    artifact_data = read_optional_json_object(args.submission_artifact)
    submission_id = optional_text(args.submission_id) or optional_text(
        artifact_data.get("submission_id")
    )
    return UsdcPairSnapshotLiveReadbackConfig(
        submission_id=submission_id,
        submission_artifact=args.submission_artifact,
        summary_output=args.summary_output,
        state_dir=args.state_dir,
        append_recovery_record=bool(args.append_recovery_record),
        require_submission_artifact=True,
        open_order_limit=max(int(args.open_order_limit or 20), 1),
    )


def run_usdc_pair_snapshot_live_readback(
    rest_client: Any,
    config: UsdcPairSnapshotLiveReadbackConfig,
) -> dict[str, Any]:
    """Read exchange state for one M58 live submission and return evidence."""

    started_at = current_utc_timestamp()
    started = time.perf_counter()
    if config.state_dir is not None:
        apply_usdc_pair_state_environment(config.state_dir)
    submission_record = load_submission_record(config)
    artifact = read_optional_json_object(config.submission_artifact)
    submission = submission_evidence(config, submission_record, artifact)
    effective_config = config_with_submission_defaults(config, submission)
    exchange_order_id = text_value(
        submission.get("coinbase_order_id")
        or submission.get("exchange_order_id")
    )
    client_order_id = text_value(submission.get("client_order_id"))
    product_id = text_value(submission.get("product_id"))

    order_read = read_exchange_order(rest_client, exchange_order_id)
    order = order_read.order or {}
    if order:
        client_order_id = text_value(order.get("client_order_id")) or client_order_id
        product_id = text_value(order.get("product_id")) or product_id
    open_order_read = read_open_orders(
        rest_client,
        product_id=product_id,
        limit=effective_config.open_order_limit,
    )
    checks = readback_checks(
        config=effective_config,
        submission=submission,
        submission_artifact=artifact,
        order_read=order_read,
        open_order_read=open_order_read,
        exchange_order_id=exchange_order_id,
        client_order_id=client_order_id,
        product_id=product_id,
    )
    passed = all(check["passed"] for check in checks)
    recovery_submission_id = None
    recovery_appended = False
    if (
        passed
        and effective_config.append_recovery_record
        and submission_record is not None
    ):
        recovery_submission_id, recovery_appended = append_recovery_record(
            submission_record=submission_record,
            order=order,
            open_order_read=open_order_read,
        )

    filled_value = decimal_text(order.get("filled_value") or "0")
    total_fees = decimal_text(order.get("total_fees") or "0")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "status": "passed" if passed else "failed",
        "started_at": started_at,
        "ended_at": current_utc_timestamp(),
        "duration_seconds": round(max(time.perf_counter() - started, 0), 3),
        "backend_git_commit": read_git_value(["rev-parse", "--short", "HEAD"]),
        "backend_git_branch": read_git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "submission_id": text_value(submission.get("submission_id")),
        "readiness_id": text_value(submission.get("readiness_id")),
        "plan_id": text_value(submission.get("plan_id")),
        "client_order_id": client_order_id,
        "product_id": product_id,
        "exchange_order_id": exchange_order_id,
        "exchange_order_id_evidence_only": True,
        "order_read_attempted": order_read.attempted,
        "order_read_succeeded": order_read.succeeded,
        "order_read_error": order_read.error,
        "order_found": order_read.order is not None,
        "order_status": text_value(order.get("status") or order.get("order_status")),
        "order_cancelled": order_cancelled(order),
        "filled_size": text_value(order.get("filled_size")),
        "filled_value": filled_value,
        "executed_notional_usdc": filled_value,
        "total_fees": total_fees,
        "outstanding_hold_amount": decimal_text(
            order.get("outstanding_hold_amount") or "0"
        ),
        "open_order_read_attempted": open_order_read.attempted,
        "open_order_read_succeeded": open_order_read.succeeded,
        "open_order_read_error": open_order_read.error,
        "open_product_order_count": len(open_order_read.orders),
        "m58_non_fill_cancel_verified": passed,
        "recovery_record_appended": recovery_appended,
        "recovery_submission_id": recovery_submission_id,
        "submitted_notional_usdc": text_value(
            submission.get("submitted_notional_usdc")
        ),
        "notional_usdc": "0",
        "live_coinbase_execution": "not_run",
        "live_coinbase_read_ran": order_read.attempted or open_order_read.attempted,
        "live_coinbase_orders_ran": False,
        "read_only": True,
        "operator_identity_key": "client_order_id",
        "submission_artifact_present": bool(artifact),
        "submission_artifact_type": text_value(artifact.get("artifact_type")),
        "submission_artifact_status": text_value(artifact.get("status")),
        "submission_record_present": submission_record is not None,
        "checks": checks,
    }


def config_with_submission_defaults(
    config: UsdcPairSnapshotLiveReadbackConfig,
    submission: Mapping[str, Any],
) -> UsdcPairSnapshotLiveReadbackConfig:
    """Return config with submission id filled from evidence."""

    return replace(
        config,
        submission_id=optional_text(config.submission_id)
        or optional_text(submission.get("submission_id")),
    )


def load_submission_record(
    config: UsdcPairSnapshotLiveReadbackConfig,
) -> UsdcPairSnapshotOrderPlanLiveSubmitRecord | None:
    """Return a stored M58 live submission record if one is requested."""

    submission_id = optional_text(config.submission_id)
    if not submission_id:
        return None
    if config.state_dir is not None:
        apply_usdc_pair_state_environment(config.state_dir)
    return FileUsdcPairSnapshotOrderPlanLiveSubmitStore().find_by_submission_id(
        submission_id
    )


def submission_evidence(
    config: UsdcPairSnapshotLiveReadbackConfig,
    record: UsdcPairSnapshotOrderPlanLiveSubmitRecord | None,
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Return submission evidence from store first, artifact second."""

    if record is not None:
        return record.model_dump(mode="json")
    if artifact:
        return dict(artifact)
    if config.require_submission_artifact:
        return {}
    return {}


def read_exchange_order(rest_client: Any, exchange_order_id: str) -> M58OrderRead:
    """Read one exchange order by Coinbase order id."""

    if not exchange_order_id:
        return M58OrderRead(False, False, None, "exchange_order_id_required")
    method = getattr(rest_client, "get_order", None)
    if not callable(method):
        return M58OrderRead(False, False, None, "get_order_unavailable")
    try:
        response = method(exchange_order_id)
    except Exception as exc:
        return M58OrderRead(True, False, None, type(exc).__name__)
    data = object_record(response)
    order = object_record(data.get("order"))
    if not order and data.get("order_id"):
        order = data
    return M58OrderRead(True, bool(order), order or None, None if order else "not_found")


def read_open_orders(
    rest_client: Any,
    *,
    product_id: str,
    limit: int,
) -> M58OpenOrderRead:
    """Read open orders for the product after the submit/cancel."""

    if not product_id:
        return M58OpenOrderRead(False, False, [], "product_id_required")
    method = getattr(rest_client, "list_orders", None)
    if not callable(method):
        return M58OpenOrderRead(False, False, [], "list_orders_unavailable")
    try:
        response = method(
            product_ids=[product_id],
            order_status=["OPEN"],
            limit=limit,
        )
    except Exception as exc:
        return M58OpenOrderRead(True, False, [], type(exc).__name__)
    data = object_record(response)
    orders = [object_record(order) for order in list_value(data.get("orders"))]
    return M58OpenOrderRead(True, True, orders, None)


def readback_checks(
    *,
    config: UsdcPairSnapshotLiveReadbackConfig,
    submission: Mapping[str, Any],
    submission_artifact: Mapping[str, Any],
    order_read: M58OrderRead,
    open_order_read: M58OpenOrderRead,
    exchange_order_id: str,
    client_order_id: str,
    product_id: str,
) -> list[dict[str, Any]]:
    """Return pass/fail checks for one M58 live readback."""

    order = order_read.order or {}
    checks = [
        check("m58_submission_evidence_present", bool(submission)),
        check("m58_client_order_id_present", bool(client_order_id)),
        check("m58_product_id_present", bool(product_id)),
        check("m58_exchange_order_id_present", bool(exchange_order_id)),
        check("m58_exchange_order_id_evidence_only", True),
        check("m58_order_read_attempted", order_read.attempted),
        check("m58_order_read_succeeded", order_read.succeeded),
        check("m58_order_found", order_read.order is not None),
        check(
            "m58_order_matches_exchange_order_id",
            text_value(order.get("order_id")) == exchange_order_id,
        ),
        check(
            "m58_order_matches_client_order_id",
            text_value(order.get("client_order_id")) == client_order_id,
        ),
        check(
            "m58_order_matches_product_id",
            text_value(order.get("product_id")) == product_id,
        ),
        check("m58_order_cancelled", order_cancelled(order)),
        check("m58_filled_value_zero", decimal_value(order.get("filled_value")) == 0),
        check("m58_filled_size_zero", decimal_value(order.get("filled_size")) == 0),
        check("m58_total_fees_zero", decimal_value(order.get("total_fees")) == 0),
        check(
            "m58_outstanding_hold_zero",
            decimal_value(order.get("outstanding_hold_amount")) == 0,
        ),
        check("m58_open_order_read_attempted", open_order_read.attempted),
        check("m58_open_order_read_succeeded", open_order_read.succeeded),
        check("m58_no_open_product_orders", len(open_order_read.orders) == 0),
        check("m58_readback_does_not_submit_orders", True),
    ]
    if config.require_submission_artifact:
        checks.extend(
            [
                check("m58_submission_artifact_present", bool(submission_artifact)),
                check(
                    "m58_submission_artifact_type",
                    text_value(submission_artifact.get("artifact_type"))
                    in LIVE_SUBMISSION_ARTIFACT_TYPES,
                ),
                check(
                    "m58_submission_artifact_live_submitted",
                    bool(submission_artifact.get("live_exchange_submitted")),
                ),
            ]
        )
    return checks


def append_recovery_record(
    *,
    submission_record: UsdcPairSnapshotOrderPlanLiveSubmitRecord,
    order: Mapping[str, Any],
    open_order_read: M58OpenOrderRead,
) -> tuple[str, bool]:
    """Append local recovery evidence when readback proves cancellation."""

    store = FileUsdcPairSnapshotOrderPlanLiveSubmitStore()
    recovery_submission_id = f"{submission_record.submission_id}-readback-recovery"
    if store.find_by_submission_id(recovery_submission_id) is not None:
        return recovery_submission_id, False
    now = current_utc_timestamp()
    recovered = submission_record.model_copy(
        update={
            "submission_id": recovery_submission_id,
            "recorded_at": now,
            "cancelled_at": now,
            "cancel_submitted": True,
            "cancel_rollback_complete": True,
            "cancel_result": {
                "success": True,
                "client_order_id": submission_record.client_order_id,
                "fallback_order_id": submission_record.coinbase_order_id,
                "initial_cancel_result": submission_record.cancel_result,
                "order_readback_status": text_value(
                    order.get("status") or order.get("order_status")
                ),
                "order_readback_filled_value": decimal_text(
                    order.get("filled_value") or "0"
                ),
                "order_readback_total_fees": decimal_text(
                    order.get("total_fees") or "0"
                ),
                "open_product_order_count": len(open_order_read.orders),
            },
            "operator_notes": (
                "M58 readback recovery evidence: exchange order readback "
                "proved cancellation before additional orders."
            ),
            "live_coinbase_execution": "submitted_cancelled",
            "detail": (
                "M58 Phase E readback recovery evidence. Coinbase readback "
                "reported the order cancelled with zero fills, zero fees, and "
                "no open product orders."
            ),
        }
    )
    store.append(recovered)
    return recovery_submission_id, True


def order_cancelled(order: Mapping[str, Any]) -> bool:
    """Return whether an order readback status is cancelled."""

    return text_value(order.get("status") or order.get("order_status")).upper() in (
        CANCELLED_STATUSES
    )


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


def decimal_value(value: Any) -> Decimal:
    """Return a non-negative Decimal, defaulting blank values to zero."""

    text = text_value(value)
    if not text:
        return Decimal("0")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return number if number >= 0 else Decimal("0")


def decimal_text(value: Any) -> str:
    """Return stable decimal text for non-negative numeric values."""

    return format(decimal_value(value), "f")


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
    """Hydrate live-read Coinbase credentials before SDK construction."""

    ensure_live_coinbase_credentials(environ)
    refresh_configuration_credentials()


def build_coinbase_rest_client() -> Any:
    """Return the Coinbase SDK REST client for read-only order readback."""

    from coinbase.rest import RESTClient

    return RESTClient(
        api_key=os.environ["COINBASE_API_KEY"],
        api_secret=os.environ["COINBASE_API_SECRET"],
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the read-only M58 live readback and write evidence."""

    config = config_from_args(build_parser().parse_args(argv))
    if config.state_dir is not None:
        apply_usdc_pair_state_environment(config.state_dir)
    assert_live_read_credentials_present(os.environ)
    run_admin_api.apply_local_environment(run_admin_api.parse_args([]))
    summary = run_usdc_pair_snapshot_live_readback(
        build_coinbase_rest_client(),
        config,
    )
    write_json(config.summary_output, summary)
    print(
        "Backend M58 live readback: "
        f"{summary['status']}; read {summary['live_coinbase_read_ran']}; "
        f"order {summary['order_status']}; "
        f"executed {summary['executed_notional_usdc']} USDC; "
        f"artifact {config.summary_output.resolve()}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
