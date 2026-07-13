"""Prepare or execute the sealed V15R4 cancel-only recovery authority.

V15R4 cannot place a root or child. Preparation binds both the completed V15R2
shutdown and the terminal failed V15R3 proof runtime, validates the local
active-child identity and authoritative Coinbase readback, then creates only
an owner-only schema-22 plan. Preparation exposes no runtime, marker, ledger,
handoff, process signal, or mutation request. Execution is a separate
hash-confirmed mode, and the runner itself never submits the operator cancel.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import signal
import secrets
import socket
import stat
import subprocess
import time
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg2
import requests

from tools import run_controlled_admin_spot_child_cancel_recovery as v15r2
from tools import run_controlled_admin_spot_child_cancel_slice as v15
from tools import run_controlled_admin_spot_root_child_batch as base


ProofFailure = base.ProofFailure
PRODUCT_ID = base.PRODUCT_ID
PROFILE_LABEL = base.PROFILE_LABEL
TEST_PORTFOLIO_ID = base.TEST_PORTFOLIO_ID
ROOT_REFERENCE_CAP = Decimal("9.99")
CHILD_REFERENCE_CAP = Decimal("2.00")
SLICE_REFERENCE_CAP = Decimal("12.00")
ROOT_ACTUAL_REFERENCE_NOTIONAL = Decimal("1.0075796583")
ACTIVE_CHILD_REFERENCE_NOTIONAL = Decimal("1.7049248762")
AGGREGATE_REFERENCE_NOTIONAL = Decimal("2.7125045345")
CHILD_BASE_SIZE = Decimal("0.00001583")
CHILD_LIMIT_PRICE = Decimal("107702.14")
PLAN_TTL = timedelta(minutes=120)
PLAN_SCHEMA_VERSION = "22"
AUTHORITY_KIND = "selected_chain_child_cancel_recovery_v15r4"
ACTOR_ID = "operator-controlled-spot-proof"
ACTOR_ROLES = ["trader"]
CANCEL_OPERATOR_INTENT = v15r2.CHILD_CANCEL_OPERATOR_INTENT

ROOT_CLIENT_ORDER_ID = v15r2.R1_ROOT_CLIENT_ORDER_ID
ROOT_EXCHANGE_ORDER_ID = v15r2.R1_ROOT_EXCHANGE_ORDER_ID
CHILD_CLIENT_ORDER_ID = v15r2.R1_CHILD_CLIENT_ORDER_ID
CHILD_EXCHANGE_ORDER_ID = "5bb903af-3c6e-4d0a-bd73-087f0dfead89"
R2_PLAN_SHA256 = "0b9ab483459a986ad05200a6740a0de6dca63b6c5da197572c952ce8aef524c2"
R2_BATCH_ID = "bb88b375-66a3-5562-87bd-1e88ebceecda"
R2_CANCEL_IDEMPOTENCY_KEY = "cd7713ea-5841-5c8a-9aea-161a2eb32e31"
R2_CANCEL_CORRELATION_ID = "cd79b000-9c19-58dd-9ce0-537d4823bdec"
R2_CANCEL_CLAIM_ID = "46341b9c-efd0-5451-805d-efd2d1cd2709"
R2_CANCEL_APPROVAL_ID = "6b7375fb-6d38-5164-90f0-ec81ec75c780"
R2_CANCEL_ADMISSION_AUDIT_ID = "aef54633-6cd4-4ad9-892b-7740aa27b45a"
R2_CANCEL_CAP_ID = "6e678aff-e044-5962-9895-720b5ec528dc"
R2_CANCEL_RECONCILIATION_ID = "f24753f6-eac6-5207-9806-1b5502c0d474"
R2_PROOF_PAYLOAD_HASH = "47ea2b0bdec88367454689f1a287b28bc17a353e8362a71473a9e84da39ced05"
R2_FAILED_CANCEL_PAYLOAD_HASH = "5875e395e1692d1c82c5fded7a3e80f75c568d449df9825a2593c1dfeb4769c6"
R2_FAILED_CANCEL_AUDIT_ID = "60018f6a-745d-4a43-9990-82b29928bbe8"
FAILED_V15R3_PLAN_SHA256 = (
    "7309ca5552796a60e57c3abb0622e913da97ce5b6450dd7eb3633c4754e12b25"
)
FAILED_V15R3_PLAN_BYTES_SHA256 = (
    "f9b7e51eed13dfd1f303322c451e9d89b40633cdef6080a7b251cf784854ea6b"
)
FAILED_V15R3_BATCH_ID = "ed13aab8-99aa-59c2-9104-b4f02cf66dc1"
FAILED_V15R3_BACKEND_COMMIT = "677e96bbf6c375bc7f9f31ae94d043515189d1b3"
FAILED_V15R3_RUNNER_SHA256 = (
    "dab6f528f8d24052971c6376fcb2e3be9e3d410b384b165214b3112402beec83"
)
FAILED_V15R3_CANCEL_IDS = frozenset(
    {
        "fba7a3ed-420e-52b9-a4c4-e3a6bbc9d865",
        "3512e3bd-5cb1-5442-8a01-4ebdc71a77a9",
        "7bc45910-0144-59a4-a006-df23ee327ebc",
        "ef26324a-c9fe-52d9-9f24-54d23fa943b7",
        "8cc92c40-def3-5c34-80c0-b40345a5bdd2",
        "30e91103-79dc-5b1c-9843-e4be3ccc2963",
    }
)
FAILED_PROOF_PLAN_SHA256 = (
    "189c338ebd49afb1013a0c2e54e6a228dc6e4e57707b5f0ef7487f63b5cf2302"
)
FAILED_PROOF_PLAN_BYTES_SHA256 = (
    "dfcc3c12d8cc18c6808abc48cc8125cc24cf7494f79a5f8dff33246b25b5f6e7"
)
FAILED_PROOF_BATCH_ID = "12613395-b8d6-5fdd-9dc7-de3086de1a26"
FAILED_PROOF_BACKEND_COMMIT = "aeea2205a18df36019572785b1c948775c53962d"
FAILED_PROOF_RUNNER_SHA256 = (
    "655964ffc3efd5701ecf39a3c2a695a394dc1421bda6a38e6f528a049de3d474"
)
FAILED_PROOF_CANCEL_IDS = frozenset(
    {
        "9df5c983-2f13-55bc-b8f1-47beed4c7ffd",
        "c26a8f8a-4a13-5fff-ba31-19155d398eff",
        "b6aa4aba-40e1-5c47-bc76-74e3de81751e",
        "8c530163-9ca8-5fdf-8227-a69ed3580b3a",
        "d675db7e-cbe4-5872-9391-0e222ad1c36d",
        "05632c40-d7d0-5fe2-8679-d360580ac6be",
    }
)
R2_CONCRETE_CANCEL_ENDPOINT = (
    f"POST /api/v1/orders/{ROOT_CLIENT_ORDER_ID}/fill-follow-up/child-cancel"
)
R2_USED_IDS = frozenset(
    {
        R2_BATCH_ID,
        R2_CANCEL_IDEMPOTENCY_KEY,
        R2_CANCEL_CORRELATION_ID,
        R2_CANCEL_CLAIM_ID,
        R2_CANCEL_APPROVAL_ID,
        R2_CANCEL_ADMISSION_AUDIT_ID,
        R2_CANCEL_CAP_ID,
        R2_CANCEL_RECONCILIATION_ID,
        FAILED_V15R3_BATCH_ID,
        *FAILED_V15R3_CANCEL_IDS,
        FAILED_PROOF_BATCH_ID,
        *FAILED_PROOF_CANCEL_IDS,
    }
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT.parent / "coinbase-frontend"
R2_STATE_DIR = ROOT / "artifacts/controlled-root-child-batch-20260713T022339Z-301d5d02"
REGISTRY_DIR = Path("/var/tmp/coinbase-admin-controlled-spot-root-child-batches")
PLAN_PATH = Path(
    "/home/ec2-user/.local/state/"
    "coinbase-controlled-spot-child-cancel-v15r4-20260713.plan.json"
)
FAILED_V15R3_PLAN_PATH = Path(
    "/home/ec2-user/.local/state/"
    "coinbase-controlled-spot-child-cancel-v15r3-20260713.plan."
    f"{FAILED_V15R3_PLAN_SHA256}.failed-post-shutdown-port-proof.json"
)
MARKER_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r4-20260713.authority.json"
)
PLACEMENT_LEDGER_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r4-20260713.placements.jsonl"
)
CANCEL_LEDGER_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r4-20260713.cancel-command.jsonl"
)
BACKEND_CLAIM_LOG_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r4-20260713.backend-claims.jsonl"
)
HANDOFF_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r4-20260713.handoff.json"
)
RUNTIME_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r4-20260713.runtime.json"
)

FAILED_PROOF_STATE_DIR = (
    ROOT / "artifacts/controlled-root-child-batch-20260713T060242Z-0559cb04"
)
FAILED_PROOF_REGISTRY_PREFIX = (
    "test-profile-btc-usdc-selected-child-cancel-v15r3-20260713"
)
FAILED_PROOF_ARTIFACT_PATHS: dict[str, Path] = {
    "plan": Path(
        "/home/ec2-user/.local/state/"
        "coinbase-controlled-spot-child-cancel-v15r3-20260713.plan.json"
    ),
    "marker": REGISTRY_DIR / f"{FAILED_PROOF_REGISTRY_PREFIX}.authority.json",
    "placement_ledger": (
        REGISTRY_DIR / f"{FAILED_PROOF_REGISTRY_PREFIX}.placements.jsonl"
    ),
    "cancel_ledger": (
        REGISTRY_DIR / f"{FAILED_PROOF_REGISTRY_PREFIX}.cancel-command.jsonl"
    ),
    "backend_claim_log": (
        REGISTRY_DIR / f"{FAILED_PROOF_REGISTRY_PREFIX}.backend-claims.jsonl"
    ),
    "runtime_transition": (
        REGISTRY_DIR / f"{FAILED_PROOF_REGISTRY_PREFIX}.runtime.json"
    ),
    "runtime_authority": FAILED_PROOF_STATE_DIR / "runtime-child-authority.json",
    "runtime_authority_used": (
        FAILED_PROOF_STATE_DIR / "runtime-child-authority.used.json"
    ),
    "sentinel": FAILED_PROOF_STATE_DIR / "sdk-boundary-sentinel.json",
    "runtime_log": FAILED_PROOF_STATE_DIR / "embedded-runtime.log",
    "runtime_pid": FAILED_PROOF_STATE_DIR / "embedded-runtime.pid",
    "live_service": FAILED_PROOF_STATE_DIR / "live_service.jsonl",
    "idempotency": FAILED_PROOF_STATE_DIR / "idempotency.jsonl",
    "audit": FAILED_PROOF_STATE_DIR / "audit.jsonl",
}
FAILED_PROOF_ARTIFACT_HASHES: dict[str, str] = {
    "plan": FAILED_PROOF_PLAN_BYTES_SHA256,
    "marker": "208cec96134f5037f868ecfc456849468a01c4b4fb2c72b20e11a13b66e7da2d",
    "placement_ledger": hashlib.sha256(b"").hexdigest(),
    "cancel_ledger": hashlib.sha256(b"").hexdigest(),
    "backend_claim_log": hashlib.sha256(b"").hexdigest(),
    "runtime_transition": (
        "646464a2e25bd5d805923831b4deb6c281987978f8407be23bae50ce892d2d62"
    ),
    "runtime_authority": (
        "0124c650bf6eac10f329d7009aafdcece91ca0b00b24ac000580602c5cce6035"
    ),
    "runtime_authority_used": (
        "e9f27439e34e3899336811d76796f461cdc440234c05a2d61510c8d83782b4c9"
    ),
    "sentinel": (
        "f97cebc12863187950cf79484e8072f9e2677a0761a9f266e71e88d004393ee7"
    ),
    "runtime_log": (
        "ba92371461254c029da456fb828277612813e9821682831ebf189ab63fcf6987"
    ),
    "runtime_pid": (
        "8617db95ac48c2cfbf3792b4c44a75b1da3c03c97b22962947ecc25ee49c4d6b"
    ),
    "live_service": (
        "9cacf4ad3bfd2117d58f1751024541f3eae591148b4caf5fb0268199922407c1"
    ),
    "idempotency": (
        "7a8ed1acff361593daccf0c98633d42bad940cc959d5b9aaa067e3f2a75fd79c"
    ),
    "audit": (
        "7535a16a3dc09cf36817c1479bba00af5ce02a1085a3d62858a83c0500d9b74b"
    ),
}
FAILED_PROOF_ABSENT_ARTIFACT_PATHS: dict[str, Path] = {
    "handoff": REGISTRY_DIR / f"{FAILED_PROOF_REGISTRY_PREFIX}.handoff.json",
    "approval_log": FAILED_PROOF_STATE_DIR / "approvals.jsonl",
    "cap_guard_log": FAILED_PROOF_STATE_DIR / "cap_guard.jsonl",
    "reconciliation_log": FAILED_PROOF_STATE_DIR / "reconciliation.jsonl",
    "operator_progress": (
        FAILED_PROOF_STATE_DIR / "v15r3-operator-ui-cancel-handoff.json"
    ),
    "parent_authority_loss": FAILED_PROOF_STATE_DIR / "parent-authority-loss.json",
    "failure_summary": FAILED_PROOF_STATE_DIR / "controlled-batch-failure.json",
    "cleanup_summary": FAILED_PROOF_STATE_DIR / "controlled-batch-cleanup.json",
    "batch_summary": FAILED_PROOF_STATE_DIR / "controlled-batch-summary.json",
}
FAILED_PROOF_RECORD_HASHES: dict[str, str] = {
    "live_service": (
        "776acce37f5c8d24528f40c6fb0ab71f29cb4906ddb3ae64ed8da789922d4fdd"
    ),
    "idempotency": (
        "ab9eb9d03afa50cdb8ca6f348bffdd7f423b98a6b33813895e2282423f3f204f"
    ),
    "audit": "f04d446ca55febe29099b67ad38af3f1f2d7bb5e21cb0105ce91a7de47d50d0d",
}
FAILED_PROOF_APPROVAL_ID = (
    "controlled-child-cancel-v15r3-0f2f1920-e333-4048-9999-6d7ee6be665f"
)
FAILED_PROOF_TRANSITION_SHA256 = (
    "ef1f4cfa34f7b879b429051aae676f4003412dc2523782f7098c714a3568bb39"
)
FAILED_PROOF_PARENT_PROCESS_ID = 671522
FAILED_PROOF_RUNTIME_PROCESS_ID = 671573

R2_ARTIFACT_PATHS: dict[str, str] = {
    "plan_path": (
        "/home/ec2-user/.local/state/"
        "coinbase-controlled-spot-child-cancel-v15r2-20260713.plan.json"
    ),
    "marker_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.authority.json"
    ),
    "placement_ledger_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.placements.jsonl"
    ),
    "cancel_ledger_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.cancel-command.jsonl"
    ),
    "backend_claim_log_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.backend-claims.jsonl"
    ),
    "handoff_path": str(
        REGISTRY_DIR
        / "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713.handoff.json"
    ),
    "sentinel_path": str(R2_STATE_DIR / "sdk-boundary-sentinel.json"),
    "progress_path": str(R2_STATE_DIR / "v15r2-operator-ui-cancel-handoff.json"),
    "idempotency_path": str(R2_STATE_DIR / "idempotency.jsonl"),
    "audit_path": str(R2_STATE_DIR / "audit.jsonl"),
    "runtime_authority_path": str(R2_STATE_DIR / "runtime-child-authority.json"),
    "runtime_authority_used_path": str(
        R2_STATE_DIR / "runtime-child-authority.used.json"
    ),
    "runtime_pid_path": str(R2_STATE_DIR / "embedded-runtime.pid"),
}
R2_EXPECTED_HASHES: dict[str, str] = {
    "plan_bytes_sha256": "e4fd504a27eb999b42f0f5f7c2f4faa682dd75ac5c0811574d6e6937ca481c89",
    "marker_bytes_sha256": "a818a49d68ebf3908a1f7d08861b1afd82d12b18128e997bdbdeb8bd3e79af1f",
    "placement_ledger_bytes_sha256": "bf59dd45661d0e12c8cc3a0fda694e31b3f40a29dce05d123598d5178681ec13",
    "cancel_ledger_bytes_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "backend_claim_log_bytes_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "handoff_bytes_sha256": "d0b8c04bbf09baabba242fa4a605ff19a6786361955481ff1ff736da3a55c4af",
    "sentinel_bytes_sha256": "e93fe5902917f9765f6ab706cac400ad89807e3851cf465d24fe68c3595a9978",
    "progress_bytes_sha256": "8aec5d1b208df79231c14d32da034ec3bc3c4e96f34c7a72cc58186327fd8254",
    "successful_child_record_canonical_sha256": "63f586fedf05871a5476d0b4cf32e31a6298dde966730c45a2fc9d41f055b96d",
    "failed_cancel_record_canonical_sha256": "0c9b56e031b26c6d314c9a7335c49b68042137aff2ebcfa234665df18eb66773",
    "failed_cancel_audit_canonical_sha256": "645ad1950a300a8caf3ecd4110d95e6f201daff55716eda216141544e5eb1b2e",
    "runtime_authority_bytes_sha256": "169b4ca1489406351b1c3c51d68e11775fe49a0a6e53eb7f2b6470b9266aa4e5",
    "runtime_authority_used_bytes_sha256": "7a308f8ea028462f95304897fc210b2eae3d67770064bbfaf65a4f48d292f261",
    "runtime_pid_bytes_sha256": "c518928a7dcb53c2686c6f3b6ac666e2de687e18e22e1e7d5d0c897d0c1297da",
}

COMPLETED_SHUTDOWN_ARTIFACT_PATHS: dict[str, Path] = {
    "parent_loss": R2_STATE_DIR / "parent-authority-loss.json",
    "sentinel": R2_STATE_DIR / "sdk-boundary-sentinel.json",
    "progress": R2_STATE_DIR / "v15r2-operator-ui-cancel-handoff.json",
    "live_service": R2_STATE_DIR / "live_service.jsonl",
    "audit": R2_STATE_DIR / "audit.jsonl",
    "idempotency": R2_STATE_DIR / "idempotency.jsonl",
}
COMPLETED_SHUTDOWN_ARTIFACT_HASHES: dict[str, str] = {
    "parent_loss": "6e7a71090150bc87f6d38a4173404f1f74a66c509fa63b638ba6ae7239a7b241",
    "sentinel": "4ee558ad45baca579307ed758d2d8f89878416c42e9ac789e4d0bff7315afe2c",
    "progress": "0754ecb215423e169fedd3111a1598fd2ed3c54381d5c4754dbb2a0505280f0a",
    "live_service": "8483b3b4ca9bf97bd3c9fdc93fe12e1ec9ebc2bc9fab8b9a48aa83a97d2e89df",
    "audit": "09c135ce57f2dfb377bda4910224c5954fecde491297e89f4882a57596e29e16",
    "idempotency": "be41c6b79b8e03661141c513219bc8945a86a0f3ef025abdf411980b6febb65c",
}
COMPLETED_SHUTDOWN_RECORD_HASHES = {
    "transition_disable_decision": (
        "42d61427795772ac24771b3a25a053b679fe3a54ae40767b21407e29073dbe2c"
    ),
    "transition_disable_idempotency": (
        "3009d0625c92f89ceaad7b669b1357969ece4633c6e878b189e6376e113b61cc"
    ),
    "transition_disable_audit": (
        "7fc777c09925fedfa108f00daf0560866c8470b6e74c8853cabc1ddcc0240137"
    ),
}

V15R3_PLAN_FIELDS = frozenset(
    {
        "schema_version", "authority_kind", "approval_id", "batch_id",
        "created_at", "expires_at", "backend_commit", "frontend_commit",
        "runner_sha256", "v15r2_active_child_binding",
        "local_active_child_binding", "profile_label", "portfolio_id",
        "product_id", "placement_attempt_count", "placement_attempt_schedule",
        "root_placement_maximum", "child_placement_maximum",
        "cancel_command_maximum", "root_placement_authorized",
        "child_placement_authorized", "root_reference_cap_usdc",
        "child_reference_cap_usdc", "slice_reference_cap_usdc",
        "root_actual_reference_notional_usdc",
        "active_child_reference_notional_usdc",
        "aggregate_reference_notional_usdc", "planned_reference_notional_usdc",
        "root_evidence", "child", "child_evidence", "actor_id", "actor_roles",
        "child_cancel_operator_intent", "cancel_command", "retry_authorized",
        "substitution_authorized", "later_child_authorized",
        "browser_derives_child_identity", "exchange_order_id_evidence_only",
        "exchange_order_id_fallback_authorized", "plan_sha256",
    }
)
V15R4_PLAN_FIELDS = V15R3_PLAN_FIELDS | {"failed_v15r3_execution_binding"}
V15R3_RECOVERED_TRANSITION_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "recovery_status",
        "transition_mode",
        "controlled_plan_sha256",
        "failed_plan_sha256",
        "failed_plan_bytes_sha256",
        "failed_batch_id",
        "failed_backend_commit",
        "failed_runner_sha256",
        "r2_plan_sha256",
        "r2_parent_process_identity",
        "r2_runtime_process_identity",
        "predecessor_signal_attempt_count",
        "predecessor_signal_authorized",
        "predecessor_restart_authorized",
        "both_predecessor_processes_absent",
        "both_predecessor_exact_identities_absent",
        "terminal_artifact_paths",
        "terminal_artifact_hashes",
        "transition_disable_record_hashes",
        "admin_port_8787_free",
        "competitor_pid",
        "exact_child_open_zero_fill",
        "child_readback",
        "recorded_at",
        "transition_sha256",
    }
)
V15R4_RECOVERED_TRANSITION_FIELDS = V15R3_RECOVERED_TRANSITION_FIELDS | {
    "failed_v15r3_execution_binding"
}


def _require(condition: bool, blocker: str) -> None:
    if not condition:
        raise ProofFailure(blocker)


def _canonical_json_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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


def _file_sha256(path: Path, blocker: str, *, allow_public_read: bool = False) -> str:
    _require_safe_regular_file(path, blocker, allow_public_read=allow_public_read)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, blocker: str, *, allow_public_read: bool = False) -> dict[str, Any]:
    _require_safe_regular_file(path, blocker, allow_public_read=allow_public_read)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofFailure(f"{blocker}_malformed") from exc
    _require(isinstance(value, dict), f"{blocker}_not_object")
    return dict(value)


def _text(path: Path, blocker: str, *, allow_public_read: bool = False) -> str:
    _require_safe_regular_file(path, blocker, allow_public_read=allow_public_read)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProofFailure(f"{blocker}_malformed") from exc


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
    return str(
        uuid5(
            NAMESPACE_URL,
            f"coinbase://selected-child-cancel-v15r4/{batch_id}/{purpose}",
        )
    )


def cancel_command_ids(plan: Mapping[str, Any]) -> tuple[str, ...]:
    cancel = dict(plan.get("cancel_command") or {})
    return tuple(
        str(cancel.get(field) or "")
        for field in (
            "idempotency_key", "correlation_id", "claim_id",
            "approval_snapshot_id",
            "cap_guard_decision_id", "reconciliation_plan_id",
        )
    )


def expected_failed_v15r3_execution_binding() -> dict[str, Any]:
    """Return the exact terminal failed-proof lineage sealed into V15R4."""

    return {
        "schema_version": "1",
        "status": "failed_v15r3_proof_runtime_bound_no_live_cancel",
        "plan_sha256": FAILED_PROOF_PLAN_SHA256,
        "plan_bytes_sha256": FAILED_PROOF_PLAN_BYTES_SHA256,
        "approval_id": FAILED_PROOF_APPROVAL_ID,
        "batch_id": FAILED_PROOF_BATCH_ID,
        "backend_commit": FAILED_PROOF_BACKEND_COMMIT,
        "runner_sha256": FAILED_PROOF_RUNNER_SHA256,
        "cancel_command_ids": {
            "idempotency_key": "9df5c983-2f13-55bc-b8f1-47beed4c7ffd",
            "correlation_id": "c26a8f8a-4a13-5fff-ba31-19155d398eff",
            "claim_id": "b6aa4aba-40e1-5c47-bc76-74e3de81751e",
            "approval_snapshot_id": "8c530163-9ca8-5fdf-8227-a69ed3580b3a",
            "cap_guard_decision_id": "d675db7e-cbe4-5872-9391-0e222ad1c36d",
            "reconciliation_plan_id": "05632c40-d7d0-5fe2-8679-d360580ac6be",
        },
        "artifact_paths": {
            key: str(value) for key, value in FAILED_PROOF_ARTIFACT_PATHS.items()
        },
        "artifact_hashes": dict(FAILED_PROOF_ARTIFACT_HASHES),
        "absent_artifact_paths": {
            key: str(value)
            for key, value in FAILED_PROOF_ABSENT_ARTIFACT_PATHS.items()
        },
        "transition_sha256": FAILED_PROOF_TRANSITION_SHA256,
        "parent_process_id": FAILED_PROOF_PARENT_PROCESS_ID,
        "runtime_process_id": FAILED_PROOF_RUNTIME_PROCESS_ID,
        "root_sdk_call_count": 0,
        "child_sdk_call_count": 0,
        "cancel_route_call_count": 0,
        "semantic_claim_count": 0,
        "exchange_cancel_boundary_call_count": 0,
        "failure_stage": "approval_proof_request",
        "failure_http_status": 422,
        "live_service_enabled": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "successor_binder_signal_attempt_count": 0,
        "successor_binder_restart_attempt_count": 0,
        "both_processes_absent": True,
        "admin_port_8787_free": True,
        "child_readback": {
            "client_order_id": CHILD_CLIENT_ORDER_ID,
            "exchange_order_id": CHILD_EXCHANGE_ORDER_ID,
            "status": "OPEN",
            "filled_size": "0",
            "filled_value": "0",
            "total_fees": "0",
            "number_of_fills": 0,
            "reference_notional_usdc": base.decimal_text(
                ACTIVE_CHILD_REFERENCE_NOTIONAL
            ),
        },
    }


def _read_process_identity(process_id: int) -> dict[str, Any]:
    proc = Path(f"/proc/{process_id}")
    try:
        metadata = proc.stat()
        raw_stat = (proc / "stat").read_text(encoding="utf-8")
        raw_cmdline = (proc / "cmdline").read_bytes()
        cwd = os.readlink(proc / "cwd")
    except OSError as exc:
        raise ProofFailure("v15r2_process_identity_unavailable") from exc
    close_paren = raw_stat.rfind(")")
    fields = raw_stat[close_paren + 2 :].split() if close_paren > 0 else []
    _require(
        len(fields) >= 20 and fields[19].isdigit() and raw_cmdline,
        "v15r2_process_identity_malformed",
    )
    return {
        "process_id": process_id,
        "start_identity": fields[19],
        "uid": metadata.st_uid,
        "cwd": cwd,
        "cwd_sha256": hashlib.sha256(cwd.encode("utf-8")).hexdigest(),
        "cmdline_sha256": hashlib.sha256(raw_cmdline).hexdigest(),
    }


def same_kernel_process_identity(
    sealed: Mapping[str, Any], observed: Mapping[str, Any]
) -> bool:
    """Match the immutable Linux task identity, not mutable exec/cwd evidence."""

    sealed_start = str(sealed.get("start_identity") or "")
    observed_start = str(observed.get("start_identity") or "")
    return (
        int(sealed.get("process_id") or 0) > 1
        and int(sealed.get("process_id") or 0)
        == int(observed.get("process_id") or 0)
        and bool(sealed_start)
        and sealed_start == observed_start
    )


def _process_id_absent(process_id: int) -> bool:
    return not Path(f"/proc/{process_id}").exists()


def load_v15r2_failed_cancel_binding() -> dict[str, Any]:
    """Bind the one R2 child placement and rejected no-live cancel attempt."""

    paths = {key: Path(value) for key, value in R2_ARTIFACT_PATHS.items()}
    hash_keys = {
        "plan_path": "plan_bytes_sha256",
        "marker_path": "marker_bytes_sha256",
        "placement_ledger_path": "placement_ledger_bytes_sha256",
        "cancel_ledger_path": "cancel_ledger_bytes_sha256",
        "backend_claim_log_path": "backend_claim_log_bytes_sha256",
        "handoff_path": "handoff_bytes_sha256",
        "sentinel_path": "sentinel_bytes_sha256",
        "progress_path": "progress_bytes_sha256",
        "runtime_authority_path": "runtime_authority_bytes_sha256",
        "runtime_authority_used_path": "runtime_authority_used_bytes_sha256",
        "runtime_pid_path": "runtime_pid_bytes_sha256",
    }
    _require(
        all(
            _file_sha256(
                paths[path_key],
                f"v15r2_{path_key}",
                allow_public_read=path_key == "runtime_pid_path",
            )
            == R2_EXPECTED_HASHES[hash_key]
            for path_key, hash_key in hash_keys.items()
        ),
        "v15r2_artifact_hash_mismatch",
    )
    plan = _json(paths["plan_path"], "v15r2_plan")
    marker = _json(paths["marker_path"], "v15r2_marker")
    placements = _jsonl(paths["placement_ledger_path"], "v15r2_placement_ledger")
    cancel_rows = _jsonl(paths["cancel_ledger_path"], "v15r2_cancel_ledger")
    claim_rows = _jsonl(paths["backend_claim_log_path"], "v15r2_backend_claim_log")
    handoff = _json(paths["handoff_path"], "v15r2_handoff")
    sentinel = _json(paths["sentinel_path"], "v15r2_sentinel")
    progress = _json(paths["progress_path"], "v15r2_progress")
    runtime_authority = _json(
        paths["runtime_authority_path"], "v15r2_runtime_authority"
    )
    runtime_authority_used = _json(
        paths["runtime_authority_used_path"], "v15r2_runtime_authority_used"
    )
    _require_safe_regular_file(
        paths["runtime_pid_path"],
        "v15r2_runtime_pid",
        allow_public_read=True,
    )
    idempotency_rows = _jsonl(
        paths["idempotency_path"], "v15r2_idempotency", allow_public_read=True
    )
    audit_rows = _jsonl(
        paths["audit_path"], "v15r2_audit", allow_public_read=True
    )

    _require(
        plan.get("schema_version") == "20"
        and plan.get("authority_kind") == "selected_chain_child_cancel_recovery_v15r2"
        and plan.get("plan_sha256") == R2_PLAN_SHA256
        and plan.get("batch_id") == R2_BATCH_ID
        and plan.get("portfolio_id") == TEST_PORTFOLIO_ID
        and plan.get("product_id") == PRODUCT_ID
        and plan.get("placement_attempt_count") == 1
        and plan.get("placement_attempt_schedule") == ["child"]
        and plan.get("root_placement_maximum") == 0
        and plan.get("child_placement_maximum") == 1
        and plan.get("cancel_command_maximum") == 1
        and Decimal(str(plan.get("root_actual_reference_notional_usdc")))
        == ROOT_ACTUAL_REFERENCE_NOTIONAL
        and Decimal(str(plan.get("slice_reference_cap_usdc")))
        == SLICE_REFERENCE_CAP,
        "v15r2_plan_scope_mismatch",
    )
    source_root = dict(plan.get("root_evidence") or {})
    source_child = dict(plan.get("child") or {})
    source_cancel = dict(plan.get("cancel_command") or {})
    _require(
        source_root.get("client_order_id") == ROOT_CLIENT_ORDER_ID
        and source_root.get("exchange_order_id") == ROOT_EXCHANGE_ORDER_ID
        and source_root.get("status") == "FILLED"
        and source_child.get("client_order_id") == CHILD_CLIENT_ORDER_ID
        and source_child.get("parent_client_order_id") == ROOT_CLIENT_ORDER_ID
        and source_cancel.get("idempotency_key") == R2_CANCEL_IDEMPOTENCY_KEY
        and source_cancel.get("correlation_id") == R2_CANCEL_CORRELATION_ID
        and source_cancel.get("claim_id") == R2_CANCEL_CLAIM_ID
        and source_cancel.get("approval_snapshot_id") == R2_CANCEL_APPROVAL_ID
        and source_cancel.get("cap_guard_decision_id") == R2_CANCEL_CAP_ID
        and source_cancel.get("reconciliation_plan_id")
        == R2_CANCEL_RECONCILIATION_ID,
        "v15r2_identity_scope_mismatch",
    )
    _require(
        marker.get("authority") == "selected_chain_child_cancel_recovery_v15r2"
        and marker.get("plan_sha256") == R2_PLAN_SHA256
        and marker.get("batch_id") == R2_BATCH_ID
        and marker.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
        and marker.get("child_client_order_id") == CHILD_CLIENT_ORDER_ID
        and marker.get("placement_attempt_maximum") == 1
        and marker.get("root_placement_maximum") == 0
        and marker.get("child_placement_maximum") == 1
        and marker.get("cancel_command_maximum") == 1
        and len(placements) == 1,
        "v15r2_marker_or_placement_mismatch",
    )
    placement = placements[0]
    exact_tuple = dict(placement.get("exact_order_tuple") or {})
    _require(
        placement.get("sequence") == 1
        and placement.get("attempt_kind") == "child"
        and placement.get("plan_sha256") == R2_PLAN_SHA256
        and placement.get("batch_id") == R2_BATCH_ID
        and placement.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
        and placement.get("client_order_id") == CHILD_CLIENT_ORDER_ID
        and exact_tuple.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
        and exact_tuple.get("client_order_id") == CHILD_CLIENT_ORDER_ID
        and exact_tuple.get("product_id") == PRODUCT_ID
        and Decimal(str(exact_tuple.get("base_size"))) == CHILD_BASE_SIZE
        and Decimal(str(exact_tuple.get("limit_price"))) == CHILD_LIMIT_PRICE
        and Decimal(str(exact_tuple.get("base_size")))
        * Decimal(str(exact_tuple.get("limit_price")))
        == ACTIVE_CHILD_REFERENCE_NOTIONAL,
        "v15r2_exact_child_tuple_mismatch",
    )
    _require(not cancel_rows and not claim_rows, "v15r2_cancel_or_claim_log_not_empty")
    _require(
        handoff.get("authority") == "selected_chain_child_cancel_recovery_v15r2"
        and handoff.get("plan_sha256") == R2_PLAN_SHA256
        and handoff.get("batch_id") == R2_BATCH_ID
        and handoff.get("actor_id") == ACTOR_ID
        and handoff.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
        and handoff.get("child_client_order_id") == CHILD_CLIENT_ORDER_ID
        and handoff.get("idempotency_key") == R2_CANCEL_IDEMPOTENCY_KEY
        and handoff.get("correlation_id") == R2_CANCEL_CORRELATION_ID
        and handoff.get("payload_hash") == R2_PROOF_PAYLOAD_HASH,
        "v15r2_handoff_mismatch",
    )
    _require(
        sentinel.get("installed") is True
        and sentinel.get("wrapper_identity_proven") is True
        and sentinel.get("phase") == "child_place_limit_order_returned"
        and sentinel.get("root_create_order_call_count") == 0
        and sentinel.get("root_create_order_maximum") == 0
        and sentinel.get("root_sdk_inflight") is False
        and sentinel.get("child_place_limit_order_call_count") == 1
        and sentinel.get("child_place_limit_order_maximum") == 1
        and sentinel.get("child_sdk_inflight") is False
        and sentinel.get("denied_call_count") == 0
        and sentinel.get("critical_failure") is False
        and sentinel.get("error") is None,
        "v15r2_sentinel_mismatch",
    )
    _require(
        progress.get("status") == "awaiting_operator_ui_root_scoped_cancel"
        and progress.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
        and progress.get("child_client_order_id") == CHILD_CLIENT_ORDER_ID
        and progress.get("controlled_plan_sha256") == R2_PLAN_SHA256
        and progress.get("idempotency_key") == R2_CANCEL_IDEMPOTENCY_KEY
        and progress.get("correlation_id") == R2_CANCEL_CORRELATION_ID
        and progress.get("runner_cancel_post_submitted") is False
        and progress.get("runner_cancel_claim_acquired") is False
        and progress.get("root_placement_authorized") is False,
        "v15r2_progress_mismatch",
    )
    parent_pid = int(marker.get("process_id") or 0)
    runtime_pid = int(progress.get("runtime_pid") or 0)
    try:
        recorded_runtime_pid = int(
            paths["runtime_pid_path"].read_text(encoding="utf-8").strip()
        )
    except (OSError, ValueError) as exc:
        raise ProofFailure("v15r2_runtime_pid_malformed") from exc
    parent_identity = _read_process_identity(parent_pid)
    runtime_identity = _read_process_identity(runtime_pid)
    _require(
        parent_pid > 1
        and runtime_pid > 1
        and runtime_pid == recorded_runtime_pid
        and parent_identity.get("uid") == os.getuid()
        and runtime_identity.get("uid") == os.getuid()
        and parent_identity.get("cwd") == str(ROOT)
        and runtime_identity.get("cwd") == str(ROOT)
        and runtime_authority.get("plan_sha256") == R2_PLAN_SHA256
        and runtime_authority.get("batch_id") == R2_BATCH_ID
        and int(runtime_authority.get("parent_pid") or 0) == parent_pid
        and runtime_authority.get("parent_start_identity")
        == parent_identity.get("start_identity")
        and runtime_authority.get("state_dir") == str(R2_STATE_DIR)
        and runtime_authority_used.get("plan_sha256") == R2_PLAN_SHA256
        and runtime_authority_used.get("batch_id") == R2_BATCH_ID
        and int(runtime_authority_used.get("parent_pid") or 0) == parent_pid
        and int(runtime_authority_used.get("child_pid") or 0) == runtime_pid,
        "v15r2_process_binding_mismatch",
    )

    successful = [
        row
        for row in idempotency_rows
        if _canonical_json_sha256(row)
        == R2_EXPECTED_HASHES["successful_child_record_canonical_sha256"]
    ]
    failed = [
        row
        for row in idempotency_rows
        if _canonical_json_sha256(row)
        == R2_EXPECTED_HASHES["failed_cancel_record_canonical_sha256"]
    ]
    failed_audits = [
        row
        for row in audit_rows
        if _canonical_json_sha256(row)
        == R2_EXPECTED_HASHES["failed_cancel_audit_canonical_sha256"]
    ]
    _require(
        len(successful) == 1 and len(failed) == 1 and len(failed_audits) == 1,
        "v15r2_bound_record_hash_mismatch",
    )
    success_response = dict(successful[0].get("response") or {})
    success_data = dict(success_response.get("data") or {})
    submission = dict(success_data.get("submission_attempt") or {})
    readback = dict(success_data.get("submission_readback") or {})
    matched = dict(readback.get("matched_order") or {})
    _require(
        successful[0].get("status") == "accepted"
        and success_response.get("status") == "accepted"
        and success_response.get("live_exchange_submitted") is True
        and success_response.get("live_coinbase_orders_ran") is True
        and submission.get("placed_client_order_id") == CHILD_CLIENT_ORDER_ID
        and submission.get("exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
        and submission.get("controlled_plan_sha256") == R2_PLAN_SHA256
        and Decimal(str(submission.get("reference_notional_usdc")))
        == ACTIVE_CHILD_REFERENCE_NOTIONAL
        and readback.get("authoritative") is True
        and readback.get("exact_identity_match") is True
        and readback.get("client_order_id") == CHILD_CLIENT_ORDER_ID
        and readback.get("exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
        and str(readback.get("authoritative_status") or "").upper() == "OPEN"
        and Decimal(str(matched.get("filled_size") or "0")) == 0
        and Decimal(str(matched.get("filled_value") or "0")) == 0
        and int(matched.get("number_of_fills") or 0) == 0,
        "v15r2_successful_child_record_mismatch",
    )
    failed_row = failed[0]
    failed_response = dict(failed_row.get("response") or {})
    failed_decision = dict(failed_response.get("admission_decision") or {})
    failed_audit = failed_audits[0]
    failed_audit_decision = dict(failed_audit.get("admission_decision") or {})
    _require(
        failed_row.get("idempotency_key") == R2_CANCEL_IDEMPOTENCY_KEY
        and failed_row.get("payload_hash") == R2_FAILED_CANCEL_PAYLOAD_HASH
        and failed_row.get("client_order_id") == ROOT_CLIENT_ORDER_ID
        and failed_row.get("status") == "not_implemented"
        and failed_row.get("actor_id") == ACTOR_ID
        and failed_row.get("endpoint") == R2_CONCRETE_CANCEL_ENDPOINT
        and failed_response.get("status") == "not_implemented"
        and failed_response.get("audit_id") == R2_FAILED_CANCEL_AUDIT_ID
        and failed_response.get("failure_stage") == "approval"
        and failed_response.get("live_exchange_submitted") is False
        and failed_response.get("live_coinbase_orders_ran") is False
        and failed_decision.get("payload_hash") == R2_FAILED_CANCEL_PAYLOAD_HASH
        and failed_decision.get("allowed") is False
        and failed_audit.get("audit_id") == R2_FAILED_CANCEL_AUDIT_ID
        and failed_audit.get("actor_id") == ACTOR_ID
        and failed_audit.get("endpoint") == R2_CONCRETE_CANCEL_ENDPOINT
        and failed_audit.get("idempotency_key") == R2_CANCEL_IDEMPOTENCY_KEY
        and failed_audit.get("status") == "not_implemented"
        and failed_audit.get("failure_stage") == "approval"
        and failed_audit.get("live_exchange_submitted") is False
        and failed_audit.get("live_coinbase_orders_ran") is False
        and failed_audit_decision.get("payload_hash")
        == R2_FAILED_CANCEL_PAYLOAD_HASH
        and failed_audit_decision.get("allowed") is False,
        "v15r2_failed_cancel_not_no_live",
    )
    return {
        "r2_plan_sha256": R2_PLAN_SHA256,
        "r2_batch_id": R2_BATCH_ID,
        "root_client_order_id": ROOT_CLIENT_ORDER_ID,
        "root_exchange_order_id": ROOT_EXCHANGE_ORDER_ID,
        "child_client_order_id": CHILD_CLIENT_ORDER_ID,
        "child_exchange_order_id": CHILD_EXCHANGE_ORDER_ID,
        "r2_placement_attempt_count": 1,
        "r2_root_sdk_call_count": 0,
        "r2_child_sdk_call_count": 1,
        "r2_cancel_command_count": 0,
        "child_status": "OPEN",
        "child_zero_fill_proven": True,
        "child_reference_notional_usdc": base.decimal_text(
            ACTIVE_CHILD_REFERENCE_NOTIONAL
        ),
        "aggregate_reference_notional_usdc": base.decimal_text(
            AGGREGATE_REFERENCE_NOTIONAL
        ),
        "r2_proof_payload_hash": R2_PROOF_PAYLOAD_HASH,
        "failed_cancel_idempotency_key": R2_CANCEL_IDEMPOTENCY_KEY,
        "failed_cancel_correlation_id": R2_CANCEL_CORRELATION_ID,
        "failed_cancel_payload_hash": R2_FAILED_CANCEL_PAYLOAD_HASH,
        "failed_cancel_audit_id": R2_FAILED_CANCEL_AUDIT_ID,
        "failed_cancel_http_status": 501,
        "failed_cancel_status": "not_implemented",
        "failed_cancel_live_exchange_submitted": False,
        "failed_cancel_live_coinbase_orders_ran": False,
        "failed_cancel_semantic_claim_acquired": False,
        "failed_cancel_exchange_boundary_called": False,
        "cancel_ledgers_empty": True,
        "r2_state_dir": str(R2_STATE_DIR),
        "r2_parent_process_identity": parent_identity,
        "r2_runtime_process_identity": runtime_identity,
        "source_paths": dict(R2_ARTIFACT_PATHS),
        "source_hashes": dict(R2_EXPECTED_HASHES),
    }


def _record_with_canonical_hash(
    rows: list[Mapping[str, Any]], *, expected_hash: str, blocker: str
) -> dict[str, Any]:
    matches = [
        dict(row)
        for row in rows
        if _canonical_json_sha256(dict(row)) == expected_hash
    ]
    _require(len(matches) == 1, blocker)
    return matches[0]


def load_v15r3_completed_shutdown_binding() -> dict[str, Any]:
    """Bind the completed R2 shutdown without replaying either signal."""

    _require(
        _file_sha256(FAILED_V15R3_PLAN_PATH, "v15r3_failed_transition_plan")
        == FAILED_V15R3_PLAN_BYTES_SHA256,
        "v15r3_failed_transition_plan_hash_mismatch",
    )
    failed_plan = _json(
        FAILED_V15R3_PLAN_PATH, "v15r3_failed_transition_plan"
    )
    _require(
        set(failed_plan) == V15R3_PLAN_FIELDS
        and failed_plan.get("plan_sha256") == FAILED_V15R3_PLAN_SHA256
        and plan_hash(failed_plan) == FAILED_V15R3_PLAN_SHA256
        and failed_plan.get("batch_id") == FAILED_V15R3_BATCH_ID
        and failed_plan.get("backend_commit") == FAILED_V15R3_BACKEND_COMMIT
        and failed_plan.get("runner_sha256") == FAILED_V15R3_RUNNER_SHA256
        and set(cancel_command_ids(failed_plan)) == FAILED_V15R3_CANCEL_IDS,
        "v15r3_failed_transition_plan_scope_mismatch",
    )
    r2_source = dict(failed_plan.get("v15r2_active_child_binding") or {})
    _require(
        r2_source.get("r2_plan_sha256") == R2_PLAN_SHA256
        and r2_source.get("r2_batch_id") == R2_BATCH_ID
        and r2_source.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
        and r2_source.get("child_client_order_id") == CHILD_CLIENT_ORDER_ID
        and r2_source.get("child_exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
        and r2_source.get("r2_root_sdk_call_count") == 0
        and r2_source.get("r2_child_sdk_call_count") == 1
        and r2_source.get("r2_cancel_command_count") == 0
        and r2_source.get("cancel_ledgers_empty") is True
        and r2_source.get("source_paths") == R2_ARTIFACT_PATHS
        and r2_source.get("source_hashes") == R2_EXPECTED_HASHES,
        "v15r3_failed_transition_r2_lineage_mismatch",
    )

    for name, path in COMPLETED_SHUTDOWN_ARTIFACT_PATHS.items():
        _require(
            _file_sha256(
                path,
                f"v15r3_completed_shutdown_{name}",
                allow_public_read=name in {"live_service", "audit", "idempotency"},
            )
            == COMPLETED_SHUTDOWN_ARTIFACT_HASHES[name],
            f"v15r3_completed_shutdown_{name}_hash_mismatch",
        )

    parent_loss = _json(
        COMPLETED_SHUTDOWN_ARTIFACT_PATHS["parent_loss"],
        "v15r3_completed_shutdown_parent_loss",
    )
    active = [
        dict(row)
        for row in list(parent_loss.get("authoritative_active_orders") or [])
        if isinstance(row, Mapping)
    ]
    _require(
        parent_loss.get("status")
        == "v15_parent_authority_lost_reconciliation_only"
        and parent_loss.get("plan_sha256") == R2_PLAN_SHA256
        and parent_loss.get("new_sdk_placements_denied") is True
        and parent_loss.get("new_cancel_command_authorized") is False
        and parent_loss.get("root_create_order_call_count") == 0
        and parent_loss.get("child_place_limit_order_call_count") == 1
        and parent_loss.get("root_sdk_inflight") is False
        and parent_loss.get("child_sdk_inflight") is False
        and parent_loss.get("authoritative_active_read_stable") is True
        and len(active) == 1
        and active[0].get("client_order_id") == CHILD_CLIENT_ORDER_ID
        and active[0].get("order_id") == CHILD_EXCHANGE_ORDER_ID
        and str(active[0].get("status") or "").upper() in {"OPEN", "PENDING"}
        and Decimal(str(active[0].get("filled_size") or "0")) == 0
        and Decimal(str(active[0].get("filled_value") or "0")) == 0
        and Decimal(str(active[0].get("total_fees") or "0")) == 0
        and int(active[0].get("number_of_fills") or 0) == 0
        and dict(parent_loss.get("sealed_cancel_reconciliation") or {}).get(
            "cancel_post_submitted"
        )
        is False,
        "v15r3_completed_shutdown_parent_loss_scope_mismatch",
    )
    sentinel = _json(
        COMPLETED_SHUTDOWN_ARTIFACT_PATHS["sentinel"],
        "v15r3_completed_shutdown_sentinel",
    )
    _require(
        sentinel.get("phase") == "runtime_exited"
        and sentinel.get("process_id")
        == int(dict(r2_source["r2_runtime_process_identity"])["process_id"])
        and sentinel.get("root_create_order_call_count") == 0
        and sentinel.get("root_create_order_maximum") == 0
        and sentinel.get("child_place_limit_order_call_count") == 1
        and sentinel.get("child_place_limit_order_maximum") == 1
        and sentinel.get("root_sdk_inflight") is False
        and sentinel.get("child_sdk_inflight") is False
        and sentinel.get("critical_failure") is False
        and sentinel.get("denied_call_count") == 0
        and sentinel.get("error") is None,
        "v15r3_completed_shutdown_sentinel_scope_mismatch",
    )

    live_rows = _jsonl(
        COMPLETED_SHUTDOWN_ARTIFACT_PATHS["live_service"],
        "v15r3_completed_shutdown_live_service",
        allow_public_read=True,
    )
    idempotency_rows = _jsonl(
        COMPLETED_SHUTDOWN_ARTIFACT_PATHS["idempotency"],
        "v15r3_completed_shutdown_idempotency",
        allow_public_read=True,
    )
    audit_rows = _jsonl(
        COMPLETED_SHUTDOWN_ARTIFACT_PATHS["audit"],
        "v15r3_completed_shutdown_audit",
        allow_public_read=True,
    )
    disable = _record_with_canonical_hash(
        live_rows,
        expected_hash=COMPLETED_SHUTDOWN_RECORD_HASHES[
            "transition_disable_decision"
        ],
        blocker="v15r3_completed_shutdown_disable_decision_missing",
    )
    idempotency = _record_with_canonical_hash(
        idempotency_rows,
        expected_hash=COMPLETED_SHUTDOWN_RECORD_HASHES[
            "transition_disable_idempotency"
        ],
        blocker="v15r3_completed_shutdown_disable_idempotency_missing",
    )
    audit = _record_with_canonical_hash(
        audit_rows,
        expected_hash=COMPLETED_SHUTDOWN_RECORD_HASHES[
            "transition_disable_audit"
        ],
        blocker="v15r3_completed_shutdown_disable_audit_missing",
    )
    _require(
        disable.get("status") == "blocked"
        and disable.get("requested_service_status") == "live_disabled"
        and disable.get("service_enabled") is False
        and disable.get("live_coinbase_execution_approved") is False
        and disable.get("max_submitted_notional_usdc") == "0"
        and disable.get("max_executed_notional_usdc") == "0"
        and disable.get("deployment_ref") == FAILED_V15R3_BACKEND_COMMIT
        and idempotency.get("status") == "accepted"
        and dict(idempotency.get("response") or {}).get(
            "live_exchange_submitted"
        )
        is False
        and dict(idempotency.get("response") or {}).get(
            "live_coinbase_orders_ran"
        )
        is False
        and audit.get("status") == "accepted"
        and audit.get("live_exchange_submitted") is False
        and audit.get("live_coinbase_orders_ran") is False,
        "v15r3_completed_shutdown_disable_scope_mismatch",
    )

    _require(
        _file_sha256(
            Path(R2_ARTIFACT_PATHS["cancel_ledger_path"]),
            "v15r3_completed_shutdown_r2_cancel_ledger",
        )
        == hashlib.sha256(b"").hexdigest()
        and _file_sha256(
            Path(R2_ARTIFACT_PATHS["backend_claim_log_path"]),
            "v15r3_completed_shutdown_r2_backend_claim_log",
        )
        == hashlib.sha256(b"").hexdigest(),
        "v15r3_completed_shutdown_r2_cancel_claim_present",
    )
    _require(
        all(
            not os.path.lexists(path)
            for path in (
                MARKER_PATH,
                PLACEMENT_LEDGER_PATH,
                CANCEL_LEDGER_PATH,
                BACKEND_CLAIM_LOG_PATH,
                HANDOFF_PATH,
                RUNTIME_PATH,
            )
        ),
        "v15r3_completed_shutdown_authority_artifact_present",
    )
    identities = (
        dict(r2_source["r2_parent_process_identity"]),
        dict(r2_source["r2_runtime_process_identity"]),
    )
    for identity in identities:
        process_id = int(identity["process_id"])
        if not Path(f"/proc/{process_id}").exists():
            continue
        _require(
            not same_kernel_process_identity(
                identity, _read_process_identity(process_id)
            ),
            "v15r3_completed_shutdown_predecessor_pid_present",
        )
    base.require_runtime_exclusivity(require_port_free=True)
    local = read_local_active_child_binding()
    child = read_exact_active_child_after_transition()
    return {
        "status": "v15r2_shutdown_bound_no_overlap_proven",
        "failed_plan_sha256": FAILED_V15R3_PLAN_SHA256,
        "failed_plan_bytes_sha256": FAILED_V15R3_PLAN_BYTES_SHA256,
        "failed_batch_id": FAILED_V15R3_BATCH_ID,
        "failed_backend_commit": FAILED_V15R3_BACKEND_COMMIT,
        "failed_runner_sha256": FAILED_V15R3_RUNNER_SHA256,
        "r2_source_binding": r2_source,
        "local_active_child_binding": local,
        "terminal_artifact_paths": {
            key: str(value)
            for key, value in COMPLETED_SHUTDOWN_ARTIFACT_PATHS.items()
        },
        "terminal_artifact_hashes": dict(
            COMPLETED_SHUTDOWN_ARTIFACT_HASHES
        ),
        "transition_disable_record_hashes": dict(
            COMPLETED_SHUTDOWN_RECORD_HASHES
        ),
        "both_predecessor_exact_identities_absent": True,
        "admin_port_8787_free": True,
        "child_readback": child,
    }


def load_failed_v15r3_execution_binding() -> dict[str, Any]:
    """Bind the consumed 189c runtime and prove no cancel boundary was reached."""

    public_read_artifacts = {
        "runtime_log", "runtime_pid", "live_service", "idempotency", "audit"
    }
    for name, path in FAILED_PROOF_ARTIFACT_PATHS.items():
        _require(
            _file_sha256(
                path,
                f"v15r4_failed_execution_{name}",
                allow_public_read=name in public_read_artifacts,
            )
            == FAILED_PROOF_ARTIFACT_HASHES[name],
            f"v15r4_failed_execution_{name}_hash_mismatch",
        )
    _require(
        all(
            not os.path.lexists(path)
            for path in FAILED_PROOF_ABSENT_ARTIFACT_PATHS.values()
        ),
        "v15r4_failed_execution_absent_artifact_present",
    )

    failed_plan = _json(
        FAILED_PROOF_ARTIFACT_PATHS["plan"],
        "v15r4_failed_execution_plan",
    )
    failed_cancel = dict(failed_plan.get("cancel_command") or {})
    _require(
        set(failed_plan) == V15R3_PLAN_FIELDS
        and failed_plan.get("schema_version") == "21"
        and failed_plan.get("authority_kind")
        == "selected_chain_child_cancel_recovery_v15r3"
        and failed_plan.get("plan_sha256") == FAILED_PROOF_PLAN_SHA256
        and plan_hash(failed_plan) == FAILED_PROOF_PLAN_SHA256
        and failed_plan.get("approval_id") == FAILED_PROOF_APPROVAL_ID
        and failed_plan.get("batch_id") == FAILED_PROOF_BATCH_ID
        and failed_plan.get("backend_commit") == FAILED_PROOF_BACKEND_COMMIT
        and failed_plan.get("runner_sha256") == FAILED_PROOF_RUNNER_SHA256
        and set(cancel_command_ids(failed_plan)) == FAILED_PROOF_CANCEL_IDS
        and failed_cancel.get("semantic_retry_policy")
        == "fresh_v15r3_idempotency_key_exactly_once"
        and failed_plan.get("placement_attempt_count") == 0
        and failed_plan.get("placement_attempt_schedule") == []
        and failed_plan.get("root_placement_maximum") == 0
        and failed_plan.get("child_placement_maximum") == 0
        and failed_plan.get("cancel_command_maximum") == 1
        and failed_plan.get("root_placement_authorized") is False
        and failed_plan.get("child_placement_authorized") is False
        and failed_plan.get("retry_authorized") is False,
        "v15r4_failed_execution_plan_scope_mismatch",
    )

    marker = _json(
        FAILED_PROOF_ARTIFACT_PATHS["marker"],
        "v15r4_failed_execution_marker",
    )
    _require(
        marker.get("authority")
        == "selected_chain_child_cancel_recovery_v15r3"
        and marker.get("approval_id") == FAILED_PROOF_APPROVAL_ID
        and marker.get("batch_id") == FAILED_PROOF_BATCH_ID
        and marker.get("plan_file")
        == str(FAILED_PROOF_ARTIFACT_PATHS["plan"])
        and marker.get("plan_sha256") == FAILED_PROOF_PLAN_SHA256
        and marker.get("backend_commit") == FAILED_PROOF_BACKEND_COMMIT
        and marker.get("runner_sha256") == FAILED_PROOF_RUNNER_SHA256
        and marker.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
        and marker.get("child_client_order_id") == CHILD_CLIENT_ORDER_ID
        and marker.get("placement_attempt_maximum") == 0
        and marker.get("root_placement_maximum") == 0
        and marker.get("child_placement_maximum") == 0
        and marker.get("cancel_command_maximum") == 1
        and marker.get("placement_ledger_path")
        == str(FAILED_PROOF_ARTIFACT_PATHS["placement_ledger"])
        and marker.get("cancel_ledger_path")
        == str(FAILED_PROOF_ARTIFACT_PATHS["cancel_ledger"])
        and marker.get("backend_claim_log_path")
        == str(FAILED_PROOF_ARTIFACT_PATHS["backend_claim_log"])
        and marker.get("handoff_path")
        == str(FAILED_PROOF_ABSENT_ARTIFACT_PATHS["handoff"])
        and marker.get("process_id") == FAILED_PROOF_PARENT_PROCESS_ID,
        "v15r4_failed_execution_marker_scope_mismatch",
    )

    transition = _json(
        FAILED_PROOF_ARTIFACT_PATHS["runtime_transition"],
        "v15r4_failed_execution_transition",
    )
    child = dict(transition.get("child_readback") or {})
    _require(
        set(transition) == V15R3_RECOVERED_TRANSITION_FIELDS
        and transition.get("schema_version") == "2"
        and transition.get("status") == "v15r2_to_v15r3_no_overlap_proven"
        and transition.get("recovery_status")
        == "v15r2_shutdown_bound_no_overlap_proven"
        and transition.get("transition_mode")
        == "bind_completed_predecessor_shutdown_no_signals"
        and transition.get("controlled_plan_sha256")
        == FAILED_PROOF_PLAN_SHA256
        and transition.get("predecessor_signal_attempt_count") == 0
        and transition.get("predecessor_signal_authorized") is False
        and transition.get("predecessor_restart_authorized") is False
        and transition.get("both_predecessor_processes_absent") is True
        and transition.get("both_predecessor_exact_identities_absent") is True
        and transition.get("admin_port_8787_free") is True
        and transition.get("competitor_pid") is None
        and transition.get("exact_child_open_zero_fill") is True
        and child
        == expected_failed_v15r3_execution_binding()["child_readback"]
        and transition.get("transition_sha256")
        == FAILED_PROOF_TRANSITION_SHA256
        and transition_hash(transition) == FAILED_PROOF_TRANSITION_SHA256,
        "v15r4_failed_execution_transition_scope_mismatch",
    )

    runtime_authority = _json(
        FAILED_PROOF_ARTIFACT_PATHS["runtime_authority"],
        "v15r4_failed_execution_runtime_authority",
    )
    consumed_authority = _json(
        FAILED_PROOF_ARTIFACT_PATHS["runtime_authority_used"],
        "v15r4_failed_execution_consumed_authority",
    )
    _require(
        runtime_authority.get("plan_sha256") == FAILED_PROOF_PLAN_SHA256
        and runtime_authority.get("batch_id") == FAILED_PROOF_BATCH_ID
        and runtime_authority.get("parent_pid")
        == FAILED_PROOF_PARENT_PROCESS_ID
        and runtime_authority.get("state_dir") == str(FAILED_PROOF_STATE_DIR)
        and runtime_authority.get("global_batch_marker")
        == str(FAILED_PROOF_ARTIFACT_PATHS["marker"])
        and consumed_authority.get("plan_sha256")
        == FAILED_PROOF_PLAN_SHA256
        and consumed_authority.get("batch_id") == FAILED_PROOF_BATCH_ID
        and consumed_authority.get("parent_pid")
        == FAILED_PROOF_PARENT_PROCESS_ID
        and consumed_authority.get("child_pid")
        == FAILED_PROOF_RUNTIME_PROCESS_ID
        and consumed_authority.get("global_batch_marker")
        == str(FAILED_PROOF_ARTIFACT_PATHS["marker"]),
        "v15r4_failed_execution_runtime_authority_scope_mismatch",
    )

    sentinel = _json(
        FAILED_PROOF_ARTIFACT_PATHS["sentinel"],
        "v15r4_failed_execution_sentinel",
    )
    _require(
        sentinel.get("installed") is True
        and sentinel.get("wrapper_identity_proven") is True
        and sentinel.get("phase") == "runtime_exited"
        and sentinel.get("process_id") == FAILED_PROOF_RUNTIME_PROCESS_ID
        and sentinel.get("root_create_order_call_count") == 0
        and sentinel.get("root_create_order_maximum") == 0
        and sentinel.get("root_sdk_inflight") is False
        and sentinel.get("child_place_limit_order_call_count") == 0
        and sentinel.get("child_place_limit_order_maximum") == 0
        and sentinel.get("child_sdk_inflight") is False
        and sentinel.get("denied_call_count") == 0
        and sentinel.get("critical_failure") is False
        and sentinel.get("error") is None,
        "v15r4_failed_execution_sentinel_scope_mismatch",
    )
    _require(
        not _jsonl(
            FAILED_PROOF_ARTIFACT_PATHS["placement_ledger"],
            "v15r4_failed_execution_placement_ledger",
        )
        and not _jsonl(
            FAILED_PROOF_ARTIFACT_PATHS["cancel_ledger"],
            "v15r4_failed_execution_cancel_ledger",
        )
        and not _jsonl(
            FAILED_PROOF_ARTIFACT_PATHS["backend_claim_log"],
            "v15r4_failed_execution_backend_claim_log",
        ),
        "v15r4_failed_execution_command_or_claim_present",
    )

    live_rows = _jsonl(
        FAILED_PROOF_ARTIFACT_PATHS["live_service"],
        "v15r4_failed_execution_live_service",
        allow_public_read=True,
    )
    idempotency_rows = _jsonl(
        FAILED_PROOF_ARTIFACT_PATHS["idempotency"],
        "v15r4_failed_execution_idempotency",
        allow_public_read=True,
    )
    audit_rows = _jsonl(
        FAILED_PROOF_ARTIFACT_PATHS["audit"],
        "v15r4_failed_execution_audit",
        allow_public_read=True,
    )
    live = _record_with_canonical_hash(
        live_rows,
        expected_hash=FAILED_PROOF_RECORD_HASHES["live_service"],
        blocker="v15r4_failed_execution_live_service_record_missing",
    )
    idempotency = _record_with_canonical_hash(
        idempotency_rows,
        expected_hash=FAILED_PROOF_RECORD_HASHES["idempotency"],
        blocker="v15r4_failed_execution_idempotency_record_missing",
    )
    audit = _record_with_canonical_hash(
        audit_rows,
        expected_hash=FAILED_PROOF_RECORD_HASHES["audit"],
        blocker="v15r4_failed_execution_audit_record_missing",
    )
    _require(
        len(live_rows) == len(idempotency_rows) == len(audit_rows) == 1
        and live.get("status") == "blocked"
        and live.get("requested_service_status") == "live_disabled"
        and live.get("service_enabled") is False
        and live.get("live_coinbase_execution_approved") is False
        and live.get("max_submitted_notional_usdc") == "0"
        and live.get("max_executed_notional_usdc") == "0"
        and live.get("deployment_ref") == FAILED_PROOF_BACKEND_COMMIT
        and live.get("runtime_configuration_ref") == str(FAILED_PROOF_STATE_DIR)
        and idempotency.get("status") == "accepted"
        and idempotency.get("endpoint")
        == "POST /api/v1/admin/live-execution/service-decisions"
        and dict(idempotency.get("response") or {}).get(
            "live_exchange_submitted"
        )
        is False
        and dict(idempotency.get("response") or {}).get(
            "live_coinbase_orders_ran"
        )
        is False
        and audit.get("status") == "accepted"
        and audit.get("endpoint")
        == "POST /api/v1/admin/live-execution/service-decisions"
        and audit.get("live_exchange_submitted") is False
        and audit.get("live_coinbase_orders_ran") is False,
        "v15r4_failed_execution_disabled_service_scope_mismatch",
    )
    runtime_log = _text(
        FAILED_PROOF_ARTIFACT_PATHS["runtime_log"],
        "v15r4_failed_execution_runtime_log",
        allow_public_read=True,
    )
    _require(
        'POST /api/v1/admin/live-execution/service-decisions HTTP/1.1" 200 OK'
        in runtime_log
        and 'POST /api/v1/admin/approvals/requests HTTP/1.1" 422 '
        "Unprocessable Content" in runtime_log
        and "Received SIGTERM; initiating graceful shutdown" in runtime_log
        and "Application shutdown complete." in runtime_log,
        "v15r4_failed_execution_runtime_log_scope_mismatch",
    )
    _require(
        _process_id_absent(FAILED_PROOF_PARENT_PROCESS_ID)
        and _process_id_absent(FAILED_PROOF_RUNTIME_PROCESS_ID),
        "v15r4_failed_execution_process_present",
    )
    base.require_runtime_exclusivity(require_port_free=True)
    return expected_failed_v15r3_execution_binding()


def load_current_v15r3_source_binding(
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the completed R2 shutdown and consumed V15R3 proof runtime."""

    completed = load_v15r3_completed_shutdown_binding()
    completed["failed_v15r3_execution_binding"] = (
        load_failed_v15r3_execution_binding()
    )
    return dict(completed["r2_source_binding"]), completed


def validate_local_active_child_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    binding = dict(value)
    _require(
        binding.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
        and str(binding.get("root_status") or "").upper() == "FILLED"
        and binding.get("root_exchange_order_id") == ROOT_EXCHANGE_ORDER_ID
        and bool(str(binding.get("root_correlation_id") or "").strip())
        and bool(str(binding.get("root_audit_id") or "").strip())
        and binding.get("child_client_order_id") == CHILD_CLIENT_ORDER_ID
        and str(binding.get("child_parent_status") or "").upper() == "OPEN"
        and Decimal(str(binding.get("child_size") or "0")) == CHILD_BASE_SIZE
        and Decimal(str(binding.get("child_limit_price") or "0"))
        == CHILD_LIMIT_PRICE
        and binding.get("child_exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
        and binding.get("child_correlation_id") == binding.get("root_correlation_id")
        and binding.get("child_audit_id") == binding.get("root_audit_id")
        and str(binding.get("child_stealth_status") or "").upper() == "REVEALED"
        and Decimal(str(binding.get("revealed_size") or "0")) == CHILD_BASE_SIZE
        and Decimal(str(binding.get("executed_size") or "0")) == 0
        and Decimal(str(binding.get("remaining_size") or "0")) == 0
        and binding.get("active_placement_client_order_id") == CHILD_CLIENT_ORDER_ID
        and binding.get("active_exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
        and Decimal(str(binding.get("active_exchange_price") or "0"))
        == CHILD_LIMIT_PRICE
        and binding.get("controlled_plan_sha256") == R2_PLAN_SHA256
        and binding.get("controlled_batch_id") == R2_BATCH_ID
        and Decimal(str(binding.get("reference_notional_usdc") or "0"))
        == ACTIVE_CHILD_REFERENCE_NOTIONAL
        and binding.get("direct_child_client_order_ids") == []
        and binding.get("nested_child_client_order_ids") == [],
        "v15r3_local_active_child_mismatch",
    )
    return binding


def read_local_active_child_binding() -> dict[str, Any]:
    """Read the exact active R2 child from PostgreSQL without mutation."""

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
                (ROOT_CLIENT_ORDER_ID,),
            )
            root_row = cursor.fetchone()
            cursor.execute(
                "SELECT status, size, exchange_order_id, correlation_id, audit_id, price FROM order_parent WHERE client_order_id=%s AND parent_order_id=%s",
                (CHILD_CLIENT_ORDER_ID, ROOT_CLIENT_ORDER_ID),
            )
            child_row = cursor.fetchone()
            cursor.execute(
                """SELECT status, revealed_size, executed_size,
                          anchor_repricing_state_json, remaining_size
                     FROM stealth_orders
                    WHERE stealth_order_id=%s AND parent_order_id=%s""",
                (CHILD_CLIENT_ORDER_ID, ROOT_CLIENT_ORDER_ID),
            )
            stealth_row = cursor.fetchone()
            cursor.execute(
                "SELECT client_order_id FROM order_parent WHERE parent_order_id=%s AND client_order_id<>%s ORDER BY client_order_id",
                (ROOT_CLIENT_ORDER_ID, CHILD_CLIENT_ORDER_ID),
            )
            direct_children = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute(
                "SELECT client_order_id FROM order_parent WHERE parent_order_id=%s ORDER BY client_order_id",
                (CHILD_CLIENT_ORDER_ID,),
            )
            nested_children = [str(row[0]) for row in cursor.fetchall()]
        _require(
            root_row is not None and child_row is not None and stealth_row is not None,
            "v15r3_local_active_child_row_missing",
        )
        anchor = dict(stealth_row[3] or {})
        preparation = dict(
            anchor.get("controlled_admin_first_child_reveal_preparation") or {}
        )
        return validate_local_active_child_binding(
            {
                "root_client_order_id": ROOT_CLIENT_ORDER_ID,
                "root_status": root_row[0],
                "root_exchange_order_id": root_row[1],
                "root_correlation_id": root_row[2],
                "root_audit_id": root_row[3],
                "child_client_order_id": CHILD_CLIENT_ORDER_ID,
                "child_parent_status": child_row[0],
                "child_size": base.decimal_text(Decimal(str(child_row[1]))),
                "child_limit_price": base.decimal_text(Decimal(str(child_row[5]))),
                "child_exchange_order_id": child_row[2],
                "child_correlation_id": child_row[3],
                "child_audit_id": child_row[4],
                "child_stealth_status": stealth_row[0],
                "revealed_size": base.decimal_text(Decimal(str(stealth_row[1] or 0))),
                "executed_size": base.decimal_text(Decimal(str(stealth_row[2] or 0))),
                "remaining_size": base.decimal_text(Decimal(str(stealth_row[4] or 0))),
                "active_placement_client_order_id": anchor.get(
                    "active_placement_client_order_id"
                ),
                "active_exchange_order_id": anchor.get("active_exchange_order_id"),
                "active_exchange_price": base.decimal_text(
                    Decimal(str(anchor.get("active_exchange_price") or 0))
                ),
                "controlled_plan_sha256": preparation.get("controlled_plan_sha256"),
                "controlled_batch_id": preparation.get("batch_id"),
                "reference_notional_usdc": base.decimal_text(
                    Decimal(str(preparation.get("reference_notional_usdc") or 0))
                ),
                "direct_child_client_order_ids": direct_children,
                "nested_child_client_order_ids": nested_children,
            }
        )
    finally:
        connection.close()


def build_v15r3_plan(
    r2_binding: Mapping[str, Any],
    *,
    local_active_child: Mapping[str, Any],
    failed_v15r3_execution_binding: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    created_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    approval = approval_id or f"controlled-child-cancel-v15r4-{uuid4()}"
    _require(
        approval.startswith("controlled-child-cancel-v15r4-"),
        "v15r3_approval_namespace_invalid",
    )
    UUID(approval.removeprefix("controlled-child-cancel-v15r4-"))
    exact_runner = runner_sha256()
    commit = backend_commit()
    batch_id = str(
        uuid5(
            NAMESPACE_URL,
            f"coinbase://selected-child-cancel-v15r4/{commit}/{exact_runner}/{approval}",
        )
    )
    local_binding = validate_local_active_child_binding(local_active_child)
    failed_execution_binding = dict(
        failed_v15r3_execution_binding
        or expected_failed_v15r3_execution_binding()
    )
    _require(
        failed_execution_binding == expected_failed_v15r3_execution_binding(),
        "v15r4_failed_execution_binding_mismatch",
    )
    cancel = {
        "route": "/api/v1/orders/{root_client_order_id}/fill-follow-up/child-cancel",
        "method": "POST",
        "root_client_order_id": ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": CHILD_CLIENT_ORDER_ID,
        "active_exchange_order_id_evidence": CHILD_EXCHANGE_ORDER_ID,
        "identity_key": "client_order_id",
        "identity_value": ROOT_CLIENT_ORDER_ID,
        "operator_intent": CANCEL_OPERATOR_INTENT,
        "actor_roles": list(ACTOR_ROLES),
        "idempotency_key": _deterministic_id(batch_id, "child-cancel-idempotency"),
        "correlation_id": _deterministic_id(batch_id, "child-cancel-correlation"),
        "claim_id": _deterministic_id(batch_id, "child-cancel-claim"),
        "approval_snapshot_id": _deterministic_id(batch_id, "child-cancel-approval"),
        "admission_audit_id_source": "route_bound_runtime_proof",
        "cap_guard_decision_id": _deterministic_id(batch_id, "child-cancel-cap"),
        "reconciliation_plan_id": _deterministic_id(
            batch_id, "child-cancel-reconciliation"
        ),
        "controlled_plan_sha256_source": "plan_sha256",
        "semantic_retry_policy": "fresh_v15r4_idempotency_key_exactly_once",
        "exchange_order_id_fallback_authorized": False,
    }
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
        "v15r2_active_child_binding": dict(r2_binding),
        "failed_v15r3_execution_binding": failed_execution_binding,
        "local_active_child_binding": local_binding,
        "profile_label": PROFILE_LABEL,
        "portfolio_id": TEST_PORTFOLIO_ID,
        "product_id": PRODUCT_ID,
        "placement_attempt_count": 0,
        "placement_attempt_schedule": [],
        "root_placement_maximum": 0,
        "child_placement_maximum": 0,
        "cancel_command_maximum": 1,
        "root_placement_authorized": False,
        "child_placement_authorized": False,
        "root_reference_cap_usdc": base.decimal_text(ROOT_REFERENCE_CAP),
        "child_reference_cap_usdc": base.decimal_text(CHILD_REFERENCE_CAP),
        "slice_reference_cap_usdc": base.decimal_text(SLICE_REFERENCE_CAP),
        "root_actual_reference_notional_usdc": base.decimal_text(
            ROOT_ACTUAL_REFERENCE_NOTIONAL
        ),
        "active_child_reference_notional_usdc": base.decimal_text(
            ACTIVE_CHILD_REFERENCE_NOTIONAL
        ),
        "aggregate_reference_notional_usdc": base.decimal_text(
            AGGREGATE_REFERENCE_NOTIONAL
        ),
        "planned_reference_notional_usdc": base.decimal_text(
            AGGREGATE_REFERENCE_NOTIONAL
        ),
        "root_evidence": {
            "client_order_id": ROOT_CLIENT_ORDER_ID,
            "exchange_order_id": ROOT_EXCHANGE_ORDER_ID,
            "status": "FILLED",
            "filled_size": base.decimal_text(CHILD_BASE_SIZE),
            "filled_value": base.decimal_text(ROOT_ACTUAL_REFERENCE_NOTIONAL),
            "placement_authorized": False,
        },
        "child": {
            "client_order_id": CHILD_CLIENT_ORDER_ID,
            "parent_client_order_id": ROOT_CLIENT_ORDER_ID,
            "active_exchange_order_id": CHILD_EXCHANGE_ORDER_ID,
            "origin_controlled_plan_sha256": R2_PLAN_SHA256,
            "origin_controlled_batch_id": R2_BATCH_ID,
        },
        "child_evidence": {
            "client_order_id": CHILD_CLIENT_ORDER_ID,
            "parent_client_order_id": ROOT_CLIENT_ORDER_ID,
            "exchange_order_id": CHILD_EXCHANGE_ORDER_ID,
            "product_id": PRODUCT_ID,
            "side": "SELL",
            "status": "OPEN",
            "stealth_status": "REVEALED",
            "base_size": base.decimal_text(CHILD_BASE_SIZE),
            "limit_price": base.decimal_text(CHILD_LIMIT_PRICE),
            "filled_size": "0",
            "filled_value": "0",
            "number_of_fills": 0,
            "total_fees": "0",
            "reference_notional_usdc": base.decimal_text(
                ACTIVE_CHILD_REFERENCE_NOTIONAL
            ),
            "origin_controlled_plan_sha256": R2_PLAN_SHA256,
            "origin_controlled_batch_id": R2_BATCH_ID,
            "placement_authorized": False,
            "exchange_order_id_evidence_only": True,
        },
        "actor_id": ACTOR_ID,
        "actor_roles": list(ACTOR_ROLES),
        "child_cancel_operator_intent": CANCEL_OPERATOR_INTENT,
        "cancel_command": cancel,
        "retry_authorized": False,
        "substitution_authorized": False,
        "later_child_authorized": False,
        "browser_derives_child_identity": False,
        "exchange_order_id_evidence_only": True,
        "exchange_order_id_fallback_authorized": False,
    }
    _require(
        batch_id not in R2_USED_IDS
        and set(cancel_command_ids(plan)).isdisjoint(R2_USED_IDS),
        "v15r3_fresh_id_scope_mismatch",
    )
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def validate_v15r3_plan(
    plan: Mapping[str, Any], *, expected_hash: str, now: datetime | None = None
) -> None:
    _require(set(plan) == V15R4_PLAN_FIELDS, "v15r3_plan_fields_mismatch")
    computed = plan_hash(plan)
    _require(
        secrets.compare_digest(str(plan.get("plan_sha256") or ""), computed)
        and secrets.compare_digest(expected_hash, computed),
        "v15r3_plan_hash_mismatch",
    )
    _require(
        plan.get("schema_version") == PLAN_SCHEMA_VERSION
        and plan.get("authority_kind") == AUTHORITY_KIND
        and plan.get("profile_label") == PROFILE_LABEL
        and plan.get("portfolio_id") == TEST_PORTFOLIO_ID
        and plan.get("product_id") == PRODUCT_ID,
        "v15r3_plan_authority_mismatch",
    )
    _require(
        plan.get("backend_commit") == backend_commit()
        and plan.get("frontend_commit") == frontend_commit()
        and plan.get("runner_sha256") == runner_sha256(),
        "v15r3_plan_code_binding_mismatch",
    )
    _require(
        plan.get("placement_attempt_count") == 0
        and plan.get("placement_attempt_schedule") == []
        and plan.get("root_placement_maximum") == 0
        and plan.get("child_placement_maximum") == 0
        and plan.get("cancel_command_maximum") == 1
        and plan.get("root_placement_authorized") is False
        and plan.get("child_placement_authorized") is False,
        "v15r3_exact_scope_mismatch",
    )
    _require(
        plan.get("actor_id") == ACTOR_ID
        and plan.get("actor_roles") == ACTOR_ROLES
        and dict(plan.get("cancel_command") or {}).get("actor_roles") == ACTOR_ROLES,
        "v15r3_actor_scope_mismatch",
    )
    _require(
        Decimal(str(plan.get("root_reference_cap_usdc"))) == ROOT_REFERENCE_CAP
        and Decimal(str(plan.get("child_reference_cap_usdc")))
        == CHILD_REFERENCE_CAP
        and Decimal(str(plan.get("slice_reference_cap_usdc")))
        == SLICE_REFERENCE_CAP
        and Decimal(str(plan.get("root_actual_reference_notional_usdc")))
        == ROOT_ACTUAL_REFERENCE_NOTIONAL
        and Decimal(str(plan.get("active_child_reference_notional_usdc")))
        == ACTIVE_CHILD_REFERENCE_NOTIONAL
        and Decimal(str(plan.get("aggregate_reference_notional_usdc")))
        == AGGREGATE_REFERENCE_NOTIONAL
        and Decimal(str(plan.get("planned_reference_notional_usdc")))
        == AGGREGATE_REFERENCE_NOTIONAL
        and AGGREGATE_REFERENCE_NOTIONAL < SLICE_REFERENCE_CAP,
        "v15r3_numeric_scope_mismatch",
    )
    root = dict(plan.get("root_evidence") or {})
    child = dict(plan.get("child") or {})
    evidence = dict(plan.get("child_evidence") or {})
    cancel = dict(plan.get("cancel_command") or {})
    _require(
        root == {
            "client_order_id": ROOT_CLIENT_ORDER_ID,
            "exchange_order_id": ROOT_EXCHANGE_ORDER_ID,
            "status": "FILLED",
            "filled_size": base.decimal_text(CHILD_BASE_SIZE),
            "filled_value": base.decimal_text(ROOT_ACTUAL_REFERENCE_NOTIONAL),
            "placement_authorized": False,
        }
        and child == {
            "client_order_id": CHILD_CLIENT_ORDER_ID,
            "parent_client_order_id": ROOT_CLIENT_ORDER_ID,
            "active_exchange_order_id": CHILD_EXCHANGE_ORDER_ID,
            "origin_controlled_plan_sha256": R2_PLAN_SHA256,
            "origin_controlled_batch_id": R2_BATCH_ID,
        }
        and evidence.get("client_order_id") == CHILD_CLIENT_ORDER_ID
        and evidence.get("parent_client_order_id") == ROOT_CLIENT_ORDER_ID
        and evidence.get("exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
        and evidence.get("product_id") == PRODUCT_ID
        and evidence.get("side") == "SELL"
        and evidence.get("status") == "OPEN"
        and evidence.get("stealth_status") == "REVEALED"
        and Decimal(str(evidence.get("base_size"))) == CHILD_BASE_SIZE
        and Decimal(str(evidence.get("limit_price"))) == CHILD_LIMIT_PRICE
        and Decimal(str(evidence.get("filled_size") or "0")) == 0
        and Decimal(str(evidence.get("filled_value") or "0")) == 0
        and evidence.get("number_of_fills") == 0
        and Decimal(str(evidence.get("total_fees") or "0")) == 0
        and evidence.get("origin_controlled_plan_sha256") == R2_PLAN_SHA256
        and evidence.get("origin_controlled_batch_id") == R2_BATCH_ID
        and evidence.get("placement_authorized") is False
        and evidence.get("exchange_order_id_evidence_only") is True,
        "v15r3_identity_scope_mismatch",
    )
    batch_id = str(plan.get("batch_id") or "")
    _require(
        all(cancel_command_ids(plan))
        and len(set(cancel_command_ids(plan))) == len(cancel_command_ids(plan))
        and batch_id not in R2_USED_IDS
        and set(cancel_command_ids(plan)).isdisjoint(R2_USED_IDS),
        "v15r3_fresh_id_scope_mismatch",
    )
    _require(
        cancel.get("route")
        == "/api/v1/orders/{root_client_order_id}/fill-follow-up/child-cancel"
        and cancel.get("method") == "POST"
        and cancel.get("root_client_order_id") == ROOT_CLIENT_ORDER_ID
        and cancel.get("child_client_order_id") == CHILD_CLIENT_ORDER_ID
        and cancel.get("active_exchange_order_id_evidence") == CHILD_EXCHANGE_ORDER_ID
        and cancel.get("identity_key") == "client_order_id"
        and cancel.get("identity_value") == ROOT_CLIENT_ORDER_ID
        and cancel.get("operator_intent") == CANCEL_OPERATOR_INTENT
        and cancel.get("idempotency_key")
        == _deterministic_id(batch_id, "child-cancel-idempotency")
        and cancel.get("correlation_id")
        == _deterministic_id(batch_id, "child-cancel-correlation")
        and cancel.get("claim_id") == _deterministic_id(batch_id, "child-cancel-claim")
        and cancel.get("approval_snapshot_id")
        == _deterministic_id(batch_id, "child-cancel-approval")
        and cancel.get("admission_audit_id_source")
        == "route_bound_runtime_proof"
        and cancel.get("cap_guard_decision_id")
        == _deterministic_id(batch_id, "child-cancel-cap")
        and cancel.get("reconciliation_plan_id")
        == _deterministic_id(batch_id, "child-cancel-reconciliation")
        and cancel.get("controlled_plan_sha256_source") == "plan_sha256"
        and cancel.get("semantic_retry_policy")
        == "fresh_v15r4_idempotency_key_exactly_once"
        and cancel.get("exchange_order_id_fallback_authorized") is False,
        "v15r3_cancel_scope_mismatch",
    )
    _require(
        plan.get("child_cancel_operator_intent") == CANCEL_OPERATOR_INTENT
        and plan.get("retry_authorized") is False
        and plan.get("substitution_authorized") is False
        and plan.get("later_child_authorized") is False
        and plan.get("browser_derives_child_identity") is False
        and plan.get("exchange_order_id_evidence_only") is True
        and plan.get("exchange_order_id_fallback_authorized") is False,
        "v15r3_broadening_boundary_mismatch",
    )
    _require(
        plan.get("failed_v15r3_execution_binding")
        == expected_failed_v15r3_execution_binding(),
        "v15r4_failed_execution_binding_mismatch",
    )
    expected_source, completed_shutdown = load_current_v15r3_source_binding()
    expected_local = dict(completed_shutdown["local_active_child_binding"])
    _require(
        plan.get("v15r2_active_child_binding") == expected_source
        and validate_local_active_child_binding(
            dict(plan.get("local_active_child_binding") or {})
        )
        == expected_local
        and plan.get("failed_v15r3_execution_binding")
        == completed_shutdown.get("failed_v15r3_execution_binding"),
        "v15r3_recovery_binding_mismatch",
    )
    created = datetime.fromisoformat(str(plan.get("created_at") or ""))
    expires = datetime.fromisoformat(str(plan.get("expires_at") or ""))
    current = now or datetime.now(timezone.utc)
    _require(
        created.tzinfo is not None
        and expires.tzinfo is not None
        and expires - created == PLAN_TTL
        and created <= current < expires,
        "v15r3_plan_expired_or_ttl_invalid",
    )


def transition_hash(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("transition_sha256", None)
    return _canonical_json_sha256(payload)


def revalidate_v15r2_transition_processes(
    plan: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    source = dict(plan.get("v15r2_active_child_binding") or {})
    expected_parent = dict(source.get("r2_parent_process_identity") or {})
    expected_runtime = dict(source.get("r2_runtime_process_identity") or {})
    parent = _read_process_identity(int(expected_parent.get("process_id") or 0))
    runtime = _read_process_identity(int(expected_runtime.get("process_id") or 0))
    _require(
        parent == expected_parent
        and runtime == expected_runtime
        and source.get("r2_state_dir") == str(R2_STATE_DIR),
        "v15r3_transition_process_identity_changed",
    )
    return {"parent": parent, "runtime": runtime}


def _read_process_environment(process_id: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{process_id}/environ").read_bytes()
    except OSError as exc:
        raise ProofFailure("v15r3_transition_runtime_environment_unavailable") from exc
    result: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        try:
            result[key.decode("utf-8")] = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProofFailure("v15r3_transition_runtime_environment_malformed") from exc
    return result


def post_v15r2_live_service_disabled(
    *, plan: Mapping[str, Any], runtime_pid: int
) -> dict[str, Any]:
    environment = _read_process_environment(runtime_pid)
    token = environment.get("COINBASE_ADMIN_API_BEARER_TOKEN", "")
    _require(bool(token), "v15r3_transition_runtime_token_missing")
    body = {
        "decision_id": f"v15r3-transition-disable-r2-{uuid4()}",
        "status": "blocked",
        "requested_service_status": "live_disabled",
        "service_enabled": False,
        "target_module_id": "spot_operations",
        "account_family": "coinbase_retail_test",
        "venue_scope": "coinbase_advanced_trade",
        "intx_applicability": "not_applicable",
        "product_scope": [PRODUCT_ID],
        "deployment_ref": str(dict(plan)["backend_commit"]),
        "runtime_configuration_ref": str(R2_STATE_DIR),
        "decision_reason": (
            "Disable V15R2 before the sealed V15R3 cancel-only runtime transition."
        ),
        "live_coinbase_execution_approved": False,
        "max_submitted_notional_usdc": "0",
        "max_executed_notional_usdc": "0",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Admin-Actor": ACTOR_ID,
        "X-Admin-Roles": "admin",
        "Idempotency-Key": f"v15r3-transition-disable-r2-{uuid4()}",
        "X-Operator-Intent": "disable_v15r2_before_v15r3_transition",
        "X-Correlation-Id": f"corr-v15r3-transition-disable-r2-{uuid4()}",
    }
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        f"{base.BASE_URL}/admin/live-execution/service-decisions",
        headers=headers,
        json=body,
        timeout=base.HTTP_TIMEOUT_SECONDS,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProofFailure("v15r3_transition_disable_response_malformed") from exc
    decision = dict(dict(payload).get("decision") or {})
    _require(
        response.status_code == 200
        and decision.get("resolver_eligible") is False
        and decision.get("service_enabled") in {False, None}
        and decision.get("requested_service_status") == "live_disabled",
        "v15r3_transition_r2_live_service_disable_unproven",
    )
    return {
        "http_status": response.status_code,
        "resolver_eligible": False,
        "service_enabled": False,
        "decision_id": decision.get("decision_id"),
        "requested_service_status": "live_disabled",
    }


def read_v15r2_pretransition_sentinel() -> dict[str, Any]:
    path = Path(R2_ARTIFACT_PATHS["sentinel_path"])
    sentinel = _json(path, "v15r3_pretransition_sentinel")
    _require(
        sentinel.get("installed") is True
        and sentinel.get("wrapper_identity_proven") is True
        and sentinel.get("root_create_order_call_count") == 0
        and sentinel.get("root_create_order_maximum") == 0
        and sentinel.get("root_sdk_inflight") is False
        and sentinel.get("child_place_limit_order_call_count") == 1
        and sentinel.get("child_place_limit_order_maximum") == 1
        and sentinel.get("child_sdk_inflight") is False
        and sentinel.get("denied_call_count") == 0
        and sentinel.get("critical_failure") is False
        and sentinel.get("error") is None,
        "v15r3_pretransition_sentinel_mismatch",
    )
    return sentinel


def signal_exact_process(identity: Mapping[str, Any], signum: int) -> None:
    expected = dict(identity)
    process_id = int(expected.get("process_id") or 0)
    pidfd_open = getattr(os, "pidfd_open", None)
    pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
    _require(
        callable(pidfd_open) and callable(pidfd_send_signal),
        "v15r3_pidfd_api_unavailable",
    )
    try:
        pidfd = pidfd_open(process_id, 0)
    except OSError as exc:
        raise ProofFailure("v15r3_signal_pidfd_open_failed") from exc
    try:
        current = _read_process_identity(process_id)
        _require(current == expected, "v15r3_signal_process_identity_changed")
        try:
            pidfd_send_signal(pidfd, signum, None, 0)
        except OSError as exc:
            raise ProofFailure("v15r3_signal_pidfd_send_failed") from exc
    finally:
        os.close(pidfd)


def wait_exact_process_absent(identity: Mapping[str, Any]) -> bool:
    expected = dict(identity)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            current = _read_process_identity(int(expected.get("process_id") or 0))
        except ProofFailure:
            return True
        if current.get("start_identity") != expected.get("start_identity"):
            return True
        time.sleep(0.25)
    raise ProofFailure("v15r3_transition_exact_process_still_present")


def wait_v15r2_parent_loss_evidence(
    *, expected_runtime_identity: Mapping[str, Any]
) -> dict[str, Any]:
    path = R2_STATE_DIR / "parent-authority-loss.json"
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        _require(
            _read_process_identity(int(expected_runtime_identity["process_id"]))
            == dict(expected_runtime_identity),
            "v15r3_transition_runtime_identity_changed_before_parent_loss",
        )
        if os.path.lexists(path):
            try:
                report = _json(path, "v15r3_parent_loss")
            except ProofFailure:
                time.sleep(0.25)
                continue
            active = list(report.get("authoritative_active_orders") or [])
            exact_active = [
                row
                for row in active
                if str(dict(row).get("client_order_id") or "")
                == CHILD_CLIENT_ORDER_ID
                and str(dict(row).get("order_id") or "")
                == CHILD_EXCHANGE_ORDER_ID
            ]
            if (
                report.get("status")
                == "v15_parent_authority_lost_reconciliation_only"
                and report.get("plan_sha256") == R2_PLAN_SHA256
                and report.get("new_sdk_placements_denied") is True
                and report.get("new_cancel_command_authorized") is False
                and report.get("root_create_order_call_count") == 0
                and report.get("child_place_limit_order_call_count") == 1
                and report.get("root_sdk_inflight") is False
                and report.get("child_sdk_inflight") is False
                and report.get("authoritative_active_read_stable") is True
                and len(exact_active) == 1
                and report.get("live_service_disable_http_status") == 200
                and dict(report.get("sealed_cancel_reconciliation") or {}).get(
                    "cancel_post_submitted"
                )
                is False
            ):
                return report
        time.sleep(0.25)
    raise ProofFailure("v15r3_transition_parent_loss_evidence_timeout")


def prove_admin_port_free() -> dict[str, Any]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", base.PORT))
    except OSError as exc:
        raise ProofFailure("v15r3_transition_admin_port_not_free") from exc
    finally:
        listener.close()
    return {"port": base.PORT, "free": True, "competitor_pid": None}


def read_exact_active_child_after_transition() -> dict[str, Any]:
    rest_client = base.hydrate_test_credentials()
    raw = base.exact_exchange_order(rest_client, CHILD_EXCHANGE_ORDER_ID)
    exact_tuple = {
        "client_order_id": CHILD_CLIENT_ORDER_ID,
        "root_client_order_id": ROOT_CLIENT_ORDER_ID,
        "product_id": PRODUCT_ID,
        "side": "SELL",
        "base_size": base.decimal_text(CHILD_BASE_SIZE),
        "limit_price": base.decimal_text(CHILD_LIMIT_PRICE),
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "post_only": False,
    }
    validated = base._validate_exact_coinbase_gtc_child_order(
        raw,
        expected_exchange_order_id=CHILD_EXCHANGE_ORDER_ID,
        expected_portfolio_id=TEST_PORTFOLIO_ID,
        expected_child_tuple=exact_tuple,
    )
    v15.validate_v15_explicit_zero_fill(validated)
    _require(
        str(validated.get("status") or "").upper() in {"OPEN", "PENDING"},
        "v15r3_transition_child_not_active_zero_fill",
    )
    return {
        "client_order_id": CHILD_CLIENT_ORDER_ID,
        "exchange_order_id": CHILD_EXCHANGE_ORDER_ID,
        "status": str(validated.get("status") or "").upper(),
        "filled_size": base.decimal_text(
            Decimal(str(validated.get("filled_size") or "0"))
        ),
        "filled_value": base.decimal_text(
            Decimal(str(validated.get("filled_value") or "0"))
        ),
        "total_fees": base.decimal_text(
            Decimal(str(validated.get("total_fees") or "0"))
        ),
        "number_of_fills": int(validated.get("number_of_fills") or 0),
        "reference_notional_usdc": base.decimal_text(
            ACTIVE_CHILD_REFERENCE_NOTIONAL
        ),
    }


def bind_completed_v15r2_shutdown(
    plan: Mapping[str, Any],
    *,
    confirmed_plan_sha256: str,
    transition_path: Path,
) -> dict[str, Any]:
    """Bind both completed predecessors without replaying a signal."""

    _require(
        str(plan.get("plan_sha256") or "") == confirmed_plan_sha256,
        "v15r3_recovered_transition_plan_hash_mismatch",
    )
    expected_source, completed = load_current_v15r3_source_binding()
    _require(
        plan.get("v15r2_active_child_binding") == expected_source
        and plan.get("local_active_child_binding")
        == completed["local_active_child_binding"]
        and plan.get("failed_v15r3_execution_binding")
        == completed["failed_v15r3_execution_binding"],
        "v15r3_recovered_transition_binding_mismatch",
    )
    child = dict(completed["child_readback"])
    proof: dict[str, Any] = {
        "schema_version": "3",
        "status": "v15r3_to_v15r4_no_overlap_proven",
        "recovery_status": (
            "failed_v15r3_proof_runtime_bound_no_live_cancel"
        ),
        "transition_mode": (
            "bind_completed_predecessor_shutdowns_no_signals"
        ),
        "controlled_plan_sha256": confirmed_plan_sha256,
        "failed_plan_sha256": completed["failed_plan_sha256"],
        "failed_plan_bytes_sha256": completed[
            "failed_plan_bytes_sha256"
        ],
        "failed_batch_id": completed["failed_batch_id"],
        "failed_backend_commit": completed["failed_backend_commit"],
        "failed_runner_sha256": completed["failed_runner_sha256"],
        "r2_plan_sha256": R2_PLAN_SHA256,
        "r2_parent_process_identity": dict(
            completed["r2_source_binding"]["r2_parent_process_identity"]
        ),
        "r2_runtime_process_identity": dict(
            completed["r2_source_binding"]["r2_runtime_process_identity"]
        ),
        "predecessor_signal_attempt_count": 0,
        "predecessor_signal_authorized": False,
        "predecessor_restart_authorized": False,
        "both_predecessor_processes_absent": True,
        "both_predecessor_exact_identities_absent": completed[
            "both_predecessor_exact_identities_absent"
        ],
        "terminal_artifact_paths": completed["terminal_artifact_paths"],
        "terminal_artifact_hashes": completed[
            "terminal_artifact_hashes"
        ],
        "transition_disable_record_hashes": completed[
            "transition_disable_record_hashes"
        ],
        "failed_v15r3_execution_binding": dict(
            completed["failed_v15r3_execution_binding"]
        ),
        "admin_port_8787_free": True,
        "competitor_pid": None,
        "exact_child_open_zero_fill": (
            child.get("client_order_id") == CHILD_CLIENT_ORDER_ID
            and child.get("exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
            and str(child.get("status") or "").upper()
            in {"OPEN", "PENDING"}
            and Decimal(str(child.get("filled_size") or "0")) == 0
            and Decimal(str(child.get("filled_value") or "0")) == 0
            and Decimal(str(child.get("total_fees") or "0")) == 0
            and int(child.get("number_of_fills") or 0) == 0
        ),
        "child_readback": child,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _require(
        proof["exact_child_open_zero_fill"] is True,
        "v15r3_recovered_transition_child_unproven",
    )
    proof["transition_sha256"] = transition_hash(proof)
    transition_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    base._write_owner_only_exclusive_json(
        transition_path,
        proof,
        exists_blocker="v15r3_recovered_transition_evidence_already_exists",
    )
    return proof


def transition_v15r2_runtime(
    plan: Mapping[str, Any],
    *,
    confirmed_plan_sha256: str,
    transition_path: Path,
) -> dict[str, Any]:
    _require(
        str(plan.get("plan_sha256") or "") == confirmed_plan_sha256,
        "v15r3_transition_plan_hash_mismatch",
    )
    identities = revalidate_v15r2_transition_processes(plan)
    disabled = post_v15r2_live_service_disabled(
        plan=plan, runtime_pid=int(identities["runtime"]["process_id"])
    )
    sentinel = read_v15r2_pretransition_sentinel()
    signal_exact_process(identities["parent"], signal.SIGINT)
    wait_exact_process_absent(identities["parent"])
    parent_loss = wait_v15r2_parent_loss_evidence(
        expected_runtime_identity=identities["runtime"]
    )
    signal_exact_process(identities["runtime"], signal.SIGTERM)
    wait_exact_process_absent(identities["runtime"])
    port = prove_admin_port_free()
    child = read_exact_active_child_after_transition()
    proof: dict[str, Any] = {
        "schema_version": "1",
        "status": "v15r2_to_v15r3_no_overlap_proven",
        "controlled_plan_sha256": confirmed_plan_sha256,
        "r2_plan_sha256": R2_PLAN_SHA256,
        "r2_parent_process_identity": identities["parent"],
        "r2_runtime_process_identity": identities["runtime"],
        "r2_live_service_disabled": disabled,
        "pretransition_sentinel": sentinel,
        "parent_loss_evidence_sha256": _canonical_json_sha256(parent_loss),
        "both_predecessor_processes_absent": True,
        "admin_port_8787_free": port.get("free") is True,
        "competitor_pid": port.get("competitor_pid"),
        "exact_child_open_zero_fill": (
            child.get("client_order_id") == CHILD_CLIENT_ORDER_ID
            and child.get("exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
            and str(child.get("status") or "").upper() in {"OPEN", "PENDING"}
            and Decimal(str(child.get("filled_size") or "0")) == 0
            and Decimal(str(child.get("filled_value") or "0")) == 0
            and int(child.get("number_of_fills") or 0) == 0
            and Decimal(str(child.get("reference_notional_usdc") or "0"))
            == ACTIVE_CHILD_REFERENCE_NOTIONAL
        ),
        "child_readback": child,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _require(
        proof["admin_port_8787_free"] is True
        and proof["competitor_pid"] is None
        and proof["exact_child_open_zero_fill"] is True,
        "v15r3_transition_final_gate_failed",
    )
    proof["transition_sha256"] = transition_hash(proof)
    transition_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    base._write_owner_only_exclusive_json(
        transition_path,
        proof,
        exists_blocker="v15r3_transition_evidence_already_exists",
    )
    return proof


def _exclusive_empty(path: Path, blocker: str) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600
        )
    except OSError as exc:
        raise ProofFailure(blocker) from exc
    os.close(descriptor)


def _validate_frozen_plan_after_transition(
    plan: Mapping[str, Any],
    *,
    expected_hash: str,
    transition: Mapping[str, Any],
    now: datetime,
) -> None:
    _require(
        set(plan) == V15R4_PLAN_FIELDS
        and plan_hash(plan) == expected_hash == plan.get("plan_sha256")
        and plan.get("backend_commit") == backend_commit()
        and plan.get("frontend_commit") == frontend_commit()
        and plan.get("runner_sha256") == runner_sha256(),
        "v15r3_post_transition_frozen_plan_mismatch",
    )
    created = datetime.fromisoformat(str(plan.get("created_at") or ""))
    expires = datetime.fromisoformat(str(plan.get("expires_at") or ""))
    _require(
        created.tzinfo is not None
        and expires.tzinfo is not None
        and expires - created == PLAN_TTL
        and created <= now < expires,
        "v15r3_post_transition_plan_expired_or_ttl_invalid",
    )
    proof = dict(transition)
    source = dict(plan.get("v15r2_active_child_binding") or {})
    child = dict(proof.get("child_readback") or {})
    try:
        child_is_exact_zero_fill = (
            child.get("client_order_id") == CHILD_CLIENT_ORDER_ID
            and child.get("exchange_order_id") == CHILD_EXCHANGE_ORDER_ID
            and str(child.get("status") or "").upper() in {"OPEN", "PENDING"}
            and Decimal(str(child.get("filled_size") or "0")) == 0
            and Decimal(str(child.get("filled_value") or "0")) == 0
            and Decimal(str(child.get("total_fees") or "0")) == 0
            and int(child.get("number_of_fills") or 0) == 0
            and Decimal(str(child.get("reference_notional_usdc") or "0"))
            == ACTIVE_CHILD_REFERENCE_NOTIONAL
        )
    except (ArithmeticError, TypeError, ValueError):
        child_is_exact_zero_fill = False
    _require(
        set(proof) == V15R4_RECOVERED_TRANSITION_FIELDS
        and proof.get("schema_version") == "3"
        and proof.get("status") == "v15r3_to_v15r4_no_overlap_proven"
        and proof.get("recovery_status")
        == "failed_v15r3_proof_runtime_bound_no_live_cancel"
        and proof.get("transition_mode")
        == "bind_completed_predecessor_shutdowns_no_signals"
        and proof.get("controlled_plan_sha256") == expected_hash
        and proof.get("failed_plan_sha256") == FAILED_V15R3_PLAN_SHA256
        and proof.get("failed_plan_bytes_sha256")
        == FAILED_V15R3_PLAN_BYTES_SHA256
        and proof.get("failed_batch_id") == FAILED_V15R3_BATCH_ID
        and proof.get("failed_backend_commit") == FAILED_V15R3_BACKEND_COMMIT
        and proof.get("failed_runner_sha256") == FAILED_V15R3_RUNNER_SHA256
        and proof.get("r2_plan_sha256") == R2_PLAN_SHA256
        and proof.get("r2_parent_process_identity")
        == source.get("r2_parent_process_identity")
        and proof.get("r2_runtime_process_identity")
        == source.get("r2_runtime_process_identity")
        and proof.get("predecessor_signal_attempt_count") == 0
        and proof.get("predecessor_signal_authorized") is False
        and proof.get("predecessor_restart_authorized") is False
        and proof.get("both_predecessor_processes_absent") is True
        and proof.get("both_predecessor_exact_identities_absent") is True
        and proof.get("terminal_artifact_paths")
        == {
            key: str(value)
            for key, value in COMPLETED_SHUTDOWN_ARTIFACT_PATHS.items()
        }
        and proof.get("terminal_artifact_hashes")
        == COMPLETED_SHUTDOWN_ARTIFACT_HASHES
        and proof.get("transition_disable_record_hashes")
        == COMPLETED_SHUTDOWN_RECORD_HASHES
        and proof.get("failed_v15r3_execution_binding")
        == plan.get("failed_v15r3_execution_binding")
        == expected_failed_v15r3_execution_binding()
        and proof.get("admin_port_8787_free") is True
        and proof.get("competitor_pid") is None
        and proof.get("exact_child_open_zero_fill") is True
        and child_is_exact_zero_fill
        and secrets.compare_digest(
            str(proof.get("transition_sha256") or ""), transition_hash(proof)
        ),
        "v15r3_post_transition_evidence_invalid",
    )


def authorize_v15r3_execution(
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
) -> dict[str, Any]:
    plan = _json(plan_path, "v15r3_execution_plan")
    _require(plan == dict(frozen_plan), "v15r3_post_transition_plan_file_changed")
    current = now or datetime.now(timezone.utc)
    _validate_frozen_plan_after_transition(
        plan,
        expected_hash=expected_hash,
        transition=transition,
        now=current,
    )
    _require(
        all(
            not os.path.lexists(path)
            for path in (
                marker_path, placement_ledger_path, cancel_ledger_path,
                backend_claim_log_path, handoff_path,
            )
        ),
        "v15r3_execution_authority_already_consumed",
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
        marker_path, authority, exists_blocker="v15r3_marker_already_exists"
    )
    for path, blocker in (
        (placement_ledger_path, "v15r3_placement_ledger_create_failed"),
        (cancel_ledger_path, "v15r3_cancel_ledger_create_failed"),
        (backend_claim_log_path, "v15r3_backend_claim_log_create_failed"),
    ):
        _exclusive_empty(path, blocker)
    return authority


def build_v15r3_cancel_admission_context(
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
    endpoint = (
        f"POST /api/v1/orders/{ROOT_CLIENT_ORDER_ID}/fill-follow-up/child-cancel"
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=AdminApiActor(actor_id=ACTOR_ID, roles=list(ACTOR_ROLES)),
        operator_intent=str(cancel["operator_intent"]),
        body=body,
        path_params={"root_client_order_id": ROOT_CLIENT_ORDER_ID},
    )
    return (
        {
            "route": cancel["route"],
            "method": "POST",
            "module_id": "spot_operations",
            "identity_key": "client_order_id",
            "identity_value": ROOT_CLIENT_ORDER_ID,
            "action_class": "live_exchange_cancel",
            "required_permission": "order:cancel",
            "service_method": (
                "cancel_order_fill_follow_up_child_by_root_client_order_id"
            ),
            "actor_id": ACTOR_ID,
            "actor_roles": list(ACTOR_ROLES),
            "operator_intent": cancel["operator_intent"],
            "command_idempotency_key": cancel["idempotency_key"],
            "payload_hash": payload_hash,
        },
        body,
    )


def write_v15r3_cancel_proof_handoff(
    handoff_path: Path,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    context: Mapping[str, Any],
    proofs: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    expected, _ = build_v15r3_cancel_admission_context(
        plan, plan_sha256=plan_sha256
    )
    cancel = dict(plan["cancel_command"])
    _require(dict(context) == expected, "v15r3_handoff_context_mismatch")
    _require(
        proofs.get("approval_id") == cancel["approval_snapshot_id"]
        and bool(proofs.get("admission_audit_id"))
        and proofs.get("cap_guard_decision_id") == cancel["cap_guard_decision_id"]
        and proofs.get("reconciliation_plan_id")
        == cancel["reconciliation_plan_id"],
        "v15r3_handoff_proof_mismatch",
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
        handoff_path, handoff, exists_blocker="v15r3_handoff_already_exists"
    )
    return handoff


def set_v15r3_cancel_only_service(
    runtime: base.AdminRuntime, *, enabled: bool
) -> dict[str, Any]:
    label = "enabled" if enabled else "disabled"
    if enabled:
        runtime.live_service_enable_attempted = True
        runtime.live_service_may_be_enabled = True
        runtime.live_service_disable_proven = False
    else:
        runtime.live_service_disable_attempted = True
    body = {
        "decision_id": f"v15r4-cancel-only-{label}-{uuid4()}",
        "status": "passed" if enabled else "blocked",
        "requested_service_status": "approval_required" if enabled else "live_disabled",
        "service_enabled": enabled,
        "target_module_id": "spot_operations",
        "account_family": "coinbase_retail_test",
        "venue_scope": "coinbase_advanced_trade",
        "intx_applicability": "not_applicable",
        "product_scope": [PRODUCT_ID],
        "deployment_ref": str(runtime.confirmed_plan["backend_commit"]),
        "runtime_configuration_ref": str(runtime.state_dir),
        "decision_reason": (
            "Enable one approval-bound cancel of the existing V15R2 first child."
            if enabled
            else "Disable V15R4 cancel-only service at transition or closeout."
        ),
        "live_coinbase_execution_approved": enabled,
        "max_submitted_notional_usdc": "0",
        "max_executed_notional_usdc": "0",
    }
    _, response, _ = runtime.request(
        "POST",
        "/admin/live-execution/service-decisions",
        headers=runtime.headers(
            idempotency_key=f"idem-v15r4-cancel-service-{label}-{uuid4()}",
            operator_intent=f"record_v15r4_cancel_service_{label}",
            role=base.ADMIN_ROLE,
        ),
        body=body,
        expected={200},
    )
    decision = dict(response.get("decision") or {})
    _require(
        decision.get("resolver_eligible") is enabled,
        f"v15r3_cancel_service_{label}_mismatch",
    )
    runtime.live_service_may_be_enabled = enabled
    runtime.live_service_disable_proven = not enabled
    return decision


def _assert_v15r3_zero_sdk_calls(runtime: base.AdminRuntime) -> dict[str, Any]:
    return runtime.sdk_boundary_sentinel(
        expected_root_create_order_calls={0},
        expected_child_place_limit_order_calls={0},
    )


def v15r3_backend_claim_identity(
    plan: Mapping[str, Any], *, plan_sha256: str
) -> dict[str, Any]:
    from application.admin_api.root_child_cancel import root_child_cancel_semantic_key

    context, _ = build_v15r3_cancel_admission_context(
        plan, plan_sha256=plan_sha256
    )
    cancel = dict(plan["cancel_command"])
    return {
        "schema_version": "1",
        "semantic_key": root_child_cancel_semantic_key(
            controlled_plan_sha256=plan_sha256,
            root_client_order_id=ROOT_CLIENT_ORDER_ID,
            child_client_order_id=CHILD_CLIENT_ORDER_ID,
        ),
        "controlled_plan_sha256": plan_sha256,
        "root_client_order_id": ROOT_CLIENT_ORDER_ID,
        "child_client_order_id": CHILD_CLIENT_ORDER_ID,
        "idempotency_key": cancel["idempotency_key"],
        "payload_hash": context["payload_hash"],
        "correlation_id": cancel["correlation_id"],
        "actor_id": ACTOR_ID,
        "source": "admin_api_root_child_cancel_claim_log",
    }


def v15r3_operator_monitor_decision(
    placement_records: list[Mapping[str, Any]],
    local_cancel_records: list[Mapping[str, Any]],
    backend_claim_records: list[Mapping[str, Any]],
    *,
    expected_identity: Mapping[str, Any],
) -> str:
    _require(not placement_records, "v15r3_monitor_placement_ledger_not_empty")
    _require(not local_cancel_records, "v15r3_monitor_runner_cancel_claim_forbidden")
    if not backend_claim_records:
        return "awaiting_operator_ui_root_scoped_cancel"
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
        "v15r3_monitor_backend_claim_identity_mismatch",
    )
    _require(
        len(backend_claim_records) <= 3
        and backend_claim_records[0].get("event") == "claim"
        and backend_claim_records[0].get("outcome") == "claimed",
        "v15r3_monitor_backend_claim_ledger_invalid",
    )
    if len(backend_claim_records) == 1:
        return "awaiting_operator_ui_root_scoped_cancel"
    _require(
        backend_claim_records[1].get("event") == "exchange_boundary"
        and backend_claim_records[1].get("outcome") == "unknown",
        "v15r3_monitor_backend_claim_ledger_invalid",
    )
    if len(backend_claim_records) == 2:
        return "awaiting_operator_ui_root_scoped_cancel"
    _require(
        backend_claim_records[2].get("event") == "outcome"
        and backend_claim_records[2].get("outcome")
        in {"accepted", "rejected", "unknown"}
        and isinstance(backend_claim_records[2].get("response"), Mapping),
        "v15r3_monitor_backend_claim_ledger_invalid",
    )
    outcome = str(backend_claim_records[2].get("outcome"))
    if outcome == "accepted":
        return "verify_terminal_closeout"
    if outcome == "rejected":
        return "operator_cancel_rejected_active_child_reconciliation_only"
    return "operator_cancel_ambiguous_reconciliation_only"


def validate_v15r3_waiting_child_readback(
    value: Mapping[str, Any]
) -> dict[str, Any]:
    child = dict(value)
    _require(
        str(child.get("client_order_id") or "") == CHILD_CLIENT_ORDER_ID
        and str(child.get("order_id") or "") == CHILD_EXCHANGE_ORDER_ID,
        "v15r3_waiting_child_identity_drift",
    )
    filled_size = Decimal(str(child.get("filled_size") or "0"))
    filled_value = Decimal(str(child.get("filled_value") or "0"))
    fill_count = int(child.get("number_of_fills") or 0)
    _require(
        filled_size == 0 and filled_value == 0 and fill_count == 0,
        "v15r3_waiting_child_fill_drift",
    )
    status = str(child.get("status") or "").upper()
    _require(status in {"OPEN", "PENDING"}, "v15r3_waiting_child_not_active")
    return {
        "client_order_id": CHILD_CLIENT_ORDER_ID,
        "exchange_order_id": CHILD_EXCHANGE_ORDER_ID,
        "status": status,
        "filled_size": "0",
        "filled_value": "0",
        "number_of_fills": 0,
    }


def write_v15r3_exact_proofs(
    runtime: base.AdminRuntime,
    *,
    plan: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, str]:
    """Write route proofs whose approval cannot outlive the sealed plan."""

    cancel = dict(plan["cancel_command"])
    return base.write_proof_chain(
        runtime,
        label="v15r4-child-cancel",
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


def _with_controlled_execution_lease(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with base.ControlledExecutionLease():
            return function(*args, **kwargs)

    return wrapped


@_with_controlled_execution_lease
def execute_v15r3_plan(
    *, plan_path: Path, confirmed_plan_sha256: str
) -> dict[str, Any]:
    """Bind the prior shutdown, expose one UI cancel, and monitor its claim."""

    _require(plan_path == PLAN_PATH, "v15r3_execute_plan_file_not_fixed")
    frozen_plan = _json(plan_path, "v15r3_execution_plan")
    validate_v15r3_plan(
        frozen_plan, expected_hash=confirmed_plan_sha256
    )
    transition = bind_completed_v15r2_shutdown(
        frozen_plan,
        confirmed_plan_sha256=confirmed_plan_sha256,
        transition_path=RUNTIME_PATH,
    )
    authority = authorize_v15r3_execution(
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
        "authority": authority,
        "transition": transition,
    }
    cleanup: dict[str, Any] = {}
    try:
        runtime.start()
        runtime.wait_until_mutations_ready()
        _assert_v15r3_zero_sdk_calls(runtime)
        context, cancel_body = build_v15r3_cancel_admission_context(
            frozen_plan, plan_sha256=confirmed_plan_sha256
        )
        proofs = write_v15r3_exact_proofs(
            runtime,
            plan=frozen_plan,
            context=context,
        )
        handoff = write_v15r3_cancel_proof_handoff(
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
            "v15r3_cancel_readiness_blocked",
        )
        _require(
            not _jsonl(CANCEL_LEDGER_PATH, "v15r3_cancel_ledger")
            and not _jsonl(BACKEND_CLAIM_LOG_PATH, "v15r3_backend_claim_log")
            and not _jsonl(PLACEMENT_LEDGER_PATH, "v15r3_placement_ledger"),
            "v15r3_claim_or_placement_present_before_operator",
        )
        set_v15r3_cancel_only_service(runtime, enabled=True)
        base.preview_admission(runtime, context)
        runtime.exchange_safe_to_shutdown = False
        progress = {
            "status": "awaiting_operator_ui_root_scoped_cancel",
            "root_client_order_id": ROOT_CLIENT_ORDER_ID,
            "child_client_order_id": CHILD_CLIENT_ORDER_ID,
            "child_exchange_order_id_evidence": CHILD_EXCHANGE_ORDER_ID,
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
        progress_path = runtime.state_dir / "v15r4-operator-ui-cancel-handoff.json"
        base._replace_owner_only_json(progress_path, progress)
        print(json.dumps(progress, sort_keys=True), flush=True)
        monitor_rest_client = base.hydrate_test_credentials()
        expires_at = datetime.fromisoformat(str(frozen_plan["expires_at"]))
        next_child_read = 0.0
        while True:
            _assert_v15r3_zero_sdk_calls(runtime)
            backend_rows = v15._read_v15_backend_cancel_claim_records(
                BACKEND_CLAIM_LOG_PATH
            )
            decision = v15r3_operator_monitor_decision(
                _jsonl(PLACEMENT_LEDGER_PATH, "v15r3_placement_ledger"),
                _jsonl(CANCEL_LEDGER_PATH, "v15r3_cancel_ledger"),
                backend_rows,
                expected_identity=v15r3_backend_claim_identity(
                    frozen_plan, plan_sha256=confirmed_plan_sha256
                ),
            )
            if decision == "verify_terminal_closeout":
                _require(len(backend_rows) == 3, "v15r3_cancel_claim_triplet_missing")
                rest_client = base.hydrate_test_credentials()
                terminal = base.exact_exchange_order(
                    rest_client, CHILD_EXCHANGE_ORDER_ID
                )
                v15.validate_v15_explicit_zero_fill(terminal)
                _require(
                    str(terminal.get("status") or "").upper()
                    in {"CANCELLED", "CANCELED"},
                    "v15r3_child_terminal_zero_fill_unproven",
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
                    "v15r3_final_active_zero_unproven",
                )
                set_v15r3_cancel_only_service(runtime, enabled=False)
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
                summary["status"] = decision
                break
            current = datetime.now(timezone.utc)
            if current >= expires_at:
                set_v15r3_cancel_only_service(runtime, enabled=False)
                summary["status"] = (
                    "plan_expired_active_child_reconciliation_only"
                )
                break
            if not backend_rows and time.monotonic() >= next_child_read:
                try:
                    waiting_child = validate_v15r3_waiting_child_readback(
                        base.exact_exchange_order(
                            monitor_rest_client, CHILD_EXCHANGE_ORDER_ID
                        )
                    )
                except ProofFailure as exc:
                    set_v15r3_cancel_only_service(runtime, enabled=False)
                    summary.update(
                        {
                            "status": (
                                "critical_child_drift_reconciliation_only"
                            ),
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
                set_v15r3_cancel_only_service(runtime, enabled=False)
            except Exception as exc:
                cleanup["live_service_disable_error"] = (
                    f"{type(exc).__name__}:{exc}"
                )
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
        terminal_closeout
        or cleanup.get("runtime_preserved_for_reconciliation") is True,
        "v15r3_nonterminal_runtime_not_preserved",
    )
    return summary


def prepare_v15r3_plan(
    *,
    plan_path: Path = PLAN_PATH,
    marker_path: Path = MARKER_PATH,
    placement_ledger_path: Path = PLACEMENT_LEDGER_PATH,
    cancel_ledger_path: Path = CANCEL_LEDGER_PATH,
    backend_claim_log_path: Path = BACKEND_CLAIM_LOG_PATH,
    handoff_path: Path = HANDOFF_PATH,
    runtime_path: Path = RUNTIME_PATH,
    now: datetime | None = None,
    require_clean_environment: bool = True,
) -> dict[str, Any]:
    if require_clean_environment:
        _require(
            _git("rev-list", "--left-right", "--count", "HEAD...origin/main")
            == "0\t0"
            and not _git("status", "--porcelain", "--untracked-files=no"),
            "v15r3_backend_not_clean_and_synced",
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
            "v15r3_frontend_not_clean_and_synced",
        )
    _require(
        all(
            not os.path.lexists(path)
            for path in (
                plan_path, marker_path, placement_ledger_path, cancel_ledger_path,
                backend_claim_log_path, handoff_path, runtime_path,
            )
        ),
        "v15r3_prepare_path_already_exists",
    )
    source_binding, completed_shutdown = load_current_v15r3_source_binding()
    local_binding = dict(completed_shutdown["local_active_child_binding"])
    plan = build_v15r3_plan(
        source_binding,
        local_active_child=local_binding,
        failed_v15r3_execution_binding=dict(
            completed_shutdown["failed_v15r3_execution_binding"]
        ),
        now=now,
    )
    plan_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    base._write_owner_only_exclusive_json(
        plan_path, plan, exists_blocker="v15r3_plan_path_already_exists"
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
        "planned_reference_notional_usdc": plan[
            "planned_reference_notional_usdc"
        ],
        "aggregate_reference_notional_usdc": plan[
            "aggregate_reference_notional_usdc"
        ],
        "live_coinbase_orders_ran": False,
        "live_coinbase_read_ran": True,
        "completed_predecessor_shutdown_bound": True,
        "failed_v15r3_execution_bound": True,
        "marker_written": False,
        "ledger_written": False,
        "handoff_written": False,
        "runtime_started": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-v15r4-plan", action="store_true")
    mode.add_argument("--execute-v15r4-plan", action="store_true")
    parser.add_argument("--plan-file")
    parser.add_argument("--confirm-plan-sha256")
    args = parser.parse_args(argv)
    if args.prepare_v15r4_plan:
        print(json.dumps(prepare_v15r3_plan(), sort_keys=True))
        return 0
    _require(bool(args.plan_file), "v15r3_execute_plan_file_required")
    _require(
        Path(str(args.plan_file)).resolve() == PLAN_PATH,
        "v15r3_execute_plan_file_not_fixed",
    )
    _require(bool(args.confirm_plan_sha256), "v15r3_execute_plan_hash_required")
    print(
        json.dumps(
            execute_v15r3_plan(
                plan_path=PLAN_PATH,
                confirmed_plan_sha256=str(args.confirm_plan_sha256),
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
