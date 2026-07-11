#!/usr/bin/env python3.13
"""Controlled successor proof for the ten-slot Admin Spot root/child batch.

Default mode is read-only. Exchange mutation additionally requires an
owner-only, unexpired immutable plan, its exact SHA-256, the exact
``--execute-controlled-batch`` flag, and the audited backend commit. One
embedded backend runtime resumes the consumed predecessor at its exact hidden
slot-1 child, then executes Test-profile ``BTC-USDC`` BUY/LIMIT/FOK roots for
slots 2 through 10. Each fully filled root authorizes exactly its deterministic
first SELL/LIMIT/GTC child, which is submitted far from market and cancelled
through the guarded Admin routes before the next root.

The predecessor plan, marker, one-record ledger, and final SDK sentinel are
read-only hash-bound evidence. A new fixed O_EXCL successor marker and ledger
consume the remaining 19 placements in the only legal order: child-1, then
root/child pairs for slots 2 through 10. A consumed or crashed successor cannot
resume, retry, or substitute a tuple. In-process SDK sentinels independently
enforce at most nine new roots and ten new children; cumulative evidence proves
ten roots and ten children across predecessor plus successor.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
from typing import Any
from uuid import NAMESPACE_OID, NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg2
import requests


ROOT = Path("/home/ec2-user/coinbase")
# Immutable production parent/tree audited before this runner-only commit.
EXPECTED_COMMIT = "cf9e804fefbc4672113847712327f481220239a1"
SECRET_ID = "coinbase/Test"
SECRET_REGION = "us-east-1"
PRODUCT_ID = "BTC-USDC"
PROFILE_LABEL = "Test"
HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID = (
    "ac466c4d-236d-4ef2-974a-eb0fe23c3445"
)
HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID = (
    "09a8fc00-7917-52bf-a145-8fa1ced3e756"
)
PORT = 8787
BASE_URL = f"http://127.0.0.1:{PORT}/api/v1"
ACTOR_ID = "operator-controlled-spot-proof"
COMMAND_ROLE = "trader"
ADMIN_ROLE = "admin"
ROOT_SUBMITTED_CAP = Decimal("9.99")
CHILD_SUBMITTED_CAP = Decimal("2.00")
TARGET_NOTIONAL = Decimal("1.10")
BATCH_SIZE = 10
CHILD_MINIMUM_BID_RATIO = Decimal("1.60")
BATCH_TOTAL_REFERENCE_CAP_USDC = Decimal("30.00")
PLANNED_ASK_RATIO = Decimal("1.0025")
MAX_ASK_RATIO = Decimal("1.005")
INTENTIONAL_FILL_OPERATOR_INTENT = (
    "execute_one_approved_intentional_test_profile_spot_fill"
)
CONTROLLED_CHILD_REVEAL_OPERATOR_INTENT = (
    "controlled_test_profile_first_child_reveal"
)
CONTROLLED_CHILD_CANCEL_OPERATOR_INTENT = (
    "controlled_test_profile_first_child_cancel"
)
HTTP_TIMEOUT_SECONDS = 20
COINBASE_SDK_TIMEOUT_SECONDS = 5
PLAN_TTL = timedelta(minutes=30)
TERMINAL_STATUSES = {
    "CANCELLED",
    "CANCELED",
    "EXPIRED",
    "FAILED",
    "REJECTED",
    "FILLED",
}
NO_FILL_TERMINAL_STATUSES = TERMINAL_STATUSES - {"FILLED"}
INTENTIONAL_FILL_CAPABILITIES = {
    "product_id": {
        PRODUCT_ID: {
            "direct_placement": "enabled",
            "stealth_planning": "enabled",
            "stealth_reveal": "disabled",
            "filled_follow_up": "conditional",
            "partial_fill_follow_up": "disabled",
            "cancelled_follow_up": "disabled",
            "same_side_post_fill_retreat": "disabled",
            "move_revealed": "disabled",
            "reprice_revealed": "disabled",
            "cancel_reentry": "disabled",
            "hotpoint_auto_placement": "disabled",
        }
    }
}
INTENTIONAL_FILL_FOLLOW_UP_INTENTS = {
    "product_id": {
        PRODUCT_ID: {
            "intents": {
                "exit": {"enabled": True},
                "rebuy": {"enabled": False},
                "same_side_replacement": {"enabled": False},
                "unsupported": {"enabled": False},
            }
        }
    }
}
INTENTIONAL_FILL_ACTION_GUARDS = {
    "wallet_available": {
        "enabled": True,
        "check_follow_up_planning": False,
        "fail_open_on_fetch_error": False,
        "block_without_credentials": True,
    },
    "limits": [],
}
GLOBAL_BATCH_REGISTRY_DIR = Path(
    "/var/tmp/coinbase-admin-controlled-spot-root-child-batches"
)
EXECUTION_LOCK_PATH = (
    GLOBAL_BATCH_REGISTRY_DIR / "controlled-root-child-batch.execution.lock"
)
PREDECESSOR_PLAN_PATH = Path(
    "/home/ec2-user/.local/state/coinbase-controlled-root-child-batch-20260711.plan.json"
)
PREDECESSOR_MARKER_PATH = GLOBAL_BATCH_REGISTRY_DIR / (
    "test-profile-btc-usdc-root-child-batch-20260711.authority.json"
)
PREDECESSOR_LEDGER_PATH = GLOBAL_BATCH_REGISTRY_DIR / (
    "test-profile-btc-usdc-root-child-batch-20260711.attempts.jsonl"
)
PREDECESSOR_STATE_DIR = ROOT / (
    "artifacts/controlled-root-child-batch-20260711T171916Z-4015ff61"
)
PREDECESSOR_SENTINEL_PATH = (
    PREDECESSOR_STATE_DIR / "sdk-boundary-sentinel.json"
)
PREDECESSOR_CLEANUP_PATH = (
    PREDECESSOR_STATE_DIR / "controlled-batch-cleanup.json"
)
PREDECESSOR_PLAN_BYTES_SHA256 = (
    "b60931d4c4ea3f22616250ee93f51c74854fcaf27357b2d8ec364451cf7ec246"
)
PREDECESSOR_PLAN_SHA256 = (
    "fde20fa7ec6ff174951cadb460b2c26714d037801898752ed0d4ee1d9e93be9e"
)
PREDECESSOR_MARKER_BYTES_SHA256 = (
    "ce81ce9bc5e85ae6a20f09f24c1db2a909645ff97a789d22a8e40e1f07ccc172"
)
PREDECESSOR_LEDGER_BYTES_SHA256 = (
    "65b8ce58cf50efc4e61ad83fc1e7f780d7d3e9e76bc78237c814a261187a3523"
)
PREDECESSOR_SENTINEL_BYTES_SHA256 = (
    "0df822c186a88a09498a8e63db10fc89ce80de61c33dce78795ca22c91ca1a8d"
)
PREDECESSOR_CLEANUP_BYTES_SHA256 = (
    "17cb46a3df5d22f902ec06574d03b7c35d56130fbdf3c8a3430dda56a9962456"
)
PREDECESSOR_BACKEND_COMMIT = "794516bffb16f5af9b98392e60d9f3037f169322"
PREDECESSOR_RUNNER_SHA256 = (
    "695deb8439d601a43b5a09f0f570b07ad612b9d7c115a1f0bc17eef64d942d8b"
)
PREDECESSOR_APPROVAL_ID = (
    "controlled-root-child-batch-82448d97-594b-4a58-9f24-b7cd51aa9be3"
)
PREDECESSOR_BATCH_ID = "45969fb1-6675-592b-ad96-37a1dfbb2c30"
CARRIED_ROOT_CLIENT_ORDER_ID = "a32a9839-d7dc-507d-bed8-8f4da1b2e2e7"
CARRIED_CHILD_CLIENT_ORDER_ID = "7fcadaa3-027f-5c09-b338-4e625ceee53f"
CARRIED_ROOT_EXCHANGE_ORDER_ID = "edc4c227-8937-4c1a-b437-1c93127c1fb2"
CARRIED_ROOT_PLANNED_NOTIONAL = Decimal("1.1000855217")
CARRIED_ROOT_FILLED_SIZE = Decimal("0.00001709")
CARRIED_ROOT_FILLED_VALUE = Decimal("1.0970980188")
CARRIED_ROOT_TOTAL_FEES = Decimal("0.00093253331598")
CARRIED_ROOT_CORRELATION_ID = (
    "corr-45969fb1-6675-592b-ad96-37a1dfbb2c30-root-1"
)
CARRIED_ROOT_ADMISSION_AUDIT_ID = "18860534-220e-46f9-a2e2-2ba91da4b025"
PREDECESSOR_PLANNED_ROOT_CLIENT_ORDER_IDS = (
    CARRIED_ROOT_CLIENT_ORDER_ID,
    "88fcb024-02f3-5a07-8552-82a6e8f75f0c",
    "10f54b2a-360b-5760-b185-4292de578f40",
    "c067da2e-08ed-5980-8bb8-18d7e59c00d9",
    "7b69ab27-7ab8-560c-8ea3-a55f7e3b20f2",
    "4357029d-675b-52fb-8820-cc6b8f7e67b4",
    "ec4769b4-4cc5-5a20-b6ec-972a9ca7ff15",
    "793e473f-bc6e-5267-bb6f-01607ed2b9aa",
    "26cecdc9-8c37-523c-b840-d51397b36a24",
    "8a2b5689-edd4-5851-a587-7ecd27f3bd39",
)
PREDECESSOR_PLANNED_CHILD_CLIENT_ORDER_IDS = (
    CARRIED_CHILD_CLIENT_ORDER_ID,
    "b82e543c-ea72-51b6-bc56-bee0bd7adcaa",
    "4d442ba8-2334-5d5c-a735-f33351d015c2",
    "34187415-2b38-502f-9882-81cf4163ac0c",
    "380e0a75-e809-5925-aebb-e4b943612039",
    "3dbeff2b-91d7-54cd-bfa7-5f17c988d959",
    "127b106d-d090-5802-922d-2d63bbfe63c1",
    "16f2ac02-a5c5-5ae2-9491-39ac57f32452",
    "1e3b4e11-e07d-5804-8bc1-6540286eeb3a",
    "25c8e065-1b0e-5874-b652-600af0d6cc8d",
)
SUCCESSOR_ROOT_ORDER_MAXIMUM = BATCH_SIZE - 1
SUCCESSOR_CHILD_ORDER_MAXIMUM = BATCH_SIZE
SUCCESSOR_ATTEMPT_COUNT = (
    SUCCESSOR_ROOT_ORDER_MAXIMUM + SUCCESSOR_CHILD_ORDER_MAXIMUM
)
PLAN_SCHEMA_VERSION = "5"
GLOBAL_BATCH_MARKER_FILENAME = (
    "test-profile-btc-usdc-root-child-successor-20260711.authority.json"
)
GLOBAL_BATCH_LEDGER_FILENAME = (
    "test-profile-btc-usdc-root-child-successor-20260711.attempts.jsonl"
)
SPOT_NONTERMINAL_STATUSES = (
    "PENDING",
    "OPEN",
    "QUEUED",
    "CANCEL_QUEUED",
    "EDIT_QUEUED",
)
SDK_BOUNDARY_SENTINEL_FILENAME = "sdk-boundary-sentinel.json"
RUNTIME_CHILD_AUTH_FILENAME = "runtime-child-authority.json"
RUNTIME_CHILD_AUTH_USED_FILENAME = "runtime-child-authority.used.json"
RUNTIME_CHILD_NONCE_ENV = "CONTROLLED_RUNTIME_CHILD_NONCE"
FOLLOW_UP_WAIT_SECONDS = 90
_CLEANUP_ACTIVE = False
_PENDING_TERMINATION_SIGNAL: int | None = None


class ProofFailure(RuntimeError):
    pass


def controlled_termination_handler(signum: int, _frame: Any) -> None:
    """Defer repeated termination signals while order recovery is active."""

    global _PENDING_TERMINATION_SIGNAL
    if _CLEANUP_ACTIVE:
        _PENDING_TERMINATION_SIGNAL = signum
        return
    raise KeyboardInterrupt(f"termination_signal:{signum}")


class ControlledExecutionLease:
    """Hold a process-local exclusive lease for the one controlled live proof."""

    def __init__(self) -> None:
        self.handle: Any | None = None

    def __enter__(self) -> "ControlledExecutionLease":
        _ensure_global_batch_registry()
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(EXECUTION_LOCK_PATH, flags, 0o600)
        except OSError as exc:
            raise ProofFailure("controlled_live_execution_lease_open_failed") from exc
        metadata = os.fstat(descriptor)
        try:
            require(
                stat.S_ISREG(metadata.st_mode),
                "controlled_live_execution_lease_not_regular",
            )
            require(
                metadata.st_uid == os.getuid(),
                "controlled_live_execution_lease_owner_mismatch",
            )
            require(
                metadata.st_mode & 0o077 == 0,
                "controlled_live_execution_lease_permissions_too_broad",
            )
            self.handle = os.fdopen(descriptor, "a+", encoding="utf-8")
        except Exception:
            os.close(descriptor)
            raise
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            self.handle = None
            raise ProofFailure("controlled_live_execution_lease_already_held") from exc
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        if self.handle is None:
            return
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def repo_backend_runtime_pids() -> list[int]:
    """Return backend runtime processes rooted in the audited repository."""

    runtime_markers = (
        "main.py",
        "dashboard_server",
        "run_admin_api",
        "run_local_admin_api",
    )
    pids: list[int] = []
    for proc_path in Path("/proc").iterdir():
        if not proc_path.name.isdigit():
            continue
        pid = int(proc_path.name)
        if pid == os.getpid():
            continue
        try:
            cwd = (proc_path / "cwd").resolve(strict=True)
            process_name = (proc_path / "comm").read_text(encoding="utf-8").strip()
            command = (proc_path / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if (
            cwd == ROOT
            and process_name.startswith(("python", "uvicorn", "gunicorn"))
            and any(marker in command for marker in runtime_markers)
        ):
            pids.append(pid)
    return sorted(pids)


def require_runtime_exclusivity(
    *,
    allowed_runtime_pids: set[int] | None = None,
    require_port_free: bool,
) -> None:
    """Fail closed when another backend runtime or listener can share authority."""

    allowed = allowed_runtime_pids or set()
    competing = [pid for pid in repo_backend_runtime_pids() if pid not in allowed]
    require(not competing, f"competing_backend_runtime_pids:{competing}")
    if not require_port_free:
        return
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", PORT))
    except OSError as exc:
        raise ProofFailure(f"embedded_runtime_port_not_exclusive:{PORT}") from exc
    finally:
        probe.close()


def object_record(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return dict(converted) if isinstance(converted, Mapping) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def list_value(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofFailure(message)


def successor_attempt_schedule() -> list[tuple[int, str]]:
    """Return the only remaining placement order after predecessor root-1."""

    return [(1, "child")] + [
        item
        for slot in range(2, BATCH_SIZE + 1)
        for item in ((slot, "root"), (slot, "child"))
    ]


def _carried_root_order() -> dict[str, Any]:
    return {
        "client_order_id": CARRIED_ROOT_CLIENT_ORDER_ID,
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "order_type": "LIMIT",
        "base_size": decimal_text(CARRIED_ROOT_FILLED_SIZE),
        "limit_price": "64370.13",
        "post_only": False,
        "time_in_force": "FILL_OR_KILL",
        "manual_live_acknowledgement": True,
    }


def offline_predecessor_binding_fixture() -> dict[str, Any]:
    """Return the immutable predecessor identity used by pure self-tests."""

    return {
        "schema_version": "1",
        "plan_path": str(PREDECESSOR_PLAN_PATH),
        "plan_bytes_sha256": PREDECESSOR_PLAN_BYTES_SHA256,
        "plan_sha256": PREDECESSOR_PLAN_SHA256,
        "marker_path": str(PREDECESSOR_MARKER_PATH),
        "marker_bytes_sha256": PREDECESSOR_MARKER_BYTES_SHA256,
        "ledger_path": str(PREDECESSOR_LEDGER_PATH),
        "ledger_bytes_sha256": PREDECESSOR_LEDGER_BYTES_SHA256,
        "sentinel_path": str(PREDECESSOR_SENTINEL_PATH),
        "sentinel_bytes_sha256": PREDECESSOR_SENTINEL_BYTES_SHA256,
        "cleanup_path": str(PREDECESSOR_CLEANUP_PATH),
        "cleanup_bytes_sha256": PREDECESSOR_CLEANUP_BYTES_SHA256,
        "backend_commit": PREDECESSOR_BACKEND_COMMIT,
        "runner_sha256": PREDECESSOR_RUNNER_SHA256,
        "approval_id": PREDECESSOR_APPROVAL_ID,
        "batch_id": PREDECESSOR_BATCH_ID,
        "portfolio_id": "62f28f44-8e72-4fe0-ace7-d71a01f54883",
        "root_slot": 1,
        "root_client_order_id": CARRIED_ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": CARRIED_CHILD_CLIENT_ORDER_ID,
        "root_exchange_order_id": CARRIED_ROOT_EXCHANGE_ORDER_ID,
        "root_planned_notional_usdc": decimal_text(
            CARRIED_ROOT_PLANNED_NOTIONAL
        ),
        "root_filled_size": decimal_text(CARRIED_ROOT_FILLED_SIZE),
        "root_filled_value": decimal_text(CARRIED_ROOT_FILLED_VALUE),
        "root_total_fees": decimal_text(CARRIED_ROOT_TOTAL_FEES),
        "root_correlation_id": CARRIED_ROOT_CORRELATION_ID,
        "root_admission_audit_id": CARRIED_ROOT_ADMISSION_AUDIT_ID,
        "root_order": _carried_root_order(),
        "predecessor_planned_root_client_order_ids": list(
            PREDECESSOR_PLANNED_ROOT_CLIENT_ORDER_IDS
        ),
        "predecessor_planned_child_client_order_ids": list(
            PREDECESSOR_PLANNED_CHILD_CLIENT_ORDER_IDS
        ),
        "predecessor_attempt_count": 1,
        "predecessor_root_sdk_call_count": 1,
        "predecessor_child_sdk_call_count": 0,
        "predecessor_service_disabled": True,
        "predecessor_runtime_stopped_required": True,
    }


def _read_owner_only_bytes(
    path: Path,
    *,
    blocker_prefix: str,
    maximum_size: int = 100_000,
    allow_group_world_read: bool = False,
) -> bytes:
    """Read immutable evidence without following a symlink."""

    require(path.is_absolute(), f"{blocker_prefix}_path_not_absolute")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProofFailure(f"{blocker_prefix}_open_failed") from exc
    try:
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode), f"{blocker_prefix}_not_regular")
        require(metadata.st_uid == os.getuid(), f"{blocker_prefix}_owner_mismatch")
        if allow_group_world_read:
            require(
                metadata.st_mode & 0o033 == 0,
                f"{blocker_prefix}_permissions_too_broad",
            )
        else:
            require(
                metadata.st_mode & 0o077 == 0,
                f"{blocker_prefix}_permissions_too_broad",
            )
        require(
            0 < metadata.st_size <= maximum_size,
            f"{blocker_prefix}_size_invalid",
        )
        raw = os.read(descriptor, maximum_size + 1)
    finally:
        os.close(descriptor)
    require(0 < len(raw) <= maximum_size, f"{blocker_prefix}_size_invalid")
    return raw


def _decode_predecessor_json(
    raw: bytes,
    *,
    blocker: str,
) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofFailure(blocker) from exc
    require(isinstance(value, dict), blocker)
    return dict(value)


def _predecessor_exact_root_tuple(
    predecessor_plan: Mapping[str, Any],
) -> dict[str, Any]:
    roots = [
        object_record(item)
        for item in list_value(predecessor_plan.get("roots"))
    ]
    require(len(roots) == BATCH_SIZE, "predecessor_plan_root_count_mismatch")
    root = roots[0]
    order = object_record(root.get("order"))
    approvals = object_record(root.get("proof_approval_ids"))
    return {
        "approval_id": str(approvals.get("root_place") or ""),
        "batch_id": PREDECESSOR_BATCH_ID,
        "batch_slot": 1,
        "operator_intent": INTENTIONAL_FILL_OPERATOR_INTENT,
        "portfolio_id": str(predecessor_plan.get("portfolio_id") or ""),
        "portfolio_label": PROFILE_LABEL,
        "client_order_id": CARRIED_ROOT_CLIENT_ORDER_ID,
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "order_type": "LIMIT",
        "time_in_force": "FILL_OR_KILL",
        "base_size": str(order.get("base_size") or ""),
        "limit_price": str(order.get("limit_price") or ""),
        "post_only": False,
        "size_in_quote": False,
        "quote_size": None,
    }


def validate_predecessor_artifacts(
    *,
    plan_raw: bytes,
    marker_raw: bytes,
    ledger_raw: bytes,
    sentinel_raw: bytes,
    cleanup_raw: bytes,
) -> dict[str, Any]:
    """Validate old bytes with their old runner/commit semantics exactly."""

    for raw, expected, blocker in (
        (plan_raw, PREDECESSOR_PLAN_BYTES_SHA256, "predecessor_plan_bytes_changed"),
        (
            marker_raw,
            PREDECESSOR_MARKER_BYTES_SHA256,
            "predecessor_marker_bytes_changed",
        ),
        (
            ledger_raw,
            PREDECESSOR_LEDGER_BYTES_SHA256,
            "predecessor_ledger_bytes_changed",
        ),
        (
            sentinel_raw,
            PREDECESSOR_SENTINEL_BYTES_SHA256,
            "predecessor_sentinel_bytes_changed",
        ),
        (
            cleanup_raw,
            PREDECESSOR_CLEANUP_BYTES_SHA256,
            "predecessor_cleanup_bytes_changed",
        ),
    ):
        require(hashlib.sha256(raw).hexdigest() == expected, blocker)
    predecessor_plan = _decode_predecessor_json(
        plan_raw,
        blocker="predecessor_plan_malformed",
    )
    marker = _decode_predecessor_json(
        marker_raw,
        blocker="predecessor_marker_malformed",
    )
    sentinel = _decode_predecessor_json(
        sentinel_raw,
        blocker="predecessor_sentinel_malformed",
    )
    cleanup = _decode_predecessor_json(
        cleanup_raw,
        blocker="predecessor_cleanup_malformed",
    )
    try:
        ledger_lines = ledger_raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ProofFailure("predecessor_ledger_not_utf8") from exc
    require(len(ledger_lines) == 1, "predecessor_ledger_record_count_mismatch")
    try:
        ledger_record = json.loads(ledger_lines[0])
    except json.JSONDecodeError as exc:
        raise ProofFailure("predecessor_ledger_malformed") from exc
    require(isinstance(ledger_record, dict), "predecessor_ledger_record_not_object")
    require(
        predecessor_plan.get("plan_sha256") == PREDECESSOR_PLAN_SHA256
        and plan_hash(predecessor_plan) == PREDECESSOR_PLAN_SHA256,
        "predecessor_plan_hash_mismatch",
    )
    require(
        predecessor_plan.get("backend_commit") == PREDECESSOR_BACKEND_COMMIT
        and predecessor_plan.get("runner_sha256") == PREDECESSOR_RUNNER_SHA256
        and predecessor_plan.get("approval_id") == PREDECESSOR_APPROVAL_ID
        and predecessor_plan.get("batch_id") == PREDECESSOR_BATCH_ID
        and predecessor_plan.get("batch_size") == BATCH_SIZE
        and predecessor_plan.get("portfolio_label") == PROFILE_LABEL
        and predecessor_plan.get("product_id") == PRODUCT_ID,
        "predecessor_plan_identity_mismatch",
    )
    roots = [
        object_record(item)
        for item in list_value(predecessor_plan.get("roots"))
    ]
    predecessor_root_ids = [
        str(root.get("root_client_order_id") or "") for root in roots
    ]
    predecessor_child_ids = [
        str(root.get("child_client_order_id") or "") for root in roots
    ]
    require(
        predecessor_root_ids == list(PREDECESSOR_PLANNED_ROOT_CLIENT_ORDER_IDS)
        and predecessor_child_ids
        == list(PREDECESSOR_PLANNED_CHILD_CLIENT_ORDER_IDS),
        "predecessor_planned_ids_mismatch",
    )
    carried_root = roots[0]
    require(
        carried_root.get("slot") == 1
        and carried_root.get("root_client_order_id")
        == CARRIED_ROOT_CLIENT_ORDER_ID
        and carried_root.get("child_client_order_id")
        == CARRIED_CHILD_CLIENT_ORDER_ID
        and object_record(carried_root.get("order")) == _carried_root_order()
        and carried_root.get("planned_notional_usdc")
        == decimal_text(CARRIED_ROOT_PLANNED_NOTIONAL)
        and deterministic_child_client_order_id(CARRIED_ROOT_CLIENT_ORDER_ID)
        == CARRIED_CHILD_CLIENT_ORDER_ID,
        "predecessor_carried_root_mismatch",
    )
    require(
        marker.get("authority") == "controlled-admin-spot-root-child-batch"
        and marker.get("plan_file") == str(PREDECESSOR_PLAN_PATH)
        and marker.get("plan_sha256") == PREDECESSOR_PLAN_SHA256
        and marker.get("runner_sha256") == PREDECESSOR_RUNNER_SHA256
        and marker.get("backend_commit") == PREDECESSOR_BACKEND_COMMIT
        and marker.get("approval_id") == PREDECESSOR_APPROVAL_ID
        and marker.get("batch_id") == PREDECESSOR_BATCH_ID
        and marker.get("attempt_ledger_path") == str(PREDECESSOR_LEDGER_PATH)
        and marker.get("marker_path") == str(PREDECESSOR_MARKER_PATH)
        and marker.get("root_order_maximum") == BATCH_SIZE
        and marker.get("child_order_maximum") == BATCH_SIZE,
        "predecessor_marker_binding_mismatch",
    )
    exact_root_tuples = [
        object_record(item)
        for item in list_value(marker.get("exact_root_tuples"))
    ]
    require(
        len(exact_root_tuples) == BATCH_SIZE
        and exact_root_tuples[0] == _predecessor_exact_root_tuple(predecessor_plan),
        "predecessor_marker_root_tuple_mismatch",
    )
    require(
        ledger_record.get("schema_version") == "1"
        and ledger_record.get("sequence") == 1
        and ledger_record.get("batch_id") == PREDECESSOR_BATCH_ID
        and ledger_record.get("batch_slot") == 1
        and ledger_record.get("attempt_kind") == "root"
        and ledger_record.get("client_order_id")
        == CARRIED_ROOT_CLIENT_ORDER_ID
        and ledger_record.get("root_client_order_id")
        == CARRIED_ROOT_CLIENT_ORDER_ID
        and ledger_record.get("plan_sha256") == PREDECESSOR_PLAN_SHA256
        and ledger_record.get("runner_sha256") == PREDECESSOR_RUNNER_SHA256
        and ledger_record.get("backend_commit") == PREDECESSOR_BACKEND_COMMIT
        and object_record(ledger_record.get("exact_order_tuple"))
        == _predecessor_exact_root_tuple(predecessor_plan)
        and ledger_record.get("exact_order_tuple_sha256")
        == _canonical_json_sha256(
            _predecessor_exact_root_tuple(predecessor_plan)
        ),
        "predecessor_ledger_root_record_mismatch",
    )
    require(
        sentinel.get("installed") is True
        and sentinel.get("wrapper_identity_proven") is True
        and sentinel.get("root_create_order_call_count") == 1
        and sentinel.get("child_place_limit_order_call_count") == 0
        and sentinel.get("root_sdk_inflight") is False
        and sentinel.get("child_sdk_inflight") is False
        and sentinel.get("denied_call_count") == 0
        and sentinel.get("critical_failure") is False
        and sentinel.get("phase") == "runtime_exited",
        "predecessor_sentinel_mismatch",
    )
    require(
        cleanup.get("live_service_disable_attempted") is True
        and cleanup.get("live_service_disable_proven_before_cleanup") is True
        and cleanup.get("live_service_disable_proven_after_cleanup") is True
        and cleanup.get("runtime_pid") == sentinel.get("process_id"),
        "predecessor_cleanup_service_disable_mismatch",
    )
    binding = offline_predecessor_binding_fixture()
    require(
        binding["portfolio_id"] == predecessor_plan.get("portfolio_id"),
        "predecessor_portfolio_mismatch",
    )
    return binding


def load_predecessor_binding() -> dict[str, Any]:
    """Read and validate predecessor evidence without writing any old path."""

    return validate_predecessor_artifacts(
        plan_raw=_read_owner_only_bytes(
            PREDECESSOR_PLAN_PATH,
            blocker_prefix="predecessor_plan",
        ),
        marker_raw=_read_owner_only_bytes(
            PREDECESSOR_MARKER_PATH,
            blocker_prefix="predecessor_marker",
        ),
        ledger_raw=_read_owner_only_bytes(
            PREDECESSOR_LEDGER_PATH,
            blocker_prefix="predecessor_ledger",
        ),
        sentinel_raw=_read_owner_only_bytes(
            PREDECESSOR_SENTINEL_PATH,
            blocker_prefix="predecessor_sentinel",
        ),
        cleanup_raw=_read_owner_only_bytes(
            PREDECESSOR_CLEANUP_PATH,
            blocker_prefix="predecessor_cleanup",
            allow_group_world_read=True,
        ),
    )


def hydrate_test_credentials() -> Any:
    os.environ.pop("COINBASE_API_KEY", None)
    os.environ.pop("COINBASE_API_SECRET", None)
    os.environ["COINBASE_SECRETS_MANAGER_SECRET_ID"] = SECRET_ID
    os.environ["COINBASE_SECRETS_MANAGER_REGION"] = SECRET_REGION
    sys.path.insert(0, str(ROOT))
    from tools.coinbase_live_credentials import ensure_live_coinbase_credentials

    ensure_live_coinbase_credentials(os.environ)
    from coinbase.rest import RESTClient

    client = RESTClient(
        api_key=os.environ["COINBASE_API_KEY"],
        api_secret=os.environ["COINBASE_API_SECRET"],
        timeout=COINBASE_SDK_TIMEOUT_SECONDS,
    )
    client.session.trust_env = False
    return client


def read_authoritative_spot_nonterminal_orders(
    rest_client: Any,
    *,
    expected_portfolio_id: str,
) -> list[dict[str, Any]]:
    """Read every exact-profile active Spot row, failing on scope ambiguity.

    Coinbase requires ``OPEN`` as the aggregate active-order query token. The
    returned row status is then validated against every recognized active state.
    """

    rows_by_exchange_id: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(20):
        kwargs: dict[str, Any] = {
            "order_status": ["OPEN"],
            "product_type": "SPOT",
            "retail_portfolio_id": expected_portfolio_id,
            "limit": 100,
        }
        if cursor:
            kwargs["cursor"] = cursor
        page = object_record(rest_client.list_orders(**kwargs))
        raw_orders = page.get("orders")
        require(isinstance(raw_orders, list), "active_spot_order_read_malformed")
        for item in raw_orders:
            require(isinstance(item, Mapping), "active_spot_order_row_not_object")
            row = dict(item)
            for field in (
                "client_order_id",
                "order_id",
                "status",
                "product_id",
                "product_type",
                "retail_portfolio_id",
            ):
                require(
                    bool(str(row.get(field) or "").strip()),
                    f"active_spot_order_row_missing:{field}",
                )
            status = str(row["status"]).upper()
            require(
                status in SPOT_NONTERMINAL_STATUSES,
                f"active_spot_order_unexpected_status:{status}",
            )
            require(
                str(row["product_type"]).upper() == "SPOT",
                "active_spot_order_product_type_mismatch",
            )
            require(
                row["retail_portfolio_id"] == expected_portfolio_id,
                "active_spot_order_portfolio_mismatch",
            )
            exchange_order_id = str(row["order_id"])
            existing = rows_by_exchange_id.get(exchange_order_id)
            if existing is not None:
                for field in (
                    "client_order_id",
                    "product_id",
                    "product_type",
                    "retail_portfolio_id",
                ):
                    require(
                        str(existing.get(field) or "")
                        == str(row.get(field) or ""),
                        "active_spot_order_conflicting_identity",
                    )
            else:
                rows_by_exchange_id[exchange_order_id] = row
        has_next = page.get("has_next")
        require(isinstance(has_next, bool), "active_spot_order_pagination_malformed")
        if not has_next:
            return list(rows_by_exchange_id.values())
        cursor = str(page.get("cursor") or "").strip()
        require(bool(cursor), "active_spot_order_pagination_cursor_missing")
        require(
            cursor not in seen_cursors,
            "active_spot_order_pagination_cursor_repeated",
        )
        seen_cursors.add(cursor)
    raise ProofFailure("active_spot_order_pagination_limit_exceeded")


def fresh_exact_market(rest_client: Any) -> dict[str, Any]:
    """Read one exact BTC-USDC bid/ask pricebook from Coinbase."""

    response = object_record(rest_client.get_best_bid_ask(product_ids=[PRODUCT_ID]))
    books = [object_record(item) for item in list_value(response.get("pricebooks"))]
    require(len(books) == 1, "exact_market_pricebook_missing")
    require(
        str(books[0].get("product_id") or "") == PRODUCT_ID,
        "exact_market_product_mismatch",
    )
    bids = [object_record(item) for item in list_value(books[0].get("bids"))]
    asks = [object_record(item) for item in list_value(books[0].get("asks"))]
    require(bool(bids), "best_bid_missing")
    require(bool(asks), "best_ask_missing")
    bid = Decimal(str(bids[0].get("price") or "0"))
    ask = Decimal(str(asks[0].get("price") or "0"))
    require(bid.is_finite() and bid > 0, "best_bid_invalid")
    require(ask.is_finite() and ask > 0, "best_ask_invalid")
    require(ask >= bid, "exact_market_crossed_book")
    observed_at = str(books[0].get("time") or response.get("time") or "").strip()
    require(bool(observed_at), "exact_market_observed_at_missing")
    try:
        parsed_observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProofFailure("exact_market_observed_at_invalid") from exc
    require(
        parsed_observed_at.tzinfo is not None,
        "exact_market_observed_at_timezone_missing",
    )
    age_seconds = (datetime.now(timezone.utc) - parsed_observed_at).total_seconds()
    require(-1 <= age_seconds <= 30, "exact_market_observed_at_stale")
    return {
        "product_id": PRODUCT_ID,
        "best_bid": bid,
        "best_ask": ask,
        "observed_at": observed_at,
        "age_seconds": age_seconds,
        "source": "coinbase_rest_get_best_bid_ask_exact_product",
    }


def coinbase_preflight(rest_client: Any) -> dict[str, Any]:
    permissions = object_record(rest_client.get_api_key_permissions())
    permissioned_id = str(permissions.get("portfolio_uuid") or "").strip()
    require(bool(permissioned_id), "permissioned_portfolio_id_missing")
    require(permissions.get("portfolio_type") == "CONSUMER", "portfolio_type_mismatch")
    require(permissions.get("can_view") is True, "portfolio_view_permission_missing")
    require(permissions.get("can_trade") is True, "portfolio_trade_permission_missing")

    portfolios = object_record(rest_client.get_portfolios())
    portfolio_rows = [
        object_record(item) for item in list_value(portfolios.get("portfolios"))
    ]
    named_test = [
        row for row in portfolio_rows if str(row.get("name") or "").strip() == PROFILE_LABEL
    ]
    require(len(named_test) == 1, "named_test_portfolio_not_unique")
    require(str(named_test[0].get("uuid") or "") == permissioned_id, "test_portfolio_mismatch")

    accounts = object_record(rest_client.get_accounts(limit=250))
    account_rows = [object_record(item) for item in list_value(accounts.get("accounts"))]
    require(bool(account_rows), "account_catalog_empty")
    account_profile_ids = {
        str(row.get("retail_portfolio_id") or row.get("portfolio_uuid") or "")
        for row in account_rows
    }
    require(account_profile_ids == {permissioned_id}, "account_profile_scope_mismatch")
    wallets: dict[str, Decimal] = {}
    for row in account_rows:
        currency = str(row.get("currency") or "").upper()
        if currency in {"BTC", "USD", "USDC"}:
            available = object_record(row.get("available_balance"))
            wallets[currency] = Decimal(str(available.get("value") or "0"))
    require(
        wallets.get("USDC", Decimal("0")) >= ROOT_SUBMITTED_CAP,
        "usdc_wallet_insufficient",
    )

    product = object_record(rest_client.get_product(PRODUCT_ID))
    expected_metadata = {
        "product_id": PRODUCT_ID,
        "product_type": "SPOT",
        "base_currency_id": "BTC",
        "quote_currency_id": "USDC",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "price_increment": "0.01",
        "base_min_size": "0.00000001",
        "quote_min_size": "1",
    }
    for key, expected in expected_metadata.items():
        require(str(product.get(key) or "") == expected, f"product_metadata_mismatch:{key}")
    require(product.get("trading_disabled") is False, "product_trading_disabled")
    require(product.get("is_disabled") is False, "product_disabled")
    require(product.get("view_only") is False, "product_view_only")

    configured = json.loads((ROOT / "products.json").read_text(encoding="utf-8"))
    require(configured.get("spot") == [PRODUCT_ID], "configured_spot_catalog_mismatch")
    configured_product = object_record(
        object_record(configured.get("metadata")).get(PRODUCT_ID)
    )
    for key in (
        "base_increment",
        "quote_increment",
        "price_increment",
        "base_min_size",
        "quote_min_size",
    ):
        require(
            str(configured_product.get(key) or "") == str(product.get(key) or ""),
            f"configured_product_metadata_mismatch:{key}",
        )

    active_orders = read_authoritative_spot_nonterminal_orders(
        rest_client,
        expected_portfolio_id=permissioned_id,
    )
    require(not active_orders, "authoritative_active_spot_orders_present")
    market = fresh_exact_market(rest_client)
    return {
        "portfolio_id": permissioned_id,
        "wallets": wallets,
        "product": product,
        "market": market,
        "best_bid": market["best_bid"],
        "best_ask": market["best_ask"],
        "active_spot_order_count": 0,
    }


def local_nonterminal_counts(*, exact_admin_scope: bool) -> dict[str, int]:
    connection = psycopg2.connect(
        host=os.environ.get("COINBASE_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("COINBASE_DB_PORT", "5432")),
        dbname=os.environ.get("COINBASE_DB_NAME", "postgres"),
        user=os.environ.get("COINBASE_DB_USER", "postgres"),
        password=os.environ.get("COINBASE_DB_PASSWORD", "postgres"),
    )
    try:
        with connection.cursor() as cursor:
            if exact_admin_scope:
                cursor.execute(
                    """
                    SELECT count(*) FROM order_parent
                    WHERE ownership_provenance = 'ADMIN_MANUAL_ROOT'
                      AND upper(status) NOT IN
                          ('FILLED','CANCELLED','CANCELED','FAILED','REJECTED','EXPIRED')
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT count(*) FROM order_parent
                    WHERE upper(status) NOT IN
                          ('FILLED','CANCELLED','CANCELED','FAILED','REJECTED','EXPIRED')
                    """
                )
            parent_count = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT count(*) FROM stealth_orders
                WHERE upper(status) NOT IN
                    ('EXECUTED','FILLED','CANCELLED','CANCELED','FAILED','REJECTED','EXPIRED')
                """
            )
            stealth_count = int(cursor.fetchone()[0])
    finally:
        connection.close()
    return {"parent": parent_count, "stealth": stealth_count}


def prove_local_scope_with_historical_hidden_child(
    *,
    planned_client_order_ids: set[str],
    carried_root_plan: Mapping[str, Any] | None = None,
    require_carried_hidden: bool = False,
) -> dict[str, Any]:
    """Allow only the exact prior FILLED root and wholly unsubmitted child.

    This is deliberately a read-only identity exception, not reusable cleanup
    authority. No command emitted by this runner may target either historical
    identifier.
    """

    immutable_historical_ids = {
        HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID,
        HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID,
    }
    carried_ids = (
        {CARRIED_ROOT_CLIENT_ORDER_ID, CARRIED_CHILD_CLIENT_ORDER_ID}
        if carried_root_plan is not None
        else set()
    )
    require(
        not (planned_client_order_ids - carried_ids)
        & (immutable_historical_ids | carried_ids),
        "batch_ids_overlap_historical_chain",
    )
    connection = psycopg2.connect(
        host=os.environ.get("COINBASE_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("COINBASE_DB_PORT", "5432")),
        dbname=os.environ.get("COINBASE_DB_NAME", "postgres"),
        user=os.environ.get("COINBASE_DB_USER", "postgres"),
        password=os.environ.get("COINBASE_DB_PASSWORD", "postgres"),
    )

    def row_dict(cursor: Any, row: Any) -> dict[str, Any]:
        require(row is not None, "historical_chain_row_missing")
        return dict(zip([column[0] for column in cursor.description], row))

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT client_order_id, parent_order_id, product_id, side,
                          size, status, ownership_provenance,
                          retail_portfolio_id, correlation_id, audit_id,
                          exchange_order_id
                     FROM order_parent
                    WHERE client_order_id = %s""",
                (HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID,),
            )
            root = row_dict(cursor, cursor.fetchone())
            cursor.execute(
                """SELECT client_order_id, parent_order_id, product_id, side,
                          size, status, ownership_provenance,
                          retail_portfolio_id, correlation_id, audit_id,
                          exchange_order_id
                     FROM order_parent
                    WHERE client_order_id = %s""",
                (HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID,),
            )
            child = row_dict(cursor, cursor.fetchone())
            cursor.execute(
                """SELECT stealth_order_id, parent_order_id, product_id, side,
                          total_size, remaining_size, revealed_size,
                          executed_size, status, revealed_orders,
                          last_placement_at, condition_first_met_at,
                          condition_confirmed_at, anchor_repricing_state_json
                     FROM stealth_orders
                    WHERE stealth_order_id = %s""",
                (HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID,),
            )
            stealth = row_dict(cursor, cursor.fetchone())
            carried_root: dict[str, Any] | None = None
            carried_child: dict[str, Any] | None = None
            carried_stealth: dict[str, Any] | None = None
            if carried_root_plan is not None:
                cursor.execute(
                    """SELECT client_order_id, parent_order_id, product_id, side,
                              size, status, ownership_provenance,
                              retail_portfolio_id, correlation_id, audit_id,
                              exchange_order_id
                         FROM order_parent
                        WHERE client_order_id = %s""",
                    (CARRIED_ROOT_CLIENT_ORDER_ID,),
                )
                carried_root = row_dict(cursor, cursor.fetchone())
                cursor.execute(
                    """SELECT client_order_id, parent_order_id, product_id, side,
                              size, status, ownership_provenance,
                              retail_portfolio_id, correlation_id, audit_id,
                              exchange_order_id
                         FROM order_parent
                        WHERE client_order_id = %s""",
                    (CARRIED_CHILD_CLIENT_ORDER_ID,),
                )
                carried_child = row_dict(cursor, cursor.fetchone())
                cursor.execute(
                    """SELECT stealth_order_id, parent_order_id, product_id, side,
                              total_size, remaining_size, revealed_size,
                              executed_size, status, revealed_orders,
                              last_placement_at, condition_first_met_at,
                              condition_confirmed_at, anchor_repricing_state_json
                         FROM stealth_orders
                        WHERE stealth_order_id = %s""",
                    (CARRIED_CHILD_CLIENT_ORDER_ID,),
                )
                carried_stealth = row_dict(cursor, cursor.fetchone())
            cursor.execute(
                """SELECT client_order_id
                     FROM order_parent
                    WHERE upper(status) NOT IN
                          ('FILLED','CANCELLED','CANCELED','FAILED',
                           'REJECTED','EXPIRED')
                    ORDER BY client_order_id"""
            )
            nonterminal_parents = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT stealth_order_id
                     FROM stealth_orders
                    WHERE upper(status) NOT IN
                          ('EXECUTED','FILLED','CANCELLED','CANCELED','FAILED',
                           'REJECTED','EXPIRED')
                    ORDER BY stealth_order_id"""
            )
            nonterminal_stealth = [str(row[0]) for row in cursor.fetchall()]
    finally:
        connection.close()

    require(
        root.get("client_order_id")
        == HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID,
        "historical_root_identity_mismatch",
    )
    require(not root.get("parent_order_id"), "historical_root_not_flat")
    require(
        root.get("product_id") == PRODUCT_ID
        and str(root.get("side") or "").upper() == "BUY"
        and str(root.get("status") or "").upper() == "FILLED"
        and root.get("ownership_provenance") == "ADMIN_MANUAL_ROOT"
        and bool(str(root.get("exchange_order_id") or "")),
        "historical_root_evidence_mismatch",
    )
    require(
        deterministic_child_client_order_id(
            HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID
        )
        == HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID,
        "historical_child_not_deterministic",
    )
    require(
        child.get("client_order_id")
        == HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID
        and str(child.get("parent_order_id") or "")
        == HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID
        and child.get("product_id") == PRODUCT_ID
        and str(child.get("side") or "").upper() == "SELL"
        and str(child.get("status") or "").upper() == "PENDING"
        and child.get("ownership_provenance") == "ADMIN_FILL_FOLLOW_UP"
        and not child.get("exchange_order_id"),
        "historical_child_tracking_evidence_mismatch",
    )
    require(
        str(root.get("retail_portfolio_id") or "")
        == str(child.get("retail_portfolio_id") or "")
        and bool(str(root.get("retail_portfolio_id") or "")),
        "historical_chain_portfolio_mismatch",
    )
    require(
        str(root.get("correlation_id") or "")
        == str(child.get("correlation_id") or "")
        and bool(str(root.get("correlation_id") or "")),
        "historical_chain_correlation_mismatch",
    )
    require(
        str(root.get("audit_id") or "")
        == str(child.get("audit_id") or "")
        and bool(str(root.get("audit_id") or "")),
        "historical_chain_audit_mismatch",
    )
    anchor_state = object_record(stealth.get("anchor_repricing_state_json"))
    revealed_orders = list_value(stealth.get("revealed_orders"))
    require(
        str(stealth.get("stealth_order_id") or "")
        == HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID
        and str(stealth.get("parent_order_id") or "")
        == HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID
        and stealth.get("product_id") == PRODUCT_ID
        and str(stealth.get("side") or "").upper() == "SELL"
        and str(stealth.get("status") or "").upper() == "HIDDEN",
        "historical_stealth_child_identity_mismatch",
    )
    total_size = Decimal(str(stealth.get("total_size") or "0"))
    require(
        total_size > 0
        and total_size == Decimal(str(stealth.get("remaining_size") or "0"))
        and Decimal(str(stealth.get("revealed_size") or "0")) == 0
        and Decimal(str(stealth.get("executed_size") or "0")) == 0
        and total_size == Decimal(str(child.get("size") or "0"))
        and not revealed_orders
        and stealth.get("last_placement_at") is None
        and not anchor_state.get("active_placement_client_order_id")
        and not anchor_state.get("active_exchange_order_id")
        and not anchor_state.get(
            "controlled_admin_first_child_reveal_preparation"
        ),
        "historical_stealth_child_not_wholly_unsubmitted",
    )
    carried_scope: dict[str, Any] | None = None
    carried_nonterminal = False
    if carried_root_plan is not None:
        require(
            carried_root is not None
            and carried_child is not None
            and carried_stealth is not None,
            "carried_chain_row_missing",
        )
        require(
            carried_root.get("client_order_id")
            == CARRIED_ROOT_CLIENT_ORDER_ID
            and not carried_root.get("parent_order_id")
            and carried_root.get("product_id") == PRODUCT_ID
            and str(carried_root.get("side") or "").upper() == "BUY"
            and str(carried_root.get("status") or "").upper() == "FILLED"
            and carried_root.get("ownership_provenance")
            == "ADMIN_MANUAL_ROOT"
            and carried_root.get("exchange_order_id")
            == CARRIED_ROOT_EXCHANGE_ORDER_ID
            and carried_root.get("retail_portfolio_id")
            == offline_predecessor_binding_fixture()["portfolio_id"]
            and Decimal(str(carried_root.get("size") or "0"))
            == CARRIED_ROOT_FILLED_SIZE
            and carried_root.get("correlation_id")
            == CARRIED_ROOT_CORRELATION_ID
            and carried_root.get("audit_id")
            == CARRIED_ROOT_ADMISSION_AUDIT_ID,
            "carried_root_evidence_mismatch",
        )
        require(
            deterministic_child_client_order_id(CARRIED_ROOT_CLIENT_ORDER_ID)
            == CARRIED_CHILD_CLIENT_ORDER_ID,
            "carried_child_not_deterministic",
        )
        child_status = str(carried_child.get("status") or "").upper()
        stealth_status = str(carried_stealth.get("status") or "").upper()
        carried_nonterminal = child_status not in TERMINAL_STATUSES
        require(
            carried_child.get("client_order_id")
            == CARRIED_CHILD_CLIENT_ORDER_ID
            and str(carried_child.get("parent_order_id") or "")
            == CARRIED_ROOT_CLIENT_ORDER_ID
            and carried_child.get("product_id") == PRODUCT_ID
            and str(carried_child.get("side") or "").upper() == "SELL"
            and carried_child.get("ownership_provenance")
            == "ADMIN_FILL_FOLLOW_UP"
            and carried_child.get("retail_portfolio_id")
            == carried_root.get("retail_portfolio_id")
            and carried_child.get("correlation_id")
            == carried_root.get("correlation_id")
            and carried_child.get("audit_id") == carried_root.get("audit_id"),
            "carried_child_tracking_evidence_mismatch",
        )
        require(
            Decimal(str(carried_child.get("size") or "0"))
            == CARRIED_ROOT_FILLED_SIZE,
            "carried_child_size_mismatch",
        )
        carried_anchor = object_record(
            carried_stealth.get("anchor_repricing_state_json")
        )
        carried_revealed = list_value(carried_stealth.get("revealed_orders"))
        carried_total = Decimal(str(carried_stealth.get("total_size") or "0"))
        carried_executed = Decimal(
            str(carried_stealth.get("executed_size") or "0")
        )
        require(
            carried_stealth.get("stealth_order_id")
            == CARRIED_CHILD_CLIENT_ORDER_ID
            and str(carried_stealth.get("parent_order_id") or "")
            == CARRIED_ROOT_CLIENT_ORDER_ID
            and carried_stealth.get("product_id") == PRODUCT_ID
            and str(carried_stealth.get("side") or "").upper() == "SELL"
            and carried_total == CARRIED_ROOT_FILLED_SIZE
            and carried_executed == 0,
            "carried_stealth_identity_mismatch",
        )
        if carried_nonterminal:
            require(
                child_status in {"PENDING", "HIDDEN", "TRIGGERED"}
                and stealth_status in {"PENDING", "HIDDEN", "TRIGGERED"}
                and not carried_child.get("exchange_order_id")
                and carried_total
                == Decimal(str(carried_stealth.get("remaining_size") or "0"))
                and Decimal(str(carried_stealth.get("revealed_size") or "0"))
                == 0
                and not carried_revealed
                and carried_stealth.get("last_placement_at") is None
                and not carried_anchor.get("active_placement_client_order_id")
                and not carried_anchor.get("active_exchange_order_id")
                and not carried_anchor.get(
                    "controlled_admin_first_child_reveal_preparation"
                ),
                "carried_child_not_wholly_unsubmitted",
            )
            # Condition timestamps may be set by bridge evaluation before the
            # controlled route atomically clears them. They are not placement
            # evidence and must not broaden authority.
        else:
            require(
                child_status in {"CANCELLED", "CANCELED"}
                and stealth_status in {"CANCELLED", "CANCELED"}
                and carried_executed == 0,
                "carried_child_not_zero_fill_cancelled",
            )
        require(
            not require_carried_hidden or carried_nonterminal,
            "carried_child_not_available_for_first_successor_attempt",
        )
        carried_scope = {
            "root_client_order_id": CARRIED_ROOT_CLIENT_ORDER_ID,
            "child_client_order_id": CARRIED_CHILD_CLIENT_ORDER_ID,
            "root_status": "FILLED",
            "child_parent_status": child_status,
            "child_stealth_status": stealth_status,
            "child_wholly_unsubmitted": carried_nonterminal,
            "condition_timestamps_do_not_authorize_placement": True,
            "root_placement_authorized": False,
        }
    expected_nonterminal = [HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID]
    if carried_nonterminal:
        expected_nonterminal.append(CARRIED_CHILD_CLIENT_ORDER_ID)
    expected_nonterminal.sort()
    require(
        nonterminal_parents == expected_nonterminal,
        f"unrelated_local_nonterminal_parent_present:{nonterminal_parents}",
    )
    require(
        nonterminal_stealth == expected_nonterminal,
        f"unrelated_local_nonterminal_stealth_present:{nonterminal_stealth}",
    )
    return {
        "historical_root_client_order_id": (
            HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID
        ),
        "historical_child_client_order_id": (
            HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID
        ),
        "historical_root_status": "FILLED",
        "historical_child_parent_status": "PENDING",
        "historical_child_stealth_status": "HIDDEN",
        "historical_child_exchange_order_id": None,
        "historical_child_revealed_order_count": 0,
        "historical_child_active_placement": False,
        "exception_is_read_only": True,
        "planned_ids_disjoint": True,
        "carried_chain": carried_scope,
    }


def validate_runner_commit_topology(
    *,
    production_commit: str,
    head_commit: str,
    head_parents: Sequence[str],
    changed_paths: Sequence[str],
    runner_path: str,
    committed_runner_sha256: str,
    working_runner_sha256: str,
) -> dict[str, Any]:
    """Require one runner-only commit directly atop the production tree."""

    require(
        len(production_commit) == 40
        and all(
            character in "0123456789abcdef"
            for character in production_commit
        ),
        "backend_production_commit_not_patched",
    )
    require(
        len(head_commit) == 40
        and all(character in "0123456789abcdef" for character in head_commit),
        "runner_head_commit_invalid",
    )
    require(
        head_commit != production_commit,
        "runner_commit_missing_above_production_commit",
    )
    require(
        list(head_parents) == [production_commit],
        "runner_commit_not_directly_above_production_commit",
    )
    require(
        list(changed_paths) == [runner_path],
        "runner_commit_contains_non_runner_paths",
    )
    require(
        len(committed_runner_sha256) == 64
        and committed_runner_sha256 == working_runner_sha256,
        "committed_runner_bytes_mismatch",
    )
    return {
        "production_commit": production_commit,
        "runner_commit": head_commit,
        "runner_commit_parent": production_commit,
        "runner_path": runner_path,
        "runner_sha256": working_runner_sha256,
        "runner_only_commit_proven": True,
    }


def require_clean_commit() -> dict[str, Any]:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    parent_record = subprocess.check_output(
        ["git", "rev-list", "--parents", "-n", "1", head],
        cwd=ROOT,
        text=True,
    ).strip().split()
    require(
        bool(parent_record) and parent_record[0] == head,
        "runner_commit_parent_readback_mismatch",
    )
    runner_relative_path = (
        Path(__file__).resolve().relative_to(ROOT).as_posix()
    )
    changed_paths = subprocess.check_output(
        [
            "git",
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            head,
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    committed_runner_bytes = subprocess.check_output(
        ["git", "show", f"{head}:{runner_relative_path}"],
        cwd=ROOT,
    )
    topology = validate_runner_commit_topology(
        production_commit=EXPECTED_COMMIT,
        head_commit=head,
        head_parents=parent_record[1:],
        changed_paths=changed_paths,
        runner_path=runner_relative_path,
        committed_runner_sha256=hashlib.sha256(
            committed_runner_bytes
        ).hexdigest(),
        working_runner_sha256=runner_sha256(),
    )
    production_drift = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            f"{EXPECTED_COMMIT}..{head}",
            "--",
            ".",
            ":(exclude)tools/run_controlled_admin_spot_root_child_batch.py",
        ],
        cwd=ROOT,
        check=False,
    )
    require(
        production_drift.returncode == 0,
        "backend_production_tree_changed_after_audited_commit",
    )
    divergence = subprocess.check_output(
        ["git", "rev-list", "--left-right", "--count", "origin/main...main"],
        cwd=ROOT,
        text=True,
    ).strip()
    require(divergence == "0\t0", f"backend_origin_divergence:{divergence}")
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip()
    require(not status, "backend_worktree_not_clean")
    return topology


def deterministic_batch_id(approval_id: str, expected_runner_hash: str) -> str:
    """Derive one stable batch identity from its immutable authority."""

    require(bool(approval_id), "batch_approval_id_missing")
    require(len(expected_runner_hash) == 64, "batch_runner_hash_invalid")
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "coinbase://controlled-admin-spot-root-child-batch/"
                f"{EXPECTED_COMMIT}/{expected_runner_hash}/{approval_id}"
            ),
        )
    )


def deterministic_root_client_order_id(batch_id: str, slot: int) -> str:
    require(1 <= slot <= BATCH_SIZE, "batch_root_slot_out_of_range")
    return str(
        uuid5(
            NAMESPACE_URL,
            f"coinbase://controlled-admin-spot-root-child/{batch_id}/root/{slot}",
        )
    )


def deterministic_child_client_order_id(root_client_order_id: str) -> str:
    """Match the production filled-follow-up identity derivation exactly."""

    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "coinbase://filled-follow-up/"
                f"{root_client_order_id}/{root_client_order_id}"
            ),
        )
    )


def deterministic_proof_approval_id(
    batch_id: str,
    *,
    slot: int,
    purpose: str,
) -> str:
    require(
        purpose in {"root_place", "root_cancel", "child_reveal", "child_cancel"},
        "batch_proof_approval_purpose_invalid",
    )
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "coinbase://controlled-admin-spot-root-child/"
                f"{batch_id}/slot/{slot}/approval/{purpose}"
            ),
        )
    )


def build_root_order(
    preflight: Mapping[str, Any],
    *,
    batch_id: str,
    slot: int,
) -> tuple[dict[str, Any], Decimal]:
    bid = Decimal(str(preflight["best_bid"]))
    ask = Decimal(str(preflight["best_ask"]))
    product = object_record(preflight["product"])
    price_increment = Decimal(str(product["price_increment"]))
    base_increment = Decimal(str(product["base_increment"]))
    base_min_size = Decimal(str(product["base_min_size"]))
    quote_min_size = Decimal(str(product["quote_min_size"]))
    price_ticks = ((ask * PLANNED_ASK_RATIO) / price_increment).to_integral_value(
        rounding=ROUND_CEILING
    )
    price = price_ticks * price_increment
    size_ticks = (TARGET_NOTIONAL / price / base_increment).to_integral_value(
        rounding=ROUND_CEILING
    )
    size = max(base_min_size, size_ticks * base_increment)
    notional = price * size
    require(ask >= bid > 0, "exact_market_invalid")
    require(price >= ask, "intentional_fill_limit_not_marketable")
    require(price <= ask * MAX_ASK_RATIO, "intentional_fill_slippage_band_failed")
    require(price > bid * Decimal("0.5"), "intentional_fill_override_not_required")
    require(price % price_increment == 0, "price_increment_alignment_failed")
    require(size % base_increment == 0, "base_increment_alignment_failed")
    require(notional >= quote_min_size, "quote_min_size_failed")
    require(notional < ROOT_SUBMITTED_CAP, "submitted_notional_cap_failed")
    return (
        {
            "client_order_id": deterministic_root_client_order_id(batch_id, slot),
            "product_id": PRODUCT_ID,
            "side": "BUY",
            "order_type": "LIMIT",
            "base_size": decimal_text(size),
            "limit_price": decimal_text(price),
            "post_only": False,
            "time_in_force": "FILL_OR_KILL",
            "manual_live_acknowledgement": True,
        },
        notional,
    )


def validate_prepared_root_order(
    preflight: Mapping[str, Any],
    order_body: Mapping[str, Any],
    *,
    batch_id: str,
    slot: int,
) -> Decimal:
    """Validate one immutable root tuple against fresh exchange authority."""

    expected_fields = {
        "client_order_id",
        "product_id",
        "side",
        "order_type",
        "base_size",
        "limit_price",
        "post_only",
        "time_in_force",
        "manual_live_acknowledgement",
    }
    require(set(order_body) == expected_fields, "prepared_order_fields_mismatch")
    client_order_id = str(order_body.get("client_order_id") or "")
    try:
        parsed_client_order_id = UUID(client_order_id)
    except ValueError as exc:
        raise ProofFailure("prepared_client_order_id_invalid") from exc
    require(
        parsed_client_order_id.version == 5
        and str(parsed_client_order_id) == client_order_id,
        "prepared_client_order_id_not_canonical_uuid5",
    )
    require(
        client_order_id == deterministic_root_client_order_id(batch_id, slot),
        "prepared_root_client_order_id_not_deterministic",
    )
    require(order_body.get("product_id") == PRODUCT_ID, "prepared_product_mismatch")
    require(order_body.get("side") == "BUY", "prepared_side_mismatch")
    require(order_body.get("order_type") == "LIMIT", "prepared_order_type_mismatch")
    require(order_body.get("post_only") is False, "prepared_post_only_must_be_false")
    require(
        order_body.get("time_in_force") == "FILL_OR_KILL",
        "prepared_time_in_force_mismatch",
    )
    require(
        order_body.get("manual_live_acknowledgement") is True,
        "prepared_manual_acknowledgement_missing",
    )

    product = object_record(preflight.get("product"))
    price_increment = Decimal(str(product.get("price_increment") or "0"))
    base_increment = Decimal(str(product.get("base_increment") or "0"))
    base_min_size = Decimal(str(product.get("base_min_size") or "0"))
    quote_min_size = Decimal(str(product.get("quote_min_size") or "0"))
    bid = Decimal(str(preflight.get("best_bid") or "0"))
    ask = Decimal(str(preflight.get("best_ask") or "0"))
    price = Decimal(str(order_body.get("limit_price") or "0"))
    size = Decimal(str(order_body.get("base_size") or "0"))
    for value, blocker in (
        (price_increment, "prepared_price_increment_invalid"),
        (base_increment, "prepared_base_increment_invalid"),
        (base_min_size, "prepared_base_min_size_invalid"),
        (quote_min_size, "prepared_quote_min_size_invalid"),
        (bid, "prepared_reference_bid_invalid"),
        (ask, "prepared_reference_ask_invalid"),
        (price, "prepared_limit_price_invalid"),
        (size, "prepared_base_size_invalid"),
    ):
        require(value.is_finite() and value > 0, blocker)
    require(
        str(order_body["limit_price"]) == decimal_text(price),
        "prepared_limit_price_not_canonical",
    )
    require(
        str(order_body["base_size"]) == decimal_text(size),
        "prepared_base_size_not_canonical",
    )
    require(price % price_increment == 0, "prepared_price_increment_mismatch")
    require(size % base_increment == 0, "prepared_base_increment_mismatch")
    require(size >= base_min_size, "prepared_base_min_size_failed")
    require(ask >= bid, "prepared_exact_market_crossed")
    require(price >= ask, "prepared_limit_not_marketable")
    require(price <= ask * MAX_ASK_RATIO, "prepared_limit_exceeds_slippage_band")
    require(price > bid * Decimal("0.5"), "prepared_intentional_override_not_required")
    notional = price * size
    require(notional >= quote_min_size, "prepared_quote_min_size_failed")
    require(notional < ROOT_SUBMITTED_CAP, "prepared_submitted_notional_cap_failed")
    wallets = object_record(preflight.get("wallets"))
    wallet_available = Decimal(str(wallets.get("USDC") or "0"))
    require(
        wallet_available.is_finite() and wallet_available >= notional,
        "prepared_usdc_wallet_insufficient",
    )
    return notional


def plan_hash(plan: Mapping[str, Any]) -> str:
    """Return the SHA-256 binding for every immutable plan field."""

    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_plan_unexpired(
    plan: Mapping[str, Any],
    *,
    blocker: str,
    now: datetime | None = None,
) -> None:
    try:
        expires_at = datetime.fromisoformat(
            str(plan.get("expires_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ProofFailure(f"{blocker}:timestamp_invalid") from exc
    require(
        expires_at.tzinfo is not None,
        f"{blocker}:timestamp_timezone_missing",
    )
    require(
        (now or datetime.now(timezone.utc)) < expires_at,
        blocker,
    )


def runner_sha256() -> str:
    """Return the exact runner content hash bound into every plan."""

    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def approved_exact_root_tuple(
    plan: Mapping[str, Any],
    root_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one complete approved root tuple for SDK-boundary validation."""

    order = object_record(root_plan.get("order"))
    approvals = object_record(root_plan.get("proof_approval_ids"))
    return {
        "approval_id": str(approvals.get("root_place") or ""),
        "batch_id": str(plan.get("batch_id") or ""),
        "batch_slot": int(root_plan.get("slot") or 0),
        "operator_intent": str(plan.get("operator_intent") or ""),
        "portfolio_id": str(plan.get("portfolio_id") or ""),
        "portfolio_label": str(plan.get("portfolio_label") or ""),
        "client_order_id": str(order.get("client_order_id") or ""),
        "product_id": str(plan.get("product_id") or ""),
        "side": str(plan.get("side") or ""),
        "order_type": str(plan.get("order_type") or ""),
        "time_in_force": str(plan.get("time_in_force") or ""),
        "base_size": str(order.get("base_size") or ""),
        "limit_price": str(order.get("limit_price") or ""),
        "post_only": order.get("post_only"),
        "size_in_quote": False,
        "quote_size": None,
    }


def build_controlled_live_plan(preflight: Mapping[str, Any]) -> dict[str, Any]:
    """Build ten exact root tuples plus a deterministic first-child policy."""

    approval_id = f"controlled-root-child-batch-{uuid4()}"
    exact_runner_hash = runner_sha256()
    batch_id = deterministic_batch_id(approval_id, exact_runner_hash)
    root_plans: list[dict[str, Any]] = []
    planned_total = Decimal("0")
    planned_child_total = Decimal("0")
    planned_bid = Decimal(str(preflight["best_bid"]))
    price_increment = Decimal(
        str(object_record(preflight["product"])["price_increment"])
    )
    planned_child_price = (
        (planned_bid * CHILD_MINIMUM_BID_RATIO) / price_increment
    ).to_integral_value(rounding=ROUND_CEILING) * price_increment
    for slot in range(1, BATCH_SIZE + 1):
        order_body, planned_notional = build_root_order(
            preflight,
            batch_id=batch_id,
            slot=slot,
        )
        validated_notional = validate_prepared_root_order(
            preflight,
            order_body,
            batch_id=batch_id,
            slot=slot,
        )
        require(validated_notional == planned_notional, "prepared_notional_mismatch")
        root_client_order_id = str(order_body["client_order_id"])
        root_plans.append(
            {
                "slot": slot,
                "root_client_order_id": root_client_order_id,
                "child_client_order_id": deterministic_child_client_order_id(
                    root_client_order_id
                ),
                "planned_notional_usdc": decimal_text(planned_notional),
                "order": dict(order_body),
                "proof_approval_ids": {
                    purpose: deterministic_proof_approval_id(
                        batch_id,
                        slot=slot,
                        purpose=purpose,
                    )
                    for purpose in (
                        "root_place",
                        "root_cancel",
                        "child_reveal",
                        "child_cancel",
                    )
                },
            }
        )
        planned_total += planned_notional
        planned_child_notional = (
            Decimal(str(order_body["base_size"])) * planned_child_price
        )
        require(
            planned_child_notional < CHILD_SUBMITTED_CAP,
            "planned_child_reference_notional_not_strictly_below_cap",
        )
        planned_child_total += planned_child_notional
    wallet_available = Decimal(
        str(object_record(preflight.get("wallets")).get("USDC") or "0")
    )
    require(
        wallet_available.is_finite() and wallet_available >= planned_total,
        "batch_planned_usdc_wallet_insufficient",
    )
    planned_batch_total = planned_total + planned_child_total
    require(
        planned_batch_total < BATCH_TOTAL_REFERENCE_CAP_USDC,
        "planned_batch_root_child_reference_cap_exceeded",
    )
    created_at = datetime.now(timezone.utc)
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "approval_id": approval_id,
        "batch_id": batch_id,
        "batch_size": BATCH_SIZE,
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + PLAN_TTL).isoformat(),
        "backend_commit": EXPECTED_COMMIT,
        "runner_sha256": exact_runner_hash,
        "portfolio_id": str(preflight.get("portfolio_id") or ""),
        "portfolio_label": PROFILE_LABEL,
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "operator_intent": INTENTIONAL_FILL_OPERATOR_INTENT,
        "order_type": "LIMIT",
        "time_in_force": "FILL_OR_KILL",
        "post_only": False,
        "best_bid_at_plan": decimal_text(Decimal(str(preflight["best_bid"]))),
        "best_ask_at_plan": decimal_text(Decimal(str(preflight["best_ask"]))),
        "market_source_at_plan": str(
            object_record(preflight.get("market")).get("source") or ""
        ),
        "market_observed_at_plan": str(
            object_record(preflight.get("market")).get("observed_at") or ""
        ),
        "maximum_ask_ratio": decimal_text(MAX_ASK_RATIO),
        "planned_ask_ratio": decimal_text(PLANNED_ASK_RATIO),
        "planned_limit_to_ask_ratio": decimal_text(
            Decimal(str(order_body["limit_price"]))
            / Decimal(str(preflight["best_ask"]))
        ),
        "root_submitted_cap_usdc": decimal_text(ROOT_SUBMITTED_CAP),
        "child_submitted_cap_usdc": decimal_text(CHILD_SUBMITTED_CAP),
        "child_minimum_bid_ratio": decimal_text(CHILD_MINIMUM_BID_RATIO),
        "batch_total_reference_cap_usdc": decimal_text(
            BATCH_TOTAL_REFERENCE_CAP_USDC
        ),
        "planned_total_root_notional_usdc": decimal_text(planned_total),
        "planned_total_child_reference_notional_usdc": decimal_text(
            planned_child_total
        ),
        "planned_total_root_child_reference_notional_usdc": decimal_text(
            planned_batch_total
        ),
        "roots": root_plans,
    }
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def build_successor_live_plan(
    preflight: Mapping[str, Any],
    *,
    predecessor_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Build child-1 plus nine fresh root/child pairs under new authority."""

    require(
        dict(predecessor_binding) == offline_predecessor_binding_fixture(),
        "successor_predecessor_binding_mismatch",
    )
    approval_id = f"controlled-root-child-successor-{uuid4()}"
    exact_runner_hash = runner_sha256()
    batch_id = deterministic_batch_id(approval_id, exact_runner_hash)
    planned_bid = Decimal(str(preflight["best_bid"]))
    price_increment = Decimal(
        str(object_record(preflight["product"])["price_increment"])
    )
    planned_child_price = (
        (planned_bid * CHILD_MINIMUM_BID_RATIO) / price_increment
    ).to_integral_value(rounding=ROUND_CEILING) * price_increment
    roots: list[dict[str, Any]] = []
    carried_root = {
        "slot": 1,
        "root_placement_authorized": False,
        "root_client_order_id": CARRIED_ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": CARRIED_CHILD_CLIENT_ORDER_ID,
        "planned_notional_usdc": decimal_text(CARRIED_ROOT_PLANNED_NOTIONAL),
        "order": _carried_root_order(),
        "proof_approval_ids": {
            purpose: deterministic_proof_approval_id(
                batch_id,
                slot=1,
                purpose=purpose,
            )
            for purpose in ("child_reveal", "child_cancel")
        },
    }
    roots.append(carried_root)
    planned_new_root_total = Decimal("0")
    for slot in range(2, BATCH_SIZE + 1):
        order_body, planned_notional = build_root_order(
            preflight,
            batch_id=batch_id,
            slot=slot,
        )
        require(
            validate_prepared_root_order(
                preflight,
                order_body,
                batch_id=batch_id,
                slot=slot,
            )
            == planned_notional,
            "successor_prepared_notional_mismatch",
        )
        root_id = str(order_body["client_order_id"])
        roots.append(
            {
                "slot": slot,
                "root_placement_authorized": True,
                "root_client_order_id": root_id,
                "child_client_order_id": deterministic_child_client_order_id(
                    root_id
                ),
                "planned_notional_usdc": decimal_text(planned_notional),
                "order": dict(order_body),
                "proof_approval_ids": {
                    purpose: deterministic_proof_approval_id(
                        batch_id,
                        slot=slot,
                        purpose=purpose,
                    )
                    for purpose in (
                        "root_place",
                        "root_cancel",
                        "child_reveal",
                        "child_cancel",
                    )
                },
            }
        )
        planned_new_root_total += planned_notional
    fresh_ids = {
        str(value)
        for root in roots[1:]
        for value in (
            root["root_client_order_id"],
            root["child_client_order_id"],
        )
    }
    predecessor_ids = set(PREDECESSOR_PLANNED_ROOT_CLIENT_ORDER_IDS) | set(
        PREDECESSOR_PLANNED_CHILD_CLIENT_ORDER_IDS
    )
    historical_ids = {
        HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID,
        HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID,
        CARRIED_ROOT_CLIENT_ORDER_ID,
        CARRIED_CHILD_CLIENT_ORDER_ID,
    }
    require(
        not fresh_ids & (predecessor_ids | historical_ids),
        "successor_fresh_ids_overlap_predecessor_or_historical_chain",
    )
    planned_child_total = Decimal("0")
    for root in roots:
        child_reference_notional = (
            Decimal(str(object_record(root["order"])["base_size"]))
            * planned_child_price
        )
        require(
            child_reference_notional < CHILD_SUBMITTED_CAP,
            "successor_child_reference_notional_not_strictly_below_cap",
        )
        planned_child_total += child_reference_notional
    wallet_available = Decimal(
        str(object_record(preflight.get("wallets")).get("USDC") or "0")
    )
    require(
        wallet_available.is_finite()
        and wallet_available >= planned_new_root_total,
        "successor_new_root_wallet_insufficient",
    )
    planned_all_root_total = (
        CARRIED_ROOT_PLANNED_NOTIONAL + planned_new_root_total
    )
    planned_batch_total = planned_all_root_total + planned_child_total
    require(
        planned_batch_total < BATCH_TOTAL_REFERENCE_CAP_USDC,
        "successor_root_child_reference_cap_exceeded",
    )
    created_at = datetime.now(timezone.utc)
    first_new_order = object_record(roots[1]["order"])
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "continuation_kind": "consumed_root_1_child_1_first_successor",
        "approval_id": approval_id,
        "batch_id": batch_id,
        "batch_size": BATCH_SIZE,
        "remaining_attempt_count": SUCCESSOR_ATTEMPT_COUNT,
        "new_root_order_maximum": SUCCESSOR_ROOT_ORDER_MAXIMUM,
        "child_order_maximum": SUCCESSOR_CHILD_ORDER_MAXIMUM,
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + PLAN_TTL).isoformat(),
        "backend_commit": EXPECTED_COMMIT,
        "runner_sha256": exact_runner_hash,
        "predecessor_binding": dict(predecessor_binding),
        "portfolio_id": str(preflight.get("portfolio_id") or ""),
        "portfolio_label": PROFILE_LABEL,
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "operator_intent": INTENTIONAL_FILL_OPERATOR_INTENT,
        "order_type": "LIMIT",
        "time_in_force": "FILL_OR_KILL",
        "post_only": False,
        "best_bid_at_plan": decimal_text(planned_bid),
        "best_ask_at_plan": decimal_text(
            Decimal(str(preflight["best_ask"]))
        ),
        "market_source_at_plan": str(
            object_record(preflight.get("market")).get("source") or ""
        ),
        "market_observed_at_plan": str(
            object_record(preflight.get("market")).get("observed_at") or ""
        ),
        "maximum_ask_ratio": decimal_text(MAX_ASK_RATIO),
        "planned_ask_ratio": decimal_text(PLANNED_ASK_RATIO),
        "planned_limit_to_ask_ratio": decimal_text(
            Decimal(str(first_new_order["limit_price"]))
            / Decimal(str(preflight["best_ask"]))
        ),
        "root_submitted_cap_usdc": decimal_text(ROOT_SUBMITTED_CAP),
        "child_submitted_cap_usdc": decimal_text(CHILD_SUBMITTED_CAP),
        "child_minimum_bid_ratio": decimal_text(CHILD_MINIMUM_BID_RATIO),
        "batch_total_reference_cap_usdc": decimal_text(
            BATCH_TOTAL_REFERENCE_CAP_USDC
        ),
        "inherited_root_reference_notional_usdc": decimal_text(
            CARRIED_ROOT_PLANNED_NOTIONAL
        ),
        "planned_new_root_notional_usdc": decimal_text(
            planned_new_root_total
        ),
        "planned_total_root_notional_usdc": decimal_text(
            planned_all_root_total
        ),
        "planned_total_child_reference_notional_usdc": decimal_text(
            planned_child_total
        ),
        "planned_total_root_child_reference_notional_usdc": decimal_text(
            planned_batch_total
        ),
        "roots": roots,
    }
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def approved_exact_successor_root_tuple(
    plan: Mapping[str, Any],
    root_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a root tuple only for fresh successor slots 2 through 10."""

    slot = int(root_plan.get("slot") or 0)
    require(
        slot >= 2 and root_plan.get("root_placement_authorized") is True,
        "successor_carried_root_placement_denied",
    )
    return approved_exact_root_tuple(plan, root_plan)


def validate_successor_live_plan(
    plan: Mapping[str, Any],
    *,
    expected_hash: str,
    preflight: Mapping[str, Any],
    predecessor_binding: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Decimal]:
    """Validate the 19-placement continuation and cumulative 10/10 cap."""

    expected_fields = {
        "schema_version",
        "continuation_kind",
        "approval_id",
        "batch_id",
        "batch_size",
        "remaining_attempt_count",
        "new_root_order_maximum",
        "child_order_maximum",
        "created_at",
        "expires_at",
        "backend_commit",
        "runner_sha256",
        "predecessor_binding",
        "portfolio_id",
        "portfolio_label",
        "product_id",
        "side",
        "operator_intent",
        "order_type",
        "time_in_force",
        "post_only",
        "best_bid_at_plan",
        "best_ask_at_plan",
        "market_source_at_plan",
        "market_observed_at_plan",
        "maximum_ask_ratio",
        "planned_ask_ratio",
        "planned_limit_to_ask_ratio",
        "root_submitted_cap_usdc",
        "child_submitted_cap_usdc",
        "child_minimum_bid_ratio",
        "batch_total_reference_cap_usdc",
        "inherited_root_reference_notional_usdc",
        "planned_new_root_notional_usdc",
        "planned_total_root_notional_usdc",
        "planned_total_child_reference_notional_usdc",
        "planned_total_root_child_reference_notional_usdc",
        "roots",
        "plan_sha256",
    }
    require(set(plan) == expected_fields, "successor_plan_fields_mismatch")
    require(
        dict(predecessor_binding) == offline_predecessor_binding_fixture()
        and object_record(plan.get("predecessor_binding"))
        == dict(predecessor_binding),
        "successor_plan_predecessor_binding_mismatch",
    )
    supplied_hash = str(plan.get("plan_sha256") or "")
    computed_hash = plan_hash(plan)
    require(
        len(expected_hash) == 64
        and secrets.compare_digest(supplied_hash, computed_hash)
        and secrets.compare_digest(expected_hash, computed_hash),
        "successor_plan_hash_mismatch",
    )
    require(
        plan.get("schema_version") == PLAN_SCHEMA_VERSION
        and plan.get("continuation_kind")
        == "consumed_root_1_child_1_first_successor"
        and plan.get("backend_commit") == EXPECTED_COMMIT
        and plan.get("runner_sha256") == runner_sha256(),
        "successor_plan_authority_mismatch",
    )
    approval_id = str(plan.get("approval_id") or "")
    batch_id = str(plan.get("batch_id") or "")
    require(bool(approval_id), "successor_plan_approval_missing")
    require(
        batch_id == deterministic_batch_id(approval_id, runner_sha256()),
        "successor_plan_batch_id_mismatch",
    )
    require(
        plan.get("batch_size") == BATCH_SIZE
        and plan.get("remaining_attempt_count") == SUCCESSOR_ATTEMPT_COUNT
        and plan.get("new_root_order_maximum")
        == SUCCESSOR_ROOT_ORDER_MAXIMUM
        and plan.get("child_order_maximum")
        == SUCCESSOR_CHILD_ORDER_MAXIMUM,
        "successor_plan_count_mismatch",
    )
    require(
        plan.get("portfolio_id") == preflight.get("portfolio_id")
        == predecessor_binding.get("portfolio_id")
        and plan.get("portfolio_label") == PROFILE_LABEL
        and plan.get("product_id") == PRODUCT_ID
        and plan.get("side") == "BUY"
        and plan.get("operator_intent") == INTENTIONAL_FILL_OPERATOR_INTENT
        and plan.get("order_type") == "LIMIT"
        and plan.get("time_in_force") == "FILL_OR_KILL"
        and plan.get("post_only") is False,
        "successor_plan_scope_mismatch",
    )
    require(
        plan.get("root_submitted_cap_usdc")
        == decimal_text(ROOT_SUBMITTED_CAP)
        and plan.get("child_submitted_cap_usdc")
        == decimal_text(CHILD_SUBMITTED_CAP)
        and plan.get("child_minimum_bid_ratio")
        == decimal_text(CHILD_MINIMUM_BID_RATIO)
        and plan.get("batch_total_reference_cap_usdc")
        == decimal_text(BATCH_TOTAL_REFERENCE_CAP_USDC),
        "successor_plan_cap_policy_mismatch",
    )
    try:
        created_at = datetime.fromisoformat(str(plan.get("created_at") or ""))
        expires_at = datetime.fromisoformat(str(plan.get("expires_at") or ""))
    except ValueError as exc:
        raise ProofFailure("successor_plan_timestamp_invalid") from exc
    require(
        created_at.tzinfo is not None
        and expires_at.tzinfo is not None
        and expires_at - created_at == PLAN_TTL
        and datetime.now(timezone.utc) < expires_at,
        "successor_plan_expired_or_timestamp_mismatch",
    )
    planned_bid = Decimal(str(plan.get("best_bid_at_plan") or "0"))
    planned_ask = Decimal(str(plan.get("best_ask_at_plan") or "0"))
    require(
        planned_bid.is_finite()
        and planned_bid > 0
        and planned_ask.is_finite()
        and planned_ask >= planned_bid,
        "successor_plan_market_invalid",
    )
    roots = [object_record(item) for item in list_value(plan.get("roots"))]
    require(
        len(roots) == BATCH_SIZE
        and [root.get("slot") for root in roots]
        == list(range(1, BATCH_SIZE + 1)),
        "successor_plan_root_slots_mismatch",
    )
    root_fields = {
        "slot",
        "root_placement_authorized",
        "root_client_order_id",
        "child_client_order_id",
        "planned_notional_usdc",
        "order",
        "proof_approval_ids",
    }
    carried = roots[0]
    require(set(carried) == root_fields, "successor_carried_root_fields_mismatch")
    require(
        carried.get("root_placement_authorized") is False
        and carried.get("root_client_order_id")
        == CARRIED_ROOT_CLIENT_ORDER_ID
        and carried.get("child_client_order_id")
        == CARRIED_CHILD_CLIENT_ORDER_ID
        and object_record(carried.get("order")) == _carried_root_order()
        and carried.get("planned_notional_usdc")
        == decimal_text(CARRIED_ROOT_PLANNED_NOTIONAL),
        "successor_carried_root_mismatch",
    )
    carried_approvals = object_record(carried.get("proof_approval_ids"))
    require(
        set(carried_approvals) == {"child_reveal", "child_cancel"},
        "successor_carried_root_proof_scope_mismatch",
    )
    for purpose, approval in carried_approvals.items():
        require(
            approval
            == deterministic_proof_approval_id(
                batch_id,
                slot=1,
                purpose=purpose,
            ),
            f"successor_carried_child_approval_mismatch:{purpose}",
        )
    planned_new_root_total = Decimal("0")
    planned_child_total = Decimal("0")
    price_increment = Decimal(
        str(object_record(preflight.get("product")).get("price_increment") or "0")
    )
    planned_child_price = (
        (planned_bid * CHILD_MINIMUM_BID_RATIO) / price_increment
    ).to_integral_value(rounding=ROUND_CEILING) * price_increment
    root_ids: list[str] = [CARRIED_ROOT_CLIENT_ORDER_ID]
    child_ids: list[str] = [CARRIED_CHILD_CLIENT_ORDER_ID]
    for slot, root in enumerate(roots[1:], start=2):
        require(set(root) == root_fields, f"successor_root_fields_mismatch:{slot}")
        root_id = deterministic_root_client_order_id(batch_id, slot)
        child_id = deterministic_child_client_order_id(root_id)
        require(
            root.get("root_placement_authorized") is True
            and root.get("root_client_order_id") == root_id
            and root.get("child_client_order_id") == child_id,
            f"successor_root_identity_mismatch:{slot}",
        )
        order = object_record(root.get("order"))
        notional = validate_prepared_root_order(
            preflight,
            order,
            batch_id=batch_id,
            slot=slot,
        )
        require(
            root.get("planned_notional_usdc") == decimal_text(notional),
            f"successor_root_notional_mismatch:{slot}",
        )
        approvals = object_record(root.get("proof_approval_ids"))
        require(
            set(approvals)
            == {"root_place", "root_cancel", "child_reveal", "child_cancel"},
            f"successor_root_proof_scope_mismatch:{slot}",
        )
        for purpose, approval in approvals.items():
            require(
                approval
                == deterministic_proof_approval_id(
                    batch_id,
                    slot=slot,
                    purpose=purpose,
                ),
                f"successor_proof_approval_mismatch:{slot}:{purpose}",
            )
        planned_new_root_total += notional
        root_ids.append(root_id)
        child_ids.append(child_id)
    predecessor_ids = set(PREDECESSOR_PLANNED_ROOT_CLIENT_ORDER_IDS) | set(
        PREDECESSOR_PLANNED_CHILD_CLIENT_ORDER_IDS
    )
    fresh_ids = set(root_ids[1:]) | set(child_ids[1:])
    require(
        len(set(root_ids)) == BATCH_SIZE
        and len(set(child_ids)) == BATCH_SIZE
        and not set(root_ids) & set(child_ids)
        and not fresh_ids & predecessor_ids
        and not fresh_ids
        & {
            HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID,
            HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID,
        },
        "successor_plan_id_disjointness_failed",
    )
    for root in roots:
        planned_child_notional = (
            Decimal(str(object_record(root.get("order")).get("base_size") or "0"))
            * planned_child_price
        )
        require(
            planned_child_notional < CHILD_SUBMITTED_CAP,
            "successor_plan_child_reference_cap_mismatch",
        )
        planned_child_total += planned_child_notional
    total_roots = CARRIED_ROOT_PLANNED_NOTIONAL + planned_new_root_total
    total_batch = total_roots + planned_child_total
    require(
        plan.get("inherited_root_reference_notional_usdc")
        == decimal_text(CARRIED_ROOT_PLANNED_NOTIONAL)
        and plan.get("planned_new_root_notional_usdc")
        == decimal_text(planned_new_root_total)
        and plan.get("planned_total_root_notional_usdc")
        == decimal_text(total_roots)
        and plan.get("planned_total_child_reference_notional_usdc")
        == decimal_text(planned_child_total)
        and plan.get("planned_total_root_child_reference_notional_usdc")
        == decimal_text(total_batch)
        and total_batch < BATCH_TOTAL_REFERENCE_CAP_USDC,
        "successor_plan_aggregate_cap_mismatch",
    )
    wallet_available = Decimal(
        str(object_record(preflight.get("wallets")).get("USDC") or "0")
    )
    require(
        wallet_available.is_finite()
        and wallet_available >= planned_new_root_total,
        "successor_plan_new_root_wallet_insufficient",
    )
    first_new_order = object_record(roots[1].get("order"))
    first_new_price = Decimal(str(first_new_order.get("limit_price") or "0"))
    recorded_ratio = Decimal(
        str(plan.get("planned_limit_to_ask_ratio") or "0")
    )
    require(
        first_new_price >= planned_ask
        and first_new_price <= planned_ask * MAX_ASK_RATIO
        and recorded_ratio == first_new_price / planned_ask
        and Decimal("1") <= recorded_ratio <= MAX_ASK_RATIO,
        "successor_plan_new_root_ask_binding_mismatch",
    )
    return roots, planned_new_root_total


def write_controlled_live_plan(path: Path, plan: Mapping[str, Any]) -> None:
    """Write one new owner-only plan without following an existing symlink."""

    require(path.is_absolute(), "controlled_live_plan_path_not_absolute")
    require(path.parent.is_dir(), "controlled_live_plan_parent_missing")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ProofFailure("controlled_live_plan_create_failed") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(plan), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_controlled_live_plan(path: Path) -> dict[str, Any]:
    """Read one bounded owner-only regular plan file without symlink traversal."""

    require(path.is_absolute(), "controlled_live_plan_path_not_absolute")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProofFailure("controlled_live_plan_open_failed") from exc
    try:
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode), "controlled_live_plan_not_regular")
        require(metadata.st_uid == os.getuid(), "controlled_live_plan_owner_mismatch")
        require(metadata.st_mode & 0o077 == 0, "controlled_live_plan_permissions_too_broad")
        require(
            0 < metadata.st_size <= 100_000,
            "controlled_batch_plan_size_invalid",
        )
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            payload = json.load(handle)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    require(isinstance(payload, dict), "controlled_live_plan_not_object")
    return dict(payload)


def validate_controlled_live_plan(
    plan: Mapping[str, Any],
    *,
    expected_hash: str,
    preflight: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Decimal]:
    """Bind the operator-confirmed hash and revalidate all ten root tuples."""

    expected_fields = {
        "schema_version",
        "approval_id",
        "batch_id",
        "batch_size",
        "created_at",
        "expires_at",
        "backend_commit",
        "runner_sha256",
        "portfolio_id",
        "portfolio_label",
        "product_id",
        "side",
        "operator_intent",
        "order_type",
        "time_in_force",
        "post_only",
        "best_bid_at_plan",
        "best_ask_at_plan",
        "market_source_at_plan",
        "market_observed_at_plan",
        "maximum_ask_ratio",
        "planned_ask_ratio",
        "planned_limit_to_ask_ratio",
        "root_submitted_cap_usdc",
        "child_submitted_cap_usdc",
        "child_minimum_bid_ratio",
        "batch_total_reference_cap_usdc",
        "planned_total_root_notional_usdc",
        "planned_total_child_reference_notional_usdc",
        "planned_total_root_child_reference_notional_usdc",
        "roots",
        "plan_sha256",
    }
    require(set(plan) == expected_fields, "controlled_batch_plan_fields_mismatch")
    supplied_hash = str(plan.get("plan_sha256") or "")
    require(
        len(expected_hash) == 64
        and all(character in "0123456789abcdef" for character in expected_hash),
        "controlled_batch_plan_confirmation_hash_invalid",
    )
    computed_hash = plan_hash(plan)
    require(
        secrets.compare_digest(supplied_hash, computed_hash),
        "controlled_batch_plan_stored_hash_mismatch",
    )
    require(
        secrets.compare_digest(expected_hash, computed_hash),
        "controlled_batch_plan_not_operator_confirmed",
    )
    require(
        plan.get("schema_version") == PLAN_SCHEMA_VERSION,
        "controlled_batch_plan_schema_mismatch",
    )
    require(
        plan.get("backend_commit") == EXPECTED_COMMIT,
        "controlled_batch_plan_commit_mismatch",
    )
    require(
        plan.get("runner_sha256") == runner_sha256(),
        "controlled_batch_plan_runner_sha256_mismatch",
    )
    approval_id = str(plan.get("approval_id") or "")
    batch_id = str(plan.get("batch_id") or "")
    require(bool(approval_id), "controlled_batch_plan_approval_id_missing")
    require(
        batch_id == deterministic_batch_id(approval_id, runner_sha256()),
        "controlled_batch_plan_batch_id_mismatch",
    )
    require(plan.get("batch_size") == BATCH_SIZE, "controlled_batch_size_mismatch")
    require(
        plan.get("portfolio_id") == preflight.get("portfolio_id"),
        "controlled_batch_plan_portfolio_mismatch",
    )
    require(
        plan.get("portfolio_label") == PROFILE_LABEL,
        "controlled_batch_plan_profile_mismatch",
    )
    require(plan.get("product_id") == PRODUCT_ID, "controlled_batch_plan_product_mismatch")
    require(plan.get("side") == "BUY", "controlled_batch_plan_side_mismatch")
    require(
        plan.get("operator_intent") == INTENTIONAL_FILL_OPERATOR_INTENT,
        "controlled_batch_plan_operator_intent_mismatch",
    )
    require(plan.get("order_type") == "LIMIT", "controlled_batch_plan_order_type_mismatch")
    require(
        plan.get("time_in_force") == "FILL_OR_KILL",
        "controlled_batch_plan_time_in_force_mismatch",
    )
    require(plan.get("post_only") is False, "controlled_batch_plan_post_only_mismatch")
    require(
        plan.get("root_submitted_cap_usdc") == decimal_text(ROOT_SUBMITTED_CAP),
        "controlled_batch_root_cap_mismatch",
    )
    require(
        plan.get("child_submitted_cap_usdc") == decimal_text(CHILD_SUBMITTED_CAP),
        "controlled_batch_child_cap_mismatch",
    )
    require(
        plan.get("child_minimum_bid_ratio")
        == decimal_text(CHILD_MINIMUM_BID_RATIO),
        "controlled_batch_child_bid_ratio_mismatch",
    )
    require(
        plan.get("batch_total_reference_cap_usdc")
        == decimal_text(BATCH_TOTAL_REFERENCE_CAP_USDC),
        "controlled_batch_total_reference_cap_mismatch",
    )
    require(
        plan.get("maximum_ask_ratio") == decimal_text(MAX_ASK_RATIO),
        "controlled_batch_plan_ask_ratio_mismatch",
    )
    require(
        plan.get("planned_ask_ratio") == decimal_text(PLANNED_ASK_RATIO),
        "controlled_batch_plan_planned_ask_ratio_mismatch",
    )
    require(
        plan.get("market_source_at_plan")
        == "coinbase_rest_get_best_bid_ask_exact_product",
        "controlled_batch_plan_market_source_mismatch",
    )
    require(
        bool(str(plan.get("market_observed_at_plan") or "").strip()),
        "controlled_batch_plan_market_observed_at_missing",
    )

    try:
        created_at = datetime.fromisoformat(str(plan.get("created_at") or ""))
        expires_at = datetime.fromisoformat(str(plan.get("expires_at") or ""))
    except ValueError as exc:
        raise ProofFailure("controlled_batch_plan_timestamp_invalid") from exc
    require(
        created_at.tzinfo is not None and expires_at.tzinfo is not None,
        "controlled_batch_plan_timestamp_timezone_missing",
    )
    now = datetime.now(timezone.utc)
    require(
        created_at <= now + timedelta(seconds=1),
        "controlled_batch_plan_created_in_future",
    )
    require(expires_at - created_at == PLAN_TTL, "controlled_batch_plan_ttl_mismatch")
    require(now < expires_at, "controlled_batch_plan_expired")

    planned_bid = Decimal(str(plan.get("best_bid_at_plan") or "0"))
    planned_ask = Decimal(str(plan.get("best_ask_at_plan") or "0"))
    require(planned_bid.is_finite() and planned_bid > 0, "controlled_batch_plan_bid_invalid")
    require(
        planned_ask.is_finite() and planned_ask >= planned_bid,
        "controlled_batch_plan_ask_invalid",
    )

    raw_roots = list_value(plan.get("roots"))
    require(len(raw_roots) == BATCH_SIZE, "controlled_batch_root_count_mismatch")
    roots = [object_record(item) for item in raw_roots]
    require(all(roots), "controlled_batch_root_row_malformed")
    require(
        [root.get("slot") for root in roots] == list(range(1, BATCH_SIZE + 1)),
        "controlled_batch_root_slots_not_exact",
    )
    root_ids: list[str] = []
    child_ids: list[str] = []
    total_notional = Decimal("0")
    planned_child_total = Decimal("0")
    price_increment = Decimal(
        str(object_record(preflight.get("product")).get("price_increment") or "0")
    )
    require(
        price_increment.is_finite() and price_increment > 0,
        "controlled_batch_price_increment_invalid",
    )
    planned_child_price = (
        (planned_bid * CHILD_MINIMUM_BID_RATIO) / price_increment
    ).to_integral_value(rounding=ROUND_CEILING) * price_increment
    for slot, root_plan in enumerate(roots, start=1):
        require(
            set(root_plan)
            == {
                "slot",
                "root_client_order_id",
                "child_client_order_id",
                "planned_notional_usdc",
                "order",
                "proof_approval_ids",
            },
            f"controlled_batch_root_fields_mismatch:{slot}",
        )
        order = object_record(root_plan.get("order"))
        root_id = deterministic_root_client_order_id(batch_id, slot)
        child_id = deterministic_child_client_order_id(root_id)
        require(
            root_plan.get("root_client_order_id") == root_id,
            f"controlled_batch_root_id_mismatch:{slot}",
        )
        require(
            root_plan.get("child_client_order_id") == child_id,
            f"controlled_batch_child_id_mismatch:{slot}",
        )
        require(
            order.get("client_order_id") == root_id,
            f"controlled_batch_order_root_id_mismatch:{slot}",
        )
        approvals = object_record(root_plan.get("proof_approval_ids"))
        require(
            set(approvals)
            == {"root_place", "root_cancel", "child_reveal", "child_cancel"},
            f"controlled_batch_proof_approval_fields_mismatch:{slot}",
        )
        for purpose, approval in approvals.items():
            require(
                approval
                == deterministic_proof_approval_id(
                    batch_id,
                    slot=slot,
                    purpose=purpose,
                ),
                f"controlled_batch_proof_approval_id_mismatch:{slot}:{purpose}",
            )
        notional = validate_prepared_root_order(
            preflight,
            order,
            batch_id=batch_id,
            slot=slot,
        )
        require(
            root_plan.get("planned_notional_usdc") == decimal_text(notional),
            f"controlled_batch_root_notional_mismatch:{slot}",
        )
        total_notional += notional
        planned_child_notional = (
            Decimal(str(order.get("base_size") or "0")) * planned_child_price
        )
        require(
            planned_child_notional < CHILD_SUBMITTED_CAP,
            f"controlled_batch_child_reference_cap_mismatch:{slot}",
        )
        planned_child_total += planned_child_notional
        root_ids.append(root_id)
        child_ids.append(child_id)
    require(len(set(root_ids)) == BATCH_SIZE, "controlled_batch_root_ids_not_unique")
    require(len(set(child_ids)) == BATCH_SIZE, "controlled_batch_child_ids_not_unique")
    require(not set(root_ids) & set(child_ids), "controlled_batch_root_child_id_collision")
    require(
        plan.get("planned_total_root_notional_usdc") == decimal_text(total_notional),
        "controlled_batch_total_root_notional_mismatch",
    )
    require(
        plan.get("planned_total_child_reference_notional_usdc")
        == decimal_text(planned_child_total),
        "controlled_batch_total_child_reference_notional_mismatch",
    )
    planned_batch_total = total_notional + planned_child_total
    require(
        plan.get("planned_total_root_child_reference_notional_usdc")
        == decimal_text(planned_batch_total),
        "controlled_batch_total_root_child_reference_notional_mismatch",
    )
    require(
        planned_batch_total < BATCH_TOTAL_REFERENCE_CAP_USDC,
        "controlled_batch_total_reference_cap_exceeded",
    )
    wallet_available = Decimal(
        str(object_record(preflight.get("wallets")).get("USDC") or "0")
    )
    require(
        wallet_available.is_finite() and wallet_available >= total_notional,
        "controlled_batch_total_wallet_insufficient",
    )
    first_order = object_record(roots[0].get("order"))
    planned_price = Decimal(str(first_order.get("limit_price") or "0"))
    recorded_planned_ratio = Decimal(
        str(plan.get("planned_limit_to_ask_ratio") or "0")
    )
    require(
        planned_price >= planned_ask
        and planned_price <= planned_ask * MAX_ASK_RATIO,
        "controlled_batch_plan_order_not_bound_to_planned_ask",
    )
    require(
        recorded_planned_ratio == planned_price / planned_ask
        and Decimal("1") <= recorded_planned_ratio <= MAX_ASK_RATIO,
        "controlled_batch_plan_actual_ask_ratio_mismatch",
    )
    return roots, total_notional


def batch_registry_paths(batch_id: str) -> tuple[Path, Path]:
    try:
        parsed = UUID(batch_id)
    except ValueError as exc:
        raise ProofFailure("global_batch_id_invalid") from exc
    require(
        parsed.version == 5 and str(parsed) == batch_id,
        "global_batch_id_not_canonical_uuid5",
    )
    return (
        GLOBAL_BATCH_REGISTRY_DIR / GLOBAL_BATCH_MARKER_FILENAME,
        GLOBAL_BATCH_REGISTRY_DIR / GLOBAL_BATCH_LEDGER_FILENAME,
    )


def build_global_batch_marker_payload(
    plan_file: Path,
    *,
    confirmed_plan: Mapping[str, Any],
    expected_hash: str,
    expected_runner_sha256: str,
    registered_at: str,
    process_id: int,
) -> dict[str, Any]:
    predecessor_binding = object_record(
        confirmed_plan.get("predecessor_binding")
    )
    require(
        predecessor_binding == offline_predecessor_binding_fixture(),
        "successor_marker_predecessor_binding_mismatch",
    )
    root_plans = [
        object_record(root)
        for root in list_value(confirmed_plan.get("roots"))
    ]
    roots = [
        approved_exact_successor_root_tuple(confirmed_plan, root)
        for root in root_plans[1:]
    ]
    marker_path, ledger_path = batch_registry_paths(
        str(confirmed_plan.get("batch_id") or "")
    )
    return {
        "schema_version": "1",
        "authority": "controlled-admin-spot-root-child-successor-batch",
        "approval_id": str(confirmed_plan.get("approval_id") or ""),
        "batch_id": str(confirmed_plan.get("batch_id") or ""),
        "batch_size": BATCH_SIZE,
        "plan_file": str(plan_file),
        "plan_sha256": expected_hash,
        "runner_sha256": expected_runner_sha256,
        "backend_commit": EXPECTED_COMMIT,
        "marker_path": str(marker_path),
        "attempt_ledger_path": str(ledger_path),
        "remaining_attempt_count": SUCCESSOR_ATTEMPT_COUNT,
        "root_order_maximum": SUCCESSOR_ROOT_ORDER_MAXIMUM,
        "child_order_maximum": SUCCESSOR_CHILD_ORDER_MAXIMUM,
        "cumulative_root_order_count_after_success": BATCH_SIZE,
        "cumulative_child_order_count_after_success": BATCH_SIZE,
        "inherited_reference_notional_usdc": decimal_text(
            CARRIED_ROOT_PLANNED_NOTIONAL
        ),
        "predecessor_binding": predecessor_binding,
        "exact_child_client_order_ids": [
            str(root["child_client_order_id"]) for root in root_plans
        ],
        "carried_root_policy": {
            "batch_slot": 1,
            "root_client_order_id": CARRIED_ROOT_CLIENT_ORDER_ID,
            "child_client_order_id": CARRIED_CHILD_CLIENT_ORDER_ID,
            "root_placement_authorized": False,
            "first_successor_attempt": "child",
        },
        "exact_root_tuples": roots,
        "child_policy": {
            "product_id": PRODUCT_ID,
            "side": "SELL",
            "order_type": "LIMIT",
            "time_in_force": "GOOD_UNTIL_CANCELLED",
            "post_only": False,
            "minimum_fresh_bid_ratio": decimal_text(CHILD_MINIMUM_BID_RATIO),
            "strict_max_notional_usdc": decimal_text(CHILD_SUBMITTED_CAP),
            "strict_batch_reference_cap_usdc": decimal_text(
                BATCH_TOTAL_REFERENCE_CAP_USDC
            ),
            "deterministic_first_child_only": True,
        },
        "registered_at": registered_at,
        "process_id": process_id,
    }


def _ensure_global_batch_registry() -> None:
    try:
        GLOBAL_BATCH_REGISTRY_DIR.mkdir(mode=0o700, parents=False, exist_ok=True)
    except FileExistsError:
        pass
    metadata = GLOBAL_BATCH_REGISTRY_DIR.lstat()
    require(stat.S_ISDIR(metadata.st_mode), "global_batch_registry_not_directory")
    require(not GLOBAL_BATCH_REGISTRY_DIR.is_symlink(), "global_batch_registry_symlink")
    require(metadata.st_uid == os.getuid(), "global_batch_registry_owner_mismatch")
    require(
        metadata.st_mode & 0o077 == 0,
        "global_batch_registry_permissions_too_broad",
    )


def require_batch_unregistered(
    *,
    marker_exists: bool,
    ledger_exists: bool,
) -> None:
    """Treat any prior or crash-partial durable state as permanently consumed."""

    require(not marker_exists, "global_batch_already_registered")
    require(not ledger_exists, "global_batch_attempt_ledger_already_exists")


def initialize_global_batch_ledger(
    plan_file: Path,
    *,
    confirmed_plan: Mapping[str, Any],
    expected_hash: str,
    expected_runner_sha256: str,
) -> tuple[Path, Path]:
    """Register this batch once; any partial creation remains fail-closed."""

    require(plan_file.is_absolute(), "controlled_batch_plan_path_not_absolute")
    require(
        expected_runner_sha256 == runner_sha256(),
        "runner_sha256_changed_before_batch_registration",
    )
    _ensure_global_batch_registry()
    marker_path, ledger_path = batch_registry_paths(
        str(confirmed_plan.get("batch_id") or "")
    )
    require_batch_unregistered(
        marker_exists=marker_path.exists(),
        ledger_exists=ledger_path.exists(),
    )
    marker_payload = build_global_batch_marker_payload(
        plan_file,
        confirmed_plan=confirmed_plan,
        expected_hash=expected_hash,
        expected_runner_sha256=expected_runner_sha256,
        registered_at=datetime.now(timezone.utc).isoformat(),
        process_id=os.getpid(),
    )
    _write_owner_only_exclusive_json(
        marker_path,
        marker_payload,
        exists_blocker="global_batch_already_registered",
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(ledger_path, flags, 0o600)
    except Exception as exc:
        raise ProofFailure("global_batch_attempt_ledger_create_failed") from exc
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    directory_descriptor = os.open(GLOBAL_BATCH_REGISTRY_DIR, directory_flags)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    require(
        expected_runner_sha256 == runner_sha256(),
        "runner_sha256_changed_after_batch_registration",
    )
    return marker_path, ledger_path


def _validate_authorized_child_tuple(
    plan: Mapping[str, Any],
    root_plan: Mapping[str, Any],
    child_tuple: Mapping[str, Any],
) -> None:
    expected_fields = {
        "batch_id",
        "batch_slot",
        "approval_snapshot_id",
        "root_client_order_id",
        "client_order_id",
        "product_id",
        "side",
        "order_type",
        "time_in_force",
        "base_size",
        "limit_price",
        "post_only",
        "reference_bid",
        "market_observed_at",
        "minimum_bid_ratio",
        "strict_max_notional_usdc",
    }
    require(set(child_tuple) == expected_fields, "child_tuple_fields_mismatch")
    slot = int(root_plan.get("slot") or 0)
    root_id = str(root_plan.get("root_client_order_id") or "")
    child_id = str(root_plan.get("child_client_order_id") or "")
    require(child_tuple.get("batch_id") == plan.get("batch_id"), "child_tuple_batch_mismatch")
    require(child_tuple.get("batch_slot") == slot, "child_tuple_slot_mismatch")
    require(
        child_tuple.get("approval_snapshot_id")
        == object_record(root_plan.get("proof_approval_ids")).get(
            "child_reveal"
        ),
        "child_tuple_approval_snapshot_mismatch",
    )
    require(child_tuple.get("root_client_order_id") == root_id, "child_tuple_root_mismatch")
    require(child_tuple.get("client_order_id") == child_id, "child_tuple_id_mismatch")
    require(child_tuple.get("product_id") == PRODUCT_ID, "child_tuple_product_mismatch")
    require(child_tuple.get("side") == "SELL", "child_tuple_side_mismatch")
    require(child_tuple.get("order_type") == "LIMIT", "child_tuple_type_mismatch")
    require(
        child_tuple.get("time_in_force") == "GOOD_UNTIL_CANCELLED",
        "child_tuple_tif_mismatch",
    )
    require(child_tuple.get("post_only") is False, "child_tuple_post_only_mismatch")
    size = Decimal(str(child_tuple.get("base_size") or "0"))
    price = Decimal(str(child_tuple.get("limit_price") or "0"))
    bid = Decimal(str(child_tuple.get("reference_bid") or "0"))
    minimum_ratio = Decimal(str(child_tuple.get("minimum_bid_ratio") or "0"))
    cap = Decimal(str(child_tuple.get("strict_max_notional_usdc") or "0"))
    for value, blocker in (
        (size, "child_tuple_size_invalid"),
        (price, "child_tuple_price_invalid"),
        (bid, "child_tuple_bid_invalid"),
        (minimum_ratio, "child_tuple_ratio_invalid"),
        (cap, "child_tuple_cap_invalid"),
    ):
        require(value.is_finite() and value > 0, blocker)
    require(
        str(child_tuple.get("base_size")) == decimal_text(size),
        "child_tuple_size_not_canonical",
    )
    require(
        str(child_tuple.get("limit_price")) == decimal_text(price),
        "child_tuple_price_not_canonical",
    )
    require(minimum_ratio == CHILD_MINIMUM_BID_RATIO, "child_tuple_ratio_policy_drift")
    require(cap == CHILD_SUBMITTED_CAP, "child_tuple_cap_policy_drift")
    require(price >= bid * CHILD_MINIMUM_BID_RATIO, "child_tuple_not_far_from_bid")
    require(price * size < CHILD_SUBMITTED_CAP, "child_tuple_notional_not_strictly_below_cap")
    try:
        observed_at = datetime.fromisoformat(
            str(child_tuple.get("market_observed_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ProofFailure("child_tuple_market_observed_at_invalid") from exc
    require(observed_at.tzinfo is not None, "child_tuple_market_timezone_missing")


def build_child_order_tuple(
    plan: Mapping[str, Any],
    root_plan: Mapping[str, Any],
    *,
    filled_size: Decimal,
    fresh_market: Mapping[str, Any],
    price_increment: Decimal,
) -> dict[str, Any]:
    require(filled_size.is_finite() and filled_size > 0, "child_filled_size_invalid")
    bid = Decimal(str(fresh_market.get("best_bid") or "0"))
    require(bid.is_finite() and bid > 0, "child_fresh_bid_invalid")
    require(
        price_increment.is_finite() and price_increment > 0,
        "child_price_increment_invalid",
    )
    price_ticks = (
        (bid * CHILD_MINIMUM_BID_RATIO) / price_increment
    ).to_integral_value(rounding=ROUND_CEILING)
    price = price_ticks * price_increment
    child_tuple = {
        "batch_id": str(plan.get("batch_id") or ""),
        "batch_slot": int(root_plan.get("slot") or 0),
        "approval_snapshot_id": str(
            object_record(root_plan.get("proof_approval_ids")).get(
                "child_reveal"
            )
            or ""
        ),
        "root_client_order_id": str(root_plan.get("root_client_order_id") or ""),
        "client_order_id": str(root_plan.get("child_client_order_id") or ""),
        "product_id": PRODUCT_ID,
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "base_size": decimal_text(filled_size),
        "limit_price": decimal_text(price),
        "post_only": False,
        "reference_bid": decimal_text(bid),
        "market_observed_at": str(fresh_market.get("observed_at") or ""),
        "minimum_bid_ratio": decimal_text(CHILD_MINIMUM_BID_RATIO),
        "strict_max_notional_usdc": decimal_text(CHILD_SUBMITTED_CAP),
    }
    _validate_authorized_child_tuple(plan, root_plan, child_tuple)
    return child_tuple


def _parse_and_validate_attempt_ledger(
    raw: bytes,
    *,
    confirmed_plan: Mapping[str, Any],
    confirmed_plan_hash: str,
) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ProofFailure("global_batch_attempt_ledger_not_utf8") from exc
    schedule = successor_attempt_schedule()
    require(
        len(lines) <= SUCCESSOR_ATTEMPT_COUNT,
        "global_batch_attempt_count_exceeded",
    )
    roots = [object_record(item) for item in list_value(confirmed_plan.get("roots"))]
    records: list[dict[str, Any]] = []
    cumulative_reference_notional = CARRIED_ROOT_PLANNED_NOTIONAL
    for sequence, line in enumerate(lines, start=1):
        require(bool(line.strip()), "global_batch_attempt_blank_line")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProofFailure("global_batch_attempt_ledger_malformed") from exc
        require(isinstance(value, dict), "global_batch_attempt_record_not_object")
        record = dict(value)
        require(
            set(record)
            == {
                "schema_version",
                "sequence",
                "batch_id",
                "batch_slot",
                "attempt_kind",
                "client_order_id",
                "root_client_order_id",
                "plan_sha256",
                "runner_sha256",
                "backend_commit",
                "exact_order_tuple",
                "exact_order_tuple_sha256",
                "consumed_at",
                "process_id",
            },
            "global_batch_attempt_record_fields_mismatch",
        )
        expected_slot, expected_kind = schedule[sequence - 1]
        require(record.get("schema_version") == "1", "global_batch_attempt_schema_mismatch")
        require(record.get("sequence") == sequence, "global_batch_attempt_sequence_mismatch")
        require(record.get("batch_slot") == expected_slot, "global_batch_attempt_slot_sequence_mismatch")
        require(record.get("attempt_kind") == expected_kind, "global_batch_attempt_kind_sequence_mismatch")
        require(record.get("batch_id") == confirmed_plan.get("batch_id"), "global_batch_attempt_batch_mismatch")
        require(record.get("plan_sha256") == confirmed_plan_hash, "global_batch_attempt_plan_hash_mismatch")
        require(record.get("runner_sha256") == runner_sha256(), "global_batch_attempt_runner_hash_mismatch")
        require(record.get("backend_commit") == EXPECTED_COMMIT, "global_batch_attempt_commit_mismatch")
        try:
            consumed_at = datetime.fromisoformat(
                str(record.get("consumed_at") or "").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ProofFailure("global_batch_attempt_timestamp_invalid") from exc
        require(
            consumed_at.tzinfo is not None,
            "global_batch_attempt_timestamp_timezone_missing",
        )
        root_plan = roots[expected_slot - 1]
        expected_root_id = str(root_plan.get("root_client_order_id") or "")
        expected_client_id = (
            expected_root_id
            if expected_kind == "root"
            else str(root_plan.get("child_client_order_id") or "")
        )
        require(record.get("root_client_order_id") == expected_root_id, "global_batch_attempt_root_id_mismatch")
        require(record.get("client_order_id") == expected_client_id, "global_batch_attempt_client_id_mismatch")
        exact_tuple = object_record(record.get("exact_order_tuple"))
        require(
            record.get("exact_order_tuple_sha256") == _canonical_json_sha256(exact_tuple),
            "global_batch_attempt_tuple_hash_mismatch",
        )
        if expected_kind == "root":
            require(
                exact_tuple
                == approved_exact_successor_root_tuple(
                    confirmed_plan,
                    root_plan,
                ),
                "global_batch_attempt_root_tuple_mismatch",
            )
        else:
            _validate_authorized_child_tuple(confirmed_plan, root_plan, exact_tuple)
            market_observed_at = datetime.fromisoformat(
                str(exact_tuple["market_observed_at"]).replace("Z", "+00:00")
            )
            market_age = (consumed_at - market_observed_at).total_seconds()
            require(
                -1 <= market_age <= 30,
                "global_batch_child_market_not_fresh_at_consumption",
            )
        tuple_notional = Decimal(str(exact_tuple.get("base_size") or "0")) * Decimal(
            str(exact_tuple.get("limit_price") or "0")
        )
        require(
            tuple_notional.is_finite() and tuple_notional > 0,
            "global_batch_attempt_reference_notional_invalid",
        )
        cumulative_reference_notional += tuple_notional
        require(
            cumulative_reference_notional < BATCH_TOTAL_REFERENCE_CAP_USDC,
            "global_batch_attempt_cumulative_reference_cap_exceeded",
        )
        records.append(record)
    return records


def read_batch_attempt_ledger(
    ledger_path: Path,
    *,
    confirmed_plan: Mapping[str, Any],
    confirmed_plan_hash: str,
) -> list[dict[str, Any]]:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(ledger_path, flags)
    except OSError as exc:
        raise ProofFailure("global_batch_attempt_ledger_open_failed") from exc
    try:
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode), "global_batch_attempt_ledger_not_regular")
        require(metadata.st_uid == os.getuid(), "global_batch_attempt_ledger_owner_mismatch")
        require(metadata.st_mode & 0o077 == 0, "global_batch_attempt_ledger_permissions_too_broad")
        require(metadata.st_size <= 100_000, "global_batch_attempt_ledger_too_large")
        raw = os.read(descriptor, 100_001)
    finally:
        os.close(descriptor)
    require(len(raw) <= 100_000, "global_batch_attempt_ledger_too_large")
    return _parse_and_validate_attempt_ledger(
        raw,
        confirmed_plan=confirmed_plan,
        confirmed_plan_hash=confirmed_plan_hash,
    )


def require_next_batch_attempt(
    records: Sequence[Mapping[str, Any]],
    *,
    slot: int,
    attempt_kind: str,
) -> int:
    schedule = successor_attempt_schedule()
    require(
        len(records) < SUCCESSOR_ATTEMPT_COUNT,
        "global_batch_attempt_count_exceeded",
    )
    next_sequence = len(records) + 1
    expected_slot, expected_kind = schedule[next_sequence - 1]
    require(slot == expected_slot, "global_batch_attempt_slot_not_next")
    require(attempt_kind == expected_kind, "global_batch_attempt_kind_not_next")
    return next_sequence


def build_batch_attempt_record(
    *,
    confirmed_plan: Mapping[str, Any],
    confirmed_plan_hash: str,
    sequence: int,
    slot: int,
    attempt_kind: str,
    exact_order_tuple: Mapping[str, Any],
    consumed_at: str,
    process_id: int,
) -> dict[str, Any]:
    roots = [object_record(item) for item in list_value(confirmed_plan.get("roots"))]
    require(1 <= slot <= len(roots), "global_batch_attempt_slot_invalid")
    root_plan = roots[slot - 1]
    tuple_record = dict(exact_order_tuple)
    if attempt_kind == "root":
        require(
            tuple_record
            == approved_exact_successor_root_tuple(
                confirmed_plan,
                root_plan,
            ),
            "global_batch_attempt_root_tuple_drift",
        )
        client_order_id = str(root_plan["root_client_order_id"])
    else:
        require(attempt_kind == "child", "global_batch_attempt_kind_invalid")
        _validate_authorized_child_tuple(
            confirmed_plan,
            root_plan,
            tuple_record,
        )
        client_order_id = str(root_plan["child_client_order_id"])
    return {
        "schema_version": "1",
        "sequence": sequence,
        "batch_id": str(confirmed_plan.get("batch_id") or ""),
        "batch_slot": slot,
        "attempt_kind": attempt_kind,
        "client_order_id": client_order_id,
        "root_client_order_id": str(root_plan["root_client_order_id"]),
        "plan_sha256": confirmed_plan_hash,
        "runner_sha256": runner_sha256(),
        "backend_commit": EXPECTED_COMMIT,
        "exact_order_tuple": tuple_record,
        "exact_order_tuple_sha256": _canonical_json_sha256(tuple_record),
        "consumed_at": consumed_at,
        "process_id": process_id,
    }


def authorized_sdk_tuple_for_call(
    records: Sequence[Mapping[str, Any]],
    *,
    attempt_kind: str,
    prior_call_count: int,
) -> dict[str, Any]:
    """Return only the next already-consumed root or child SDK tuple."""

    require(attempt_kind in {"root", "child"}, "sdk_attempt_kind_invalid")
    maximum = (
        SUCCESSOR_ROOT_ORDER_MAXIMUM
        if attempt_kind == "root"
        else SUCCESSOR_CHILD_ORDER_MAXIMUM
    )
    require(
        0 <= prior_call_count < maximum,
        f"{attempt_kind}_sdk_call_maximum_exceeded",
    )
    attempts = [
        object_record(record)
        for record in records
        if record.get("attempt_kind") == attempt_kind
    ]
    require(
        len(attempts) > prior_call_count,
        f"{attempt_kind}_sdk_attempt_not_consumed",
    )
    return object_record(attempts[prior_call_count]["exact_order_tuple"])


def consume_batch_attempt(
    ledger_path: Path,
    *,
    confirmed_plan: Mapping[str, Any],
    confirmed_plan_hash: str,
    slot: int,
    attempt_kind: str,
    exact_order_tuple: Mapping[str, Any],
    consumed_at: str | None = None,
    process_id: int | None = None,
) -> dict[str, Any]:
    """Append one irreversible root/child capability before command HTTP."""

    require(attempt_kind in {"root", "child"}, "global_batch_attempt_kind_invalid")
    flags = os.O_RDWR | os.O_APPEND | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(ledger_path, flags)
    except OSError as exc:
        raise ProofFailure("global_batch_attempt_ledger_open_failed") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        require_plan_unexpired(
            confirmed_plan,
            blocker="global_batch_plan_expired_before_attempt_consumption",
        )
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode), "global_batch_attempt_ledger_not_regular")
        require(metadata.st_uid == os.getuid(), "global_batch_attempt_ledger_owner_mismatch")
        require(metadata.st_mode & 0o077 == 0, "global_batch_attempt_ledger_permissions_too_broad")
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, 100_001)
        records = _parse_and_validate_attempt_ledger(
            raw,
            confirmed_plan=confirmed_plan,
            confirmed_plan_hash=confirmed_plan_hash,
        )
        next_sequence = require_next_batch_attempt(
            records,
            slot=slot,
            attempt_kind=attempt_kind,
        )
        record = build_batch_attempt_record(
            confirmed_plan=confirmed_plan,
            confirmed_plan_hash=confirmed_plan_hash,
            sequence=next_sequence,
            slot=slot,
            attempt_kind=attempt_kind,
            exact_order_tuple=exact_order_tuple,
            consumed_at=consumed_at or datetime.now(timezone.utc).isoformat(),
            process_id=process_id if process_id is not None else os.getpid(),
        )
        encoded = (
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        os.lseek(descriptor, 0, os.SEEK_END)
        written = os.write(descriptor, encoded)
        require(written == len(encoded), "global_batch_attempt_ledger_short_write")
        os.fsync(descriptor)
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
    verified = read_batch_attempt_ledger(
        ledger_path,
        confirmed_plan=confirmed_plan,
        confirmed_plan_hash=confirmed_plan_hash,
    )
    require(
        verified and verified[-1] == record,
        "global_batch_attempt_durable_readback_mismatch",
    )
    return record
def _canonical_json_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _process_start_identity(process_id: int) -> str:
    """Return Linux PID starttime (field 22), robust to spaces in comm."""

    raw = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
    close_paren = raw.rfind(")")
    require(close_paren > 0, "runtime_child_parent_stat_malformed")
    fields_after_comm = raw[close_paren + 2 :].split()
    require(len(fields_after_comm) >= 20, "runtime_child_parent_stat_incomplete")
    starttime = fields_after_comm[19]
    require(starttime.isdigit(), "runtime_child_parent_start_identity_invalid")
    return starttime


def _read_owner_only_json(
    path: Path,
    *,
    blocker_prefix: str,
    maximum_size: int = 30_000,
) -> tuple[dict[str, Any], bytes]:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProofFailure(f"{blocker_prefix}_open_failed") from exc
    try:
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode), f"{blocker_prefix}_not_regular")
        require(metadata.st_uid == os.getuid(), f"{blocker_prefix}_owner_mismatch")
        require(metadata.st_mode & 0o077 == 0, f"{blocker_prefix}_permissions_too_broad")
        require(0 < metadata.st_size <= maximum_size, f"{blocker_prefix}_size_invalid")
        raw = os.read(descriptor, maximum_size + 1)
        require(len(raw) == metadata.st_size, f"{blocker_prefix}_short_read")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofFailure(f"{blocker_prefix}_malformed") from exc
    require(isinstance(value, dict), f"{blocker_prefix}_not_object")
    return dict(value), raw


def _write_owner_only_exclusive_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    exists_blocker: str,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ProofFailure(exists_blocker) from exc
    except OSError as exc:
        raise ProofFailure(f"{exists_blocker}_create_failed") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception as exc:
        raise ProofFailure(f"{exists_blocker}_write_failed") from exc


def _replace_owner_only_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically replace an owner-only reconciliation evidence file."""

    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_runtime_child_authority_payload(
    *,
    state_dir: Path,
    auth_file: Path,
    global_batch_marker: Path,
    global_batch_marker_sha256: str,
    attempt_ledger_path: Path,
    confirmed_plan: Mapping[str, Any],
    confirmed_plan_hash: str,
    confirmed_runner_sha256: str,
    parent_pid: int,
    parent_start_identity: str,
    nonce: str,
) -> dict[str, Any]:
    """Bind one embedded child process to the complete registered batch."""

    return {
        "schema_version": "2",
        "state_dir": str(state_dir),
        "auth_file": str(auth_file),
        "global_batch_marker": str(global_batch_marker),
        "global_batch_marker_sha256": global_batch_marker_sha256,
        "attempt_ledger_path": str(attempt_ledger_path),
        "approval_id": str(confirmed_plan.get("approval_id") or ""),
        "batch_id": str(confirmed_plan.get("batch_id") or ""),
        "batch_size": BATCH_SIZE,
        "plan_sha256": confirmed_plan_hash,
        "runner_sha256": confirmed_runner_sha256,
        "backend_commit": EXPECTED_COMMIT,
        "confirmed_plan": dict(confirmed_plan),
        "parent_pid": parent_pid,
        "parent_start_identity": parent_start_identity,
        "nonce": nonce,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _validate_authority_plan_structure(
    confirmed_plan: Mapping[str, Any],
    *,
    expected_plan_hash: str,
) -> None:
    require(
        plan_hash(confirmed_plan) == expected_plan_hash
        == confirmed_plan.get("plan_sha256"),
        "runtime_child_authority_plan_hash_mismatch",
    )
    require(
        confirmed_plan.get("backend_commit") == EXPECTED_COMMIT,
        "runtime_child_authority_plan_commit_mismatch",
    )
    require(
        confirmed_plan.get("runner_sha256") == runner_sha256(),
        "runtime_child_authority_plan_runner_mismatch",
    )
    batch_id = str(confirmed_plan.get("batch_id") or "")
    approval_id = str(confirmed_plan.get("approval_id") or "")
    require(
        batch_id == deterministic_batch_id(approval_id, runner_sha256()),
        "runtime_child_authority_batch_id_mismatch",
    )
    require(
        confirmed_plan.get("batch_size") == BATCH_SIZE,
        "runtime_child_authority_batch_size_mismatch",
    )
    predecessor_binding = object_record(
        confirmed_plan.get("predecessor_binding")
    )
    require(
        predecessor_binding == offline_predecessor_binding_fixture(),
        "runtime_child_authority_predecessor_binding_mismatch",
    )
    require(
        confirmed_plan.get("remaining_attempt_count")
        == SUCCESSOR_ATTEMPT_COUNT
        and confirmed_plan.get("new_root_order_maximum")
        == SUCCESSOR_ROOT_ORDER_MAXIMUM
        and confirmed_plan.get("child_order_maximum")
        == SUCCESSOR_CHILD_ORDER_MAXIMUM,
        "runtime_child_authority_successor_counts_mismatch",
    )
    roots = [
        object_record(item) for item in list_value(confirmed_plan.get("roots"))
    ]
    require(
        len(roots) == BATCH_SIZE and all(roots),
        "runtime_child_authority_root_count_mismatch",
    )
    seen: set[str] = set()
    forbidden_fresh_ids = {
        HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID,
        HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID,
    } | set(PREDECESSOR_PLANNED_ROOT_CLIENT_ORDER_IDS) | set(
        PREDECESSOR_PLANNED_CHILD_CLIENT_ORDER_IDS
    )
    for slot, root_plan in enumerate(roots, start=1):
        require(
            root_plan.get("slot") == slot,
            "runtime_child_authority_root_slot_mismatch",
        )
        if slot == 1:
            root_id = CARRIED_ROOT_CLIENT_ORDER_ID
            child_id = CARRIED_CHILD_CLIENT_ORDER_ID
            require(
                root_plan.get("root_placement_authorized") is False
                and object_record(root_plan.get("order"))
                == _carried_root_order(),
                "runtime_child_authority_carried_root_mismatch",
            )
        else:
            root_id = deterministic_root_client_order_id(batch_id, slot)
            child_id = deterministic_child_client_order_id(root_id)
            require(
                root_plan.get("root_placement_authorized") is True,
                "runtime_child_authority_fresh_root_not_authorized",
            )
        require(
            root_plan.get("root_client_order_id") == root_id,
            "runtime_child_authority_root_id_mismatch",
        )
        require(
            root_plan.get("child_client_order_id") == child_id,
            "runtime_child_authority_child_id_mismatch",
        )
        order = object_record(root_plan.get("order"))
        require(
            order.get("client_order_id") == root_id,
            "runtime_child_authority_order_id_mismatch",
        )
        require(
            order.get("product_id") == PRODUCT_ID
            and order.get("side") == "BUY"
            and order.get("order_type") == "LIMIT"
            and order.get("time_in_force") == "FILL_OR_KILL"
            and order.get("post_only") is False,
            "runtime_child_authority_root_tuple_mismatch",
        )
        require(
            root_id not in seen and child_id not in seen,
            "runtime_child_authority_id_collision",
        )
        if slot > 1:
            require(
                root_id not in forbidden_fresh_ids
                and child_id not in forbidden_fresh_ids,
                "runtime_child_authority_predecessor_id_collision",
            )
        seen.update({root_id, child_id})


def validate_runtime_child_authority_payload(
    payload: Mapping[str, Any],
    *,
    state_dir: Path,
    auth_file: Path,
    supplied_nonce: str,
    actual_parent_pid: int,
    actual_parent_start_identity: str,
) -> dict[str, Any]:
    """Pure fail-closed validation for the parent-created batch capability."""

    expected_fields = {
        "schema_version",
        "state_dir",
        "auth_file",
        "global_batch_marker",
        "global_batch_marker_sha256",
        "attempt_ledger_path",
        "approval_id",
        "batch_id",
        "batch_size",
        "plan_sha256",
        "runner_sha256",
        "backend_commit",
        "confirmed_plan",
        "parent_pid",
        "parent_start_identity",
        "nonce",
        "created_at",
    }
    require(
        set(payload) == expected_fields,
        "runtime_child_authority_fields_mismatch",
    )
    require(
        payload.get("schema_version") == "2",
        "runtime_child_authority_schema_mismatch",
    )
    require(
        payload.get("state_dir") == str(state_dir),
        "runtime_child_authority_state_dir_mismatch",
    )
    require(
        payload.get("auth_file") == str(auth_file),
        "runtime_child_authority_file_mismatch",
    )
    marker_path, ledger_path = batch_registry_paths(
        str(payload.get("batch_id") or "")
    )
    require(
        payload.get("global_batch_marker") == str(marker_path),
        "runtime_child_authority_marker_path_mismatch",
    )
    require(
        payload.get("attempt_ledger_path") == str(ledger_path),
        "runtime_child_authority_ledger_path_mismatch",
    )
    for field in (
        "global_batch_marker_sha256",
        "plan_sha256",
        "runner_sha256",
    ):
        value = str(payload.get(field) or "")
        require(
            len(value) == 64
            and all(character in "0123456789abcdef" for character in value),
            f"runtime_child_authority_hash_invalid:{field}",
        )
    require(
        payload.get("backend_commit") == EXPECTED_COMMIT,
        "runtime_child_authority_commit_mismatch",
    )
    require(
        payload.get("runner_sha256") == runner_sha256(),
        "runtime_child_authority_runner_mismatch",
    )
    require(
        payload.get("batch_size") == BATCH_SIZE,
        "runtime_child_authority_batch_size_mismatch",
    )
    require(
        bool(str(payload.get("approval_id") or "")),
        "runtime_child_authority_approval_missing",
    )
    require(
        int(payload.get("parent_pid") or -1) == actual_parent_pid,
        "runtime_child_authority_parent_pid_mismatch",
    )
    require(
        str(payload.get("parent_start_identity") or "")
        == actual_parent_start_identity,
        "runtime_child_authority_parent_start_mismatch",
    )
    require(
        bool(supplied_nonce)
        and secrets.compare_digest(str(payload.get("nonce") or ""), supplied_nonce),
        "runtime_child_authority_nonce_mismatch",
    )
    confirmed_plan = object_record(payload.get("confirmed_plan"))
    require(
        confirmed_plan.get("approval_id") == payload.get("approval_id"),
        "runtime_child_authority_plan_approval_mismatch",
    )
    require(
        confirmed_plan.get("batch_id") == payload.get("batch_id"),
        "runtime_child_authority_plan_batch_mismatch",
    )
    _validate_authority_plan_structure(
        confirmed_plan,
        expected_plan_hash=str(payload["plan_sha256"]),
    )
    return confirmed_plan


def validate_canonical_root_create_order_call(
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
    *,
    exact_tuple: Mapping[str, Any],
) -> None:
    """Reject any root SDK call that is not its consumed FOK tuple."""

    require(not args, "root_create_order_positional_arguments_denied")
    require(
        set(kwargs)
        == {"client_order_id", "product_id", "side", "order_configuration"},
        "root_create_order_keyword_arguments_mismatch",
    )
    require(
        kwargs.get("client_order_id") == exact_tuple.get("client_order_id"),
        "root_create_order_client_id_mismatch",
    )
    require(
        kwargs.get("product_id") == PRODUCT_ID == exact_tuple.get("product_id"),
        "root_create_order_product_mismatch",
    )
    require(
        str(kwargs.get("side") or "").upper()
        == "BUY"
        == exact_tuple.get("side"),
        "root_create_order_side_mismatch",
    )
    configuration = object_record(kwargs.get("order_configuration"))
    require(
        set(configuration) == {"limit_limit_fok"},
        "root_create_order_configuration_mismatch",
    )
    fok = object_record(configuration.get("limit_limit_fok"))
    require(
        set(fok) == {"base_size", "limit_price"},
        "root_create_order_fok_fields_mismatch",
    )
    for field in ("base_size", "limit_price"):
        try:
            actual = Decimal(str(fok.get(field)))
            approved = Decimal(str(exact_tuple.get(field)))
        except (ArithmeticError, TypeError, ValueError):
            raise ProofFailure(f"root_create_order_{field}_invalid") from None
        require(
            actual.is_finite() and actual > 0,
            f"root_create_order_{field}_invalid",
        )
        require(
            approved.is_finite() and approved > 0 and actual == approved,
            f"root_create_order_{field}_mismatch",
        )


def validate_canonical_child_place_limit_order_call(
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
    *,
    exact_tuple: Mapping[str, Any],
) -> None:
    """Reject generic, later-generation, or tuple-drifted child SDK calls."""

    require(not args, "child_place_limit_order_positional_arguments_denied")
    require(
        set(kwargs)
        == {
            "product_id",
            "side",
            "limit_price",
            "base_size",
            "client_order_id",
            "post_only",
        },
        "child_place_limit_order_keyword_arguments_mismatch",
    )
    require(
        kwargs.get("product_id") == PRODUCT_ID == exact_tuple.get("product_id"),
        "child_place_limit_order_product_mismatch",
    )
    require(
        str(kwargs.get("side") or "").upper()
        == "SELL"
        == exact_tuple.get("side"),
        "child_place_limit_order_side_mismatch",
    )
    require(
        kwargs.get("client_order_id") == exact_tuple.get("client_order_id"),
        "child_place_limit_order_client_id_mismatch",
    )
    require(
        kwargs.get("post_only") is False,
        "child_place_limit_order_post_only_mismatch",
    )
    for field in ("base_size", "limit_price"):
        try:
            actual = Decimal(str(kwargs.get(field)))
            approved = Decimal(str(exact_tuple.get(field)))
        except (ArithmeticError, TypeError, ValueError):
            raise ProofFailure(f"child_place_limit_order_{field}_invalid") from None
        require(
            actual.is_finite() and actual > 0,
            f"child_place_limit_order_{field}_invalid",
        )
        require(
            approved.is_finite() and approved > 0 and actual == approved,
            f"child_place_limit_order_{field}_mismatch",
        )
    require(
        Decimal(str(kwargs["base_size"]))
        * Decimal(str(kwargs["limit_price"]))
        < CHILD_SUBMITTED_CAP,
        "child_place_limit_order_notional_cap_exceeded",
    )


def consume_runtime_child_authority(
    *,
    state_dir: Path,
    auth_file: Path,
    supplied_nonce: str,
) -> tuple[dict[str, Any], str, Path]:
    """Validate and irreversibly consume the parent-created runtime capability."""

    require(state_dir.is_absolute(), "runtime_child_state_dir_not_absolute")
    require(
        auth_file == state_dir / RUNTIME_CHILD_AUTH_FILENAME,
        "runtime_child_auth_file_path_mismatch",
    )
    state_metadata = state_dir.lstat()
    require(
        stat.S_ISDIR(state_metadata.st_mode),
        "runtime_child_state_dir_not_directory",
    )
    require(not state_dir.is_symlink(), "runtime_child_state_dir_symlink")
    require(
        state_metadata.st_uid == os.getuid(),
        "runtime_child_state_dir_owner_mismatch",
    )
    require(
        state_metadata.st_mode & 0o077 == 0,
        "runtime_child_state_dir_permissions_too_broad",
    )
    auth_payload, _ = _read_owner_only_json(
        auth_file,
        blocker_prefix="runtime_child_authority",
        maximum_size=100_000,
    )
    parent_pid = os.getppid()
    parent_start_identity = _process_start_identity(parent_pid)
    confirmed_plan = validate_runtime_child_authority_payload(
        auth_payload,
        state_dir=state_dir,
        auth_file=auth_file,
        supplied_nonce=supplied_nonce,
        actual_parent_pid=parent_pid,
        actual_parent_start_identity=parent_start_identity,
    )
    require(
        load_predecessor_binding()
        == object_record(confirmed_plan.get("predecessor_binding")),
        "runtime_child_predecessor_artifacts_changed",
    )
    marker_path = Path(str(auth_payload["global_batch_marker"]))
    marker_payload, marker_raw = _read_owner_only_json(
        marker_path,
        blocker_prefix="runtime_child_global_batch_marker",
        maximum_size=100_000,
    )
    require(
        hashlib.sha256(marker_raw).hexdigest()
        == auth_payload["global_batch_marker_sha256"],
        "runtime_child_global_batch_marker_hash_mismatch",
    )
    expected_marker = build_global_batch_marker_payload(
        Path(str(marker_payload.get("plan_file") or "")),
        confirmed_plan=confirmed_plan,
        expected_hash=str(auth_payload["plan_sha256"]),
        expected_runner_sha256=str(auth_payload["runner_sha256"]),
        registered_at=str(marker_payload.get("registered_at") or ""),
        process_id=int(marker_payload.get("process_id") or 0),
    )
    require(
        marker_payload == expected_marker,
        "runtime_child_global_batch_marker_binding_mismatch",
    )
    ledger_path = Path(str(auth_payload["attempt_ledger_path"]))
    read_batch_attempt_ledger(
        ledger_path,
        confirmed_plan=confirmed_plan,
        confirmed_plan_hash=str(auth_payload["plan_sha256"]),
    )
    auth_sha256 = _canonical_json_sha256(auth_payload)
    used_path = state_dir / RUNTIME_CHILD_AUTH_USED_FILENAME
    _write_owner_only_exclusive_json(
        used_path,
        {
            "authority_sha256": auth_sha256,
            "approval_id": auth_payload["approval_id"],
            "batch_id": auth_payload["batch_id"],
            "plan_sha256": auth_payload["plan_sha256"],
            "runner_sha256": auth_payload["runner_sha256"],
            "global_batch_marker": str(marker_path),
            "attempt_ledger_path": str(ledger_path),
            "child_pid": os.getpid(),
            "parent_pid": parent_pid,
            "consumed_at": datetime.now(timezone.utc).isoformat(),
        },
        exists_blocker="runtime_child_authority_already_consumed",
    )
    return confirmed_plan, auth_sha256, ledger_path


def _write_sdk_boundary_sentinel_evidence(
    state_dir: Path,
    *,
    root_create_order_call_count: int,
    child_place_limit_order_call_count: int,
    denied_call_count: int,
    root_sdk_inflight: bool = False,
    child_sdk_inflight: bool = False,
    phase: str,
    installed: bool,
    wrapper_identity_proven: bool,
    error: str | None = None,
) -> None:
    """Atomically persist both SDK-boundary counters."""

    path = state_dir / SDK_BOUNDARY_SENTINEL_FILENAME
    temporary = state_dir / (
        f".{SDK_BOUNDARY_SENTINEL_FILENAME}.{os.getpid()}.tmp"
    )
    payload = {
        "root_sentinel": "configuration.REST_CLIENT.create_order",
        "child_sentinel": "configuration.REST_CLIENT.place_limit_order",
        "installed": installed,
        "wrapper_identity_proven": wrapper_identity_proven,
        "root_create_order_call_count": root_create_order_call_count,
        "child_place_limit_order_call_count": child_place_limit_order_call_count,
        "denied_call_count": denied_call_count,
        "root_sdk_inflight": root_sdk_inflight,
        "child_sdk_inflight": child_sdk_inflight,
        "root_create_order_maximum": SUCCESSOR_ROOT_ORDER_MAXIMUM,
        "child_place_limit_order_maximum": SUCCESSOR_CHILD_ORDER_MAXIMUM,
        "phase": phase,
        "critical_failure": bool(
            denied_call_count > 0
            or root_create_order_call_count > SUCCESSOR_ROOT_ORDER_MAXIMUM
            or child_place_limit_order_call_count
            > SUCCESSOR_CHILD_ORDER_MAXIMUM
        ),
        "error": error,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "process_id": os.getpid(),
    }
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)


def _parent_loss_reconciliation_decision(
    *,
    root_sdk_inflight: bool,
    child_sdk_inflight: bool,
    first_active_read: Sequence[Mapping[str, Any]] | None,
    second_active_read: Sequence[Mapping[str, Any]] | None,
    live_service_disable_proven: bool,
) -> str:
    """Pure fail-closed parent-loss reconciliation decision."""

    if root_sdk_inflight or child_sdk_inflight:
        return "wait_for_sdk_quiescence"
    if first_active_read is None or second_active_read is None:
        return "repeat_authoritative_active_reads"
    first_identities = [
        (row.get("client_order_id"), row.get("order_id"))
        for row in first_active_read
    ]
    second_identities = [
        (row.get("client_order_id"), row.get("order_id"))
        for row in second_active_read
    ]
    if first_identities != second_identities:
        return "repeat_authoritative_active_reads"
    if second_identities:
        return "reconcile_exact_active_order"
    if not live_service_disable_proven:
        return "retry_idempotent_service_disable"
    return "continue_monitoring_quiescent_zero"


def _parent_loss_cancel_retry_decision(
    *,
    exact_order_active: bool,
    stable_active_scope_proven: bool,
    prior_cancel_outcome: str | None,
) -> str:
    """Retry only the same idempotent cancel after a fresh active read."""

    if not exact_order_active:
        return "poll_exact_order_and_active_set"
    if not stable_active_scope_proven:
        return "wait_for_stable_active_scope_before_cancel"
    if prior_cancel_outcome == "accepted":
        return "poll_for_exact_cancel_terminal"
    require(
        prior_cancel_outcome
        in {None, "timeout_or_exception", "non_200_or_unaccepted"},
        "parent_loss_cancel_outcome_invalid",
    )
    return "issue_same_idempotent_exact_cancel"


def run_embedded_runtime_child(*, state_dir: Path, auth_file: Path) -> int:
    """Launch one canonical runtime with root and first-child SDK sentinels."""

    import runpy
    import threading

    supplied_nonce = os.environ.pop(RUNTIME_CHILD_NONCE_ENV, "")
    confirmed_plan, _, ledger_path = consume_runtime_child_authority(
        state_dir=state_dir,
        auth_file=auth_file,
        supplied_nonce=supplied_nonce,
    )
    confirmed_plan_hash = str(confirmed_plan["plan_sha256"])
    authority_parent_pid = os.getppid()
    authority_parent_start = _process_start_identity(authority_parent_pid)
    require(
        os.environ.get("COINBASE_SECRETS_MANAGER_SECRET_ID") == SECRET_ID,
        "runtime_child_secret_selector_mismatch",
    )
    require(
        os.environ.get("COINBASE_SECRETS_MANAGER_REGION") == SECRET_REGION,
        "runtime_child_secret_region_mismatch",
    )
    require(
        os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID")
        == confirmed_plan["portfolio_id"],
        "runtime_child_portfolio_environment_mismatch",
    )
    require(
        os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_LABEL")
        == PROFILE_LABEL,
        "runtime_child_profile_label_environment_mismatch",
    )
    require_clean_commit()
    sys.path.insert(0, str(ROOT))
    from tools.coinbase_live_credentials import ensure_live_coinbase_credentials

    os.environ.pop("COINBASE_API_KEY", None)
    os.environ.pop("COINBASE_API_SECRET", None)
    ensure_live_coinbase_credentials(os.environ)
    from tools.run_admin_api import apply_local_environment, parse_args

    apply_local_environment(parse_args([]))
    import configuration

    child_rest_client = configuration.get_rest_client()
    child_sdk_client = child_rest_client.get_sdk_client()
    child_sdk_client.timeout = COINBASE_SDK_TIMEOUT_SECONDS
    child_sdk_client.session.trust_env = False
    require(
        child_sdk_client.timeout == COINBASE_SDK_TIMEOUT_SECONDS,
        "coinbase_sdk_timeout_not_bounded",
    )
    require(
        child_sdk_client.session.trust_env is False,
        "coinbase_sdk_proxy_inheritance_not_disabled",
    )

    sentinel_lock = threading.Lock()
    root_create_order_calls = 0
    child_place_limit_order_calls = 0
    denied_calls = 0
    root_sdk_inflight = False
    child_sdk_inflight = False
    parent_authority_lost = threading.Event()
    original_root_create_order = child_rest_client.create_order
    original_child_place_limit_order = child_rest_client.place_limit_order

    def identities_proven() -> bool:
        return bool(
            configuration.REST_CLIENT.create_order is bounded_root_create_order
            and child_rest_client.create_order is bounded_root_create_order
            and configuration.REST_CLIENT.place_limit_order
            is bounded_child_place_limit_order
            and child_rest_client.place_limit_order
            is bounded_child_place_limit_order
        )

    def deny_sdk_call(*, phase: str, error: str) -> None:
        nonlocal denied_calls
        denied_calls += 1
        _write_sdk_boundary_sentinel_evidence(
            state_dir,
            root_create_order_call_count=root_create_order_calls,
            child_place_limit_order_call_count=child_place_limit_order_calls,
            denied_call_count=denied_calls,
            root_sdk_inflight=root_sdk_inflight,
            child_sdk_inflight=child_sdk_inflight,
            phase=phase,
            installed=True,
            wrapper_identity_proven=identities_proven(),
            error=error,
        )

    def current_attempts() -> list[dict[str, Any]]:
        return read_batch_attempt_ledger(
            ledger_path,
            confirmed_plan=confirmed_plan,
            confirmed_plan_hash=confirmed_plan_hash,
        )

    def require_controlled_child_preparation(
        exact_tuple: Mapping[str, Any],
    ) -> None:
        """Deny a generic bridge call even when it copies the exact tuple."""

        import dashboard_server

        bridge = getattr(dashboard_server, "stealth_order_bridge", None)
        manager = getattr(bridge, "stealth_manager", None) if bridge else None
        require(manager is not None, "child_sdk_manager_unavailable")
        child_id = str(exact_tuple.get("client_order_id") or "")
        state = manager._get_stealth_order(child_id)
        require(isinstance(state, dict), "child_sdk_state_missing")
        anchor_state = object_record(state.get("anchor_repricing_state_json"))
        preparation = object_record(
            anchor_state.get(
                "controlled_admin_first_child_reveal_preparation"
            )
        )
        slot = int(exact_tuple.get("batch_slot") or 0)
        roots = [
            object_record(item)
            for item in list_value(confirmed_plan.get("roots"))
        ]
        require(1 <= slot <= len(roots), "child_sdk_preparation_slot_invalid")
        root_plan = roots[slot - 1]
        approvals = object_record(root_plan.get("proof_approval_ids"))
        require(
            preparation.get("batch_id") == confirmed_plan.get("batch_id")
            and preparation.get("batch_slot") == slot
            and preparation.get("root_client_order_id")
            == root_plan.get("root_client_order_id")
            and preparation.get("stealth_order_id") == child_id
            and preparation.get("portfolio_id")
            == confirmed_plan.get("portfolio_id")
            and preparation.get("approval_snapshot_id")
            == approvals.get("child_reveal")
            == exact_tuple.get("approval_snapshot_id")
            and bool(preparation.get("admission_audit_id"))
            and bool(preparation.get("cap_guard_decision_id"))
            and bool(preparation.get("reconciliation_plan_id"))
            and bool(preparation.get("authority_id")),
            "child_sdk_controlled_route_preparation_mismatch",
        )
        require(
            str(state.get("status") or "").upper() == "HIDDEN"
            and not list_value(state.get("revealed_orders"))
            and Decimal(str(state.get("revealed_size") or "0")) == 0
            and Decimal(str(state.get("executed_size") or "0")) == 0
            and not anchor_state.get("active_placement_client_order_id")
            and not anchor_state.get("active_exchange_order_id"),
            "child_sdk_state_not_preexchange_prepared",
        )
        market = object_record(manager._get_current_market_data(PRODUCT_ID))
        market_bid = Decimal(str(market.get("bid") or "0"))
        require(
            market_bid.is_finite() and market_bid > 0,
            "child_sdk_fresh_bid_missing",
        )
        try:
            market_observed_at = datetime.fromisoformat(
                str(market.get("time") or "").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ProofFailure("child_sdk_market_timestamp_invalid") from exc
        require(
            market_observed_at.tzinfo is not None,
            "child_sdk_market_timestamp_timezone_missing",
        )
        market_age = (
            datetime.now(timezone.utc) - market_observed_at
        ).total_seconds()
        require(
            -1 <= market_age <= 30,
            "child_sdk_market_evidence_expired",
        )
        require(
            Decimal(str(exact_tuple.get("limit_price") or "0"))
            >= market_bid * CHILD_MINIMUM_BID_RATIO,
            "child_sdk_price_below_160_percent_fresh_bid",
        )

    def bounded_root_create_order(*args: Any, **kwargs: Any) -> Any:
        nonlocal root_create_order_calls, root_sdk_inflight
        with sentinel_lock:
            try:
                require(
                    not parent_authority_lost.is_set(),
                    "root_parent_authority_lost",
                )
                require_plan_unexpired(
                    confirmed_plan,
                    blocker="root_plan_expired_at_sdk_boundary",
                )
                exact_tuple = authorized_sdk_tuple_for_call(
                    current_attempts(),
                    attempt_kind="root",
                    prior_call_count=root_create_order_calls,
                )
                validate_canonical_root_create_order_call(
                    args,
                    kwargs,
                    exact_tuple=exact_tuple,
                )
            except ProofFailure as exc:
                deny_sdk_call(
                    phase="blocked_root_create_order",
                    error=str(exc),
                )
                raise RuntimeError(str(exc)) from exc
            root_create_order_calls += 1
            root_sdk_inflight = True
            _write_sdk_boundary_sentinel_evidence(
                state_dir,
                root_create_order_call_count=root_create_order_calls,
                child_place_limit_order_call_count=child_place_limit_order_calls,
                denied_call_count=denied_calls,
                root_sdk_inflight=True,
                child_sdk_inflight=child_sdk_inflight,
                phase="root_create_order_entered",
                installed=True,
                wrapper_identity_proven=identities_proven(),
            )
        try:
            require_plan_unexpired(
                confirmed_plan,
                blocker="root_plan_expired_before_sdk_io",
            )
            return original_root_create_order(*args, **kwargs)
        finally:
            with sentinel_lock:
                root_sdk_inflight = False
                _write_sdk_boundary_sentinel_evidence(
                    state_dir,
                    root_create_order_call_count=root_create_order_calls,
                    child_place_limit_order_call_count=(
                        child_place_limit_order_calls
                    ),
                    denied_call_count=denied_calls,
                    root_sdk_inflight=False,
                    child_sdk_inflight=child_sdk_inflight,
                    phase="root_create_order_returned",
                    installed=True,
                    wrapper_identity_proven=identities_proven(),
                )

    def bounded_child_place_limit_order(*args: Any, **kwargs: Any) -> Any:
        nonlocal child_place_limit_order_calls, child_sdk_inflight
        with sentinel_lock:
            try:
                require(
                    not parent_authority_lost.is_set(),
                    "child_parent_authority_lost",
                )
                require_plan_unexpired(
                    confirmed_plan,
                    blocker="child_plan_expired_at_sdk_boundary",
                )
                exact_tuple = authorized_sdk_tuple_for_call(
                    current_attempts(),
                    attempt_kind="child",
                    prior_call_count=child_place_limit_order_calls,
                )
                require_controlled_child_preparation(exact_tuple)
                validate_canonical_child_place_limit_order_call(
                    args,
                    kwargs,
                    exact_tuple=exact_tuple,
                )
            except ProofFailure as exc:
                deny_sdk_call(
                    phase="blocked_child_place_limit_order",
                    error=str(exc),
                )
                raise RuntimeError(str(exc)) from exc
            child_place_limit_order_calls += 1
            child_sdk_inflight = True
            _write_sdk_boundary_sentinel_evidence(
                state_dir,
                root_create_order_call_count=root_create_order_calls,
                child_place_limit_order_call_count=child_place_limit_order_calls,
                denied_call_count=denied_calls,
                root_sdk_inflight=root_sdk_inflight,
                child_sdk_inflight=True,
                phase="child_place_limit_order_entered",
                installed=True,
                wrapper_identity_proven=identities_proven(),
            )
        try:
            require_plan_unexpired(
                confirmed_plan,
                blocker="child_plan_expired_before_sdk_io",
            )
            return original_child_place_limit_order(*args, **kwargs)
        finally:
            with sentinel_lock:
                child_sdk_inflight = False
                _write_sdk_boundary_sentinel_evidence(
                    state_dir,
                    root_create_order_call_count=root_create_order_calls,
                    child_place_limit_order_call_count=(
                        child_place_limit_order_calls
                    ),
                    denied_call_count=denied_calls,
                    root_sdk_inflight=root_sdk_inflight,
                    child_sdk_inflight=False,
                    phase="child_place_limit_order_returned",
                    installed=True,
                    wrapper_identity_proven=identities_proven(),
                )

    configuration.REST_CLIENT.create_order = bounded_root_create_order
    configuration.REST_CLIENT.place_limit_order = bounded_child_place_limit_order
    require(identities_proven(), "sdk_boundary_sentinel_identity_mismatch")

    from core.action_condition_guard import (
        get_action_condition_guard_policy,
        normalize_action_guard_wallet_policy,
    )
    from core.enums import OrderSide, ProductCapability, SpotFollowUpTrigger
    from core.product_capability import evaluate_product_capability
    from core.spot_follow_up_policy import evaluate_spot_follow_up_policy

    planning = evaluate_product_capability(
        product_id=PRODUCT_ID,
        capability=ProductCapability.STEALTH_PLANNING,
    )
    filled = evaluate_product_capability(
        product_id=PRODUCT_ID,
        capability=ProductCapability.FILLED_FOLLOW_UP,
        allow_conditional=True,
    )
    partial = evaluate_product_capability(
        product_id=PRODUCT_ID,
        capability=ProductCapability.PARTIAL_FILL_FOLLOW_UP,
        allow_conditional=True,
    )
    cancelled = evaluate_product_capability(
        product_id=PRODUCT_ID,
        capability=ProductCapability.CANCELLED_FOLLOW_UP,
        allow_conditional=True,
    )
    generic_reveal = evaluate_product_capability(
        product_id=PRODUCT_ID,
        capability=ProductCapability.STEALTH_REVEAL,
    )
    require(planning.allowed, "controlled_batch_stealth_planning_not_enabled")
    require(
        filled.allowed and filled.mode == "conditional",
        "controlled_batch_follow_up_not_conditional",
    )
    require(
        partial.mode == "disabled",
        "controlled_batch_partial_follow_up_not_disabled",
    )
    require(
        cancelled.mode == "disabled",
        "controlled_batch_cancelled_follow_up_not_disabled",
    )
    require(
        generic_reveal.mode == "disabled" and not generic_reveal.allowed,
        "controlled_batch_generic_child_reveal_not_disabled",
    )
    follow_up_policy = evaluate_spot_follow_up_policy(
        product_id=PRODUCT_ID,
        source_side=OrderSide.BUY.value,
        follow_up_side=OrderSide.SELL.value,
        trigger=SpotFollowUpTrigger.FILLED,
    )
    require(
        follow_up_policy.allowed and follow_up_policy.intent == "exit",
        "controlled_batch_exit_follow_up_not_enabled",
    )
    wallet_policy = normalize_action_guard_wallet_policy(
        get_action_condition_guard_policy()
    )
    require(
        wallet_policy.get("enabled") is True,
        "controlled_batch_wallet_guard_not_enabled",
    )
    require(
        wallet_policy.get("check_follow_up_planning") is False,
        "controlled_batch_fill_backed_planning_not_enabled",
    )
    require(
        wallet_policy.get("fail_open_on_fetch_error") is False,
        "controlled_batch_wallet_guard_fail_open",
    )
    replacement_policy = getattr(configuration.ORDERBOOK, "should_replace", {})
    require(
        isinstance(replacement_policy, Mapping)
        and replacement_policy.get("FILLED") is True,
        "controlled_batch_filled_replacement_disabled",
    )

    def parent_loss_headers(
        *,
        idempotency_key: str,
        operator_intent: str,
        correlation_id: str,
        role: str,
    ) -> dict[str, str]:
        return {
            "Authorization": (
                f"Bearer {os.environ['COINBASE_ADMIN_API_BEARER_TOKEN']}"
            ),
            "X-Admin-Actor": ACTOR_ID,
            "X-Admin-Roles": role,
            "Idempotency-Key": idempotency_key,
            "X-Operator-Intent": operator_intent,
            "X-Correlation-Id": correlation_id,
        }

    def post_parent_loss_admin_command(
        path: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        session = requests.Session()
        session.trust_env = False
        response = session.post(
            f"{BASE_URL}{path}",
            headers=dict(headers),
            json=dict(body),
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text[:1000]}
        return {
            "http_status": response.status_code,
            "payload": object_record(payload),
        }

    def handle_parent_authority_loss() -> None:
        """Deny placements and continuously reconcile until quiescent."""

        parent_authority_lost.set()
        report_path = state_dir / "parent-authority-loss.json"
        report: dict[str, Any] = {
            "status": "parent_authority_lost_reconciliation_only",
            "parent_pid": authority_parent_pid,
            "parent_start_identity": authority_parent_start,
            "new_sdk_placements_denied": True,
            "runtime_preserved": True,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        cancel_outcomes: dict[str, str] = {}
        cancel_attempt_counts: dict[str, int] = {}
        terminal_attempt_evidence: dict[str, dict[str, Any]] = {}
        operator_alert_emitted = False
        disable_attempt_count = 0

        def exact_transmitted_attempt_state(
            attempt: Mapping[str, Any],
        ) -> dict[str, Any]:
            """Read and validate one SDK-entered exact order identity."""

            from application.admin_api.command_service import (
                exact_coinbase_order_readback,
            )

            client_order_id = str(attempt["client_order_id"])
            readback = exact_coinbase_order_readback(
                child_rest_client,
                client_order_id=client_order_id,
                product_id=PRODUCT_ID,
            )
            if readback.get("confirmed_absent") is True:
                return {
                    "attempt_kind": attempt["attempt_kind"],
                    "client_order_id": client_order_id,
                    "status": "VISIBILITY_PENDING",
                    "confirmed_absent": True,
                    "exact_identity_match": False,
                    "exact_order_active": False,
                    "terminal_proven": False,
                }
            require(
                readback.get("exact_identity_match") is True,
                "parent_loss_exact_order_identity_unproven",
            )
            matched = object_record(readback.get("matched_order"))
            exchange_order_id = str(matched.get("order_id") or "")
            require(
                bool(exchange_order_id),
                "parent_loss_exact_exchange_order_id_missing",
            )
            attempt_kind = str(attempt["attempt_kind"])
            if attempt_kind == "root":
                root_plan = next(
                    object_record(item)
                    for item in list_value(confirmed_plan.get("roots"))
                    if item.get("root_client_order_id") == client_order_id
                )
                validated = _validate_exact_coinbase_fok_order(
                    matched,
                    expected_exchange_order_id=exchange_order_id,
                    expected_client_order_id=client_order_id,
                    expected_portfolio_id=str(
                        confirmed_plan["portfolio_id"]
                    ),
                    expected_order_body=object_record(root_plan["order"]),
                )
                expected_size = Decimal(
                    str(object_record(root_plan["order"])["base_size"])
                )
            else:
                require(
                    attempt_kind == "child",
                    "parent_loss_attempt_kind_invalid",
                )
                validated = _validate_exact_coinbase_gtc_child_order(
                    matched,
                    expected_exchange_order_id=exchange_order_id,
                    expected_portfolio_id=str(
                        confirmed_plan["portfolio_id"]
                    ),
                    expected_child_tuple=object_record(
                        attempt["exact_order_tuple"]
                    ),
                )
                expected_size = Decimal(
                    str(
                        object_record(attempt["exact_order_tuple"])[
                            "base_size"
                        ]
                    )
                )
            status = str(validated.get("status") or "").upper()
            filled_size = Decimal(
                str(validated.get("filled_size") or "0")
            )
            require(
                filled_size.is_finite() and filled_size >= 0,
                "parent_loss_exact_order_filled_size_invalid",
            )
            exact_active = status in SPOT_NONTERMINAL_STATUSES
            terminal_proven = False
            terminal_kind: str | None = None
            critical_failure: str | None = None
            if attempt_kind == "root":
                if status == "FILLED" and filled_size == expected_size:
                    terminal_proven = True
                    terminal_kind = "root_filled"
                elif (
                    status in NO_FILL_TERMINAL_STATUSES
                    and filled_size == 0
                ):
                    terminal_proven = True
                    terminal_kind = "root_terminal_no_fill"
                elif filled_size > 0:
                    critical_failure = "parent_loss_root_partial_fill"
                    if status in TERMINAL_STATUSES:
                        terminal_proven = True
                        terminal_kind = "root_terminal_partial_fill"
            else:
                if (
                    status in {"CANCELLED", "CANCELED"}
                    and filled_size == 0
                ):
                    terminal_proven = True
                    terminal_kind = "child_exact_cancelled"
                elif (
                    status in NO_FILL_TERMINAL_STATUSES
                    and filled_size == 0
                ):
                    terminal_proven = True
                    terminal_kind = "child_terminal_no_fill"
                elif status == "FILLED":
                    terminal_proven = True
                    terminal_kind = "child_terminal_filled"
                    critical_failure = "parent_loss_child_fill_detected"
                elif filled_size > 0:
                    critical_failure = (
                        "parent_loss_child_partial_fill_detected"
                    )
            return {
                "attempt_kind": attempt_kind,
                "client_order_id": client_order_id,
                "exchange_order_id": exchange_order_id,
                "status": status,
                "filled_size": decimal_text(filled_size),
                "expected_size": decimal_text(expected_size),
                "confirmed_absent": False,
                "exact_identity_match": True,
                "exact_order_active": exact_active,
                "terminal_proven": terminal_proven,
                "terminal_kind": terminal_kind,
                "critical_failure": critical_failure,
            }

        def post_exact_parent_loss_cancel(
            attempt: Mapping[str, Any],
        ) -> dict[str, Any]:
            """Post only the deterministic cancel bound to one exact attempt."""

            slot = int(attempt["batch_slot"])
            client_order_id = str(attempt["client_order_id"])
            attempt_kind = str(attempt["attempt_kind"])
            if attempt_kind == "child":
                root_id = str(attempt["root_client_order_id"])
                return post_parent_loss_admin_command(
                    f"/stealth/orders/{client_order_id}/cancel",
                    headers=parent_loss_headers(
                        idempotency_key=(
                            f"{confirmed_plan['batch_id']}-child-"
                            f"{slot}-cancel"
                        ),
                        operator_intent=(
                            CONTROLLED_CHILD_CANCEL_OPERATOR_INTENT
                        ),
                        correlation_id=(
                            f"corr-{confirmed_plan['batch_id']}-child-"
                            f"{slot}-cancel"
                        ),
                        role=COMMAND_ROLE,
                    ),
                    body={
                        "reason": (
                            f"controlled batch slot {slot} first-child "
                            "exact cancel"
                        ),
                        "manual_live_acknowledgement": True,
                        "expected_root_client_order_id": root_id,
                        "controlled_batch_id": confirmed_plan["batch_id"],
                        "controlled_batch_slot": slot,
                    },
                )
            require(
                attempt_kind == "root",
                "parent_loss_cancel_attempt_kind_invalid",
            )
            return post_parent_loss_admin_command(
                f"/orders/{client_order_id}/cancel",
                headers=parent_loss_headers(
                    idempotency_key=(
                        f"{confirmed_plan['batch_id']}-root-{slot}-cancel"
                    ),
                    operator_intent="controlled_batch_root_safety_cancel",
                    correlation_id=(
                        f"corr-{confirmed_plan['batch_id']}-root-"
                        f"{slot}-cancel"
                    ),
                    role=COMMAND_ROLE,
                ),
                body={
                    "reason": (
                        f"controlled_batch_slot_{slot}_root_safety_cancel"
                    ),
                    "manual_live_acknowledgement": True,
                },
            )

        def attempt_parent_loss_service_disable() -> None:
            nonlocal disable_attempt_count
            if report.get("live_service_disable_proven") is True:
                return
            disable_attempt_count += 1
            try:
                disable_result = post_parent_loss_admin_command(
                    "/admin/live-execution/service-decisions",
                    headers=parent_loss_headers(
                        idempotency_key=(
                            f"{confirmed_plan['batch_id']}-"
                            "parent-loss-disable"
                        ),
                        operator_intent=(
                            "disable_controlled_batch_after_"
                            "parent_authority_loss"
                        ),
                        correlation_id=(
                            f"corr-{confirmed_plan['batch_id']}-"
                            "parent-loss-disable"
                        ),
                        role=ADMIN_ROLE,
                    ),
                    body={
                        "decision_id": (
                            "parent-loss-disable-"
                            f"{confirmed_plan['batch_id']}"
                        ),
                        "status": "blocked",
                        "requested_service_status": "live_disabled",
                        "service_enabled": False,
                        "target_module_id": "spot_operations",
                        "account_family": "coinbase_retail_test",
                        "venue_scope": "coinbase_advanced_trade",
                        "intx_applicability": "not_applicable",
                        "product_scope": [PRODUCT_ID],
                        "deployment_ref": EXPECTED_COMMIT,
                        "runtime_configuration_ref": str(state_dir),
                        "decision_reason": (
                            "Disable live service because the exact parent "
                            "process authority was lost."
                        ),
                        "live_coinbase_execution_approved": False,
                        "max_submitted_notional_usdc": "0",
                        "max_executed_notional_usdc": "0",
                    },
                )
                report["live_service_disable"] = disable_result
                disable_payload = object_record(
                    disable_result.get("payload")
                )
                disable_decision = object_record(
                    disable_payload.get("decision")
                )
                report["live_service_disable_proven"] = bool(
                    disable_result.get("http_status") == 200
                    and disable_decision.get("service_enabled") is False
                )
                report["live_service_disable_attempt_count"] = (
                    disable_attempt_count
                )
                report.pop("live_service_disable_error", None)
            except Exception as exc:
                report["live_service_disable_proven"] = False
                report["live_service_disable_error"] = (
                    f"{type(exc).__name__}:{exc}"
                )

        while True:
            with sentinel_lock:
                sdk_inflight = root_sdk_inflight or child_sdk_inflight
                report["root_sdk_inflight_after_wait"] = root_sdk_inflight
                report["child_sdk_inflight_after_wait"] = child_sdk_inflight
                report["root_create_order_call_count"] = (
                    root_create_order_calls
                )
                report["child_place_limit_order_call_count"] = (
                    child_place_limit_order_calls
                )
                report["denied_sdk_call_count"] = denied_calls
            attempt_parent_loss_service_disable()
            if sdk_inflight:
                report["status"] = (
                    "parent_authority_lost_waiting_for_sdk_quiescence"
                )
                report["sdk_quiescence_proven"] = False
                report["updated_at"] = datetime.now(timezone.utc).isoformat()
                try:
                    _replace_owner_only_json(report_path, report)
                except Exception:
                    pass
                time.sleep(0.25)
                continue

            report["status"] = "parent_authority_lost_reconciliation_only"
            report["sdk_quiescence_proven"] = True
            active_orders: list[dict[str, Any]] | None = None
            try:
                first_read = read_authoritative_spot_nonterminal_orders(
                    child_rest_client,
                    expected_portfolio_id=str(
                        confirmed_plan["portfolio_id"]
                    ),
                )
                time.sleep(0.5)
                second_read = read_authoritative_spot_nonterminal_orders(
                    child_rest_client,
                    expected_portfolio_id=str(
                        confirmed_plan["portfolio_id"]
                    ),
                )
                require(
                    [
                        (row.get("client_order_id"), row.get("order_id"))
                        for row in first_read
                    ]
                    == [
                        (row.get("client_order_id"), row.get("order_id"))
                        for row in second_read
                    ],
                    "parent_loss_active_order_read_not_stable",
                )
                active_orders = second_read
                report["authoritative_active_order_read_proven"] = True
                report["authoritative_active_orders_before_cancel"] = (
                    active_orders
                )
                report.pop("authoritative_active_order_read_error", None)
            except Exception as exc:
                report["authoritative_active_order_read_proven"] = False
                report["authoritative_active_order_read_error"] = (
                    f"{type(exc).__name__}:{exc}"
                )

            transmitted_attempts: list[dict[str, Any]] = []
            attempt_by_client_id: dict[str, dict[str, Any]] = {}
            exact_attempt_states: dict[str, dict[str, Any]] = {}
            try:
                ledger_attempts = current_attempts()
                transmitted_roots = [
                    object_record(record)
                    for record in ledger_attempts
                    if record.get("attempt_kind") == "root"
                ][:root_create_order_calls]
                transmitted_children = [
                    object_record(record)
                    for record in ledger_attempts
                    if record.get("attempt_kind") == "child"
                ][:child_place_limit_order_calls]
                require(
                    len(transmitted_roots) == root_create_order_calls,
                    "parent_loss_root_transmission_ledger_mismatch",
                )
                require(
                    len(transmitted_children)
                    == child_place_limit_order_calls,
                    "parent_loss_child_transmission_ledger_mismatch",
                )
                transmitted_attempts = sorted(
                    transmitted_roots + transmitted_children,
                    key=lambda record: int(record["sequence"]),
                )
                attempt_by_client_id = {
                    str(record["client_order_id"]): record
                    for record in transmitted_attempts
                }
                require(
                    len(attempt_by_client_id) == len(transmitted_attempts),
                    "parent_loss_transmitted_attempt_identity_duplicate",
                )
                for attempt in transmitted_attempts:
                    client_order_id = str(attempt["client_order_id"])
                    if client_order_id in terminal_attempt_evidence:
                        exact_attempt_states[client_order_id] = dict(
                            terminal_attempt_evidence[client_order_id]
                        )
                        continue
                    try:
                        state = exact_transmitted_attempt_state(attempt)
                    except Exception as exc:
                        state = {
                            "attempt_kind": attempt["attempt_kind"],
                            "client_order_id": client_order_id,
                            "status": "EXACT_READ_PENDING",
                            "exact_order_active": False,
                            "terminal_proven": False,
                            "read_error": f"{type(exc).__name__}:{exc}",
                        }
                    exact_attempt_states[client_order_id] = state
                    if state.get("terminal_proven") is True:
                        terminal_attempt_evidence[client_order_id] = dict(
                            state
                        )
                report["transmitted_attempt_count"] = len(
                    transmitted_attempts
                )
                report["exact_transmitted_attempt_states"] = (
                    exact_attempt_states
                )
                report["terminal_transmitted_attempt_count"] = len(
                    terminal_attempt_evidence
                )
                report.pop("transmitted_attempt_reconciliation_error", None)
            except Exception as exc:
                report["transmitted_attempt_reconciliation_error"] = (
                    f"{type(exc).__name__}:{exc}"
                )

            active_client_ids = {
                str(row.get("client_order_id") or "")
                for row in (active_orders or [])
                if str(row.get("client_order_id") or "")
            }
            active_client_ids.update(
                client_order_id
                for client_order_id, state in exact_attempt_states.items()
                if state.get("exact_order_active") is True
            )
            active_client_ids = {
                client_order_id
                for client_order_id in active_client_ids
                if exact_attempt_states.get(client_order_id, {}).get(
                    "terminal_proven"
                )
                is not True
            }
            unknown_active_ids = sorted(
                active_client_ids - set(attempt_by_client_id)
            )
            exact_active_ids = sorted(
                active_client_ids & set(attempt_by_client_id)
            )
            report["unknown_active_client_order_ids"] = unknown_active_ids
            report["exact_active_client_order_ids"] = exact_active_ids
            if unknown_active_ids or len(exact_active_ids) > 1:
                report["exact_admin_cancel_error"] = (
                    "parent_loss_active_order_not_one_exact_attempt:"
                    f"unknown={unknown_active_ids}:exact={exact_active_ids}"
                )
            elif len(exact_active_ids) == 1:
                active_client_id = exact_active_ids[0]
                prior_outcome = cancel_outcomes.get(active_client_id)
                cancel_decision = _parent_loss_cancel_retry_decision(
                    exact_order_active=True,
                    stable_active_scope_proven=bool(
                        report.get(
                            "authoritative_active_order_read_proven"
                        )
                        is True
                    ),
                    prior_cancel_outcome=prior_outcome,
                )
                report["exact_admin_cancel_decision"] = cancel_decision
                if cancel_decision == "issue_same_idempotent_exact_cancel":
                    cancel_attempt_counts[active_client_id] = (
                        cancel_attempt_counts.get(active_client_id, 0) + 1
                    )
                    cancel_attempt_number = cancel_attempt_counts[
                        active_client_id
                    ]
                    try:
                        result = post_exact_parent_loss_cancel(
                            attempt_by_client_id[active_client_id]
                        )
                        cancel_payload = object_record(
                            result.get("payload")
                        )
                        cancel_accepted = bool(
                            result.get("http_status") == 200
                            and cancel_payload.get("status") == "accepted"
                        )
                        outcome = (
                            "accepted"
                            if cancel_accepted
                            else "non_200_or_unaccepted"
                        )
                        cancel_outcomes[active_client_id] = outcome
                        report["exact_admin_cancel_last_result"] = {
                            "client_order_id": active_client_id,
                            "attempt_number": cancel_attempt_number,
                            "same_idempotent_cancel": True,
                            "outcome": outcome,
                            **result,
                        }
                        report.pop("exact_admin_cancel_error", None)
                    except Exception as exc:
                        cancel_outcomes[active_client_id] = (
                            "timeout_or_exception"
                        )
                        report["exact_admin_cancel_error"] = (
                            f"{type(exc).__name__}:{exc}"
                        )
                        report["exact_admin_cancel_last_result"] = {
                            "client_order_id": active_client_id,
                            "attempt_number": cancel_attempt_number,
                            "same_idempotent_cancel": True,
                            "outcome": "timeout_or_exception",
                        }
            else:
                report["exact_admin_cancel_decision"] = (
                    "poll_exact_order_and_active_set"
                )
            report["exact_admin_cancel_attempt_counts"] = dict(
                cancel_attempt_counts
            )
            report["exact_admin_cancel_outcomes"] = dict(cancel_outcomes)

            remaining_first: list[dict[str, Any]] | None = None
            remaining_second: list[dict[str, Any]] | None = None
            try:
                remaining_first = read_authoritative_spot_nonterminal_orders(
                    child_rest_client,
                    expected_portfolio_id=str(
                        confirmed_plan["portfolio_id"]
                    ),
                )
                time.sleep(0.5)
                remaining_second = read_authoritative_spot_nonterminal_orders(
                    child_rest_client,
                    expected_portfolio_id=str(
                        confirmed_plan["portfolio_id"]
                    ),
                )
                require(
                    [
                        (row.get("client_order_id"), row.get("order_id"))
                        for row in remaining_first
                    ]
                    == [
                        (row.get("client_order_id"), row.get("order_id"))
                        for row in remaining_second
                    ],
                    "parent_loss_final_active_order_read_not_stable",
                )
                report[
                    "authoritative_active_orders_after_reconciliation"
                ] = remaining_second
                report["authoritative_active_zero_after_reconciliation"] = (
                    not remaining_second
                )
                report.pop("final_active_order_read_error", None)
            except Exception as exc:
                report["authoritative_active_zero_after_reconciliation"] = (
                    False
                )
                report["final_active_order_read_error"] = (
                    f"{type(exc).__name__}:{exc}"
                )

            reconciliation_decision = _parent_loss_reconciliation_decision(
                root_sdk_inflight=False,
                child_sdk_inflight=False,
                first_active_read=remaining_first,
                second_active_read=remaining_second,
                live_service_disable_proven=bool(
                    report.get("live_service_disable_proven") is True
                ),
            )
            report["reconciliation_decision"] = reconciliation_decision
            quiescent_zero_observed = (
                reconciliation_decision
                == "continue_monitoring_quiescent_zero"
            )
            critical_attempt_failures = {
                client_order_id: state.get("critical_failure")
                for client_order_id, state in exact_attempt_states.items()
                if state.get("critical_failure")
            }
            all_transmitted_attempts_terminal = bool(
                len(terminal_attempt_evidence) == len(transmitted_attempts)
            )
            retry_pending = any(
                cancel_outcomes.get(client_order_id)
                in {"timeout_or_exception", "non_200_or_unaccepted"}
                for client_order_id in exact_active_ids
            )
            operator_reconciliation_required = bool(
                unknown_active_ids
                or len(exact_active_ids) > 1
                or critical_attempt_failures
            )
            report["operator_reconciliation_required"] = (
                operator_reconciliation_required
            )
            report["critical_attempt_failures"] = critical_attempt_failures
            report["all_transmitted_attempts_terminal"] = (
                all_transmitted_attempts_terminal
            )
            report["automatic_cancel_retry_authorized"] = retry_pending
            report["automatic_cancel_retry_scope"] = (
                "same_idempotency_key_exact_cancel_only"
                if retry_pending
                else "none"
            )
            if operator_reconciliation_required:
                report["status"] = (
                    "parent_authority_lost_operator_reconciliation_required"
                )
                if not operator_alert_emitted:
                    print(
                        json.dumps(
                            {
                                "status": report["status"],
                                "state_dir": str(state_dir),
                                "evidence_path": str(report_path),
                                "runtime_preserved": True,
                                "automatic_cancel_retry_authorized": (
                                    retry_pending
                                ),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                    operator_alert_emitted = True
            elif retry_pending:
                report["status"] = (
                    "parent_authority_lost_retrying_same_idempotent_cancel"
                )
            elif exact_active_ids:
                report["status"] = (
                    "parent_authority_lost_polling_exact_cancel_terminal"
                )
            elif (
                quiescent_zero_observed
                and all_transmitted_attempts_terminal
            ):
                report["status"] = (
                    "parent_authority_lost_terminal_monitoring_"
                    "runtime_preserved"
                )
            elif quiescent_zero_observed:
                report["status"] = (
                    "parent_authority_lost_monitoring_runtime_preserved"
                )
            else:
                report["status"] = (
                    "parent_authority_lost_reconciliation_only"
                )
            report["updated_at"] = datetime.now(timezone.utc).isoformat()
            try:
                _replace_owner_only_json(report_path, report)
            except Exception:
                pass
            time.sleep(0.5)

    def monitor_parent_authority() -> None:
        while True:
            time.sleep(0.25)
            try:
                current_start = _process_start_identity(authority_parent_pid)
            except Exception:
                current_start = ""
            if current_start != authority_parent_start:
                handle_parent_authority_loss()
                return

    require(
        _process_start_identity(authority_parent_pid)
        == authority_parent_start,
        "runtime_parent_authority_lost_before_main",
    )
    threading.Thread(
        target=monitor_parent_authority,
        name="controlled-batch-parent-authority-watchdog",
        daemon=True,
    ).start()

    _write_sdk_boundary_sentinel_evidence(
        state_dir,
        root_create_order_call_count=0,
        child_place_limit_order_call_count=0,
        denied_call_count=0,
        phase="installed_before_main",
        installed=True,
        wrapper_identity_proven=True,
    )
    try:
        runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
    finally:
        with sentinel_lock:
            _write_sdk_boundary_sentinel_evidence(
                state_dir,
                root_create_order_call_count=root_create_order_calls,
                child_place_limit_order_call_count=child_place_limit_order_calls,
                denied_call_count=denied_calls,
                root_sdk_inflight=root_sdk_inflight,
                child_sdk_inflight=child_sdk_inflight,
                phase="runtime_exited",
                installed=True,
                wrapper_identity_proven=identities_proven(),
                error=(
                    "unauthorized_sdk_order_call"
                    if denied_calls
                    else None
                ),
            )
    return 0


class AdminRuntime:
    def __init__(
        self,
        *,
        portfolio_id: str,
        confirmed_plan: Mapping[str, Any],
        confirmed_plan_hash: str,
        global_batch_marker: Path,
        attempt_ledger_path: Path,
    ) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.state_dir = (
            ROOT
            / "artifacts"
            / f"controlled-root-child-batch-{stamp}-{uuid4().hex[:8]}"
        )
        self.state_dir.mkdir(parents=True, mode=0o700)
        expected_marker, expected_ledger = batch_registry_paths(
            str(confirmed_plan.get("batch_id") or "")
        )
        require(
            global_batch_marker == expected_marker,
            "runtime_global_batch_marker_path_mismatch",
        )
        require(
            attempt_ledger_path == expected_ledger,
            "runtime_attempt_ledger_path_mismatch",
        )
        marker_payload, marker_raw = _read_owner_only_json(
            global_batch_marker,
            blocker_prefix="runtime_global_batch_marker",
            maximum_size=100_000,
        )
        confirmed_runner_sha256 = str(confirmed_plan.get("runner_sha256") or "")
        require(
            marker_payload.get("approval_id") == confirmed_plan.get("approval_id"),
            "runtime_global_batch_marker_approval_mismatch",
        )
        require(
            marker_payload.get("plan_sha256") == confirmed_plan_hash,
            "runtime_global_batch_marker_plan_hash_mismatch",
        )
        require(
            marker_payload.get("runner_sha256") == confirmed_runner_sha256,
            "runtime_global_batch_marker_runner_hash_mismatch",
        )
        require(
            marker_payload.get("attempt_ledger_path")
            == str(attempt_ledger_path),
            "runtime_global_batch_marker_ledger_mismatch",
        )
        self.confirmed_plan = dict(confirmed_plan)
        self.confirmed_plan_hash = confirmed_plan_hash
        self.global_batch_marker = global_batch_marker
        self.attempt_ledger_path = attempt_ledger_path
        self.child_nonce = secrets.token_urlsafe(48)
        self.child_auth_file = self.state_dir / RUNTIME_CHILD_AUTH_FILENAME
        parent_pid = os.getpid()
        authority_payload = build_runtime_child_authority_payload(
            state_dir=self.state_dir,
            auth_file=self.child_auth_file,
            global_batch_marker=global_batch_marker,
            global_batch_marker_sha256=hashlib.sha256(marker_raw).hexdigest(),
            attempt_ledger_path=attempt_ledger_path,
            confirmed_plan=confirmed_plan,
            confirmed_plan_hash=confirmed_plan_hash,
            confirmed_runner_sha256=confirmed_runner_sha256,
            parent_pid=parent_pid,
            parent_start_identity=_process_start_identity(parent_pid),
            nonce=self.child_nonce,
        )
        self.child_authority_sha256 = _canonical_json_sha256(authority_payload)
        _write_owner_only_exclusive_json(
            self.child_auth_file,
            authority_payload,
            exists_blocker="runtime_child_authority_already_exists",
        )
        self.token = secrets.token_urlsafe(48)
        self.portfolio_id = portfolio_id
        self.session = requests.Session()
        self.session.trust_env = False
        self.process: subprocess.Popen[Any] | None = None
        self.log_handle: Any | None = None
        self.exchange_safe_to_shutdown = True
        self.exchange_order_observed = False
        self.live_service_enable_attempted = False
        self.live_service_may_be_enabled = False
        self.live_service_disable_attempted = False
        self.live_service_disable_proven = False

    def headers(
        self,
        *,
        idempotency_key: str | None = None,
        operator_intent: str | None = None,
        role: str = ADMIN_ROLE,
        correlation_id: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Admin-Actor": ACTOR_ID,
            "X-Admin-Roles": role,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if operator_intent:
            headers["X-Operator-Intent"] = operator_intent
        if idempotency_key or operator_intent:
            headers["X-Correlation-Id"] = correlation_id or f"corr-{uuid4()}"
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        expected: set[int] | None = None,
        timeout: int = HTTP_TIMEOUT_SECONDS,
    ) -> tuple[int, dict[str, Any], Mapping[str, str]]:
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        response = self.session.request(
            method,
            url,
            headers=dict(headers or {}),
            json=dict(body) if body is not None else None,
            params=dict(params) if params is not None else None,
            timeout=timeout,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text[:1000]}
        if expected is not None and response.status_code not in expected:
            raise ProofFailure(
                f"http_status_unexpected:{method}:{path}:{response.status_code}:"
                f"{json.dumps(payload, sort_keys=True, default=str)[:2000]}"
            )
        return response.status_code, object_record(payload), response.headers

    def sdk_boundary_sentinel(
        self,
        *,
        expected_root_create_order_calls: set[int] | None = None,
        expected_child_place_limit_order_calls: set[int] | None = None,
    ) -> dict[str, Any]:
        """Read and fail closed on both in-child SDK order sentinels."""

        path = self.state_dir / SDK_BOUNDARY_SENTINEL_FILENAME
        require(
            path.is_file() and not path.is_symlink(),
            "sdk_boundary_sentinel_missing",
        )
        metadata = path.stat()
        require(
            metadata.st_uid == os.getuid(),
            "sdk_boundary_sentinel_owner_mismatch",
        )
        require(
            metadata.st_mode & 0o077 == 0,
            "sdk_boundary_sentinel_permissions_too_broad",
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        require(isinstance(payload, dict), "sdk_boundary_sentinel_malformed")
        evidence = dict(payload)
        require(
            evidence.get("installed") is True,
            "sdk_boundary_sentinel_not_installed",
        )
        require(
            evidence.get("wrapper_identity_proven") is True,
            "sdk_boundary_sentinel_identity_unproven",
        )
        root_create_calls = int(
            evidence.get("root_create_order_call_count") or 0
        )
        child_place_calls = int(
            evidence.get("child_place_limit_order_call_count") or 0
        )
        require(
            0 <= root_create_calls <= SUCCESSOR_ROOT_ORDER_MAXIMUM,
            "critical_root_create_order_count_exceeded",
        )
        require(
            0 <= child_place_calls <= SUCCESSOR_CHILD_ORDER_MAXIMUM,
            "critical_child_place_limit_order_count_exceeded",
        )
        require(
            int(evidence.get("denied_call_count") or 0) == 0,
            "critical_unauthorized_sdk_order_call_attempted",
        )
        require(
            evidence.get("root_sdk_inflight") is False,
            "root_sdk_call_not_quiescent",
        )
        require(
            evidence.get("child_sdk_inflight") is False,
            "child_sdk_call_not_quiescent",
        )
        if expected_root_create_order_calls is not None:
            require(
                root_create_calls in expected_root_create_order_calls,
                "root_create_order_count_mismatch",
            )
        if expected_child_place_limit_order_calls is not None:
            require(
                child_place_calls in expected_child_place_limit_order_calls,
                "child_place_limit_order_count_mismatch",
            )
        return evidence

    def start(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "COINBASE_SECRETS_MANAGER_SECRET_ID": SECRET_ID,
                "COINBASE_SECRETS_MANAGER_REGION": SECRET_REGION,
                "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID": self.portfolio_id,
                "COINBASE_ADMIN_API_SPOT_PORTFOLIO_LABEL": PROFILE_LABEL,
                "COINBASE_ADMIN_API_EMBEDDED_ENABLED": "1",
                "COINBASE_ADMIN_API_EMBEDDED_HOST": "127.0.0.1",
                "COINBASE_ADMIN_API_EMBEDDED_PORT": str(PORT),
                "COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED": "1",
                "COINBASE_ADMIN_API_AUTH_MODE": "bootstrap_bearer",
                "COINBASE_ADMIN_API_BEARER_TOKEN": self.token,
                "COINBASE_ADMIN_API_ENVIRONMENT": "local-controlled-live-test-profile",
                "COINBASE_BACKEND_DEPLOYMENT_TIER": "local",
                "COINBASE_ADMIN_API_STATE_DIR": str(self.state_dir),
                "COINBASE_ADMIN_API_APPROVAL_LOG_PATH": str(self.state_dir / "approvals.jsonl"),
                "COINBASE_ADMIN_API_IDEMPOTENCY_LOG_PATH": str(self.state_dir / "idempotency.jsonl"),
                "COINBASE_ADMIN_API_AUDIT_LOG_PATH": str(self.state_dir / "audit.jsonl"),
                "COINBASE_ADMIN_API_CAP_GUARD_LOG_PATH": str(self.state_dir / "cap_guard.jsonl"),
                "COINBASE_ADMIN_API_RECONCILIATION_LOG_PATH": str(self.state_dir / "reconciliation.jsonl"),
                "COINBASE_ADMIN_API_LIVE_SERVICE_DECISION_LOG_PATH": str(self.state_dir / "live_service.jsonl"),
                "COINBASE_ADMIN_API_LIVE_ADAPTER_DECISION_LOG_PATH": str(self.state_dir / "live_adapter.jsonl"),
                "PRODUCT_CAPABILITIES_JSON": json.dumps(
                    INTENTIONAL_FILL_CAPABILITIES,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "SPOT_FOLLOW_UP_POLICY_JSON": json.dumps(
                    INTENTIONAL_FILL_FOLLOW_UP_INTENTS,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "ACTION_CONDITION_GUARDS_JSON": json.dumps(
                    INTENTIONAL_FILL_ACTION_GUARDS,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                RUNTIME_CHILD_NONCE_ENV: self.child_nonce,
            }
        )
        for key in (
            "DISABLE_RECONCILER",
            "COINBASE_ADMIN_API_ORDER_EVENT_STREAM_DISABLED",
            "COINBASE_REFRESH_PRODUCTS_ON_IMPORT",
        ):
            env.pop(key, None)
        self.log_handle = (self.state_dir / "embedded-runtime.log").open(
            "w", encoding="utf-8"
        )
        self.process = subprocess.Popen(
            [
                "python3.13",
                str(Path(__file__).resolve()),
                "--runtime-child",
                "--runtime-state-dir",
                str(self.state_dir),
                "--runtime-auth-file",
                str(self.child_auth_file),
            ],
            cwd=ROOT,
            env=env,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        (self.state_dir / "embedded-runtime.pid").write_text(
            f"{self.process.pid}\n", encoding="utf-8"
        )

    def wait_until_mutations_ready(self) -> dict[str, Any]:
        decision_body = {
            "decision_id": f"disabled-startup-{uuid4()}",
            "status": "blocked",
            "requested_service_status": "live_disabled",
            "service_enabled": False,
            "target_module_id": "spot_operations",
            "account_family": "coinbase_retail_test",
            "venue_scope": "coinbase_advanced_trade",
            "intx_applicability": "not_applicable",
            "product_scope": [PRODUCT_ID],
            "deployment_ref": EXPECTED_COMMIT,
            "runtime_configuration_ref": str(self.state_dir),
            "decision_reason": "Keep live service disabled while canonical runtime starts.",
            "live_coinbase_execution_approved": False,
            "max_submitted_notional_usdc": "0",
            "max_executed_notional_usdc": "0",
        }
        headers = self.headers(
            idempotency_key=f"idem-disabled-startup-{uuid4()}",
            operator_intent="record_disabled_service_before_controlled_proof",
            role=ADMIN_ROLE,
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            require(self.process is not None, "server_process_missing")
            if self.process.poll() is not None:
                raise ProofFailure(f"embedded_runtime_exited:{self.process.returncode}")
            try:
                status_code, payload, _ = self.request(
                    "POST",
                    "/admin/live-execution/service-decisions",
                    headers=headers,
                    body=decision_body,
                    expected={200, 503},
                    timeout=5,
                )
            except requests.RequestException:
                time.sleep(0.5)
                continue
            if status_code == 200:
                used_payload, _ = _read_owner_only_json(
                    self.state_dir / RUNTIME_CHILD_AUTH_USED_FILENAME,
                    blocker_prefix="runtime_child_authority_used",
                )
                require(
                    used_payload.get("authority_sha256")
                    == self.child_authority_sha256,
                    "runtime_child_authority_handshake_mismatch",
                )
                require(
                    int(used_payload.get("child_pid") or -1)
                    == self.process.pid,
                    "runtime_child_authority_handshake_pid_mismatch",
                )
                self.live_service_may_be_enabled = False
                self.live_service_disable_proven = True
                self.sdk_boundary_sentinel(
                    expected_root_create_order_calls={0},
                    expected_child_place_limit_order_calls={0},
                )
                return payload
            time.sleep(0.5)
        raise ProofFailure("embedded_runtime_readiness_timeout")

    def stop_if_safe(self) -> dict[str, Any]:
        if self.process is None:
            return {
                "runtime_process_started": False,
                "runtime_process_shutdown_proven": True,
                "runtime_preserved_for_reconciliation": False,
            }
        if self.process.poll() is not None:
            if self.log_handle is not None:
                self.log_handle.close()
            return {
                "runtime_process_started": True,
                "runtime_process_shutdown_proven": True,
                "runtime_exit_code": self.process.returncode,
                "runtime_preserved_for_reconciliation": False,
            }
        if not self.exchange_safe_to_shutdown:
            print(
                json.dumps(
                    {
                        "status": "runtime_preserved_for_reconciliation",
                        "pid": self.process.pid,
                        "state_dir": str(self.state_dir),
                    },
                    sort_keys=True,
                )
            )
            if self.log_handle is not None:
                self.log_handle.close()
            return {
                "runtime_process_started": True,
                "runtime_process_shutdown_proven": False,
                "runtime_pid": self.process.pid,
                "runtime_preserved_for_reconciliation": True,
            }
        self.process.send_signal(signal.SIGTERM)
        forced_kill = False
        try:
            self.process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            forced_kill = True
            self.process.kill()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                if self.log_handle is not None:
                    self.log_handle.close()
                return {
                    "runtime_process_started": True,
                    "runtime_process_shutdown_proven": False,
                    "runtime_pid": self.process.pid,
                    "runtime_preserved_for_reconciliation": False,
                    "runtime_forced_kill_attempted": True,
                }
        if self.log_handle is not None:
            self.log_handle.close()
        return {
            "runtime_process_started": True,
            "runtime_process_shutdown_proven": True,
            "runtime_exit_code": self.process.returncode,
            "runtime_preserved_for_reconciliation": False,
            "runtime_forced_kill_attempted": forced_kill,
        }


def capture_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    admission = object_record(payload.get("admission_decision"))
    required = (
        "route",
        "method",
        "module_id",
        "identity_key",
        "identity_value",
        "action_class",
        "required_permission",
        "service_method",
        "actor_id",
        "operator_intent",
        "idempotency_key",
        "payload_hash",
    )
    for key in required:
        require(bool(admission.get(key)), f"admission_context_missing:{key}")
    require(admission.get("allowed") is False, "initial_admission_not_blocked")
    require(payload.get("live_exchange_submitted") is False, "initial_exchange_submit_flag")
    require(payload.get("live_coinbase_orders_ran") is False, "initial_coinbase_run_flag")
    return {
        "route": admission["route"],
        "method": admission["method"],
        "module_id": admission["module_id"],
        "identity_key": admission["identity_key"],
        "identity_value": admission["identity_value"],
        "action_class": admission["action_class"],
        "required_permission": admission["required_permission"],
        "service_method": admission["service_method"],
        "actor_id": admission["actor_id"],
        "operator_intent": admission["operator_intent"],
        "command_idempotency_key": admission["idempotency_key"],
        "payload_hash": admission["payload_hash"],
    }


def write_proof_chain(
    runtime: AdminRuntime,
    *,
    label: str,
    context: Mapping[str, Any],
    wallet_available: Decimal,
    max_notional: Decimal,
    command_kind: str,
    cancel: bool,
    approval_id: str | None = None,
) -> dict[str, str]:
    require(
        command_kind
        in {"root_place", "root_cancel", "child_reveal", "child_cancel"},
        f"proof_chain_command_kind_invalid:{label}",
    )
    require(
        cancel == command_kind.endswith("cancel"),
        f"proof_chain_cancel_kind_mismatch:{label}",
    )
    approval_id = approval_id or f"approval-{label}-{uuid4()}"
    cap_ref = f"cap-{label}-{uuid4()}"
    reconciliation_ref = f"reconciliation-{label}-{uuid4()}"
    approval_request_body = {
        key: value
        for key, value in context.items()
        if key not in {"service_method", "actor_id"}
    } | {"request_reason": f"Approval-bound controlled batch {label} proof."}
    _, approval_request, _ = runtime.request(
        "POST",
        "/admin/approvals/requests",
        headers=runtime.headers(
            idempotency_key=f"idem-approval-request-{label}-{uuid4()}",
            operator_intent=f"request_{label}_approval",
            role=COMMAND_ROLE,
        ),
        body=approval_request_body,
        expected={200},
    )
    request_id = str(object_record(approval_request.get("approval")).get("approval_request_id") or "")
    require(bool(request_id), f"approval_request_id_missing:{label}")
    _, approval_decision, _ = runtime.request(
        "POST",
        f"/admin/approvals/requests/{request_id}/decisions",
        headers=runtime.headers(
            idempotency_key=f"idem-approval-decision-{label}-{uuid4()}",
            operator_intent=f"approve_{label}_snapshot",
            role=ADMIN_ROLE,
        ),
        body={
            "decision": "approved",
            "decision_reason": f"Approve the exact controlled batch {label} tuple.",
            "expires_at": (datetime.now(timezone.utc) + PLAN_TTL).isoformat(),
            "approval_id": approval_id,
            "cap_guard_decision_ref": cap_ref,
            "reconciliation_plan_ref": reconciliation_ref,
        },
        expected={200},
    )
    approval = object_record(approval_decision.get("approval"))
    require(approval.get("approval_id") == approval_id, f"approval_snapshot_mismatch:{label}")

    audit_body = dict(context) | {
        "approval_snapshot_id": approval_id,
        "approval_snapshot_approved_by_actor_id": approval.get("decision_actor_id"),
        "approval_snapshot_requested_by_actor_id": approval.get("requested_by_actor_id"),
        "approval_snapshot_expires_at": approval.get("expires_at"),
        "approval_cap_guard_decision_ref": cap_ref,
        "approval_reconciliation_plan_ref": reconciliation_ref,
        "allowed": False,
        "status": "blocked",
        "reason": f"Initial controlled batch {label} admission was blocked before route-bound proofs.",
    }
    _, audit_response, _ = runtime.request(
        "POST",
        "/admin/admission-audits",
        headers=runtime.headers(
            idempotency_key=f"idem-admission-audit-{label}-{uuid4()}",
            operator_intent=f"record_{label}_admission_audit",
            role=ADMIN_ROLE,
        ),
        body=audit_body,
        expected={200},
    )
    audit = object_record(audit_response.get("admission_audit"))
    audit_id = str(audit.get("admission_audit_id") or "")
    require(bool(audit_id), f"admission_audit_id_missing:{label}")
    require(audit.get("resolver_eligible") is True, f"admission_audit_not_eligible:{label}")

    require(
        max_notional.is_finite() and max_notional >= 0,
        f"proof_chain_max_notional_invalid:{label}",
    )
    require(
        (cancel and max_notional == 0)
        or (not cancel and Decimal("0") < max_notional <= ROOT_SUBMITTED_CAP),
        f"proof_chain_max_notional_scope_mismatch:{label}",
    )
    max_notional_text = decimal_text(max_notional)
    cap_body = dict(context) | {
        "approval_snapshot_id": approval_id,
        "approval_cap_guard_decision_ref": cap_ref,
        "admission_audit_id": audit_id,
        "allowed": True,
        "status": "passed",
        "cap_policy_ref": (
            "no_new_notional:cancel_order"
            if cancel
            else f"submitted_notional_cap:{max_notional_text}"
        ),
        "guard_policy_ref": (
            {
                "root_place": (
                    "approved_intentional_fill_exact_ask_wallet_single_fok"
                ),
                "root_cancel": "cancel_by_client_order_id",
                "child_reveal": (
                    "controlled_first_child_far_sell_gtc_wallet_and_cap"
                ),
                "child_cancel": (
                    "controlled_first_child_exact_exchange_identity_cancel"
                ),
            }[command_kind]
        ),
        "product_scope": "BTC-USDC Spot Test profile",
        "max_submitted_notional_usdc": max_notional_text,
        "max_executed_notional_usdc": max_notional_text,
        "wallet_check_required": not cancel,
        "wallet_check_status": "passed",
        "wallet_available_notional_usdc": (
            "0" if cancel else decimal_text(wallet_available)
        ),
        "wallet_check_source": (
            "not_applicable:cancel_order"
            if cancel
            else (
                "coinbase_test_profile_btc_available_times_child_limit_price"
                if command_kind == "child_reveal"
                else "coinbase_test_profile_usdc_accounts_readback"
            )
        ),
        "reason": f"Controlled batch {label} cap and guard proof.",
    }
    _, cap_response, _ = runtime.request(
        "POST",
        "/admin/cap-guard/decisions",
        headers=runtime.headers(
            idempotency_key=f"idem-cap-{label}-{uuid4()}",
            operator_intent=f"record_{label}_cap_guard",
            role=ADMIN_ROLE,
        ),
        body=cap_body,
        expected={200},
    )
    cap = object_record(cap_response.get("decision"))
    require(cap.get("decision_id") == cap_ref, f"cap_decision_mismatch:{label}")
    require(cap.get("resolver_eligible") is True, f"cap_decision_not_eligible:{label}")

    reconciliation_body = dict(context) | {
        "approval_snapshot_id": approval_id,
        "approval_reconciliation_plan_ref": reconciliation_ref,
        "admission_audit_id": audit_id,
        "cap_guard_decision_id": cap_ref,
        "allowed": True,
        "status": "passed",
        "reconciliation_policy_ref": (
            {
                "root_place": (
                    "post_fill_exact_root_child_chain_and_exchange_readback"
                ),
                "root_cancel": "post_cancel_exact_terminal_readback",
                "child_reveal": (
                    "post_submit_exact_child_exchange_readback_then_cancel"
                ),
                "child_cancel": (
                    "post_cancel_exact_child_terminal_and_local_reconciliation"
                ),
            }[command_kind]
        ),
        "product_scope": "BTC-USDC Spot Test profile",
        "exchange_submission_required": True,
        "post_submit_reconciliation_required": True,
        "retained_inventory_required": True,
        "max_submitted_notional_usdc": max_notional_text,
        "max_executed_notional_usdc": max_notional_text,
        "reason": f"Controlled batch {label} reconciliation proof.",
    }
    _, reconciliation_response, _ = runtime.request(
        "POST",
        "/admin/reconciliation/plans",
        headers=runtime.headers(
            idempotency_key=f"idem-reconciliation-{label}-{uuid4()}",
            operator_intent=f"record_{label}_reconciliation",
            role=ADMIN_ROLE,
        ),
        body=reconciliation_body,
        expected={200},
    )
    reconciliation = object_record(reconciliation_response.get("plan"))
    require(
        reconciliation.get("plan_id") == reconciliation_ref,
        f"reconciliation_plan_mismatch:{label}",
    )
    require(
        reconciliation.get("resolver_eligible") is True,
        f"reconciliation_plan_not_eligible:{label}",
    )
    return {
        "approval_id": approval_id,
        "admission_audit_id": audit_id,
        "cap_guard_decision_id": cap_ref,
        "reconciliation_plan_id": reconciliation_ref,
    }


def set_live_service(runtime: AdminRuntime, *, enabled: bool) -> dict[str, Any]:
    label = "enabled" if enabled else "disabled"
    if enabled:
        runtime.live_service_enable_attempted = True
        runtime.live_service_may_be_enabled = True
        runtime.live_service_disable_proven = False
    else:
        runtime.live_service_disable_attempted = True
    body = {
        "decision_id": f"live-service-{label}-{uuid4()}",
        "status": "passed" if enabled else "blocked",
        "requested_service_status": "approval_required" if enabled else "live_disabled",
        "service_enabled": enabled,
        "target_module_id": "spot_operations",
        "account_family": "coinbase_retail_test",
        "venue_scope": "coinbase_advanced_trade",
        "intx_applicability": "not_applicable",
        "product_scope": [PRODUCT_ID],
        "deployment_ref": EXPECTED_COMMIT,
        "runtime_configuration_ref": str(runtime.state_dir),
        "decision_reason": (
            "Enable the approval-bound ten-slot Test-profile root/first-child batch."
            if enabled
            else "Disable live service after the controlled root/first-child batch."
        ),
        "live_coinbase_execution_approved": enabled,
        "max_submitted_notional_usdc": (
            decimal_text(ROOT_SUBMITTED_CAP) if enabled else "0"
        ),
        "max_executed_notional_usdc": (
            decimal_text(ROOT_SUBMITTED_CAP) if enabled else "0"
        ),
    }
    _, response, _ = runtime.request(
        "POST",
        "/admin/live-execution/service-decisions",
        headers=runtime.headers(
            idempotency_key=f"idem-live-service-{label}-{uuid4()}",
            operator_intent=f"record_{label}_live_service_decision",
            role=ADMIN_ROLE,
        ),
        body=body,
        expected={200},
    )
    decision = object_record(response.get("decision"))
    require(decision.get("resolver_eligible") is enabled, f"live_service_eligibility_mismatch:{label}")
    if enabled:
        runtime.live_service_may_be_enabled = True
    else:
        runtime.live_service_may_be_enabled = False
        runtime.live_service_disable_proven = True
    return decision


def preview_admission(runtime: AdminRuntime, context: Mapping[str, Any]) -> dict[str, Any]:
    _, response, _ = runtime.request(
        "GET",
        "/admin/live-execution/admission-preview",
        headers=runtime.headers(role="viewer"),
        params=context,
        expected={200},
    )
    decision = object_record(response.get("admission_decision"))
    require(decision.get("allowed") is True, f"admission_preview_blocked:{decision.get('blockers')}")
    require(decision.get("payload_hash") == context["payload_hash"], "admission_preview_hash_mismatch")
    return decision


def exact_exchange_order(rest_client: Any, exchange_order_id: str) -> dict[str, Any]:
    response = object_record(rest_client.get_order(exchange_order_id))
    order = object_record(response.get("order"))
    return order or response


def _reconciliation_root_plan_slot(root_plan: Mapping[str, Any]) -> int:
    """Read the immutable plan's canonical ``slot`` field fail-closed."""

    try:
        slot = int(root_plan.get("slot") or 0)
    except (TypeError, ValueError):
        slot = 0
    require(1 <= slot <= BATCH_SIZE, "failure_root_slot_invalid")
    return slot


def successor_sdk_call_occurred(
    *,
    slot: int,
    attempt_kind: str,
    sdk_call_count: int,
) -> bool:
    """Map a batch slot to its ordinal in the successor-only SDK process."""

    require(1 <= slot <= BATCH_SIZE, "successor_sdk_slot_invalid")
    require(attempt_kind in {"root", "child"}, "successor_sdk_kind_invalid")
    maximum = (
        SUCCESSOR_ROOT_ORDER_MAXIMUM
        if attempt_kind == "root"
        else SUCCESSOR_CHILD_ORDER_MAXIMUM
    )
    require(
        0 <= sdk_call_count <= maximum,
        "successor_sdk_call_count_invalid",
    )
    if attempt_kind == "root":
        return slot > 1 and sdk_call_count >= slot - 1
    return sdk_call_count >= slot


def consumed_root_absence_can_be_terminal(
    *,
    root_sdk_call_occurred: bool,
    child_attempt_count: int,
) -> bool:
    """Permit absence only when no root transmission or child was possible."""

    require(child_attempt_count >= 0, "failure_child_attempt_count_invalid")
    return not root_sdk_call_occurred and child_attempt_count == 0


def reconcile_failure_state(
    runtime: AdminRuntime,
    *,
    rest_client: Any,
    summary: dict[str, Any],
    current_root_client_order_id: str | None,
) -> dict[str, Any]:
    """Disable service and prove a quiescent terminal pair after every stop."""

    reconciliation: dict[str, Any] = {
        "live_service_disable_attempted": True,
        "current_root_client_order_id": current_root_client_order_id,
        "retry_attempted": False,
        "substitution_attempted": False,
        "next_slot_authorized": False,
    }
    ledger: list[dict[str, Any]] = []
    try:
        set_live_service(runtime, enabled=False)
        reconciliation["live_service_disabled"] = (
            runtime.live_service_disable_proven
        )
    except (Exception, KeyboardInterrupt) as exc:
        reconciliation["live_service_disabled"] = False
        reconciliation["live_service_disable_error"] = (
            f"{type(exc).__name__}:{exc}"
        )

    initial_sentinel: dict[str, Any] | None = None
    try:
        initial_sentinel = runtime.sdk_boundary_sentinel()
        reconciliation["sdk_boundary_sentinel"] = initial_sentinel
        reconciliation["sdk_boundary_sentinel_safe"] = True
    except (Exception, KeyboardInterrupt) as exc:
        reconciliation["sdk_boundary_sentinel_safe"] = False
        reconciliation["sdk_boundary_sentinel_error"] = (
            f"{type(exc).__name__}:{exc}"
        )
    try:
        ledger = read_batch_attempt_ledger(
            runtime.attempt_ledger_path,
            confirmed_plan=runtime.confirmed_plan,
            confirmed_plan_hash=runtime.confirmed_plan_hash,
        )
        reconciliation["attempt_ledger_count"] = len(ledger)
        reconciliation["attempt_ledger_readback_proven"] = True
    except (Exception, KeyboardInterrupt) as exc:
        reconciliation["attempt_ledger_readback_proven"] = False
        reconciliation["attempt_ledger_readback_error"] = (
            f"{type(exc).__name__}:{exc}"
        )

    root_terminal_safe = bool(
        current_root_client_order_id is None
        and reconciliation.get("attempt_ledger_readback_proven") is True
        and initial_sentinel is not None
    )
    if current_root_client_order_id:
        root_attempts = [
            record
            for record in ledger
            if record.get("attempt_kind") == "root"
            and record.get("client_order_id") == current_root_client_order_id
        ]
        child_attempts = [
            record
            for record in ledger
            if record.get("attempt_kind") == "child"
            and record.get("root_client_order_id")
            == current_root_client_order_id
        ]
        reconciliation["current_root_attempt_count"] = len(root_attempts)
        reconciliation["current_child_attempt_count"] = len(child_attempts)
        reconciliation["current_root_attempt_consumed"] = bool(root_attempts)
        reconciliation["current_child_attempt_consumed"] = bool(child_attempts)
        try:
            require(
                len(root_attempts) <= 1,
                "failure_reconciliation_duplicate_root_attempt",
            )
            require(
                len(child_attempts) <= 1,
                "failure_reconciliation_duplicate_child_attempt",
            )
            root_plan = next(
                object_record(item)
                for item in list_value(runtime.confirmed_plan.get("roots"))
                if item.get("root_client_order_id")
                == current_root_client_order_id
            )
            slot = _reconciliation_root_plan_slot(root_plan)
            root_sdk_call_occurred = bool(
                initial_sentinel is not None
                and successor_sdk_call_occurred(
                    slot=slot,
                    attempt_kind="root",
                    sdk_call_count=int(
                        initial_sentinel.get(
                            "root_create_order_call_count"
                        )
                        or 0
                    ),
                )
            )
            child_sdk_call_occurred = bool(
                initial_sentinel is not None
                and successor_sdk_call_occurred(
                    slot=slot,
                    attempt_kind="child",
                    sdk_call_count=int(
                        initial_sentinel.get(
                            "child_place_limit_order_call_count"
                        )
                        or 0
                    ),
                )
            )
            reconciliation["current_root_sdk_call_occurred"] = (
                root_sdk_call_occurred
            )
            reconciliation["current_child_sdk_call_occurred"] = (
                child_sdk_call_occurred
            )

            if not root_attempts and slot > 1:
                require(
                    not root_sdk_call_occurred and not child_attempts,
                    "unconsumed_root_has_sdk_or_child_attempt",
                )
                root_status_code, local_root_payload, _ = runtime.request(
                    "GET",
                    f"/orders/{current_root_client_order_id}",
                    headers=runtime.headers(role="auditor"),
                    expected={200, 404},
                )
                chain_status_code, local_chain_payload, _ = runtime.request(
                    "GET",
                    (
                        f"/orders/{current_root_client_order_id}"
                        "/fill-follow-up/chain"
                    ),
                    headers=runtime.headers(role="auditor"),
                    expected={200, 404},
                )
                local_root_absent = bool(
                    root_status_code == 404
                    or local_root_payload.get("found") is False
                )
                local_chain_absent = bool(
                    chain_status_code == 404
                    or local_chain_payload.get("found") is False
                )
                require(
                    local_root_absent and local_chain_absent,
                    "unconsumed_root_local_state_present",
                )
                reconciliation["current_root_local_absence_proven"] = True
                reconciliation["current_root_chain_absence_proven"] = True
                reconciliation["current_pair_terminal_proof_kind"] = (
                    "unconsumed_local_and_exchange_absence"
                )
                root_terminal_safe = True
            else:
                from application.admin_api.command_service import (
                    exact_coinbase_order_readback,
                )

                root_readback = exact_coinbase_order_readback(
                    rest_client,
                    client_order_id=current_root_client_order_id,
                    product_id=PRODUCT_ID,
                )
                reconciliation["current_root_authoritative_readback"] = (
                    root_readback
                )
                if root_readback.get("confirmed_absent") is True:
                    require(
                        slot > 1
                        and consumed_root_absence_can_be_terminal(
                            root_sdk_call_occurred=root_sdk_call_occurred,
                            child_attempt_count=len(child_attempts),
                        ),
                        "transmitted_root_confirmed_absent_is_ambiguous",
                    )
                    root_status_code, local_root_payload, _ = runtime.request(
                        "GET",
                        f"/orders/{current_root_client_order_id}",
                        headers=runtime.headers(role="auditor"),
                        expected={200, 404},
                    )
                    chain_status_code, local_chain_payload, _ = (
                        runtime.request(
                            "GET",
                            (
                                f"/orders/{current_root_client_order_id}"
                                "/fill-follow-up/chain"
                            ),
                            headers=runtime.headers(role="auditor"),
                            expected={200, 404},
                        )
                    )
                    require(
                        root_status_code == 404
                        or local_root_payload.get("found") is False,
                        "untransmitted_root_local_state_present",
                    )
                    require(
                        chain_status_code == 404
                        or local_chain_payload.get("found") is False,
                        "untransmitted_root_chain_state_present",
                    )
                    reconciliation["current_root_local_absence_proven"] = (
                        True
                    )
                    reconciliation["current_root_chain_absence_proven"] = (
                        True
                    )
                    reconciliation["current_pair_terminal_proof_kind"] = (
                        "consumed_but_untransmitted_absence"
                    )
                    root_terminal_safe = True
                else:
                    require(
                        root_readback.get("exact_identity_match") is True,
                        "failure_root_exact_identity_unproven",
                    )
                    matched_root = object_record(
                        root_readback.get("matched_order")
                    )
                    exchange_id = str(matched_root.get("order_id") or "")
                    require(bool(exchange_id), "failure_root_exchange_id_missing")
                    validated_root = _validate_exact_coinbase_fok_order(
                        matched_root,
                        expected_exchange_order_id=exchange_id,
                        expected_client_order_id=current_root_client_order_id,
                        expected_portfolio_id=runtime.portfolio_id,
                        expected_order_body=object_record(root_plan["order"]),
                    )
                    root_status = str(
                        validated_root.get("status") or ""
                    ).upper()
                    root_filled_size = Decimal(
                        str(validated_root.get("filled_size") or "0")
                    )
                    reconciliation["current_root_authoritative_status"] = (
                        root_status
                    )
                    reconciliation[
                        "current_root_authoritative_filled_size"
                    ] = decimal_text(root_filled_size)
                    if root_status in NO_FILL_TERMINAL_STATUSES:
                        require(
                            not child_attempts,
                            "terminal_no_fill_has_child_attempt",
                        )
                        no_fill_proof = (
                            _prove_terminal_no_fill_locally_and_authoritatively(
                                runtime,
                                rest_client=rest_client,
                                client_order_id=current_root_client_order_id,
                                exchange_order_id=exchange_id,
                                expected_exchange_status=root_status,
                            )
                        )
                        reconciliation["terminal_no_fill_proof"] = (
                            no_fill_proof
                        )
                        reconciliation[
                            "current_pair_terminal_proof_kind"
                        ] = "terminal_no_fill_with_local_chain"
                        root_terminal_safe = True
                    elif root_status == "FILLED" and child_attempts:
                        require(
                            root_filled_size
                            == Decimal(str(root_plan["order"]["base_size"])),
                            "failure_root_partial_fill_detected",
                        )
                        require(
                            child_sdk_call_occurred,
                            "filled_root_child_sdk_call_not_proven",
                        )
                        child_tuple = object_record(
                            child_attempts[0].get("exact_order_tuple")
                        )
                        child_readback = exact_coinbase_order_readback(
                            rest_client,
                            client_order_id=str(
                                root_plan["child_client_order_id"]
                            ),
                            product_id=PRODUCT_ID,
                        )
                        reconciliation[
                            "current_child_authoritative_readback"
                        ] = child_readback
                        require(
                            child_readback.get("exact_identity_match") is True,
                            "failure_child_exact_identity_unproven",
                        )
                        matched_child = object_record(
                            child_readback.get("matched_order")
                        )
                        child_exchange_id = str(
                            matched_child.get("order_id") or ""
                        )
                        require(
                            bool(child_exchange_id),
                            "failure_child_exchange_id_missing",
                        )
                        validated_child = (
                            _validate_exact_coinbase_gtc_child_order(
                                matched_child,
                                expected_exchange_order_id=child_exchange_id,
                                expected_portfolio_id=runtime.portfolio_id,
                                expected_child_tuple=child_tuple,
                            )
                        )
                        child_status = str(
                            validated_child.get("status") or ""
                        ).upper()
                        child_filled_size = Decimal(
                            str(validated_child.get("filled_size") or "0")
                        )
                        require(
                            child_status in {"CANCELLED", "CANCELED"}
                            and child_filled_size == 0,
                            "failure_child_not_terminal_zero_fill",
                        )
                        reconciliation[
                            "current_child_authoritative_status"
                        ] = child_status
                        reconciliation[
                            "current_child_authoritative_filled_size"
                        ] = decimal_text(child_filled_size)
                        reconciliation["cancelled_child_chain_proof"] = (
                            _validate_cancelled_child_chain(
                                runtime,
                                root_plan=root_plan,
                                exchange_order_id=child_exchange_id,
                            )
                        )
                        reconciliation[
                            "current_pair_terminal_proof_kind"
                        ] = "filled_root_cancelled_child_with_local_chain"
                        root_terminal_safe = True
        except (Exception, KeyboardInterrupt) as exc:
            reconciliation["terminal_identity_reconciliation_error"] = (
                f"{type(exc).__name__}:{exc}"
            )
            root_terminal_safe = False

    active_orders: list[dict[str, Any]] | None = None
    quiescence_window_proven = False
    try:
        require(
            initial_sentinel is not None,
            "initial_sdk_boundary_sentinel_unproven",
        )
        _, runtime_before, _ = runtime.request(
            "GET",
            "/admin/runtime",
            headers=runtime.headers(role="viewer"),
            expected={200},
        )
        require(
            int(runtime_before.get("total_inflight") or 0) == 0,
            "admin_runtime_inflight_before_active_reads",
        )
        first_active = read_authoritative_spot_nonterminal_orders(
            rest_client,
            expected_portfolio_id=runtime.portfolio_id,
        )
        time.sleep(0.5)
        second_active = read_authoritative_spot_nonterminal_orders(
            rest_client,
            expected_portfolio_id=runtime.portfolio_id,
        )
        first_identities = sorted(
            (
                str(row.get("client_order_id") or ""),
                str(row.get("order_id") or ""),
                str(row.get("status") or "").upper(),
            )
            for row in first_active
        )
        second_identities = sorted(
            (
                str(row.get("client_order_id") or ""),
                str(row.get("order_id") or ""),
                str(row.get("status") or "").upper(),
            )
            for row in second_active
        )
        require(
            first_identities == second_identities,
            "authoritative_active_order_reads_not_stable",
        )
        final_sentinel = runtime.sdk_boundary_sentinel()
        require(
            int(
                final_sentinel.get("root_create_order_call_count") or 0
            )
            == int(
                initial_sentinel.get("root_create_order_call_count") or 0
            ),
            "root_sdk_call_count_changed_during_quiescence_window",
        )
        require(
            int(
                final_sentinel.get("child_place_limit_order_call_count") or 0
            )
            == int(
                initial_sentinel.get(
                    "child_place_limit_order_call_count"
                )
                or 0
            ),
            "child_sdk_call_count_changed_during_quiescence_window",
        )
        _, runtime_after, _ = runtime.request(
            "GET",
            "/admin/runtime",
            headers=runtime.headers(role="viewer"),
            expected={200},
        )
        require(
            int(runtime_after.get("total_inflight") or 0) == 0,
            "admin_runtime_inflight_after_active_reads",
        )
        active_orders = second_active
        quiescence_window_proven = True
        reconciliation["admin_runtime_before_active_reads"] = runtime_before
        reconciliation["admin_runtime_after_active_reads"] = runtime_after
        reconciliation["sdk_boundary_sentinel_after_active_reads"] = (
            final_sentinel
        )
        reconciliation["authoritative_active_spot_orders"] = active_orders
        reconciliation["authoritative_active_spot_order_count"] = len(
            active_orders
        )
        reconciliation["authoritative_active_order_reads_stable"] = True
        reconciliation["authoritative_active_order_read_proven"] = True
        reconciliation["quiescence_window_proven"] = True
    except (Exception, KeyboardInterrupt) as exc:
        reconciliation["authoritative_active_order_read_proven"] = False
        reconciliation["authoritative_active_order_reads_stable"] = False
        reconciliation["quiescence_window_proven"] = False
        reconciliation["quiescence_window_error"] = (
            f"{type(exc).__name__}:{exc}"
        )

    reconciliation["current_pair_terminal_safe"] = root_terminal_safe

    runtime.exchange_safe_to_shutdown = bool(
        reconciliation.get("live_service_disabled") is True
        and reconciliation.get("attempt_ledger_readback_proven") is True
        and reconciliation.get("sdk_boundary_sentinel_safe") is True
        and root_terminal_safe
        and quiescence_window_proven
        and active_orders == []
    )
    reconciliation["safe_to_shutdown"] = runtime.exchange_safe_to_shutdown
    summary["failure_reconciliation"] = reconciliation
    return reconciliation


def finalize_runtime_cleanup(
    runtime: AdminRuntime,
    *,
    summary: dict[str, Any],
) -> None:
    """Prove a disabled service plus safe shutdown, or preserve the runtime."""

    cleanup: dict[str, Any] = {
        "exchange_safe_to_shutdown": runtime.exchange_safe_to_shutdown,
        "live_service_enable_attempted": runtime.live_service_enable_attempted,
        "live_service_disable_attempted": runtime.live_service_disable_attempted,
        "live_service_disable_proven_before_cleanup": (
            runtime.live_service_disable_proven
        ),
    }
    if (
        runtime.exchange_safe_to_shutdown
        and runtime.live_service_enable_attempted
        and not runtime.live_service_disable_proven
    ):
        try:
            set_live_service(runtime, enabled=False)
        except (Exception, KeyboardInterrupt) as exc:
            cleanup["safe_cleanup_disable_error"] = f"{type(exc).__name__}:{exc}"
            runtime.exchange_safe_to_shutdown = False
    cleanup["live_service_disable_proven_after_cleanup"] = (
        runtime.live_service_disable_proven
    )
    try:
        cleanup["sdk_boundary_sentinel"] = runtime.sdk_boundary_sentinel()
    except ProofFailure as exc:
        cleanup["sdk_boundary_sentinel_error"] = str(exc)
        runtime.exchange_safe_to_shutdown = False
    cleanup.update(runtime.stop_if_safe())
    (runtime.state_dir / "controlled-batch-cleanup.json").write_text(
        json.dumps(cleanup, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    summary["runtime_cleanup"] = cleanup
    if (
        runtime.exchange_safe_to_shutdown
        and not cleanup.get("runtime_process_shutdown_proven")
    ):
        raise ProofFailure("safe_runtime_shutdown_unproven")


def _wait_for_exchange_terminal(
    rest_client: Any,
    *,
    exchange_order_id: str,
    client_order_id: str,
    portfolio_id: str,
    order_body: Mapping[str, Any],
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    order: dict[str, Any] = {}
    while time.monotonic() < deadline:
        order = exact_exchange_order(rest_client, exchange_order_id)
        _validate_exact_coinbase_fok_order(
            order,
            expected_exchange_order_id=exchange_order_id,
            expected_client_order_id=client_order_id,
            expected_portfolio_id=portfolio_id,
            expected_order_body=order_body,
        )
        if str(order.get("status") or "").upper() in TERMINAL_STATUSES:
            return order
        time.sleep(0.25)
    return order


def _wallet_balances(rest_client: Any, *, expected_portfolio_id: str) -> dict[str, Decimal]:
    response = object_record(rest_client.get_accounts(limit=250))
    rows = [object_record(item) for item in list_value(response.get("accounts"))]
    require(bool(rows), "wallet_account_catalog_empty")
    profile_ids = {
        str(row.get("retail_portfolio_id") or row.get("portfolio_uuid") or "")
        for row in rows
    }
    require(profile_ids == {expected_portfolio_id}, "wallet_profile_scope_mismatch")
    balances: dict[str, Decimal] = {}
    for row in rows:
        currency = str(row.get("currency") or "").upper()
        if currency not in {"BTC", "USDC"}:
            continue
        available = object_record(row.get("available_balance"))
        parsed = Decimal(str(available.get("value") or "0"))
        require(parsed.is_finite() and parsed >= 0, f"wallet_balance_invalid:{currency}")
        balances[currency] = parsed
    require("USDC" in balances, "wallet_usdc_missing")
    balances.setdefault("BTC", Decimal("0"))
    return balances


def _read_order_match_audit_rows(db_client: Any, client_order_id: str) -> list[dict[str, Any]]:
    rows = db_client.execute_query(
        """
        SELECT client_order_id, snapshot_seq, cumulative_quantity, filled_value,
               total_fees, number_of_fills, status, derived_size_delta,
               derived_value_delta, derived_fee_delta, derived_price,
               derived_trade_key, emitted_fill_ledger_row, raw_payload_json
          FROM order_match_audit
         WHERE client_order_id = %s
         ORDER BY snapshot_seq ASC
        """,
        (client_order_id,),
    ) or []
    require(all(isinstance(row, Mapping) for row in rows), "order_match_audit_rows_malformed")
    return [dict(row) for row in rows]


def _prove_fresh_fill_persistence_identity(client_order_id: str) -> dict[str, Any]:
    """Prove a fresh root ID has no pre-existing fill or match-audit rows."""

    sys.path.insert(0, str(ROOT))
    from database import order as order_module

    ledger_rows = order_module.get_fills_by_order(client_order_id) or []
    audit_rows = _read_order_match_audit_rows(
        order_module.DB_CLIENT,
        client_order_id,
    )
    column_rows = order_module.DB_CLIENT.execute_query(
        """
        SELECT data_type, udt_name
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'fill_ledger'
           AND column_name = 'exchange_trade_id'
        """
    ) or []
    require(len(column_rows) == 1, "fill_ledger_exchange_trade_id_column_missing")
    column = dict(column_rows[0])
    require(
        str(column.get("data_type") or "").lower() == "text"
        and str(column.get("udt_name") or "").lower() == "text",
        "fill_ledger_exchange_trade_id_column_not_text",
    )
    require(not ledger_rows, "fresh_client_order_id_fill_ledger_collision")
    require(not audit_rows, "fresh_client_order_id_match_audit_collision")
    return {
        "client_order_id": client_order_id,
        "fill_ledger_row_count": 0,
        "order_match_audit_row_count": 0,
        "exchange_trade_id_column_type": "text",
        "fresh_identity_proven": True,
    }


def _normalized_false(value: Any, *, blocker: str) -> bool:
    if value is False or value == 0:
        return True
    if isinstance(value, str) and value.strip().lower() in {
        "false",
        "0",
        "no",
    }:
        return True
    if value is True or value == 1:
        return False
    raise ProofFailure(blocker)


def _missing_or_false(value: Any, *, blocker: str) -> bool:
    if value is None:
        return True
    return _normalized_false(value, blocker=blocker)


def _validate_exact_coinbase_fok_order(
    order: Mapping[str, Any],
    *,
    expected_exchange_order_id: str,
    expected_client_order_id: str,
    expected_portfolio_id: str,
    expected_order_body: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate Coinbase's canonical FOK row without accepting semantic drift."""

    require(isinstance(order, Mapping), "exact_fok_order_not_object")
    row = dict(order)
    exact_fields = {
        "order_id": expected_exchange_order_id,
        "client_order_id": expected_client_order_id,
        "product_id": PRODUCT_ID,
        "retail_portfolio_id": expected_portfolio_id,
    }
    for field, expected in exact_fields.items():
        require(str(row.get(field) or "") == expected, f"exact_fok_order_{field}_mismatch")
    require(str(row.get("product_type") or "").upper() == "SPOT", "exact_fok_order_product_type_mismatch")
    require(str(row.get("side") or "").upper() == "BUY", "exact_fok_order_side_mismatch")
    require(str(row.get("order_type") or "").upper() == "LIMIT", "exact_fok_order_type_mismatch")
    require(str(row.get("time_in_force") or "").upper() == "FILL_OR_KILL", "exact_fok_order_tif_mismatch")
    require(bool(str(row.get("status") or "").strip()), "exact_fok_order_status_missing")
    require(
        _normalized_false(
            row.get("size_in_quote"), blocker="exact_fok_order_size_in_quote_invalid"
        ),
        "exact_fok_order_size_in_quote_true",
    )
    require(
        "quote_size" not in row or row.get("quote_size") in (None, ""),
        "exact_fok_order_quote_size_present",
    )
    require(
        _missing_or_false(row.get("post_only"), blocker="exact_fok_order_post_only_invalid"),
        "exact_fok_order_post_only_true",
    )
    configuration = row.get("order_configuration")
    require(isinstance(configuration, Mapping), "exact_fok_order_configuration_malformed")
    configuration = dict(configuration)
    require(set(configuration) == {"limit_limit_fok"}, "exact_fok_order_configuration_mismatch")
    raw_fok = configuration.get("limit_limit_fok")
    require(isinstance(raw_fok, Mapping), "exact_fok_order_fok_malformed")
    fok = dict(raw_fok)
    allowed_fields = {
        "base_size",
        "limit_price",
        "currency_size",
        "reduce_only",
        "rfq_disabled",
        "rfq_enabled",
        "post_only",
    }
    require(set(fok) <= allowed_fields, "exact_fok_order_fok_unknown_field")
    require({"base_size", "limit_price"} <= set(fok), "exact_fok_order_fok_required_field_missing")
    require(
        Decimal(str(fok.get("base_size") or "0"))
        == Decimal(str(expected_order_body.get("base_size") or "0")),
        "exact_fok_order_base_size_mismatch",
    )
    require(
        Decimal(str(fok.get("limit_price") or "0"))
        == Decimal(str(expected_order_body.get("limit_price") or "0")),
        "exact_fok_order_limit_price_mismatch",
    )
    if "rfq_enabled" in fok:
        require(
            _normalized_false(
                fok["rfq_enabled"],
                blocker="exact_fok_order_rfq_enabled_invalid",
            ),
            "exact_fok_order_rfq_enabled_truthy",
        )
    for decoration in set(fok) - {
        "base_size",
        "limit_price",
        "rfq_enabled",
    }:
        require(
            _missing_or_false(
                fok[decoration],
                blocker=f"exact_fok_order_{decoration}_invalid",
            ),
            f"exact_fok_order_{decoration}_truthy",
        )
    require("quote_size" not in fok, "exact_fok_order_fok_quote_size_present")
    return row


def _validate_exact_coinbase_gtc_child_order(
    order: Mapping[str, Any],
    *,
    expected_exchange_order_id: str,
    expected_portfolio_id: str,
    expected_child_tuple: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the exact deterministic SELL/GTC child exchange row."""

    require(isinstance(order, Mapping), "exact_child_order_not_object")
    row = dict(order)
    for field, expected in {
        "order_id": expected_exchange_order_id,
        "client_order_id": str(expected_child_tuple["client_order_id"]),
        "product_id": PRODUCT_ID,
        "retail_portfolio_id": expected_portfolio_id,
    }.items():
        require(
            str(row.get(field) or "") == expected,
            f"exact_child_order_{field}_mismatch",
        )
    require(
        str(row.get("product_type") or "").upper() == "SPOT",
        "exact_child_order_product_type_mismatch",
    )
    require(
        str(row.get("side") or "").upper() == "SELL",
        "exact_child_order_side_mismatch",
    )
    require(
        str(row.get("order_type") or "").upper() == "LIMIT",
        "exact_child_order_type_mismatch",
    )
    require(
        str(row.get("time_in_force") or "").upper()
        == "GOOD_UNTIL_CANCELLED",
        "exact_child_order_tif_mismatch",
    )
    require(
        _missing_or_false(
            row.get("post_only"),
            blocker="exact_child_order_post_only_invalid",
        ),
        "exact_child_order_post_only_true",
    )
    configuration = object_record(row.get("order_configuration"))
    require(
        set(configuration) == {"limit_limit_gtc"},
        "exact_child_order_configuration_mismatch",
    )
    gtc = object_record(configuration.get("limit_limit_gtc"))
    allowed_fields = {
        "base_size",
        "limit_price",
        "post_only",
        "reduce_only",
        "rfq_disabled",
    }
    require(set(gtc) <= allowed_fields, "exact_child_order_gtc_unknown_field")
    require(
        {"base_size", "limit_price"} <= set(gtc),
        "exact_child_order_gtc_required_field_missing",
    )
    require(
        Decimal(str(gtc.get("base_size") or "0"))
        == Decimal(str(expected_child_tuple.get("base_size") or "0")),
        "exact_child_order_base_size_mismatch",
    )
    require(
        Decimal(str(gtc.get("limit_price") or "0"))
        == Decimal(str(expected_child_tuple.get("limit_price") or "0")),
        "exact_child_order_limit_price_mismatch",
    )
    for decoration in set(gtc) - {"base_size", "limit_price"}:
        require(
            _missing_or_false(
                gtc[decoration],
                blocker=f"exact_child_order_{decoration}_invalid",
            ),
            f"exact_child_order_{decoration}_truthy",
        )
    status = str(row.get("status") or "").upper()
    require(
        status
        in {
            "PENDING",
            "OPEN",
            "CANCELLED",
            "CANCELED",
            "FILLED",
            "FAILED",
            "REJECTED",
        },
        f"exact_child_order_status_invalid:{status}",
    )
    filled_size = Decimal(str(row.get("filled_size") or "0"))
    require(
        filled_size.is_finite() and filled_size >= 0,
        "exact_child_order_filled_size_invalid",
    )
    return row


def _read_exact_rest_fill_pages(
    rest_client: Any,
    *,
    exchange_order_id: str,
    portfolio_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read bounded SDK cursor pages and prove exact complete fill identity."""

    cursor: str | None = None
    seen_cursors: set[str] = set()
    fills: list[dict[str, Any]] = []
    page_count = 0
    for page_count in range(1, 6):
        kwargs: dict[str, Any] = {
            "order_ids": [exchange_order_id],
            "retail_portfolio_id": portfolio_id,
            "limit": 100,
        }
        if cursor is not None:
            kwargs["cursor"] = cursor
        page = object_record(rest_client.get_fills(**kwargs))
        raw_fills = page.get("fills")
        require(isinstance(raw_fills, list), "exact_rest_fills_malformed")
        page_fills = [object_record(item) for item in raw_fills]
        require(all(page_fills), "exact_rest_fill_row_malformed")
        fills.extend(page_fills)
        next_cursor = str(page.get("cursor") or "").strip()
        if not next_cursor:
            return fills, {
                "page_count": page_count,
                "fill_count": len(fills),
                "pagination_complete": True,
                "termination": "empty_or_missing_cursor",
                "page_limit": 100,
                "maximum_pages": 5,
            }
        require(bool(page_fills), "exact_rest_fills_empty_page_with_cursor")
        require(next_cursor not in seen_cursors, "exact_rest_fills_cursor_repeated")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise ProofFailure("exact_rest_fills_pagination_bound_exceeded")


def _raw_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProofFailure("order_match_audit_raw_payload_invalid") from exc
        require(isinstance(parsed, dict), "order_match_audit_raw_payload_not_object")
        return dict(parsed)
    raise ProofFailure("order_match_audit_raw_payload_missing")


def _reconcile_fill_ledger_with_exact_rest_fills(
    rest_client: Any,
    *,
    client_order_id: str,
    exchange_order_id: str,
    portfolio_id: str,
    expected_filled_size: Decimal,
    expected_filled_value: Decimal,
    expected_total_fees: Decimal,
) -> dict[str, Any]:
    """Prove a per-row bijection, then invoke the canonical FillReconciler."""

    sys.path.insert(0, str(ROOT))
    from business.fill_reconciler import FillReconciler
    from calculation.resolver import resolve_cumulative_filled
    from database import order as order_module

    deadline = time.monotonic() + 30
    ledger_rows = order_module.get_fills_by_order(client_order_id) or []
    audit_rows = _read_order_match_audit_rows(order_module.DB_CLIENT, client_order_id)
    while (not ledger_rows or not audit_rows) and time.monotonic() < deadline:
        time.sleep(0.25)
        ledger_rows = order_module.get_fills_by_order(client_order_id) or []
        audit_rows = _read_order_match_audit_rows(
            order_module.DB_CLIENT,
            client_order_id,
        )
    require(bool(ledger_rows), "fill_ledger_ws_rows_missing")
    require(bool(audit_rows), "order_match_audit_rows_missing")
    require(
        all(str(row.get("reconciliation_status") or "") == "WS_DERIVED" for row in ledger_rows),
        "fill_ledger_not_clean_ws_derived_before_reconciliation",
    )

    joined = order_module.DB_CLIENT.execute_query(
        """
        SELECT fl.derived_trade_key, fl.instrument, fl.side,
               fl.quantity AS ledger_quantity, fl.price AS ledger_price,
               fl.fees AS ledger_fees, fl.reconciliation_status,
               oma.snapshot_seq, oma.cumulative_quantity,
               oma.filled_value, oma.total_fees, oma.number_of_fills,
               oma.status AS audit_status,
               oma.derived_size_delta, oma.derived_value_delta,
               oma.derived_fee_delta, oma.derived_price,
               oma.emitted_fill_ledger_row, oma.raw_payload_json
          FROM fill_ledger fl
          JOIN order_match_audit oma
            ON oma.client_order_id = fl.client_order_id
           AND oma.derived_trade_key = fl.derived_trade_key
         WHERE fl.client_order_id = %s
         ORDER BY oma.snapshot_seq ASC
        """,
        (client_order_id,),
    ) or []
    joined = [dict(row) for row in joined]
    match_audits = [row for row in audit_rows if row.get("derived_trade_key")]
    require(len(joined) == len(ledger_rows) == len(match_audits), "fill_ledger_match_audit_join_not_bijective")

    prior_cumulative = Decimal("0")
    for row in joined:
        raw = _raw_payload(row.get("raw_payload_json"))
        require(str(raw.get("client_order_id") or "") == client_order_id, "match_audit_raw_client_order_id_mismatch")
        require(str(raw.get("product_id") or "") == PRODUCT_ID, "match_audit_raw_product_mismatch")
        require(str(raw.get("side") or raw.get("order_side") or "").upper() == "BUY", "match_audit_raw_side_mismatch")
        require(str(raw.get("retail_portfolio_id") or "") == portfolio_id, "match_audit_raw_portfolio_mismatch")
        require(row.get("emitted_fill_ledger_row") is True, "match_audit_fill_ledger_emission_unproven")
        require(str(row.get("instrument") or "") == PRODUCT_ID, "fill_ledger_product_mismatch")
        require(str(row.get("side") or "").upper() == "BUY", "fill_ledger_side_mismatch")
        ledger_quantity = Decimal(str(row.get("ledger_quantity") or "0"))
        ledger_price = Decimal(str(row.get("ledger_price") or "0"))
        ledger_fees = Decimal(str(row.get("ledger_fees") or "0"))
        audit_quantity = Decimal(str(row.get("derived_size_delta") or "0"))
        audit_price = Decimal(str(row.get("derived_price") or "0"))
        audit_fees = Decimal(str(row.get("derived_fee_delta") or "0"))
        require(abs(ledger_quantity - audit_quantity) <= Decimal("0.00000001"), "fill_ledger_match_audit_quantity_mismatch")
        require(abs(ledger_price - audit_price) <= Decimal("0.00000001"), "fill_ledger_match_audit_price_mismatch")
        require(abs(ledger_fees - audit_fees) <= Decimal("0.00000001"), "fill_ledger_match_audit_fee_mismatch")
        cumulative = Decimal(str(row.get("cumulative_quantity") or "0"))
        require(cumulative > prior_cumulative, "match_audit_cumulative_quantity_not_increasing")
        require(abs((cumulative - prior_cumulative) - audit_quantity) <= Decimal("0.00000001"), "match_audit_cumulative_delta_mismatch")
        raw_cumulative = resolve_cumulative_filled(raw)
        require(
            abs(Decimal(str(raw_cumulative)) - cumulative)
            <= Decimal("0.00000001"),
            "match_audit_raw_cumulative_quantity_mismatch",
        )
        raw_filled_value = Decimal(str(raw.get("filled_value") or "0"))
        raw_total_fees = Decimal(str(raw.get("total_fees") or "0"))
        raw_effective_price = Decimal(
            str(
                raw.get("avg_price")
                or raw.get("limit_price")
                or raw.get("price")
                or "0"
            )
        )
        require(
            abs(raw_filled_value - Decimal(str(row.get("filled_value") or "0")))
            <= Decimal("0.00000001"),
            "match_audit_raw_filled_value_mismatch",
        )
        require(
            abs(raw_total_fees - Decimal(str(row.get("total_fees") or "0")))
            <= Decimal("0.00000001"),
            "match_audit_raw_total_fees_mismatch",
        )
        require(
            abs(raw_effective_price - audit_price) <= Decimal("0.00000001"),
            "match_audit_raw_effective_price_mismatch",
        )
        require(
            int(raw.get("number_of_fills") or 0)
            == int(row.get("number_of_fills") or 0),
            "match_audit_raw_number_of_fills_mismatch",
        )
        require(
            str(raw.get("status") or "").upper()
            == str(row.get("audit_status") or "").upper(),
            "match_audit_raw_status_mismatch",
        )
        deterministic_key = str(
            uuid5(
                NAMESPACE_OID,
                f"coinbase-fill:{client_order_id}:{raw_cumulative}",
            )
        )
        require(str(row.get("derived_trade_key") or "") == deterministic_key, "fill_ledger_deterministic_key_mismatch")
        prior_cumulative = cumulative
    require(abs(prior_cumulative - expected_filled_size) <= Decimal("0.00000001"), "match_audit_cumulative_filled_size_mismatch")

    rest_fills, pagination = _read_exact_rest_fill_pages(
        rest_client,
        exchange_order_id=exchange_order_id,
        portfolio_id=portfolio_id,
    )
    require(bool(rest_fills), "exact_rest_fills_missing")
    normalized_rest: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for fill in rest_fills:
        require(str(fill.get("order_id") or "") == exchange_order_id, "exact_rest_fill_order_id_mismatch")
        require(str(fill.get("retail_portfolio_id") or "") == portfolio_id, "exact_rest_fill_portfolio_mismatch")
        require(str(fill.get("product_id") or "") == PRODUCT_ID, "exact_rest_fill_product_mismatch")
        require(str(fill.get("side") or "").upper() == "BUY", "exact_rest_fill_side_mismatch")
        require(_normalized_false(fill.get("size_in_quote"), blocker="exact_rest_fill_size_in_quote_invalid"), "exact_rest_fill_size_in_quote_true")
        trade_id = str(fill.get("trade_id") or "")
        entry_id = str(fill.get("entry_id") or "")
        require(bool(trade_id) and bool(entry_id), "exact_rest_fill_identity_missing")
        require(len(entry_id) <= 80, "exact_rest_fill_entry_id_too_long")
        pair = (trade_id, entry_id)
        require(pair not in seen_pairs, "exact_rest_fill_identity_pair_duplicate")
        seen_pairs.add(pair)
        size = Decimal(str(fill.get("size") or "0"))
        price = Decimal(str(fill.get("price") or "0"))
        commission = Decimal(str(fill.get("commission") or ""))
        require(size.is_finite() and size > 0, "exact_rest_fill_size_invalid")
        require(price.is_finite() and price > 0, "exact_rest_fill_price_invalid")
        require(commission.is_finite() and commission >= 0, "exact_rest_fill_commission_invalid")
        normalized_rest.append(
            {
                **fill,
                "trade_id": trade_id,
                "entry_id": entry_id,
                "_size_decimal": size,
                "_price_decimal": price,
                "_fee_decimal": commission,
            }
        )

    remaining_rest = list(normalized_rest)
    expected_pairs: dict[str, tuple[str, str]] = {}
    for row in joined:
        ledger_quantity = Decimal(str(row.get("ledger_quantity") or "0"))
        ledger_price = Decimal(str(row.get("ledger_price") or "0"))
        ledger_fees = Decimal(str(row.get("ledger_fees") or "0"))
        candidates = [
            fill
            for fill in remaining_rest
            if abs(fill["_size_decimal"] - ledger_quantity) <= Decimal("0.00000001")
            and abs(fill["_price_decimal"] - ledger_price) <= Decimal("0.01")
            and abs(fill["_fee_decimal"] - ledger_fees) <= Decimal("0.00000001")
        ]
        require(len(candidates) == 1, "fill_ledger_rest_bijection_ambiguous_or_missing")
        matched_fill = candidates[0]
        remaining_rest.remove(matched_fill)
        expected_pairs[str(row["derived_trade_key"])] = (
            str(matched_fill["trade_id"]),
            str(matched_fill["entry_id"]),
        )
    require(not remaining_rest, "fill_ledger_rest_bijection_unmatched_rest")

    rest_quantity = sum((fill["_size_decimal"] for fill in normalized_rest), Decimal("0"))
    rest_value = sum((fill["_size_decimal"] * fill["_price_decimal"] for fill in normalized_rest), Decimal("0"))
    rest_fees = sum((fill["_fee_decimal"] for fill in normalized_rest), Decimal("0"))
    ledger_quantity = sum((Decimal(str(row.get("ledger_quantity") or "0")) for row in joined), Decimal("0"))
    ledger_value = sum((Decimal(str(row.get("ledger_quantity") or "0")) * Decimal(str(row.get("ledger_price") or "0")) for row in joined), Decimal("0"))
    ledger_fees = sum((Decimal(str(row.get("ledger_fees") or "0")) for row in joined), Decimal("0"))
    require(abs(rest_quantity - expected_filled_size) <= Decimal("0.00000001"), "exact_rest_fill_quantity_total_mismatch")
    require(abs(ledger_quantity - rest_quantity) <= Decimal("0.00000001"), "fill_ledger_quantity_total_mismatch")
    require(abs(rest_value - expected_filled_value) <= Decimal("0.01"), "exact_rest_fill_value_total_mismatch")
    require(abs(ledger_value - rest_value) <= Decimal("0.01"), "fill_ledger_value_total_mismatch")
    require(abs(rest_fees - expected_total_fees) <= Decimal("0.00000001"), "exact_rest_fill_fee_total_mismatch")
    require(abs(ledger_fees - rest_fees) <= Decimal("0.00000001"), "fill_ledger_fee_total_mismatch")

    clean_rest_rows = [
        {
            key: value
            for key, value in fill.items()
            if not key.startswith("_")
        }
        for fill in normalized_rest
    ]

    def fills_fetcher(candidate_exchange_order_id: str) -> list[dict[str, Any]]:
        require(candidate_exchange_order_id == exchange_order_id, "fill_reconciler_exchange_identity_drift")
        return [dict(fill) for fill in clean_rest_rows]

    report = FillReconciler(
        order_module.DB_CLIENT,
        fills_fetcher,
    ).reconcile_order(client_order_id, exchange_order_id)
    require(report.is_clean and not report.ws_unmatched and not report.rest_unmatched, "fill_reconciler_report_not_clean")
    require(len(report.matched) == len(clean_rest_rows), "fill_reconciler_match_count_mismatch")
    require(report.rows_updated == len(clean_rest_rows), "fill_reconciler_update_count_mismatch")
    reconciled = order_module.get_fills_by_order(client_order_id) or []
    require(len(reconciled) == len(clean_rest_rows), "fill_ledger_reconciled_count_mismatch")
    require(all(str(row.get("reconciliation_status") or "") == "RECONCILED" for row in reconciled), "fill_ledger_status_not_reconciled")
    actual_pairs = {
        str(row.get("derived_trade_key") or ""): (
            str(row.get("exchange_trade_id") or ""),
            str(row.get("exchange_entry_id") or ""),
        )
        for row in reconciled
    }
    require(actual_pairs == expected_pairs, "fill_ledger_reconciled_identity_pairs_mismatch")
    return {
        "status": "clean_reconciled",
        "rest_fill_count": len(clean_rest_rows),
        "ledger_fill_count": len(reconciled),
        "identity_pairs": sorted(
            [list(pair) for pair in expected_pairs.values()]
        ),
        "rest_quantity": decimal_text(rest_quantity),
        "rest_value": decimal_text(rest_value),
        "rest_fee_total": decimal_text(rest_fees),
        "ledger_quantity": decimal_text(ledger_quantity),
        "ledger_value": decimal_text(ledger_value),
        "ledger_fee_total": decimal_text(ledger_fees),
        "rows_updated": report.rows_updated,
        "reconciliation_statuses": ["RECONCILED"],
        **pagination,
    }


def _cross_check_fill_readback_evidence(
    fill_readback: Mapping[str, Any],
    *,
    exchange_order: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> dict[str, Any]:
    """Cross-bind Admin, exact get_order, raw REST fills, and local ledger totals."""

    api_count = int(fill_readback.get("fill_count") or 0)
    rest_count = int(reconciliation.get("rest_fill_count") or 0)
    ledger_count = int(reconciliation.get("ledger_fill_count") or 0)
    require(api_count == rest_count == ledger_count and api_count > 0, "fill_readback_count_crosscheck_mismatch")
    require(fill_readback.get("fills_have_more_pages") is False, "fill_readback_pagination_incomplete")
    for count_field in ("fill_trade_id_present_count", "fill_entry_id_present_count"):
        if count_field in fill_readback:
            require(int(fill_readback.get(count_field) or 0) == rest_count, f"fill_readback_{count_field}_mismatch")

    api_notional = Decimal(str(fill_readback.get("executed_notional_usdc") or "0"))
    exchange_value = Decimal(str(exchange_order.get("filled_value") or "0"))
    rest_value = Decimal(str(reconciliation.get("rest_value") or "0"))
    require(abs(api_notional - exchange_value) <= Decimal("0.01"), "fill_readback_get_order_notional_mismatch")
    require(abs(api_notional - rest_value) <= Decimal("0.01"), "fill_readback_rest_notional_mismatch")

    exchange_size = Decimal(str(exchange_order.get("filled_size") or "0"))
    rest_size = Decimal(str(reconciliation.get("rest_quantity") or "0"))
    require(abs(exchange_size - rest_size) <= Decimal("0.00000001"), "fill_readback_get_order_rest_size_mismatch")
    exchange_fee = Decimal(
        str(exchange_order.get("total_fees") or exchange_order.get("fee") or "0")
    )
    rest_fee = Decimal(str(reconciliation.get("rest_fee_total") or "0"))
    require(abs(exchange_fee - rest_fee) <= Decimal("0.00000001"), "fill_readback_get_order_rest_fee_mismatch")
    if exchange_order.get("number_of_fills") not in (None, ""):
        require(int(exchange_order["number_of_fills"]) == rest_count, "get_order_number_of_fills_mismatch")
    for field in ("filled_size", "fill_size", "filled_quantity"):
        if field in fill_readback and fill_readback.get(field) not in (None, ""):
            require(
                abs(Decimal(str(fill_readback[field])) - rest_size)
                <= Decimal("0.00000001"),
                f"fill_readback_{field}_mismatch",
            )
    for field in ("total_fees", "fee", "commission"):
        if field in fill_readback and fill_readback.get(field) not in (None, ""):
            require(
                abs(Decimal(str(fill_readback[field])) - rest_fee)
                <= Decimal("0.00000001"),
                f"fill_readback_{field}_mismatch",
            )
    return {
        "fill_count": rest_count,
        "filled_size": decimal_text(rest_size),
        "executed_notional_usdc": decimal_text(rest_value),
        "total_fees": decimal_text(rest_fee),
        "admin_get_order_rest_ledger_bound": True,
    }


def _raise_on_critical_chain_state(chain: Mapping[str, Any]) -> None:
    """Fail immediately on authorization/duplication states that cannot be polled."""

    duplicate_ids = list_value(chain.get("duplicate_child_client_order_ids"))
    nested_child_ids = list_value(chain.get("nested_child_client_order_ids"))
    nested_parent_ids = list_value(chain.get("nested_parent_client_order_ids"))
    require(not duplicate_ids, "critical_automatic_child_duplicate_detected")
    require(not nested_child_ids, "critical_automatic_child_nested_detected")
    require(not nested_parent_ids, "critical_automatic_child_nested_parent_detected")
    require(
        int(chain.get("flat_hierarchy_violation_count") or 0) == 0,
        "critical_automatic_child_flat_hierarchy_violation",
    )
    require(
        int(chain.get("follow_up_child_count") or 0) <= 1,
        "critical_automatic_child_count_exceeded_one",
    )
    for child in [
        object_record(item) for item in list_value(chain.get("follow_up_children"))
    ]:
        require(
            not str(child.get("exchange_order_id") or "").strip(),
            "critical_child_exchange_order_id_present",
        )
        status = str(child.get("status") or "").upper()
        require(
            status in {"", "HIDDEN", "PENDING", "TRIGGERED"},
            f"critical_child_reveal_or_lifecycle_status:{status}",
        )
        lifecycle_event = str(child.get("last_lifecycle_event") or "").upper()
        require(
            lifecycle_event
            not in {
                "REVEAL_SUCCEEDED",
                "PLACEMENT_SUCCEEDED",
                "FILL_RECEIVED",
                "EXECUTED",
                "ORDER_PLACED",
            },
            f"critical_child_reveal_lifecycle_event:{lifecycle_event}",
        )


def _chain_validation_failure_is_transient(reason: str) -> bool:
    return reason in {
        "operator_chain_missing",
        "automatic_child_count_not_one",
        "automatic_child_identity_missing",
        "chain_root_missing",
        "chain_root_not_filled",
        "automatic_child_row_count_not_one",
        "automatic_fill_claim_not_done",
        "automatic_fill_audit_child_mismatch",
        "automatic_fill_audit_count_mismatch",
        "automatic_fill_decision_mismatch",
        "automatic_child_placement_blocker_pending",
    }


def _validate_automatic_hidden_child_chain(
    chain: Mapping[str, Any],
    *,
    root_client_order_id: str,
    portfolio_id: str,
    expected_filled_size: Decimal,
    expected_placement_correlation_id: str,
    expected_admission_audit_id: str,
    expected_exchange_order_id: str,
) -> dict[str, Any]:
    _raise_on_critical_chain_state(chain)
    require(chain.get("type") == "admin_order_fill_follow_up_chain", "chain_type_mismatch")
    require(chain.get("found") is True, "operator_chain_missing")
    require(chain.get("client_order_id") == root_client_order_id, "operator_chain_identity_mismatch")
    require(chain.get("root_parent_client_order_id") == root_client_order_id, "operator_chain_root_identity_mismatch")
    require(chain.get("follow_up_child_count") == 1, "automatic_child_count_not_one")
    child_ids = [str(item) for item in list_value(chain.get("follow_up_child_client_order_ids"))]
    require(len(child_ids) == 1 and bool(child_ids[0]), "automatic_child_identity_missing")
    require(not list_value(chain.get("duplicate_child_client_order_ids")), "automatic_child_duplicate_detected")
    require(not list_value(chain.get("nested_child_client_order_ids")), "automatic_child_nested_detected")
    require(not list_value(chain.get("nested_parent_client_order_ids")), "automatic_child_nested_parent_detected")
    require(int(chain.get("flat_hierarchy_violation_count") or 0) == 0, "automatic_child_flat_hierarchy_violation")
    require(chain.get("order_parent_child_read_ran") is True, "automatic_child_parent_child_read_not_run")
    require(chain.get("stealth_child_read_ran") is True, "automatic_child_stealth_read_not_run")
    chain_blockers = list_value(chain.get("blockers"))
    require(
        chain_blockers
        in (
            [],
            [f"follow_up_child_placement_blocked:{child_ids[0]}"],
        ),
        "automatic_child_chain_blockers_mismatch",
    )

    root = object_record(chain.get("root_order"))
    require(root.get("client_order_id") == root_client_order_id, "chain_root_missing")
    require(str(root.get("status") or "").upper() == "FILLED", "chain_root_not_filled")
    require(root.get("ownership_provenance") == "ADMIN_MANUAL_ROOT", "chain_root_provenance_mismatch")
    require(root.get("retail_portfolio_id") == portfolio_id, "chain_root_portfolio_mismatch")
    require(root.get("parent_client_order_id") in {None, ""}, "chain_root_parent_present")
    root_correlation_id = str(root.get("correlation_id") or "").strip()
    root_audit_id = str(root.get("audit_id") or "").strip()
    require(root_correlation_id == expected_placement_correlation_id, "chain_root_correlation_mismatch")
    require(root_audit_id == expected_admission_audit_id, "chain_root_audit_mismatch")
    require(
        str(root.get("exchange_order_id") or root.get("coinbase_order_id") or "")
        == expected_exchange_order_id,
        "chain_root_exchange_order_id_mismatch",
    )

    children = [object_record(item) for item in list_value(chain.get("follow_up_children"))]
    require(len(children) == 1, "automatic_child_row_count_not_one")
    child = children[0]
    require(child.get("client_order_id") == child_ids[0], "automatic_child_id_mismatch")
    require(child.get("product_id") == PRODUCT_ID, "automatic_child_product_mismatch")
    require(str(child.get("side") or "").upper() == "SELL", "automatic_child_side_mismatch")
    child_status = str(
        child.get("stealth_status") or child.get("status") or ""
    ).upper()
    require(
        child_status in {"HIDDEN", "PENDING", "TRIGGERED"},
        "automatic_child_not_preexchange",
    )
    require(child.get("ownership_provenance") == "ADMIN_FILL_FOLLOW_UP", "automatic_child_provenance_mismatch")
    require(child.get("parent_client_order_id") == root_client_order_id, "automatic_child_parent_mismatch")
    require(child.get("retail_portfolio_id") == portfolio_id, "automatic_child_portfolio_mismatch")
    require(not str(child.get("exchange_order_id") or "").strip(), "critical_child_exchange_order_id_present")
    require(str(child.get("correlation_id") or "").strip() == expected_placement_correlation_id, "automatic_child_correlation_mismatch")
    require(str(child.get("audit_id") or "").strip() == expected_admission_audit_id, "automatic_child_audit_mismatch")
    require(
        Decimal(str(child.get("size") or "0")) == expected_filled_size,
        "automatic_child_size_mismatch",
    )
    require(Decimal(str(child.get("price") or "0")) > 0, "automatic_child_price_invalid")

    scope = object_record(chain.get("portfolio_scope"))
    require(scope.get("scope_consistent") is True, "automatic_child_portfolio_scope_inconsistent")
    require(scope.get("status") == "matched", "automatic_child_portfolio_scope_blocked")
    audit = object_record(chain.get("fill_follow_up_decision_audit"))
    require(
        audit.get("automatic_fill_event_processing_enabled") is True,
        "automatic_fill_event_processing_not_enabled",
    )
    require(
        audit.get("automation_mode") == "automatic_owned_root_fill_event",
        "automatic_fill_event_mode_mismatch",
    )
    require(audit.get("claim_state") == "done", "automatic_fill_claim_not_done")
    require(
        audit.get("existing_follow_up_client_order_ids") == child_ids,
        "automatic_fill_audit_child_mismatch",
    )
    require(audit.get("existing_follow_up_count") == 1, "automatic_fill_audit_count_mismatch")
    require(
        audit.get("follow_up_decision") == "automatic_child_created",
        "automatic_fill_decision_mismatch",
    )
    require(chain.get("read_only") is True, "chain_not_read_only")
    require(chain.get("live_coinbase_orders_ran") is False, "chain_live_order_flag")
    require(chain.get("local_state_mutated") is False, "chain_local_mutation_flag")
    require(chain.get("exchange_state_mutated") is False, "chain_exchange_mutation_flag")
    return child


def _validate_hidden_child_detail(
    detail: Mapping[str, Any],
    *,
    child_id: str,
    root_client_order_id: str,
    expected_filled_size: Decimal,
) -> dict[str, Any]:
    require(detail.get("type") == "admin_stealth_order_detail", "stealth_detail_type_mismatch")
    require(detail.get("found") is True, "stealth_child_not_found")
    order = object_record(detail.get("order"))
    require(order.get("stealth_order_id") == child_id, "stealth_child_identity_mismatch")
    require(order.get("parent_stealth_order_id") == root_client_order_id, "stealth_child_parent_mismatch")
    require(order.get("product_id") == PRODUCT_ID, "stealth_child_product_mismatch")
    require(str(order.get("side") or "").upper() == "SELL", "stealth_child_side_mismatch")
    require(
        str(order.get("status") or "").upper()
        in {"HIDDEN", "PENDING", "TRIGGERED"},
        "stealth_child_status_mismatch",
    )
    require(
        Decimal(str(order.get("total_size") or "0")) == expected_filled_size,
        "stealth_child_total_size_mismatch",
    )
    require(not str(order.get("active_placement_client_order_id") or "").strip(), "critical_child_active_placement_present")
    require(not str(order.get("active_exchange_order_id") or "").strip(), "critical_child_active_exchange_id_present")
    require(not list_value(order.get("revealed_orders")), "critical_child_revealed_order_present")
    require(Decimal(str(order.get("revealed_size") or "0")) == 0, "critical_child_revealed_size_nonzero")
    require(
        str(order.get("last_lifecycle_event") or "").upper()
        in {
            "",
            "CREATED",
            "PENDING",
            "TRIGGERED",
            "CONDITION_MET",
            "REVEAL_TRIGGERED",
            "PLACEMENT_BLOCKED",
        },
        "critical_child_lifecycle_event_not_hidden_safe",
    )
    submission_audit = object_record(detail.get("reveal_submission_audit"))
    require(submission_audit.get("coinbase_order_submit_ran") is False, "critical_child_reveal_submit_recorded")
    require(submission_audit.get("active_placement_created") is False, "critical_child_reveal_placement_created")
    require(detail.get("read_only") is True, "stealth_detail_not_read_only")
    require(detail.get("live_coinbase_orders_ran") is False, "stealth_detail_live_order_flag")
    return order


def _validate_intentional_fill_acceptance(
    response: Mapping[str, Any],
    *,
    place_proofs: Mapping[str, str],
    place_headers: Mapping[str, str],
    order_body: Mapping[str, Any],
    portfolio_id: str,
    exchange_order_id: str,
) -> dict[str, Any]:
    """Bind the accepted command to the exact proofs and fee-safe override."""

    admission = object_record(response.get("admission_decision"))
    require(
        response.get("correlation_id") == place_headers.get("X-Correlation-Id"),
        "accepted_response_correlation_mismatch",
    )
    require(
        response.get("idempotency_key") == place_headers.get("Idempotency-Key"),
        "accepted_response_idempotency_mismatch",
    )
    require(response.get("submission_event_recorded") is True, "accepted_submission_event_not_recorded")
    require(response.get("coinbase_order_id") == exchange_order_id, "accepted_response_exchange_id_mismatch")
    require(admission.get("allowed") is True, "accepted_admission_not_allowed")
    expected_bindings = {
        "approval_snapshot_id": place_proofs["approval_id"],
        "admission_audit_id": place_proofs["admission_audit_id"],
        "cap_guard_decision_id": place_proofs["cap_guard_decision_id"],
        "reconciliation_plan_id": place_proofs["reconciliation_plan_id"],
    }
    for field, expected in expected_bindings.items():
        require(admission.get(field) == expected, f"accepted_admission_binding_mismatch:{field}")
    require(bool(str(response.get("audit_id") or "").strip()), "accepted_command_audit_id_missing")
    guard_admission = object_record(object_record(response.get("guard")).get("admission_decision"))
    for field, expected in expected_bindings.items():
        require(guard_admission.get(field) == expected, f"accepted_guard_admission_binding_mismatch:{field}")
    require(
        admission.get("operator_intent") == INTENTIONAL_FILL_OPERATOR_INTENT,
        "accepted_admission_operator_intent_mismatch",
    )
    require(
        admission.get("identity_value") == order_body["client_order_id"],
        "accepted_admission_identity_mismatch",
    )

    portfolio_scope = object_record(response.get("portfolio_scope"))
    require(portfolio_scope.get("scope_consistent") is True, "accepted_portfolio_scope_inconsistent")
    require(portfolio_scope.get("portfolio_id") == portfolio_id, "accepted_portfolio_id_mismatch")
    proof_bindings = object_record(portfolio_scope.get("proof_bindings"))
    for field, expected in expected_bindings.items():
        require(proof_bindings.get(field) == expected, f"accepted_scope_binding_mismatch:{field}")

    data = object_record(response.get("data"))
    active_limit = object_record(data.get("active_order_limit"))
    require(active_limit.get("allowed") is True, "accepted_active_order_limit_not_allowed")
    require(active_limit.get("open_order_count") == 0, "accepted_active_order_limit_not_zero")
    require(active_limit.get("open_client_order_ids") == [], "accepted_active_order_id_list_not_empty")
    require(active_limit.get("cancel_before_next") is True, "accepted_active_order_cancel_policy_missing")
    require(active_limit.get("blocker") is None, "accepted_active_order_limit_blocked")
    require(active_limit.get("authoritative") is True, "accepted_active_order_limit_not_authoritative")
    require(active_limit.get("pagination_complete") is True, "accepted_active_order_limit_pagination_incomplete")
    require(int(active_limit.get("page_count") or 0) >= 1, "accepted_active_order_limit_page_count_invalid")
    require(active_limit.get("order_count") == 0, "accepted_active_order_limit_order_count_not_zero")
    standing = object_record(data.get("standing_price_limit"))
    override = object_record(standing.get("intentional_fill_override"))
    require(override.get("requested") is True, "intentional_fill_override_not_requested")
    require(override.get("allowed") is True, "intentional_fill_override_not_allowed")
    require(override.get("blocker") is None, "intentional_fill_override_blocked")
    require(override.get("approval_snapshot_id") == expected_bindings["approval_snapshot_id"], "intentional_fill_override_approval_mismatch")
    require(override.get("admission_audit_id") == expected_bindings["admission_audit_id"], "intentional_fill_override_audit_mismatch")
    require(override.get("cap_guard_decision_id") == expected_bindings["cap_guard_decision_id"], "intentional_fill_override_cap_mismatch")
    require(override.get("profile_alias") == PROFILE_LABEL, "intentional_fill_override_profile_mismatch")
    require(override.get("portfolio_id") == portfolio_id, "intentional_fill_override_portfolio_mismatch")
    require(override.get("product_id") == PRODUCT_ID, "intentional_fill_override_product_mismatch")
    require(override.get("side") == "BUY", "intentional_fill_override_side_mismatch")
    require(override.get("order_type") == "LIMIT", "intentional_fill_override_type_mismatch")
    require(override.get("time_in_force") == "FILL_OR_KILL", "intentional_fill_override_tif_mismatch")
    require(override.get("post_only") is False, "intentional_fill_override_post_only_mismatch")
    require(override.get("marketable") is True, "intentional_fill_override_not_marketable")
    require(override.get("child_exchange_reveal_authorized") is False, "intentional_fill_override_child_reveal_authorized")
    filled_capability = object_record(override.get("filled_follow_up_capability"))
    partial_capability = object_record(override.get("partial_fill_follow_up_capability"))
    cancelled_capability = object_record(override.get("cancelled_follow_up_capability"))
    reveal_capability = object_record(override.get("stealth_reveal_capability"))
    require(filled_capability.get("mode") == "conditional" and filled_capability.get("allowed") is True, "intentional_fill_override_filled_capability_mismatch")
    require(partial_capability.get("mode") == "disabled", "intentional_fill_override_partial_capability_mismatch")
    require(cancelled_capability.get("mode") == "disabled", "intentional_fill_override_cancel_capability_mismatch")
    require(reveal_capability.get("mode") == "disabled" and reveal_capability.get("allowed") is False, "intentional_fill_override_reveal_capability_mismatch")
    follow_up_policy = object_record(override.get("follow_up_policy"))
    require(follow_up_policy.get("intent") == "exit" and follow_up_policy.get("allowed") is True, "intentional_fill_override_follow_up_intent_mismatch")
    wallet_policy = object_record(override.get("wallet_policy"))
    require(wallet_policy.get("check_follow_up_planning") is False, "intentional_fill_override_wallet_planning_mismatch")
    require(wallet_policy.get("enabled") is True and wallet_policy.get("fail_open_on_fetch_error") is False, "intentional_fill_override_wallet_policy_mismatch")

    requested_price = Decimal(str(override.get("requested_limit_price") or "0"))
    requested_size = Decimal(str(override.get("base_size") or "0"))
    planned_notional = Decimal(str(override.get("planned_notional_usdc") or "0"))
    approved_cap = Decimal(str(override.get("approved_max_notional_usdc") or "0"))
    best_bid = Decimal(str(override.get("best_bid") or "0"))
    best_ask = Decimal(str(override.get("best_ask") or "0"))
    require(requested_price == Decimal(str(order_body["limit_price"])), "intentional_fill_override_limit_price_mismatch")
    require(requested_size == Decimal(str(order_body["base_size"])), "intentional_fill_override_base_size_mismatch")
    require(planned_notional == requested_price * requested_size, "intentional_fill_override_notional_product_mismatch")
    require(
        Decimal("0") < planned_notional <= ROOT_SUBMITTED_CAP
        and planned_notional < Decimal("10"),
        "intentional_fill_override_notional_cap_mismatch",
    )
    require(
        approved_cap == ROOT_SUBMITTED_CAP,
        "intentional_fill_override_approved_cap_mismatch",
    )
    require(best_bid > 0 and best_ask >= best_bid, "intentional_fill_override_market_invalid")
    require(best_ask <= requested_price <= best_ask * MAX_ASK_RATIO, "intentional_fill_override_ask_band_mismatch")
    require(override.get("maximum_ask_ratio") == decimal_text(MAX_ASK_RATIO), "intentional_fill_override_maximum_ask_ratio_mismatch")
    require(override.get("market_source") in {"ticker", "coinbase_rest_best_bid"}, "intentional_fill_override_market_source_mismatch")
    observed_at = str(override.get("market_observed_at") or "").strip()
    require(bool(observed_at), "intentional_fill_override_market_observed_at_missing")
    try:
        observed_datetime = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProofFailure("intentional_fill_override_market_observed_at_invalid") from exc
    require(observed_datetime.tzinfo is not None, "intentional_fill_override_market_observed_at_timezone_missing")
    observed_age = (datetime.now(timezone.utc) - observed_datetime).total_seconds()
    require(0 <= observed_age <= 30, "intentional_fill_override_market_observed_at_stale")

    target = object_record(override.get("follow_up_target_movement"))
    require(target.get("ready") is True, "intentional_fill_fee_target_not_ready")
    require(target.get("blocker") is None, "intentional_fill_fee_target_blocked")
    require(target.get("source") == "runtime_fee_manager_profit_validator", "intentional_fill_fee_target_source_mismatch")
    require(target.get("profitability_preflight_passed") is True, "intentional_fill_profitability_unproven")
    require(target.get("filled_follow_up_replacement_enabled") is True, "intentional_fill_replacement_unproven")
    require(object_record(target.get("fee_freshness")).get("is_fresh") is True, "intentional_fill_fee_freshness_unproven")
    target_movement = Decimal(str(target.get("target_movement") or "0"))
    fee_rate = Decimal(str(target.get("fee_rate") or "0"))
    require(target_movement.is_finite() and Decimal("0") < target_movement <= Decimal("0.05"), "intentional_fill_fee_target_invalid")
    require(fee_rate.is_finite() and Decimal("0") < fee_rate < Decimal("1"), "intentional_fill_fee_rate_invalid")

    registration = object_record(data.get("root_registration"))
    require(registration.get("registered") is True, "accepted_root_registration_missing")
    require(registration.get("client_order_id") == order_body["client_order_id"], "accepted_root_registration_identity_mismatch")
    require(registration.get("retail_portfolio_id") == portfolio_id, "accepted_root_registration_portfolio_mismatch")
    require(registration.get("ownership_provenance") == "ADMIN_MANUAL_ROOT", "accepted_root_registration_provenance_mismatch")
    require(registration.get("target_movement_source") == "fee_aware_intentional_fill_target", "accepted_root_target_source_mismatch")
    require(Decimal(str(registration.get("target_movement") or "0")) == target_movement, "accepted_root_target_mismatch")
    submission = object_record(data.get("submission_attempt"))
    require(submission.get("outcome") == "accepted", "accepted_submission_outcome_mismatch")
    require(submission.get("authoritative_readback_confirmed") is True, "accepted_submission_readback_unproven")
    require(submission.get("exchange_order_id") == exchange_order_id, "accepted_submission_exchange_id_mismatch")
    require(submission.get("exchange_order_id_confirmed") is True, "accepted_submission_exchange_id_unconfirmed")
    readback = object_record(submission.get("readback"))
    require(readback.get("authoritative") is True, "accepted_submission_readback_not_authoritative")
    require(readback.get("page_count") == 1, "accepted_submission_readback_page_count_mismatch")
    require(readback.get("order_count") == 1, "accepted_submission_readback_order_count_mismatch")
    require(readback.get("pagination_complete") is True, "accepted_submission_readback_pagination_incomplete")
    require(readback.get("read_method") == "get_order", "accepted_submission_readback_method_mismatch")
    require(readback.get("client_order_id") == order_body["client_order_id"], "accepted_submission_readback_client_id_mismatch")
    require(readback.get("exchange_order_id") == exchange_order_id, "accepted_submission_readback_exchange_id_mismatch")
    require(readback.get("exact_identity_match") is True, "accepted_submission_readback_identity_unproven")
    require(readback.get("confirmed_absent") is False, "accepted_submission_readback_marked_absent")
    matched_order = readback.get("matched_order")
    require(isinstance(matched_order, Mapping), "accepted_submission_matched_order_missing")
    validated_matched_order = _validate_exact_coinbase_fok_order(
        matched_order,
        expected_exchange_order_id=exchange_order_id,
        expected_client_order_id=str(order_body["client_order_id"]),
        expected_portfolio_id=portfolio_id,
        expected_order_body=order_body,
    )
    require(
        readback.get("authoritative_status")
        == str(validated_matched_order.get("status") or "").upper(),
        "accepted_submission_readback_status_mismatch",
    )
    return {
        "admission": admission,
        "intentional_fill_override": override,
        "follow_up_target_movement": target,
        "root_registration": registration,
        "active_order_limit": active_limit,
        "submission_readback": readback,
    }


def _prove_terminal_no_fill_locally_and_authoritatively(
    runtime: AdminRuntime,
    *,
    rest_client: Any,
    client_order_id: str,
    exchange_order_id: str,
    expected_exchange_status: str,
) -> dict[str, Any]:
    """Require local terminal convergence and read-only zero-fill evidence."""

    local_payload: dict[str, Any] = {}
    local_order: dict[str, Any] = {}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        _, local_payload, _ = runtime.request(
            "GET",
            f"/orders/{client_order_id}",
            headers=runtime.headers(role="auditor"),
            expected={200},
        )
        local_order = object_record(local_payload.get("order"))
        if str(local_order.get("status") or "").upper() in NO_FILL_TERMINAL_STATUSES:
            break
        time.sleep(0.25)
    local_status = str(local_order.get("status") or "").upper()
    require(local_payload.get("found") is True, "terminal_no_fill_local_root_missing")
    require(local_status in NO_FILL_TERMINAL_STATUSES, "terminal_no_fill_local_root_not_terminal")
    require(local_status == expected_exchange_status, "terminal_no_fill_local_exchange_status_mismatch")
    require(local_order.get("client_order_id") == client_order_id, "terminal_no_fill_local_identity_mismatch")
    require(local_order.get("ownership_provenance") == "ADMIN_MANUAL_ROOT", "terminal_no_fill_local_provenance_mismatch")
    require(local_order.get("retail_portfolio_id") == runtime.portfolio_id, "terminal_no_fill_local_portfolio_mismatch")

    fill_headers = runtime.headers(
        idempotency_key=f"read-zero-fill-{client_order_id}",
        operator_intent="read_authoritative_terminal_zero_fill_evidence",
        role="auditor",
        correlation_id=f"corr-zero-fill-readback-{client_order_id}",
    )
    _, fill_readback, _ = runtime.request(
        "GET",
        f"/orders/{client_order_id}/fill-readback",
        headers=fill_headers,
        params={"product_id": PRODUCT_ID, "fill_limit": 100},
        expected={200},
    )
    require(fill_readback.get("status") == "passed", "terminal_no_fill_readback_failed")
    require(fill_readback.get("client_order_id") == client_order_id, "terminal_no_fill_readback_identity_mismatch")
    require(fill_readback.get("product_id") == PRODUCT_ID, "terminal_no_fill_readback_product_mismatch")
    require(fill_readback.get("exchange_order_id") == exchange_order_id, "terminal_no_fill_readback_exchange_id_mismatch")
    require(fill_readback.get("order_found") is True, "terminal_no_fill_readback_order_missing")
    fill_readback_status = str(fill_readback.get("order_status") or "").upper()
    require(fill_readback_status == local_status, "terminal_no_fill_readback_status_mismatch")
    require(int(fill_readback.get("fill_count") or 0) == 0, "terminal_no_fill_readback_fill_present")
    require(fill_readback.get("fill_trade_id_present_count") == 0, "terminal_no_fill_readback_trade_id_present")
    require(fill_readback.get("fill_entry_id_present_count") == 0, "terminal_no_fill_readback_entry_id_present")
    require(fill_readback.get("fills_have_more_pages") is False, "terminal_no_fill_readback_pagination_incomplete")
    require(fill_readback.get("fill_read_status") == "not_filled", "terminal_no_fill_readback_status_mismatch")
    require(Decimal(str(fill_readback.get("executed_notional_usdc") or "0")) == 0, "terminal_no_fill_readback_notional_nonzero")
    require(fill_readback.get("live_fill_readback_proof_recorded") is False, "terminal_no_fill_recorded_as_fill_proof")
    require(fill_readback.get("read_only") is True, "terminal_no_fill_readback_not_read_only")
    require(fill_readback.get("live_coinbase_read_ran") is True, "terminal_no_fill_coinbase_read_missing")
    require(fill_readback.get("live_coinbase_orders_ran") is False, "terminal_no_fill_readback_order_mutation")
    require(fill_readback.get("local_state_mutated") is False, "terminal_no_fill_readback_local_mutation")
    require(fill_readback.get("exchange_state_mutated") is False, "terminal_no_fill_readback_exchange_mutation")

    _, chain, _ = runtime.request(
        "GET",
        f"/orders/{client_order_id}/fill-follow-up/chain",
        headers=runtime.headers(role="auditor"),
        expected={200},
    )
    _raise_on_critical_chain_state(chain)
    require(chain.get("type") == "admin_order_fill_follow_up_chain", "terminal_no_fill_chain_type_mismatch")
    require(chain.get("found") is True, "terminal_no_fill_chain_root_missing")
    require(chain.get("client_order_id") == client_order_id, "terminal_no_fill_chain_identity_mismatch")
    require(chain.get("root_parent_client_order_id") == client_order_id, "terminal_no_fill_chain_root_identity_mismatch")
    require(int(chain.get("follow_up_child_count") or 0) == 0, "terminal_no_fill_unexpected_child")
    require(list_value(chain.get("follow_up_child_client_order_ids")) == [], "terminal_no_fill_child_id_present")
    require(list_value(chain.get("blockers")) == [], "terminal_no_fill_chain_blocked")
    require(chain.get("order_parent_child_read_ran") is True, "terminal_no_fill_parent_child_read_not_run")
    require(chain.get("stealth_child_read_ran") is True, "terminal_no_fill_stealth_child_read_not_run")
    chain_root = object_record(chain.get("root_order"))
    chain_root_status = str(chain_root.get("status") or "").upper()
    require(chain_root_status == local_status, "terminal_no_fill_chain_root_status_mismatch")
    require(chain_root.get("client_order_id") == client_order_id, "terminal_no_fill_chain_root_client_mismatch")
    require(chain_root.get("ownership_provenance") == "ADMIN_MANUAL_ROOT", "terminal_no_fill_chain_root_provenance_mismatch")
    require(chain_root.get("retail_portfolio_id") == runtime.portfolio_id, "terminal_no_fill_chain_root_portfolio_mismatch")
    require(chain_root.get("parent_client_order_id") in {None, ""}, "terminal_no_fill_chain_root_parent_present")
    scope = object_record(chain.get("portfolio_scope"))
    require(scope.get("scope_consistent") is True, "terminal_no_fill_chain_scope_inconsistent")
    require(scope.get("status") == "matched", "terminal_no_fill_chain_scope_mismatch")
    require(chain.get("read_only") is True, "terminal_no_fill_chain_not_read_only")
    require(chain.get("live_coinbase_orders_ran") is False, "terminal_no_fill_chain_live_order_flag")
    require(chain.get("local_state_mutated") is False, "terminal_no_fill_chain_local_mutation")
    require(chain.get("exchange_state_mutated") is False, "terminal_no_fill_chain_exchange_mutation")

    rest_fills, rest_pagination = _read_exact_rest_fill_pages(
        rest_client,
        exchange_order_id=exchange_order_id,
        portfolio_id=runtime.portfolio_id,
    )
    require(rest_fills == [], "terminal_no_fill_raw_rest_fill_present")
    require(rest_pagination.get("pagination_complete") is True, "terminal_no_fill_raw_rest_pagination_incomplete")
    sys.path.insert(0, str(ROOT))
    from database import order as order_module

    ledger_rows = order_module.get_fills_by_order(client_order_id) or []
    require(not ledger_rows, "terminal_no_fill_local_fill_ledger_row_present")
    audit_rows = _read_order_match_audit_rows(order_module.DB_CLIENT, client_order_id)
    match_bearing_rows = []
    for row in audit_rows:
        derived_size = Decimal(str(row.get("derived_size_delta") or "0"))
        derived_value = Decimal(str(row.get("derived_value_delta") or "0"))
        derived_fee = Decimal(str(row.get("derived_fee_delta") or "0"))
        cumulative_quantity = Decimal(str(row.get("cumulative_quantity") or "0"))
        filled_value = Decimal(str(row.get("filled_value") or "0"))
        total_fees = Decimal(str(row.get("total_fees") or "0"))
        number_of_fills = int(row.get("number_of_fills") or 0)
        if (
            bool(str(row.get("derived_trade_key") or "").strip())
            or row.get("emitted_fill_ledger_row") is True
            or derived_size != 0
            or derived_value != 0
            or derived_fee != 0
            or cumulative_quantity != 0
            or filled_value != 0
            or total_fees != 0
            or number_of_fills != 0
        ):
            match_bearing_rows.append(row)
    require(not match_bearing_rows, "terminal_no_fill_match_bearing_audit_row_present")
    return {
        "local_status": local_status,
        "fill_readback_order_status": fill_readback_status,
        "chain_root_status": chain_root_status,
        "fill_readback_fill_count": 0,
        "fill_readback_read_only": True,
        "follow_up_child_count": 0,
        "raw_rest_fill_count": 0,
        "raw_rest_fill_pagination_complete": True,
        "local_fill_ledger_row_count": 0,
        "match_bearing_audit_row_count": 0,
    }


def _validate_controlled_child_reveal_response(
    response: Mapping[str, Any],
    *,
    root_plan: Mapping[str, Any],
    child_tuple: Mapping[str, Any],
    portfolio_id: str,
) -> tuple[str, dict[str, Any]]:
    child_id = str(root_plan["child_client_order_id"])
    require(response.get("status") == "accepted", "child_reveal_not_accepted")
    require(response.get("stealth_order_id") == child_id, "child_reveal_identity_mismatch")
    require(response.get("live_exchange_submitted") is True, "child_reveal_submit_flag_missing")
    require(response.get("live_coinbase_orders_ran") is True, "child_reveal_coinbase_flag_missing")
    exchange_order_id = str(response.get("coinbase_order_id") or "")
    require(bool(exchange_order_id), "child_reveal_exchange_order_id_missing")
    data = object_record(response.get("data"))
    require(data.get("controlled_batch_id") == child_tuple["batch_id"], "child_reveal_batch_mismatch")
    require(data.get("controlled_batch_slot") == child_tuple["batch_slot"], "child_reveal_slot_mismatch")
    attempt = object_record(data.get("submission_attempt"))
    require(attempt.get("placed_client_order_id") == child_id, "child_reveal_attempt_identity_mismatch")
    require(attempt.get("exchange_order_id") == exchange_order_id, "child_reveal_attempt_exchange_id_mismatch")
    require(attempt.get("product_id") == PRODUCT_ID, "child_reveal_attempt_product_mismatch")
    require(str(attempt.get("side") or "").upper() == "SELL", "child_reveal_attempt_side_mismatch")
    require(
        Decimal(str(attempt.get("base_size") or "0"))
        == Decimal(str(child_tuple["base_size"])),
        "child_reveal_attempt_size_mismatch",
    )
    require(
        Decimal(str(attempt.get("submitted_limit_price") or "0"))
        == Decimal(str(child_tuple["limit_price"])),
        "child_reveal_attempt_price_mismatch",
    )
    require(attempt.get("post_only") is False, "child_reveal_attempt_post_only_mismatch")
    require(attempt.get("placement_attempted") is True, "child_reveal_attempt_flag_missing")
    require(attempt.get("placement_succeeded") is True, "child_reveal_success_flag_missing")
    readback = object_record(data.get("submission_readback"))
    require(readback.get("authoritative") is True, "child_reveal_readback_not_authoritative")
    require(readback.get("exact_identity_match") is True, "child_reveal_readback_identity_unproven")
    require(readback.get("exchange_order_id") == exchange_order_id, "child_reveal_readback_exchange_id_mismatch")
    matched = object_record(readback.get("matched_order"))
    validated = _validate_exact_coinbase_gtc_child_order(
        matched,
        expected_exchange_order_id=exchange_order_id,
        expected_portfolio_id=portfolio_id,
        expected_child_tuple=child_tuple,
    )
    authoritative_status = str(readback.get("authoritative_status") or "").upper()
    require(
        authoritative_status == str(validated.get("status") or "").upper(),
        "child_reveal_readback_status_mismatch",
    )
    filled_size = Decimal(str(validated.get("filled_size") or "0"))
    if authoritative_status == "FILLED":
        raise ProofFailure("stop_child_filled_before_cancel")
    if filled_size > 0:
        raise ProofFailure("stop_child_partial_fill_before_cancel")
    require(
        authoritative_status in {"PENDING", "OPEN"},
        f"child_reveal_unexpected_status:{authoritative_status}",
    )
    return exchange_order_id, validated


def _validate_controlled_child_cancel_response(
    response: Mapping[str, Any],
    *,
    root_plan: Mapping[str, Any],
    child_tuple: Mapping[str, Any],
    exchange_order_id: str,
    portfolio_id: str,
) -> dict[str, Any]:
    if response.get("status") != "accepted":
        failure_stage = str(response.get("failure_stage") or "")
        if failure_stage in {
            "controlled_child_already_filled",
            "controlled_child_filled_during_cancel",
        }:
            raise ProofFailure("stop_child_filled_during_cancel")
        if failure_stage == "controlled_child_partial_fill_cancelled":
            raise ProofFailure("stop_child_partial_fill_cancelled")
        raise ProofFailure(f"child_cancel_not_accepted:{failure_stage}")
    child_id = str(root_plan["child_client_order_id"])
    require(response.get("stealth_order_id") == child_id, "child_cancel_identity_mismatch")
    require(response.get("coinbase_order_id") == exchange_order_id, "child_cancel_exchange_id_mismatch")
    data = object_record(response.get("data"))
    require(data.get("controlled_batch_id") == child_tuple["batch_id"], "child_cancel_batch_mismatch")
    require(data.get("controlled_batch_slot") == child_tuple["batch_slot"], "child_cancel_slot_mismatch")
    identity = object_record(data.get("cancellation_identity"))
    require(identity.get("operator_identity_key") == "client_order_id", "child_cancel_operator_identity_mismatch")
    require(identity.get("operator_identity_value") == child_id, "child_cancel_operator_value_mismatch")
    require(identity.get("exchange_order_id") == exchange_order_id, "child_cancel_identity_exchange_id_mismatch")
    require(identity.get("exchange_order_id_evidence_only") is True, "child_cancel_exchange_evidence_flag_missing")
    require(
        isinstance(identity.get("exchange_id_fallback_used"), bool),
        "child_cancel_exchange_fallback_evidence_missing",
    )
    readback = object_record(data.get("cancellation_readback"))
    require(readback.get("authoritative") is True, "child_cancel_readback_not_authoritative")
    require(readback.get("exact_identity_match") is True, "child_cancel_readback_identity_unproven")
    require(readback.get("exchange_order_id") == exchange_order_id, "child_cancel_readback_exchange_id_mismatch")
    require(
        str(readback.get("authoritative_status") or "").upper()
        in {"CANCELLED", "CANCELED"},
        "child_cancel_terminal_status_mismatch",
    )
    matched = object_record(readback.get("matched_order"))
    validated = _validate_exact_coinbase_gtc_child_order(
        matched,
        expected_exchange_order_id=exchange_order_id,
        expected_portfolio_id=portfolio_id,
        expected_child_tuple=child_tuple,
    )
    require(
        str(validated.get("status") or "").upper()
        in {"CANCELLED", "CANCELED"},
        "child_cancel_matched_order_not_cancelled",
    )
    require(
        Decimal(str(validated.get("filled_size") or "0")) == 0,
        "stop_child_fill_detected_after_cancel",
    )
    local_reconciliation = object_record(data.get("local_reconciliation"))
    require(
        local_reconciliation.get("local_status") == "CANCELLED"
        and local_reconciliation.get("active_placement_cleared") is True,
        "child_cancel_local_reconciliation_unproven",
    )
    return {
        "exchange_order_id": exchange_order_id,
        "authoritative_status": str(validated.get("status") or "").upper(),
        "filled_size": "0",
        "exchange_id_fallback_used": identity["exchange_id_fallback_used"],
        "local_reconciliation": local_reconciliation,
    }


def _validate_cancelled_child_chain(
    runtime: AdminRuntime,
    *,
    root_plan: Mapping[str, Any],
    exchange_order_id: str,
) -> dict[str, Any]:
    root_id = str(root_plan["root_client_order_id"])
    child_id = str(root_plan["child_client_order_id"])
    _, chain, _ = runtime.request(
        "GET",
        f"/orders/{root_id}/fill-follow-up/chain",
        headers=runtime.headers(role="auditor"),
        expected={200},
    )
    require(
        chain.get("type") == "admin_order_fill_follow_up_chain",
        "cancelled_child_chain_type_mismatch",
    )
    require(chain.get("found") is True, "cancelled_child_chain_missing")
    require(chain.get("client_order_id") == root_id, "cancelled_child_chain_root_mismatch")
    require(
        chain.get("root_parent_client_order_id") == root_id,
        "cancelled_child_chain_root_parent_mismatch",
    )
    require(chain.get("follow_up_child_count") == 1, "cancelled_child_chain_count_mismatch")
    require(chain.get("follow_up_child_client_order_ids") == [child_id], "cancelled_child_chain_id_mismatch")
    require(not list_value(chain.get("duplicate_child_client_order_ids")), "cancelled_child_chain_duplicate")
    require(not list_value(chain.get("nested_child_client_order_ids")), "cancelled_child_chain_nested")
    require(not list_value(chain.get("nested_parent_client_order_ids")), "cancelled_child_chain_nested_parent")
    require(int(chain.get("flat_hierarchy_violation_count") or 0) == 0, "cancelled_child_chain_flat_violation")
    require(
        chain.get("order_parent_child_read_ran") is True
        and chain.get("stealth_child_read_ran") is True,
        "cancelled_child_chain_sources_unproven",
    )
    root = object_record(chain.get("root_order"))
    require(root.get("client_order_id") == root_id, "cancelled_child_chain_root_row_mismatch")
    require(
        str(root.get("status") or "").upper() == "FILLED",
        "cancelled_child_chain_root_not_filled",
    )
    require(
        root.get("ownership_provenance") == "ADMIN_MANUAL_ROOT",
        "cancelled_child_chain_root_provenance_mismatch",
    )
    require(
        root.get("retail_portfolio_id") == runtime.portfolio_id,
        "cancelled_child_chain_root_portfolio_mismatch",
    )
    require(
        root.get("parent_client_order_id") in {None, ""},
        "cancelled_child_chain_root_has_parent",
    )
    scope = object_record(chain.get("portfolio_scope"))
    require(
        scope.get("scope_consistent") is True
        and scope.get("status") == "matched",
        "cancelled_child_chain_scope_mismatch",
    )
    children = [object_record(item) for item in list_value(chain.get("follow_up_children"))]
    require(len(children) == 1, "cancelled_child_chain_row_count_mismatch")
    child = children[0]
    require(child.get("client_order_id") == child_id, "cancelled_child_chain_child_mismatch")
    require(child.get("parent_client_order_id") == root_id, "cancelled_child_chain_parent_mismatch")
    require(child.get("ownership_provenance") == "ADMIN_FILL_FOLLOW_UP", "cancelled_child_chain_provenance_mismatch")
    require(
        str(child.get("status") or "").upper() in {"CANCELLED", "CANCELED"},
        "cancelled_child_chain_status_mismatch",
    )
    require(
        str(child.get("exchange_order_id") or "") == exchange_order_id,
        "cancelled_child_chain_exchange_id_mismatch",
    )
    _, detail, _ = runtime.request(
        "GET",
        f"/stealth/orders/{child_id}",
        headers=runtime.headers(role="auditor"),
        expected={200},
    )
    order = object_record(detail.get("order"))
    require(detail.get("found") is True, "cancelled_child_detail_missing")
    require(order.get("stealth_order_id") == child_id, "cancelled_child_detail_identity_mismatch")
    require(
        order.get("parent_stealth_order_id") == root_id,
        "cancelled_child_detail_parent_mismatch",
    )
    require(
        order.get("product_id") == PRODUCT_ID
        and str(order.get("side") or "").upper() == "SELL",
        "cancelled_child_detail_tuple_mismatch",
    )
    require(
        str(order.get("status") or "").upper() in {"CANCELLED", "CANCELED"},
        "cancelled_child_detail_status_mismatch",
    )
    require(
        not str(order.get("active_placement_client_order_id") or "").strip()
        and not str(order.get("active_exchange_order_id") or "").strip(),
        "cancelled_child_active_placement_not_cleared",
    )
    require(
        Decimal(str(order.get("executed_size") or "0")) == 0,
        "cancelled_child_detail_fill_detected",
    )
    require(
        detail.get("read_only") is True
        and detail.get("live_coinbase_orders_ran") is False,
        "cancelled_child_detail_read_only_unproven",
    )
    require(
        chain.get("read_only") is True
        and chain.get("live_coinbase_orders_ran") is False
        and chain.get("local_state_mutated") is False
        and chain.get("exchange_state_mutated") is False,
        "cancelled_child_chain_read_only_unproven",
    )
    return {
        "root_client_order_id": root_id,
        "child_client_order_id": child_id,
        "child_exchange_order_id": exchange_order_id,
        "child_status": str(order.get("status") or "").upper(),
        "active_placement_cleared": True,
        "flat_hierarchy_proven": True,
    }


def execute_controlled_batch(
    rest_client: Any,
    preflight: Mapping[str, Any],
    *,
    confirmed_plan: Mapping[str, Any],
    confirmed_plan_hash: str,
    global_batch_marker: Path,
    attempt_ledger_path: Path,
) -> dict[str, Any]:
    """Execute ten sequential root/first-child pairs in one runtime."""

    global _CLEANUP_ACTIVE, _PENDING_TERMINATION_SIGNAL

    runtime = AdminRuntime(
        portfolio_id=str(preflight["portfolio_id"]),
        confirmed_plan=confirmed_plan,
        confirmed_plan_hash=confirmed_plan_hash,
        global_batch_marker=global_batch_marker,
        attempt_ledger_path=attempt_ledger_path,
    )
    summary: dict[str, Any] = {
        "status": "failed",
        "state_dir": str(runtime.state_dir),
        "backend_commit": EXPECTED_COMMIT,
        "runner_sha256": runner_sha256(),
        "plan_sha256": confirmed_plan_hash,
        "batch_id": confirmed_plan["batch_id"],
        "batch_size": BATCH_SIZE,
        "product_id": PRODUCT_ID,
        "portfolio_label": PROFILE_LABEL,
        "successor_root_order_count_authorized": SUCCESSOR_ROOT_ORDER_MAXIMUM,
        "successor_child_order_count_authorized": SUCCESSOR_CHILD_ORDER_MAXIMUM,
        "cumulative_root_order_count_authorized": BATCH_SIZE,
        "cumulative_child_order_count_authorized": BATCH_SIZE,
        "generic_or_later_child_authorized": False,
        "retry_authorized": False,
        "substitution_authorized": False,
        "slot_results": [],
    }
    current_root_id: str | None = None
    root_place_http_attempted = False
    root_cancel_http_attempted = False
    child_reveal_http_attempted = False
    child_cancel_http_attempted = False
    root_cancel_headers: dict[str, str] = {}
    root_cancel_body: dict[str, Any] = {}
    child_cancel_headers: dict[str, str] = {}
    child_cancel_body: dict[str, Any] = {}
    try:
        runtime.start()
        runtime.wait_until_mutations_ready()
        require(runtime.process is not None, "embedded_runtime_process_missing")
        require_runtime_exclusivity(
            allowed_runtime_pids={runtime.process.pid},
            require_port_free=False,
        )
        runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={0},
            expected_child_place_limit_order_calls={0},
        )
        _, live_enablement, _ = runtime.request(
            "GET",
            "/admin/live-enablement",
            headers=runtime.headers(role="viewer"),
            expected={200},
        )
        require(
            live_enablement.get("live_command_runtime_ready") is True,
            "live_command_runtime_not_ready",
        )
        scope = object_record(live_enablement.get("spot_portfolio_scope"))
        require(scope.get("status") == "matched", "live_enablement_portfolio_scope_blocked")
        require(scope.get("portfolio_id") == runtime.portfolio_id, "live_enablement_portfolio_id_mismatch")
        roots = [object_record(item) for item in list_value(confirmed_plan["roots"])]
        all_planned_ids = {
            str(value)
            for root_plan in roots
            for value in (
                root_plan["root_client_order_id"],
                root_plan["child_client_order_id"],
            )
        }
        for slot, root_plan in enumerate(roots, start=1):
            current_root_id = str(root_plan["root_client_order_id"])
            root_place_http_attempted = False
            root_cancel_http_attempted = False
            child_reveal_http_attempted = False
            child_cancel_http_attempted = False
            root_cancel_headers = {}
            root_cancel_body = {}
            child_cancel_headers = {}
            child_cancel_body = {}
            slot_result: dict[str, Any] = {
                "slot": slot,
                "root_client_order_id": current_root_id,
                "child_client_order_id": root_plan["child_client_order_id"],
                "status": "failed",
            }
            summary["slot_results"].append(slot_result)

            local_scope = prove_local_scope_with_historical_hidden_child(
                planned_client_order_ids=all_planned_ids,
                carried_root_plan=roots[0],
                require_carried_hidden=slot == 1,
            )
            active_before_root = read_authoritative_spot_nonterminal_orders(
                rest_client,
                expected_portfolio_id=runtime.portfolio_id,
            )
            require(not active_before_root, f"slot_{slot}_active_order_before_root")
            fresh_preflight = coinbase_preflight(rest_client)
            predecessor_binding = load_predecessor_binding()
            fresh_roots, _ = validate_successor_live_plan(
                confirmed_plan,
                expected_hash=confirmed_plan_hash,
                preflight=fresh_preflight,
                predecessor_binding=predecessor_binding,
            )
            fresh_root_plan = fresh_roots[slot - 1]
            require(fresh_root_plan == root_plan, f"slot_{slot}_root_plan_drift")
            order_body = object_record(root_plan["order"])
            approvals = object_record(root_plan["proof_approval_ids"])
            wallet_available = Decimal(
                str(fresh_preflight["wallets"]["USDC"])
            )
            immediate_preflight = coinbase_preflight(rest_client)
            immediate_roots, _ = validate_successor_live_plan(
                confirmed_plan,
                expected_hash=confirmed_plan_hash,
                preflight=immediate_preflight,
                predecessor_binding=predecessor_binding,
            )
            require(immediate_roots[slot - 1] == root_plan, f"slot_{slot}_root_tuple_drift_before_http")
            root_calls_before = max(0, slot - 2)
            child_calls_before = slot - 1
            runtime.sdk_boundary_sentinel(
                expected_root_create_order_calls={root_calls_before},
                expected_child_place_limit_order_calls={child_calls_before},
            )
            wallets_before: dict[str, Decimal] | None = None
            if slot == 1:
                require(
                    root_plan.get("root_placement_authorized") is False,
                    "carried_root_placement_authority_present",
                )
                try:
                    approved_exact_successor_root_tuple(
                        confirmed_plan,
                        root_plan,
                    )
                except ProofFailure as exc:
                    require(
                        str(exc) == "successor_carried_root_placement_denied",
                        "carried_root_denial_reason_mismatch",
                    )
                else:
                    raise ProofFailure("carried_root_sdk_tuple_available")
                require(
                    not read_batch_attempt_ledger(
                        attempt_ledger_path,
                        confirmed_plan=confirmed_plan,
                        confirmed_plan_hash=confirmed_plan_hash,
                    ),
                    "successor_ledger_not_empty_before_child_1",
                )
                place_headers = {
                    "X-Correlation-Id": str(
                        predecessor_binding["root_correlation_id"]
                    )
                }
                place_proofs = {
                    "admission_audit_id": str(
                        predecessor_binding["root_admission_audit_id"]
                    )
                }
                exchange_order_id = str(
                    predecessor_binding["root_exchange_order_id"]
                )
                exchange_order = _validate_exact_coinbase_fok_order(
                    exact_exchange_order(rest_client, exchange_order_id),
                    expected_exchange_order_id=exchange_order_id,
                    expected_client_order_id=current_root_id,
                    expected_portfolio_id=runtime.portfolio_id,
                    expected_order_body=order_body,
                )
                slot_result["root_inherited_from_predecessor"] = True
                slot_result["predecessor_binding"] = predecessor_binding
            else:
                require(
                    root_plan.get("root_placement_authorized") is True,
                    f"slot_{slot}_fresh_root_not_authorized",
                )
                root_tuple = approved_exact_successor_root_tuple(
                    confirmed_plan,
                    root_plan,
                )
                root_attempt = consume_batch_attempt(
                    attempt_ledger_path,
                    confirmed_plan=confirmed_plan,
                    confirmed_plan_hash=confirmed_plan_hash,
                    slot=slot,
                    attempt_kind="root",
                    exact_order_tuple=root_tuple,
                )
                slot_result["root_attempt_ledger_record"] = root_attempt
                runtime.sdk_boundary_sentinel(
                    expected_root_create_order_calls={root_calls_before},
                    expected_child_place_limit_order_calls={child_calls_before},
                )
                _prove_fresh_fill_persistence_identity(current_root_id)
                place_headers = runtime.headers(
                    idempotency_key=(
                        f"{confirmed_plan['batch_id']}-root-{slot}-place"
                    ),
                    operator_intent=INTENTIONAL_FILL_OPERATOR_INTENT,
                    role=COMMAND_ROLE,
                    correlation_id=(
                        f"corr-{confirmed_plan['batch_id']}-root-{slot}"
                    ),
                )
                _, initial_place, _ = runtime.request(
                    "POST",
                    "/orders",
                    headers=place_headers,
                    body=order_body,
                    expected={501},
                )
                place_context = capture_context(initial_place)
                require(
                    place_context["identity_value"] == current_root_id,
                    "root_place_identity_mismatch",
                )
                root_cancel_body = {
                    "reason": f"controlled_batch_slot_{slot}_root_safety_cancel",
                    "manual_live_acknowledgement": True,
                }
                root_cancel_headers = runtime.headers(
                    idempotency_key=(
                        f"{confirmed_plan['batch_id']}-root-{slot}-cancel"
                    ),
                    operator_intent="controlled_batch_root_safety_cancel",
                    role=COMMAND_ROLE,
                    correlation_id=(
                        f"corr-{confirmed_plan['batch_id']}-root-{slot}-cancel"
                    ),
                )
                _, initial_root_cancel, _ = runtime.request(
                    "POST",
                    f"/orders/{current_root_id}/cancel",
                    headers=root_cancel_headers,
                    body=root_cancel_body,
                    expected={501},
                )
                root_cancel_context = capture_context(initial_root_cancel)
                wallet_available = Decimal(
                    str(fresh_preflight["wallets"]["USDC"])
                )
                place_proofs = write_proof_chain(
                    runtime,
                    label=f"slot-{slot}-root-place",
                    context=place_context,
                    wallet_available=wallet_available,
                    max_notional=ROOT_SUBMITTED_CAP,
                    command_kind="root_place",
                    cancel=False,
                    approval_id=str(approvals["root_place"]),
                )
                root_cancel_proofs = write_proof_chain(
                    runtime,
                    label=f"slot-{slot}-root-cancel",
                    context=root_cancel_context,
                    wallet_available=wallet_available,
                    max_notional=Decimal("0"),
                    command_kind="root_cancel",
                    cancel=True,
                    approval_id=str(approvals["root_cancel"]),
                )
                preview_admission(runtime, place_context)
                preview_admission(runtime, root_cancel_context)
                slot_result["root_place_proofs"] = place_proofs
                slot_result["root_cancel_proofs"] = root_cancel_proofs
                wallets_before = _wallet_balances(
                    rest_client,
                    expected_portfolio_id=runtime.portfolio_id,
                )
                require(
                    confirmed_plan.get("runner_sha256") == runner_sha256(),
                    "runner_sha256_changed_before_root_http",
                )
                require_plan_unexpired(
                    confirmed_plan,
                    blocker=f"slot_{slot}_plan_expired_before_root_http",
                )
                runtime.exchange_safe_to_shutdown = False
                root_place_http_attempted = True
                status_code, place_response, response_headers = runtime.request(
                    "POST",
                    "/orders",
                    headers=place_headers,
                    body=order_body,
                    expected=None,
                )
                require(
                    status_code == 200,
                    f"slot_{slot}_root_place_http:{status_code}",
                )
                require(
                    place_response.get("status") == "accepted",
                    f"slot_{slot}_root_rejected",
                )
                require(
                    str(
                        response_headers.get("X-Idempotency-Replayed") or ""
                    ).lower()
                    != "true",
                    f"slot_{slot}_root_place_replayed",
                )
                exchange_order_id = str(
                    place_response.get("coinbase_order_id") or ""
                )
                require(
                    bool(exchange_order_id),
                    f"slot_{slot}_root_exchange_id_missing",
                )
                runtime.exchange_order_observed = True
                slot_result["root_acceptance"] = (
                    _validate_intentional_fill_acceptance(
                        place_response,
                        place_proofs=place_proofs,
                        place_headers=place_headers,
                        order_body=order_body,
                        portfolio_id=runtime.portfolio_id,
                        exchange_order_id=exchange_order_id,
                    )
                )
                runtime.sdk_boundary_sentinel(
                    expected_root_create_order_calls={root_calls_before + 1},
                    expected_child_place_limit_order_calls={child_calls_before},
                )
                exchange_order = _wait_for_exchange_terminal(
                    rest_client,
                    exchange_order_id=exchange_order_id,
                    client_order_id=current_root_id,
                    portfolio_id=runtime.portfolio_id,
                    order_body=order_body,
                )
            authoritative_status = str(exchange_order.get("status") or "").upper()
            filled_size = Decimal(str(exchange_order.get("filled_size") or "0"))
            filled_value = Decimal(str(exchange_order.get("filled_value") or "0"))
            total_fees = Decimal(
                str(exchange_order.get("total_fees") or exchange_order.get("fee") or "0")
            )
            slot_result["root_exchange_status"] = authoritative_status
            slot_result["root_exchange_order_id"] = exchange_order_id
            if slot > 1 and authoritative_status not in TERMINAL_STATUSES:
                root_cancel_http_attempted = True
                _, root_cancel_response, _ = runtime.request(
                    "POST",
                    f"/orders/{current_root_id}/cancel",
                    headers=root_cancel_headers,
                    body=root_cancel_body,
                    expected={200},
                )
                cancel_readback = object_record(
                    object_record(root_cancel_response.get("data")).get(
                        "cancellation_readback"
                    )
                )
                require(cancel_readback.get("terminal_status_proven") is True, "root_safety_cancel_terminal_unproven")
                raise ProofFailure("stop_root_fok_remained_nonterminal")
            if slot > 1 and authoritative_status in NO_FILL_TERMINAL_STATUSES:
                require(filled_size == 0 and filled_value == 0, "stop_root_terminal_partial_fill")
                slot_result["terminal_no_fill_proof"] = _prove_terminal_no_fill_locally_and_authoritatively(
                    runtime,
                    rest_client=rest_client,
                    client_order_id=current_root_id,
                    exchange_order_id=exchange_order_id,
                    expected_exchange_status=authoritative_status,
                )
                raise ProofFailure("stop_root_no_fill")
            require(authoritative_status == "FILLED", f"stop_root_status:{authoritative_status}")
            requested_size = Decimal(str(order_body["base_size"]))
            require(filled_size == requested_size, "stop_root_partial_fill")
            require(
                Decimal("0") < filled_value <= ROOT_SUBMITTED_CAP,
                "root_executed_notional_out_of_bounds",
            )
            if slot == 1:
                require(
                    filled_size == CARRIED_ROOT_FILLED_SIZE
                    and filled_value == CARRIED_ROOT_FILLED_VALUE
                    and total_fees == CARRIED_ROOT_TOTAL_FEES,
                    "carried_root_fill_evidence_mismatch",
                )

            fill_headers = runtime.headers(
                idempotency_key=f"{confirmed_plan['batch_id']}-root-{slot}-fill-read",
                operator_intent="read_authoritative_spot_order_and_fill_evidence",
                role="auditor",
                correlation_id=f"corr-{confirmed_plan['batch_id']}-root-{slot}-fill",
            )
            fill_readback: dict[str, Any] = {}
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                runtime.sdk_boundary_sentinel(
                    expected_root_create_order_calls={slot - 1},
                    expected_child_place_limit_order_calls={slot - 1},
                )
                _, fill_readback, _ = runtime.request(
                    "GET",
                    f"/orders/{current_root_id}/fill-readback",
                    headers=fill_headers,
                    params={"product_id": PRODUCT_ID, "fill_limit": 100},
                    expected={200},
                )
                if (
                    fill_readback.get("status") == "passed"
                    and str(fill_readback.get("order_status") or "").upper() == "FILLED"
                    and int(fill_readback.get("fill_count") or 0) > 0
                    and fill_readback.get("live_fill_readback_proof_recorded") is True
                ):
                    break
                time.sleep(0.5)
            require(fill_readback.get("status") == "passed", "root_fill_readback_failed")
            require(str(fill_readback.get("order_status") or "").upper() == "FILLED", "root_fill_readback_not_filled")
            require(int(fill_readback.get("fill_count") or 0) > 0, "root_fill_readback_empty")
            require(fill_readback.get("live_fill_readback_proof_recorded") is True, "root_fill_readback_proof_missing")

            chain: dict[str, Any] = {}
            preexchange_child: dict[str, Any] = {}
            chain_deadline = time.monotonic() + FOLLOW_UP_WAIT_SECONDS
            while time.monotonic() < chain_deadline:
                _, chain, _ = runtime.request(
                    "GET",
                    f"/orders/{current_root_id}/fill-follow-up/chain",
                    headers=runtime.headers(role="auditor"),
                    expected={200},
                )
                _raise_on_critical_chain_state(chain)
                try:
                    preexchange_child = _validate_automatic_hidden_child_chain(
                        chain,
                        root_client_order_id=current_root_id,
                        portfolio_id=runtime.portfolio_id,
                        expected_filled_size=filled_size,
                        expected_placement_correlation_id=str(place_headers["X-Correlation-Id"]),
                        expected_admission_audit_id=place_proofs["admission_audit_id"],
                        expected_exchange_order_id=exchange_order_id,
                    )
                except ProofFailure as exc:
                    if not _chain_validation_failure_is_transient(str(exc)):
                        raise
                    time.sleep(0.25)
                    continue
                break
            require(bool(preexchange_child), "automatic_first_child_timeout")
            child_id = str(root_plan["child_client_order_id"])
            require(preexchange_child.get("client_order_id") == child_id, "automatic_first_child_not_deterministic")
            _, child_detail, _ = runtime.request(
                "GET",
                f"/stealth/orders/{child_id}",
                headers=runtime.headers(role="auditor"),
                expected={200},
            )
            _validate_hidden_child_detail(
                child_detail,
                child_id=child_id,
                root_client_order_id=current_root_id,
                expected_filled_size=filled_size,
            )
            require(
                not read_authoritative_spot_nonterminal_orders(
                    rest_client,
                    expected_portfolio_id=runtime.portfolio_id,
                ),
                "active_order_present_between_root_and_child",
            )
            fill_reconciliation = _reconcile_fill_ledger_with_exact_rest_fills(
                rest_client,
                client_order_id=current_root_id,
                exchange_order_id=exchange_order_id,
                portfolio_id=runtime.portfolio_id,
                expected_filled_size=filled_size,
                expected_filled_value=filled_value,
                expected_total_fees=total_fees,
            )
            slot_result["root_fill_reconciliation"] = fill_reconciliation
            slot_result["root_fill_crosscheck"] = _cross_check_fill_readback_evidence(
                fill_readback,
                exchange_order=exchange_order,
                reconciliation=fill_reconciliation,
            )
            _, replay, _ = runtime.request(
                "GET",
                f"/orders/{current_root_id}/fill-follow-up/replay",
                headers=runtime.headers(role="auditor"),
                expected={200},
            )
            require(replay.get("replay_ran") is True, "follow_up_replay_not_run")
            require(replay.get("read_only") is True, "follow_up_replay_not_read_only")
            require(replay.get("follow_up_order_created") is False, "follow_up_replay_created_duplicate")
            replay_audit = object_record(replay.get("fill_follow_up_decision_audit"))
            require(replay_audit.get("existing_follow_up_client_order_ids") == [child_id], "follow_up_replay_child_mismatch")
            require(replay_audit.get("existing_follow_up_count") == 1, "follow_up_replay_count_mismatch")
            if slot == 1:
                require(
                    runtime.live_service_disable_proven,
                    "predecessor_service_not_disabled_before_successor_attempt",
                )
                slot_result["predecessor_reconciliation_before_first_attempt"] = {
                    "predecessor_artifacts_hash_bound": True,
                    "root_full_fill_authoritatively_proven": True,
                    "fill_ledger_reconciled": True,
                    "fill_readback_crosschecked": True,
                    "deterministic_child_wholly_unsubmitted": True,
                    "zero_active_spot_orders": True,
                    "predecessor_service_disabled": True,
                    "predecessor_runtime_stopped_before_successor": True,
                    "root_placement_authorized": False,
                }

            child_market = fresh_exact_market(rest_client)
            price_increment = Decimal(
                str(object_record(immediate_preflight["product"])["price_increment"])
            )
            child_tuple = build_child_order_tuple(
                confirmed_plan,
                root_plan,
                filled_size=filled_size,
                fresh_market=child_market,
                price_increment=price_increment,
            )
            child_attempt = consume_batch_attempt(
                attempt_ledger_path,
                confirmed_plan=confirmed_plan,
                confirmed_plan_hash=confirmed_plan_hash,
                slot=slot,
                attempt_kind="child",
                exact_order_tuple=child_tuple,
            )
            slot_result["child_attempt_ledger_record"] = child_attempt
            runtime.sdk_boundary_sentinel(
                expected_root_create_order_calls={slot - 1},
                expected_child_place_limit_order_calls={slot - 1},
            )

            child_reveal_body = {
                "reason": f"controlled batch slot {slot} first-child submission",
                "manual_live_acknowledgement": True,
                "expected_root_client_order_id": current_root_id,
                "controlled_limit_price": child_tuple["limit_price"],
                "controlled_batch_id": confirmed_plan["batch_id"],
                "controlled_batch_slot": slot,
            }
            child_reveal_headers = runtime.headers(
                idempotency_key=f"{confirmed_plan['batch_id']}-child-{slot}-reveal",
                operator_intent=CONTROLLED_CHILD_REVEAL_OPERATOR_INTENT,
                role=COMMAND_ROLE,
                correlation_id=f"corr-{confirmed_plan['batch_id']}-child-{slot}-reveal",
            )
            _, initial_child_reveal, _ = runtime.request(
                "POST",
                f"/stealth/orders/{child_id}/reveal",
                headers=child_reveal_headers,
                body=child_reveal_body,
                expected={501},
            )
            child_reveal_context = capture_context(initial_child_reveal)

            child_cancel_body = {
                "reason": f"controlled batch slot {slot} first-child exact cancel",
                "manual_live_acknowledgement": True,
                "expected_root_client_order_id": current_root_id,
                "controlled_batch_id": confirmed_plan["batch_id"],
                "controlled_batch_slot": slot,
            }
            child_cancel_headers = runtime.headers(
                idempotency_key=f"{confirmed_plan['batch_id']}-child-{slot}-cancel",
                operator_intent=CONTROLLED_CHILD_CANCEL_OPERATOR_INTENT,
                role=COMMAND_ROLE,
                correlation_id=f"corr-{confirmed_plan['batch_id']}-child-{slot}-cancel",
            )
            _, initial_child_cancel, _ = runtime.request(
                "POST",
                f"/stealth/orders/{child_id}/cancel",
                headers=child_cancel_headers,
                body=child_cancel_body,
                expected={501},
            )
            child_cancel_context = capture_context(initial_child_cancel)
            child_wallets = _wallet_balances(
                rest_client,
                expected_portfolio_id=runtime.portfolio_id,
            )
            child_wallet_reference_available = (
                child_wallets["BTC"]
                * Decimal(str(child_tuple["limit_price"]))
            )
            require(
                child_wallets["BTC"]
                >= Decimal(str(child_tuple["base_size"])),
                "child_wallet_base_size_insufficient",
            )
            child_reveal_proofs = write_proof_chain(
                runtime,
                label=f"slot-{slot}-child-reveal",
                context=child_reveal_context,
                wallet_available=child_wallet_reference_available,
                max_notional=CHILD_SUBMITTED_CAP,
                command_kind="child_reveal",
                cancel=False,
                approval_id=str(approvals["child_reveal"]),
            )
            child_cancel_proofs = write_proof_chain(
                runtime,
                label=f"slot-{slot}-child-cancel",
                context=child_cancel_context,
                wallet_available=wallet_available,
                max_notional=Decimal("0"),
                command_kind="child_cancel",
                cancel=True,
                approval_id=str(approvals["child_cancel"]),
            )
            if slot == 1:
                set_live_service(runtime, enabled=True)
            preview_admission(runtime, child_reveal_context)
            preview_admission(runtime, child_cancel_context)
            slot_result["child_reveal_proofs"] = child_reveal_proofs
            slot_result["child_cancel_proofs"] = child_cancel_proofs

            require(
                not read_authoritative_spot_nonterminal_orders(
                    rest_client,
                    expected_portfolio_id=runtime.portfolio_id,
                ),
                "active_order_present_before_child_http",
            )
            immediate_child_market = fresh_exact_market(rest_client)
            require(
                Decimal(str(child_tuple["limit_price"]))
                >= Decimal(str(immediate_child_market["best_bid"]))
                * CHILD_MINIMUM_BID_RATIO,
                "child_price_below_160_percent_immediate_fresh_bid",
            )
            require_plan_unexpired(
                confirmed_plan,
                blocker=f"slot_{slot}_plan_expired_before_child_http",
            )
            runtime.exchange_safe_to_shutdown = False
            child_reveal_http_attempted = True
            child_status_code, child_response, child_headers = runtime.request(
                "POST",
                f"/stealth/orders/{child_id}/reveal",
                headers=child_reveal_headers,
                body=child_reveal_body,
                expected=None,
            )
            require(child_status_code == 200, f"child_reveal_http_failed:{child_status_code}")
            require(
                str(child_headers.get("X-Idempotency-Replayed") or "").lower()
                != "true",
                "child_reveal_unexpectedly_replayed",
            )
            child_exchange_order_id, child_exchange_row = (
                _validate_controlled_child_reveal_response(
                    child_response,
                    root_plan=root_plan,
                    child_tuple=child_tuple,
                    portfolio_id=runtime.portfolio_id,
                )
            )
            slot_result["child_exchange_order_id"] = child_exchange_order_id
            runtime.sdk_boundary_sentinel(
                expected_root_create_order_calls={slot - 1},
                expected_child_place_limit_order_calls={slot},
            )
            raw_child = exact_exchange_order(rest_client, child_exchange_order_id)
            raw_child = _validate_exact_coinbase_gtc_child_order(
                raw_child,
                expected_exchange_order_id=child_exchange_order_id,
                expected_portfolio_id=runtime.portfolio_id,
                expected_child_tuple=child_tuple,
            )
            raw_child_filled = Decimal(str(raw_child.get("filled_size") or "0"))
            if str(raw_child.get("status") or "").upper() == "FILLED":
                raise ProofFailure("stop_child_filled_before_cancel")
            if raw_child_filled > 0:
                # The one authorized cancel below is cleanup, not continuation.
                child_cancel_http_attempted = True
                runtime.request(
                    "POST",
                    f"/stealth/orders/{child_id}/cancel",
                    headers=child_cancel_headers,
                    body=child_cancel_body,
                    expected=None,
                )
                raise ProofFailure("stop_child_partial_fill_before_cancel")

            child_cancel_http_attempted = True
            child_cancel_status, child_cancel_response, child_cancel_headers_out = runtime.request(
                "POST",
                f"/stealth/orders/{child_id}/cancel",
                headers=child_cancel_headers,
                body=child_cancel_body,
                expected=None,
            )
            require(child_cancel_status == 200, f"child_cancel_http_failed:{child_cancel_status}")
            require(
                str(child_cancel_headers_out.get("X-Idempotency-Replayed") or "").lower()
                != "true",
                "child_cancel_unexpectedly_replayed",
            )
            slot_result["child_cancel"] = _validate_controlled_child_cancel_response(
                child_cancel_response,
                root_plan=root_plan,
                child_tuple=child_tuple,
                exchange_order_id=child_exchange_order_id,
                portfolio_id=runtime.portfolio_id,
            )
            terminal_child = exact_exchange_order(rest_client, child_exchange_order_id)
            terminal_child = _validate_exact_coinbase_gtc_child_order(
                terminal_child,
                expected_exchange_order_id=child_exchange_order_id,
                expected_portfolio_id=runtime.portfolio_id,
                expected_child_tuple=child_tuple,
            )
            require(
                str(terminal_child.get("status") or "").upper()
                in {"CANCELLED", "CANCELED"},
                "child_not_terminal_after_admin_cancel",
            )
            require(
                Decimal(str(terminal_child.get("filled_size") or "0")) == 0,
                "stop_child_fill_detected_after_terminal_read",
            )
            slot_result["cancelled_child_chain"] = _validate_cancelled_child_chain(
                runtime,
                root_plan=root_plan,
                exchange_order_id=child_exchange_order_id,
            )
            active_after_pair = read_authoritative_spot_nonterminal_orders(
                rest_client,
                expected_portfolio_id=runtime.portfolio_id,
            )
            require(not active_after_pair, f"slot_{slot}_active_order_after_pair")
            slot_result["active_order_zero_after_pair"] = True
            prove_local_scope_with_historical_hidden_child(
                planned_client_order_ids=all_planned_ids,
                carried_root_plan=roots[0],
            )
            wallet_evidence: dict[str, Any]
            if slot == 1:
                require(
                    wallets_before is None,
                    "carried_root_wallet_baseline_should_not_exist",
                )
                wallet_evidence = {
                    "wallet_delta_kind": "inherited_root_no_new_root_delta",
                    "wallet_btc_delta": None,
                    "wallet_usdc_delta": None,
                }
            else:
                require(
                    wallets_before is not None,
                    f"slot_{slot}_wallet_baseline_missing",
                )
                wallets_after = _wallet_balances(
                    rest_client,
                    expected_portfolio_id=runtime.portfolio_id,
                )
                btc_delta = wallets_after["BTC"] - wallets_before["BTC"]
                usdc_delta = wallets_after["USDC"] - wallets_before["USDC"]
                require(btc_delta > 0, f"slot_{slot}_wallet_btc_delta_missing")
                require(usdc_delta < 0, f"slot_{slot}_wallet_usdc_delta_missing")
                base_tolerance = max(
                    Decimal(
                        str(
                            object_record(immediate_preflight["product"])[
                                "base_increment"
                            ]
                        )
                    )
                    * 2,
                    filled_size * Decimal("0.02"),
                )
                require(
                    abs(btc_delta - filled_size) <= base_tolerance,
                    f"slot_{slot}_wallet_btc_delta_mismatch",
                )
                usdc_spent = -usdc_delta
                require(
                    abs(usdc_spent - (filled_value + total_fees))
                    <= Decimal("0.05")
                    or abs(usdc_spent - filled_value) <= Decimal("0.05"),
                    f"slot_{slot}_wallet_usdc_delta_mismatch",
                )
                wallet_evidence = {
                    "wallet_delta_kind": "new_root_fill",
                    "wallet_btc_delta": decimal_text(btc_delta),
                    "wallet_usdc_delta": decimal_text(usdc_delta),
                }
            slot_result.update(
                {
                    "status": "passed",
                    "root_status": "FILLED",
                    "root_filled_size": decimal_text(filled_size),
                    "root_filled_value": decimal_text(filled_value),
                    "root_total_fees": decimal_text(total_fees),
                    "child_preexchange_status": str(
                        preexchange_child.get("stealth_status")
                        or preexchange_child.get("status")
                        or ""
                    ).upper(),
                    "child_submitted_status": str(child_exchange_row.get("status") or "").upper(),
                    "child_terminal_status": str(terminal_child.get("status") or "").upper(),
                    "child_filled_size": "0",
                    **wallet_evidence,
                    "historical_chain_exception": local_scope,
                }
            )

        final_ledger = read_batch_attempt_ledger(
            attempt_ledger_path,
            confirmed_plan=confirmed_plan,
            confirmed_plan_hash=confirmed_plan_hash,
        )
        require(
            len(final_ledger) == SUCCESSOR_ATTEMPT_COUNT,
            "batch_attempt_ledger_not_complete",
        )
        require(
            [
                (int(record["batch_slot"]), str(record["attempt_kind"]))
                for record in final_ledger
            ]
            == successor_attempt_schedule(),
            "batch_successor_attempt_schedule_not_exact",
        )
        final_chain_readbacks = []
        for root_plan, slot_result in zip(
            roots,
            list_value(summary.get("slot_results")),
            strict=True,
        ):
            final_chain_readbacks.append(
                _validate_cancelled_child_chain(
                    runtime,
                    root_plan=root_plan,
                    exchange_order_id=str(
                        object_record(slot_result).get(
                            "child_exchange_order_id"
                        )
                        or ""
                    ),
                )
            )
        require(
            len(final_chain_readbacks) == BATCH_SIZE,
            "batch_final_chain_readback_count_mismatch",
        )
        set_live_service(runtime, enabled=False)
        require(
            runtime.live_service_disable_proven,
            "batch_live_service_disable_unproven",
        )
        sentinel_before_shutdown = runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={SUCCESSOR_ROOT_ORDER_MAXIMUM},
            expected_child_place_limit_order_calls={SUCCESSOR_CHILD_ORDER_MAXIMUM},
        )
        _, admin_runtime_before, _ = runtime.request(
            "GET",
            "/admin/runtime",
            headers=runtime.headers(role="viewer"),
            expected={200},
        )
        require(
            int(admin_runtime_before.get("total_inflight") or 0) == 0,
            "batch_admin_runtime_inflight_before_final_reads",
        )
        final_active_first = read_authoritative_spot_nonterminal_orders(
            rest_client,
            expected_portfolio_id=runtime.portfolio_id,
        )
        time.sleep(0.5)
        final_active_second = read_authoritative_spot_nonterminal_orders(
            rest_client,
            expected_portfolio_id=runtime.portfolio_id,
        )
        require(
            final_active_first == final_active_second,
            "batch_final_active_order_reads_not_stable",
        )
        require(
            not final_active_second,
            "active_order_present_after_batch",
        )
        sentinel = runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={SUCCESSOR_ROOT_ORDER_MAXIMUM},
            expected_child_place_limit_order_calls={SUCCESSOR_CHILD_ORDER_MAXIMUM},
        )
        require(
            sentinel.get("root_create_order_call_count")
            == sentinel_before_shutdown.get("root_create_order_call_count")
            and sentinel.get("child_place_limit_order_call_count")
            == sentinel_before_shutdown.get(
                "child_place_limit_order_call_count"
            ),
            "batch_sdk_call_count_changed_during_shutdown_window",
        )
        _, admin_runtime_after, _ = runtime.request(
            "GET",
            "/admin/runtime",
            headers=runtime.headers(role="viewer"),
            expected={200},
        )
        require(
            int(admin_runtime_after.get("total_inflight") or 0) == 0,
            "batch_admin_runtime_inflight_after_final_reads",
        )
        runtime.exchange_safe_to_shutdown = True
        summary.update(
            {
                "status": "passed",
                "successor_root_order_count_submitted": (
                    SUCCESSOR_ROOT_ORDER_MAXIMUM
                ),
                "successor_child_order_count_submitted": (
                    SUCCESSOR_CHILD_ORDER_MAXIMUM
                ),
                "cumulative_root_order_count_submitted": BATCH_SIZE,
                "cumulative_child_order_count_submitted": BATCH_SIZE,
                "child_order_count_cancelled_zero_fill": BATCH_SIZE,
                "attempt_ledger_record_count": SUCCESSOR_ATTEMPT_COUNT,
                "attempt_schedule": successor_attempt_schedule(),
                "sdk_boundary_sentinel": sentinel,
                "aggregate_sdk_boundary_evidence": {
                    "predecessor_root_create_order_call_count": 1,
                    "predecessor_child_place_limit_order_call_count": 0,
                    "successor_root_create_order_call_count": (
                        sentinel["root_create_order_call_count"]
                    ),
                    "successor_child_place_limit_order_call_count": (
                        sentinel["child_place_limit_order_call_count"]
                    ),
                    "cumulative_root_create_order_call_count": BATCH_SIZE,
                    "cumulative_child_place_limit_order_call_count": BATCH_SIZE,
                    "predecessor_sentinel_sha256": (
                        PREDECESSOR_SENTINEL_BYTES_SHA256
                    ),
                },
                "final_root_child_chain_readbacks": final_chain_readbacks,
                "admin_runtime_before_shutdown": admin_runtime_before,
                "admin_runtime_after_shutdown": admin_runtime_after,
                "shutdown_quiescence_window_proven": True,
                "exchange_active_spot_order_count_after": 0,
                "live_service_disabled_after": True,
                "historical_chain_untouched": True,
            }
        )
        (runtime.state_dir / "controlled-batch-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return summary
    except (Exception, KeyboardInterrupt) as exc:
        _CLEANUP_ACTIVE = True
        summary["failure_type"] = type(exc).__name__
        summary["failure_reason"] = str(exc)
        # At most one pre-authorized cleanup cancel is allowed; never replay it.
        if child_reveal_http_attempted and not child_cancel_http_attempted and child_cancel_headers:
            child_cancel_http_attempted = True
            try:
                runtime.request(
                    "POST",
                    f"/stealth/orders/{summary['slot_results'][-1]['child_client_order_id']}/cancel",
                    headers=child_cancel_headers,
                    body=child_cancel_body,
                    expected=None,
                )
                summary["single_child_failure_cancel_attempted"] = True
            except (Exception, KeyboardInterrupt) as cancel_exc:
                summary["single_child_failure_cancel_error"] = f"{type(cancel_exc).__name__}:{cancel_exc}"
        if root_place_http_attempted and not root_cancel_http_attempted and root_cancel_headers:
            try:
                active = read_authoritative_spot_nonterminal_orders(
                    rest_client,
                    expected_portfolio_id=runtime.portfolio_id,
                )
                exact_active_root = [
                    row
                    for row in active
                    if str(row.get("client_order_id") or "") == current_root_id
                ]
                if len(exact_active_root) == 1:
                    root_cancel_http_attempted = True
                    runtime.request(
                        "POST",
                        f"/orders/{current_root_id}/cancel",
                        headers=root_cancel_headers,
                        body=root_cancel_body,
                        expected=None,
                    )
                    summary["single_root_failure_cancel_attempted"] = True
            except (Exception, KeyboardInterrupt) as cancel_exc:
                summary["single_root_failure_cancel_error"] = f"{type(cancel_exc).__name__}:{cancel_exc}"
        reconcile_failure_state(
            runtime,
            rest_client=rest_client,
            summary=summary,
            current_root_client_order_id=current_root_id,
        )
        (runtime.state_dir / "controlled-batch-failure.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        _CLEANUP_ACTIVE = True
        try:
            finalize_runtime_cleanup(runtime, summary=summary)
        finally:
            pending_signal = _PENDING_TERMINATION_SIGNAL
            _PENDING_TERMINATION_SIGNAL = None
            _CLEANUP_ACTIVE = False
        if pending_signal is not None and summary.get("status") == "passed":
            raise KeyboardInterrupt(
                f"termination_signal_during_cleanup:{pending_signal}"
            )


def run_offline_self_test() -> dict[str, Any]:
    """Exercise batch authority, ledgers, and SDK guards without I/O."""

    require(
        EXECUTION_LOCK_PATH.parent == GLOBAL_BATCH_REGISTRY_DIR,
        "self_test_execution_lease_not_in_durable_registry",
    )
    ephemeral_tmp_prefix = "/" + "tmp/"
    require(
        not str(EXECUTION_LOCK_PATH).startswith(ephemeral_tmp_prefix),
        "self_test_execution_lease_has_ephemeral_tmp_dependency",
    )
    late_sdk_order = {
        "client_order_id": "offline-late-sdk-client-order-id",
        "order_id": "offline-late-sdk-exchange-order-id",
        "status": "OPEN",
    }
    require(
        _parent_loss_reconciliation_decision(
            root_sdk_inflight=False,
            child_sdk_inflight=True,
            first_active_read=[],
            second_active_read=[],
            live_service_disable_proven=True,
        )
        == "wait_for_sdk_quiescence",
        "self_test_parent_loss_inflight_not_held",
    )
    require(
        _parent_loss_reconciliation_decision(
            root_sdk_inflight=False,
            child_sdk_inflight=False,
            first_active_read=[],
            second_active_read=[],
            live_service_disable_proven=True,
        )
        == "continue_monitoring_quiescent_zero",
        "self_test_parent_loss_empty_window_stopped_monitoring",
    )
    require(
        _parent_loss_reconciliation_decision(
            root_sdk_inflight=False,
            child_sdk_inflight=False,
            first_active_read=[late_sdk_order],
            second_active_read=[late_sdk_order],
            live_service_disable_proven=True,
        )
        == "reconcile_exact_active_order",
        "self_test_parent_loss_late_order_not_reconciled",
    )
    require(
        _parent_loss_cancel_retry_decision(
            exact_order_active=True,
            stable_active_scope_proven=True,
            prior_cancel_outcome=None,
        )
        == "issue_same_idempotent_exact_cancel",
        "self_test_parent_loss_initial_cancel_not_issued",
    )
    for failed_cancel_outcome in (
        "timeout_or_exception",
        "non_200_or_unaccepted",
    ):
        require(
            _parent_loss_cancel_retry_decision(
                exact_order_active=True,
                stable_active_scope_proven=True,
                prior_cancel_outcome=failed_cancel_outcome,
            )
            == "issue_same_idempotent_exact_cancel",
            (
                "self_test_parent_loss_same_idempotent_cancel_not_retried:"
                f"{failed_cancel_outcome}"
            ),
        )
    require(
        _parent_loss_cancel_retry_decision(
            exact_order_active=True,
            stable_active_scope_proven=True,
            prior_cancel_outcome="accepted",
        )
        == "poll_for_exact_cancel_terminal",
        "self_test_parent_loss_accepted_cancel_retried",
    )
    require(
        _parent_loss_cancel_retry_decision(
            exact_order_active=True,
            stable_active_scope_proven=False,
            prior_cancel_outcome="timeout_or_exception",
        )
        == "wait_for_stable_active_scope_before_cancel",
        "self_test_parent_loss_retry_without_stable_active_scope",
    )
    for slot in range(1, BATCH_SIZE + 1):
        if slot == 1:
            require(
                not successor_sdk_call_occurred(
                    slot=slot,
                    attempt_kind="root",
                    sdk_call_count=SUCCESSOR_ROOT_ORDER_MAXIMUM,
                ),
                "self_test_carried_root_mapped_to_successor_sdk_call",
            )
        else:
            require(
                not successor_sdk_call_occurred(
                    slot=slot,
                    attempt_kind="root",
                    sdk_call_count=slot - 2,
                )
                and successor_sdk_call_occurred(
                    slot=slot,
                    attempt_kind="root",
                    sdk_call_count=slot - 1,
                ),
                f"self_test_successor_root_sdk_ordinal_mismatch:{slot}",
            )
        require(
            not successor_sdk_call_occurred(
                slot=slot,
                attempt_kind="child",
                sdk_call_count=slot - 1,
            )
            and successor_sdk_call_occurred(
                slot=slot,
                attempt_kind="child",
                sdk_call_count=slot,
            ),
            f"self_test_successor_child_sdk_ordinal_mismatch:{slot}",
        )
    require(
        not consumed_root_absence_can_be_terminal(
            root_sdk_call_occurred=True,
            child_attempt_count=0,
        ),
        "self_test_late_visible_transmitted_root_absence_marked_terminal",
    )
    require(
        consumed_root_absence_can_be_terminal(
            root_sdk_call_occurred=False,
            child_attempt_count=0,
        ),
        "self_test_untransmitted_consumed_root_absence_not_terminal",
    )

    now = datetime.now(timezone.utc)
    preflight = {
        "portfolio_id": "62f28f44-8e72-4fe0-ace7-d71a01f54883",
        "wallets": {"USDC": Decimal("997"), "BTC": Decimal("0")},
        "product": {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
        },
        "best_bid": Decimal("100.00"),
        "best_ask": Decimal("100.01"),
        "market": {
            "product_id": PRODUCT_ID,
            "source": "coinbase_rest_get_best_bid_ask_exact_product",
            "observed_at": now.isoformat(),
        },
    }
    # Successor regression gate: the consumed predecessor contributes its
    # already-FILLED slot-1 root, so the only remaining legal schedule is
    # child-1 followed by root/child pairs for slots 2 through 10.
    predecessor = offline_predecessor_binding_fixture()
    require(
        load_predecessor_binding() == predecessor,
        "self_test_predecessor_artifact_binding_mismatch",
    )
    successor_schedule = successor_attempt_schedule()
    require(
        successor_schedule
        == [(1, "child")]
        + [
            item
            for slot in range(2, BATCH_SIZE + 1)
            for item in ((slot, "root"), (slot, "child"))
        ],
        "self_test_successor_attempt_schedule_mismatch",
    )
    require(
        len(successor_schedule) == 19,
        "self_test_successor_attempt_count_mismatch",
    )
    successor_plan = build_successor_live_plan(
        preflight,
        predecessor_binding=predecessor,
    )
    successor_roots, _ = validate_successor_live_plan(
        successor_plan,
        expected_hash=str(successor_plan["plan_sha256"]),
        preflight=preflight,
        predecessor_binding=predecessor,
    )
    require(
        successor_roots[0]["root_placement_authorized"] is False
        and all(
            root["root_placement_authorized"] is True
            for root in successor_roots[1:]
        ),
        "self_test_successor_root_authority_topology_mismatch",
    )
    expect_successor_root_denial = globals().get(
        "approved_exact_successor_root_tuple"
    )
    require(
        callable(expect_successor_root_denial),
        "self_test_successor_root_tuple_guard_missing",
    )
    plan = successor_plan
    roots = successor_roots
    total_root_notional = Decimal(
        str(plan["planned_new_root_notional_usdc"])
    )

    def expect_proof_failure(callback: Any, blocker: str) -> str:
        try:
            callback()
        except ProofFailure as exc:
            return str(exc)
        raise ProofFailure(blocker)

    require(
        expect_proof_failure(
            lambda: approved_exact_successor_root_tuple(plan, roots[0]),
            "self_test_carried_root_placement_tuple_available",
        )
        == "successor_carried_root_placement_denied",
        "self_test_carried_root_denial_blocker_mismatch",
    )

    # Regression fixtures from the first live slot. Coinbase may decorate a
    # FOK response with false-valued RFQ fields; those fields are evidence, not
    # semantic drift. The active-order reader must also work through both the
    # raw SDK and the backend wrapper while preserving the exact Test-profile
    # filter and independently validating scope on every returned row.
    live_slot_fok = {
        "order_id": "offline-live-slot-exchange-id",
        "client_order_id": "offline-live-slot-client-id",
        "product_id": PRODUCT_ID,
        "retail_portfolio_id": preflight["portfolio_id"],
        "product_type": "SPOT",
        "side": "BUY",
        "status": "FILLED",
        "order_type": "LIMIT",
        "time_in_force": "FILL_OR_KILL",
        "filled_size": "0.00001709",
        "filled_value": "1.0970980188",
        "size_in_quote": False,
        "post_only": None,
        "order_configuration": {
            "limit_limit_fok": {
                "base_size": "0.00001709",
                "limit_price": "64370.13",
                "reduce_only": False,
                "rfq_disabled": False,
                "rfq_enabled": False,
            }
        },
    }
    validated_live_slot_fok = _validate_exact_coinbase_fok_order(
        live_slot_fok,
        expected_exchange_order_id="offline-live-slot-exchange-id",
        expected_client_order_id="offline-live-slot-client-id",
        expected_portfolio_id=str(preflight["portfolio_id"]),
        expected_order_body={
            "base_size": "0.00001709",
            "limit_price": "64370.13",
        },
    )
    require(
        validated_live_slot_fok["status"] == "FILLED",
        "self_test_false_rfq_fok_decoration_not_accepted",
    )
    truthy_rfq_fok = json.loads(json.dumps(live_slot_fok))
    truthy_rfq_fok["order_configuration"]["limit_limit_fok"][
        "rfq_enabled"
    ] = True
    require(
        expect_proof_failure(
            lambda: _validate_exact_coinbase_fok_order(
                truthy_rfq_fok,
                expected_exchange_order_id="offline-live-slot-exchange-id",
                expected_client_order_id="offline-live-slot-client-id",
                expected_portfolio_id=str(preflight["portfolio_id"]),
                expected_order_body={
                    "base_size": "0.00001709",
                    "limit_price": "64370.13",
                },
            ),
            "self_test_truthy_rfq_fok_decoration_not_denied",
        )
        == "exact_fok_order_rfq_enabled_truthy",
        "self_test_truthy_rfq_fok_blocker_mismatch",
    )
    null_rfq_fok = json.loads(json.dumps(live_slot_fok))
    null_rfq_fok["order_configuration"]["limit_limit_fok"][
        "rfq_enabled"
    ] = None
    require(
        expect_proof_failure(
            lambda: _validate_exact_coinbase_fok_order(
                null_rfq_fok,
                expected_exchange_order_id="offline-live-slot-exchange-id",
                expected_client_order_id="offline-live-slot-client-id",
                expected_portfolio_id=str(preflight["portfolio_id"]),
                expected_order_body={
                    "base_size": "0.00001709",
                    "limit_price": "64370.13",
                },
            ),
            "self_test_null_rfq_fok_decoration_not_denied",
        )
        == "exact_fok_order_rfq_enabled_invalid",
        "self_test_null_rfq_fok_blocker_mismatch",
    )
    unknown_rfq_fok = json.loads(json.dumps(live_slot_fok))
    unknown_rfq_fok["order_configuration"]["limit_limit_fok"][
        "unknown_flag"
    ] = False
    require(
        expect_proof_failure(
            lambda: _validate_exact_coinbase_fok_order(
                unknown_rfq_fok,
                expected_exchange_order_id="offline-live-slot-exchange-id",
                expected_client_order_id="offline-live-slot-client-id",
                expected_portfolio_id=str(preflight["portfolio_id"]),
                expected_order_body={
                    "base_size": "0.00001709",
                    "limit_price": "64370.13",
                },
            ),
            "self_test_unknown_fok_decoration_not_denied",
        )
        == "exact_fok_order_fok_unknown_field",
        "self_test_unknown_fok_decoration_blocker_mismatch",
    )

    class OfflineCanonicalOrderWrapper:
        def __init__(
            self,
            orders: Sequence[Mapping[str, Any]] | None = None,
        ) -> None:
            self.calls: list[dict[str, Any]] = []
            self.orders = [dict(row) for row in (orders or [])]

        def list_orders(
            self,
            order_status: list[str] | None = None,
            *,
            order_ids: list[str] | None = None,
            product_ids: list[str] | None = None,
            limit: int | None = None,
            cursor: str | None = None,
            product_type: str | None = None,
            retail_portfolio_id: str | None = None,
        ) -> dict[str, Any]:
            self.calls.append(
                {
                    "order_status": order_status,
                    "order_ids": order_ids,
                    "product_ids": product_ids,
                    "limit": limit,
                    "cursor": cursor,
                    "product_type": product_type,
                    "retail_portfolio_id": retail_portfolio_id,
                }
            )
            return {
                "orders": [dict(row) for row in self.orders],
                "has_next": False,
                "cursor": "",
            }

    canonical_order_wrapper = OfflineCanonicalOrderWrapper()
    require(
        read_authoritative_spot_nonterminal_orders(
            canonical_order_wrapper,
            expected_portfolio_id=str(preflight["portfolio_id"]),
        )
        == [],
        "self_test_canonical_wrapper_active_read_not_empty",
    )
    require(
        canonical_order_wrapper.calls
        == [
            {
                "order_status": ["OPEN"],
                "order_ids": None,
                "product_ids": None,
                "limit": 100,
                "cursor": None,
                "product_type": "SPOT",
                "retail_portfolio_id": preflight["portfolio_id"],
            }
        ],
        "self_test_canonical_wrapper_active_read_arguments_mismatch",
    )
    other_spot_order = {
        "client_order_id": "offline-other-spot-client-id",
        "order_id": "offline-other-spot-exchange-id",
        "status": "OPEN",
        "product_id": "ETH-USDC",
        "product_type": "SPOT",
        "retail_portfolio_id": preflight["portfolio_id"],
    }
    other_spot_rows = read_authoritative_spot_nonterminal_orders(
        OfflineCanonicalOrderWrapper([other_spot_order]),
        expected_portfolio_id=str(preflight["portfolio_id"]),
    )
    require(
        other_spot_rows == [other_spot_order],
        "self_test_other_test_profile_spot_order_not_returned",
    )
    wrong_profile_order = dict(other_spot_order)
    wrong_profile_order["retail_portfolio_id"] = (
        "22222222-3333-4444-8555-666666666666"
    )
    require(
        expect_proof_failure(
            lambda: read_authoritative_spot_nonterminal_orders(
                OfflineCanonicalOrderWrapper([wrong_profile_order]),
                expected_portfolio_id=str(preflight["portfolio_id"]),
            ),
            "self_test_wrong_profile_active_order_not_denied",
        )
        == "active_spot_order_portfolio_mismatch",
        "self_test_wrong_profile_active_order_blocker_mismatch",
    )

    reconciliation_slot_reader = globals().get(
        "_reconciliation_root_plan_slot"
    )
    require(
        callable(reconciliation_slot_reader),
        "self_test_reconciliation_slot_reader_missing",
    )
    require(
        reconciliation_slot_reader({"slot": 1}) == 1,
        "self_test_reconciliation_slot_reader_value_mismatch",
    )
    require(
        expect_proof_failure(
            lambda: reconciliation_slot_reader({"batch_slot": 1}),
            "self_test_reconciliation_batch_slot_alias_accepted",
        )
        == "failure_root_slot_invalid",
        "self_test_reconciliation_slot_blocker_mismatch",
    )

    offline_runner_path = (
        Path(__file__).resolve().relative_to(ROOT).as_posix()
    )
    offline_runner_hash = "a" * 64
    offline_runner_commit = "b" * 40
    topology = validate_runner_commit_topology(
        production_commit=EXPECTED_COMMIT,
        head_commit=offline_runner_commit,
        head_parents=[EXPECTED_COMMIT],
        changed_paths=[offline_runner_path],
        runner_path=offline_runner_path,
        committed_runner_sha256=offline_runner_hash,
        working_runner_sha256=offline_runner_hash,
    )
    require(
        topology.get("runner_only_commit_proven") is True,
        "self_test_runner_only_commit_topology_unproven",
    )
    require(
        expect_proof_failure(
            lambda: validate_runner_commit_topology(
                production_commit=EXPECTED_COMMIT,
                head_commit=EXPECTED_COMMIT,
                head_parents=["c" * 40],
                changed_paths=[offline_runner_path],
                runner_path=offline_runner_path,
                committed_runner_sha256=offline_runner_hash,
                working_runner_sha256=offline_runner_hash,
            ),
            "self_test_missing_runner_commit_not_denied",
        )
        == "runner_commit_missing_above_production_commit",
        "self_test_missing_runner_commit_blocker_mismatch",
    )
    require(
        expect_proof_failure(
            lambda: validate_runner_commit_topology(
                production_commit=EXPECTED_COMMIT,
                head_commit=offline_runner_commit,
                head_parents=["c" * 40],
                changed_paths=[offline_runner_path],
                runner_path=offline_runner_path,
                committed_runner_sha256=offline_runner_hash,
                working_runner_sha256=offline_runner_hash,
            ),
            "self_test_intervening_commit_not_denied",
        )
        == "runner_commit_not_directly_above_production_commit",
        "self_test_intervening_commit_blocker_mismatch",
    )
    require(
        expect_proof_failure(
            lambda: validate_runner_commit_topology(
                production_commit=EXPECTED_COMMIT,
                head_commit=offline_runner_commit,
                head_parents=[EXPECTED_COMMIT],
                changed_paths=[offline_runner_path, "unrelated.py"],
                runner_path=offline_runner_path,
                committed_runner_sha256=offline_runner_hash,
                working_runner_sha256=offline_runner_hash,
            ),
            "self_test_non_runner_commit_path_not_denied",
        )
        == "runner_commit_contains_non_runner_paths",
        "self_test_non_runner_commit_path_blocker_mismatch",
    )
    require(
        expect_proof_failure(
            lambda: validate_runner_commit_topology(
                production_commit=EXPECTED_COMMIT,
                head_commit=offline_runner_commit,
                head_parents=[EXPECTED_COMMIT],
                changed_paths=[offline_runner_path],
                runner_path=offline_runner_path,
                committed_runner_sha256="c" * 64,
                working_runner_sha256=offline_runner_hash,
            ),
            "self_test_runner_blob_mismatch_not_denied",
        )
        == "committed_runner_bytes_mismatch",
        "self_test_runner_blob_mismatch_blocker_mismatch",
    )

    require(len(roots) == BATCH_SIZE == 10, "self_test_root_count_mismatch")
    require(
        [root["slot"] for root in roots] == list(range(1, 11)),
        "self_test_root_slots_mismatch",
    )
    root_ids = [str(root["root_client_order_id"]) for root in roots]
    child_ids = [str(root["child_client_order_id"]) for root in roots]
    require(len(set(root_ids)) == 10, "self_test_root_ids_not_unique")
    require(len(set(child_ids)) == 10, "self_test_child_ids_not_unique")
    require(not set(root_ids) & set(child_ids), "self_test_root_child_id_collision")
    historical_ids = {
        HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID,
        HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID,
    }
    require(
        not (set(root_ids) | set(child_ids)) & historical_ids,
        "self_test_historical_id_collision",
    )
    require(
        deterministic_child_client_order_id(
            HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID
        )
        == HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID,
        "self_test_historical_child_derivation_mismatch",
    )
    require(
        Decimal(str(plan["planned_total_root_child_reference_notional_usdc"]))
        < BATCH_TOTAL_REFERENCE_CAP_USDC,
        "self_test_planned_batch_reference_cap_failed",
    )
    require(
        Decimal("9") < total_root_notional < Decimal("11"),
        "self_test_new_root_notional_unexpected",
    )
    predecessor_planned_ids = set(
        PREDECESSOR_PLANNED_ROOT_CLIENT_ORDER_IDS
    ) | set(PREDECESSOR_PLANNED_CHILD_CLIENT_ORDER_IDS)
    require(
        not (set(root_ids[1:]) | set(child_ids[1:]))
        & predecessor_planned_ids,
        "self_test_fresh_successor_predecessor_id_collision",
    )
    require(
        root_ids[0] == CARRIED_ROOT_CLIENT_ORDER_ID
        and child_ids[0] == CARRIED_CHILD_CLIENT_ORDER_ID,
        "self_test_carried_pair_identity_mismatch",
    )

    tampered_plan = dict(plan)
    tampered_plan["batch_size"] = 11
    require(
        plan_hash(tampered_plan) != plan["plan_sha256"],
        "self_test_plan_hash_not_binding",
    )
    expect_proof_failure(
        lambda: validate_successor_live_plan(
            tampered_plan,
            expected_hash=str(plan["plan_sha256"]),
            preflight=preflight,
            predecessor_binding=predecessor,
        ),
        "self_test_tampered_plan_accepted",
    )

    offline_test_root = (
        ROOT / "genai_tools" / "pytest-tmp" / "controlled-batch-offline"
    )
    marker_payload = build_global_batch_marker_payload(
        offline_test_root / "controlled-root-child-batch-plan.json",
        confirmed_plan=plan,
        expected_hash=str(plan["plan_sha256"]),
        expected_runner_sha256=str(plan["runner_sha256"]),
        registered_at=now.isoformat(),
        process_id=12345,
    )
    require(
        marker_payload["authority"]
        == "controlled-admin-spot-root-child-successor-batch",
        "self_test_global_marker_authority_mismatch",
    )
    require(
        marker_payload["marker_path"].endswith(GLOBAL_BATCH_MARKER_FILENAME)
        and marker_payload["attempt_ledger_path"].endswith(
            GLOBAL_BATCH_LEDGER_FILENAME
        ),
        "self_test_global_batch_paths_not_fixed",
    )
    second_plan = build_successor_live_plan(
        preflight,
        predecessor_binding=predecessor,
    )
    require(
        second_plan["batch_id"] != plan["batch_id"],
        "self_test_second_batch_fixture_not_distinct",
    )
    require(
        batch_registry_paths(str(second_plan["batch_id"]))
        == batch_registry_paths(str(plan["batch_id"])),
        "self_test_second_plan_received_new_global_authority_path",
    )
    require(
        marker_payload["root_order_maximum"]
        == SUCCESSOR_ROOT_ORDER_MAXIMUM
        and marker_payload["child_order_maximum"]
        == SUCCESSOR_CHILD_ORDER_MAXIMUM
        and marker_payload["remaining_attempt_count"]
        == SUCCESSOR_ATTEMPT_COUNT
        and len(marker_payload["exact_root_tuples"])
        == SUCCESSOR_ROOT_ORDER_MAXIMUM
        and marker_payload["exact_child_client_order_ids"] == child_ids
        and marker_payload["predecessor_binding"] == predecessor,
        "self_test_global_marker_limits_mismatch",
    )
    require(
        marker_payload["inherited_reference_notional_usdc"]
        == decimal_text(CARRIED_ROOT_PLANNED_NOTIONAL),
        "self_test_global_marker_inherited_cap_seed_mismatch",
    )
    require(
        marker_payload["child_policy"]["strict_batch_reference_cap_usdc"]
        == decimal_text(BATCH_TOTAL_REFERENCE_CAP_USDC),
        "self_test_global_marker_batch_cap_mismatch",
    )
    expect_proof_failure(
        lambda: require_batch_unregistered(
            marker_exists=True,
            ledger_exists=False,
        ),
        "self_test_crash_marker_without_ledger_reusable",
    )
    expect_proof_failure(
        lambda: require_batch_unregistered(
            marker_exists=False,
            ledger_exists=True,
        ),
        "self_test_crash_ledger_without_marker_reusable",
    )
    expect_proof_failure(
        lambda: require_batch_unregistered(
            marker_exists=True,
            ledger_exists=True,
        ),
        "self_test_completed_registration_reusable",
    )
    require_batch_unregistered(marker_exists=False, ledger_exists=False)

    offline_state_dir = offline_test_root / "runtime-state"
    offline_auth_file = offline_state_dir / RUNTIME_CHILD_AUTH_FILENAME
    marker_path, ledger_path = batch_registry_paths(str(plan["batch_id"]))
    authority_payload = build_runtime_child_authority_payload(
        state_dir=offline_state_dir,
        auth_file=offline_auth_file,
        global_batch_marker=marker_path,
        global_batch_marker_sha256="a" * 64,
        attempt_ledger_path=ledger_path,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
        confirmed_runner_sha256=str(plan["runner_sha256"]),
        parent_pid=12345,
        parent_start_identity="67890",
        nonce="offline-batch-nonce",
    )
    validated_authority_plan = validate_runtime_child_authority_payload(
        authority_payload,
        state_dir=offline_state_dir,
        auth_file=offline_auth_file,
        supplied_nonce="offline-batch-nonce",
        actual_parent_pid=12345,
        actual_parent_start_identity="67890",
    )
    require(
        validated_authority_plan == plan,
        "self_test_runtime_authority_plan_mismatch",
    )
    expect_proof_failure(
        lambda: validate_runtime_child_authority_payload(
            authority_payload,
            state_dir=offline_state_dir,
            auth_file=offline_auth_file,
            supplied_nonce="wrong",
            actual_parent_pid=12345,
            actual_parent_start_identity="67890",
        ),
        "self_test_runtime_authority_wrong_nonce_accepted",
    )

    raw_ledger = b""
    records: list[dict[str, Any]] = []
    child_tuple_by_slot: dict[int, dict[str, Any]] = {}
    root_sdk_call_count = 0
    child_sdk_call_count = 0
    cumulative_reference_notional = CARRIED_ROOT_PLANNED_NOTIONAL
    for slot, attempt_kind in successor_schedule:
        root_plan = roots[slot - 1]
        order = object_record(root_plan["order"])
        if attempt_kind == "root":
            exact_tuple = approved_exact_successor_root_tuple(
                plan,
                root_plan,
            )
        else:
            exact_tuple = build_child_order_tuple(
                plan,
                root_plan,
                filled_size=Decimal(str(order["base_size"])),
                fresh_market={
                    "best_bid": preflight["best_bid"],
                    "observed_at": now.isoformat(),
                },
                price_increment=Decimal("0.01"),
            )
            child_tuple_by_slot[slot] = exact_tuple
        sequence = require_next_batch_attempt(
            records,
            slot=slot,
            attempt_kind=attempt_kind,
        )
        record = build_batch_attempt_record(
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
            sequence=sequence,
            slot=slot,
            attempt_kind=attempt_kind,
            exact_order_tuple=exact_tuple,
            consumed_at=now.isoformat(),
            process_id=12345,
        )
        raw_ledger += (
            json.dumps(record, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        records = _parse_and_validate_attempt_ledger(
            raw_ledger,
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
        )
        if attempt_kind == "root":
            authorized_root = authorized_sdk_tuple_for_call(
                records,
                attempt_kind="root",
                prior_call_count=root_sdk_call_count,
            )
            validate_canonical_root_create_order_call(
                (),
                {
                    "client_order_id": order["client_order_id"],
                    "product_id": PRODUCT_ID,
                    "side": "BUY",
                    "order_configuration": {
                        "limit_limit_fok": {
                            "base_size": order["base_size"],
                            "limit_price": order["limit_price"],
                        }
                    },
                },
                exact_tuple=authorized_root,
            )
            root_sdk_call_count += 1
        else:
            authorized_child = authorized_sdk_tuple_for_call(
                records,
                attempt_kind="child",
                prior_call_count=child_sdk_call_count,
            )
            validate_canonical_child_place_limit_order_call(
                (),
                {
                    "product_id": PRODUCT_ID,
                    "side": "SELL",
                    "limit_price": exact_tuple["limit_price"],
                    "base_size": exact_tuple["base_size"],
                    "client_order_id": exact_tuple["client_order_id"],
                    "post_only": False,
                },
                exact_tuple=authorized_child,
            )
            child_sdk_call_count += 1
        tuple_notional = Decimal(str(exact_tuple["base_size"])) * Decimal(
            str(exact_tuple["limit_price"])
        )
        if attempt_kind == "child":
            require(
                tuple_notional < CHILD_SUBMITTED_CAP,
                f"self_test_child_cap_failed:{slot}",
            )
        cumulative_reference_notional += tuple_notional
        require(
            cumulative_reference_notional < BATCH_TOTAL_REFERENCE_CAP_USDC,
            f"self_test_cumulative_batch_cap_failed:{slot}:{attempt_kind}",
        )

    child_tuples = [child_tuple_by_slot[slot] for slot in range(1, 11)]
    require(
        len(records) == SUCCESSOR_ATTEMPT_COUNT,
        "self_test_attempt_ledger_count_mismatch",
    )
    require(
        root_sdk_call_count == SUCCESSOR_ROOT_ORDER_MAXIMUM,
        "self_test_root_sdk_count_mismatch",
    )
    require(
        child_sdk_call_count == SUCCESSOR_CHILD_ORDER_MAXIMUM,
        "self_test_child_sdk_count_mismatch",
    )
    require(
        [
            (int(record["batch_slot"]), str(record["attempt_kind"]))
            for record in records
        ]
        == successor_schedule,
        "self_test_attempt_sequence_mismatch",
    )
    expect_proof_failure(
        lambda: authorized_sdk_tuple_for_call(
            records,
            attempt_kind="root",
            prior_call_count=SUCCESSOR_ROOT_ORDER_MAXIMUM,
        ),
        "self_test_tenth_successor_root_sdk_call_accepted",
    )
    expect_proof_failure(
        lambda: authorized_sdk_tuple_for_call(
            records,
            attempt_kind="child",
            prior_call_count=SUCCESSOR_CHILD_ORDER_MAXIMUM,
        ),
        "self_test_eleventh_cumulative_child_sdk_call_accepted",
    )
    expect_proof_failure(
        lambda: require_next_batch_attempt(
            records,
            slot=1,
            attempt_kind="child",
        ),
        "self_test_full_ledger_replay_accepted",
    )

    child_one_raw = raw_ledger.splitlines(keepends=True)[0]
    child_one_records = _parse_and_validate_attempt_ledger(
        child_one_raw,
        confirmed_plan=plan,
        confirmed_plan_hash=str(plan["plan_sha256"]),
    )
    expect_proof_failure(
        lambda: require_next_batch_attempt(
            child_one_records,
            slot=1,
            attempt_kind="child",
        ),
        "self_test_consumed_child_one_replay_accepted",
    )
    expect_proof_failure(
        lambda: require_next_batch_attempt(
            child_one_records,
            slot=2,
            attempt_kind="child",
        ),
        "self_test_crash_prefix_skipped_root_two",
    )

    drifted_root = dict(
        approved_exact_successor_root_tuple(plan, roots[1])
    )
    drifted_root["base_size"] = decimal_text(
        Decimal(str(drifted_root["base_size"])) + Decimal("0.00000001")
    )
    expect_proof_failure(
        lambda: build_batch_attempt_record(
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
            sequence=2,
            slot=2,
            attempt_kind="root",
            exact_order_tuple=drifted_root,
            consumed_at=now.isoformat(),
            process_id=12345,
        ),
        "self_test_root_tuple_drift_accepted",
    )
    drifted_child = dict(child_tuples[0])
    drifted_child["client_order_id"] = deterministic_child_client_order_id(
        str(roots[0]["child_client_order_id"])
    )
    expect_proof_failure(
        lambda: build_batch_attempt_record(
            confirmed_plan=plan,
            confirmed_plan_hash=str(plan["plan_sha256"]),
            sequence=1,
            slot=1,
            attempt_kind="child",
            exact_order_tuple=drifted_child,
            consumed_at=now.isoformat(),
            process_id=12345,
        ),
        "self_test_later_generation_child_accepted",
    )
    drifted_child_price = dict(child_tuples[0])
    drifted_child_price["limit_price"] = decimal_text(
        Decimal(str(drifted_child_price["limit_price"])) - Decimal("0.01")
    )
    expect_proof_failure(
        lambda: _validate_authorized_child_tuple(
            plan,
            roots[0],
            drifted_child_price,
        ),
        "self_test_child_price_drift_accepted",
    )

    canonical_child_order = {
        "order_id": "offline-child-exchange-id",
        "client_order_id": child_tuples[0]["client_order_id"],
        "product_id": PRODUCT_ID,
        "product_type": "SPOT",
        "retail_portfolio_id": preflight["portfolio_id"],
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "status": "OPEN",
        "filled_size": "0",
        "post_only": False,
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": child_tuples[0]["base_size"],
                "limit_price": child_tuples[0]["limit_price"],
                "post_only": False,
            }
        },
    }
    _validate_exact_coinbase_gtc_child_order(
        canonical_child_order,
        expected_exchange_order_id="offline-child-exchange-id",
        expected_portfolio_id=str(preflight["portfolio_id"]),
        expected_child_tuple=child_tuples[0],
    )

    child_id = child_ids[0]
    root_id = root_ids[0]
    order = object_record(roots[0]["order"])
    for preexchange_status in ("HIDDEN", "PENDING", "TRIGGERED"):
        fake_chain = {
            "type": "admin_order_fill_follow_up_chain",
            "found": True,
            "client_order_id": root_id,
            "root_parent_client_order_id": root_id,
            "follow_up_child_count": 1,
            "follow_up_child_client_order_ids": [child_id],
            "duplicate_child_client_order_ids": [],
            "nested_child_client_order_ids": [],
            "nested_parent_client_order_ids": [],
            "flat_hierarchy_violation_count": 0,
            "order_parent_child_read_ran": True,
            "stealth_child_read_ran": True,
            "blockers": [],
            "root_order": {
                "client_order_id": root_id,
                "status": "FILLED",
                "ownership_provenance": "ADMIN_MANUAL_ROOT",
                "retail_portfolio_id": preflight["portfolio_id"],
                "parent_client_order_id": None,
                "correlation_id": "corr-root",
                "audit_id": "audit-root",
                "exchange_order_id": "offline-root-exchange-id",
            },
            "follow_up_children": [
                {
                    "client_order_id": child_id,
                    "product_id": PRODUCT_ID,
                    "side": "SELL",
                    "status": preexchange_status,
                    "stealth_status": preexchange_status,
                    "ownership_provenance": "ADMIN_FILL_FOLLOW_UP",
                    "parent_client_order_id": root_id,
                    "retail_portfolio_id": preflight["portfolio_id"],
                    "exchange_order_id": None,
                    "correlation_id": "corr-root",
                    "audit_id": "audit-root",
                    "size": order["base_size"],
                    "price": "101.00",
                    "last_lifecycle_event": "CREATED",
                }
            ],
            "portfolio_scope": {"scope_consistent": True, "status": "matched"},
            "fill_follow_up_decision_audit": {
                "automatic_fill_event_processing_enabled": True,
                "automation_mode": "automatic_owned_root_fill_event",
                "claim_state": "done",
                "existing_follow_up_client_order_ids": [child_id],
                "existing_follow_up_count": 1,
                "follow_up_decision": "automatic_child_created",
            },
            "read_only": True,
            "live_coinbase_orders_ran": False,
            "local_state_mutated": False,
            "exchange_state_mutated": False,
        }
        validated_child = _validate_automatic_hidden_child_chain(
            fake_chain,
            root_client_order_id=root_id,
            portfolio_id=str(preflight["portfolio_id"]),
            expected_filled_size=Decimal(str(order["base_size"])),
            expected_placement_correlation_id="corr-root",
            expected_admission_audit_id="audit-root",
            expected_exchange_order_id="offline-root-exchange-id",
        )
        require(
            str(
                validated_child.get("stealth_status")
                or validated_child.get("status")
            ).upper()
            == preexchange_status,
            "self_test_preexchange_status_not_preserved",
        )

    source = Path(__file__).resolve().read_text(encoding="utf-8")
    execution_source = source[
        source.index("def execute_controlled_batch(") :
        source.index("def run_offline_self_test(")
    ]
    require(
        HISTORICAL_FILLED_ROOT_CLIENT_ORDER_ID not in execution_source
        and HISTORICAL_HIDDEN_CHILD_CLIENT_ORDER_ID not in execution_source,
        "self_test_historical_chain_targeted_by_execution",
    )
    for required_fragment in (
        "historical_stealth_child_not_wholly_unsubmitted",
        "unrelated_local_nonterminal_parent_present",
        "unrelated_local_nonterminal_stealth_present",
        "reconcile_failure_state(",
        "set_live_service(runtime, enabled=False)",
        "child_sdk_controlled_route_preparation_mismatch",
        "controlled-batch-parent-authority-watchdog",
        "parent_authority_lost_reconciliation_only",
        "new_sdk_placements_denied",
        "exact_child_admin_cancel",
        "root_sdk_call_not_quiescent",
        "child_sdk_call_not_quiescent",
        '"/admin/runtime"',
        "_validate_cancelled_child_chain(",
        "exact_transmitted_attempt_state(",
        "continue_monitoring_quiescent_zero",
        "issue_same_idempotent_exact_cancel",
        "same_idempotency_key_exact_cancel_only",
    ):
        require(
            required_fragment in source,
            f"self_test_static_safety_fragment_missing:{required_fragment}",
        )
    forbidden_watchdog_kill = "os.kill(os.getpid(), " + "signal.SIGTERM)"
    require(
        forbidden_watchdog_kill not in source,
        "self_test_parent_loss_watchdog_can_kill_runtime",
    )

    return {
        "status": "offline_self_test_passed",
        "backend_commit": EXPECTED_COMMIT,
        "runner_sha256": runner_sha256(),
        "batch_size": BATCH_SIZE,
        "carried_root_slots": [1],
        "successor_root_slots": list(range(2, 11)),
        "child_slots": list(range(1, 11)),
        "root_client_order_ids_unique": True,
        "child_client_order_ids_unique": True,
        "root_child_ids_disjoint": True,
        "historical_chain_ids_disjoint": True,
        "historical_chain_read_only_exception_static_proven": True,
        "preexchange_child_statuses_proven": [
            "HIDDEN",
            "PENDING",
            "TRIGGERED",
        ],
        "root_order_type": "LIMIT",
        "root_time_in_force": "FILL_OR_KILL",
        "root_post_only": False,
        "child_order_type": "LIMIT",
        "child_time_in_force": "GOOD_UNTIL_CANCELLED",
        "child_post_only": False,
        "child_minimum_bid_ratio": decimal_text(CHILD_MINIMUM_BID_RATIO),
        "child_strict_max_notional_usdc": decimal_text(CHILD_SUBMITTED_CAP),
        "batch_strict_reference_cap_usdc": decimal_text(
            BATCH_TOTAL_REFERENCE_CAP_USDC
        ),
        "planned_total_root_child_reference_notional_usdc": plan[
            "planned_total_root_child_reference_notional_usdc"
        ],
        "inherited_root_reference_notional_usdc": decimal_text(
            CARRIED_ROOT_PLANNED_NOTIONAL
        ),
        "successor_attempt_schedule": successor_schedule,
        "attempt_ledger_record_count": SUCCESSOR_ATTEMPT_COUNT,
        "attempt_sequence_proven": True,
        "carried_root_placement_denied": True,
        "predecessor_plan_bytes_bound": PREDECESSOR_PLAN_BYTES_SHA256,
        "predecessor_marker_bytes_bound": PREDECESSOR_MARKER_BYTES_SHA256,
        "predecessor_ledger_bytes_bound": PREDECESSOR_LEDGER_BYTES_SHA256,
        "predecessor_sentinel_bytes_bound": (
            PREDECESSOR_SENTINEL_BYTES_SHA256
        ),
        "predecessor_cleanup_bytes_bound": PREDECESSOR_CLEANUP_BYTES_SHA256,
        "predecessor_artifacts_preserved_read_only": True,
        "fresh_slots_disjoint_from_all_predecessor_planned_ids": True,
        "replay_denied": True,
        "crash_marker_denied": True,
        "global_batch_reauthorization_by_new_plan_denied": True,
        "crash_prefix_cannot_skip": True,
        "parent_crash_enters_reconciliation_only_static_proven": True,
        "parent_loss_late_sdk_order_race_denied": True,
        "parent_loss_empty_visibility_window_continues_monitoring": True,
        "parent_loss_exact_order_detail_polling_static_proven": True,
        "parent_loss_timeout_cancel_same_idempotency_retry_proven": True,
        "parent_loss_non_200_cancel_same_idempotency_retry_proven": True,
        "failure_reconciliation_successor_sdk_ordinals_proven": True,
        "failure_reconciliation_late_visible_root_absence_denied": True,
        "tuple_drift_denied": True,
        "later_generation_child_denied": True,
        "generic_same_tuple_child_without_route_preparation_denied": True,
        "tenth_successor_root_sdk_call_denied": True,
        "eleventh_cumulative_root_sdk_call_denied": True,
        "eleventh_cumulative_child_sdk_call_denied": True,
        "successor_root_sdk_maximum": SUCCESSOR_ROOT_ORDER_MAXIMUM,
        "successor_child_sdk_maximum": SUCCESSOR_CHILD_ORDER_MAXIMUM,
        "cumulative_root_count_after_success": BATCH_SIZE,
        "cumulative_child_count_after_success": BATCH_SIZE,
        "runtime_child_authority_validation_proven": True,
        "production_parent_commit_bound": EXPECTED_COMMIT,
        "runner_only_direct_child_commit_topology_proven": True,
        "intervening_or_unrelated_commit_denied": True,
        "committed_runner_blob_hash_binding_proven": True,
        "live_path_tmp_dependency_absent": True,
        "execution_lease_in_owner_only_durable_registry": True,
        "service_disable_and_failure_reconciliation_static_proven": True,
        "network_used": False,
        "credentials_loaded": False,
        "global_marker_written": False,
        "attempt_ledger_written": False,
    }


def _planned_client_order_ids(plan: Mapping[str, Any]) -> set[str]:
    return {
        str(value)
        for root in [
            object_record(item) for item in list_value(plan.get("roots"))
        ]
        for value in (
            root.get("root_client_order_id"),
            root.get("child_client_order_id"),
        )
        if value
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute-controlled-batch", action="store_true")
    mode.add_argument("--prepare-controlled-batch-plan", type=Path)
    mode.add_argument("--offline-self-test", action="store_true")
    mode.add_argument("--runtime-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--confirm-plan-sha256")
    parser.add_argument("--runtime-state-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--runtime-auth-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.offline_self_test:
        require(args.plan_file is None, "plan_file_not_allowed_in_self_test")
        require(
            args.confirm_plan_sha256 is None,
            "plan_hash_not_allowed_in_self_test",
        )
        require(
            args.runtime_state_dir is None,
            "runtime_state_dir_not_allowed_in_self_test",
        )
        require(
            args.runtime_auth_file is None,
            "runtime_auth_file_not_allowed_in_self_test",
        )
        print(json.dumps(run_offline_self_test(), sort_keys=True))
        return 0

    if args.runtime_child:
        require(args.runtime_state_dir is not None, "runtime_state_dir_required")
        require(args.runtime_auth_file is not None, "runtime_auth_file_required")
        require(args.plan_file is None, "plan_file_not_allowed_in_runtime_child")
        require(
            args.confirm_plan_sha256 is None,
            "plan_hash_not_allowed_in_runtime_child",
        )
        return run_embedded_runtime_child(
            state_dir=args.runtime_state_dir,
            auth_file=args.runtime_auth_file,
        )

    require(
        args.runtime_state_dir is None,
        "runtime_state_dir_requires_runtime_child",
    )
    require(
        args.runtime_auth_file is None,
        "runtime_auth_file_requires_runtime_child",
    )
    require_clean_commit()
    rest_client = hydrate_test_credentials()
    preflight = coinbase_preflight(rest_client)
    predecessor_binding = load_predecessor_binding()
    carried_plan = {
        "root_client_order_id": CARRIED_ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": CARRIED_CHILD_CLIENT_ORDER_ID,
    }
    historical_scope = prove_local_scope_with_historical_hidden_child(
        planned_client_order_ids=set(),
        carried_root_plan=carried_plan,
        require_carried_hidden=True,
    )
    sanitized = {
        "status": "read_only_preflight_passed",
        "backend_commit": EXPECTED_COMMIT,
        "runner_sha256": runner_sha256(),
        "profile_label": PROFILE_LABEL,
        "profile_type": "CONSUMER",
        "can_view": True,
        "can_trade": True,
        "product_id": PRODUCT_ID,
        "root_operator_intent": INTENTIONAL_FILL_OPERATOR_INTENT,
        "root_order_type": "LIMIT",
        "root_time_in_force": "FILL_OR_KILL",
        "root_post_only": False,
        "successor_attempt_count": SUCCESSOR_ATTEMPT_COUNT,
        "successor_attempt_schedule": successor_attempt_schedule(),
        "successor_root_order_maximum": SUCCESSOR_ROOT_ORDER_MAXIMUM,
        "successor_child_order_maximum": SUCCESSOR_CHILD_ORDER_MAXIMUM,
        "cumulative_root_order_count_after_success": BATCH_SIZE,
        "cumulative_child_order_count_after_success": BATCH_SIZE,
        "child_side": "SELL",
        "child_time_in_force": "GOOD_UNTIL_CANCELLED",
        "child_post_only": False,
        "child_minimum_bid_ratio": decimal_text(CHILD_MINIMUM_BID_RATIO),
        "child_strict_max_notional_usdc": decimal_text(CHILD_SUBMITTED_CAP),
        "batch_strict_reference_cap_usdc": decimal_text(
            BATCH_TOTAL_REFERENCE_CAP_USDC
        ),
        "best_bid": decimal_text(Decimal(str(preflight["best_bid"]))),
        "best_ask": decimal_text(Decimal(str(preflight["best_ask"]))),
        "market_observed_at": object_record(preflight.get("market")).get(
            "observed_at"
        ),
        "usdc_available": decimal_text(
            Decimal(str(preflight["wallets"]["USDC"]))
        ),
        "exchange_active_spot_order_count": preflight[
            "active_spot_order_count"
        ],
        "historical_chain_exception": historical_scope,
        "predecessor_binding": predecessor_binding,
        "live_execution_requested": args.execute_controlled_batch,
        "controlled_batch_plan_requested": (
            args.prepare_controlled_batch_plan is not None
        ),
    }
    print(json.dumps(sanitized, sort_keys=True))

    if args.prepare_controlled_batch_plan is not None:
        require(args.plan_file is None, "plan_file_not_allowed_during_prepare")
        require(
            args.confirm_plan_sha256 is None,
            "plan_confirmation_not_allowed_during_prepare",
        )
        plan = build_successor_live_plan(
            preflight,
            predecessor_binding=predecessor_binding,
        )
        validate_successor_live_plan(
            plan,
            expected_hash=str(plan["plan_sha256"]),
            preflight=preflight,
            predecessor_binding=predecessor_binding,
        )
        planned_ids = _planned_client_order_ids(plan)
        prove_local_scope_with_historical_hidden_child(
            planned_client_order_ids=planned_ids,
            carried_root_plan=object_record(plan["roots"][0]),
            require_carried_hidden=True,
        )
        write_controlled_live_plan(args.prepare_controlled_batch_plan, plan)
        print(
            json.dumps(
                {
                    "status": "controlled_batch_plan_prepared",
                    "live_execution_requested": False,
                    "plan_file": str(args.prepare_controlled_batch_plan),
                    "plan_sha256": plan["plan_sha256"],
                    "backend_commit": plan["backend_commit"],
                    "runner_sha256": plan["runner_sha256"],
                    "approval_id": plan["approval_id"],
                    "batch_id": plan["batch_id"],
                    "batch_size": plan["batch_size"],
                    "successor_attempt_count": plan[
                        "remaining_attempt_count"
                    ],
                    "successor_attempt_schedule": successor_attempt_schedule(),
                    "successor_root_order_maximum": plan[
                        "new_root_order_maximum"
                    ],
                    "successor_child_order_maximum": plan[
                        "child_order_maximum"
                    ],
                    "cumulative_root_order_count_after_success": BATCH_SIZE,
                    "cumulative_child_order_count_after_success": BATCH_SIZE,
                    "root_client_order_ids": [
                        root["root_client_order_id"] for root in plan["roots"]
                    ],
                    "child_client_order_ids": [
                        root["child_client_order_id"] for root in plan["roots"]
                    ],
                    "root_slots": [
                        root["slot"] for root in plan["roots"]
                    ],
                    "planned_total_root_notional_usdc": plan[
                        "planned_total_root_notional_usdc"
                    ],
                    "inherited_root_reference_notional_usdc": plan[
                        "inherited_root_reference_notional_usdc"
                    ],
                    "planned_new_root_notional_usdc": plan[
                        "planned_new_root_notional_usdc"
                    ],
                    "planned_total_child_reference_notional_usdc": plan[
                        "planned_total_child_reference_notional_usdc"
                    ],
                    "planned_total_root_child_reference_notional_usdc": plan[
                        "planned_total_root_child_reference_notional_usdc"
                    ],
                    "batch_total_reference_cap_usdc": plan[
                        "batch_total_reference_cap_usdc"
                    ],
                    "expires_at": plan["expires_at"],
                },
                sort_keys=True,
            )
        )
        return 0

    if not args.execute_controlled_batch:
        require(
            args.plan_file is None,
            "plan_file_requires_controlled_batch_execute",
        )
        require(
            args.confirm_plan_sha256 is None,
            "plan_confirmation_requires_controlled_batch_execute",
        )
        return 0

    require(args.plan_file is not None, "controlled_batch_plan_file_required")
    require(
        bool(args.confirm_plan_sha256),
        "controlled_batch_plan_confirmation_required",
    )
    confirmed_plan = read_controlled_live_plan(args.plan_file)
    validate_successor_live_plan(
        confirmed_plan,
        expected_hash=str(args.confirm_plan_sha256),
        preflight=preflight,
        predecessor_binding=predecessor_binding,
    )
    planned_ids = _planned_client_order_ids(confirmed_plan)
    require(len(planned_ids) == BATCH_SIZE * 2, "controlled_batch_plan_ids_not_exact")
    prove_local_scope_with_historical_hidden_child(
        planned_client_order_ids=planned_ids,
        carried_root_plan=object_record(confirmed_plan["roots"][0]),
        require_carried_hidden=True,
    )
    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, controlled_termination_handler)
    signal.signal(signal.SIGTERM, controlled_termination_handler)
    try:
        with ControlledExecutionLease():
            require_runtime_exclusivity(
                allowed_runtime_pids=set(),
                require_port_free=True,
            )
            require(
                load_predecessor_binding() == predecessor_binding,
                "predecessor_artifacts_changed_before_successor_registration",
            )
            marker_path, ledger_path = initialize_global_batch_ledger(
                args.plan_file,
                confirmed_plan=confirmed_plan,
                expected_hash=str(args.confirm_plan_sha256),
                expected_runner_sha256=str(confirmed_plan["runner_sha256"]),
            )
            summary = execute_controlled_batch(
                rest_client,
                preflight,
                confirmed_plan=confirmed_plan,
                confirmed_plan_hash=str(args.confirm_plan_sha256),
                global_batch_marker=marker_path,
                attempt_ledger_path=ledger_path,
            )
            summary["global_batch_marker"] = str(marker_path)
            summary["attempt_ledger_path"] = str(ledger_path)
            (Path(str(summary["state_dir"])) / "controlled-batch-summary.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True, default=str)
                + "\n",
                encoding="utf-8",
            )
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    print(json.dumps(summary, sort_keys=True, default=str))
    return 0 if summary.get("status") == "passed" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        raise SystemExit(1)
    except KeyboardInterrupt as exc:
        print(
            json.dumps(
                {"status": "interrupted_after_recovery", "reason": str(exc)},
                sort_keys=True,
            )
        )
        raise SystemExit(130)
