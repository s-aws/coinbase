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
from typing import Any, Literal, Mapping
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
    validate_controlled_v15_plan_scope(plan)
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
    if not (
        expected_hash == observed_hash == _canonical_plan_hash(plan)
        and execution_started_within_plan
        and marker.get("plan_sha256") == observed_hash
        and marker.get("batch_id") == plan.get("batch_id")
        and marker.get("root_client_order_id")
        == dict(plan.get("root") or {}).get("client_order_id")
        and marker.get("child_client_order_id")
        == dict(plan.get("child") or {}).get("client_order_id")
        and marker.get("portfolio_id") == plan.get("portfolio_id")
        and marker.get("product_id") == plan.get("product_id")
        and handoff.get("plan_sha256") == observed_hash
        and handoff.get("batch_id") == plan.get("batch_id")
        and handoff.get("root_client_order_id")
        == dict(plan.get("root") or {}).get("client_order_id")
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
        == dict(plan.get("root") or {}).get("client_order_id")
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
