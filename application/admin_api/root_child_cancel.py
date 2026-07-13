"""Crash-safe semantic claims for root-scoped first-child cancellation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
from threading import RLock
from typing import Any, Callable, Literal, Mapping
import uuid

from pydantic import BaseModel, ConfigDict, Field


ROOT_CHILD_CANCEL_ROUTE = (
    "/api/v1/orders/{root_client_order_id}/fill-follow-up/child-cancel"
)
ROOT_CHILD_CANCEL_SERVICE_METHOD = (
    "cancel_order_fill_follow_up_child_by_root_client_order_id"
)
CONTROLLED_V15_PLAN_PATH_ENV = "COINBASE_ADMIN_API_CONTROLLED_V15_PLAN_PATH"
CONTROLLED_V15_PLAN_SHA256_ENV = (
    "COINBASE_ADMIN_API_CONTROLLED_V15_PLAN_SHA256"
)
CONTROLLED_V15_MARKER_PATH_ENV = (
    "COINBASE_ADMIN_API_CONTROLLED_V15_MARKER_PATH"
)
CONTROLLED_V15_HANDOFF_PATH_ENV = (
    "COINBASE_ADMIN_API_CONTROLLED_V15_HANDOFF_PATH"
)
MAX_AUTHORITY_FILE_BYTES = 1_000_000
MAX_CLAIM_FILE_BYTES = 1_000_000
CONTROLLED_V15_PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "authority_kind",
        "approval_id",
        "batch_id",
        "created_at",
        "expires_at",
        "backend_production_commit",
        "backend_runner_commit",
        "frontend_commit",
        "runner_sha256",
        "v14_completion_binding",
        "profile_label",
        "portfolio_id",
        "product_id",
        "root_operator_intent",
        "child_reveal_operator_intent",
        "child_cancel_operator_intent",
        "placement_attempt_count",
        "root_placement_maximum",
        "child_placement_maximum",
        "cancel_command_maximum",
        "placement_attempt_schedule",
        "root_submitted_cap_usdc",
        "child_submitted_cap_usdc",
        "slice_reference_cap_usdc",
        "root_reference_notional_usdc",
        "child_reference_reserve_usdc",
        "planned_reference_notional_usdc",
        "conservative_reference_notional_usdc",
        "best_bid_at_plan",
        "best_ask_at_plan",
        "market_observed_at_plan",
        "market_source_at_plan",
        "root",
        "child",
        "cancel_command",
        "retry_authorized",
        "substitution_authorized",
        "later_child_authorized",
        "browser_derives_child_identity",
        "exchange_order_id_evidence_only",
        "plan_sha256",
    }
)
CONTROLLED_V15R2_AUTHORITY_KIND = (
    "selected_chain_child_cancel_recovery_v15r2"
)
CONTROLLED_V15R3_AUTHORITY_KIND = (
    "selected_chain_child_cancel_recovery_v15r3"
)
CONTROLLED_V15R4_AUTHORITY_KIND = (
    "selected_chain_child_cancel_recovery_v15r4"
)
CONTROLLED_V15R5_AUTHORITY_KIND = (
    "selected_chain_child_cancel_recovery_v15r5"
)
CONTROLLED_V15R2_PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "authority_kind",
        "approval_id",
        "batch_id",
        "created_at",
        "expires_at",
        "backend_commit",
        "frontend_commit",
        "runner_sha256",
        "v15r1_recovery_binding",
        "local_hidden_child_binding",
        "profile_label",
        "portfolio_id",
        "product_id",
        "placement_attempt_count",
        "placement_attempt_schedule",
        "root_placement_maximum",
        "child_placement_maximum",
        "cancel_command_maximum",
        "root_placement_authorized",
        "root_reference_cap_usdc",
        "root_actual_reference_notional_usdc",
        "child_submitted_cap_usdc",
        "slice_reference_cap_usdc",
        "planned_reference_notional_usdc",
        "conservative_reference_notional_usdc",
        "root_evidence",
        "child",
        "child_reveal_operator_intent",
        "child_cancel_operator_intent",
        "cancel_command",
        "retry_authorized",
        "substitution_authorized",
        "later_child_authorized",
        "browser_derives_child_identity",
        "exchange_order_id_evidence_only",
        "plan_sha256",
    }
)
CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID = (
    "e4ad814e-c0d1-521a-a8c5-458243935ad2"
)
CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID = (
    "e403d359-ecf3-59dc-b5b0-dfdd3c3efdaf"
)
CONTROLLED_V15R2_ROOT_EXCHANGE_ORDER_ID = (
    "9eb2038c-5059-434c-a117-62ea0b804837"
)
CONTROLLED_V15R1_PLAN_SHA256 = (
    "24fc4e211d87c7c3a95d87002f9894ff3119f1e08a48aa4d1ab68c00c7f138ed"
)
CONTROLLED_V15R1_BATCH_ID = "fb2ca86c-7ff3-5493-a1bd-d3a73fc1e322"
CONTROLLED_V15R2_ROOT_FILLED_SIZE = Decimal("0.00001583")
CONTROLLED_V15R2_ROOT_FILLED_VALUE = Decimal("1.0075796583")
CONTROLLED_V15R1_DIRECT_FILL_PROOF_KEY = (
    "spot_fill_readback:e4ad814e-c0d1-521a-a8c5-458243935ad2:"
    "audit-18ecf7f4-a489-5f3f-968f-4ce8167cdc90"
)
CONTROLLED_V15R1_DIRECT_FILL_PROOF_SHA256 = (
    "f8428444e8b2a6193ef49bd76d1e4d1fa8178f31ee492ef48368d3920f48bfad"
)
CONTROLLED_V15R1_SOURCE_PATHS = {
    "plan_path": (
        "/home/ec2-user/.local/state/"
        "coinbase-controlled-spot-child-cancel-v15r1-20260713.plan.json"
    ),
    "marker_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713."
        "authority.json"
    ),
    "ledger_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713."
        "placements.jsonl"
    ),
    "cancel_ledger_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713."
        "cancel-command.jsonl"
    ),
    "backend_claim_log_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713."
        "backend-claims.jsonl"
    ),
    "handoff_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713."
        "handoff.json"
    ),
    "audit_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T012938Z-24703c84/audit.jsonl"
    ),
    "sentinel_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T012938Z-24703c84/"
        "sdk-boundary-sentinel.json"
    ),
    "parent_authority_loss_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T012938Z-24703c84/"
        "parent-authority-loss.json"
    ),
}
CONTROLLED_V15R1_SOURCE_HASHES = {
    "plan_bytes_sha256": (
        "f9f79ba28444de532352200afa0703e01838e7b674cd849e287735d17dac7c08"
    ),
    "marker_bytes_sha256": (
        "ed9ab94189b2eb0e2b665a0c0784b01b2b948cee12d8fb8af8d8a03a6a238511"
    ),
    "ledger_bytes_sha256": (
        "474f931ce453a57c1b2a0a741d2a0207d7929684e9e9bf33f25562828888770c"
    ),
    "cancel_ledger_bytes_sha256": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "backend_claim_log_bytes_sha256": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "audit_bytes_sha256": (
        "cbc8ff26e0fa23c12d51f2094543e20807181e6d5c5192ca89044c113496a1e5"
    ),
    "sentinel_bytes_sha256": (
        "6a7888eeb50b8fb2d656c9f0068f7e7fc6e1753b114cf7e80094c78a2ca80e0f"
    ),
    "parent_authority_loss_bytes_sha256": (
        "b6af47512d0261259740dc6077356580b82049f7d4dcd1d5301f8df627e1fc15"
    ),
}
CONTROLLED_V15R2_MARKER_FIELDS = frozenset(
    {
        "schema_version",
        "authority",
        "approval_id",
        "batch_id",
        "plan_file",
        "plan_sha256",
        "backend_commit",
        "frontend_commit",
        "runner_sha256",
        "profile_label",
        "portfolio_id",
        "product_id",
        "root_client_order_id",
        "child_client_order_id",
        "placement_attempt_maximum",
        "root_placement_maximum",
        "child_placement_maximum",
        "cancel_command_maximum",
        "placement_ledger_path",
        "cancel_ledger_path",
        "backend_claim_log_path",
        "handoff_path",
        "registered_at",
        "process_id",
    }
)
CONTROLLED_V15R2_HANDOFF_FIELDS = frozenset(
    {
        "schema_version",
        "authority",
        "plan_sha256",
        "batch_id",
        "root_client_order_id",
        "child_client_order_id",
        "approval_snapshot_id",
        "admission_audit_id",
        "cap_guard_decision_id",
        "reconciliation_plan_id",
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
        "command_idempotency_key",
        "payload_hash",
        "idempotency_key",
        "correlation_id",
        "recorded_at",
    }
)
CONTROLLED_V15R3_PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "authority_kind",
        "approval_id",
        "batch_id",
        "created_at",
        "expires_at",
        "backend_commit",
        "frontend_commit",
        "runner_sha256",
        "v15r2_active_child_binding",
        "local_active_child_binding",
        "profile_label",
        "portfolio_id",
        "product_id",
        "placement_attempt_count",
        "placement_attempt_schedule",
        "root_placement_maximum",
        "child_placement_maximum",
        "cancel_command_maximum",
        "root_placement_authorized",
        "child_placement_authorized",
        "root_reference_cap_usdc",
        "child_reference_cap_usdc",
        "slice_reference_cap_usdc",
        "root_actual_reference_notional_usdc",
        "active_child_reference_notional_usdc",
        "aggregate_reference_notional_usdc",
        "planned_reference_notional_usdc",
        "root_evidence",
        "child",
        "child_evidence",
        "actor_id",
        "actor_roles",
        "child_cancel_operator_intent",
        "cancel_command",
        "retry_authorized",
        "substitution_authorized",
        "later_child_authorized",
        "browser_derives_child_identity",
        "exchange_order_id_evidence_only",
        "exchange_order_id_fallback_authorized",
        "plan_sha256",
    }
)
CONTROLLED_V15R4_PLAN_FIELDS = CONTROLLED_V15R3_PLAN_FIELDS | {
    "failed_v15r3_execution_binding"
}
CONTROLLED_V15R5_PLAN_FIELDS = CONTROLLED_V15R4_PLAN_FIELDS | {
    "failed_v15r4_execution_binding"
}
CONTROLLED_V15R2_PLAN_SHA256 = (
    "0b9ab483459a986ad05200a6740a0de6dca63b6c5da197572c952ce8aef524c2"
)
CONTROLLED_V15R2_BATCH_ID = "bb88b375-66a3-5562-87bd-1e88ebceecda"
CONTROLLED_V15R2_CHILD_EXCHANGE_ORDER_ID = (
    "5bb903af-3c6e-4d0a-bd73-087f0dfead89"
)
CONTROLLED_V15R2_CHILD_LIMIT_PRICE = Decimal("107702.14")
CONTROLLED_V15R2_CHILD_REFERENCE_NOTIONAL = Decimal("1.7049248762")
CONTROLLED_V15R2_AGGREGATE_REFERENCE_NOTIONAL = Decimal("2.7125045345")
CONTROLLED_V15R2_SOURCE_PATHS = {
    "plan_path": (
        "/home/ec2-user/.local/state/"
        "coinbase-controlled-spot-child-cancel-v15r2-20260713.plan.json"
    ),
    "marker_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713."
        "authority.json"
    ),
    "placement_ledger_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713."
        "placements.jsonl"
    ),
    "cancel_ledger_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713."
        "cancel-command.jsonl"
    ),
    "backend_claim_log_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713."
        "backend-claims.jsonl"
    ),
    "handoff_path": (
        "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
        "test-profile-btc-usdc-selected-child-cancel-v15r2-20260713."
        "handoff.json"
    ),
    "sentinel_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T022339Z-301d5d02/"
        "sdk-boundary-sentinel.json"
    ),
    "progress_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T022339Z-301d5d02/"
        "v15r2-operator-ui-cancel-handoff.json"
    ),
    "idempotency_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T022339Z-301d5d02/"
        "idempotency.jsonl"
    ),
    "audit_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T022339Z-301d5d02/"
        "audit.jsonl"
    ),
    "runtime_authority_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T022339Z-301d5d02/"
        "runtime-child-authority.json"
    ),
    "runtime_authority_used_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T022339Z-301d5d02/"
        "runtime-child-authority.used.json"
    ),
    "runtime_pid_path": (
        "/home/ec2-user/coinbase/artifacts/"
        "controlled-root-child-batch-20260713T022339Z-301d5d02/"
        "embedded-runtime.pid"
    ),
}
CONTROLLED_V15R2_SOURCE_HASHES = {
    "plan_bytes_sha256": (
        "e4fd504a27eb999b42f0f5f7c2f4faa682dd75ac5c0811574d6e6937ca481c89"
    ),
    "marker_bytes_sha256": (
        "a818a49d68ebf3908a1f7d08861b1afd82d12b18128e997bdbdeb8bd3e79af1f"
    ),
    "placement_ledger_bytes_sha256": (
        "bf59dd45661d0e12c8cc3a0fda694e31b3f40a29dce05d123598d5178681ec13"
    ),
    "cancel_ledger_bytes_sha256": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "backend_claim_log_bytes_sha256": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "handoff_bytes_sha256": (
        "d0b8c04bbf09baabba242fa4a605ff19a6786361955481ff1ff736da3a55c4af"
    ),
    "sentinel_bytes_sha256": (
        "e93fe5902917f9765f6ab706cac400ad89807e3851cf465d24fe68c3595a9978"
    ),
    "progress_bytes_sha256": (
        "8aec5d1b208df79231c14d32da034ec3bc3c4e96f34c7a72cc58186327fd8254"
    ),
    "successful_child_record_canonical_sha256": (
        "63f586fedf05871a5476d0b4cf32e31a6298dde966730c45a2fc9d41f055b96d"
    ),
    "failed_cancel_record_canonical_sha256": (
        "0c9b56e031b26c6d314c9a7335c49b68042137aff2ebcfa234665df18eb66773"
    ),
    "failed_cancel_audit_canonical_sha256": (
        "645ad1950a300a8caf3ecd4110d95e6f201daff55716eda216141544e5eb1b2e"
    ),
    "runtime_authority_bytes_sha256": (
        "169b4ca1489406351b1c3c51d68e11775fe49a0a6e53eb7f2b6470b9266aa4e5"
    ),
    "runtime_authority_used_bytes_sha256": (
        "7a308f8ea028462f95304897fc210b2eae3d67770064bbfaf65a4f48d292f261"
    ),
    "runtime_pid_bytes_sha256": (
        "c518928a7dcb53c2686c6f3b6ac666e2de687e18e22e1e7d5d0c897d0c1297da"
    ),
}
CONTROLLED_V15R2_STATE_DIR = (
    "/home/ec2-user/coinbase/artifacts/"
    "controlled-root-child-batch-20260713T022339Z-301d5d02"
)
CONTROLLED_V15R2_PARENT_PROCESS_IDENTITY = {
    "process_id": 637735,
    "start_identity": "16869564",
    "uid": 1000,
    "cwd": "/home/ec2-user/coinbase",
    "cwd_sha256": (
        "8821a8c117a3e2d9fe297367217adcd83cf46c68c627d663385dafb4e8a14c62"
    ),
    "cmdline_sha256": (
        "055683e470e85d76ef39227e019bc39d4b7fcca1135d0192055d90435f09e536"
    ),
}
CONTROLLED_V15R2_RUNTIME_PROCESS_IDENTITY = {
    "process_id": 637770,
    "start_identity": "16871269",
    "uid": 1000,
    "cwd": "/home/ec2-user/coinbase",
    "cwd_sha256": (
        "8821a8c117a3e2d9fe297367217adcd83cf46c68c627d663385dafb4e8a14c62"
    ),
    "cmdline_sha256": (
        "869aaf6d4029e6675d891c077930d18d37be251a271b2bedf7d62d2fbd280b61"
    ),
}
CONTROLLED_V15R2_USED_CANCEL_IDS = frozenset(
    {
        CONTROLLED_V15R2_BATCH_ID,
        "cd7713ea-5841-5c8a-9aea-161a2eb32e31",
        "cd79b000-9c19-58dd-9ce0-537d4823bdec",
        "46341b9c-efd0-5451-805d-efd2d1cd2709",
        "6b7375fb-6d38-5164-90f0-ec81ec75c780",
        "aef54633-6cd4-4ad9-892b-7740aa27b45a",
        "6e678aff-e044-5962-9895-720b5ec528dc",
        "f24753f6-eac6-5207-9806-1b5502c0d474",
        "ed13aab8-99aa-59c2-9104-b4f02cf66dc1",
        "fba7a3ed-420e-52b9-a4c4-e3a6bbc9d865",
        "3512e3bd-5cb1-5442-8a01-4ebdc71a77a9",
        "7bc45910-0144-59a4-a006-df23ee327ebc",
        "ef26324a-c9fe-52d9-9f24-54d23fa943b7",
        "8cc92c40-def3-5c34-80c0-b40345a5bdd2",
        "30e91103-79dc-5b1c-9843-e4be3ccc2963",
        "12613395-b8d6-5fdd-9dc7-de3086de1a26",
        "9df5c983-2f13-55bc-b8f1-47beed4c7ffd",
        "c26a8f8a-4a13-5fff-ba31-19155d398eff",
        "b6aa4aba-40e1-5c47-bc76-74e3de81751e",
        "8c530163-9ca8-5fdf-8227-a69ed3580b3a",
        "d675db7e-cbe4-5872-9391-0e222ad1c36d",
        "05632c40-d7d0-5fe2-8679-d360580ac6be",
        "cad60f27-a08b-5382-9853-46a74180fc8c",
        "864a4850-09d1-5d67-84f7-ca1d239e6c0f",
        "c9446bba-a981-584a-8172-7d2b85fa38a0",
        "51cbd1c6-22fe-5f6f-a65b-c921ddd54c18",
        "b6695117-0c27-5a00-9d83-285645ab83df",
        "0371b0c7-67e4-5e77-ad69-1c340b1523b8",
        "1f64cfde-0c03-5395-9433-e206127591cf",
    }
)
_CONTROLLED_V15R3_FAILED_STATE_DIR = (
    "/home/ec2-user/coinbase/artifacts/"
    "controlled-root-child-batch-20260713T060242Z-0559cb04"
)
_CONTROLLED_V15R3_FAILED_REGISTRY_PREFIX = (
    "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
    "test-profile-btc-usdc-selected-child-cancel-v15r3-20260713"
)
CONTROLLED_V15R4_FAILED_EXECUTION_BINDING = {
    "schema_version": "1",
    "status": "failed_v15r3_proof_runtime_bound_no_live_cancel",
    "plan_sha256": (
        "189c338ebd49afb1013a0c2e54e6a228dc6e4e57707b5f0ef7487f63b5cf2302"
    ),
    "plan_bytes_sha256": (
        "dfcc3c12d8cc18c6808abc48cc8125cc24cf7494f79a5f8dff33246b25b5f6e7"
    ),
    "approval_id": (
        "controlled-child-cancel-v15r3-0f2f1920-e333-4048-9999-6d7ee6be665f"
    ),
    "batch_id": "12613395-b8d6-5fdd-9dc7-de3086de1a26",
    "backend_commit": "aeea2205a18df36019572785b1c948775c53962d",
    "runner_sha256": (
        "655964ffc3efd5701ecf39a3c2a695a394dc1421bda6a38e6f528a049de3d474"
    ),
    "cancel_command_ids": {
        "idempotency_key": "9df5c983-2f13-55bc-b8f1-47beed4c7ffd",
        "correlation_id": "c26a8f8a-4a13-5fff-ba31-19155d398eff",
        "claim_id": "b6aa4aba-40e1-5c47-bc76-74e3de81751e",
        "approval_snapshot_id": "8c530163-9ca8-5fdf-8227-a69ed3580b3a",
        "cap_guard_decision_id": "d675db7e-cbe4-5872-9391-0e222ad1c36d",
        "reconciliation_plan_id": "05632c40-d7d0-5fe2-8679-d360580ac6be",
    },
    "artifact_paths": {
        "plan": (
            "/home/ec2-user/.local/state/"
            "coinbase-controlled-spot-child-cancel-v15r3-20260713.plan.json"
        ),
        "marker": f"{_CONTROLLED_V15R3_FAILED_REGISTRY_PREFIX}.authority.json",
        "placement_ledger": (
            f"{_CONTROLLED_V15R3_FAILED_REGISTRY_PREFIX}.placements.jsonl"
        ),
        "cancel_ledger": (
            f"{_CONTROLLED_V15R3_FAILED_REGISTRY_PREFIX}.cancel-command.jsonl"
        ),
        "backend_claim_log": (
            f"{_CONTROLLED_V15R3_FAILED_REGISTRY_PREFIX}.backend-claims.jsonl"
        ),
        "runtime_transition": (
            f"{_CONTROLLED_V15R3_FAILED_REGISTRY_PREFIX}.runtime.json"
        ),
        "runtime_authority": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/runtime-child-authority.json"
        ),
        "runtime_authority_used": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/runtime-child-authority.used.json"
        ),
        "sentinel": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/sdk-boundary-sentinel.json"
        ),
        "runtime_log": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/embedded-runtime.log"
        ),
        "runtime_pid": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/embedded-runtime.pid"
        ),
        "live_service": f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/live_service.jsonl",
        "idempotency": f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/idempotency.jsonl",
        "audit": f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/audit.jsonl",
    },
    "artifact_hashes": {
        "plan": "dfcc3c12d8cc18c6808abc48cc8125cc24cf7494f79a5f8dff33246b25b5f6e7",
        "marker": "208cec96134f5037f868ecfc456849468a01c4b4fb2c72b20e11a13b66e7da2d",
        "placement_ledger": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "cancel_ledger": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "backend_claim_log": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "runtime_transition": "646464a2e25bd5d805923831b4deb6c281987978f8407be23bae50ce892d2d62",
        "runtime_authority": "0124c650bf6eac10f329d7009aafdcece91ca0b00b24ac000580602c5cce6035",
        "runtime_authority_used": "e9f27439e34e3899336811d76796f461cdc440234c05a2d61510c8d83782b4c9",
        "sentinel": "f97cebc12863187950cf79484e8072f9e2677a0761a9f266e71e88d004393ee7",
        "runtime_log": "ba92371461254c029da456fb828277612813e9821682831ebf189ab63fcf6987",
        "runtime_pid": "8617db95ac48c2cfbf3792b4c44a75b1da3c03c97b22962947ecc25ee49c4d6b",
        "live_service": "9cacf4ad3bfd2117d58f1751024541f3eae591148b4caf5fb0268199922407c1",
        "idempotency": "7a8ed1acff361593daccf0c98633d42bad940cc959d5b9aaa067e3f2a75fd79c",
        "audit": "7535a16a3dc09cf36817c1479bba00af5ce02a1085a3d62858a83c0500d9b74b",
    },
    "absent_artifact_paths": {
        "handoff": f"{_CONTROLLED_V15R3_FAILED_REGISTRY_PREFIX}.handoff.json",
        "approval_log": f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/approvals.jsonl",
        "cap_guard_log": f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/cap_guard.jsonl",
        "reconciliation_log": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/reconciliation.jsonl"
        ),
        "operator_progress": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/"
            "v15r3-operator-ui-cancel-handoff.json"
        ),
        "parent_authority_loss": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/parent-authority-loss.json"
        ),
        "failure_summary": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/controlled-batch-failure.json"
        ),
        "cleanup_summary": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/controlled-batch-cleanup.json"
        ),
        "batch_summary": (
            f"{_CONTROLLED_V15R3_FAILED_STATE_DIR}/controlled-batch-summary.json"
        ),
    },
    "transition_sha256": (
        "ef1f4cfa34f7b879b429051aae676f4003412dc2523782f7098c714a3568bb39"
    ),
    "parent_process_id": 671522,
    "runtime_process_id": 671573,
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
        "client_order_id": CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID,
        "exchange_order_id": CONTROLLED_V15R2_CHILD_EXCHANGE_ORDER_ID,
        "status": "OPEN",
        "filled_size": "0",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": 0,
        "reference_notional_usdc": "1.7049248762",
    },
}
_CONTROLLED_V15R4_FAILED_STATE_DIR = (
    "/home/ec2-user/coinbase/artifacts/"
    "controlled-root-child-batch-20260713T070801Z-3bf26cda"
)
_CONTROLLED_V15R4_FAILED_REGISTRY_PREFIX = (
    "/var/tmp/coinbase-admin-controlled-spot-root-child-batches/"
    "test-profile-btc-usdc-selected-child-cancel-v15r4-20260713"
)
CONTROLLED_V15R5_FAILED_EXECUTION_BINDING = {
    "schema_version": "1",
    "status": "failed_v15r4_service_enable_bound_no_live_cancel",
    "plan_sha256": (
        "46f4dfd9c44acb3a8b47a7833d0b3882304491cd33952e80538a43ee3e2a3852"
    ),
    "plan_bytes_sha256": (
        "4570beccbe1c79a53771116efe6aa547ffe65a39d25508dff0f7a746dad25b6e"
    ),
    "approval_id": (
        "controlled-child-cancel-v15r4-c3dcc49c-a4de-40df-964e-20048f8ef993"
    ),
    "batch_id": "cad60f27-a08b-5382-9853-46a74180fc8c",
    "backend_commit": "d44ede08d1186159d3d0cf71c001ccc365f760db",
    "runner_sha256": (
        "766d2d2221d9c3248951ebbe78be2b5d918cad1b488d5dcec87526d2b9f65b85"
    ),
    "cancel_command_ids": {
        "idempotency_key": "864a4850-09d1-5d67-84f7-ca1d239e6c0f",
        "correlation_id": "c9446bba-a981-584a-8172-7d2b85fa38a0",
        "claim_id": "51cbd1c6-22fe-5f6f-a65b-c921ddd54c18",
        "approval_snapshot_id": "b6695117-0c27-5a00-9d83-285645ab83df",
        "cap_guard_decision_id": "0371b0c7-67e4-5e77-ad69-1c340b1523b8",
        "reconciliation_plan_id": "1f64cfde-0c03-5395-9433-e206127591cf",
    },
    "proof_ids": {
        "approval_request_id": "3622b1ec-c88f-4ac6-8404-c309677be309",
        "admission_audit_id": "e7e62288-95bb-44be-8286-ebe031acde54",
    },
    "artifact_paths": {
        "plan": (
            "/home/ec2-user/.local/state/"
            "coinbase-controlled-spot-child-cancel-v15r4-20260713.plan.json"
        ),
        "marker": f"{_CONTROLLED_V15R4_FAILED_REGISTRY_PREFIX}.authority.json",
        "placement_ledger": (
            f"{_CONTROLLED_V15R4_FAILED_REGISTRY_PREFIX}.placements.jsonl"
        ),
        "cancel_ledger": (
            f"{_CONTROLLED_V15R4_FAILED_REGISTRY_PREFIX}.cancel-command.jsonl"
        ),
        "backend_claim_log": (
            f"{_CONTROLLED_V15R4_FAILED_REGISTRY_PREFIX}.backend-claims.jsonl"
        ),
        "runtime_transition": (
            f"{_CONTROLLED_V15R4_FAILED_REGISTRY_PREFIX}.runtime.json"
        ),
        "handoff": f"{_CONTROLLED_V15R4_FAILED_REGISTRY_PREFIX}.handoff.json",
        "approvals": f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/approvals.jsonl",
        "audit": f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/audit.jsonl",
        "cap_guard": f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/cap_guard.jsonl",
        "runtime_log": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/embedded-runtime.log"
        ),
        "runtime_pid": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/embedded-runtime.pid"
        ),
        "idempotency": f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/idempotency.jsonl",
        "live_service": f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/live_service.jsonl",
        "reconciliation": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/reconciliation.jsonl"
        ),
        "runtime_authority": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/runtime-child-authority.json"
        ),
        "runtime_authority_used": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/runtime-child-authority.used.json"
        ),
        "sentinel": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/sdk-boundary-sentinel.json"
        ),
    },
    "artifact_hashes": {
        "plan": "4570beccbe1c79a53771116efe6aa547ffe65a39d25508dff0f7a746dad25b6e",
        "marker": "8a142ce3383d3f64ca90c3f651db0d5ceb1bef95259c4666d2962a37ee3b60a6",
        "placement_ledger": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "cancel_ledger": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "backend_claim_log": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "runtime_transition": "817910b246598db386ba24aaec688a7f95973f4864283b38ef53314098aabeba",
        "handoff": "99f556263ab598dc34743b1880e9711c372e7400432e09ffd22c7828dced59ec",
        "approvals": "41019a362a9fad224a88bbbc1229290834faa617d745f66c3f74da30bbdd76b5",
        "audit": "b96a1ec6bf2eaabc4938a7e61a2245bf892d36a8f95daf76c490c05fe57388f7",
        "cap_guard": "7919167a873b41c314f5ef3acf0f26ac97b6736e59105157d77c6f1c01002f99",
        "runtime_log": "3c7b692f088cc1c9fd161e54aee964f1244d7f50ecd6f938c87472bbd8688e5e",
        "runtime_pid": "9e97c91ee229d3119877d1a7d80594683529d6761d3f7c75816a567db4862369",
        "idempotency": "092f3bdd4fc4b8d566693693009ba756ffcf83b1d17195ce955bef87515bea85",
        "live_service": "840a50fe96b153d5463b44d4b05d5a1aa153bafcc2071fa9be2391c31b8376d8",
        "reconciliation": "84e5359de97c5b6216c673c1b2574d33b916725d77807c935f30a1101670a6b1",
        "runtime_authority": "4ab3275561e754ba327c3a291aefcf1f6b51537dd85aabff415c66bb97e05734",
        "runtime_authority_used": "d99d7c57a3721227e76b0bf8acb0eb81e8f20dc54f7b5ecc4022e532d72c5728",
        "sentinel": "529b912ab796e73d3ed9ee3f6ba1830cc9f484a82fbf891b76fa5161550cebab",
    },
    "absent_artifact_paths": {
        "operator_progress": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/"
            "v15r4-operator-ui-cancel-handoff.json"
        ),
        "parent_authority_loss": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/parent-authority-loss.json"
        ),
        "failure_summary": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/controlled-batch-failure.json"
        ),
        "cleanup_summary": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/controlled-batch-cleanup.json"
        ),
        "batch_summary": (
            f"{_CONTROLLED_V15R4_FAILED_STATE_DIR}/controlled-batch-summary.json"
        ),
    },
    "record_counts": {
        "approvals": 3,
        "audit": 8,
        "cap_guard": 1,
        "idempotency": 7,
        "live_service": 2,
        "reconciliation": 1,
    },
    "record_hashes": {
        "logical_cancel_admission_audit": (
            "65258f8faebcb06241ef78752f7dfe7a6dda0127a4551c3832fb55e47e52ed09"
        ),
        "admin_admission_audit_idempotency": (
            "045a9c5e872304f79b736d666efdebb182225328a5c0596080b496d50a15b416"
        ),
        "service_enable_rejection_audit": (
            "6ec0ba4d579becc9338109a58e84710c94235a0ea28283be328e7a1fc99efba4"
        ),
        "startup_disabled_service": (
            "f30e020ad6695eea948e380cc6737e7fa18d6427462b55e4654429304beaeab1"
        ),
        "cleanup_disabled_service": (
            "4ebb35ac379672461600af0db8bff93eb950260f2d2bbfa6ba301ee92853b9b8"
        ),
        "cleanup_disable_idempotency": (
            "beca86d1d2426c8387c0cd48895ad34b912f09cfa00b91e38a98a761915edcd4"
        ),
        "cleanup_disable_audit": (
            "fb2f71cfae697ca9d5642c2e537e056c2f6add366ccf785e9b5cdc0119090fef"
        ),
    },
    "transition_sha256": (
        "c29e7a7a8950c25fb66d4c179afe90bc317b774d885fc6d22cce86020e7808bd"
    ),
    "parent_process_id": 684483,
    "runtime_process_id": 684589,
    "root_sdk_call_count": 0,
    "child_sdk_call_count": 0,
    "cancel_route_call_count": 0,
    "cancel_readiness_get_count": 1,
    "semantic_claim_count": 0,
    "exchange_cancel_boundary_call_count": 0,
    "proof_chain_completed": True,
    "handoff_written": True,
    "failure_stage": "live_service_enable",
    "failure_http_status": 400,
    "failure_message": (
        "Enabled live-service decisions require a positive submitted notional cap."
    ),
    "failure_payload_sha256": (
        "ad0ba85eb5f532019619c2c7147a238f81256c69dec623de785f295ada33bbf0"
    ),
    "service_enable_rejected": True,
    "live_service_enabled": False,
    "cleanup_disable_proven": True,
    "live_exchange_submitted": False,
    "live_coinbase_orders_ran": False,
    "successor_binder_signal_attempt_count": 0,
    "successor_binder_restart_attempt_count": 0,
    "both_processes_absent": True,
    "admin_port_8787_free": True,
    "child_readback": {
        "client_order_id": CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID,
        "exchange_order_id": CONTROLLED_V15R2_CHILD_EXCHANGE_ORDER_ID,
        "status": "OPEN",
        "filled_size": "0",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": 0,
        "reference_notional_usdc": "1.7049248762",
    },
}
CONTROLLED_V15R3_MARKER_FIELDS = CONTROLLED_V15R2_MARKER_FIELDS
CONTROLLED_V15R3_HANDOFF_FIELDS = CONTROLLED_V15R2_HANDOFF_FIELDS | {
    "actor_roles"
}
CONTROLLED_V15R4_MARKER_FIELDS = CONTROLLED_V15R3_MARKER_FIELDS
CONTROLLED_V15R4_HANDOFF_FIELDS = CONTROLLED_V15R3_HANDOFF_FIELDS
CONTROLLED_V15R5_MARKER_FIELDS = CONTROLLED_V15R4_MARKER_FIELDS
CONTROLLED_V15R5_HANDOFF_FIELDS = CONTROLLED_V15R4_HANDOFF_FIELDS


class AdminRootChildCancelAuthorityError(RuntimeError):
    pass


class AdminRootChildCancelClaimStoreError(RuntimeError):
    pass


def validate_controlled_v15_plan_scope(
    plan: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    """Reject any V15 authority whose sealed live scope is not exact."""

    try:
        if set(plan) != CONTROLLED_V15_PLAN_FIELDS:
            raise ValueError("fields")
        root = plan["root"]
        child = plan["child"]
        cancel = plan["cancel_command"]
        if not all(isinstance(value, Mapping) for value in (root, child, cancel)):
            raise ValueError("objects")
        root = dict(root)
        child = dict(child)
        cancel = dict(cancel)
        root_order = root.get("order")
        child_policy = child.get("order_policy")
        if not isinstance(root_order, Mapping) or not isinstance(
            child_policy, Mapping
        ):
            raise ValueError("order_objects")
        root_order = dict(root_order)
        child_policy = dict(child_policy)

        created_at = datetime.fromisoformat(str(plan["created_at"]))
        expires_at = datetime.fromisoformat(str(plan["expires_at"]))
        if not (
            created_at.tzinfo is not None
            and expires_at.tzinfo is not None
            and expires_at - created_at == timedelta(minutes=120)
        ):
            raise ValueError("ttl")

        root_cap = Decimal(str(plan["root_submitted_cap_usdc"]))
        child_cap = Decimal(str(plan["child_submitted_cap_usdc"]))
        slice_cap = Decimal(str(plan["slice_reference_cap_usdc"]))
        root_reference = Decimal(str(plan["root_reference_notional_usdc"]))
        child_reserve = Decimal(str(plan["child_reference_reserve_usdc"]))
        planned = Decimal(str(plan["planned_reference_notional_usdc"]))
        conservative = Decimal(
            str(plan["conservative_reference_notional_usdc"])
        )
        root_size = Decimal(str(root_order["base_size"]))
        root_price = Decimal(str(root_order["limit_price"]))
        if not (
            root_cap == Decimal("9.99")
            and child_cap == Decimal("2.00")
            and slice_cap == Decimal("12.00")
            and conservative == Decimal("11.99")
            and root_reference.is_finite()
            and 0 < root_reference < root_cap
            and child_reserve == child_cap
            and planned == root_reference + child_reserve
            and planned < slice_cap
            and conservative < slice_cap
            and root_size.is_finite()
            and root_size > 0
            and root_price.is_finite()
            and root_price > 0
            and root_size * root_price == root_reference
        ):
            raise ValueError("caps")

        root_id = str(root.get("client_order_id") or "")
        expected_child_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"coinbase://filled-follow-up/{root_id}/{root_id}",
            )
        )
        if not (
            plan.get("schema_version") == "19"
            and plan.get("authority_kind")
            == "selected_chain_child_cancel_v15"
            and plan.get("profile_label") == "Test"
            and plan.get("portfolio_id")
            == "62f28f44-8e72-4fe0-ace7-d71a01f54883"
            and plan.get("product_id") == "BTC-USDC"
            and plan.get("root_operator_intent")
            == "execute_one_approved_intentional_test_profile_spot_fill"
            and plan.get("child_reveal_operator_intent")
            == "controlled_v15_test_profile_first_child_reveal"
            and plan.get("child_cancel_operator_intent")
            == "controlled_v15_test_profile_first_child_cancel"
            and plan.get("placement_attempt_count") == 2
            and plan.get("root_placement_maximum") == 1
            and plan.get("child_placement_maximum") == 1
            and plan.get("cancel_command_maximum") == 1
            and plan.get("placement_attempt_schedule") == ["root", "child"]
            and plan.get("retry_authorized") is False
            and plan.get("substitution_authorized") is False
            and plan.get("later_child_authorized") is False
            and plan.get("browser_derives_child_identity") is False
            and plan.get("exchange_order_id_evidence_only") is True
            and set(root)
            == {
                "client_order_id",
                "order",
                "approval_snapshot_id",
                "cap_guard_decision_id",
                "reconciliation_plan_id",
            }
            and set(child)
            == {
                "client_order_id",
                "parent_client_order_id",
                "order_policy",
                "approval_snapshot_id",
                "cap_guard_decision_id",
                "reconciliation_plan_id",
            }
            and isinstance(plan.get("v14_completion_binding"), Mapping)
            and plan.get("market_source_at_plan")
            == "coinbase_rest_get_best_bid_ask_exact_product"
            and all(
                len(str(plan.get(name) or "")) == length
                and all(
                    character in "0123456789abcdef"
                    for character in str(plan.get(name) or "")
                )
                for name, length in (
                    ("backend_production_commit", 40),
                    ("backend_runner_commit", 40),
                    ("frontend_commit", 40),
                    ("runner_sha256", 64),
                    ("plan_sha256", 64),
                )
            )
            and root_id
            and all(
                str(root.get(name) or "")
                for name in (
                    "approval_snapshot_id",
                    "cap_guard_decision_id",
                    "reconciliation_plan_id",
                )
            )
            and root_order
            == {
                "client_order_id": root_id,
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_type": "LIMIT",
                "base_size": root_order.get("base_size"),
                "limit_price": root_order.get("limit_price"),
                "post_only": False,
                "time_in_force": "FILL_OR_KILL",
                "manual_live_acknowledgement": True,
            }
            and child.get("client_order_id") == expected_child_id
            and child.get("parent_client_order_id") == root_id
            and all(
                str(child.get(name) or "")
                for name in (
                    "approval_snapshot_id",
                    "cap_guard_decision_id",
                    "reconciliation_plan_id",
                )
            )
            and child_policy
            == {
                "product_id": "BTC-USDC",
                "side": "SELL",
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": False,
                "base_size_source": "authoritative_root_filled_size",
                "minimum_fresh_bid_ratio": "1.60",
                "target_fresh_bid_ratio": "1.70",
                "strict_max_notional_usdc": "2.00",
            }
            and cancel
            == {
                "route": ROOT_CHILD_CANCEL_ROUTE,
                "method": "POST",
                "root_client_order_id": root_id,
                "child_client_order_id": expected_child_id,
                "identity_key": "client_order_id",
                "identity_value": root_id,
                "operator_intent": (
                    "controlled_v15_test_profile_first_child_cancel"
                ),
                "idempotency_key": cancel.get("idempotency_key"),
                "correlation_id": cancel.get("correlation_id"),
                "claim_id": cancel.get("claim_id"),
                "approval_snapshot_id": cancel.get("approval_snapshot_id"),
                "admission_audit_id_source": "route_bound_runtime_proof",
                "cap_guard_decision_id": cancel.get(
                    "cap_guard_decision_id"
                ),
                "reconciliation_plan_id": cancel.get(
                    "reconciliation_plan_id"
                ),
                "controlled_plan_sha256_source": "plan_sha256",
                "semantic_retry_policy": "same_idempotency_key_only",
            }
            and all(
                str(cancel.get(name) or "")
                for name in (
                    "idempotency_key",
                    "correlation_id",
                    "claim_id",
                    "approval_snapshot_id",
                    "cap_guard_decision_id",
                    "reconciliation_plan_id",
                )
            )
        ):
            raise ValueError("scope")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise AdminRootChildCancelAuthorityError(
            "controlled_v15_plan_schema_invalid"
        ) from exc


def is_controlled_v15r2_recovery_plan(plan: Mapping[str, Any]) -> bool:
    """Identify only the sealed child-only V15R2 recovery schema."""

    return bool(
        plan.get("schema_version") == "20"
        and plan.get("authority_kind") == CONTROLLED_V15R2_AUTHORITY_KIND
    )


def is_controlled_v15r3_recovery_plan(plan: Mapping[str, Any]) -> bool:
    """Identify only the sealed zero-placement V15R3 cancel recovery."""

    return bool(
        plan.get("schema_version") == "21"
        and plan.get("authority_kind") == CONTROLLED_V15R3_AUTHORITY_KIND
    )


def is_controlled_v15r4_recovery_plan(plan: Mapping[str, Any]) -> bool:
    """Identify only the self-describing failed-V15R3 cancel successor."""

    return bool(
        plan.get("schema_version") == "22"
        and plan.get("authority_kind") == CONTROLLED_V15R4_AUTHORITY_KIND
    )


def is_controlled_v15r5_recovery_plan(plan: Mapping[str, Any]) -> bool:
    """Identify only the failed-V15R4 cancel-only successor."""

    return bool(
        plan.get("schema_version") == "23"
        and plan.get("authority_kind") == CONTROLLED_V15R5_AUTHORITY_KIND
    )


def is_controlled_v15_cancel_only_recovery_plan(
    plan: Mapping[str, Any],
) -> bool:
    return bool(
        is_controlled_v15r3_recovery_plan(plan)
        or is_controlled_v15r4_recovery_plan(plan)
        or is_controlled_v15r5_recovery_plan(plan)
    )


def _lower_hex(value: Any, length: int) -> bool:
    text = str(value or "")
    return bool(
        len(text) == length
        and all(character in "0123456789abcdef" for character in text)
    )


def _v15r2_proof_id(batch_id: str, purpose: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "coinbase://selected-child-cancel-v15r2/"
            f"{batch_id}/{purpose}",
        )
    )


def _v15r3_proof_id(batch_id: str, purpose: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "coinbase://selected-child-cancel-v15r3/"
            f"{batch_id}/{purpose}",
        )
    )


def _v15r4_proof_id(batch_id: str, purpose: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "coinbase://selected-child-cancel-v15r4/"
            f"{batch_id}/{purpose}",
        )
    )


def _v15r5_proof_id(batch_id: str, purpose: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "coinbase://selected-child-cancel-v15r5/"
            f"{batch_id}/{purpose}",
        )
    )


def validate_controlled_v15r2_recovery_plan_scope(
    plan: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    """Reject any schema-20 recovery authority outside its sealed child."""

    del now
    try:
        if set(plan) != CONTROLLED_V15R2_PLAN_FIELDS:
            raise ValueError("fields")
        root = dict(plan["root_evidence"])
        child = dict(plan["child"])
        child_policy = dict(child["order_policy"])
        cancel = dict(plan["cancel_command"])
        recovery = dict(plan["v15r1_recovery_binding"])
        local = dict(plan["local_hidden_child_binding"])
        source_paths = dict(recovery["source_paths"])
        source_hashes = dict(recovery["source_hashes"])
        if set(root) != {
            "client_order_id",
            "exchange_order_id",
            "status",
            "filled_size",
            "filled_value",
            "placement_authorized",
        }:
            raise ValueError("root_fields")
        if set(child) != {
            "client_order_id",
            "parent_client_order_id",
            "approval_snapshot_id",
            "cap_guard_decision_id",
            "reconciliation_plan_id",
            "order_policy",
        }:
            raise ValueError("child_fields")
        if set(child_policy) != {
            "product_id",
            "side",
            "order_type",
            "time_in_force",
            "post_only",
            "base_size",
            "minimum_fresh_bid_ratio",
            "target_fresh_bid_ratio",
            "strict_max_notional_usdc",
        }:
            raise ValueError("child_policy_fields")
        if set(cancel) != {
            "route",
            "method",
            "root_client_order_id",
            "child_client_order_id",
            "identity_key",
            "identity_value",
            "operator_intent",
            "idempotency_key",
            "correlation_id",
            "claim_id",
            "approval_snapshot_id",
            "admission_audit_id_source",
            "cap_guard_decision_id",
            "reconciliation_plan_id",
            "controlled_plan_sha256_source",
            "semantic_retry_policy",
        }:
            raise ValueError("cancel_fields")
        if set(recovery) != {
            "r1_plan_sha256",
            "r1_batch_id",
            "r1_root_client_order_id",
            "r1_child_client_order_id",
            "r1_root_exchange_order_id",
            "r1_attempt_count",
            "r1_root_sdk_call_count",
            "r1_child_sdk_call_count",
            "root_filled_size",
            "root_filled_value",
            "root_fill_count",
            "fill_pagination_complete",
            "fill_pagination_proof_source",
            "active_spot_order_count",
            "handoff_absent",
            "cancel_ledgers_empty",
            "source_paths",
            "source_hashes",
            "direct_fill_proof_key",
            "direct_fill_proof_canonical_sha256",
        }:
            raise ValueError("recovery_fields")
        if set(local) != {
            "root_client_order_id",
            "root_status",
            "root_exchange_order_id",
            "root_correlation_id",
            "root_audit_id",
            "child_client_order_id",
            "child_parent_status",
            "child_size",
            "child_exchange_order_id",
            "child_correlation_id",
            "child_audit_id",
            "child_stealth_status",
            "revealed_size",
            "executed_size",
            "revealed_orders",
            "active_placement_client_order_id",
            "active_exchange_order_id",
            "preexisting_controlled_preparation_present",
            "direct_child_client_order_ids",
            "nested_child_client_order_ids",
        }:
            raise ValueError("local_fields")
        if set(source_paths) != {
            "plan_path",
            "marker_path",
            "ledger_path",
            "cancel_ledger_path",
            "backend_claim_log_path",
            "handoff_path",
            "audit_path",
            "sentinel_path",
            "parent_authority_loss_path",
        } or source_paths != CONTROLLED_V15R1_SOURCE_PATHS:
            raise ValueError("source_paths")
        if set(source_hashes) != {
            "plan_bytes_sha256",
            "marker_bytes_sha256",
            "ledger_bytes_sha256",
            "cancel_ledger_bytes_sha256",
            "backend_claim_log_bytes_sha256",
            "audit_bytes_sha256",
            "sentinel_bytes_sha256",
            "parent_authority_loss_bytes_sha256",
        } or source_hashes != CONTROLLED_V15R1_SOURCE_HASHES:
            raise ValueError("source_hashes")

        approval_id = str(plan["approval_id"])
        approval_prefix = "controlled-child-cancel-v15r2-"
        if not approval_id.startswith(approval_prefix):
            raise ValueError("approval")
        approval_uuid = uuid.UUID(approval_id.removeprefix(approval_prefix))
        if approval_uuid.version != 4:
            raise ValueError("approval_version")
        backend_commit = str(plan["backend_commit"])
        runner_sha256 = str(plan["runner_sha256"])
        expected_batch_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "coinbase://selected-child-cancel-v15r2/"
                f"{backend_commit}/{runner_sha256}/{approval_id}",
            )
        )
        batch_id = str(plan["batch_id"])
        created_at = datetime.fromisoformat(str(plan["created_at"]))
        expires_at = datetime.fromisoformat(str(plan["expires_at"]))
        root_cap = Decimal(str(plan["root_reference_cap_usdc"]))
        root_actual = Decimal(
            str(plan["root_actual_reference_notional_usdc"])
        )
        child_cap = Decimal(str(plan["child_submitted_cap_usdc"]))
        slice_cap = Decimal(str(plan["slice_reference_cap_usdc"]))
        planned = Decimal(str(plan["planned_reference_notional_usdc"]))
        conservative = Decimal(
            str(plan["conservative_reference_notional_usdc"])
        )
        root_size = Decimal(str(root["filled_size"]))
        root_value = Decimal(str(root["filled_value"]))
        local_size = Decimal(str(local["child_size"]))
        policy_size = Decimal(str(child_policy["base_size"]))
        if not (
            is_controlled_v15r2_recovery_plan(plan)
            and batch_id == expected_batch_id
            and created_at.tzinfo is not None
            and expires_at.tzinfo is not None
            and expires_at - created_at == timedelta(minutes=120)
            and _lower_hex(backend_commit, 40)
            and _lower_hex(plan.get("frontend_commit"), 40)
            and _lower_hex(runner_sha256, 64)
            and _lower_hex(plan.get("plan_sha256"), 64)
            and _canonical_plan_hash(plan) == plan.get("plan_sha256")
            and plan.get("profile_label") == "Test"
            and plan.get("portfolio_id")
            == "62f28f44-8e72-4fe0-ace7-d71a01f54883"
            and plan.get("product_id") == "BTC-USDC"
            and plan.get("placement_attempt_count") == 1
            and plan.get("placement_attempt_schedule") == ["child"]
            and plan.get("root_placement_maximum") == 0
            and plan.get("child_placement_maximum") == 1
            and plan.get("cancel_command_maximum") == 1
            and plan.get("root_placement_authorized") is False
            and root_cap == Decimal("9.99")
            and root_actual == CONTROLLED_V15R2_ROOT_FILLED_VALUE
            and child_cap == Decimal("2.00")
            and slice_cap == Decimal("12.00")
            and planned == root_actual + child_cap
            and conservative == Decimal("11.99")
            and planned < slice_cap
            and conservative < slice_cap
            and root
            == {
                "client_order_id": CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID,
                "exchange_order_id": CONTROLLED_V15R2_ROOT_EXCHANGE_ORDER_ID,
                "status": "FILLED",
                "filled_size": root.get("filled_size"),
                "filled_value": root.get("filled_value"),
                "placement_authorized": False,
            }
            and root_size == CONTROLLED_V15R2_ROOT_FILLED_SIZE
            and root_value == root_actual
            and recovery.get("r1_plan_sha256")
            == CONTROLLED_V15R1_PLAN_SHA256
            and recovery.get("r1_batch_id") == CONTROLLED_V15R1_BATCH_ID
            and recovery.get("r1_root_client_order_id")
            == CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID
            and recovery.get("r1_child_client_order_id")
            == CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID
            and recovery.get("r1_root_exchange_order_id")
            == CONTROLLED_V15R2_ROOT_EXCHANGE_ORDER_ID
            and recovery.get("r1_attempt_count") == 2
            and recovery.get("r1_root_sdk_call_count") == 1
            and recovery.get("r1_child_sdk_call_count") == 0
            and Decimal(str(recovery.get("root_filled_size"))) == root_size
            and Decimal(str(recovery.get("root_filled_value"))) == root_value
            and recovery.get("root_fill_count") == 1
            and recovery.get("fill_pagination_complete") is True
            and recovery.get("fill_pagination_proof_source")
            == "sealed_admin_fill_readback_proof_contract"
            and recovery.get("active_spot_order_count") == 0
            and recovery.get("handoff_absent") is True
            and recovery.get("cancel_ledgers_empty") is True
            and recovery.get("direct_fill_proof_key")
            == CONTROLLED_V15R1_DIRECT_FILL_PROOF_KEY
            and recovery.get("direct_fill_proof_canonical_sha256")
            == CONTROLLED_V15R1_DIRECT_FILL_PROOF_SHA256
            and local.get("root_client_order_id")
            == CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID
            and str(local.get("root_status") or "").upper() == "FILLED"
            and local.get("root_exchange_order_id")
            == CONTROLLED_V15R2_ROOT_EXCHANGE_ORDER_ID
            and bool(str(local.get("root_correlation_id") or ""))
            and bool(str(local.get("root_audit_id") or ""))
            and local.get("child_client_order_id")
            == CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID
            and str(local.get("child_parent_status") or "").upper()
            in {"PENDING", "HIDDEN"}
            and str(local.get("child_stealth_status") or "").upper()
            in {"PENDING", "HIDDEN"}
            and local_size == root_size
            and Decimal(str(local.get("revealed_size") or "0")) == 0
            and Decimal(str(local.get("executed_size") or "0")) == 0
            and local.get("revealed_orders") == []
            and not str(local.get("child_exchange_order_id") or "")
            and not str(local.get("active_placement_client_order_id") or "")
            and not str(local.get("active_exchange_order_id") or "")
            and local.get("child_correlation_id")
            == local.get("root_correlation_id")
            and local.get("child_audit_id") == local.get("root_audit_id")
            and local.get("preexisting_controlled_preparation_present") is False
            and local.get("direct_child_client_order_ids") == []
            and local.get("nested_child_client_order_ids") == []
            and child.get("client_order_id")
            == CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID
            and child.get("parent_client_order_id")
            == CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID
            and child_policy
            == {
                "product_id": "BTC-USDC",
                "side": "SELL",
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": False,
                "base_size": child_policy.get("base_size"),
                "minimum_fresh_bid_ratio": child_policy.get(
                    "minimum_fresh_bid_ratio"
                ),
                "target_fresh_bid_ratio": child_policy.get(
                    "target_fresh_bid_ratio"
                ),
                "strict_max_notional_usdc": child_policy.get(
                    "strict_max_notional_usdc"
                ),
            }
            and policy_size == root_size
            and Decimal(str(child_policy["minimum_fresh_bid_ratio"]))
            == Decimal("1.60")
            and Decimal(str(child_policy["target_fresh_bid_ratio"]))
            == Decimal("1.70")
            and Decimal(str(child_policy["strict_max_notional_usdc"]))
            == child_cap
            and child.get("approval_snapshot_id")
            == _v15r2_proof_id(batch_id, "child-reveal-approval")
            and child.get("cap_guard_decision_id")
            == _v15r2_proof_id(batch_id, "child-reveal-cap")
            and child.get("reconciliation_plan_id")
            == _v15r2_proof_id(batch_id, "child-reveal-reconciliation")
            and plan.get("child_reveal_operator_intent")
            == "controlled_v15_test_profile_first_child_reveal"
            and plan.get("child_cancel_operator_intent")
            == "controlled_v15_test_profile_first_child_cancel"
            and cancel
            == {
                "route": ROOT_CHILD_CANCEL_ROUTE,
                "method": "POST",
                "root_client_order_id": CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID,
                "child_client_order_id": CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID,
                "identity_key": "client_order_id",
                "identity_value": CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID,
                "operator_intent": "controlled_v15_test_profile_first_child_cancel",
                "idempotency_key": _v15r2_proof_id(
                    batch_id, "child-cancel-idempotency"
                ),
                "correlation_id": _v15r2_proof_id(
                    batch_id, "child-cancel-correlation"
                ),
                "claim_id": _v15r2_proof_id(batch_id, "child-cancel-claim"),
                "approval_snapshot_id": _v15r2_proof_id(
                    batch_id, "child-cancel-approval"
                ),
                "admission_audit_id_source": "route_bound_runtime_proof",
                "cap_guard_decision_id": _v15r2_proof_id(
                    batch_id, "child-cancel-cap"
                ),
                "reconciliation_plan_id": _v15r2_proof_id(
                    batch_id, "child-cancel-reconciliation"
                ),
                "controlled_plan_sha256_source": "plan_sha256",
                "semantic_retry_policy": "same_idempotency_key_only",
            }
            and plan.get("retry_authorized") is False
            and plan.get("substitution_authorized") is False
            and plan.get("later_child_authorized") is False
            and plan.get("browser_derives_child_identity") is False
            and plan.get("exchange_order_id_evidence_only") is True
        ):
            raise ValueError("scope")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise AdminRootChildCancelAuthorityError(
            "controlled_v15r2_plan_schema_invalid"
        ) from exc


def _validate_controlled_cancel_only_recovery_plan_scope(
    plan: Mapping[str, Any],
    *,
    plan_fields: frozenset[str],
    schema_version: str,
    authority_kind: str,
    approval_prefix: str,
    batch_namespace: str,
    proof_id: Callable[[str, str], str],
    semantic_retry_policy: str,
    error_code: str,
    now: datetime | None = None,
) -> None:
    """Reject cancel-only authority outside the one existing active child."""

    del now
    try:
        if set(plan) != plan_fields:
            raise ValueError("fields")
        root = dict(plan["root_evidence"])
        child = dict(plan["child"])
        child_evidence = dict(plan["child_evidence"])
        source = dict(plan["v15r2_active_child_binding"])
        local = dict(plan["local_active_child_binding"])
        cancel = dict(plan["cancel_command"])
        source_paths = dict(source["source_paths"])
        source_hashes = dict(source["source_hashes"])
        parent_process_identity = dict(source["r2_parent_process_identity"])
        runtime_process_identity = dict(source["r2_runtime_process_identity"])
        if set(root) != {
            "client_order_id",
            "exchange_order_id",
            "status",
            "filled_size",
            "filled_value",
            "placement_authorized",
        }:
            raise ValueError("root_fields")
        if set(child) != {
            "client_order_id",
            "parent_client_order_id",
            "active_exchange_order_id",
            "origin_controlled_plan_sha256",
            "origin_controlled_batch_id",
        }:
            raise ValueError("child_fields")
        if set(child_evidence) != {
            "client_order_id",
            "parent_client_order_id",
            "exchange_order_id",
            "product_id",
            "side",
            "status",
            "stealth_status",
            "base_size",
            "limit_price",
            "filled_size",
            "filled_value",
            "total_fees",
            "number_of_fills",
            "reference_notional_usdc",
            "origin_controlled_plan_sha256",
            "origin_controlled_batch_id",
            "placement_authorized",
            "exchange_order_id_evidence_only",
        }:
            raise ValueError("child_evidence_fields")
        if set(local) != {
            "root_client_order_id",
            "root_status",
            "root_exchange_order_id",
            "root_correlation_id",
            "root_audit_id",
            "child_client_order_id",
            "child_parent_status",
            "child_size",
            "child_limit_price",
            "child_exchange_order_id",
            "child_correlation_id",
            "child_audit_id",
            "child_stealth_status",
            "revealed_size",
            "executed_size",
            "remaining_size",
            "active_placement_client_order_id",
            "active_exchange_order_id",
            "active_exchange_price",
            "controlled_plan_sha256",
            "controlled_batch_id",
            "reference_notional_usdc",
            "direct_child_client_order_ids",
            "nested_child_client_order_ids",
        }:
            raise ValueError("local_fields")
        if set(source) != {
            "r2_plan_sha256",
            "r2_batch_id",
            "root_client_order_id",
            "root_exchange_order_id",
            "child_client_order_id",
            "child_exchange_order_id",
            "r2_placement_attempt_count",
            "r2_root_sdk_call_count",
            "r2_child_sdk_call_count",
            "r2_cancel_command_count",
            "child_status",
            "child_zero_fill_proven",
            "child_reference_notional_usdc",
            "aggregate_reference_notional_usdc",
            "r2_proof_payload_hash",
            "failed_cancel_idempotency_key",
            "failed_cancel_correlation_id",
            "failed_cancel_payload_hash",
            "failed_cancel_audit_id",
            "failed_cancel_http_status",
            "failed_cancel_status",
            "failed_cancel_live_exchange_submitted",
            "failed_cancel_live_coinbase_orders_ran",
            "failed_cancel_semantic_claim_acquired",
            "failed_cancel_exchange_boundary_called",
            "cancel_ledgers_empty",
            "r2_state_dir",
            "r2_parent_process_identity",
            "r2_runtime_process_identity",
            "source_paths",
            "source_hashes",
        }:
            raise ValueError("source_fields")
        if source_paths != CONTROLLED_V15R2_SOURCE_PATHS:
            raise ValueError("source_paths")
        if source_hashes != CONTROLLED_V15R2_SOURCE_HASHES:
            raise ValueError("source_hashes")
        if (
            parent_process_identity
            != CONTROLLED_V15R2_PARENT_PROCESS_IDENTITY
            or runtime_process_identity
            != CONTROLLED_V15R2_RUNTIME_PROCESS_IDENTITY
        ):
            raise ValueError("process_identity")
        if set(cancel) != {
            "route",
            "method",
            "root_client_order_id",
            "child_client_order_id",
            "active_exchange_order_id_evidence",
            "identity_key",
            "identity_value",
            "operator_intent",
            "actor_roles",
            "idempotency_key",
            "correlation_id",
            "claim_id",
            "approval_snapshot_id",
            "admission_audit_id_source",
            "cap_guard_decision_id",
            "reconciliation_plan_id",
            "controlled_plan_sha256_source",
            "semantic_retry_policy",
            "exchange_order_id_fallback_authorized",
        }:
            raise ValueError("cancel_fields")

        approval_id = str(plan["approval_id"])
        if not approval_id.startswith(approval_prefix):
            raise ValueError("approval")
        approval_uuid = uuid.UUID(approval_id.removeprefix(approval_prefix))
        if approval_uuid.version != 4:
            raise ValueError("approval_version")
        backend_commit = str(plan["backend_commit"])
        runner_sha256 = str(plan["runner_sha256"])
        expected_batch_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                batch_namespace
                + f"{backend_commit}/{runner_sha256}/{approval_id}",
            )
        )
        batch_id = str(plan["batch_id"])
        created_at = datetime.fromisoformat(str(plan["created_at"]))
        expires_at = datetime.fromisoformat(str(plan["expires_at"]))
        root_cap = Decimal(str(plan["root_reference_cap_usdc"]))
        child_cap = Decimal(str(plan["child_reference_cap_usdc"]))
        slice_cap = Decimal(str(plan["slice_reference_cap_usdc"]))
        root_actual = Decimal(
            str(plan["root_actual_reference_notional_usdc"])
        )
        child_actual = Decimal(
            str(plan["active_child_reference_notional_usdc"])
        )
        aggregate = Decimal(
            str(plan["aggregate_reference_notional_usdc"])
        )
        planned = Decimal(str(plan["planned_reference_notional_usdc"]))
        root_size = Decimal(str(root["filled_size"]))
        child_size = Decimal(str(child_evidence["base_size"]))
        child_price = Decimal(str(child_evidence["limit_price"]))
        fresh_ids = {
            str(cancel[field])
            for field in (
                "idempotency_key",
                "correlation_id",
                "claim_id",
                "approval_snapshot_id",
                "cap_guard_decision_id",
                "reconciliation_plan_id",
            )
        }
        if not (
            plan.get("schema_version") == schema_version
            and plan.get("authority_kind") == authority_kind
            and batch_id == expected_batch_id
            and created_at.tzinfo is not None
            and expires_at.tzinfo is not None
            and expires_at - created_at == timedelta(minutes=120)
            and _lower_hex(backend_commit, 40)
            and _lower_hex(plan.get("frontend_commit"), 40)
            and _lower_hex(runner_sha256, 64)
            and _lower_hex(plan.get("plan_sha256"), 64)
            and _canonical_plan_hash(plan) == plan.get("plan_sha256")
            and plan.get("profile_label") == "Test"
            and plan.get("portfolio_id")
            == "62f28f44-8e72-4fe0-ace7-d71a01f54883"
            and plan.get("product_id") == "BTC-USDC"
            and plan.get("placement_attempt_count") == 0
            and plan.get("placement_attempt_schedule") == []
            and plan.get("root_placement_maximum") == 0
            and plan.get("child_placement_maximum") == 0
            and plan.get("cancel_command_maximum") == 1
            and plan.get("root_placement_authorized") is False
            and plan.get("child_placement_authorized") is False
            and root_cap == Decimal("9.99")
            and child_cap == Decimal("2.00")
            and slice_cap == Decimal("12.00")
            and root_actual == CONTROLLED_V15R2_ROOT_FILLED_VALUE
            and child_actual == CONTROLLED_V15R2_CHILD_REFERENCE_NOTIONAL
            and aggregate == CONTROLLED_V15R2_AGGREGATE_REFERENCE_NOTIONAL
            and aggregate == root_actual + child_actual
            and planned == aggregate
            and aggregate < slice_cap
            and root
            == {
                "client_order_id": CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID,
                "exchange_order_id": CONTROLLED_V15R2_ROOT_EXCHANGE_ORDER_ID,
                "status": "FILLED",
                "filled_size": root.get("filled_size"),
                "filled_value": root.get("filled_value"),
                "placement_authorized": False,
            }
            and root_size == CONTROLLED_V15R2_ROOT_FILLED_SIZE
            and Decimal(str(root["filled_value"])) == root_actual
            and child
            == {
                "client_order_id": CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID,
                "parent_client_order_id": CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID,
                "active_exchange_order_id": (
                    CONTROLLED_V15R2_CHILD_EXCHANGE_ORDER_ID
                ),
                "origin_controlled_plan_sha256": (
                    CONTROLLED_V15R2_PLAN_SHA256
                ),
                "origin_controlled_batch_id": CONTROLLED_V15R2_BATCH_ID,
            }
            and child_evidence
            == {
                "client_order_id": CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID,
                "parent_client_order_id": CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID,
                "exchange_order_id": CONTROLLED_V15R2_CHILD_EXCHANGE_ORDER_ID,
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "OPEN",
                "stealth_status": "REVEALED",
                "base_size": child_evidence.get("base_size"),
                "limit_price": child_evidence.get("limit_price"),
                "filled_size": child_evidence.get("filled_size"),
                "filled_value": child_evidence.get("filled_value"),
                "total_fees": child_evidence.get("total_fees"),
                "number_of_fills": child_evidence.get("number_of_fills"),
                "reference_notional_usdc": child_evidence.get(
                    "reference_notional_usdc"
                ),
                "origin_controlled_plan_sha256": (
                    CONTROLLED_V15R2_PLAN_SHA256
                ),
                "origin_controlled_batch_id": CONTROLLED_V15R2_BATCH_ID,
                "placement_authorized": False,
                "exchange_order_id_evidence_only": True,
            }
            and child_size == CONTROLLED_V15R2_ROOT_FILLED_SIZE
            and child_price == CONTROLLED_V15R2_CHILD_LIMIT_PRICE
            and child_size * child_price == child_actual
            and Decimal(str(child_evidence["filled_size"])) == 0
            and Decimal(str(child_evidence["filled_value"])) == 0
            and Decimal(str(child_evidence["total_fees"])) == 0
            and int(child_evidence["number_of_fills"]) == 0
            and Decimal(str(child_evidence["reference_notional_usdc"]))
            == child_actual
            and source.get("r2_plan_sha256")
            == CONTROLLED_V15R2_PLAN_SHA256
            and source.get("r2_batch_id") == CONTROLLED_V15R2_BATCH_ID
            and source.get("root_client_order_id")
            == CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID
            and source.get("child_client_order_id")
            == CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID
            and source.get("root_exchange_order_id")
            == CONTROLLED_V15R2_ROOT_EXCHANGE_ORDER_ID
            and source.get("child_exchange_order_id")
            == CONTROLLED_V15R2_CHILD_EXCHANGE_ORDER_ID
            and source.get("r2_placement_attempt_count") == 1
            and source.get("r2_root_sdk_call_count") == 0
            and source.get("r2_child_sdk_call_count") == 1
            and source.get("r2_cancel_command_count") == 0
            and source.get("child_status") == "OPEN"
            and source.get("child_zero_fill_proven") is True
            and Decimal(str(source.get("child_reference_notional_usdc")))
            == child_actual
            and Decimal(str(source.get("aggregate_reference_notional_usdc")))
            == aggregate
            and source.get("r2_proof_payload_hash")
            == "47ea2b0bdec88367454689f1a287b28bc17a353e8362a71473a9e84da39ced05"
            and source.get("failed_cancel_idempotency_key")
            == "cd7713ea-5841-5c8a-9aea-161a2eb32e31"
            and source.get("failed_cancel_correlation_id")
            == "cd79b000-9c19-58dd-9ce0-537d4823bdec"
            and source.get("failed_cancel_payload_hash")
            == "5875e395e1692d1c82c5fded7a3e80f75c568d449df9825a2593c1dfeb4769c6"
            and source.get("failed_cancel_audit_id")
            == "60018f6a-745d-4a43-9990-82b29928bbe8"
            and source.get("failed_cancel_http_status") == 501
            and source.get("failed_cancel_status") == "not_implemented"
            and source.get("failed_cancel_live_exchange_submitted") is False
            and source.get("failed_cancel_live_coinbase_orders_ran") is False
            and source.get("failed_cancel_semantic_claim_acquired") is False
            and source.get("failed_cancel_exchange_boundary_called") is False
            and source.get("cancel_ledgers_empty") is True
            and source.get("r2_state_dir") == CONTROLLED_V15R2_STATE_DIR
            and local.get("root_client_order_id")
            == CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID
            and str(local.get("root_status") or "").upper() == "FILLED"
            and local.get("root_exchange_order_id")
            == CONTROLLED_V15R2_ROOT_EXCHANGE_ORDER_ID
            and bool(str(local.get("root_correlation_id") or ""))
            and bool(str(local.get("root_audit_id") or ""))
            and local.get("child_client_order_id")
            == CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID
            and str(local.get("child_parent_status") or "").upper() == "OPEN"
            and Decimal(str(local.get("child_size"))) == child_size
            and Decimal(str(local.get("child_limit_price"))) == child_price
            and local.get("child_exchange_order_id")
            == CONTROLLED_V15R2_CHILD_EXCHANGE_ORDER_ID
            and local.get("child_correlation_id")
            == local.get("root_correlation_id")
            and local.get("child_audit_id") == local.get("root_audit_id")
            and str(local.get("child_stealth_status") or "").upper()
            == "REVEALED"
            and Decimal(str(local.get("revealed_size"))) == child_size
            and Decimal(str(local.get("executed_size"))) == 0
            and Decimal(str(local.get("remaining_size"))) == 0
            and local.get("active_placement_client_order_id")
            == CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID
            and local.get("active_exchange_order_id")
            == CONTROLLED_V15R2_CHILD_EXCHANGE_ORDER_ID
            and Decimal(str(local.get("active_exchange_price")))
            == child_price
            and local.get("controlled_plan_sha256")
            == CONTROLLED_V15R2_PLAN_SHA256
            and local.get("controlled_batch_id") == CONTROLLED_V15R2_BATCH_ID
            and Decimal(str(local.get("reference_notional_usdc")))
            == child_actual
            and local.get("direct_child_client_order_ids") == []
            and local.get("nested_child_client_order_ids") == []
            and plan.get("actor_id") == "operator-controlled-spot-proof"
            and plan.get("actor_roles") == ["trader"]
            and plan.get("child_cancel_operator_intent")
            == "controlled_v15_test_profile_first_child_cancel"
            and cancel
            == {
                "route": ROOT_CHILD_CANCEL_ROUTE,
                "method": "POST",
                "root_client_order_id": CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID,
                "child_client_order_id": CONTROLLED_V15R2_CHILD_CLIENT_ORDER_ID,
                "active_exchange_order_id_evidence": (
                    CONTROLLED_V15R2_CHILD_EXCHANGE_ORDER_ID
                ),
                "identity_key": "client_order_id",
                "identity_value": CONTROLLED_V15R2_ROOT_CLIENT_ORDER_ID,
                "operator_intent": (
                    "controlled_v15_test_profile_first_child_cancel"
                ),
                "actor_roles": ["trader"],
                "idempotency_key": proof_id(
                    batch_id, "child-cancel-idempotency"
                ),
                "correlation_id": proof_id(
                    batch_id, "child-cancel-correlation"
                ),
                "claim_id": proof_id(
                    batch_id, "child-cancel-claim"
                ),
                "approval_snapshot_id": proof_id(
                    batch_id, "child-cancel-approval"
                ),
                "admission_audit_id_source": "route_bound_runtime_proof",
                "cap_guard_decision_id": proof_id(
                    batch_id, "child-cancel-cap"
                ),
                "reconciliation_plan_id": proof_id(
                    batch_id, "child-cancel-reconciliation"
                ),
                "controlled_plan_sha256_source": "plan_sha256",
                "semantic_retry_policy": semantic_retry_policy,
                "exchange_order_id_fallback_authorized": False,
            }
            and len(fresh_ids) == 6
            and batch_id not in CONTROLLED_V15R2_USED_CANCEL_IDS
            and not fresh_ids.intersection(CONTROLLED_V15R2_USED_CANCEL_IDS)
            and plan.get("retry_authorized") is False
            and plan.get("substitution_authorized") is False
            and plan.get("later_child_authorized") is False
            and plan.get("browser_derives_child_identity") is False
            and plan.get("exchange_order_id_evidence_only") is True
            and plan.get("exchange_order_id_fallback_authorized") is False
        ):
            raise ValueError("scope")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise AdminRootChildCancelAuthorityError(error_code) from exc


def validate_controlled_v15r3_recovery_plan_scope(
    plan: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    _validate_controlled_cancel_only_recovery_plan_scope(
        plan,
        plan_fields=CONTROLLED_V15R3_PLAN_FIELDS,
        schema_version="21",
        authority_kind=CONTROLLED_V15R3_AUTHORITY_KIND,
        approval_prefix="controlled-child-cancel-v15r3-",
        batch_namespace="coinbase://selected-child-cancel-v15r3/",
        proof_id=_v15r3_proof_id,
        semantic_retry_policy="fresh_v15r3_idempotency_key_exactly_once",
        error_code="controlled_v15r3_plan_schema_invalid",
        now=now,
    )


def validate_controlled_v15r4_recovery_plan_scope(
    plan: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    try:
        if (
            plan.get("failed_v15r3_execution_binding")
            != CONTROLLED_V15R4_FAILED_EXECUTION_BINDING
        ):
            raise ValueError("failed_v15r3_execution_binding")
        _validate_controlled_cancel_only_recovery_plan_scope(
            plan,
            plan_fields=CONTROLLED_V15R4_PLAN_FIELDS,
            schema_version="22",
            authority_kind=CONTROLLED_V15R4_AUTHORITY_KIND,
            approval_prefix="controlled-child-cancel-v15r4-",
            batch_namespace="coinbase://selected-child-cancel-v15r4/",
            proof_id=_v15r4_proof_id,
            semantic_retry_policy="fresh_v15r4_idempotency_key_exactly_once",
            error_code="controlled_v15r4_plan_schema_invalid",
            now=now,
        )
    except (AdminRootChildCancelAuthorityError, TypeError, ValueError) as exc:
        raise AdminRootChildCancelAuthorityError(
            "controlled_v15r4_plan_schema_invalid"
        ) from exc


def validate_controlled_v15r5_recovery_plan_scope(
    plan: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    try:
        if (
            plan.get("failed_v15r3_execution_binding")
            != CONTROLLED_V15R4_FAILED_EXECUTION_BINDING
        ):
            raise ValueError("failed_v15r3_execution_binding")
        if (
            plan.get("failed_v15r4_execution_binding")
            != CONTROLLED_V15R5_FAILED_EXECUTION_BINDING
        ):
            raise ValueError("failed_v15r4_execution_binding")
        _validate_controlled_cancel_only_recovery_plan_scope(
            plan,
            plan_fields=CONTROLLED_V15R5_PLAN_FIELDS,
            schema_version="23",
            authority_kind=CONTROLLED_V15R5_AUTHORITY_KIND,
            approval_prefix="controlled-child-cancel-v15r5-",
            batch_namespace="coinbase://selected-child-cancel-v15r5/",
            proof_id=_v15r5_proof_id,
            semantic_retry_policy="fresh_v15r5_idempotency_key_exactly_once",
            error_code="controlled_v15r5_plan_schema_invalid",
            now=now,
        )
    except (AdminRootChildCancelAuthorityError, TypeError, ValueError) as exc:
        raise AdminRootChildCancelAuthorityError(
            "controlled_v15r5_plan_schema_invalid"
        ) from exc


def validate_controlled_child_cancel_plan_scope(
    plan: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    """Dispatch without broadening either sealed authority schema."""

    if is_controlled_v15r5_recovery_plan(plan):
        validate_controlled_v15r5_recovery_plan_scope(plan, now=now)
        return
    if is_controlled_v15r4_recovery_plan(plan):
        validate_controlled_v15r4_recovery_plan_scope(plan, now=now)
        return
    if is_controlled_v15r3_recovery_plan(plan):
        validate_controlled_v15r3_recovery_plan_scope(plan, now=now)
        return
    if is_controlled_v15r2_recovery_plan(plan):
        validate_controlled_v15r2_recovery_plan_scope(plan, now=now)
        return
    validate_controlled_v15_plan_scope(plan, now=now)


def controlled_child_cancel_root_scope(
    plan: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return the root identity container for the exact plan generation."""

    value = (
        plan.get("root_evidence")
        if (
            is_controlled_v15r2_recovery_plan(plan)
            or is_controlled_v15_cancel_only_recovery_plan(plan)
        )
        else plan.get("root")
    )
    return value if isinstance(value, Mapping) else {}


def _canonical_plan_hash(plan: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_owner_only_regular_file(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AdminRootChildCancelAuthorityError(
            f"{label}_open_failed"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and metadata.st_mode & 0o077 == 0
            and metadata.st_size <= maximum_bytes
        ):
            raise AdminRootChildCancelAuthorityError(f"{label}_unsafe")
        raw = os.read(descriptor, maximum_bytes + 1)
        if len(raw) > maximum_bytes or len(raw) != metadata.st_size:
            raise AdminRootChildCancelAuthorityError(f"{label}_size_changed")
        return raw
    finally:
        os.close(descriptor)


def load_controlled_v15_plan_authority() -> dict[str, Any]:
    """Load the exact owner-only V15 plan and consumed marker from backend env."""

    plan_path_text = os.environ.get(CONTROLLED_V15_PLAN_PATH_ENV, "").strip()
    expected_hash = os.environ.get(CONTROLLED_V15_PLAN_SHA256_ENV, "").strip()
    marker_path_text = os.environ.get(CONTROLLED_V15_MARKER_PATH_ENV, "").strip()
    handoff_path_text = os.environ.get(
        CONTROLLED_V15_HANDOFF_PATH_ENV,
        "",
    ).strip()
    if (
        not plan_path_text
        or not marker_path_text
        or not handoff_path_text
        or len(expected_hash) != 64
    ):
        raise AdminRootChildCancelAuthorityError(
            "controlled_v15_plan_authority_unconfigured"
        )
    try:
        plan = json.loads(
            _read_owner_only_regular_file(
                Path(plan_path_text),
                maximum_bytes=MAX_AUTHORITY_FILE_BYTES,
                label="controlled_v15_plan",
            )
        )
        marker = json.loads(
            _read_owner_only_regular_file(
                Path(marker_path_text),
                maximum_bytes=MAX_AUTHORITY_FILE_BYTES,
                label="controlled_v15_marker",
            )
        )
        handoff = json.loads(
            _read_owner_only_regular_file(
                Path(handoff_path_text),
                maximum_bytes=MAX_AUTHORITY_FILE_BYTES,
                label="controlled_v15_handoff",
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdminRootChildCancelAuthorityError(
            "controlled_v15_authority_malformed"
        ) from exc
    if not all(isinstance(item, dict) for item in (plan, marker, handoff)):
        raise AdminRootChildCancelAuthorityError(
            "controlled_v15_authority_not_object"
        )
    observed_hash = str(plan.get("plan_sha256") or "")
    validate_controlled_child_cancel_plan_scope(plan)
    recovery_v15r2 = is_controlled_v15r2_recovery_plan(plan)
    recovery_v15r4 = is_controlled_v15r4_recovery_plan(plan)
    recovery_v15r5 = is_controlled_v15r5_recovery_plan(plan)
    cancel_only_recovery = is_controlled_v15_cancel_only_recovery_plan(plan)
    recovery_plan = recovery_v15r2 or cancel_only_recovery
    root_scope = controlled_child_cancel_root_scope(plan)
    try:
        created_at = datetime.fromisoformat(str(plan.get("created_at") or ""))
        expires_at = datetime.fromisoformat(str(plan.get("expires_at") or ""))
        registered_at = datetime.fromisoformat(
            str(marker.get("registered_at") or "")
        )
        execution_started_within_plan = bool(
            created_at.tzinfo is not None
            and expires_at.tzinfo is not None
            and registered_at.tzinfo is not None
            and created_at <= registered_at < expires_at
        )
    except (TypeError, ValueError):
        execution_started_within_plan = False
    recovery_marker_binding = True
    recovery_handoff_binding = True
    if recovery_plan:
        try:
            recorded_at = datetime.fromisoformat(
                str(handoff.get("recorded_at") or "")
            )
            expected_marker_fields = (
                (
                    CONTROLLED_V15R5_MARKER_FIELDS
                    if recovery_v15r5
                    else (
                        CONTROLLED_V15R4_MARKER_FIELDS
                        if recovery_v15r4
                        else CONTROLLED_V15R3_MARKER_FIELDS
                    )
                )
                if cancel_only_recovery
                else CONTROLLED_V15R2_MARKER_FIELDS
            )
            expected_handoff_fields = (
                (
                    CONTROLLED_V15R5_HANDOFF_FIELDS
                    if recovery_v15r5
                    else (
                        CONTROLLED_V15R4_HANDOFF_FIELDS
                        if recovery_v15r4
                        else CONTROLLED_V15R3_HANDOFF_FIELDS
                    )
                )
                if cancel_only_recovery
                else CONTROLLED_V15R2_HANDOFF_FIELDS
            )
            expected_authority_kind = (
                (
                    CONTROLLED_V15R5_AUTHORITY_KIND
                    if recovery_v15r5
                    else (
                        CONTROLLED_V15R4_AUTHORITY_KIND
                        if recovery_v15r4
                        else CONTROLLED_V15R3_AUTHORITY_KIND
                    )
                )
                if cancel_only_recovery
                else CONTROLLED_V15R2_AUTHORITY_KIND
            )
            expected_placement_maximum = 0 if cancel_only_recovery else 1
            expected_child_maximum = 0 if cancel_only_recovery else 1
            recovery_marker_binding = bool(
                set(marker) == expected_marker_fields
                and marker.get("schema_version") == "1"
                and marker.get("authority")
                == expected_authority_kind
                and marker.get("approval_id") == plan.get("approval_id")
                and marker.get("plan_file") == plan_path_text
                and marker.get("backend_commit")
                == plan.get("backend_commit")
                and marker.get("frontend_commit")
                == plan.get("frontend_commit")
                and marker.get("runner_sha256")
                == plan.get("runner_sha256")
                and marker.get("profile_label") == plan.get("profile_label")
                and marker.get("placement_attempt_maximum")
                == expected_placement_maximum
                and marker.get("root_placement_maximum") == 0
                and marker.get("child_placement_maximum")
                == expected_child_maximum
                and marker.get("cancel_command_maximum") == 1
                and marker.get("handoff_path") == handoff_path_text
                and all(
                    Path(str(marker.get(field) or "")).is_absolute()
                    for field in (
                        "placement_ledger_path",
                        "cancel_ledger_path",
                        "backend_claim_log_path",
                        "handoff_path",
                    )
                )
                and isinstance(marker.get("process_id"), int)
                and not isinstance(marker.get("process_id"), bool)
                and int(marker["process_id"]) > 0
            )
            recovery_handoff_binding = bool(
                set(handoff) == expected_handoff_fields
                and handoff.get("schema_version") == "1"
                and handoff.get("authority")
                == expected_authority_kind
                and (
                    not cancel_only_recovery
                    or handoff.get("actor_roles") == plan.get("actor_roles")
                )
                and recorded_at.tzinfo is not None
            )
        except (TypeError, ValueError):
            recovery_marker_binding = False
            recovery_handoff_binding = False
    if not (
        expected_hash == observed_hash == _canonical_plan_hash(plan)
        and execution_started_within_plan
        and recovery_marker_binding
        and recovery_handoff_binding
        and marker.get("plan_sha256") == observed_hash
        and marker.get("batch_id") == plan.get("batch_id")
        and marker.get("root_client_order_id")
        == root_scope.get("client_order_id")
        and marker.get("child_client_order_id")
        == dict(plan.get("child") or {}).get("client_order_id")
        and marker.get("portfolio_id") == plan.get("portfolio_id")
        and marker.get("product_id") == plan.get("product_id")
        and handoff.get("plan_sha256") == observed_hash
        and handoff.get("batch_id") == plan.get("batch_id")
        and handoff.get("root_client_order_id")
        == root_scope.get("client_order_id")
        and handoff.get("child_client_order_id")
        == dict(plan.get("child") or {}).get("client_order_id")
        and handoff.get("approval_snapshot_id")
        == dict(plan.get("cancel_command") or {}).get(
            "approval_snapshot_id"
        )
        and handoff.get("cap_guard_decision_id")
        == dict(plan.get("cancel_command") or {}).get(
            "cap_guard_decision_id"
        )
        and handoff.get("reconciliation_plan_id")
        == dict(plan.get("cancel_command") or {}).get(
            "reconciliation_plan_id"
        )
        and handoff.get("route") == ROOT_CHILD_CANCEL_ROUTE
        and handoff.get("method") == "POST"
        and handoff.get("module_id") == "spot_operations"
        and handoff.get("identity_key") == "client_order_id"
        and handoff.get("identity_value")
        == root_scope.get("client_order_id")
        and handoff.get("action_class") == "live_exchange_cancel"
        and handoff.get("required_permission") == "order:cancel"
        and handoff.get("service_method")
        == ROOT_CHILD_CANCEL_SERVICE_METHOD
        and handoff.get("command_idempotency_key")
        == dict(plan.get("cancel_command") or {}).get("idempotency_key")
        and handoff.get("idempotency_key")
        == dict(plan.get("cancel_command") or {}).get("idempotency_key")
        and handoff.get("correlation_id")
        == dict(plan.get("cancel_command") or {}).get("correlation_id")
        and handoff.get("operator_intent")
        == dict(plan.get("cancel_command") or {}).get("operator_intent")
        and str(handoff.get("actor_id") or "")
        and (
            not cancel_only_recovery
            or handoff.get("actor_id") == plan.get("actor_id")
        )
        and len(str(handoff.get("payload_hash") or "")) == 64
        and all(
            character in "0123456789abcdef"
            for character in str(handoff.get("payload_hash") or "")
        )
        and all(
            str(handoff.get(field) or "")
            for field in (
                "approval_snapshot_id",
                "admission_audit_id",
                "cap_guard_decision_id",
                "reconciliation_plan_id",
            )
        )
    ):
        raise AdminRootChildCancelAuthorityError(
            "controlled_v15_plan_marker_binding_mismatch"
        )
    return {
        "plan": plan,
        "marker": marker,
        "handoff": handoff,
        "source": "owner_only_v15_plan_marker_handoff",
    }


def root_child_cancel_semantic_key(
    *,
    controlled_plan_sha256: str,
    root_client_order_id: str,
    child_client_order_id: str,
) -> str:
    """Return the immutable semantic identity for one V15 cancel action."""

    payload = {
        "child_client_order_id": str(child_client_order_id),
        "controlled_plan_sha256": str(controlled_plan_sha256),
        "root_client_order_id": str(root_client_order_id),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _explicit_decimal_zero(value: Mapping[str, Any], name: str) -> bool:
    if name not in value or value[name] is None or isinstance(value[name], bool):
        return False
    try:
        number = Decimal(str(value[name]))
    except (ArithmeticError, ValueError):
        return False
    return number.is_finite() and number == 0


def _explicit_integer_zero(value: Mapping[str, Any], name: str) -> bool:
    if name not in value or value[name] is None or isinstance(value[name], bool):
        return False
    try:
        number = Decimal(str(value[name]))
        return number.is_finite() and number == 0 and int(str(value[name])) == 0
    except (ArithmeticError, ValueError):
        return False


class AdminRootChildCancelClaimRecord(BaseModel):
    """One append-only claim or outcome event for a semantic cancel."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    event: Literal["claim", "exchange_boundary", "outcome"]
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    semantic_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    controlled_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    root_client_order_id: str = Field(min_length=1)
    child_client_order_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    correlation_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    outcome: Literal["claimed", "accepted", "rejected", "unknown"]
    response: dict[str, Any] | None = None
    reconciliation_required: bool = False
    source: str = "admin_api_root_child_cancel_claim_log"


class FileAdminRootChildCancelClaimStore:
    """Owner-only append log with an atomic cross-process claim boundary."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_ROOT_CHILD_CANCEL_CLAIM_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_root_child_cancel_claims.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    @staticmethod
    def _records_from_bytes(raw: bytes) -> list[AdminRootChildCancelClaimRecord]:
        if raw and not raw.endswith(b"\n"):
            raise AdminRootChildCancelClaimStoreError(
                "root_child_cancel_claim_log_truncated"
            )
        records: list[AdminRootChildCancelClaimRecord] = []
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise AdminRootChildCancelClaimStoreError(
                "root_child_cancel_claim_log_not_utf8"
            ) from exc
        for line in lines:
            if not line.strip():
                raise AdminRootChildCancelClaimStoreError(
                    "root_child_cancel_claim_log_blank_row"
                )
            try:
                records.append(
                    AdminRootChildCancelClaimRecord.model_validate_json(line)
                )
            except ValueError as exc:
                raise AdminRootChildCancelClaimStoreError(
                    "root_child_cancel_claim_log_malformed_row"
                ) from exc
        FileAdminRootChildCancelClaimStore._validate_record_sequences(records)
        return records

    @staticmethod
    def _record_identity(
        record: AdminRootChildCancelClaimRecord,
    ) -> tuple[str, ...]:
        return (
            record.semantic_key,
            record.controlled_plan_sha256,
            record.root_client_order_id,
            record.child_client_order_id,
            record.idempotency_key,
            record.payload_hash,
            record.correlation_id,
            record.actor_id,
        )

    @staticmethod
    def _validate_response_identity(
        record: AdminRootChildCancelClaimRecord,
    ) -> None:
        response = record.response
        if not isinstance(response, Mapping):
            raise AdminRootChildCancelClaimStoreError(
                "root_child_cancel_claim_response_identity_invalid"
            )
        data = response.get("data")
        data = data if isinstance(data, Mapping) else {}
        readiness = data.get("readiness")
        readiness = readiness if isinstance(readiness, Mapping) else {}
        if not (
            str(response.get("client_order_id") or "")
            == record.root_client_order_id
            and str(response.get("stealth_order_id") or "")
            == record.child_client_order_id
            and str(response.get("idempotency_key") or "")
            == record.idempotency_key
            and str(response.get("correlation_id") or "")
            == record.correlation_id
            and str(
                data.get("controlled_plan_sha256")
                or readiness.get("controlled_plan_sha256")
                or ""
            )
            == record.controlled_plan_sha256
        ):
            raise AdminRootChildCancelClaimStoreError(
                "root_child_cancel_claim_response_identity_invalid"
            )
        if record.outcome != "accepted":
            return
        readback = data.get("cancellation_readback")
        readback = readback if isinstance(readback, Mapping) else {}
        matched = readback.get("matched_order")
        matched = matched if isinstance(matched, Mapping) else {}
        local = data.get("local_reconciliation")
        local = local if isinstance(local, Mapping) else {}
        zero = data.get("terminal_zero_fill")
        zero = zero if isinstance(zero, Mapping) else {}
        if not (
            response.get("status") == "accepted"
            and readback.get("authoritative") is True
            and readback.get("pagination_complete") is True
            and readback.get("exact_identity_match") is True
            and str(readback.get("authoritative_status") or "").upper()
            == "CANCELLED"
            and str(matched.get("client_order_id") or "")
            == record.child_client_order_id
            and _explicit_decimal_zero(matched, "filled_size")
            and _explicit_decimal_zero(matched, "filled_value")
            and _explicit_decimal_zero(matched, "total_fees")
            and _explicit_integer_zero(matched, "number_of_fills")
            and str(local.get("local_status") or "").upper()
            == "CANCELLED"
            and local.get("active_placement_cleared") is True
            and _explicit_decimal_zero(local, "executed_size")
            and zero.get("proven") is True
            and _explicit_decimal_zero(zero, "filled_size")
            and _explicit_decimal_zero(zero, "filled_value")
            and _explicit_decimal_zero(zero, "total_fees")
            and _explicit_integer_zero(zero, "number_of_fills")
            and _explicit_decimal_zero(zero, "local_executed_size")
        ):
            raise AdminRootChildCancelClaimStoreError(
                "root_child_cancel_claim_accepted_zero_fill_invalid"
            )

    @staticmethod
    def _validate_record_sequences(
        records: list[AdminRootChildCancelClaimRecord],
    ) -> None:
        latest_by_semantic_key: dict[
            str, AdminRootChildCancelClaimRecord
        ] = {}
        identity_by_semantic_key: dict[str, tuple[str, ...]] = {}
        for record in records:
            try:
                recorded_at = datetime.fromisoformat(record.recorded_at)
            except ValueError as exc:
                raise AdminRootChildCancelClaimStoreError(
                    "root_child_cancel_claim_recorded_at_invalid"
                ) from exc
            if recorded_at.tzinfo is None or record.semantic_key != (
                root_child_cancel_semantic_key(
                    controlled_plan_sha256=(
                        record.controlled_plan_sha256
                    ),
                    root_client_order_id=record.root_client_order_id,
                    child_client_order_id=record.child_client_order_id,
                )
            ):
                raise AdminRootChildCancelClaimStoreError(
                    "root_child_cancel_claim_semantic_identity_invalid"
                )
            identity = FileAdminRootChildCancelClaimStore._record_identity(
                record
            )
            expected_identity = identity_by_semantic_key.get(
                record.semantic_key
            )
            if expected_identity is not None and identity != expected_identity:
                raise AdminRootChildCancelClaimStoreError(
                    "root_child_cancel_claim_identity_drift"
                )
            previous = latest_by_semantic_key.get(record.semantic_key)
            if record.event == "claim":
                valid_event = bool(
                    previous is None
                    and record.outcome == "claimed"
                    and record.response is None
                    and record.reconciliation_required is False
                )
            elif record.event == "exchange_boundary":
                valid_event = bool(
                    previous is not None
                    and previous.event == "claim"
                    and previous.outcome == "claimed"
                    and record.outcome == "unknown"
                    and record.response is None
                    and record.reconciliation_required is True
                )
            else:
                valid_event = bool(
                    previous is not None
                    and record.outcome in {
                        "accepted",
                        "rejected",
                        "unknown",
                    }
                    and (
                        record.outcome == "rejected"
                        or previous.event == "exchange_boundary"
                    )
                    and previous.event in {"claim", "exchange_boundary"}
                    and record.reconciliation_required
                    is (record.outcome == "unknown")
                )
                if valid_event:
                    FileAdminRootChildCancelClaimStore._validate_response_identity(
                        record
                    )
            if not valid_event:
                raise AdminRootChildCancelClaimStoreError(
                    "root_child_cancel_claim_sequence_invalid"
                )
            identity_by_semantic_key.setdefault(record.semantic_key, identity)
            latest_by_semantic_key[record.semantic_key] = record

    @staticmethod
    def _append_locked(
        descriptor: int,
        record: AdminRootChildCancelClaimRecord,
    ) -> None:
        encoded = (record.model_dump_json() + "\n").encode("utf-8")
        metadata = os.fstat(descriptor)
        if metadata.st_size + len(encoded) > MAX_CLAIM_FILE_BYTES:
            raise AdminRootChildCancelClaimStoreError(
                "root_child_cancel_claim_log_too_large"
            )
        os.lseek(descriptor, 0, os.SEEK_END)
        os.write(descriptor, encoded)
        os.fsync(descriptor)

    def _open(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if not (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and metadata.st_mode & 0o077 == 0
            and metadata.st_size <= MAX_CLAIM_FILE_BYTES
        ):
            os.close(descriptor)
            raise AdminRootChildCancelClaimStoreError(
                "root_child_cancel_claim_log_unsafe"
            )
        return descriptor

    @staticmethod
    def _read_locked(descriptor: int) -> list[AdminRootChildCancelClaimRecord]:
        metadata = os.fstat(descriptor)
        if metadata.st_size > MAX_CLAIM_FILE_BYTES:
            raise AdminRootChildCancelClaimStoreError(
                "root_child_cancel_claim_log_too_large"
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, MAX_CLAIM_FILE_BYTES + 1)
        if len(raw) > MAX_CLAIM_FILE_BYTES or len(raw) != metadata.st_size:
            raise AdminRootChildCancelClaimStoreError(
                "root_child_cancel_claim_log_size_changed"
            )
        return FileAdminRootChildCancelClaimStore._records_from_bytes(raw)

    def claim(
        self,
        *,
        controlled_plan_sha256: str,
        root_client_order_id: str,
        child_client_order_id: str,
        idempotency_key: str,
        payload_hash: str,
        correlation_id: str,
        actor_id: str,
    ) -> tuple[str, AdminRootChildCancelClaimRecord]:
        """Atomically claim, replay, or reject one semantic cancel identity."""

        semantic_key = root_child_cancel_semantic_key(
            controlled_plan_sha256=controlled_plan_sha256,
            root_client_order_id=root_client_order_id,
            child_client_order_id=child_client_order_id,
        )
        with self._lock:
            descriptor = self._open()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                records = self._read_locked(descriptor)
                matching = [
                    record
                    for record in records
                    if record.semantic_key == semantic_key
                ]
                if matching:
                    latest = matching[-1]
                    return self._existing_decision(
                        latest,
                        idempotency_key=idempotency_key,
                        payload_hash=payload_hash,
                        correlation_id=correlation_id,
                        actor_id=actor_id,
                    ), latest

                record = AdminRootChildCancelClaimRecord(
                    event="claim",
                    semantic_key=semantic_key,
                    controlled_plan_sha256=controlled_plan_sha256,
                    root_client_order_id=root_client_order_id,
                    child_client_order_id=child_client_order_id,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    outcome="claimed",
                )
                self._append_locked(descriptor, record)
                return "claimed", record
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    @staticmethod
    def _existing_decision(
        latest: AdminRootChildCancelClaimRecord,
        *,
        idempotency_key: str,
        payload_hash: str,
        correlation_id: str,
        actor_id: str,
    ) -> str:
        same_command = bool(
            latest.idempotency_key == idempotency_key
            and latest.payload_hash == payload_hash
            and latest.correlation_id == correlation_id
            and latest.actor_id == actor_id
        )
        if not same_command:
            return "semantic_conflict"
        if latest.event == "claim" and latest.outcome == "claimed":
            return "resume_same_key_before_boundary"
        if latest.event == "exchange_boundary" or latest.outcome == "unknown":
            return "reconcile_same_key_only"
        return "same_key_replay"

    def mark_exchange_boundary(
        self,
        claim: AdminRootChildCancelClaimRecord,
    ) -> AdminRootChildCancelClaimRecord:
        """Durably record the last safe point before the Coinbase cancel call."""

        record = claim.model_copy(
            update={
                "event": "exchange_boundary",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "outcome": "unknown",
                "response": None,
                "reconciliation_required": True,
            }
        )
        with self._lock:
            descriptor = self._open()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                records = self._read_locked(descriptor)
                matching = [
                    item
                    for item in records
                    if item.semantic_key == claim.semantic_key
                ]
                if not matching or not (
                    matching[-1].event == "claim"
                    and matching[-1].outcome == "claimed"
                    and self._record_identity(matching[-1])
                    == self._record_identity(claim)
                ):
                    raise AdminRootChildCancelClaimStoreError(
                        "root_child_cancel_claim_boundary_already_recorded_or_drifted"
                    )
                self._append_locked(descriptor, record)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
        return record

    def inspect(
        self,
        *,
        controlled_plan_sha256: str,
        root_client_order_id: str,
        child_client_order_id: str,
        idempotency_key: str,
        payload_hash: str,
        correlation_id: str,
        actor_id: str,
    ) -> tuple[str, AdminRootChildCancelClaimRecord | None]:
        """Read an existing semantic decision without creating a claim."""

        semantic_key = root_child_cancel_semantic_key(
            controlled_plan_sha256=controlled_plan_sha256,
            root_client_order_id=root_client_order_id,
            child_client_order_id=child_client_order_id,
        )
        with self._lock:
            if not self.path.exists():
                return "unclaimed", None
            descriptor = self._open()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH)
                matching = [
                    record
                    for record in self._read_locked(descriptor)
                    if record.semantic_key == semantic_key
                ]
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
        if not matching:
            return "unclaimed", None
        latest = matching[-1]
        return self._existing_decision(
            latest,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            correlation_id=correlation_id,
            actor_id=actor_id,
        ), latest

    def complete(
        self,
        claim: AdminRootChildCancelClaimRecord,
        *,
        outcome: Literal["accepted", "rejected", "unknown"],
        response: Mapping[str, Any],
    ) -> AdminRootChildCancelClaimRecord:
        """Append the durable terminal or reconciliation-required outcome."""

        record = claim.model_copy(
            update={
                "event": "outcome",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "outcome": outcome,
                "response": dict(response),
                "reconciliation_required": outcome == "unknown",
            }
        )
        self._validate_response_identity(record)
        with self._lock:
            descriptor = self._open()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                records = self._read_locked(descriptor)
                matching = [
                    item
                    for item in records
                    if item.semantic_key == claim.semantic_key
                ]
                if not matching:
                    raise AdminRootChildCancelClaimStoreError(
                        "root_child_cancel_claim_missing_before_outcome"
                    )
                latest = matching[-1]
                if not (
                    latest.event in {"claim", "exchange_boundary"}
                    and latest.outcome in {"claimed", "unknown"}
                    and self._record_identity(latest)
                    == self._record_identity(claim)
                    and (
                        outcome == "rejected"
                        or latest.event == "exchange_boundary"
                    )
                ):
                    raise AdminRootChildCancelClaimStoreError(
                        "root_child_cancel_claim_outcome_already_recorded_or_drifted"
                    )
                self._append_locked(descriptor, record)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
        return record

    def read_recent(self, *, limit: int = 100) -> list[AdminRootChildCancelClaimRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            descriptor = self._open()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH)
                records = self._read_locked(descriptor)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
        return list(reversed(records))[:normalized_limit]
