"""Prepare or execute the sealed V15R6 child-cancel recovery.

V15R6 authorizes no placement. Preparation validates and binds the consumed
V15R5 client-id cancellation rejection, the still-open zero-fill child, and
the exact preserved read-only runtime. It writes only an owner-only schema-24
plan. Execution requires a separately confirmed plan hash before it may send
one SIGTERM to that exact predecessor, prove no overlap, start a replacement
runtime, and expose one root-scoped operator cancel. The runner never submits
the operator cancel itself.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from application.admin_api import root_child_cancel as authority
from tools import run_controlled_admin_spot_child_cancel_recovery_v15r5 as v15r5
from tools import run_controlled_admin_spot_child_cancel_slice as v15
from tools import run_controlled_admin_spot_root_child_batch as base


ProofFailure = base.ProofFailure
PRODUCT_ID = base.PRODUCT_ID
PROFILE_LABEL = base.PROFILE_LABEL
TEST_PORTFOLIO_ID = base.TEST_PORTFOLIO_ID
ROOT_REFERENCE_CAP = v15r5.ROOT_REFERENCE_CAP
CHILD_REFERENCE_CAP = v15r5.CHILD_REFERENCE_CAP
SLICE_REFERENCE_CAP = v15r5.SLICE_REFERENCE_CAP
ROOT_ACTUAL_REFERENCE_NOTIONAL = v15r5.ROOT_ACTUAL_REFERENCE_NOTIONAL
ACTIVE_CHILD_REFERENCE_NOTIONAL = v15r5.ACTIVE_CHILD_REFERENCE_NOTIONAL
AGGREGATE_REFERENCE_NOTIONAL = v15r5.AGGREGATE_REFERENCE_NOTIONAL
CHILD_BASE_SIZE = v15r5.CHILD_BASE_SIZE
CHILD_LIMIT_PRICE = v15r5.CHILD_LIMIT_PRICE
PLAN_TTL = timedelta(minutes=120)
PLAN_SCHEMA_VERSION = "24"
AUTHORITY_KIND = authority.CONTROLLED_V15R6_AUTHORITY_KIND
ACTOR_ID = v15r5.ACTOR_ID
ACTOR_ROLES = list(v15r5.ACTOR_ROLES)
CANCEL_OPERATOR_INTENT = v15r5.CANCEL_OPERATOR_INTENT
ROOT_CLIENT_ORDER_ID = v15r5.ROOT_CLIENT_ORDER_ID
ROOT_EXCHANGE_ORDER_ID = v15r5.ROOT_EXCHANGE_ORDER_ID
CHILD_CLIENT_ORDER_ID = v15r5.CHILD_CLIENT_ORDER_ID
CHILD_EXCHANGE_ORDER_ID = v15r5.CHILD_EXCHANGE_ORDER_ID
R2_PLAN_SHA256 = v15r5.R2_PLAN_SHA256
R2_BATCH_ID = v15r5.R2_BATCH_ID
EXCHANGE_CANCEL_SUBMISSION_IDENTITY = (
    "authoritative_exchange_order_id_resolved_from_client_order_id"
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT.parent / "coinbase-frontend"
REGISTRY_DIR = Path("/var/tmp/coinbase-admin-controlled-spot-root-child-batches")
PLAN_PATH = Path(
    "/home/ec2-user/.local/state/"
    "coinbase-controlled-spot-child-cancel-v15r6-20260713.plan.json"
)
REGISTRY_PREFIX = "test-profile-btc-usdc-selected-child-cancel-v15r6-20260713"
MARKER_PATH = REGISTRY_DIR / f"{REGISTRY_PREFIX}.authority.json"
PLACEMENT_LEDGER_PATH = REGISTRY_DIR / f"{REGISTRY_PREFIX}.placements.jsonl"
CANCEL_LEDGER_PATH = REGISTRY_DIR / f"{REGISTRY_PREFIX}.cancel-command.jsonl"
BACKEND_CLAIM_LOG_PATH = REGISTRY_DIR / f"{REGISTRY_PREFIX}.backend-claims.jsonl"
HANDOFF_PATH = REGISTRY_DIR / f"{REGISTRY_PREFIX}.handoff.json"
RUNTIME_PATH = REGISTRY_DIR / f"{REGISTRY_PREFIX}.runtime.json"
SIGNAL_CLAIM_PATH = (
    REGISTRY_DIR / f"{REGISTRY_PREFIX}.predecessor-signal-claim.json"
)

REJECTED_V15R5_BINDING = deepcopy(
    authority.CONTROLLED_V15R6_REJECTED_EXECUTION_BINDING
)
REJECTED_V15R5_PATHS = {
    key: Path(value)
    for key, value in dict(REJECTED_V15R5_BINDING["artifact_paths"]).items()
}
REJECTED_V15R5_STATE_DIR = Path(
    "/home/ec2-user/coinbase/artifacts/"
    "controlled-root-child-batch-20260713T080455Z-42756f48"
)
REJECTED_V15R5_RUNTIME_LOG_PATH = REJECTED_V15R5_STATE_DIR / "embedded-runtime.log"
REJECTED_V15R5_PARENT_LOSS_PATH = (
    REJECTED_V15R5_STATE_DIR / "parent-authority-loss.json"
)
V15R6_PLAN_FIELDS = authority.CONTROLLED_V15R6_PLAN_FIELDS
V15R6_TRANSITION_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "transition_mode",
        "controlled_plan_sha256",
        "predecessor_plan_sha256",
        "predecessor_runtime_process_identity",
        "predecessor_signal",
        "predecessor_signal_claim",
        "predecessor_signal_attempt_count",
        "predecessor_restart_attempt_count",
        "predecessor_process_absent",
        "admin_port_8787_free",
        "competitor_pid",
        "pre_signal_stable_artifact_hashes",
        "pre_signal_parent_authority_loss_semantic_projection",
        "post_signal_final_mutable_artifact_hashes",
        "exact_child_open_zero_fill",
        "child_readback",
        "recorded_at",
        "transition_sha256",
    }
)
V15R6_SIGNAL_CLAIM_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "controlled_plan_sha256",
        "predecessor_plan_sha256",
        "predecessor_runtime_process_identity",
        "signal",
        "attempt_number",
        "restart_attempt_count",
        "forced_kill_attempt_count",
        "claimed_at",
        "claim_sha256",
    }
)


def _require(condition: bool, blocker: str) -> None:
    if not condition:
        raise ProofFailure(blocker)


def _canonical_json_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()


def _canonical_record_sha256(value: Mapping[str, Any]) -> str:
    return _canonical_json_sha256(value)


def _git(*args: str, cwd: Path = ROOT) -> str:
    return v15r5._git(*args, cwd=cwd)


def backend_commit() -> str:
    return _git("rev-parse", "HEAD")


def frontend_commit() -> str:
    return _git("rev-parse", "HEAD", cwd=FRONTEND_ROOT)


def runner_sha256() -> str:
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def plan_hash(plan: Mapping[str, Any]) -> str:
    return base.plan_hash(plan)


def _deterministic_id(batch_id: str, purpose: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"coinbase://selected-child-cancel-v15r6/{batch_id}/{purpose}",
        )
    )


def cancel_command_ids(plan: Mapping[str, Any]) -> tuple[str, ...]:
    cancel = dict(plan.get("cancel_command") or {})
    return tuple(
        str(cancel.get(field) or "")
        for field in (
            "idempotency_key",
            "correlation_id",
            "claim_id",
            "approval_snapshot_id",
            "cap_guard_decision_id",
            "reconciliation_plan_id",
        )
    )


def build_v15r6_plan(
    v15r5_plan: Mapping[str, Any],
    *,
    local_active_child: Mapping[str, Any],
    rejected_v15r5_execution_binding: Mapping[str, Any],
    now: datetime | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Build one fresh schema-24 cancel-only authority."""

    source = deepcopy(dict(v15r5_plan))
    validate_rejected_v15r5_source_plan(source)
    rejected = deepcopy(dict(rejected_v15r5_execution_binding))
    _require(
        rejected == REJECTED_V15R5_BINDING,
        "v15r6_rejected_v15r5_execution_binding_mismatch",
    )
    local = v15r5.validate_local_active_child_binding(local_active_child)
    created_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    approval = approval_id or f"controlled-child-cancel-v15r6-{uuid4()}"
    _require(
        approval.startswith("controlled-child-cancel-v15r6-"),
        "v15r6_approval_namespace_invalid",
    )
    UUID(approval.removeprefix("controlled-child-cancel-v15r6-"))
    exact_runner = runner_sha256()
    commit = backend_commit()
    batch_id = str(
        uuid5(
            NAMESPACE_URL,
            f"coinbase://selected-child-cancel-v15r6/"
            f"{commit}/{exact_runner}/{approval}",
        )
    )
    plan = {
        key: deepcopy(value)
        for key, value in source.items()
        if key in authority.CONTROLLED_V15R5_PLAN_FIELDS
    }
    cancel = dict(plan["cancel_command"])
    for field, purpose in (
        ("idempotency_key", "child-cancel-idempotency"),
        ("correlation_id", "child-cancel-correlation"),
        ("claim_id", "child-cancel-claim"),
        ("approval_snapshot_id", "child-cancel-approval"),
        ("cap_guard_decision_id", "child-cancel-cap"),
        ("reconciliation_plan_id", "child-cancel-reconciliation"),
    ):
        cancel[field] = _deterministic_id(batch_id, purpose)
    cancel["semantic_retry_policy"] = (
        "fresh_v15r6_idempotency_key_exactly_once"
    )
    plan.update(
        {
            "schema_version": PLAN_SCHEMA_VERSION,
            "authority_kind": AUTHORITY_KIND,
            "approval_id": approval,
            "batch_id": batch_id,
            "created_at": created_at.isoformat(),
            "expires_at": (created_at + PLAN_TTL).isoformat(),
            "backend_commit": commit,
            "frontend_commit": frontend_commit(),
            "runner_sha256": exact_runner,
            "local_active_child_binding": local,
            "cancel_command": cancel,
            "rejected_v15r5_execution_binding": rejected,
            "exchange_cancel_submission_identity": (
                EXCHANGE_CANCEL_SUBMISSION_IDENTITY
            ),
            "predecessor_runtime_signal_attempt_maximum": 1,
            "predecessor_runtime_restart_attempt_maximum": 0,
            "predecessor_runtime_signal": "SIGTERM",
            "runtime_no_overlap_required": True,
        }
    )
    plan.pop("plan_sha256", None)
    plan["plan_sha256"] = plan_hash(plan)
    prior_ids = set(authority.CONTROLLED_V15R2_USED_CANCEL_IDS)
    prior_ids.update(
        str(value)
        for value in dict(rejected["cancel_command_ids"]).values()
    )
    _require(
        batch_id not in prior_ids
        and all(cancel_command_ids(plan))
        and len(set(cancel_command_ids(plan))) == 6
        and set(cancel_command_ids(plan)).isdisjoint(prior_ids),
        "v15r6_fresh_id_scope_mismatch",
    )
    authority.validate_controlled_v15r6_recovery_plan_scope(plan)
    return plan


def validate_v15r6_plan_structure(
    plan: Mapping[str, Any],
    *,
    expected_hash: str,
    now: datetime | None = None,
) -> None:
    _require(set(plan) == V15R6_PLAN_FIELDS, "v15r6_plan_fields_mismatch")
    computed = plan_hash(plan)
    _require(
        secrets.compare_digest(str(plan.get("plan_sha256") or ""), computed)
        and secrets.compare_digest(expected_hash, computed),
        "v15r6_plan_hash_mismatch",
    )
    _require(
        plan.get("schema_version") == PLAN_SCHEMA_VERSION
        and plan.get("authority_kind") == AUTHORITY_KIND
        and plan.get("backend_commit") == backend_commit()
        and plan.get("frontend_commit") == frontend_commit()
        and plan.get("runner_sha256") == runner_sha256(),
        "v15r6_plan_code_binding_mismatch",
    )
    try:
        authority.validate_controlled_v15r6_recovery_plan_scope(plan)
        created_at = datetime.fromisoformat(str(plan.get("created_at") or ""))
        expires_at = datetime.fromisoformat(str(plan.get("expires_at") or ""))
        current = now or datetime.now(timezone.utc)
        valid_time = bool(
            created_at.tzinfo is not None
            and expires_at.tzinfo is not None
            and expires_at - created_at == PLAN_TTL
            and created_at <= current < expires_at
        )
    except (TypeError, ValueError, authority.AdminRootChildCancelAuthorityError):
        valid_time = False
    _require(valid_time, "v15r6_plan_expired_or_ttl_invalid")


def validate_v15r6_clean_synced_environment(plan: Mapping[str, Any]) -> None:
    """Re-prove both tracked worktrees immediately before transition."""

    for root, expected_commit, blocker in (
        (
            ROOT,
            str(plan.get("backend_commit") or ""),
            "v15r6_backend_not_clean_and_synced",
        ),
        (
            FRONTEND_ROOT,
            str(plan.get("frontend_commit") or ""),
            "v15r6_frontend_not_clean_and_synced",
        ),
    ):
        _require(
            _git("rev-parse", "HEAD", cwd=root) == expected_commit
            and _git(
                "rev-list",
                "--left-right",
                "--count",
                "HEAD...origin/main",
                cwd=root,
            )
            == "0\t0"
            and not _git(
                "status",
                "--porcelain",
                "--untracked-files=no",
                cwd=root,
            ),
            blocker,
        )


def require_v15r6_successor_paths_absent(*paths: Path) -> None:
    _require(
        all(not os.path.lexists(path) for path in paths),
        "v15r6_successor_artifact_exists",
    )


def signal_claim_hash(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("claim_sha256", None)
    return _canonical_json_sha256(payload)


def validate_v15r6_signal_claim(
    plan: Mapping[str, Any], claim: Mapping[str, Any]
) -> None:
    rejected = dict(plan.get("rejected_v15r5_execution_binding") or {})
    record = dict(claim)
    try:
        claimed_at = datetime.fromisoformat(str(record.get("claimed_at") or ""))
        expires_at = datetime.fromisoformat(str(plan.get("expires_at") or ""))
        valid = bool(
            set(record) == V15R6_SIGNAL_CLAIM_FIELDS
            and record.get("schema_version") == "1"
            and record.get("status")
            == "v15r6_predecessor_signal_attempt_claimed"
            and record.get("controlled_plan_sha256") == plan.get("plan_sha256")
            and record.get("predecessor_plan_sha256")
            == rejected.get("plan_sha256")
            and record.get("predecessor_runtime_process_identity")
            == rejected.get("runtime_process_identity")
            and record.get("signal") == "SIGTERM"
            and record.get("attempt_number") == 1
            and record.get("restart_attempt_count") == 0
            and record.get("forced_kill_attempt_count") == 0
            and claimed_at.tzinfo is not None
            and expires_at.tzinfo is not None
            and claimed_at < expires_at
            and secrets.compare_digest(
                str(record.get("claim_sha256") or ""),
                signal_claim_hash(record),
            )
        )
    except (TypeError, ValueError):
        valid = False
    _require(valid, "v15r6_predecessor_signal_claim_invalid")


def create_v15r6_signal_claim(
    plan: Mapping[str, Any],
    *,
    claim_path: Path,
    claimed_at: datetime | None = None,
) -> dict[str, Any]:
    rejected = dict(plan.get("rejected_v15r5_execution_binding") or {})
    current = claimed_at or datetime.now(timezone.utc)
    claim: dict[str, Any] = {
        "schema_version": "1",
        "status": "v15r6_predecessor_signal_attempt_claimed",
        "controlled_plan_sha256": plan["plan_sha256"],
        "predecessor_plan_sha256": rejected["plan_sha256"],
        "predecessor_runtime_process_identity": deepcopy(
            rejected["runtime_process_identity"]
        ),
        "signal": "SIGTERM",
        "attempt_number": 1,
        "restart_attempt_count": 0,
        "forced_kill_attempt_count": 0,
        "claimed_at": current.isoformat(),
    }
    claim["claim_sha256"] = signal_claim_hash(claim)
    validate_v15r6_signal_claim(plan, claim)
    claim_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    base._write_owner_only_exclusive_json(
        claim_path,
        claim,
        exists_blocker="v15r6_predecessor_signal_claim_already_exists",
    )
    return claim


def stable_v15r5_artifact_hashes(
    rejected: Mapping[str, Any],
) -> dict[str, str]:
    return {
        str(name): str(value)
        for name, value in dict(rejected.get("artifact_hashes") or {}).items()
        if name != "sentinel"
    }


def parent_authority_loss_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = tuple(
        dict(REJECTED_V15R5_BINDING[
            "parent_authority_loss_semantic_projection"
        ])
    )
    return {field: value.get(field) for field in fields}


def _listener_owned_by_process(process_id: int, *, port: int = base.PORT) -> bool:
    listener_inodes: set[str] = set()
    expected_port = f"{port:04X}"
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = table.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10:
                continue
            local = fields[1]
            state = fields[3]
            if local.rsplit(":", 1)[-1].upper() == expected_port and state == "0A":
                listener_inodes.add(fields[9])
    if not listener_inodes:
        return False
    try:
        descriptors = list(Path(f"/proc/{process_id}/fd").iterdir())
    except OSError:
        return False
    for descriptor in descriptors:
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        if target.startswith("socket:[") and target[8:-1] in listener_inodes:
            return True
    return False


def _record_counts() -> dict[str, int]:
    paths = {
        "approval": REJECTED_V15R5_STATE_DIR / "approvals.jsonl",
        "audit": REJECTED_V15R5_STATE_DIR / "audit.jsonl",
        "cap_guard": REJECTED_V15R5_STATE_DIR / "cap_guard.jsonl",
        "idempotency": REJECTED_V15R5_STATE_DIR / "idempotency.jsonl",
        "live_service": REJECTED_V15R5_STATE_DIR / "live_service.jsonl",
        "reconciliation": REJECTED_V15R5_STATE_DIR / "reconciliation.jsonl",
        "backend_claim": REJECTED_V15R5_PATHS["backend_claim_log"],
    }
    return {
        name: len(
            v15r5._jsonl(
                path,
                f"v15r6_v15r5_{name}",
                allow_public_read=name != "backend_claim",
            )
        )
        for name, path in paths.items()
    }


def _find_record(
    rows: list[Mapping[str, Any]],
    *,
    predicate,
    blocker: str,
) -> dict[str, Any]:
    matches = [dict(row) for row in rows if predicate(row)]
    _require(len(matches) == 1, blocker)
    return matches[0]


def validate_rejected_v15r5_service_disable_records(
    service_rows: list[Mapping[str, Any]],
    expected: Mapping[str, Any],
) -> None:
    record_hashes = dict(expected.get("record_hashes") or {})
    expected_hashes = {
        str(record_hashes.get("service_disabled") or ""),
        str(record_hashes.get("parent_loss_service_disabled") or ""),
    }
    matched = [
        dict(row)
        for row in service_rows
        if _canonical_record_sha256(row) in expected_hashes
    ]
    exact_hashes = {_canonical_record_sha256(row) for row in matched}
    exact_disable_semantics = all(
        row.get("service_enabled") is False
        and row.get("requested_service_status") == "live_disabled"
        and row.get("live_coinbase_execution_approved") is False
        and str(row.get("max_submitted_notional_usdc") or "") == "0"
        and str(row.get("max_executed_notional_usdc") or "") == "0"
        for row in matched
    )
    _require(
        len(expected_hashes) == 2
        and "" not in expected_hashes
        and len(matched) == 2
        and exact_hashes == expected_hashes
        and exact_disable_semantics,
        "v15r6_v15r5_service_disable_record_mismatch",
    )


def validate_rejected_v15r5_source_plan(source_plan: Mapping[str, Any]) -> None:
    """Validate the consumed predecessor in its historical authority window."""

    try:
        created_at = datetime.fromisoformat(
            str(source_plan.get("created_at") or "")
        )
    except ValueError as exc:
        raise ProofFailure("v15r6_v15r5_created_at_invalid") from exc
    _require(
        created_at.tzinfo is not None,
        "v15r6_v15r5_created_at_invalid",
    )
    authority.validate_controlled_v15r5_recovery_plan_scope(
        source_plan,
        now=created_at,
    )


def load_rejected_v15r5_execution_binding() -> dict[str, Any]:
    """Prove the exact consumed V15R5 boundary and preserved runtime."""

    expected = deepcopy(REJECTED_V15R5_BINDING)
    artifact_paths = {
        key: Path(value) for key, value in dict(expected["artifact_paths"]).items()
    }
    for name, expected_hash in dict(expected["artifact_hashes"]).items():
        observed = v15r5._file_sha256(
            artifact_paths[name],
            f"v15r6_v15r5_{name}",
            allow_public_read=name == "runtime_pid",
        )
        _require(observed == expected_hash, f"v15r6_v15r5_{name}_hash_mismatch")

    source_plan = v15r5._json(artifact_paths["plan"], "v15r6_v15r5_plan")
    validate_rejected_v15r5_source_plan(source_plan)
    _require(
        source_plan.get("plan_sha256") == expected["plan_sha256"]
        and source_plan.get("approval_id") == expected["approval_id"]
        and source_plan.get("batch_id") == expected["batch_id"]
        and source_plan.get("backend_commit") == expected["backend_commit"]
        and source_plan.get("runner_sha256") == expected["runner_sha256"],
        "v15r6_v15r5_plan_scope_mismatch",
    )
    _require(
        _record_counts() == expected["record_counts"],
        "v15r6_v15r5_record_count_mismatch",
    )
    cancel_key = str(dict(expected["cancel_command_ids"])["idempotency_key"])
    idempotency_rows = v15r5._jsonl(
        REJECTED_V15R5_STATE_DIR / "idempotency.jsonl",
        "v15r6_v15r5_idempotency",
        allow_public_read=True,
    )
    cancel_idempotency = _find_record(
        idempotency_rows,
        predicate=lambda row: row.get("idempotency_key") == cancel_key,
        blocker="v15r6_v15r5_cancel_idempotency_missing",
    )
    response = dict(cancel_idempotency.get("response") or {})
    _require(
        _canonical_record_sha256(cancel_idempotency)
        == dict(expected["record_hashes"])["cancel_idempotency"]
        and _canonical_record_sha256(response)
        == dict(expected["record_hashes"])["cancel_response"]
        and response.get("status") == "rejected"
        and response.get("failure_stage") == "cancellation_rejected"
        and response.get("live_exchange_submitted") is True
        and response.get("live_coinbase_orders_ran") is True,
        "v15r6_v15r5_cancel_response_mismatch",
    )
    audit_rows = v15r5._jsonl(
        REJECTED_V15R5_STATE_DIR / "audit.jsonl",
        "v15r6_v15r5_audit",
        allow_public_read=True,
    )
    cancel_audit = _find_record(
        audit_rows,
        predicate=lambda row: (
            row.get("idempotency_key") == cancel_key
            and row.get("failure_stage") == "cancellation_rejected"
        ),
        blocker="v15r6_v15r5_cancel_audit_missing",
    )
    _require(
        _canonical_record_sha256(cancel_audit)
        == dict(expected["record_hashes"])["cancel_audit"],
        "v15r6_v15r5_cancel_audit_mismatch",
    )
    claims = v15r5._jsonl(
        artifact_paths["backend_claim_log"], "v15r6_v15r5_claims"
    )
    _require(
        len(claims) == 2
        and claims[0].get("event") == "claim"
        and claims[0].get("outcome") == "claimed"
        and claims[1].get("event") == "exchange_boundary"
        and claims[1].get("outcome") == "unknown"
        and claims[1].get("reconciliation_required") is True
        and _canonical_record_sha256(claims[0])
        == dict(expected["record_hashes"])["claim"]
        and _canonical_record_sha256(claims[1])
        == dict(expected["record_hashes"])["exchange_boundary"],
        "v15r6_v15r5_claim_boundary_mismatch",
    )
    service_rows = v15r5._jsonl(
        REJECTED_V15R5_STATE_DIR / "live_service.jsonl",
        "v15r6_v15r5_live_service",
        allow_public_read=True,
    )
    validate_rejected_v15r5_service_disable_records(service_rows, expected)
    _require(
        bool(service_rows)
        and service_rows[-1].get("service_enabled") is False
        and service_rows[-1].get("requested_service_status") == "live_disabled",
        "v15r6_v15r5_service_not_disabled",
    )
    parent_loss = v15r5._json(
        REJECTED_V15R5_PARENT_LOSS_PATH, "v15r6_v15r5_parent_loss"
    )
    _require(
        parent_authority_loss_projection(parent_loss)
        == expected["parent_authority_loss_semantic_projection"],
        "v15r6_v15r5_parent_loss_projection_mismatch",
    )
    runtime_identity = dict(expected["runtime_process_identity"])
    runtime_pid = int(runtime_identity["process_id"])
    _require(
        v15r5._process_id_absent(int(expected["parent_process_id"]))
        and v15r5._read_process_identity(runtime_pid) == runtime_identity
        and _listener_owned_by_process(runtime_pid),
        "v15r6_v15r5_runtime_identity_or_listener_mismatch",
    )
    environment = v15r5._read_process_environment(runtime_pid)
    _require(
        environment.get(authority.CONTROLLED_V15_PLAN_SHA256_ENV)
        == expected["plan_sha256"]
        and environment.get(authority.CONTROLLED_V15_PLAN_PATH_ENV)
        == str(artifact_paths["plan"])
        and environment.get(authority.CONTROLLED_V15_MARKER_PATH_ENV)
        == str(artifact_paths["marker"])
        and environment.get(authority.CONTROLLED_V15_HANDOFF_PATH_ENV)
        == str(artifact_paths["handoff"]),
        "v15r6_v15r5_runtime_environment_mismatch",
    )
    cancel_line = (
        f'POST /api/v1/orders/{ROOT_CLIENT_ORDER_ID}/fill-follow-up/'
        'child-cancel HTTP/1.1"'
    )
    log_text = v15r5._text(
        REJECTED_V15R5_RUNTIME_LOG_PATH,
        "v15r6_v15r5_runtime_log",
        allow_public_read=True,
    )
    _require(
        log_text.count(cancel_line) == expected["cancel_route_call_count"],
        "v15r6_v15r5_cancel_route_count_mismatch",
    )
    sentinel = v15r5._json(artifact_paths["sentinel"], "v15r6_v15r5_sentinel")
    _require(
        sentinel.get("root_create_order_call_count") == 0
        and sentinel.get("child_place_limit_order_call_count") == 0
        and sentinel.get("root_sdk_inflight") is False
        and sentinel.get("child_sdk_inflight") is False
        and not sentinel.get("critical_failure"),
        "v15r6_v15r5_sentinel_mismatch",
    )
    child = read_exact_active_child_after_transition()
    _require(
        child == expected["child_readback"],
        "v15r6_v15r5_child_readback_mismatch",
    )
    return expected


def read_exact_active_child_after_transition() -> dict[str, Any]:
    return v15r5.read_exact_active_child_after_transition()


def _read_process_identity(process_id: int) -> dict[str, Any]:
    return v15r5._read_process_identity(process_id)


def signal_exact_process(identity: Mapping[str, Any], signum: int) -> None:
    v15r5.signal_exact_process(identity, signum)


def wait_exact_process_absent(identity: Mapping[str, Any]) -> bool:
    return v15r5.wait_exact_process_absent(identity)


def prove_admin_port_free() -> dict[str, Any]:
    return v15r5.prove_admin_port_free()


def validate_final_v15r5_sentinel(
    sentinel: Mapping[str, Any], *, expected_process_id: int
) -> None:
    _require(
        sentinel.get("phase") == "runtime_exited"
        and sentinel.get("process_id") == expected_process_id
        and sentinel.get("root_create_order_call_count") == 0
        and sentinel.get("root_create_order_maximum") == 0
        and sentinel.get("child_place_limit_order_call_count") == 0
        and sentinel.get("child_place_limit_order_maximum") == 0
        and sentinel.get("root_sdk_inflight") is False
        and sentinel.get("child_sdk_inflight") is False
        and sentinel.get("critical_failure") is False
        and sentinel.get("denied_call_count") == 0
        and sentinel.get("installed") is True
        and sentinel.get("wrapper_identity_proven") is True
        and sentinel.get("error") is None,
        "v15r6_v15r5_final_sentinel_mismatch",
    )


def final_mutable_artifact_hashes() -> dict[str, str]:
    sentinel = v15r5._json(
        REJECTED_V15R5_PATHS["sentinel"],
        "v15r6_final_sentinel",
    )
    validate_final_v15r5_sentinel(
        sentinel,
        expected_process_id=int(
            dict(REJECTED_V15R5_BINDING["runtime_process_identity"])[
                "process_id"
            ]
        ),
    )
    return {
        "parent_authority_loss": v15r5._file_sha256(
            REJECTED_V15R5_PARENT_LOSS_PATH,
            "v15r6_final_parent_authority_loss",
        ),
        "runtime_log": v15r5._file_sha256(
            REJECTED_V15R5_RUNTIME_LOG_PATH,
            "v15r6_final_runtime_log",
            allow_public_read=True,
        ),
        "sentinel": v15r5._file_sha256(
            REJECTED_V15R5_PATHS["sentinel"],
            "v15r6_final_sentinel",
        ),
    }


def transition_hash(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("transition_sha256", None)
    return _canonical_json_sha256(payload)


def transition_v15r5_runtime(
    plan: Mapping[str, Any],
    *,
    confirmed_plan_sha256: str,
    transition_path: Path,
    signal_claim_path: Path = SIGNAL_CLAIM_PATH,
    marker_path: Path = MARKER_PATH,
    placement_ledger_path: Path = PLACEMENT_LEDGER_PATH,
    cancel_ledger_path: Path = CANCEL_LEDGER_PATH,
    backend_claim_log_path: Path = BACKEND_CLAIM_LOG_PATH,
    handoff_path: Path = HANDOFF_PATH,
    now: datetime | None = None,
    pre_signal_now: datetime | None = None,
) -> dict[str, Any]:
    """Stop only the sealed preserved V15R5 runtime and prove no overlap."""

    validate_v15r6_plan_structure(
        plan,
        expected_hash=confirmed_plan_sha256,
        now=now,
    )
    successor_paths = (
        signal_claim_path,
        transition_path,
        marker_path,
        placement_ledger_path,
        cancel_ledger_path,
        backend_claim_log_path,
        handoff_path,
    )
    require_v15r6_successor_paths_absent(*successor_paths)
    rejected = load_rejected_v15r5_execution_binding()
    _require(
        plan.get("rejected_v15r5_execution_binding") == rejected,
        "v15r6_transition_rejected_binding_mismatch",
    )
    identity = dict(rejected["runtime_process_identity"])
    process_id = int(identity["process_id"])
    _require(
        _read_process_identity(process_id) == identity,
        "v15r6_transition_process_identity_changed",
    )
    validate_v15r6_clean_synced_environment(plan)
    require_v15r6_successor_paths_absent(*successor_paths)
    _require(
        _read_process_identity(process_id) == identity,
        "v15r6_transition_process_identity_changed",
    )
    final_now = pre_signal_now
    if final_now is None and now is not None:
        final_now = now
    validate_v15r6_plan_structure(
        plan,
        expected_hash=confirmed_plan_sha256,
        now=final_now,
    )
    signal_claim = create_v15r6_signal_claim(
        plan,
        claim_path=signal_claim_path,
        claimed_at=final_now,
    )
    signal_exact_process(identity, signal.SIGTERM)
    _require(
        wait_exact_process_absent(identity),
        "v15r6_transition_predecessor_shutdown_unproven",
    )
    port = prove_admin_port_free()
    child = read_exact_active_child_after_transition()
    exact_child = bool(
        child.get("client_order_id") == CHILD_CLIENT_ORDER_ID
        and child.get("exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
        and str(child.get("status") or "").upper() in {"OPEN", "PENDING"}
        and Decimal(str(child.get("filled_size") or "0")) == 0
        and Decimal(str(child.get("filled_value") or "0")) == 0
        and Decimal(str(child.get("total_fees") or "0")) == 0
        and int(child.get("number_of_fills") or 0) == 0
    )
    receipt: dict[str, Any] = {
        "schema_version": "1",
        "status": "v15r5_to_v15r6_no_overlap_proven",
        "transition_mode": "one_exact_sigterm_zero_restarts",
        "controlled_plan_sha256": confirmed_plan_sha256,
        "predecessor_plan_sha256": rejected["plan_sha256"],
        "predecessor_runtime_process_identity": identity,
        "predecessor_signal": "SIGTERM",
        "predecessor_signal_claim": signal_claim,
        "predecessor_signal_attempt_count": 1,
        "predecessor_restart_attempt_count": 0,
        "predecessor_process_absent": True,
        "admin_port_8787_free": port.get("free") is True,
        "competitor_pid": port.get("competitor_pid"),
        "pre_signal_stable_artifact_hashes": stable_v15r5_artifact_hashes(
            rejected
        ),
        "pre_signal_parent_authority_loss_semantic_projection": deepcopy(
            rejected["parent_authority_loss_semantic_projection"]
        ),
        "post_signal_final_mutable_artifact_hashes": (
            final_mutable_artifact_hashes()
        ),
        "exact_child_open_zero_fill": exact_child,
        "child_readback": child,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _require(
        receipt["admin_port_8787_free"] is True
        and receipt["competitor_pid"] is None
        and receipt["exact_child_open_zero_fill"] is True,
        "v15r6_transition_final_gate_failed",
    )
    receipt["transition_sha256"] = transition_hash(receipt)
    _require(
        set(receipt) == V15R6_TRANSITION_FIELDS,
        "v15r6_transition_fields_mismatch",
    )
    transition_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    base._write_owner_only_exclusive_json(
        transition_path,
        receipt,
        exists_blocker="v15r6_transition_evidence_already_exists",
    )
    return receipt


def validate_v15r6_transition_receipt(
    plan: Mapping[str, Any],
    *,
    expected_hash: str,
    transition: Mapping[str, Any],
) -> None:
    rejected = dict(plan.get("rejected_v15r5_execution_binding") or {})
    receipt = dict(transition)
    final_hashes = dict(
        receipt.get("post_signal_final_mutable_artifact_hashes") or {}
    )
    signal_claim = dict(receipt.get("predecessor_signal_claim") or {})
    child = dict(receipt.get("child_readback") or {})
    validate_v15r6_signal_claim(plan, signal_claim)
    try:
        recorded_at = datetime.fromisoformat(str(receipt.get("recorded_at") or ""))
        valid = bool(
            set(receipt) == V15R6_TRANSITION_FIELDS
            and receipt.get("schema_version") == "1"
            and receipt.get("status") == "v15r5_to_v15r6_no_overlap_proven"
            and receipt.get("transition_mode")
            == "one_exact_sigterm_zero_restarts"
            and receipt.get("controlled_plan_sha256") == expected_hash
            == plan.get("plan_sha256")
            and receipt.get("predecessor_plan_sha256")
            == rejected.get("plan_sha256")
            and receipt.get("predecessor_runtime_process_identity")
            == rejected.get("runtime_process_identity")
            and receipt.get("predecessor_signal") == "SIGTERM"
            and signal_claim.get("claim_sha256")
            == signal_claim_hash(signal_claim)
            and receipt.get("predecessor_signal_attempt_count") == 1
            and receipt.get("predecessor_restart_attempt_count") == 0
            and receipt.get("predecessor_process_absent") is True
            and receipt.get("admin_port_8787_free") is True
            and receipt.get("competitor_pid") is None
            and receipt.get("pre_signal_stable_artifact_hashes")
            == stable_v15r5_artifact_hashes(rejected)
            and receipt.get(
                "pre_signal_parent_authority_loss_semantic_projection"
            )
            == rejected.get("parent_authority_loss_semantic_projection")
            and set(final_hashes)
            == {"parent_authority_loss", "runtime_log", "sentinel"}
            and all(
                len(str(value)) == 64
                and all(character in "0123456789abcdef" for character in str(value))
                for value in final_hashes.values()
            )
            and receipt.get("exact_child_open_zero_fill") is True
            and child == rejected.get("child_readback")
            and recorded_at.tzinfo is not None
            and secrets.compare_digest(
                str(receipt.get("transition_sha256") or ""),
                transition_hash(receipt),
            )
        )
    except (TypeError, ValueError):
        valid = False
    _require(valid, "v15r6_transition_evidence_invalid")


def authorize_v15r6_execution(
    plan_path: Path,
    *,
    expected_hash: str,
    frozen_plan: Mapping[str, Any],
    transition: Mapping[str, Any],
    now: datetime | None = None,
    marker_path: Path = MARKER_PATH,
    placement_ledger_path: Path = PLACEMENT_LEDGER_PATH,
    cancel_ledger_path: Path = CANCEL_LEDGER_PATH,
    backend_claim_log_path: Path = BACKEND_CLAIM_LOG_PATH,
    handoff_path: Path = HANDOFF_PATH,
    signal_claim_path: Path = SIGNAL_CLAIM_PATH,
) -> dict[str, Any]:
    plan = v15r5._json(plan_path, "v15r6_execution_plan")
    _require(plan == dict(frozen_plan), "v15r6_execution_plan_file_changed")
    current = now or datetime.now(timezone.utc)
    validate_v15r6_plan_structure(
        plan,
        expected_hash=expected_hash,
        now=current,
    )
    validate_v15r6_transition_receipt(
        plan,
        expected_hash=expected_hash,
        transition=transition,
    )
    signal_claim = v15r5._json(
        signal_claim_path,
        "v15r6_predecessor_signal_claim",
    )
    _require(
        signal_claim == dict(transition.get("predecessor_signal_claim") or {}),
        "v15r6_predecessor_signal_claim_file_mismatch",
    )
    validate_v15r6_signal_claim(plan, signal_claim)
    _require(
        all(
            not os.path.lexists(path)
            for path in (
                marker_path,
                placement_ledger_path,
                cancel_ledger_path,
                backend_claim_log_path,
                handoff_path,
            )
        ),
        "v15r6_execution_authority_already_consumed",
    )
    registered = {
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
        "root_client_order_id": ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": CHILD_CLIENT_ORDER_ID,
        "placement_attempt_maximum": 0,
        "root_placement_maximum": 0,
        "child_placement_maximum": 0,
        "cancel_command_maximum": 1,
        "placement_ledger_path": str(placement_ledger_path),
        "cancel_ledger_path": str(cancel_ledger_path),
        "backend_claim_log_path": str(backend_claim_log_path),
        "handoff_path": str(handoff_path),
        "registered_at": current.isoformat(),
        "process_id": os.getpid(),
    }
    marker_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    base._write_owner_only_exclusive_json(
        marker_path,
        registered,
        exists_blocker="v15r6_marker_already_exists",
    )
    for path, blocker in (
        (placement_ledger_path, "v15r6_placement_ledger_create_failed"),
        (cancel_ledger_path, "v15r6_cancel_ledger_create_failed"),
        (backend_claim_log_path, "v15r6_backend_claim_log_create_failed"),
    ):
        v15r5._exclusive_empty(path, blocker)
    return registered


def build_v15r6_cancel_admission_context(
    plan: Mapping[str, Any], *, plan_sha256: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    return v15r5.build_v15r3_cancel_admission_context(
        plan, plan_sha256=plan_sha256
    )


def write_v15r6_cancel_proof_handoff(
    handoff_path: Path,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    context: Mapping[str, Any],
    proofs: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    expected, _ = build_v15r6_cancel_admission_context(
        plan, plan_sha256=plan_sha256
    )
    cancel = dict(plan["cancel_command"])
    _require(dict(context) == expected, "v15r6_handoff_context_mismatch")
    _require(
        proofs.get("approval_id") == cancel["approval_snapshot_id"]
        and bool(proofs.get("admission_audit_id"))
        and proofs.get("cap_guard_decision_id")
        == cancel["cap_guard_decision_id"]
        and proofs.get("reconciliation_plan_id")
        == cancel["reconciliation_plan_id"],
        "v15r6_handoff_proof_mismatch",
    )
    handoff = {
        "schema_version": "1",
        "authority": AUTHORITY_KIND,
        "plan_sha256": plan_sha256,
        "batch_id": plan["batch_id"],
        "root_client_order_id": ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": CHILD_CLIENT_ORDER_ID,
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
        handoff_path,
        handoff,
        exists_blocker="v15r6_handoff_already_exists",
    )
    return handoff


def write_v15r6_exact_proofs(
    runtime: base.AdminRuntime,
    *,
    plan: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, str]:
    cancel = dict(plan["cancel_command"])
    return base.write_proof_chain(
        runtime,
        label="v15r6-child-cancel",
        context=context,
        wallet_available=Decimal("0"),
        max_notional=Decimal("0"),
        command_kind="child_cancel",
        cancel=True,
        approval_id=str(cancel["approval_snapshot_id"]),
        cap_guard_decision_id=str(cancel["cap_guard_decision_id"]),
        reconciliation_plan_id=str(cancel["reconciliation_plan_id"]),
        approval_expires_at=str(plan["expires_at"]),
    )


def set_v15r6_cancel_only_service(
    runtime: base.AdminRuntime, *, enabled: bool
) -> dict[str, Any]:
    label = "enabled" if enabled else "disabled"
    notional_cap = base.decimal_text(CHILD_REFERENCE_CAP) if enabled else "0"
    if enabled:
        runtime.live_service_enable_attempted = True
        runtime.live_service_may_be_enabled = True
        runtime.live_service_disable_proven = False
    else:
        runtime.live_service_disable_attempted = True
    body = {
        "decision_id": f"v15r6-cancel-only-{label}-{uuid4()}",
        "status": "passed" if enabled else "blocked",
        "requested_service_status": (
            "approval_required" if enabled else "live_disabled"
        ),
        "service_enabled": enabled,
        "target_module_id": "spot_operations",
        "account_family": "coinbase_retail_test",
        "venue_scope": "coinbase_advanced_trade",
        "intx_applicability": "not_applicable",
        "product_scope": [PRODUCT_ID],
        "deployment_ref": str(runtime.confirmed_plan["backend_commit"]),
        "runtime_configuration_ref": str(runtime.state_dir),
        "decision_reason": (
            "Enable one schema-24 verified-exchange-id cancel of the exact "
            "existing first child."
            if enabled
            else "Disable V15R6 cancel-only service at transition or closeout."
        ),
        "live_coinbase_execution_approved": enabled,
        "max_submitted_notional_usdc": notional_cap,
        "max_executed_notional_usdc": notional_cap,
    }
    _, response, _ = runtime.request(
        "POST",
        "/admin/live-execution/service-decisions",
        headers=runtime.headers(
            idempotency_key=f"idem-v15r6-cancel-service-{label}-{uuid4()}",
            operator_intent=f"record_v15r6_cancel_service_{label}",
            role=base.ADMIN_ROLE,
        ),
        body=body,
        expected={200},
    )
    decision = dict(response.get("decision") or {})
    _require(
        decision.get("resolver_eligible") is enabled
        and decision.get("max_submitted_notional_usdc") == notional_cap
        and decision.get("max_executed_notional_usdc") == notional_cap,
        f"v15r6_cancel_service_{label}_mismatch",
    )
    runtime.live_service_may_be_enabled = enabled
    runtime.live_service_disable_proven = not enabled
    return decision


def v15r6_post_boundary_runtime_decision(
    runtime: Any,
    plan: Mapping[str, Any],
) -> str | None:
    """Detect a durable nonterminal response without inventing a claim outcome."""

    path = Path(runtime.state_dir) / "idempotency.jsonl"
    if not os.path.lexists(path):
        return None
    rows = v15r5._jsonl(path, "v15r6_monitor_idempotency")
    expected_key = str(dict(plan.get("cancel_command") or {}).get("idempotency_key") or "")
    matches = [row for row in rows if row.get("idempotency_key") == expected_key]
    _require(len(matches) <= 1, "v15r6_monitor_duplicate_idempotency_record")
    if not matches:
        return None
    response = dict(matches[0].get("response") or {})
    if response.get("live_exchange_submitted") is not True:
        return None
    if response.get("status") == "rejected":
        return "operator_cancel_rejected_active_child_reconciliation_only"
    if response.get("status") not in {"accepted", "rejected"}:
        return "operator_cancel_ambiguous_reconciliation_only"
    return None


def stop_v15r6_runtime_without_forced_kill(runtime: Any) -> dict[str, Any]:
    """Stop only with SIGTERM; preserve any runtime that does not exit."""

    process = runtime.process
    if process is None:
        return {
            "runtime_process_started": False,
            "runtime_process_shutdown_proven": True,
            "runtime_preserved_for_reconciliation": False,
            "runtime_forced_kill_attempted": False,
        }
    if process.poll() is not None:
        if runtime.log_handle is not None:
            runtime.log_handle.close()
        return {
            "runtime_process_started": True,
            "runtime_process_shutdown_proven": True,
            "runtime_exit_code": process.returncode,
            "runtime_preserved_for_reconciliation": False,
            "runtime_forced_kill_attempted": False,
        }
    if not runtime.exchange_safe_to_shutdown:
        if runtime.log_handle is not None:
            runtime.log_handle.close()
        return {
            "runtime_process_started": True,
            "runtime_process_shutdown_proven": False,
            "runtime_pid": process.pid,
            "runtime_preserved_for_reconciliation": True,
            "runtime_forced_kill_attempted": False,
        }
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        if runtime.log_handle is not None:
            runtime.log_handle.close()
        return {
            "runtime_process_started": True,
            "runtime_process_shutdown_proven": False,
            "runtime_pid": process.pid,
            "runtime_sigterm_timeout": True,
            "runtime_preserved_for_reconciliation": True,
            "runtime_forced_kill_attempted": False,
        }
    if runtime.log_handle is not None:
        runtime.log_handle.close()
    return {
        "runtime_process_started": True,
        "runtime_process_shutdown_proven": True,
        "runtime_exit_code": process.returncode,
        "runtime_preserved_for_reconciliation": False,
        "runtime_forced_kill_attempted": False,
    }


def _with_controlled_execution_lease(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with base.ControlledExecutionLease():
            return function(*args, **kwargs)

    return wrapped


@_with_controlled_execution_lease
def execute_v15r6_plan(
    *, plan_path: Path, confirmed_plan_sha256: str
) -> dict[str, Any]:
    """Transition once, expose one UI cancel, and monitor its durable claim."""

    _require(plan_path == PLAN_PATH, "v15r6_execute_plan_file_not_fixed")
    frozen_plan = v15r5._json(plan_path, "v15r6_execution_plan")
    validate_v15r6_plan_structure(
        frozen_plan,
        expected_hash=confirmed_plan_sha256,
    )
    transition = transition_v15r5_runtime(
        frozen_plan,
        confirmed_plan_sha256=confirmed_plan_sha256,
        transition_path=RUNTIME_PATH,
    )
    registered = authorize_v15r6_execution(
        plan_path,
        expected_hash=confirmed_plan_sha256,
        frozen_plan=frozen_plan,
        transition=transition,
    )
    runtime = base.AdminRuntime(
        portfolio_id=TEST_PORTFOLIO_ID,
        confirmed_plan=frozen_plan,
        confirmed_plan_hash=confirmed_plan_sha256,
        global_batch_marker=MARKER_PATH,
        attempt_ledger_path=PLACEMENT_LEDGER_PATH,
        controlled_v15_plan_path=plan_path,
        controlled_v15_handoff_path=HANDOFF_PATH,
        controlled_v15_claim_log_path=BACKEND_CLAIM_LOG_PATH,
    )
    terminal_closeout = False
    summary: dict[str, Any] = {
        "status": "running",
        "authority": registered,
        "transition": transition,
    }
    cleanup: dict[str, Any] = {}
    try:
        runtime.start()
        runtime.wait_until_mutations_ready()
        v15r5._assert_v15r3_zero_sdk_calls(runtime)
        context, cancel_body = build_v15r6_cancel_admission_context(
            frozen_plan, plan_sha256=confirmed_plan_sha256
        )
        proofs = write_v15r6_exact_proofs(
            runtime,
            plan=frozen_plan,
            context=context,
        )
        handoff = write_v15r6_cancel_proof_handoff(
            HANDOFF_PATH,
            plan=frozen_plan,
            plan_sha256=confirmed_plan_sha256,
            context=context,
            proofs=proofs,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        cancel_path = (
            f"/orders/{ROOT_CLIENT_ORDER_ID}/fill-follow-up/child-cancel"
        )
        _, readiness, _ = runtime.request(
            "GET",
            f"{cancel_path}/readiness",
            headers=runtime.headers(role="auditor"),
            params={"controlled_plan_sha256": confirmed_plan_sha256},
            expected={200},
        )
        _require(
            readiness.get("ready") is True
            and readiness.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
            and readiness.get("child_client_order_id") == CHILD_CLIENT_ORDER_ID,
            "v15r6_cancel_readiness_blocked",
        )
        _require(
            not v15r5._jsonl(PLACEMENT_LEDGER_PATH, "v15r6_placement_ledger")
            and not v15r5._jsonl(CANCEL_LEDGER_PATH, "v15r6_cancel_ledger")
            and not v15r5._jsonl(
                BACKEND_CLAIM_LOG_PATH, "v15r6_backend_claim_log"
            ),
            "v15r6_claim_or_placement_present_before_operator",
        )
        set_v15r6_cancel_only_service(runtime, enabled=True)
        base.preview_admission(runtime, context)
        runtime.exchange_safe_to_shutdown = False
        progress = {
            "status": "awaiting_operator_ui_root_scoped_cancel",
            "root_client_order_id": ROOT_CLIENT_ORDER_ID,
            "child_client_order_id": CHILD_CLIENT_ORDER_ID,
            "child_exchange_order_id_evidence": CHILD_EXCHANGE_ORDER_ID,
            "exchange_cancel_submission_identity": (
                EXCHANGE_CANCEL_SUBMISSION_IDENTITY
            ),
            "controlled_plan_sha256": confirmed_plan_sha256,
            "readiness_url": (
                f"{base.BASE_URL}{cancel_path}/readiness?"
                f"controlled_plan_sha256={confirmed_plan_sha256}"
            ),
            "cancel_url": f"{base.BASE_URL}{cancel_path}",
            "idempotency_key": dict(frozen_plan["cancel_command"])[
                "idempotency_key"
            ],
            "correlation_id": dict(frozen_plan["cancel_command"])[
                "correlation_id"
            ],
            "operator_intent": CANCEL_OPERATOR_INTENT,
            "actor_id": ACTOR_ID,
            "actor_roles": list(ACTOR_ROLES),
            "request_body": cancel_body,
            "runner_cancel_post_submitted": False,
            "runner_cancel_claim_acquired": False,
            "placement_attempt_count": 0,
            "root_placement_authorized": False,
            "child_placement_authorized": False,
            "runtime_pid": runtime.process.pid if runtime.process else None,
            "state_dir": str(runtime.state_dir),
            "plan_expires_at": frozen_plan["expires_at"],
            "child_cancel_handoff": handoff,
        }
        progress_path = runtime.state_dir / "v15r6-operator-ui-cancel-handoff.json"
        base._replace_owner_only_json(progress_path, progress)
        print(json.dumps(progress, sort_keys=True), flush=True)
        monitor_rest_client = base.hydrate_test_credentials()
        expires_at = datetime.fromisoformat(str(frozen_plan["expires_at"]))
        next_child_read = 0.0
        while True:
            v15r5._assert_v15r3_zero_sdk_calls(runtime)
            backend_rows = v15._read_v15_backend_cancel_claim_records(
                BACKEND_CLAIM_LOG_PATH
            )
            decision = v15r5.v15r3_operator_monitor_decision(
                v15r5._jsonl(PLACEMENT_LEDGER_PATH, "v15r6_placement_ledger"),
                v15r5._jsonl(CANCEL_LEDGER_PATH, "v15r6_cancel_ledger"),
                backend_rows,
                expected_identity=v15r5.v15r3_backend_claim_identity(
                    frozen_plan, plan_sha256=confirmed_plan_sha256
                ),
            )
            if decision == "awaiting_operator_ui_root_scoped_cancel" and len(
                backend_rows
            ) == 2:
                decision = (
                    v15r6_post_boundary_runtime_decision(runtime, frozen_plan)
                    or decision
                )
            if decision == "verify_terminal_closeout":
                _require(
                    len(backend_rows) == 3,
                    "v15r6_cancel_claim_triplet_missing",
                )
                rest_client = base.hydrate_test_credentials()
                terminal = base.exact_exchange_order(
                    rest_client, CHILD_EXCHANGE_ORDER_ID
                )
                v15.validate_v15_explicit_zero_fill(terminal)
                _require(
                    str(terminal.get("status") or "").upper()
                    in {"CANCELLED", "CANCELED"},
                    "v15r6_child_terminal_zero_fill_unproven",
                )
                cancelled_chain = base._validate_cancelled_child_chain(
                    runtime,
                    root_plan={
                        "root_client_order_id": ROOT_CLIENT_ORDER_ID,
                        "child_client_order_id": CHILD_CLIENT_ORDER_ID,
                    },
                    exchange_order_id=CHILD_EXCHANGE_ORDER_ID,
                )
                active = base.prove_stable_authoritative_active_zero(
                    rest_client, expected_portfolio_id=TEST_PORTFOLIO_ID
                )
                _require(
                    active.get("stable_zero") is True,
                    "v15r6_final_active_zero_unproven",
                )
                set_v15r6_cancel_only_service(runtime, enabled=False)
                runtime.exchange_safe_to_shutdown = True
                terminal_closeout = True
                summary.update(
                    {
                        "status": "passed",
                        "cancel_command_count": 1,
                        "backend_cancel_claim_event_count": 3,
                        "child_terminal_status": str(
                            terminal.get("status") or ""
                        ).upper(),
                        "cancelled_child_chain": cancelled_chain,
                        "final_active_spot_order_count": 0,
                        "runner_cancel_post_submitted": False,
                    }
                )
                break
            if decision != "awaiting_operator_ui_root_scoped_cancel":
                try:
                    summary["latest_child_readback"] = (
                        v15r5.validate_v15r3_waiting_child_readback(
                            base.exact_exchange_order(
                                monitor_rest_client, CHILD_EXCHANGE_ORDER_ID
                            )
                        )
                    )
                except ProofFailure as exc:
                    summary["latest_child_readback_failure"] = str(exc)
                summary["status"] = decision
                break
            current = datetime.now(timezone.utc)
            if current >= expires_at:
                set_v15r6_cancel_only_service(runtime, enabled=False)
                summary["status"] = (
                    "plan_expired_active_child_reconciliation_only"
                )
                break
            if not backend_rows and time.monotonic() >= next_child_read:
                try:
                    waiting_child = v15r5.validate_v15r3_waiting_child_readback(
                        base.exact_exchange_order(
                            monitor_rest_client, CHILD_EXCHANGE_ORDER_ID
                        )
                    )
                except ProofFailure as exc:
                    set_v15r6_cancel_only_service(runtime, enabled=False)
                    summary.update(
                        {
                            "status": "critical_child_drift_reconciliation_only",
                            "critical_failure": str(exc),
                        }
                    )
                    break
                summary["latest_waiting_child_readback"] = waiting_child
                next_child_read = time.monotonic() + 2.0
            time.sleep(0.5)
    finally:
        if runtime.live_service_may_be_enabled:
            try:
                set_v15r6_cancel_only_service(runtime, enabled=False)
            except Exception as exc:
                cleanup["live_service_disable_error"] = (
                    f"{type(exc).__name__}:{exc}"
                )
                runtime.exchange_safe_to_shutdown = False
        cleanup.update(stop_v15r6_runtime_without_forced_kill(runtime))
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
        terminal_closeout
        or cleanup.get("runtime_preserved_for_reconciliation") is True,
        "v15r6_nonterminal_runtime_not_preserved",
    )
    return summary


def approval_text(plan: Mapping[str, Any]) -> str:
    return (
        f"APPROVE plan {plan['plan_sha256']} for exactly 1 "
        "root-client_order_id-bound child-cancel attempt using the "
        "authoritative exchange order_id resolved from the sealed child "
        "client_order_id as the sole exchange submission identity, with 0 "
        "client_order_id exchange submissions, 0 fallback calls, 0 retries, "
        "0 root placement attempts, 0 child placement attempts, exactly 1 "
        "predecessor runtime SIGTERM attempt, 0 predecessor restart attempts, "
        "and 0 forced-kill attempts, including an immutable pre-signal attempt "
        "claim, read-only transition validation, "
        "creation of its marker, empty ledgers, proof handoff, temporary "
        "cancel-only service enablement capped at 2.00 USDC submitted and "
        "executed notional, and a no-overlap replacement runtime under the "
        "12.00 USDC slice-local cap."
    )


def prepare_v15r6_plan(
    *,
    plan_path: Path = PLAN_PATH,
    marker_path: Path = MARKER_PATH,
    placement_ledger_path: Path = PLACEMENT_LEDGER_PATH,
    cancel_ledger_path: Path = CANCEL_LEDGER_PATH,
    backend_claim_log_path: Path = BACKEND_CLAIM_LOG_PATH,
    handoff_path: Path = HANDOFF_PATH,
    runtime_path: Path = RUNTIME_PATH,
    signal_claim_path: Path = SIGNAL_CLAIM_PATH,
    now: datetime | None = None,
    require_clean_environment: bool = True,
) -> dict[str, Any]:
    """Prepare only the owner-only plan; create no execution authority."""

    if require_clean_environment:
        _require(
            _git("rev-list", "--left-right", "--count", "HEAD...origin/main")
            == "0\t0"
            and not _git("status", "--porcelain", "--untracked-files=no"),
            "v15r6_backend_not_clean_and_synced",
        )
        _require(
            _git(
                "rev-list", "--left-right", "--count", "HEAD...origin/main",
                cwd=FRONTEND_ROOT,
            )
            == "0\t0"
            and not _git(
                "status", "--porcelain", "--untracked-files=no",
                cwd=FRONTEND_ROOT,
            ),
            "v15r6_frontend_not_clean_and_synced",
        )
    _require(
        all(
            not os.path.lexists(path)
            for path in (
                plan_path,
                marker_path,
                placement_ledger_path,
                cancel_ledger_path,
                backend_claim_log_path,
                handoff_path,
                runtime_path,
                signal_claim_path,
            )
        ),
        "v15r6_prepare_path_already_exists",
    )
    rejected = load_rejected_v15r5_execution_binding()
    source_plan = v15r5._json(
        REJECTED_V15R5_PATHS["plan"], "v15r6_source_v15r5_plan"
    )
    local = v15r5.read_local_active_child_binding()
    plan = build_v15r6_plan(
        source_plan,
        local_active_child=local,
        rejected_v15r5_execution_binding=rejected,
        now=now,
    )
    validate_v15r6_plan_structure(
        plan,
        expected_hash=str(plan["plan_sha256"]),
        now=now,
    )
    plan_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    base._write_owner_only_exclusive_json(
        plan_path, plan, exists_blocker="v15r6_plan_path_already_exists"
    )
    return {
        "status": "prepared",
        "plan_path": str(plan_path),
        "plan_sha256": plan["plan_sha256"],
        "expires_at": plan["expires_at"],
        "placement_attempt_count": 0,
        "root_placement_maximum": 0,
        "child_placement_maximum": 0,
        "cancel_command_maximum": 1,
        "predecessor_runtime_signal_attempt_maximum": 1,
        "predecessor_runtime_restart_attempt_maximum": 0,
        "exchange_cancel_submission_identity": (
            EXCHANGE_CANCEL_SUBMISSION_IDENTITY
        ),
        "live_coinbase_orders_ran": False,
        "live_coinbase_read_ran": True,
        "marker_written": False,
        "ledger_written": False,
        "handoff_written": False,
        "runtime_started": False,
        "predecessor_signal_sent": False,
        "predecessor_signal_claim_written": False,
        "approval_text": approval_text(plan),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-v15r6-plan", action="store_true")
    mode.add_argument("--execute-v15r6-plan", action="store_true")
    parser.add_argument("--plan-file")
    parser.add_argument("--confirm-plan-sha256")
    args = parser.parse_args(argv)
    if args.prepare_v15r6_plan:
        print(json.dumps(prepare_v15r6_plan(), sort_keys=True))
        return 0
    _require(bool(args.plan_file), "v15r6_execute_plan_file_required")
    _require(
        Path(str(args.plan_file)).resolve() == PLAN_PATH,
        "v15r6_execute_plan_file_not_fixed",
    )
    _require(bool(args.confirm_plan_sha256), "v15r6_execute_plan_hash_required")
    print(
        json.dumps(
            execute_v15r6_plan(
                plan_path=PLAN_PATH,
                confirmed_plan_sha256=str(args.confirm_plan_sha256),
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
