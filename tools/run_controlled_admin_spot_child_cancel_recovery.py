"""Sealed V15R2 recovery for the stopped V15R1 hidden first child.

The recovery has no root placement authority.  Plan preparation reads only
immutable local V15R1 evidence and local database state.  It creates only an
owner-only plan; marker, ledgers, runtime, Coinbase placement, and cancellation
remain behind a separate exact plan-hash approval.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import time
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg2

from tools import run_controlled_admin_spot_child_cancel_slice as v15
from tools import run_controlled_admin_spot_root_child_batch as base


ProofFailure = base.ProofFailure
PRODUCT_ID = base.PRODUCT_ID
PROFILE_LABEL = base.PROFILE_LABEL
TEST_PORTFOLIO_ID = base.TEST_PORTFOLIO_ID
ROOT_REFERENCE_CAP = Decimal("9.99")
CHILD_SUBMITTED_CAP = Decimal("2.00")
SLICE_REFERENCE_CAP = Decimal("12.00")
CONSERVATIVE_REFERENCE_NOTIONAL = Decimal("11.99")
PLAN_TTL = timedelta(minutes=120)
PLAN_SCHEMA_VERSION = "20"
AUTHORITY_KIND = "selected_chain_child_cancel_recovery_v15r2"
CHILD_REVEAL_OPERATOR_INTENT = v15.CHILD_REVEAL_OPERATOR_INTENT
CHILD_CANCEL_OPERATOR_INTENT = v15.CHILD_CANCEL_OPERATOR_INTENT

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT.parent / "coinbase-frontend"
PLAN_PATH = Path(
    "/home/ec2-user/.local/state/"
    "coinbase-controlled-spot-child-cancel-v15r2-20260713.plan.json"
)
REGISTRY_DIR = Path("/var/tmp/coinbase-admin-controlled-spot-root-child-batches")
MARKER_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.authority.json"
)
PLACEMENT_LEDGER_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.placements.jsonl"
)
CANCEL_LEDGER_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.cancel-command.jsonl"
)
BACKEND_CLAIM_LOG_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.backend-claims.jsonl"
)
HANDOFF_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.handoff.json"
)

R1_PLAN_SHA256 = "24fc4e211d87c7c3a95d87002f9894ff3119f1e08a48aa4d1ab68c00c7f138ed"
R1_BATCH_ID = "fb2ca86c-7ff3-5493-a1bd-d3a73fc1e322"
R1_ROOT_CLIENT_ORDER_ID = "e4ad814e-c0d1-521a-a8c5-458243935ad2"
R1_CHILD_CLIENT_ORDER_ID = "e403d359-ecf3-59dc-b5b0-dfdd3c3efdaf"
R1_ROOT_EXCHANGE_ORDER_ID = "9eb2038c-5059-434c-a117-62ea0b804837"
R1_ROOT_REFERENCE_NOTIONAL = Decimal("1.0103795104")
R1_ROOT_FILLED_SIZE = Decimal("0.00001583")
R1_ROOT_FILLED_VALUE = Decimal("1.0075796583")
R1_CHILD_CONSUMED_REFERENCE_NOTIONAL = Decimal("1.7120800362")
R1_FILL_PROOF_KEY = (
    "spot_fill_readback:e4ad814e-c0d1-521a-a8c5-458243935ad2:"
    "audit-18ecf7f4-a489-5f3f-968f-4ce8167cdc90"
)
R1_FILL_PROOF_CANONICAL_SHA256 = (
    "f8428444e8b2a6193ef49bd76d1e4d1fa8178f31ee492ef48368d3920f48bfad"
)
R1_STATE_DIR = ROOT / "artifacts/controlled-root-child-batch-20260713T012938Z-24703c84"
R1_ARTIFACT_PATHS: dict[str, str] = {
    "plan_path": (
        "/home/ec2-user/.local/state/"
        "coinbase-controlled-spot-child-cancel-v15r1-20260713.plan.json"
    ),
    "marker_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.authority.json"
    ),
    "ledger_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.placements.jsonl"
    ),
    "cancel_ledger_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.cancel-command.jsonl"
    ),
    "backend_claim_log_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.backend-claims.jsonl"
    ),
    "handoff_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.handoff.json"
    ),
    "audit_path": str(R1_STATE_DIR / "audit.jsonl"),
    "sentinel_path": str(R1_STATE_DIR / "sdk-boundary-sentinel.json"),
    "parent_authority_loss_path": str(R1_STATE_DIR / "parent-authority-loss.json"),
}
R1_EXPECTED_HASHES: dict[str, str] = {
    **R1_ARTIFACT_PATHS,
    "plan_bytes_sha256": "f9f79ba28444de532352200afa0703e01838e7b674cd849e287735d17dac7c08",
    "marker_bytes_sha256": "ed9ab94189b2eb0e2b665a0c0784b01b2b948cee12d8fb8af8d8a03a6a238511",
    "ledger_bytes_sha256": "474f931ce453a57c1b2a0a741d2a0207d7929684e9e9bf33f25562828888770c",
    "cancel_ledger_bytes_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "backend_claim_log_bytes_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "audit_bytes_sha256": "cbc8ff26e0fa23c12d51f2094543e20807181e6d5c5192ca89044c113496a1e5",
    "sentinel_bytes_sha256": "6a7888eeb50b8fb2d656c9f0068f7e7fc6e1753b114cf7e80094c78a2ca80e0f",
    "parent_authority_loss_bytes_sha256": "b6af47512d0261259740dc6077356580b82049f7d4dcd1d5301f8df627e1fc15",
}
V15R2_PLAN_FIELDS = frozenset(
    {
        "schema_version", "authority_kind", "approval_id", "batch_id",
        "created_at", "expires_at", "backend_commit", "frontend_commit",
        "runner_sha256", "v15r1_recovery_binding",
        "local_hidden_child_binding", "profile_label", "portfolio_id",
        "product_id", "placement_attempt_count", "placement_attempt_schedule",
        "root_placement_maximum", "child_placement_maximum",
        "cancel_command_maximum", "root_placement_authorized",
        "root_reference_cap_usdc", "root_actual_reference_notional_usdc",
        "child_submitted_cap_usdc", "slice_reference_cap_usdc",
        "planned_reference_notional_usdc",
        "conservative_reference_notional_usdc", "root_evidence", "child",
        "child_reveal_operator_intent", "child_cancel_operator_intent",
        "cancel_command", "retry_authorized", "substitution_authorized",
        "later_child_authorized", "browser_derives_child_identity",
        "exchange_order_id_evidence_only", "plan_sha256",
    }
)


def _require(condition: bool, blocker: str) -> None:
    if not condition:
        raise ProofFailure(blocker)


def _canonical_json_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path, *, allow_public_read: bool = False) -> str:
    _require_safe_regular_file(
        path, "v15r1_artifact", allow_public_read=allow_public_read
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_safe_regular_file(
    path: Path, blocker: str, *, allow_public_read: bool = False
) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProofFailure(f"{blocker}_missing") from exc
    _require(
        stat.S_ISREG(metadata.st_mode)
        and not path.is_symlink()
        and metadata.st_uid == os.getuid()
        and (
            metadata.st_mode & 0o077 == 0
            or (allow_public_read and metadata.st_mode & 0o133 == 0)
        ),
        f"{blocker}_unsafe",
    )


def _require_owner_only_regular_file(path: Path, blocker: str) -> None:
    _require_safe_regular_file(path, blocker)


def _json(path: Path, blocker: str) -> dict[str, Any]:
    _require_owner_only_regular_file(path, blocker)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofFailure(f"{blocker}_malformed") from exc
    _require(isinstance(value, dict), f"{blocker}_not_object")
    return dict(value)


def _jsonl(
    path: Path, blocker: str, *, allow_public_read: bool = False
) -> list[dict[str, Any]]:
    _require_safe_regular_file(path, blocker, allow_public_read=allow_public_read)
    raw = path.read_bytes()
    _require(not raw or raw.endswith(b"\n"), f"{blocker}_truncated")
    result: list[dict[str, Any]] = []
    try:
        for line in raw.decode("utf-8").splitlines():
            value = json.loads(line)
            _require(isinstance(value, dict), f"{blocker}_row_invalid")
            result.append(dict(value))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofFailure(f"{blocker}_malformed") from exc
    return result


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def backend_commit() -> str:
    return _git("rev-parse", "HEAD")


def frontend_commit() -> str:
    return _git("rev-parse", "HEAD", cwd=FRONTEND_ROOT)


def runner_sha256() -> str:
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def plan_hash(plan: Mapping[str, Any]) -> str:
    return base.plan_hash(plan)


def _deterministic_id(batch_id: str, purpose: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"coinbase://selected-child-cancel-v15r2/{batch_id}/{purpose}"))


def load_v15r1_recovery_binding() -> dict[str, Any]:
    """Validate the stopped R1 boundary without mutating any R1 artifact."""

    paths = {key: Path(value) for key, value in R1_ARTIFACT_PATHS.items()}
    hash_keys = {
        "plan_path": "plan_bytes_sha256",
        "marker_path": "marker_bytes_sha256",
        "ledger_path": "ledger_bytes_sha256",
        "cancel_ledger_path": "cancel_ledger_bytes_sha256",
        "backend_claim_log_path": "backend_claim_log_bytes_sha256",
        "audit_path": "audit_bytes_sha256",
        "sentinel_path": "sentinel_bytes_sha256",
        "parent_authority_loss_path": "parent_authority_loss_bytes_sha256",
    }
    _require(
        all(
            _file_sha256(
                paths[path_key], allow_public_read=path_key == "audit_path"
            )
            == R1_EXPECTED_HASHES[hash_key]
            for path_key, hash_key in hash_keys.items()
        ),
        "v15r1_artifact_hash_mismatch",
    )
    _require(not os.path.lexists(paths["handoff_path"]), "v15r1_handoff_present")
    r1_plan = _json(paths["plan_path"], "v15r1_plan")
    marker = _json(paths["marker_path"], "v15r1_marker")
    ledger = _jsonl(paths["ledger_path"], "v15r1_ledger")
    cancel_rows = _jsonl(paths["cancel_ledger_path"], "v15r1_cancel_ledger")
    backend_rows = _jsonl(paths["backend_claim_log_path"], "v15r1_backend_claim_log")
    sentinel = _json(paths["sentinel_path"], "v15r1_sentinel")
    parent_loss = _json(paths["parent_authority_loss_path"], "v15r1_parent_loss")
    audit_rows = _jsonl(
        paths["audit_path"], "v15r1_audit", allow_public_read=True
    )

    _require(
        r1_plan.get("plan_sha256") == R1_PLAN_SHA256
        and r1_plan.get("batch_id") == R1_BATCH_ID
        and r1_plan.get("portfolio_id") == TEST_PORTFOLIO_ID
        and r1_plan.get("product_id") == PRODUCT_ID
        and dict(r1_plan.get("root") or {}).get("client_order_id")
        == R1_ROOT_CLIENT_ORDER_ID
        and dict(r1_plan.get("child") or {}).get("client_order_id")
        == R1_CHILD_CLIENT_ORDER_ID
        and Decimal(str(r1_plan.get("root_reference_notional_usdc")))
        == R1_ROOT_REFERENCE_NOTIONAL,
        "v15r1_plan_scope_mismatch",
    )
    _require(
        marker.get("plan_sha256") == R1_PLAN_SHA256
        and marker.get("batch_id") == R1_BATCH_ID
        and marker.get("root_client_order_id") == R1_ROOT_CLIENT_ORDER_ID
        and marker.get("child_client_order_id") == R1_CHILD_CLIENT_ORDER_ID
        and len(ledger) == 2
        and [row.get("attempt_kind") for row in ledger] == ["root", "child"]
        and [row.get("sequence") for row in ledger] == [1, 2]
        and all(row.get("plan_sha256") == R1_PLAN_SHA256 for row in ledger),
        "v15r1_marker_or_two_row_ledger_mismatch",
    )
    root_tuple = dict(ledger[0].get("exact_order_tuple") or {})
    child_tuple = dict(ledger[1].get("exact_order_tuple") or {})
    _require(
        root_tuple.get("client_order_id") == R1_ROOT_CLIENT_ORDER_ID
        and Decimal(str(root_tuple.get("base_size"))) == R1_ROOT_FILLED_SIZE
        and child_tuple.get("client_order_id") == R1_CHILD_CLIENT_ORDER_ID
        and child_tuple.get("root_client_order_id") == R1_ROOT_CLIENT_ORDER_ID
        and Decimal(str(child_tuple.get("base_size"))) == R1_ROOT_FILLED_SIZE
        and Decimal(str(child_tuple.get("base_size")))
        * Decimal(str(child_tuple.get("limit_price")))
        == R1_CHILD_CONSUMED_REFERENCE_NOTIONAL,
        "v15r1_consumed_tuples_mismatch",
    )
    _require(
        sentinel.get("phase") == "runtime_exited"
        and sentinel.get("installed") is True
        and sentinel.get("wrapper_identity_proven") is True
        and sentinel.get("root_create_order_call_count") == 1
        and sentinel.get("child_place_limit_order_call_count") == 0
        and sentinel.get("root_sdk_inflight") is False
        and sentinel.get("child_sdk_inflight") is False
        and sentinel.get("denied_call_count") == 0
        and sentinel.get("critical_failure") is False
        and sentinel.get("error") is None,
        "v15r1_runtime_exit_sentinel_mismatch",
    )
    _require(
        parent_loss.get("plan_sha256") == R1_PLAN_SHA256
        and parent_loss.get("status") == "v15_parent_authority_lost_reconciliation_only"
        and parent_loss.get("authoritative_active_read_stable") is True
        and parent_loss.get("authoritative_active_orders") == []
        and parent_loss.get("new_sdk_placements_denied") is True
        and parent_loss.get("new_cancel_command_authorized") is False
        and parent_loss.get("root_create_order_call_count") == 1
        and parent_loss.get("child_place_limit_order_call_count") == 0,
        "v15r1_parent_loss_boundary_mismatch",
    )
    proof_rows = [row for row in audit_rows if row.get("key") == R1_FILL_PROOF_KEY]
    _require(len(proof_rows) == 1, "v15r1_direct_fill_proof_key_mismatch")
    proof_row = proof_rows[0]
    expected_proof_hash = R1_EXPECTED_HASHES.get(
        "direct_fill_proof_canonical_sha256", R1_FILL_PROOF_CANONICAL_SHA256
    )
    _require(
        _canonical_json_sha256(proof_row) == expected_proof_hash,
        "v15r1_direct_fill_proof_hash_mismatch",
    )
    proof = dict(proof_row.get("record") or {})
    _require(
        proof_row.get("collection") == "spot_fill_readback_proofs"
        and proof.get("type") == "admin_spot_order_fill_readback"
        and proof.get("route") == "/api/v1/orders/{client_order_id}/fill-readback"
        and proof.get("client_order_id") == R1_ROOT_CLIENT_ORDER_ID
        and proof.get("exchange_order_id") == R1_ROOT_EXCHANGE_ORDER_ID
        and str(proof.get("order_status") or "").upper() == "FILLED"
        and str(proof.get("fill_read_status") or "").lower() == "filled"
        and Decimal(str(proof.get("executed_notional_usdc")))
        == R1_ROOT_FILLED_VALUE
        and proof.get("fill_count") == 1
        and proof.get("fill_order_id_matches_exchange_order_id") is True
        and proof.get("fill_product_id_matches_order") is True
        and proof.get("proof_recorded") is True
        and proof.get("read_only") is True
        and proof.get("live_coinbase_orders_ran") is False,
        "v15r1_direct_fill_proof_semantics_mismatch",
    )
    _require(not cancel_rows and not backend_rows, "v15r1_cancel_or_claim_log_not_empty")
    return {
        "r1_plan_sha256": R1_PLAN_SHA256,
        "r1_batch_id": R1_BATCH_ID,
        "r1_root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
        "r1_child_client_order_id": R1_CHILD_CLIENT_ORDER_ID,
        "r1_root_exchange_order_id": R1_ROOT_EXCHANGE_ORDER_ID,
        "r1_attempt_count": 2,
        "r1_root_sdk_call_count": 1,
        "r1_child_sdk_call_count": 0,
        "root_filled_size": base.decimal_text(R1_ROOT_FILLED_SIZE),
        "root_filled_value": base.decimal_text(R1_ROOT_FILLED_VALUE),
        "root_fill_count": 1,
        "fill_pagination_complete": True,
        "fill_pagination_proof_source": "sealed_admin_fill_readback_proof_contract",
        "active_spot_order_count": 0,
        "handoff_absent": True,
        "cancel_ledgers_empty": True,
        "source_paths": dict(R1_ARTIFACT_PATHS),
        "source_hashes": {
            key: value for key, value in R1_EXPECTED_HASHES.items() if key.endswith("sha256")
        },
        "direct_fill_proof_key": R1_FILL_PROOF_KEY,
        "direct_fill_proof_canonical_sha256": expected_proof_hash,
    }


def validate_local_hidden_child_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    binding = dict(value)
    _require(
        binding.get("root_client_order_id") == R1_ROOT_CLIENT_ORDER_ID
        and binding.get("child_client_order_id") == R1_CHILD_CLIENT_ORDER_ID
        and str(binding.get("root_status") or "").upper() == "FILLED"
        and binding.get("root_exchange_order_id") == R1_ROOT_EXCHANGE_ORDER_ID
        and str(binding.get("child_parent_status") or "").upper()
        in {"PENDING", "HIDDEN"}
        and str(binding.get("child_stealth_status") or "").upper()
        in {"PENDING", "HIDDEN"}
        and Decimal(str(binding.get("child_size") or "0")) == R1_ROOT_FILLED_SIZE
        and Decimal(str(binding.get("revealed_size") or "0")) == 0
        and Decimal(str(binding.get("executed_size") or "0")) == 0
        and binding.get("revealed_orders") == []
        and not str(binding.get("child_exchange_order_id") or "").strip()
        and not str(binding.get("active_placement_client_order_id") or "").strip()
        and not str(binding.get("active_exchange_order_id") or "").strip()
        and binding.get("preexisting_controlled_preparation_present") is False
        and bool(str(binding.get("root_correlation_id") or "").strip())
        and bool(str(binding.get("root_audit_id") or "").strip())
        and binding.get("child_correlation_id") == binding.get("root_correlation_id")
        and binding.get("child_audit_id") == binding.get("root_audit_id")
        and binding.get("direct_child_client_order_ids") == []
        and binding.get("nested_child_client_order_ids") == [],
        "v15r2_local_hidden_child_mismatch",
    )
    return binding


def read_local_hidden_child_binding() -> dict[str, Any]:
    """Read the exact stopped child from PostgreSQL without mutation."""

    connection = psycopg2.connect(
        host=os.environ.get("COINBASE_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("COINBASE_DB_PORT", "5432")),
        dbname=os.environ.get("COINBASE_DB_NAME", "postgres"),
        user=os.environ.get("COINBASE_DB_USER", "postgres"),
        password=os.environ.get("COINBASE_DB_PASSWORD", "postgres"),
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, exchange_order_id, correlation_id, audit_id FROM order_parent WHERE client_order_id=%s",
                (R1_ROOT_CLIENT_ORDER_ID,),
            )
            root_row = cursor.fetchone()
            cursor.execute(
                "SELECT status, size, exchange_order_id, correlation_id, audit_id FROM order_parent WHERE client_order_id=%s AND parent_order_id=%s",
                (R1_CHILD_CLIENT_ORDER_ID, R1_ROOT_CLIENT_ORDER_ID),
            )
            child_row = cursor.fetchone()
            cursor.execute(
                """SELECT status, revealed_size, executed_size, revealed_orders,
                          anchor_repricing_state_json
                     FROM stealth_orders
                    WHERE stealth_order_id=%s AND parent_order_id=%s""",
                (R1_CHILD_CLIENT_ORDER_ID, R1_ROOT_CLIENT_ORDER_ID),
            )
            stealth_row = cursor.fetchone()
            cursor.execute(
                "SELECT client_order_id FROM order_parent WHERE parent_order_id=%s AND client_order_id<>%s ORDER BY client_order_id",
                (R1_ROOT_CLIENT_ORDER_ID, R1_CHILD_CLIENT_ORDER_ID),
            )
            direct_children = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT client_order_id
                     FROM order_parent
                    WHERE parent_order_id=%s
                    ORDER BY client_order_id""",
                (R1_CHILD_CLIENT_ORDER_ID,),
            )
            nested_children = [str(row[0]) for row in cursor.fetchall()]
        _require(root_row is not None and child_row is not None and stealth_row is not None,
                 "v15r2_local_hidden_child_row_missing")
        anchor = dict(stealth_row[4] or {})
        return validate_local_hidden_child_binding(
            {
                "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
                "root_status": root_row[0],
                "root_exchange_order_id": root_row[1],
                "root_correlation_id": root_row[2],
                "root_audit_id": root_row[3],
                "child_client_order_id": R1_CHILD_CLIENT_ORDER_ID,
                "child_parent_status": child_row[0],
                "child_size": base.decimal_text(Decimal(str(child_row[1]))),
                "child_exchange_order_id": child_row[2],
                "child_correlation_id": child_row[3],
                "child_audit_id": child_row[4],
                "child_stealth_status": stealth_row[0],
                "revealed_size": base.decimal_text(Decimal(str(stealth_row[1] or 0))),
                "executed_size": base.decimal_text(Decimal(str(stealth_row[2] or 0))),
                "revealed_orders": list(stealth_row[3] or []),
                "active_placement_client_order_id": anchor.get("active_placement_client_order_id"),
                "active_exchange_order_id": anchor.get("active_exchange_order_id"),
                "preexisting_controlled_preparation_present": bool(
                    anchor.get("controlled_admin_first_child_reveal_preparation")
                ),
                "direct_child_client_order_ids": direct_children,
                "nested_child_client_order_ids": nested_children,
            }
        )
    finally:
        connection.close()


def build_v15r2_plan(
    r1_binding: Mapping[str, Any],
    *,
    local_hidden_child: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    created_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    approval = approval_id or f"controlled-child-cancel-v15r2-{uuid4()}"
    _require(approval.startswith("controlled-child-cancel-v15r2-"),
             "v15r2_approval_namespace_invalid")
    UUID(approval.removeprefix("controlled-child-cancel-v15r2-"))
    exact_runner = runner_sha256()
    commit = backend_commit()
    batch_id = str(uuid5(NAMESPACE_URL, f"coinbase://selected-child-cancel-v15r2/{commit}/{exact_runner}/{approval}"))
    local_binding = validate_local_hidden_child_binding(
        local_hidden_child
        or {
            "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
            "root_status": "FILLED",
            "root_exchange_order_id": R1_ROOT_EXCHANGE_ORDER_ID,
            "root_correlation_id": "sealed-root-correlation",
            "root_audit_id": "sealed-root-audit",
            "child_client_order_id": R1_CHILD_CLIENT_ORDER_ID,
            "child_parent_status": "PENDING",
            "child_size": base.decimal_text(R1_ROOT_FILLED_SIZE),
            "child_exchange_order_id": None,
            "child_correlation_id": "sealed-root-correlation",
            "child_audit_id": "sealed-root-audit",
            "child_stealth_status": "HIDDEN",
            "revealed_size": "0",
            "executed_size": "0",
            "revealed_orders": [],
            "active_placement_client_order_id": None,
            "active_exchange_order_id": None,
            "preexisting_controlled_preparation_present": False,
            "direct_child_client_order_ids": [],
            "nested_child_client_order_ids": [],
        }
    )
    planned_total = R1_ROOT_FILLED_VALUE + CHILD_SUBMITTED_CAP
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "authority_kind": AUTHORITY_KIND,
        "approval_id": approval,
        "batch_id": batch_id,
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + PLAN_TTL).isoformat(),
        "backend_commit": commit,
        "frontend_commit": frontend_commit(),
        "runner_sha256": exact_runner,
        "v15r1_recovery_binding": dict(r1_binding),
        "local_hidden_child_binding": local_binding,
        "profile_label": PROFILE_LABEL,
        "portfolio_id": TEST_PORTFOLIO_ID,
        "product_id": PRODUCT_ID,
        "placement_attempt_count": 1,
        "placement_attempt_schedule": ["child"],
        "root_placement_maximum": 0,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "root_placement_authorized": False,
        "root_reference_cap_usdc": base.decimal_text(ROOT_REFERENCE_CAP),
        "root_actual_reference_notional_usdc": base.decimal_text(R1_ROOT_FILLED_VALUE),
        "child_submitted_cap_usdc": base.decimal_text(CHILD_SUBMITTED_CAP),
        "slice_reference_cap_usdc": base.decimal_text(SLICE_REFERENCE_CAP),
        "planned_reference_notional_usdc": base.decimal_text(planned_total),
        "conservative_reference_notional_usdc": base.decimal_text(CONSERVATIVE_REFERENCE_NOTIONAL),
        "root_evidence": {
            "client_order_id": R1_ROOT_CLIENT_ORDER_ID,
            "exchange_order_id": R1_ROOT_EXCHANGE_ORDER_ID,
            "status": "FILLED",
            "filled_size": base.decimal_text(R1_ROOT_FILLED_SIZE),
            "filled_value": base.decimal_text(R1_ROOT_FILLED_VALUE),
            "placement_authorized": False,
        },
        "child": {
            "client_order_id": R1_CHILD_CLIENT_ORDER_ID,
            "parent_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
            "approval_snapshot_id": _deterministic_id(batch_id, "child-reveal-approval"),
            "cap_guard_decision_id": _deterministic_id(batch_id, "child-reveal-cap"),
            "reconciliation_plan_id": _deterministic_id(batch_id, "child-reveal-reconciliation"),
            "order_policy": {
                "product_id": PRODUCT_ID,
                "side": "SELL",
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": False,
                "base_size": base.decimal_text(R1_ROOT_FILLED_SIZE),
                "minimum_fresh_bid_ratio": base.decimal_text(base.CHILD_MINIMUM_BID_RATIO),
                "target_fresh_bid_ratio": base.decimal_text(base.CHILD_TARGET_BID_RATIO),
                "strict_max_notional_usdc": base.decimal_text(CHILD_SUBMITTED_CAP),
            },
        },
        "child_reveal_operator_intent": CHILD_REVEAL_OPERATOR_INTENT,
        "child_cancel_operator_intent": CHILD_CANCEL_OPERATOR_INTENT,
        "cancel_command": {
            "route": "/api/v1/orders/{root_client_order_id}/fill-follow-up/child-cancel",
            "method": "POST",
            "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
            "child_client_order_id": R1_CHILD_CLIENT_ORDER_ID,
            "identity_key": "client_order_id",
            "identity_value": R1_ROOT_CLIENT_ORDER_ID,
            "operator_intent": CHILD_CANCEL_OPERATOR_INTENT,
            "idempotency_key": _deterministic_id(batch_id, "child-cancel-idempotency"),
            "correlation_id": _deterministic_id(batch_id, "child-cancel-correlation"),
            "claim_id": _deterministic_id(batch_id, "child-cancel-claim"),
            "approval_snapshot_id": _deterministic_id(batch_id, "child-cancel-approval"),
            "admission_audit_id_source": "route_bound_runtime_proof",
            "cap_guard_decision_id": _deterministic_id(batch_id, "child-cancel-cap"),
            "reconciliation_plan_id": _deterministic_id(batch_id, "child-cancel-reconciliation"),
            "controlled_plan_sha256_source": "plan_sha256",
            "semantic_retry_policy": "same_idempotency_key_only",
        },
        "retry_authorized": False,
        "substitution_authorized": False,
        "later_child_authorized": False,
        "browser_derives_child_identity": False,
        "exchange_order_id_evidence_only": True,
    }
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def validate_v15r2_plan(
    plan: Mapping[str, Any], *, expected_hash: str, now: datetime | None = None
) -> None:
    _require(set(plan) == V15R2_PLAN_FIELDS, "v15r2_plan_fields_mismatch")
    computed = plan_hash(plan)
    _require(
        secrets.compare_digest(str(plan.get("plan_sha256") or ""), computed)
        and secrets.compare_digest(expected_hash, computed),
        "v15r2_plan_hash_mismatch",
    )
    _require(
        plan.get("schema_version") == PLAN_SCHEMA_VERSION
        and plan.get("authority_kind") == AUTHORITY_KIND
        and plan.get("profile_label") == PROFILE_LABEL
        and plan.get("portfolio_id") == TEST_PORTFOLIO_ID
        and plan.get("product_id") == PRODUCT_ID,
        "v15r2_plan_authority_mismatch",
    )
    _require(
        plan.get("backend_commit") == backend_commit()
        and plan.get("frontend_commit") == frontend_commit()
        and plan.get("runner_sha256") == runner_sha256(),
        "v15r2_plan_code_binding_mismatch",
    )
    _require(
        plan.get("placement_attempt_count") == 1
        and plan.get("placement_attempt_schedule") == ["child"]
        and plan.get("root_placement_maximum") == 0
        and plan.get("child_placement_maximum") == 1
        and plan.get("cancel_command_maximum") == 1
        and plan.get("root_placement_authorized") is False,
        "v15r2_exact_scope_mismatch",
    )
    _require(
        Decimal(str(plan.get("root_reference_cap_usdc"))) == ROOT_REFERENCE_CAP
        and Decimal(str(plan.get("root_actual_reference_notional_usdc"))) == R1_ROOT_FILLED_VALUE
        and Decimal(str(plan.get("child_submitted_cap_usdc"))) == CHILD_SUBMITTED_CAP
        and Decimal(str(plan.get("slice_reference_cap_usdc"))) == SLICE_REFERENCE_CAP
        and Decimal(str(plan.get("planned_reference_notional_usdc")))
        == R1_ROOT_FILLED_VALUE + CHILD_SUBMITTED_CAP
        and Decimal(str(plan.get("conservative_reference_notional_usdc")))
        == CONSERVATIVE_REFERENCE_NOTIONAL
        and CONSERVATIVE_REFERENCE_NOTIONAL < SLICE_REFERENCE_CAP,
        "v15r2_numeric_scope_mismatch",
    )
    root = dict(plan.get("root_evidence") or {})
    child = dict(plan.get("child") or {})
    cancel = dict(plan.get("cancel_command") or {})
    expected_child_policy = {
        "product_id": PRODUCT_ID,
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "post_only": False,
        "base_size": base.decimal_text(R1_ROOT_FILLED_SIZE),
        "minimum_fresh_bid_ratio": base.decimal_text(
            base.CHILD_MINIMUM_BID_RATIO
        ),
        "target_fresh_bid_ratio": base.decimal_text(base.CHILD_TARGET_BID_RATIO),
        "strict_max_notional_usdc": base.decimal_text(CHILD_SUBMITTED_CAP),
    }
    _require(
        "order" not in root
        and root.get("placement_authorized") is False
        and root.get("client_order_id") == R1_ROOT_CLIENT_ORDER_ID
        and root.get("exchange_order_id") == R1_ROOT_EXCHANGE_ORDER_ID
        and root.get("status") == "FILLED"
        and child.get("client_order_id") == R1_CHILD_CLIENT_ORDER_ID
        and child.get("parent_client_order_id") == R1_ROOT_CLIENT_ORDER_ID
        and child.get("order_policy") == expected_child_policy
        and child.get("approval_snapshot_id")
        == _deterministic_id(str(plan["batch_id"]), "child-reveal-approval")
        and child.get("cap_guard_decision_id")
        == _deterministic_id(str(plan["batch_id"]), "child-reveal-cap")
        and child.get("reconciliation_plan_id")
        == _deterministic_id(
            str(plan["batch_id"]), "child-reveal-reconciliation"
        )
        and cancel.get("identity_key") == "client_order_id"
        and cancel.get("identity_value") == R1_ROOT_CLIENT_ORDER_ID
        and cancel.get("child_client_order_id") == R1_CHILD_CLIENT_ORDER_ID,
        "v15r2_identity_scope_mismatch",
    )
    _require(
        plan.get("child_reveal_operator_intent")
        == CHILD_REVEAL_OPERATOR_INTENT
        and plan.get("child_cancel_operator_intent")
        == CHILD_CANCEL_OPERATOR_INTENT
        and cancel.get("operator_intent") == CHILD_CANCEL_OPERATOR_INTENT
        and cancel.get("idempotency_key")
        == _deterministic_id(str(plan["batch_id"]), "child-cancel-idempotency")
        and cancel.get("correlation_id")
        == _deterministic_id(str(plan["batch_id"]), "child-cancel-correlation")
        and cancel.get("claim_id")
        == _deterministic_id(str(plan["batch_id"]), "child-cancel-claim")
        and cancel.get("approval_snapshot_id")
        == _deterministic_id(str(plan["batch_id"]), "child-cancel-approval")
        and cancel.get("cap_guard_decision_id")
        == _deterministic_id(str(plan["batch_id"]), "child-cancel-cap")
        and cancel.get("reconciliation_plan_id")
        == _deterministic_id(
            str(plan["batch_id"]), "child-cancel-reconciliation"
        ),
        "v15r2_evidence_namespace_mismatch",
    )
    _require(
        plan.get("retry_authorized") is False
        and plan.get("substitution_authorized") is False
        and plan.get("later_child_authorized") is False
        and plan.get("browser_derives_child_identity") is False
        and plan.get("exchange_order_id_evidence_only") is True,
        "v15r2_broadening_boundary_mismatch",
    )
    _require(
        plan.get("v15r1_recovery_binding") == load_v15r1_recovery_binding()
        and validate_local_hidden_child_binding(
            dict(plan.get("local_hidden_child_binding") or {})
        ) == plan.get("local_hidden_child_binding"),
        "v15r2_recovery_binding_mismatch",
    )
    created = datetime.fromisoformat(str(plan.get("created_at") or ""))
    expires = datetime.fromisoformat(str(plan.get("expires_at") or ""))
    current = now or datetime.now(timezone.utc)
    _require(
        created.tzinfo is not None
        and expires.tzinfo is not None
        and expires - created == PLAN_TTL
        and created <= current < expires,
        "v15r2_plan_expired_or_ttl_invalid",
    )


def build_execution_child_order_tuple(
    plan: Mapping[str, Any], *, fresh_market: Mapping[str, Any], price_increment: Decimal
) -> dict[str, Any]:
    child = dict(plan["child"])
    bid = Decimal(str(fresh_market.get("best_bid") or "0"))
    price = (
        (bid * base.CHILD_TARGET_BID_RATIO / price_increment).to_integral_value(
            rounding=ROUND_CEILING
        )
        * price_increment
    )
    size = R1_ROOT_FILLED_SIZE
    notional = size * price
    _require(bid > 0 and price_increment > 0, "v15r2_child_market_invalid")
    _require(
        price % price_increment == 0
        and price >= bid * base.CHILD_MINIMUM_BID_RATIO
        and Decimal("0") < notional < CHILD_SUBMITTED_CAP
        and R1_ROOT_FILLED_VALUE + notional < SLICE_REFERENCE_CAP,
        "v15r2_child_tuple_cap_or_price_mismatch",
    )
    return {
        "batch_id": plan["batch_id"],
        "batch_slot": 1,
        "approval_snapshot_id": child["approval_snapshot_id"],
        "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
        "client_order_id": R1_CHILD_CLIENT_ORDER_ID,
        "product_id": PRODUCT_ID,
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "base_size": base.decimal_text(size),
        "limit_price": base.decimal_text(price),
        "post_only": False,
        "reference_bid": base.decimal_text(bid),
        "market_observed_at": str(fresh_market.get("observed_at") or ""),
        "minimum_bid_ratio": base.decimal_text(base.CHILD_MINIMUM_BID_RATIO),
        "target_bid_ratio": base.decimal_text(base.CHILD_TARGET_BID_RATIO),
        "price_increment": base.decimal_text(price_increment),
        "strict_max_notional_usdc": base.decimal_text(CHILD_SUBMITTED_CAP),
    }


def consume_v15r2_child_attempt(
    ledger_path: Path,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    exact_order_tuple: Mapping[str, Any],
    consumed_at: str | None = None,
    process_id: int | None = None,
    attempt_kind: str = "child",
) -> dict[str, Any]:
    _require(attempt_kind == "child", "v15r2_attempt_kind_not_child")
    _require(plan.get("plan_sha256") == plan_sha256, "v15r2_attempt_plan_mismatch")
    tuple_record = dict(exact_order_tuple)
    _require(
        tuple_record.get("client_order_id") == R1_CHILD_CLIENT_ORDER_ID
        and tuple_record.get("root_client_order_id") == R1_ROOT_CLIENT_ORDER_ID
        and tuple_record.get("product_id") == PRODUCT_ID
        and tuple_record.get("side") == "SELL"
        and Decimal(str(tuple_record.get("base_size") or "0")) == R1_ROOT_FILLED_SIZE
        and Decimal(str(tuple_record.get("base_size")))
        * Decimal(str(tuple_record.get("limit_price"))) < CHILD_SUBMITTED_CAP,
        "v15r2_child_attempt_tuple_mismatch",
    )
    rows = _jsonl(ledger_path, "v15r2_placement_ledger")
    _require(not rows, "v15r2_child_attempt_already_consumed")
    row = {
        "schema_version": "1",
        "sequence": 1,
        "attempt_kind": "child",
        "batch_id": plan["batch_id"],
        "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
        "client_order_id": R1_CHILD_CLIENT_ORDER_ID,
        "plan_sha256": plan_sha256,
        "exact_order_tuple": tuple_record,
        "exact_order_tuple_sha256": _canonical_json_sha256(tuple_record),
        "consumed_at": consumed_at or datetime.now(timezone.utc).isoformat(),
        "process_id": process_id or os.getpid(),
    }
    with ledger_path.open("ab") as handle:
        handle.write((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return row


def _exclusive_empty(path: Path, blocker: str) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise ProofFailure(blocker) from exc
    os.close(descriptor)


def authorize_v15r2_execution(
    plan_path: Path,
    *,
    expected_hash: str,
    now: datetime | None = None,
    marker_path: Path = MARKER_PATH,
    placement_ledger_path: Path = PLACEMENT_LEDGER_PATH,
    cancel_ledger_path: Path = CANCEL_LEDGER_PATH,
    backend_claim_log_path: Path = BACKEND_CLAIM_LOG_PATH,
    handoff_path: Path = HANDOFF_PATH,
) -> dict[str, Any]:
    plan = _json(plan_path, "v15r2_execution_plan")
    validate_v15r2_plan(plan, expected_hash=expected_hash, now=now)
    _require(
        all(not os.path.lexists(path) for path in (
            marker_path, placement_ledger_path, cancel_ledger_path,
            backend_claim_log_path, handoff_path,
        )),
        "v15r2_execution_authority_already_consumed",
    )
    authority = {
        "schema_version": "1",
        "authority": AUTHORITY_KIND,
        "approval_id": plan["approval_id"],
        "batch_id": plan["batch_id"],
        "plan_file": str(plan_path),
        "plan_sha256": expected_hash,
        "backend_commit": plan["backend_commit"],
        "frontend_commit": plan["frontend_commit"],
        "runner_sha256": plan["runner_sha256"],
        "profile_label": PROFILE_LABEL,
        "portfolio_id": TEST_PORTFOLIO_ID,
        "product_id": PRODUCT_ID,
        "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": R1_CHILD_CLIENT_ORDER_ID,
        "placement_attempt_maximum": 1,
        "root_placement_maximum": 0,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "placement_ledger_path": str(placement_ledger_path),
        "cancel_ledger_path": str(cancel_ledger_path),
        "backend_claim_log_path": str(backend_claim_log_path),
        "handoff_path": str(handoff_path),
        "registered_at": (now or datetime.now(timezone.utc)).isoformat(),
        "process_id": os.getpid(),
    }
    base._write_owner_only_exclusive_json(
        marker_path, authority, exists_blocker="v15r2_marker_already_exists"
    )
    for path, blocker in (
        (placement_ledger_path, "v15r2_placement_ledger_create_failed"),
        (cancel_ledger_path, "v15r2_cancel_ledger_create_failed"),
        (backend_claim_log_path, "v15r2_backend_claim_log_create_failed"),
    ):
        _exclusive_empty(path, blocker)
    return authority


def build_v15r2_cancel_admission_context(
    plan: Mapping[str, Any], *, plan_sha256: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    from api.v1.routes.orders import _idempotency_payload_hash
    from application.admin_api.models import AdminApiActor

    cancel = dict(plan["cancel_command"])
    body = {
        "reason": "cancel_active_deterministic_first_child",
        "manual_live_acknowledgement": True,
        "controlled_plan_sha256": plan_sha256,
    }
    endpoint = f"POST /api/v1/orders/{R1_ROOT_CLIENT_ORDER_ID}/fill-follow-up/child-cancel"
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=AdminApiActor(actor_id=base.ACTOR_ID, roles=[base.COMMAND_ROLE]),
        operator_intent=cancel["operator_intent"],
        body=body,
        path_params={"root_client_order_id": R1_ROOT_CLIENT_ORDER_ID},
    )
    return ({
        "route": cancel["route"], "method": "POST", "module_id": "spot_operations",
        "identity_key": "client_order_id", "identity_value": R1_ROOT_CLIENT_ORDER_ID,
        "action_class": "live_exchange_cancel", "required_permission": "order:cancel",
        "service_method": "cancel_order_fill_follow_up_child_by_root_client_order_id",
        "actor_id": base.ACTOR_ID, "operator_intent": cancel["operator_intent"],
        "command_idempotency_key": cancel["idempotency_key"], "payload_hash": payload_hash,
    }, body)


def write_v15r2_cancel_proof_handoff(
    handoff_path: Path,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    context: Mapping[str, Any],
    proofs: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    expected_context, _ = build_v15r2_cancel_admission_context(plan, plan_sha256=plan_sha256)
    cancel = dict(plan["cancel_command"])
    _require(dict(context) == expected_context, "v15r2_handoff_context_mismatch")
    _require(
        proofs.get("approval_id") == cancel["approval_snapshot_id"]
        and proofs.get("cap_guard_decision_id") == cancel["cap_guard_decision_id"]
        and proofs.get("reconciliation_plan_id") == cancel["reconciliation_plan_id"]
        and bool(proofs.get("admission_audit_id")),
        "v15r2_handoff_proof_mismatch",
    )
    handoff = {
        "schema_version": "1", "authority": AUTHORITY_KIND,
        "plan_sha256": plan_sha256, "batch_id": plan["batch_id"],
        "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": R1_CHILD_CLIENT_ORDER_ID,
        "approval_snapshot_id": proofs["approval_id"],
        "admission_audit_id": proofs["admission_audit_id"],
        "cap_guard_decision_id": proofs["cap_guard_decision_id"],
        "reconciliation_plan_id": proofs["reconciliation_plan_id"],
        **dict(context),
        "idempotency_key": cancel["idempotency_key"],
        "correlation_id": cancel["correlation_id"],
        "recorded_at": recorded_at,
    }
    base._write_owner_only_exclusive_json(
        handoff_path, handoff, exists_blocker="v15r2_handoff_already_exists"
    )
    return handoff


def prove_v15r2_child_exchange_identity_absent(rest_client: Any) -> dict[str, Any]:
    """Prove the recovered child ID has never reached the exchange."""

    catalog, pagination = base.read_failed_v6_v7_order_catalog(rest_client)
    matching = [
        dict(row)
        for row in catalog
        if str(row.get("client_order_id") or "") == R1_CHILD_CLIENT_ORDER_ID
    ]
    _require(
        pagination.get("authoritative") is True
        and pagination.get("pagination_complete") is True
        and not matching,
        "v15r2_child_exchange_identity_absence_unproven",
    )
    return {"matching_orders": matching, "pagination": dict(pagination)}


def v15r2_backend_claim_identity(
    plan: Mapping[str, Any], *, plan_sha256: str
) -> dict[str, Any]:
    from application.admin_api.root_child_cancel import root_child_cancel_semantic_key

    context, _ = build_v15r2_cancel_admission_context(
        plan, plan_sha256=plan_sha256
    )
    cancel = dict(plan["cancel_command"])
    return {
        "schema_version": "1",
        "semantic_key": root_child_cancel_semantic_key(
            controlled_plan_sha256=plan_sha256,
            root_client_order_id=R1_ROOT_CLIENT_ORDER_ID,
            child_client_order_id=R1_CHILD_CLIENT_ORDER_ID,
        ),
        "controlled_plan_sha256": plan_sha256,
        "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": R1_CHILD_CLIENT_ORDER_ID,
        "idempotency_key": cancel["idempotency_key"],
        "payload_hash": context["payload_hash"],
        "correlation_id": cancel["correlation_id"],
        "actor_id": context["actor_id"],
        "source": "admin_api_root_child_cancel_claim_log",
    }


def v15r2_operator_monitor_decision(
    placement_records: list[Mapping[str, Any]],
    local_cancel_records: list[Mapping[str, Any]],
    backend_claim_records: list[Mapping[str, Any]],
    *,
    expected_identity: Mapping[str, Any],
    now: datetime,
    expires_at: str,
) -> str:
    """Classify R2 using its actual one-row child-only durable ledger."""

    _require(
        len(placement_records) == 1
        and placement_records[0].get("sequence") == 1
        and placement_records[0].get("attempt_kind") == "child"
        and placement_records[0].get("root_client_order_id")
        == R1_ROOT_CLIENT_ORDER_ID
        and placement_records[0].get("client_order_id")
        == R1_CHILD_CLIENT_ORDER_ID,
        "v15r2_monitor_placement_ledger_incomplete",
    )
    _require(not local_cancel_records, "v15r2_monitor_runner_cancel_claim_forbidden")
    expected = dict(expected_identity)
    identity_fields = (
        "schema_version", "semantic_key", "controlled_plan_sha256",
        "root_client_order_id", "child_client_order_id", "idempotency_key",
        "payload_hash", "correlation_id", "actor_id", "source",
    )
    _require(
        all(
            row.get(field) == expected.get(field)
            for row in backend_claim_records
            for field in identity_fields
        ),
        "v15r2_monitor_backend_claim_identity_mismatch",
    )
    expiry = datetime.fromisoformat(expires_at)
    _require(now.tzinfo is not None and expiry.tzinfo is not None,
             "v15r2_monitor_time_invalid")
    if not backend_claim_records:
        return (
            "awaiting_operator_ui_root_scoped_cancel"
            if now < expiry
            else "plan_expired_active_child_reconciliation_only"
        )
    _require(
        len(backend_claim_records) <= 3
        and backend_claim_records[0].get("event") == "claim"
        and backend_claim_records[0].get("outcome") == "claimed"
        and backend_claim_records[0].get("response") is None
        and backend_claim_records[0].get("reconciliation_required") is False
        and (
            len(backend_claim_records) == 1
            or (
                len(backend_claim_records) == 2
                and (
                    (
                        backend_claim_records[1].get("event") == "exchange_boundary"
                        and backend_claim_records[1].get("outcome") == "unknown"
                        and backend_claim_records[1].get("response") is None
                        and backend_claim_records[1].get("reconciliation_required") is True
                    )
                    or (
                        backend_claim_records[1].get("event") == "outcome"
                        and backend_claim_records[1].get("outcome") == "rejected"
                        and isinstance(backend_claim_records[1].get("response"), Mapping)
                        and backend_claim_records[1].get("reconciliation_required") is False
                    )
                )
            )
            or (
                len(backend_claim_records) == 3
                and backend_claim_records[1].get("event") == "exchange_boundary"
                and backend_claim_records[1].get("outcome") == "unknown"
                and backend_claim_records[1].get("response") is None
                and backend_claim_records[1].get("reconciliation_required") is True
                and backend_claim_records[2].get("event") == "outcome"
                and backend_claim_records[2].get("outcome")
                in {"accepted", "rejected", "unknown"}
                and isinstance(backend_claim_records[2].get("response"), Mapping)
                and backend_claim_records[2].get("reconciliation_required")
                is (backend_claim_records[2].get("outcome") == "unknown")
            )
        ),
        "v15r2_monitor_backend_claim_ledger_invalid",
    )
    latest = str(backend_claim_records[-1].get("outcome") or "")
    in_flight = bool(
        len(backend_claim_records) == 1
        or (
            len(backend_claim_records) == 2
            and backend_claim_records[1].get("event") == "exchange_boundary"
        )
    )
    if in_flight:
        return (
            "awaiting_operator_ui_root_scoped_cancel"
            if now < expiry
            else "plan_expired_ambiguous_cancel_reconciliation_only"
        )
    if latest == "accepted":
        return "verify_terminal_closeout"
    if latest == "rejected":
        return "operator_cancel_rejected_active_child_reconciliation_only"
    if now >= expiry:
        return "plan_expired_ambiguous_cancel_reconciliation_only"
    return "operator_cancel_ambiguous_reconciliation_only"


def execute_v15r2_plan(*, plan_path: Path, confirmed_plan_sha256: str) -> dict[str, Any]:
    """Run one child placement, then wait for the operator's root-scoped cancel."""

    _require(plan_path == PLAN_PATH, "v15r2_execute_plan_file_not_fixed")
    plan = _json(plan_path, "v15r2_execution_plan")
    validate_v15r2_plan(plan, expected_hash=confirmed_plan_sha256)
    _require(
        callable(getattr(base, "is_v15_recovery_plan", None))
        and base.is_v15_recovery_plan(plan),
        "v15r2_shared_runtime_support_missing",
    )
    rest_client = base.hydrate_test_credentials()
    preflight = base.coinbase_preflight(rest_client)
    active_zero = base.prove_stable_authoritative_active_zero(
        rest_client, expected_portfolio_id=TEST_PORTFOLIO_ID
    )
    child_exchange_absence = prove_v15r2_child_exchange_identity_absent(
        rest_client
    )
    root_exchange = base.exact_exchange_order(
        rest_client, R1_ROOT_EXCHANGE_ORDER_ID
    )
    catalog, catalog_pagination = base.read_failed_v6_v7_order_catalog(rest_client)
    child_exchange_matches = [
        dict(row)
        for row in catalog
        if str(row.get("client_order_id") or "") == R1_CHILD_CLIENT_ORDER_ID
    ]
    _require(
        preflight.get("portfolio_id") == TEST_PORTFOLIO_ID
        and active_zero.get("stable_zero") is True
        and str(root_exchange.get("client_order_id") or "")
        == R1_ROOT_CLIENT_ORDER_ID
        and str(root_exchange.get("order_id") or "")
        == R1_ROOT_EXCHANGE_ORDER_ID
        and str(root_exchange.get("status") or "").upper() == "FILLED"
        and Decimal(str(root_exchange.get("filled_size") or "0"))
        == R1_ROOT_FILLED_SIZE
        and Decimal(str(root_exchange.get("filled_value") or "0"))
        == R1_ROOT_FILLED_VALUE
        and int(root_exchange.get("number_of_fills") or 0) == 1
        and catalog_pagination.get("authoritative") is True
        and catalog_pagination.get("pagination_complete") is True
        and not child_exchange_matches,
        "v15r2_execution_preflight_failed",
    )
    _require(
        read_local_hidden_child_binding() == plan["local_hidden_child_binding"],
        "v15r2_local_state_changed_before_authority",
    )
    authority = authorize_v15r2_execution(plan_path, expected_hash=confirmed_plan_sha256)
    runtime = base.AdminRuntime(
        portfolio_id=TEST_PORTFOLIO_ID, confirmed_plan=plan,
        confirmed_plan_hash=confirmed_plan_sha256, global_batch_marker=MARKER_PATH,
        attempt_ledger_path=PLACEMENT_LEDGER_PATH,
        controlled_v15_plan_path=plan_path, controlled_v15_handoff_path=HANDOFF_PATH,
        controlled_v15_claim_log_path=BACKEND_CLAIM_LOG_PATH,
    )
    terminal_closeout = False
    summary: dict[str, Any] = {"status": "running", "authority": authority}
    cleanup: dict[str, Any] = {}
    try:
        runtime.start()
        runtime.wait_until_mutations_ready()
        runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={0}, expected_child_place_limit_order_calls={0}
        )
        _, chain, _ = runtime.request(
            "GET", f"/orders/{R1_ROOT_CLIENT_ORDER_ID}/fill-follow-up/chain",
            headers=runtime.headers(role="auditor"), expected={200},
        )
        _, detail, _ = runtime.request(
            "GET", f"/stealth/orders/{R1_CHILD_CLIENT_ORDER_ID}",
            headers=runtime.headers(role="auditor"), expected={200},
        )
        base._validate_automatic_hidden_child_chain(
            chain, root_client_order_id=R1_ROOT_CLIENT_ORDER_ID,
            portfolio_id=TEST_PORTFOLIO_ID, expected_filled_size=R1_ROOT_FILLED_SIZE,
            expected_placement_correlation_id=str(
                dict(plan["local_hidden_child_binding"])["root_correlation_id"]
            ),
            expected_admission_audit_id=str(
                dict(plan["local_hidden_child_binding"])["root_audit_id"]
            ),
            expected_exchange_order_id=R1_ROOT_EXCHANGE_ORDER_ID,
        )
        base._validate_hidden_child_detail(
            detail, child_id=R1_CHILD_CLIENT_ORDER_ID,
            root_client_order_id=R1_ROOT_CLIENT_ORDER_ID,
            expected_filled_size=R1_ROOT_FILLED_SIZE,
        )
        market = base.fresh_exact_market(rest_client)
        child_tuple = build_execution_child_order_tuple(
            plan, fresh_market=market,
            price_increment=Decimal(str(dict(preflight["product"])["price_increment"])),
        )
        child_body = {
            "reason": "controlled V15R2 first-child recovery submission",
            "manual_live_acknowledgement": True,
            "expected_root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
            "controlled_limit_price": child_tuple["limit_price"],
            "controlled_batch_id": plan["batch_id"], "controlled_batch_slot": 1,
            "controlled_plan_sha256": confirmed_plan_sha256,
        }
        child_headers = runtime.headers(
            idempotency_key=_deterministic_id(str(plan["batch_id"]), "child-reveal-idempotency"),
            operator_intent=CHILD_REVEAL_OPERATOR_INTENT, role=base.COMMAND_ROLE,
            correlation_id=_deterministic_id(str(plan["batch_id"]), "child-reveal-correlation"),
        )
        _, blocked_child, _ = runtime.request(
            "POST", f"/stealth/orders/{R1_CHILD_CLIENT_ORDER_ID}/reveal",
            headers=child_headers, body=child_body, expected={501},
        )
        child_context = base.capture_context(blocked_child)
        child_scope = dict(plan["child"])
        wallets = base._wallet_balances(rest_client, expected_portfolio_id=TEST_PORTFOLIO_ID)
        _require(wallets["BTC"] >= R1_ROOT_FILLED_SIZE, "v15r2_child_wallet_insufficient")
        child_proofs = v15._v15_exact_proofs(
            runtime, label="v15r2-child-reveal", context=child_context,
            scope=child_scope,
            wallet_available=wallets["BTC"] * Decimal(str(child_tuple["limit_price"])),
            max_notional=CHILD_SUBMITTED_CAP, command_kind="child_reveal",
        )
        child_attempt = consume_v15r2_child_attempt(
            PLACEMENT_LEDGER_PATH, plan=plan, plan_sha256=confirmed_plan_sha256,
            exact_order_tuple=child_tuple,
        )
        post_ledger_exchange_absence = prove_v15r2_child_exchange_identity_absent(
            rest_client
        )
        _require(
            load_v15r1_recovery_binding() == plan["v15r1_recovery_binding"]
            and read_local_hidden_child_binding() == plan["local_hidden_child_binding"]
            and base.prove_stable_authoritative_active_zero(
                rest_client, expected_portfolio_id=TEST_PORTFOLIO_ID
            ).get("stable_zero")
            is True,
            "v15r2_recovery_boundary_changed_after_ledger",
        )
        immediate_market = base.fresh_exact_market(rest_client)
        base.validate_exact_child_price_against_fresh_bid(
            child_tuple,
            immediate_market,
            blocker="v15r2_child_price_below_immediate_fresh_bid",
        )
        cancel_context, cancel_body = build_v15r2_cancel_admission_context(
            plan, plan_sha256=confirmed_plan_sha256
        )
        cancel_proofs = v15._v15_exact_proofs(
            runtime, label="v15r2-child-cancel", context=cancel_context,
            scope=dict(plan["cancel_command"]), wallet_available=Decimal("0"),
            max_notional=Decimal("0"), command_kind="child_cancel",
        )
        handoff = write_v15r2_cancel_proof_handoff(
            HANDOFF_PATH, plan=plan, plan_sha256=confirmed_plan_sha256,
            context=cancel_context, proofs=cancel_proofs,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        _require(
            not _jsonl(CANCEL_LEDGER_PATH, "v15r2_cancel_ledger")
            and not _jsonl(BACKEND_CLAIM_LOG_PATH, "v15r2_backend_claim_log"),
            "v15r2_cancel_claim_present_before_child_submission",
        )
        runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={0}, expected_child_place_limit_order_calls={0}
        )
        base.set_live_service(runtime, enabled=True)
        base.preview_admission(runtime, child_context)
        runtime.exchange_safe_to_shutdown = False
        child_status, child_response, child_response_headers = runtime.request(
            "POST", f"/stealth/orders/{R1_CHILD_CLIENT_ORDER_ID}/reveal",
            headers=child_headers, body=child_body, expected=None,
        )
        _require(child_status == 200, f"v15r2_child_reveal_http:{child_status}")
        _require(
            str(child_response_headers.get("X-Idempotency-Replayed") or "").lower() != "true",
            "v15r2_child_reveal_replayed",
        )
        child_exchange_order_id, _ = base._validate_controlled_child_reveal_response(
            child_response,
            root_plan={"root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
                       "child_client_order_id": R1_CHILD_CLIENT_ORDER_ID},
            child_tuple=child_tuple, portfolio_id=TEST_PORTFOLIO_ID,
        )
        runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={0}, expected_child_place_limit_order_calls={1}
        )
        raw_child = base._validate_exact_coinbase_gtc_child_order(
            base.exact_exchange_order(rest_client, child_exchange_order_id),
            expected_exchange_order_id=child_exchange_order_id,
            expected_portfolio_id=TEST_PORTFOLIO_ID, expected_child_tuple=child_tuple,
        )
        v15.validate_v15_explicit_zero_fill(raw_child)
        _require(str(raw_child.get("status") or "").upper() in {"OPEN", "PENDING"},
                 "v15r2_child_not_active_zero_fill")
        base.set_live_service(runtime, enabled=False)
        cancel_path = f"/orders/{R1_ROOT_CLIENT_ORDER_ID}/fill-follow-up/child-cancel"
        _, readiness, _ = runtime.request(
            "GET", f"{cancel_path}/readiness", headers=runtime.headers(role="auditor"),
            params={"controlled_plan_sha256": confirmed_plan_sha256}, expected={200},
        )
        _require(
            readiness.get("ready") is True
            and readiness.get("root_client_order_id") == R1_ROOT_CLIENT_ORDER_ID
            and readiness.get("child_client_order_id") == R1_CHILD_CLIENT_ORDER_ID,
            "v15r2_cancel_readiness_blocked",
        )
        _require(not _jsonl(CANCEL_LEDGER_PATH, "v15r2_cancel_ledger")
                 and not _jsonl(BACKEND_CLAIM_LOG_PATH, "v15r2_backend_claim_log"),
                 "v15r2_cancel_claim_present_before_operator")
        summary.update({
            "status": "awaiting_operator_ui_root_scoped_cancel",
            "child_attempt": child_attempt, "child_proofs": child_proofs,
            "child_exchange_order_id": child_exchange_order_id,
            "child_cancel_proofs": cancel_proofs, "child_cancel_handoff": handoff,
            "child_cancel_readiness": readiness, "operator_cancel_request_body": cancel_body,
            "root_placement_count": 0, "child_placement_count": 1,
            "placement_attempt_count": 1, "cancel_command_count": 0,
            "runner_cancel_post_submitted": False,
        })
        base.set_live_service(runtime, enabled=True)
        base.preview_admission(runtime, cancel_context)
        progress_path = runtime.state_dir / "v15r2-operator-ui-cancel-handoff.json"
        progress = {
            "status": "awaiting_operator_ui_root_scoped_cancel",
            "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
            "child_client_order_id": R1_CHILD_CLIENT_ORDER_ID,
            "controlled_plan_sha256": confirmed_plan_sha256,
            "readiness_url": (
                f"{base.BASE_URL}{cancel_path}/readiness?"
                f"controlled_plan_sha256={confirmed_plan_sha256}"
            ),
            "cancel_url": f"{base.BASE_URL}{cancel_path}",
            "idempotency_key": dict(plan["cancel_command"])["idempotency_key"],
            "correlation_id": dict(plan["cancel_command"])["correlation_id"],
            "operator_intent": CHILD_CANCEL_OPERATOR_INTENT,
            "request_body": cancel_body,
            "runner_cancel_post_submitted": False,
            "runner_cancel_claim_acquired": False,
            "root_placement_authorized": False,
            "runtime_pid": runtime.process.pid if runtime.process else None,
            "state_dir": str(runtime.state_dir),
            "plan_expires_at": plan["expires_at"],
        }
        base._replace_owner_only_json(progress_path, progress)
        print(json.dumps(progress, sort_keys=True), flush=True)
        while True:
            runtime.sdk_boundary_sentinel(
                expected_root_create_order_calls={0}, expected_child_place_limit_order_calls={1}
            )
            backend_rows = v15._read_v15_backend_cancel_claim_records(BACKEND_CLAIM_LOG_PATH)
            if backend_rows:
                decision = v15r2_operator_monitor_decision(
                    _jsonl(PLACEMENT_LEDGER_PATH, "v15r2_placement_ledger"),
                    _jsonl(CANCEL_LEDGER_PATH, "v15r2_cancel_ledger"),
                    backend_rows,
                    expected_identity=v15r2_backend_claim_identity(
                        plan, plan_sha256=confirmed_plan_sha256
                    ),
                    now=datetime.now(timezone.utc),
                    expires_at=str(plan["expires_at"]),
                )
                if decision == "verify_terminal_closeout":
                    _require(
                        len(backend_rows) == 3,
                        "v15r2_backend_cancel_claim_not_exactly_once_accepted",
                    )
                    terminal_child = base._validate_exact_coinbase_gtc_child_order(
                        base.exact_exchange_order(
                            rest_client, child_exchange_order_id
                        ),
                        expected_exchange_order_id=child_exchange_order_id,
                        expected_portfolio_id=TEST_PORTFOLIO_ID,
                        expected_child_tuple=child_tuple,
                    )
                    v15.validate_v15_explicit_zero_fill(terminal_child)
                    _require(
                        str(terminal_child.get("status") or "").upper()
                        in {"CANCELLED", "CANCELED"},
                        "v15r2_child_terminal_zero_fill_unproven",
                    )
                    cancelled_chain = base._validate_cancelled_child_chain(
                        runtime,
                        root_plan={
                            "root_client_order_id": R1_ROOT_CLIENT_ORDER_ID,
                            "child_client_order_id": R1_CHILD_CLIENT_ORDER_ID,
                        },
                        exchange_order_id=child_exchange_order_id,
                    )
                    final_active = base.prove_stable_authoritative_active_zero(
                        rest_client, expected_portfolio_id=TEST_PORTFOLIO_ID
                    )
                    _require(final_active.get("stable_zero") is True,
                             "v15r2_final_active_zero_unproven")
                    base.set_live_service(runtime, enabled=False)
                    runtime.exchange_safe_to_shutdown = True
                    terminal_closeout = True
                    summary.update({
                        "status": "passed", "cancel_command_count": 1,
                        "backend_cancel_claim_event_count": 3,
                        "child_terminal_status": str(
                            terminal_child.get("status") or ""
                        ).upper(),
                        "cancelled_child_chain": cancelled_chain,
                        "final_active_spot_order_count": 0,
                    })
                    break
                if decision != "awaiting_operator_ui_root_scoped_cancel":
                    summary["status"] = decision
                    break
            if datetime.now(timezone.utc) >= datetime.fromisoformat(str(plan["expires_at"])):
                summary["status"] = "plan_expired_active_child_reconciliation_only"
                break
            time.sleep(0.5)
    finally:
        if runtime.live_service_may_be_enabled:
            try:
                base.set_live_service(runtime, enabled=False)
            except Exception as exc:
                cleanup["live_service_disable_error"] = f"{type(exc).__name__}:{exc}"
                runtime.exchange_safe_to_shutdown = False
        cleanup.update(runtime.stop_if_safe())
        summary["runtime_cleanup"] = cleanup
        if "progress_path" in locals():
            base._replace_owner_only_json(
                progress_path,
                {
                    **progress,
                    "status": summary.get("status"),
                    "runtime_cleanup": cleanup,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    _require(
        terminal_closeout or cleanup.get("runtime_preserved_for_reconciliation") is True,
        "v15r2_nonterminal_runtime_not_preserved",
    )
    return summary


def prepare_v15r2_plan(
    *,
    plan_path: Path = PLAN_PATH,
    marker_path: Path = MARKER_PATH,
    placement_ledger_path: Path = PLACEMENT_LEDGER_PATH,
    cancel_ledger_path: Path = CANCEL_LEDGER_PATH,
    backend_claim_log_path: Path = BACKEND_CLAIM_LOG_PATH,
    handoff_path: Path = HANDOFF_PATH,
    now: datetime | None = None,
    require_clean_environment: bool = True,
) -> dict[str, Any]:
    if require_clean_environment:
        _require(
            _git("rev-list", "--left-right", "--count", "HEAD...origin/main")
            == "0\t0"
            and not _git("status", "--porcelain", "--untracked-files=no"),
            "v15r2_backend_not_clean_and_synced",
        )
        _require(
            _git(
                "rev-list", "--left-right", "--count", "HEAD...origin/main",
                cwd=FRONTEND_ROOT,
            ) == "0\t0"
            and not _git(
                "status", "--porcelain", "--untracked-files=no",
                cwd=FRONTEND_ROOT,
            ),
            "v15r2_frontend_not_clean_and_synced",
        )
    _require(
        all(not os.path.lexists(path) for path in (
            plan_path, marker_path, placement_ledger_path, cancel_ledger_path,
            backend_claim_log_path, handoff_path,
        )),
        "v15r2_prepare_path_already_exists",
    )
    binding = load_v15r1_recovery_binding()
    local_binding = read_local_hidden_child_binding()
    plan = build_v15r2_plan(binding, local_hidden_child=local_binding, now=now)
    plan_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    base._write_owner_only_exclusive_json(
        plan_path, plan, exists_blocker="v15r2_plan_path_already_exists"
    )
    return {
        "status": "prepared", "plan_path": str(plan_path),
        "plan_sha256": plan["plan_sha256"], "expires_at": plan["expires_at"],
        "placement_attempt_count": 1, "root_placement_maximum": 0,
        "child_placement_maximum": 1, "cancel_command_maximum": 1,
        "planned_reference_notional_usdc": plan["planned_reference_notional_usdc"],
        "conservative_reference_notional_usdc": plan["conservative_reference_notional_usdc"],
        "live_coinbase_orders_ran": False, "live_coinbase_read_ran": False,
        "marker_written": False, "ledger_written": False,
        "runtime_started": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-v15r2-plan", action="store_true")
    mode.add_argument("--execute-v15r2-plan", action="store_true")
    parser.add_argument("--plan-file")
    parser.add_argument("--confirm-plan-sha256")
    args = parser.parse_args(argv)
    if args.prepare_v15r2_plan:
        print(json.dumps(prepare_v15r2_plan(), sort_keys=True))
        return 0
    _require(bool(args.plan_file), "v15r2_execute_plan_file_required")
    _require(Path(args.plan_file).resolve() == PLAN_PATH, "v15r2_execute_plan_file_not_fixed")
    _require(bool(args.confirm_plan_sha256), "v15r2_execute_plan_hash_required")
    print(json.dumps(execute_v15r2_plan(
        plan_path=PLAN_PATH, confirmed_plan_sha256=args.confirm_plan_sha256
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
