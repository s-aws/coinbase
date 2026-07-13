"""Prepare and validate the sealed V15 selected-child cancel authority.

Preparation is deliberately read-only with respect to trading state. It may
read the Test-profile Coinbase account and local evidence, then creates only an
owner-only immutable plan. Marker, claim ledgers, runtime state, approvals, and
orders belong to the separately authorized execution phase.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import time
from typing import Any, Callable, Mapping, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from tools import run_controlled_admin_spot_root_child_batch as base


ProofFailure = base.ProofFailure
PRODUCT_ID = base.PRODUCT_ID
PROFILE_LABEL = base.PROFILE_LABEL
TEST_PORTFOLIO_ID = base.TEST_PORTFOLIO_ID
ROOT_SUBMITTED_CAP = Decimal("9.99")
CHILD_SUBMITTED_CAP = Decimal("2.00")
SLICE_REFERENCE_CAP = Decimal("12.00")
CONSERVATIVE_REFERENCE_NOTIONAL = Decimal("11.99")
PLAN_TTL = timedelta(minutes=120)
PLAN_SCHEMA_VERSION = "19"
AUTHORITY_KIND = "selected_chain_child_cancel_v15"
ROOT_OPERATOR_INTENT = base.INTENTIONAL_FILL_OPERATOR_INTENT
CHILD_REVEAL_OPERATOR_INTENT = "controlled_v15_test_profile_first_child_reveal"
CHILD_CANCEL_OPERATOR_INTENT = "controlled_v15_test_profile_first_child_cancel"

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT.parent / "coinbase-frontend"
PLAN_PATH = Path(
    "/home/ec2-user/.local/state/"
    "coinbase-controlled-spot-child-cancel-v15r1-20260713.plan.json"
)
REGISTRY_DIR = Path("/var/tmp/coinbase-admin-controlled-spot-root-child-batches")
MARKER_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.authority.json"
)
PLACEMENT_LEDGER_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.placements.jsonl"
)
CANCEL_LEDGER_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.cancel-command.jsonl"
)
BACKEND_CLAIM_LOG_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.backend-claims.jsonl"
)
HANDOFF_PATH = REGISTRY_DIR / (
    "test-profile-btc-usdc-selected-child-cancel-v15r1-20260713.handoff.json"
)

V15_PLAN_FIELDS = frozenset(
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

V14_PLAN_PATH = base.SUCCESSOR_V14_PLAN_PATH
V14_MARKER_PATH = REGISTRY_DIR / base.V14_GLOBAL_BATCH_MARKER_FILENAME
V14_LEDGER_PATH = REGISTRY_DIR / base.V14_GLOBAL_BATCH_LEDGER_FILENAME
V14_STATE_DIR = ROOT / "artifacts/controlled-root-child-batch-20260712T170233Z-b7635795"
V14_SUMMARY_PATH = V14_STATE_DIR / "controlled-batch-summary.json"
V14_SENTINEL_PATH = V14_STATE_DIR / "sdk-boundary-sentinel.json"


def _require(condition: bool, blocker: str) -> None:
    if not condition:
        raise ProofFailure(blocker)


def _sha256(path: Path) -> str:
    _require(path.is_file() and not path.is_symlink(), f"v14_artifact_missing:{path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def backend_runner_commit() -> str:
    return _git("rev-parse", "HEAD")


def backend_production_commit() -> str:
    return _git("rev-parse", "HEAD^")


def frontend_commit() -> str:
    return _git("rev-parse", "HEAD", cwd=FRONTEND_ROOT)


def runner_sha256() -> str:
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def plan_hash(plan: Mapping[str, Any]) -> str:
    return base.plan_hash(plan)


def deterministic_child_client_order_id(root_client_order_id: str) -> str:
    return base.deterministic_child_client_order_id(root_client_order_id)


def offline_v14_completion_binding_fixture() -> dict[str, Any]:
    return {
        "plan_path": str(V14_PLAN_PATH),
        "plan_bytes_sha256": "ea10b6c37129faa1813e41394babe87dd82298a0cc4ca9bf86b3f754e99b98b0",
        "plan_sha256": "77ed23bae80f023cab3b258dcf512cd283c9e959c05301c13ebf656b4aecb3e6",
        "marker_path": str(V14_MARKER_PATH),
        "marker_bytes_sha256": "74f1f8d0560432a095a255b4b7daf47de7a0b12cdcfc3ac625206368383e65e6",
        "ledger_path": str(V14_LEDGER_PATH),
        "ledger_bytes_sha256": "031e6e78400eb7371aabe30ded9bbdc3dfb2f2e14cbcf8fda963bc8b217e6a0b",
        "summary_path": str(V14_SUMMARY_PATH),
        "summary_bytes_sha256": "3d011f44b09b519fc41d15a0731da2b709de301a8e2774915c8660899d624772",
        "sentinel_path": str(V14_SENTINEL_PATH),
        "sentinel_bytes_sha256": "895dd16c7d5513e8f9264698100ac7b7894a82be78233b9ea533ac9aebd4f212",
        "backend_commit": "f8fd86310954d78da29dc5e45853d19c2453ee22",
        "runner_sha256": "e70e86b856240f3f147b19ad07e98daf9e1d05ff750c403e1750b26deb895c7e",
        "batch_id": "8dd575ef-fc61-5d63-b8bf-222d131ceca4",
        "attempt_count": 6,
        "root_placement_count": 3,
        "child_placement_count": 3,
        "completed_root_count": 10,
        "completed_child_count": 10,
        "actual_reference_notional_usdc": "29.4468020111",
        "final_active_spot_order_count": 0,
        "live_service_disabled": True,
        "shutdown_quiescent": True,
        "all_v14_authority_consumed": True,
    }


def load_v14_completion_binding() -> dict[str, Any]:
    expected = offline_v14_completion_binding_fixture()
    observed_hashes = {
        "plan_bytes_sha256": _sha256(V14_PLAN_PATH),
        "marker_bytes_sha256": _sha256(V14_MARKER_PATH),
        "ledger_bytes_sha256": _sha256(V14_LEDGER_PATH),
        "summary_bytes_sha256": _sha256(V14_SUMMARY_PATH),
        "sentinel_bytes_sha256": _sha256(V14_SENTINEL_PATH),
    }
    _require(
        all(expected[key] == value for key, value in observed_hashes.items()),
        "v14_completion_artifact_hash_mismatch",
    )
    summary = json.loads(V14_SUMMARY_PATH.read_text(encoding="utf-8"))
    _require(
        summary.get("status") == "passed"
        and summary.get("plan_sha256") == expected["plan_sha256"]
        and summary.get("backend_commit") == expected["backend_commit"]
        and summary.get("runner_sha256") == expected["runner_sha256"]
        and summary.get("batch_id") == expected["batch_id"]
        and summary.get("attempt_ledger_record_count") == expected["attempt_count"]
        and summary.get("successor_root_order_count_submitted")
        == expected["root_placement_count"]
        and summary.get("successor_child_order_count_submitted")
        == expected["child_placement_count"]
        and summary.get("proof_set_root_exchange_target_count")
        == expected["completed_root_count"]
        and summary.get("proof_set_child_exchange_target_count")
        == expected["completed_child_count"]
        and summary.get("proof_set_reference_notional_usdc")
        == expected["actual_reference_notional_usdc"]
        and summary.get("exchange_active_spot_order_count_after") == 0
        and summary.get("live_service_disabled_after") is True
        and summary.get("shutdown_quiescence_window_proven") is True,
        "v14_completion_summary_mismatch",
    )
    marker = json.loads(V14_MARKER_PATH.read_text(encoding="utf-8"))
    ledger_rows = [
        json.loads(line)
        for line in V14_LEDGER_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _require(
        marker.get("plan_sha256") == expected["plan_sha256"]
        and len(ledger_rows) == expected["attempt_count"],
        "v14_authority_consumption_mismatch",
    )
    return expected


def _canonical_decimal(value: Decimal) -> str:
    return base.decimal_text(value)


def _validate_lower_sha256(value: object, blocker: str) -> str:
    text = str(value or "")
    _require(
        len(text) == 64 and all(character in "0123456789abcdef" for character in text),
        blocker,
    )
    return text


def _validate_commit(value: object, blocker: str) -> str:
    text = str(value or "")
    _require(
        len(text) == 40 and all(character in "0123456789abcdef" for character in text),
        blocker,
    )
    return text


def _deterministic_batch_id(
    *, approval_id: str, production_commit: str, exact_runner_sha256: str
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "coinbase://selected-chain-child-cancel-v15/"
            f"{production_commit}/{exact_runner_sha256}/{approval_id}",
        )
    )


def _deterministic_root_id(batch_id: str) -> str:
    return base.deterministic_root_client_order_id(batch_id, 1)


def _deterministic_evidence_id(batch_id: str, purpose: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"coinbase://selected-chain-child-cancel-v15/{batch_id}/{purpose}"))


def _build_v15_root_order(
    preflight: Mapping[str, Any], *, batch_id: str
) -> tuple[dict[str, Any], Decimal]:
    """Use the Coinbase minimum quote with a small increment-safe buffer."""

    product = dict(preflight["product"])
    bid = Decimal(str(preflight["best_bid"]))
    ask = Decimal(str(preflight["best_ask"]))
    price_increment = Decimal(str(product["price_increment"]))
    base_increment = Decimal(str(product["base_increment"]))
    base_min_size = Decimal(str(product["base_min_size"]))
    quote_min_size = Decimal(str(product["quote_min_size"]))
    price = (
        (ask * base.PLANNED_ASK_RATIO / price_increment).to_integral_value(
            rounding=ROUND_CEILING
        )
        * price_increment
    )
    target_notional = quote_min_size * Decimal("1.01")
    size = max(
        base_min_size,
        (target_notional / price / base_increment).to_integral_value(
            rounding=ROUND_CEILING
        )
        * base_increment,
    )
    notional = size * price
    _require(ask >= bid > 0, "v15_root_market_invalid")
    _require(
        ask <= price <= ask * base.MAX_ASK_RATIO,
        "v15_root_marketable_band_failed",
    )
    _require(price % price_increment == 0, "v15_root_price_increment_failed")
    _require(size % base_increment == 0, "v15_root_base_increment_failed")
    _require(size >= base_min_size, "v15_root_base_minimum_failed")
    _require(notional >= quote_min_size, "v15_root_quote_minimum_failed")
    _require(notional < ROOT_SUBMITTED_CAP, "v15_root_notional_cap_failed")
    return (
        {
            "client_order_id": _deterministic_root_id(batch_id),
            "product_id": PRODUCT_ID,
            "side": "BUY",
            "order_type": "LIMIT",
            "base_size": _canonical_decimal(size),
            "limit_price": _canonical_decimal(price),
            "post_only": False,
            "time_in_force": "FILL_OR_KILL",
            "manual_live_acknowledgement": True,
        },
        notional,
    )


def build_execution_child_order_tuple(
    plan: Mapping[str, Any],
    *,
    filled_size: Decimal,
    fresh_market: Mapping[str, Any],
    price_increment: Decimal,
) -> dict[str, Any]:
    """Build the sole child tuple from fresh market evidence after root fill."""

    child = dict(plan.get("child") or {})
    policy = dict(child.get("order_policy") or {})
    bid = Decimal(str(fresh_market.get("best_bid") or "0"))
    price = (
        (bid * base.CHILD_TARGET_BID_RATIO / price_increment).to_integral_value(
            rounding=ROUND_CEILING
        )
        * price_increment
    )
    notional = filled_size * price
    _require(filled_size.is_finite() and filled_size > 0, "v15_child_size_invalid")
    _require(bid.is_finite() and bid > 0, "v15_child_bid_invalid")
    _require(
        price_increment.is_finite() and price_increment > 0,
        "v15_child_price_increment_invalid",
    )
    _require(price >= bid * base.CHILD_MINIMUM_BID_RATIO, "v15_child_price_distance_failed")
    _require(price % price_increment == 0, "v15_child_price_increment_failed")
    _require(
        notional > 0 and notional < CHILD_SUBMITTED_CAP,
        "v15_child_notional_cap_failed",
    )
    _require(
        policy
        == {
            "product_id": PRODUCT_ID,
            "side": "SELL",
            "order_type": "LIMIT",
            "time_in_force": "GOOD_UNTIL_CANCELLED",
            "post_only": False,
            "base_size_source": "authoritative_root_filled_size",
            "minimum_fresh_bid_ratio": _canonical_decimal(
                base.CHILD_MINIMUM_BID_RATIO
            ),
            "target_fresh_bid_ratio": _canonical_decimal(
                base.CHILD_TARGET_BID_RATIO
            ),
            "strict_max_notional_usdc": _canonical_decimal(
                CHILD_SUBMITTED_CAP
            ),
        },
        "v15_child_policy_mismatch",
    )
    return {
        "batch_id": str(plan.get("batch_id") or ""),
        "batch_slot": 1,
        "approval_snapshot_id": child.get("approval_snapshot_id"),
        "root_client_order_id": child.get("parent_client_order_id"),
        "client_order_id": child.get("client_order_id"),
        "product_id": PRODUCT_ID,
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "base_size": _canonical_decimal(filled_size),
        "limit_price": _canonical_decimal(price),
        "post_only": False,
        "reference_bid": _canonical_decimal(bid),
        "market_observed_at": str(fresh_market.get("observed_at") or ""),
        "minimum_bid_ratio": _canonical_decimal(base.CHILD_MINIMUM_BID_RATIO),
        "target_bid_ratio": _canonical_decimal(base.CHILD_TARGET_BID_RATIO),
        "price_increment": _canonical_decimal(price_increment),
        "strict_max_notional_usdc": _canonical_decimal(CHILD_SUBMITTED_CAP),
    }


def build_v15_plan(
    preflight: Mapping[str, Any],
    *,
    now: datetime | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    created_at = now or datetime.now(timezone.utc)
    _require(created_at.tzinfo is not None, "v15_created_at_timezone_missing")
    created_at = created_at.astimezone(timezone.utc)
    production_commit = _validate_commit(
        backend_production_commit(), "v15_backend_production_commit_invalid"
    )
    runner_commit = _validate_commit(
        backend_runner_commit(), "v15_backend_runner_commit_invalid"
    )
    exact_frontend_commit = _validate_commit(
        frontend_commit(), "v15_frontend_commit_invalid"
    )
    exact_runner_sha256 = _validate_lower_sha256(
        runner_sha256(), "v15_runner_sha256_invalid"
    )
    approval = approval_id or f"controlled-child-cancel-v15-{uuid4()}"
    _require(
        approval.startswith("controlled-child-cancel-v15-"),
        "v15_approval_id_namespace_invalid",
    )
    batch_id = _deterministic_batch_id(
        approval_id=approval,
        production_commit=production_commit,
        exact_runner_sha256=exact_runner_sha256,
    )
    root_id = _deterministic_root_id(batch_id)
    child_id = deterministic_child_client_order_id(root_id)
    root_order, root_notional = _build_v15_root_order(
        preflight, batch_id=batch_id
    )
    _require(
        root_order.get("client_order_id") == root_id,
        "v15_root_builder_identity_mismatch",
    )
    planned_total = root_notional + CHILD_SUBMITTED_CAP
    _require(root_notional < ROOT_SUBMITTED_CAP, "v15_root_notional_cap_failed")
    _require(planned_total < SLICE_REFERENCE_CAP, "v15_slice_reference_cap_failed")
    _require(
        CONSERVATIVE_REFERENCE_NOTIONAL < SLICE_REFERENCE_CAP,
        "v15_conservative_reference_cap_failed",
    )
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "authority_kind": AUTHORITY_KIND,
        "approval_id": approval,
        "batch_id": batch_id,
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + PLAN_TTL).isoformat(),
        "backend_production_commit": production_commit,
        "backend_runner_commit": runner_commit,
        "frontend_commit": exact_frontend_commit,
        "runner_sha256": exact_runner_sha256,
        "v14_completion_binding": load_v14_completion_binding(),
        "profile_label": PROFILE_LABEL,
        "portfolio_id": TEST_PORTFOLIO_ID,
        "product_id": PRODUCT_ID,
        "root_operator_intent": ROOT_OPERATOR_INTENT,
        "child_reveal_operator_intent": CHILD_REVEAL_OPERATOR_INTENT,
        "child_cancel_operator_intent": CHILD_CANCEL_OPERATOR_INTENT,
        "placement_attempt_count": 2,
        "root_placement_maximum": 1,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "placement_attempt_schedule": ["root", "child"],
        "root_submitted_cap_usdc": _canonical_decimal(ROOT_SUBMITTED_CAP),
        "child_submitted_cap_usdc": _canonical_decimal(CHILD_SUBMITTED_CAP),
        "slice_reference_cap_usdc": _canonical_decimal(SLICE_REFERENCE_CAP),
        "root_reference_notional_usdc": _canonical_decimal(root_notional),
        "child_reference_reserve_usdc": _canonical_decimal(
            CHILD_SUBMITTED_CAP
        ),
        "planned_reference_notional_usdc": _canonical_decimal(planned_total),
        "conservative_reference_notional_usdc": _canonical_decimal(
            CONSERVATIVE_REFERENCE_NOTIONAL
        ),
        "best_bid_at_plan": _canonical_decimal(Decimal(str(preflight["best_bid"]))),
        "best_ask_at_plan": _canonical_decimal(Decimal(str(preflight["best_ask"]))),
        "market_observed_at_plan": str(dict(preflight["market"])["observed_at"]),
        "market_source_at_plan": str(dict(preflight["market"])["source"]),
        "root": {
            "client_order_id": root_id,
            "order": root_order,
            "approval_snapshot_id": _deterministic_evidence_id(batch_id, "root-approval"),
            "cap_guard_decision_id": _deterministic_evidence_id(batch_id, "root-cap"),
            "reconciliation_plan_id": _deterministic_evidence_id(batch_id, "root-reconciliation"),
        },
        "child": {
            "client_order_id": child_id,
            "parent_client_order_id": root_id,
            "order_policy": {
                "product_id": PRODUCT_ID,
                "side": "SELL",
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": False,
                "base_size_source": "authoritative_root_filled_size",
                "minimum_fresh_bid_ratio": _canonical_decimal(
                    base.CHILD_MINIMUM_BID_RATIO
                ),
                "target_fresh_bid_ratio": _canonical_decimal(
                    base.CHILD_TARGET_BID_RATIO
                ),
                "strict_max_notional_usdc": _canonical_decimal(
                    CHILD_SUBMITTED_CAP
                ),
            },
            "approval_snapshot_id": _deterministic_evidence_id(batch_id, "child-reveal-approval"),
            "cap_guard_decision_id": _deterministic_evidence_id(batch_id, "child-reveal-cap"),
            "reconciliation_plan_id": _deterministic_evidence_id(batch_id, "child-reveal-reconciliation"),
        },
        "cancel_command": {
            "route": (
                "/api/v1/orders/{root_client_order_id}/"
                "fill-follow-up/child-cancel"
            ),
            "method": "POST",
            "root_client_order_id": root_id,
            "child_client_order_id": child_id,
            "identity_key": "client_order_id",
            "identity_value": root_id,
            "operator_intent": CHILD_CANCEL_OPERATOR_INTENT,
            "idempotency_key": _deterministic_evidence_id(batch_id, "child-cancel-idempotency"),
            "correlation_id": _deterministic_evidence_id(batch_id, "child-cancel-correlation"),
            "claim_id": _deterministic_evidence_id(batch_id, "child-cancel-claim"),
            "approval_snapshot_id": _deterministic_evidence_id(batch_id, "child-cancel-approval"),
            "admission_audit_id_source": "route_bound_runtime_proof",
            "cap_guard_decision_id": _deterministic_evidence_id(batch_id, "child-cancel-cap"),
            "reconciliation_plan_id": _deterministic_evidence_id(batch_id, "child-cancel-reconciliation"),
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


def validate_v15_plan(
    plan: Mapping[str, Any],
    *,
    expected_hash: str,
    preflight: Mapping[str, Any],
    now: datetime | None = None,
) -> None:
    _require(set(plan) == V15_PLAN_FIELDS, "v15_plan_fields_mismatch")
    supplied_hash = _validate_lower_sha256(
        plan.get("plan_sha256"), "v15_plan_stored_hash_invalid"
    )
    confirmed_hash = _validate_lower_sha256(
        expected_hash, "v15_plan_confirmation_hash_invalid"
    )
    computed_hash = plan_hash(plan)
    _require(
        secrets.compare_digest(supplied_hash, computed_hash)
        and secrets.compare_digest(confirmed_hash, computed_hash),
        "v15_plan_hash_mismatch",
    )
    _require(
        plan.get("schema_version") == PLAN_SCHEMA_VERSION
        and plan.get("authority_kind") == AUTHORITY_KIND,
        "v15_plan_authority_mismatch",
    )
    _require(
        plan.get("backend_production_commit") == backend_production_commit()
        and plan.get("backend_runner_commit") == backend_runner_commit()
        and plan.get("frontend_commit") == frontend_commit()
        and plan.get("runner_sha256") == runner_sha256(),
        "v15_plan_code_binding_mismatch",
    )
    _require(
        plan.get("v14_completion_binding") == load_v14_completion_binding(),
        "v15_plan_v14_binding_mismatch",
    )
    _require(
        plan.get("profile_label") == PROFILE_LABEL
        and plan.get("portfolio_id") == TEST_PORTFOLIO_ID
        and plan.get("product_id") == PRODUCT_ID,
        "v15_plan_scope_mismatch",
    )
    _require(
        plan.get("placement_attempt_count") == 2
        and plan.get("root_placement_maximum") == 1
        and plan.get("child_placement_maximum") == 1
        and plan.get("cancel_command_maximum") == 1
        and plan.get("placement_attempt_schedule") == ["root", "child"],
        "v15_plan_attempt_scope_mismatch",
    )
    _require(
        plan.get("retry_authorized") is False
        and plan.get("substitution_authorized") is False
        and plan.get("later_child_authorized") is False
        and plan.get("browser_derives_child_identity") is False
        and plan.get("exchange_order_id_evidence_only") is True,
        "v15_plan_broadening_boundary_mismatch",
    )
    created_at = datetime.fromisoformat(str(plan.get("created_at") or ""))
    expires_at = datetime.fromisoformat(str(plan.get("expires_at") or ""))
    current = now or datetime.now(timezone.utc)
    _require(
        created_at.tzinfo is not None
        and expires_at.tzinfo is not None
        and expires_at - created_at == PLAN_TTL
        and created_at <= current < expires_at,
        "v15_plan_expired_or_ttl_invalid",
    )
    root = dict(plan.get("root") or {})
    child = dict(plan.get("child") or {})
    cancel = dict(plan.get("cancel_command") or {})
    root_order = dict(root.get("order") or {})
    batch_id = str(plan.get("batch_id") or "")
    _require(
        root.get("client_order_id") == _deterministic_root_id(batch_id)
        and root_order.get("client_order_id") == root.get("client_order_id"),
        "v15_root_identity_mismatch",
    )
    root_notional = base.validate_prepared_root_order(
        preflight, root_order, batch_id=batch_id, slot=1
    )
    expected_child_id = deterministic_child_client_order_id(
        str(root["client_order_id"])
    )
    expected_child_policy = {
        "product_id": PRODUCT_ID,
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "post_only": False,
        "base_size_source": "authoritative_root_filled_size",
        "minimum_fresh_bid_ratio": _canonical_decimal(
            base.CHILD_MINIMUM_BID_RATIO
        ),
        "target_fresh_bid_ratio": _canonical_decimal(
            base.CHILD_TARGET_BID_RATIO
        ),
        "strict_max_notional_usdc": _canonical_decimal(CHILD_SUBMITTED_CAP),
    }
    _require(
        set(root)
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
        },
        "v15_root_or_child_fields_mismatch",
    )
    _require(
        child.get("client_order_id") == expected_child_id
        and child.get("parent_client_order_id") == root.get("client_order_id")
        and child.get("order_policy") == expected_child_policy,
        "v15_child_identity_or_tuple_mismatch",
    )
    _require(
        set(cancel)
        == {
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
        }
        and cancel.get("admission_audit_id_source")
        == "route_bound_runtime_proof"
        and root.get("approval_snapshot_id")
        == _deterministic_evidence_id(batch_id, "root-approval")
        and root.get("cap_guard_decision_id")
        == _deterministic_evidence_id(batch_id, "root-cap")
        and root.get("reconciliation_plan_id")
        == _deterministic_evidence_id(batch_id, "root-reconciliation")
        and child.get("approval_snapshot_id")
        == _deterministic_evidence_id(batch_id, "child-reveal-approval")
        and child.get("cap_guard_decision_id")
        == _deterministic_evidence_id(batch_id, "child-reveal-cap")
        and child.get("reconciliation_plan_id")
        == _deterministic_evidence_id(batch_id, "child-reveal-reconciliation")
        and cancel.get("approval_snapshot_id")
        == _deterministic_evidence_id(batch_id, "child-cancel-approval")
        and cancel.get("cap_guard_decision_id")
        == _deterministic_evidence_id(batch_id, "child-cancel-cap")
        and cancel.get("reconciliation_plan_id")
        == _deterministic_evidence_id(batch_id, "child-cancel-reconciliation")
        and cancel.get("claim_id")
        == _deterministic_evidence_id(batch_id, "child-cancel-claim")
        and cancel.get("idempotency_key")
        == _deterministic_evidence_id(batch_id, "child-cancel-idempotency")
        and cancel.get("correlation_id")
        == _deterministic_evidence_id(batch_id, "child-cancel-correlation"),
        "v15_evidence_namespace_mismatch",
    )
    _require(
        cancel.get("route")
        == (
            "/api/v1/orders/{root_client_order_id}/"
            "fill-follow-up/child-cancel"
        )
        and cancel.get("method") == "POST"
        and cancel.get("root_client_order_id") == root.get("client_order_id")
        and cancel.get("child_client_order_id") == expected_child_id
        and cancel.get("identity_key") == "client_order_id"
        and cancel.get("identity_value") == root.get("client_order_id")
        and cancel.get("controlled_plan_sha256_source") == "plan_sha256"
        and cancel.get("semantic_retry_policy") == "same_idempotency_key_only",
        "v15_cancel_command_scope_mismatch",
    )
    planned = root_notional + CHILD_SUBMITTED_CAP
    _require(
        Decimal(str(plan.get("root_submitted_cap_usdc"))) == ROOT_SUBMITTED_CAP
        and Decimal(str(plan.get("child_submitted_cap_usdc")))
        == CHILD_SUBMITTED_CAP
        and Decimal(str(plan.get("slice_reference_cap_usdc")))
        == SLICE_REFERENCE_CAP
        and Decimal(str(plan.get("root_reference_notional_usdc")))
        == root_notional
        and Decimal(str(plan.get("child_reference_reserve_usdc")))
        == CHILD_SUBMITTED_CAP
        and Decimal(str(plan.get("planned_reference_notional_usdc"))) == planned
        and Decimal(str(plan.get("conservative_reference_notional_usdc")))
        == CONSERVATIVE_REFERENCE_NOTIONAL
        and root_notional < ROOT_SUBMITTED_CAP
        and planned < SLICE_REFERENCE_CAP
        and CONSERVATIVE_REFERENCE_NOTIONAL < SLICE_REFERENCE_CAP,
        "v15_plan_cap_mismatch",
    )


def write_prepared_v15_plan(
    plan_path: Path,
    plan: Mapping[str, Any],
    *,
    marker_path: Path = MARKER_PATH,
    placement_ledger_path: Path = PLACEMENT_LEDGER_PATH,
    cancel_ledger_path: Path = CANCEL_LEDGER_PATH,
    backend_claim_log_path: Path = BACKEND_CLAIM_LOG_PATH,
    handoff_path: Path = HANDOFF_PATH,
) -> None:
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
        "v15_prepare_execution_artifact_already_present",
    )
    base.write_controlled_live_plan(plan_path, plan)
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
        "v15_prepare_created_execution_artifact",
    )


def _require_owner_only_regular_file(path: Path, blocker: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProofFailure(f"{blocker}_missing") from exc
    _require(
        stat.S_ISREG(metadata.st_mode)
        and not path.is_symlink()
        and metadata.st_uid == os.getuid()
        and metadata.st_mode & 0o077 == 0,
        f"{blocker}_unsafe",
    )
    return metadata


def _create_owner_only_empty_file(path: Path, blocker: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ProofFailure(blocker) from exc
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def initialize_v15_execution_authority(
    plan_path: Path,
    plan: Mapping[str, Any],
    *,
    expected_hash: str,
    preflight: Mapping[str, Any],
    now: datetime | None = None,
    marker_path: Path = MARKER_PATH,
    placement_ledger_path: Path = PLACEMENT_LEDGER_PATH,
    cancel_ledger_path: Path = CANCEL_LEDGER_PATH,
    backend_claim_log_path: Path | None = None,
    handoff_path: Path = HANDOFF_PATH,
) -> dict[str, Any]:
    """Consume an exact approval into fail-closed owner-only execution files."""

    validate_v15_plan(
        plan,
        expected_hash=expected_hash,
        preflight=preflight,
        now=now,
    )
    _require_owner_only_regular_file(plan_path, "v15_execution_plan")
    disk_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    _require(disk_plan == dict(plan), "v15_execution_plan_disk_mismatch")
    _require(
        all(
            not os.path.lexists(path)
            for path in (
                marker_path,
                placement_ledger_path,
                cancel_ledger_path,
                handoff_path,
            )
        ),
        "v15_execution_authority_already_consumed",
    )
    marker_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_metadata = marker_path.parent.lstat()
    _require(
        stat.S_ISDIR(parent_metadata.st_mode)
        and not marker_path.parent.is_symlink()
        and parent_metadata.st_uid == os.getuid()
        and parent_metadata.st_mode & 0o077 == 0,
        "v15_execution_registry_unsafe",
    )
    authority = {
        "schema_version": "1",
        "authority": AUTHORITY_KIND,
        "approval_id": plan["approval_id"],
        "batch_id": plan["batch_id"],
        "plan_file": str(plan_path),
        "plan_sha256": expected_hash,
        "backend_production_commit": plan["backend_production_commit"],
        "backend_runner_commit": plan["backend_runner_commit"],
        "frontend_commit": plan["frontend_commit"],
        "runner_sha256": plan["runner_sha256"],
        "profile_label": PROFILE_LABEL,
        "portfolio_id": TEST_PORTFOLIO_ID,
        "product_id": PRODUCT_ID,
        "root_client_order_id": dict(plan["root"])["client_order_id"],
        "child_client_order_id": dict(plan["child"])["client_order_id"],
        "placement_attempt_maximum": 2,
        "root_placement_maximum": 1,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "placement_ledger_path": str(placement_ledger_path),
        "cancel_ledger_path": str(cancel_ledger_path),
        **(
            {"backend_claim_log_path": str(backend_claim_log_path)}
            if backend_claim_log_path is not None
            else {}
        ),
        "handoff_path": str(handoff_path),
        "registered_at": (now or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        ).isoformat(),
        "process_id": os.getpid(),
    }
    # The marker is deliberately first: any later partial initialization burns
    # this authority rather than leaving a second execution opportunity.
    base._write_owner_only_exclusive_json(
        marker_path,
        authority,
        exists_blocker="v15_execution_authority_already_consumed",
    )
    _create_owner_only_empty_file(
        placement_ledger_path, "v15_placement_ledger_create_failed"
    )
    _create_owner_only_empty_file(
        cancel_ledger_path, "v15_cancel_ledger_create_failed"
    )
    _require_owner_only_regular_file(marker_path, "v15_execution_marker")
    _require_owner_only_regular_file(
        placement_ledger_path, "v15_execution_placement_ledger"
    )
    _require_owner_only_regular_file(
        cancel_ledger_path, "v15_execution_cancel_ledger"
    )
    return authority


def authorize_v15_execution(
    plan_path: Path,
    *,
    expected_hash: str,
    preflight: Mapping[str, Any],
    active_zero: Mapping[str, Any],
    fresh_ids: Mapping[str, Any],
    now: datetime | None = None,
    marker_path: Path = MARKER_PATH,
    placement_ledger_path: Path = PLACEMENT_LEDGER_PATH,
    cancel_ledger_path: Path = CANCEL_LEDGER_PATH,
    backend_claim_log_path: Path = BACKEND_CLAIM_LOG_PATH,
    handoff_path: Path = HANDOFF_PATH,
) -> dict[str, Any]:
    """Validate every external gate before creating execution artifacts."""

    _require_owner_only_regular_file(plan_path, "v15_execution_plan")
    try:
        plan_value = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofFailure("v15_execution_plan_malformed") from exc
    _require(isinstance(plan_value, dict), "v15_execution_plan_not_object")
    plan = dict(plan_value)
    validate_v15_plan(
        plan,
        expected_hash=expected_hash,
        preflight=preflight,
        now=now,
    )
    _require(
        preflight.get("portfolio_id") == TEST_PORTFOLIO_ID
        and int(preflight.get("active_spot_order_count") or 0) == 0,
        "v15_execute_profile_or_active_order_gate_failed",
    )
    _require(
        active_zero.get("stable_zero") is True,
        "v15_execute_active_zero_unproven",
    )
    _require(
        fresh_ids.get("fresh_read") is True,
        "v15_execute_fresh_identity_absence_unproven",
    )
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
        "v15_execution_authority_already_consumed",
    )
    authority = initialize_v15_execution_authority(
        plan_path,
        plan,
        expected_hash=expected_hash,
        preflight=preflight,
        now=now,
        marker_path=marker_path,
        placement_ledger_path=placement_ledger_path,
        cancel_ledger_path=cancel_ledger_path,
        backend_claim_log_path=backend_claim_log_path,
        handoff_path=handoff_path,
    )
    # The immutable marker is already present. Failure here burns authority
    # rather than leaving a second opportunity to initialize the slice.
    _create_owner_only_empty_file(
        backend_claim_log_path,
        "v15_backend_claim_log_create_failed",
    )
    _require_owner_only_regular_file(
        backend_claim_log_path,
        "v15_backend_claim_log",
    )
    return authority


def write_v15_cancel_proof_handoff(
    handoff_path: Path,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    context: Mapping[str, Any],
    proofs: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    """Write the route-created cancel proof ids for backend authority loading."""

    _require(plan.get("plan_sha256") == plan_sha256, "v15_handoff_plan_mismatch")
    cancel = dict(plan.get("cancel_command") or {})
    approval_id = str(proofs.get("approval_id") or "")
    audit_id = str(proofs.get("admission_audit_id") or "")
    cap_id = str(proofs.get("cap_guard_decision_id") or "")
    reconciliation_id = str(proofs.get("reconciliation_plan_id") or "")
    _require(
        approval_id == cancel.get("approval_snapshot_id")
        and cap_id == cancel.get("cap_guard_decision_id")
        and reconciliation_id == cancel.get("reconciliation_plan_id")
        and bool(audit_id),
        "v15_handoff_proof_mismatch",
    )
    expected_context, _ = build_v15_cancel_admission_context(
        plan,
        plan_sha256=plan_sha256,
    )
    exact_context = dict(context)
    _require(
        exact_context == expected_context,
        "v15_handoff_route_context_mismatch",
    )
    handoff = {
        "schema_version": "1",
        "authority": AUTHORITY_KIND,
        "plan_sha256": plan_sha256,
        "batch_id": plan["batch_id"],
        "root_client_order_id": dict(plan["root"])["client_order_id"],
        "child_client_order_id": dict(plan["child"])["client_order_id"],
        "approval_snapshot_id": approval_id,
        "admission_audit_id": audit_id,
        "cap_guard_decision_id": cap_id,
        "reconciliation_plan_id": reconciliation_id,
        "route": exact_context["route"],
        "method": exact_context["method"],
        "module_id": exact_context["module_id"],
        "identity_key": exact_context["identity_key"],
        "identity_value": exact_context["identity_value"],
        "action_class": exact_context["action_class"],
        "required_permission": exact_context["required_permission"],
        "service_method": exact_context["service_method"],
        "actor_id": exact_context["actor_id"],
        "command_idempotency_key": exact_context[
            "command_idempotency_key"
        ],
        "payload_hash": exact_context["payload_hash"],
        "idempotency_key": cancel["idempotency_key"],
        "correlation_id": cancel["correlation_id"],
        "operator_intent": cancel["operator_intent"],
        "recorded_at": recorded_at,
    }
    base._write_owner_only_exclusive_json(
        handoff_path,
        handoff,
        exists_blocker="v15_handoff_already_exists",
    )
    _require_owner_only_regular_file(handoff_path, "v15_handoff")
    return handoff


def v15_resume_decision(
    placement_records: list[Mapping[str, Any]],
    cancel_records: list[Mapping[str, Any]],
) -> str:
    """Return the only safe next action after an interrupted V15 process."""

    placement_kinds = [str(record.get("attempt_kind") or "") for record in placement_records]
    _require(
        placement_kinds in ([], ["root"], ["root", "child"]),
        "v15_resume_placement_ledger_invalid",
    )
    _require(len(cancel_records) <= 2, "v15_resume_cancel_ledger_invalid")
    if cancel_records:
        _require(
            placement_kinds == ["root", "child"],
            "v15_resume_cancel_without_placements",
        )
        _require(
            (
                len(cancel_records) == 1
                and str(cancel_records[0].get("outcome") or "")
                in {"claimed", "accepted", "rejected", "unknown"}
            )
            or (
                len(cancel_records) == 2
                and str(cancel_records[0].get("outcome") or "") == "claimed"
                and str(cancel_records[1].get("outcome") or "")
                in {"accepted", "rejected", "unknown"}
            ),
            "v15_resume_cancel_ledger_invalid",
        )
        outcome = str(cancel_records[-1].get("outcome") or "")
        if outcome in {"claimed", "unknown"}:
            return "reconcile_cancel_same_key_only"
        if outcome == "accepted":
            return "verify_terminal_closeout"
        return "stop_cancel_outcome_blocked"
    if placement_kinds == ["root", "child"]:
        return "inspect_child_no_new_placement"
    if placement_kinds == ["root"]:
        return "reconcile_root_no_new_placement"
    return "submit_root"


def v15_operator_monitor_decision(
    placement_records: list[Mapping[str, Any]],
    local_cancel_records: list[Mapping[str, Any]],
    backend_claim_records: list[Mapping[str, Any]],
    *,
    expected_identity: Mapping[str, Any],
    now: datetime,
    expires_at: str,
) -> str:
    """Classify a fresh or restarted read-only operator-cancel monitor."""

    _require(
        [str(row.get("attempt_kind") or "") for row in placement_records]
        == ["root", "child"],
        "v15_monitor_placement_ledger_incomplete",
    )
    _require(
        not local_cancel_records,
        "v15_monitor_runner_cancel_claim_forbidden",
    )
    expected = dict(expected_identity)
    identity_fields = (
        "schema_version",
        "semantic_key",
        "controlled_plan_sha256",
        "root_client_order_id",
        "child_client_order_id",
        "idempotency_key",
        "payload_hash",
        "correlation_id",
        "actor_id",
        "source",
    )
    _require(
        all(
            row.get(field) == expected.get(field)
            for row in backend_claim_records
            for field in identity_fields
        ),
        "v15_monitor_backend_claim_identity_mismatch",
    )
    expiry = datetime.fromisoformat(expires_at)
    _require(
        now.tzinfo is not None and expiry.tzinfo is not None,
        "v15_monitor_time_invalid",
    )
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
                        backend_claim_records[1].get("event")
                        == "exchange_boundary"
                        and backend_claim_records[1].get("outcome")
                        == "unknown"
                        and backend_claim_records[1].get("response") is None
                        and backend_claim_records[1].get(
                            "reconciliation_required"
                        )
                        is True
                    )
                    or (
                        backend_claim_records[1].get("event") == "outcome"
                        and backend_claim_records[1].get("outcome")
                        == "rejected"
                        and isinstance(
                            backend_claim_records[1].get("response"),
                            Mapping,
                        )
                        and backend_claim_records[1].get(
                            "reconciliation_required"
                        )
                        is False
                    )
                )
            )
            or (
                len(backend_claim_records) == 3
                and backend_claim_records[1].get("event")
                == "exchange_boundary"
                and backend_claim_records[1].get("outcome") == "unknown"
                and backend_claim_records[1].get("response") is None
                and backend_claim_records[1].get("reconciliation_required")
                is True
                and backend_claim_records[2].get("event") == "outcome"
                and backend_claim_records[2].get("outcome")
                in {"accepted", "rejected", "unknown"}
                and isinstance(
                    backend_claim_records[2].get("response"), Mapping
                )
                and backend_claim_records[2].get("reconciliation_required")
                is (backend_claim_records[2].get("outcome") == "unknown")
            )
        ),
        "v15_monitor_backend_claim_ledger_invalid",
    )
    latest = str(backend_claim_records[-1].get("outcome") or "")
    if latest == "accepted":
        return "verify_terminal_closeout"
    if latest == "rejected":
        return "operator_cancel_rejected_active_child_reconciliation_only"
    if now >= expiry:
        return "plan_expired_ambiguous_cancel_reconciliation_only"
    return "operator_cancel_ambiguous_reconciliation_only"


def v15_backend_claim_identity(
    plan: Mapping[str, Any],
    *,
    plan_sha256: str,
) -> dict[str, Any]:
    """Return the exact immutable identity shared by all backend claim events."""

    from application.admin_api.root_child_cancel import (
        root_child_cancel_semantic_key,
    )

    cancel = dict(plan["cancel_command"])
    context, _ = build_v15_cancel_admission_context(
        plan,
        plan_sha256=plan_sha256,
    )
    root_id = str(dict(plan["root"])["client_order_id"])
    child_id = str(dict(plan["child"])["client_order_id"])
    return {
        "schema_version": "1",
        "semantic_key": root_child_cancel_semantic_key(
            controlled_plan_sha256=plan_sha256,
            root_client_order_id=root_id,
            child_client_order_id=child_id,
        ),
        "controlled_plan_sha256": plan_sha256,
        "root_client_order_id": root_id,
        "child_client_order_id": child_id,
        "idempotency_key": cancel["idempotency_key"],
        "payload_hash": context["payload_hash"],
        "correlation_id": cancel["correlation_id"],
        "actor_id": context["actor_id"],
        "source": "admin_api_root_child_cancel_claim_log",
    }


def _read_owner_only_jsonl(path: Path, blocker: str) -> list[dict[str, Any]]:
    metadata = _require_owner_only_regular_file(path, blocker)
    _require(metadata.st_size <= 100_000, f"{blocker}_too_large")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        _require(isinstance(value, dict), f"{blocker}_row_invalid")
        rows.append(dict(value))
    return rows


_LedgerResult = TypeVar("_LedgerResult")


def _mutate_owner_only_jsonl(
    path: Path,
    *,
    blocker: str,
    mutation: Callable[
        [list[dict[str, Any]]], tuple[Mapping[str, Any] | None, _LedgerResult]
    ],
) -> _LedgerResult:
    """Serialize one validate/decide/append operation under an OS file lock."""

    flags = os.O_RDWR | os.O_APPEND | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProofFailure(f"{blocker}_open_failed") from exc
    try:
        metadata = os.fstat(descriptor)
        _require(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and metadata.st_mode & 0o077 == 0,
            f"{blocker}_unsafe",
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, 100_001)
        _require(len(raw) <= 100_000, f"{blocker}_too_large")
        rows: list[dict[str, Any]] = []
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            _require(isinstance(value, dict), f"{blocker}_row_invalid")
            rows.append(dict(value))
        record, result = mutation(rows)
        if record is not None:
            encoded = (
                json.dumps(dict(record), sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            _require(len(raw) + len(encoded) <= 100_000, f"{blocker}_too_large")
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        return result
    finally:
        os.close(descriptor)


def consume_v15_placement_attempt(
    ledger_path: Path,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    attempt_kind: str,
    exact_order_tuple: Mapping[str, Any],
    consumed_at: str,
) -> dict[str, Any]:
    _require(plan.get("plan_sha256") == plan_sha256, "v15_attempt_plan_mismatch")
    _require(attempt_kind in {"root", "child"}, "v15_placement_attempt_kind_invalid")
    scope = dict(plan[attempt_kind])
    tuple_record = dict(exact_order_tuple)
    if attempt_kind == "root":
        _require(
            tuple_record == dict(scope["order"]),
            "v15_placement_tuple_drift",
        )
    else:
        _require(
            tuple_record.get("batch_id") == plan.get("batch_id")
            and tuple_record.get("batch_slot") == 1
            and tuple_record.get("approval_snapshot_id")
            == scope.get("approval_snapshot_id")
            and tuple_record.get("root_client_order_id")
            == scope.get("parent_client_order_id")
            and tuple_record.get("client_order_id")
            == scope.get("client_order_id")
            and tuple_record.get("product_id") == PRODUCT_ID
            and tuple_record.get("side") == "SELL"
            and tuple_record.get("order_type") == "LIMIT"
            and tuple_record.get("time_in_force")
            == "GOOD_UNTIL_CANCELLED"
            and tuple_record.get("post_only") is False
            and Decimal(str(tuple_record.get("base_size") or "0")) > 0
            and Decimal(str(tuple_record.get("limit_price") or "0")) > 0
            and Decimal(str(tuple_record.get("base_size") or "0"))
            * Decimal(str(tuple_record.get("limit_price") or "0"))
            < CHILD_SUBMITTED_CAP
            and Decimal(str(tuple_record.get("limit_price") or "0"))
            >= Decimal(str(tuple_record.get("reference_bid") or "0"))
            * base.CHILD_MINIMUM_BID_RATIO
            and Decimal(str(tuple_record.get("strict_max_notional_usdc") or "0"))
            == CHILD_SUBMITTED_CAP,
            "v15_placement_tuple_drift",
        )
    client_order_id = str(scope["client_order_id"])
    def mutation(
        rows: list[dict[str, Any]],
    ) -> tuple[Mapping[str, Any], dict[str, Any]]:
        schedule = ["root", "child"]
        _require(
            len(rows) < len(schedule), "v15_placement_attempt_count_exceeded"
        )
        sequence = len(rows) + 1
        _require(
            attempt_kind == schedule[sequence - 1],
            "v15_placement_attempt_not_next",
        )
        record = {
            "schema_version": "1",
            "sequence": sequence,
            "attempt_kind": attempt_kind,
            "batch_id": plan["batch_id"],
            "root_client_order_id": dict(plan["root"])["client_order_id"],
            "client_order_id": client_order_id,
            "plan_sha256": plan_sha256,
            "exact_order_tuple": tuple_record,
            "exact_order_tuple_sha256": hashlib.sha256(
                json.dumps(
                    tuple_record, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest(),
            "consumed_at": consumed_at,
            "process_id": os.getpid(),
        }
        return record, record

    return _mutate_owner_only_jsonl(
        ledger_path,
        blocker="v15_placement_ledger",
        mutation=mutation,
    )


def claim_v15_cancel_command(
    ledger_path: Path,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    claimed_at: str,
) -> dict[str, Any]:
    _require(plan.get("plan_sha256") == plan_sha256, "v15_cancel_claim_plan_mismatch")
    command = dict(plan.get("cancel_command") or {})

    def mutation(
        rows: list[dict[str, Any]],
    ) -> tuple[Mapping[str, Any] | None, dict[str, Any]]:
        decision = cancel_command_claim_decision(
            rows,
            command=command,
            plan_sha256=plan_sha256,
        )
        if decision in {"semantic_conflict", "reconcile_same_key_only"}:
            raise ProofFailure(
                "v15_cancel_semantic_conflict"
                if decision == "semantic_conflict"
                else "v15_cancel_unknown_outcome_reconciliation_only"
            )
        if decision == "same_key_replay":
            return None, dict(rows[-1])
        _require(len(rows) == 0, "v15_cancel_command_count_exceeded")
        claim = build_cancel_command_claim(
            plan,
            plan_sha256=plan_sha256,
            claimed_at=claimed_at,
        )
        return claim, claim

    return _mutate_owner_only_jsonl(
        ledger_path,
        blocker="v15_cancel_ledger",
        mutation=mutation,
    )


def record_v15_cancel_outcome(
    ledger_path: Path,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    outcome: str,
    recorded_at: str,
    response: Mapping[str, Any],
) -> dict[str, Any]:
    """Complete the one local cancel claim without authorizing another call."""

    _require(
        plan.get("plan_sha256") == plan_sha256,
        "v15_cancel_outcome_plan_mismatch",
    )
    _require(
        outcome in {"accepted", "rejected", "unknown"},
        "v15_cancel_outcome_invalid",
    )
    command = dict(plan.get("cancel_command") or {})

    def mutation(
        rows: list[dict[str, Any]],
    ) -> tuple[Mapping[str, Any], dict[str, Any]]:
        _require(len(rows) == 1, "v15_cancel_outcome_already_recorded")
        claim = dict(rows[0])
        _require(
            claim.get("outcome") == "claimed"
            and claim.get("plan_sha256") == plan_sha256
            and claim.get("claim_id") == command.get("claim_id")
            and claim.get("root_client_order_id")
            == command.get("root_client_order_id")
            and claim.get("child_client_order_id")
            == command.get("child_client_order_id")
            and claim.get("idempotency_key")
            == command.get("idempotency_key"),
            "v15_cancel_outcome_claim_mismatch",
        )
        record = {
            **claim,
            "record_type": "selected_chain_child_cancel_outcome",
            "recorded_at": recorded_at,
            "outcome": outcome,
            "response": dict(response),
        }
        return record, record

    return _mutate_owner_only_jsonl(
        ledger_path,
        blocker="v15_cancel_ledger",
        mutation=mutation,
    )


def build_cancel_command_claim(
    plan: Mapping[str, Any], *, plan_sha256: str, claimed_at: str
) -> dict[str, Any]:
    _require(plan_sha256 == plan.get("plan_sha256"), "v15_cancel_claim_plan_mismatch")
    command = dict(plan.get("cancel_command") or {})
    return {
        "schema_version": "1",
        "record_type": "selected_chain_child_cancel_claim",
        "plan_sha256": plan_sha256,
        "claim_id": command.get("claim_id"),
        "root_client_order_id": command.get("root_client_order_id"),
        "child_client_order_id": command.get("child_client_order_id"),
        "identity_key": command.get("identity_key"),
        "identity_value": command.get("identity_value"),
        "idempotency_key": command.get("idempotency_key"),
        "operator_intent": command.get("operator_intent"),
        "claimed_at": claimed_at,
        "outcome": "claimed",
    }


def cancel_command_claim_decision(
    records: list[Mapping[str, Any]],
    *,
    command: Mapping[str, Any],
    plan_sha256: str,
) -> str:
    matching_semantic = [
        record
        for record in records
        if record.get("plan_sha256") == plan_sha256
        and record.get("root_client_order_id") == command.get("root_client_order_id")
        and record.get("child_client_order_id") == command.get("child_client_order_id")
        and record.get("identity_key") == "client_order_id"
        and record.get("identity_value") == command.get("root_client_order_id")
    ]
    if not matching_semantic:
        return "claim"
    latest = matching_semantic[-1]
    if latest.get("idempotency_key") != command.get("idempotency_key"):
        return "semantic_conflict"
    if latest.get("outcome") == "unknown":
        return "reconcile_same_key_only"
    return "same_key_replay"


def _prove_v15_fresh_ids_absent(
    rest_client: Any,
    plan: Mapping[str, Any],
    *,
    include_root: bool = True,
) -> dict[str, Any]:
    planned_ids = {str(dict(plan["child"])["client_order_id"])}
    if include_root:
        planned_ids.add(str(dict(plan["root"])["client_order_id"]))
    local_absence = base.prove_local_scope_with_historical_hidden_child(
        planned_client_order_ids=planned_ids,
        carried_root_plan=base.completed_slot_1_binding_fixture(),
    )
    catalog, pagination = base.read_failed_v6_v7_order_catalog(rest_client)
    matching = [
        dict(row)
        for row in catalog
        if str(row.get("client_order_id") or "") in planned_ids
    ]
    fresh = bool(
        pagination.get("authoritative") is True
        and pagination.get("pagination_complete") is True
        and not matching
        and local_absence.get("planned_ids_absent_from_order_parent") is True
        and local_absence.get("planned_ids_absent_from_stealth_orders") is True
        and local_absence.get("planned_ids_absent_from_fill_ledger") is True
        and local_absence.get("planned_ids_absent_from_order_match_audit") is True
    )
    return {
        "fresh_read": fresh,
        "planned_client_order_ids": sorted(planned_ids),
        "coinbase_matching_orders": matching,
        "pagination": dict(pagination),
        "local_absence": dict(local_absence),
    }


def _validate_v15_cancel_readiness(
    readiness: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
) -> dict[str, Any]:
    evidence = dict(readiness)
    root = dict(plan["root"])
    child = dict(plan["child"])
    cancel = dict(plan["cancel_command"])
    _require(
        evidence.get("type")
        == "admin_order_fill_follow_up_child_cancel_readiness"
        and evidence.get("found") is True
        and evidence.get("ready") is True
        and evidence.get("readiness_status") == "ready"
        and evidence.get("root_client_order_id") == root["client_order_id"]
        and evidence.get("child_client_order_id") == child["client_order_id"]
        and evidence.get("product_id") == PRODUCT_ID
        and evidence.get("profile_alias") == PROFILE_LABEL
        and evidence.get("portfolio_id") == TEST_PORTFOLIO_ID
        and evidence.get("controlled_batch_id") == plan["batch_id"]
        and evidence.get("controlled_batch_slot") == 1
        and evidence.get("controlled_plan_sha256") == plan_sha256
        and evidence.get("approval_snapshot_id")
        == cancel["approval_snapshot_id"]
        and evidence.get("cap_guard_decision_id")
        == cancel["cap_guard_decision_id"]
        and evidence.get("reconciliation_plan_id")
        == cancel["reconciliation_plan_id"]
        and bool(str(evidence.get("audit_id") or ""))
        and evidence.get("cancel_idempotency_key")
        == cancel["idempotency_key"]
        and evidence.get("cancel_correlation_id") == cancel["correlation_id"]
        and evidence.get("cancel_operator_intent")
        == cancel["operator_intent"]
        and evidence.get("backend_decision") == "allowed"
        and evidence.get("environment")
        == "local-controlled-live-test-profile"
        and evidence.get("active_placement_proven") is True
        and evidence.get("zero_fill_proven") is True
        and evidence.get("exchange_order_id_evidence_present") is True
        and evidence.get("exchange_order_id_evidence_only") is True
        and evidence.get("reconciliation_required") is False
        and not list(evidence.get("blockers") or [])
        and evidence.get("read_only") is True
        and evidence.get("live_coinbase_orders_ran") is False
        and evidence.get("coinbase_order_cancel_submitted") is False,
        "v15_root_scoped_cancel_readiness_mismatch",
    )
    cap_fields = (
        "root_reference_notional_usdc",
        "child_reference_notional_usdc",
        "aggregate_reference_notional_usdc",
        "root_notional_cap_usdc",
        "child_notional_cap_usdc",
        "aggregate_notional_cap_usdc",
    )
    _require(
        all(field in evidence and evidence[field] is not None for field in cap_fields),
        "v15_root_scoped_cancel_readiness_cap_missing",
    )
    _require(
        Decimal(str(evidence["root_reference_notional_usdc"]))
        < ROOT_SUBMITTED_CAP
        and Decimal(str(evidence["child_reference_notional_usdc"]))
        < CHILD_SUBMITTED_CAP
        and Decimal(str(evidence["aggregate_reference_notional_usdc"]))
        < SLICE_REFERENCE_CAP
        and Decimal(str(evidence["root_notional_cap_usdc"]))
        == ROOT_SUBMITTED_CAP
        and Decimal(str(evidence["child_notional_cap_usdc"]))
        == CHILD_SUBMITTED_CAP
        and Decimal(str(evidence["aggregate_notional_cap_usdc"]))
        == SLICE_REFERENCE_CAP,
        "v15_root_scoped_cancel_readiness_cap_mismatch",
    )
    return evidence


def validate_v15_explicit_zero_fill(
    order: Mapping[str, Any],
) -> dict[str, Any]:
    """Require explicit Coinbase zero-fill fields; absence is never zero."""

    evidence = dict(order)
    required = ("filled_size", "filled_value", "total_fees", "number_of_fills")
    _require(
        all(field in evidence and evidence[field] is not None for field in required),
        "v15_zero_fill_field_missing",
    )
    _require(
        Decimal(str(evidence["filled_size"])) == 0
        and Decimal(str(evidence["filled_value"])) == 0
        and Decimal(str(evidence["total_fees"])) == 0
        and int(evidence["number_of_fills"]) == 0,
        "v15_zero_fill_not_zero",
    )
    return evidence


def build_v15_cancel_admission_context(
    plan: Mapping[str, Any],
    *,
    plan_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the exact UI request admission context without POSTing cancel."""

    from application.admin_api.idempotency import make_payload_hash

    _require(plan.get("plan_sha256") == plan_sha256, "v15_cancel_context_plan_mismatch")
    cancel = dict(plan["cancel_command"])
    root_id = str(dict(plan["root"])["client_order_id"])
    body = {
        "reason": "cancel_active_deterministic_first_child",
        "manual_live_acknowledgement": True,
        "controlled_plan_sha256": plan_sha256,
    }
    endpoint = (
        f"POST /api/v1/orders/{root_id}/fill-follow-up/child-cancel"
    )
    payload_hash = make_payload_hash(
        {
            "endpoint": endpoint,
            "actor_id": base.ACTOR_ID,
            "roles": [base.COMMAND_ROLE],
            "operator_intent": cancel["operator_intent"],
            "body": body,
            "path_params": {"root_client_order_id": root_id},
        }
    )
    context = {
        "route": cancel["route"],
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": root_id,
        "action_class": "live_exchange_cancel",
        "required_permission": "order:cancel",
        "service_method": (
            "cancel_order_fill_follow_up_child_by_root_client_order_id"
        ),
        "actor_id": base.ACTOR_ID,
        "operator_intent": cancel["operator_intent"],
        "command_idempotency_key": cancel["idempotency_key"],
        "payload_hash": payload_hash,
    }
    return context, body


def _read_v15_backend_cancel_claim_records(path: Path) -> list[dict[str, Any]]:
    """Use the canonical store parser so corrupt sequences fail closed."""

    from application.admin_api.root_child_cancel import (
        FileAdminRootChildCancelClaimStore,
    )

    _require_owner_only_regular_file(path, "v15_backend_claim_log")
    try:
        return [
            record.model_dump(mode="json")
            for record in reversed(
                FileAdminRootChildCancelClaimStore(path).read_recent(limit=500)
            )
        ]
    except Exception as exc:
        raise ProofFailure("v15_backend_claim_log_invalid") from exc


def _validate_v15_backend_cancel_claim_log(
    path: Path,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
) -> dict[str, Any]:
    records = _read_v15_backend_cancel_claim_records(path)
    expected_identity = v15_backend_claim_identity(
        plan,
        plan_sha256=plan_sha256,
    )
    _require(
        v15_operator_monitor_decision(
            [{"attempt_kind": "root"}, {"attempt_kind": "child"}],
            [],
            records,
            expected_identity=expected_identity,
            now=datetime.now(timezone.utc),
            expires_at="9999-12-31T23:59:59+00:00",
        )
        == "verify_terminal_closeout"
        and len(records) == 3,
        "v15_backend_cancel_claim_not_exactly_once_accepted",
    )
    return {
        "semantic_key": records[-1]["semantic_key"],
        "claim_event_count": 1,
        "exchange_boundary_event_count": 1,
        "outcome_event_count": 1,
        "backend_claim_event_count": 3,
        "outcome": "accepted",
    }


def _v15_exact_proofs(
    runtime: base.AdminRuntime,
    *,
    label: str,
    context: Mapping[str, Any],
    scope: Mapping[str, Any],
    wallet_available: Decimal,
    max_notional: Decimal,
    command_kind: str,
) -> dict[str, str]:
    return base.write_proof_chain(
        runtime,
        label=label,
        context=context,
        wallet_available=wallet_available,
        max_notional=max_notional,
        command_kind=command_kind,
        cancel=command_kind.endswith("cancel"),
        approval_id=str(scope["approval_snapshot_id"]),
        cap_guard_decision_id=str(scope["cap_guard_decision_id"]),
        reconciliation_plan_id=str(scope["reconciliation_plan_id"]),
    )


def execute_v15_plan(
    *,
    plan_path: Path,
    confirmed_plan_sha256: str,
) -> dict[str, Any]:
    """Execute the sealed root/fill/first-child/cancel slice exactly once."""

    _require(plan_path == PLAN_PATH, "v15_execute_plan_file_not_fixed")
    confirmed_plan_sha256 = _validate_lower_sha256(
        confirmed_plan_sha256,
        "v15_execute_plan_hash_invalid",
    )
    _require_owner_only_regular_file(plan_path, "v15_execution_plan")
    try:
        plan_value = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofFailure("v15_execution_plan_malformed") from exc
    _require(isinstance(plan_value, dict), "v15_execution_plan_not_object")
    plan = dict(plan_value)
    rest_client = base.hydrate_test_credentials()
    preflight = base.coinbase_preflight(rest_client)
    active_zero = base.prove_stable_authoritative_active_zero(
        rest_client,
        expected_portfolio_id=TEST_PORTFOLIO_ID,
    )
    fresh_ids = _prove_v15_fresh_ids_absent(rest_client, plan)

    # This is the only transition from read-only validation to durable
    # execution authority. Every external gate above must pass first.
    authority = authorize_v15_execution(
        plan_path,
        expected_hash=confirmed_plan_sha256,
        preflight=preflight,
        active_zero=active_zero,
        fresh_ids=fresh_ids,
        marker_path=MARKER_PATH,
        placement_ledger_path=PLACEMENT_LEDGER_PATH,
        cancel_ledger_path=CANCEL_LEDGER_PATH,
        backend_claim_log_path=BACKEND_CLAIM_LOG_PATH,
        handoff_path=HANDOFF_PATH,
    )
    root = dict(plan["root"])
    child = dict(plan["child"])
    cancel = dict(plan["cancel_command"])
    root_id = str(root["client_order_id"])
    child_id = str(child["client_order_id"])
    root_order = dict(root["order"])
    root_reference = Decimal(str(plan["root_reference_notional_usdc"]))
    runtime = base.AdminRuntime(
        portfolio_id=TEST_PORTFOLIO_ID,
        confirmed_plan=plan,
        confirmed_plan_hash=confirmed_plan_sha256,
        global_batch_marker=MARKER_PATH,
        attempt_ledger_path=PLACEMENT_LEDGER_PATH,
        controlled_v15_plan_path=plan_path,
        controlled_v15_handoff_path=HANDOFF_PATH,
        controlled_v15_claim_log_path=BACKEND_CLAIM_LOG_PATH,
    )
    summary: dict[str, Any] = {
        "status": "running",
        "authority": authority,
        "plan_sha256": confirmed_plan_sha256,
        "batch_id": plan["batch_id"],
        "root_client_order_id": root_id,
        "child_client_order_id": child_id,
        "preartifact_active_zero": active_zero,
        "preartifact_fresh_ids": fresh_ids,
    }
    cleanup: dict[str, Any] = {}
    terminal_closeout = False
    try:
        runtime.start()
        runtime.wait_until_mutations_ready()
        runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={0},
            expected_child_place_limit_order_calls={0},
        )
        wallets_before = base._wallet_balances(
            rest_client,
            expected_portfolio_id=TEST_PORTFOLIO_ID,
        )

        root_headers = runtime.headers(
            idempotency_key=_deterministic_evidence_id(
                str(plan["batch_id"]), "root-place-idempotency"
            ),
            operator_intent=str(plan["root_operator_intent"]),
            role=base.COMMAND_ROLE,
            correlation_id=_deterministic_evidence_id(
                str(plan["batch_id"]), "root-place-correlation"
            ),
        )
        _, blocked_root, _ = runtime.request(
            "POST",
            "/orders",
            headers=root_headers,
            body=root_order,
            expected={501},
        )
        root_context = base.capture_context(blocked_root)
        _require(
            root_context["identity_value"] == root_id,
            "v15_root_route_identity_mismatch",
        )
        root_proofs = _v15_exact_proofs(
            runtime,
            label="v15-root-place",
            context=root_context,
            scope=root,
            wallet_available=Decimal(str(preflight["wallets"]["USDC"])),
            max_notional=ROOT_SUBMITTED_CAP,
            command_kind="root_place",
        )
        root_attempt = consume_v15_placement_attempt(
            PLACEMENT_LEDGER_PATH,
            plan=plan,
            plan_sha256=confirmed_plan_sha256,
            attempt_kind="root",
            exact_order_tuple=root_order,
            consumed_at=datetime.now(timezone.utc).isoformat(),
        )
        _require(
            plan_hash(plan) == confirmed_plan_sha256
            and plan.get("runner_sha256") == runner_sha256(),
            "v15_plan_or_runner_changed_after_root_ledger",
        )
        base.require_plan_unexpired(
            plan,
            blocker="v15_plan_expired_after_root_ledger",
        )
        immediate_preflight = base.coinbase_preflight(rest_client)
        validate_v15_plan(
            plan,
            expected_hash=confirmed_plan_sha256,
            preflight=immediate_preflight,
        )
        immediate_active = base.prove_stable_authoritative_active_zero(
            rest_client,
            expected_portfolio_id=TEST_PORTFOLIO_ID,
        )
        immediate_fresh = _prove_v15_fresh_ids_absent(rest_client, plan)
        _require(
            immediate_active.get("stable_zero") is True
            and immediate_fresh.get("fresh_read") is True
            and wallets_before["USDC"] >= root_reference,
            "v15_root_immediate_gate_failed",
        )
        runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={0},
            expected_child_place_limit_order_calls={0},
        )
        base.set_live_service(runtime, enabled=True)
        base.preview_admission(runtime, root_context)
        runtime.exchange_safe_to_shutdown = False
        root_status, root_response, root_response_headers = runtime.request(
            "POST",
            "/orders",
            headers=root_headers,
            body=root_order,
            expected=None,
        )
        _require(root_status == 200, f"v15_root_place_http:{root_status}")
        _require(
            root_response.get("status") == "accepted"
            and str(
                root_response_headers.get("X-Idempotency-Replayed") or ""
            ).lower()
            != "true",
            "v15_root_place_not_freshly_accepted",
        )
        root_exchange_order_id = str(
            root_response.get("coinbase_order_id") or ""
        )
        _require(bool(root_exchange_order_id), "v15_root_exchange_id_missing")
        runtime.exchange_order_observed = True
        root_acceptance = base._validate_intentional_fill_acceptance(
            root_response,
            place_proofs=root_proofs,
            place_headers=root_headers,
            order_body=root_order,
            portfolio_id=TEST_PORTFOLIO_ID,
            exchange_order_id=root_exchange_order_id,
        )
        runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={1},
            expected_child_place_limit_order_calls={0},
        )
        root_exchange = base._wait_for_exchange_terminal(
            rest_client,
            exchange_order_id=root_exchange_order_id,
            client_order_id=root_id,
            portfolio_id=TEST_PORTFOLIO_ID,
            order_body=root_order,
        )
        _require(
            all(
                field in root_exchange and root_exchange[field] is not None
                for field in (
                    "filled_size",
                    "filled_value",
                    "total_fees",
                    "number_of_fills",
                )
            ),
            "v15_root_fill_field_missing",
        )
        root_exchange_status = str(root_exchange.get("status") or "").upper()
        filled_size = Decimal(str(root_exchange["filled_size"]))
        filled_value = Decimal(str(root_exchange["filled_value"]))
        total_fees = Decimal(str(root_exchange["total_fees"]))
        _require(
            root_exchange_status == "FILLED"
            and filled_size == Decimal(str(root_order["base_size"]))
            and Decimal("0") < filled_value <= ROOT_SUBMITTED_CAP
            and total_fees.is_finite()
            and total_fees >= 0
            and int(root_exchange["number_of_fills"]) > 0,
            "v15_root_not_exact_filled_terminal",
        )

        fill_headers = runtime.headers(
            idempotency_key=_deterministic_evidence_id(
                str(plan["batch_id"]), "root-fill-read"
            ),
            operator_intent="read_authoritative_spot_order_and_fill_evidence",
            role="auditor",
            correlation_id=_deterministic_evidence_id(
                str(plan["batch_id"]), "root-fill-correlation"
            ),
        )
        fill_readback: dict[str, Any] = {}
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            _, fill_readback, _ = runtime.request(
                "GET",
                f"/orders/{root_id}/fill-readback",
                headers=fill_headers,
                params={"product_id": PRODUCT_ID, "fill_limit": 100},
                expected={200},
            )
            if (
                fill_readback.get("status") == "passed"
                and str(fill_readback.get("order_status") or "").upper()
                == "FILLED"
                and "fill_count" in fill_readback
                and fill_readback["fill_count"] is not None
                and int(fill_readback["fill_count"]) > 0
                and fill_readback.get("live_fill_readback_proof_recorded")
                is True
                and fill_readback.get("fills_have_more_pages") is False
            ):
                break
            time.sleep(0.5)
        _require(
            fill_readback.get("status") == "passed"
            and str(fill_readback.get("order_status") or "").upper()
            == "FILLED"
            and "fill_count" in fill_readback
            and fill_readback["fill_count"] is not None
            and int(fill_readback["fill_count"]) > 0
            and fill_readback.get("live_fill_readback_proof_recorded") is True
            and fill_readback.get("fills_have_more_pages") is False,
            "v15_root_fill_readback_unproven",
        )

        preexchange_child: dict[str, Any] = {}
        chain_deadline = time.monotonic() + base.FOLLOW_UP_WAIT_SECONDS
        while time.monotonic() < chain_deadline:
            _, chain, _ = runtime.request(
                "GET",
                f"/orders/{root_id}/fill-follow-up/chain",
                headers=runtime.headers(role="auditor"),
                expected={200},
            )
            base._raise_on_critical_chain_state(chain)
            try:
                preexchange_child = base._validate_automatic_hidden_child_chain(
                    chain,
                    root_client_order_id=root_id,
                    portfolio_id=TEST_PORTFOLIO_ID,
                    expected_filled_size=filled_size,
                    expected_placement_correlation_id=str(
                        root_headers["X-Correlation-Id"]
                    ),
                    expected_admission_audit_id=root_proofs[
                        "admission_audit_id"
                    ],
                    expected_exchange_order_id=root_exchange_order_id,
                )
            except ProofFailure as exc:
                if not base._chain_validation_failure_is_transient(str(exc)):
                    raise
                time.sleep(0.25)
                continue
            break
        _require(
            preexchange_child.get("client_order_id") == child_id,
            "v15_automatic_first_child_not_exact",
        )
        _, child_detail, _ = runtime.request(
            "GET",
            f"/stealth/orders/{child_id}",
            headers=runtime.headers(role="auditor"),
            expected={200},
        )
        base._validate_hidden_child_detail(
            child_detail,
            child_id=child_id,
            root_client_order_id=root_id,
            expected_filled_size=filled_size,
        )
        fill_reconciliation = base._reconcile_fill_ledger_with_exact_rest_fills(
            rest_client,
            client_order_id=root_id,
            exchange_order_id=root_exchange_order_id,
            portfolio_id=TEST_PORTFOLIO_ID,
            expected_filled_size=filled_size,
            expected_filled_value=filled_value,
            expected_total_fees=total_fees,
        )
        _require(
            fill_reconciliation.get("pagination_complete") is True,
            "v15_root_fill_pagination_not_explicitly_complete",
        )
        fill_crosscheck = base._cross_check_fill_readback_evidence(
            fill_readback,
            exchange_order=root_exchange,
            reconciliation=fill_reconciliation,
        )
        _, root_wallet_propagation = base._wait_for_root_wallet_propagation(
            rest_client,
            expected_portfolio_id=TEST_PORTFOLIO_ID,
            wallets_before=wallets_before,
            filled_size=filled_size,
            filled_value=filled_value,
            total_fees=total_fees,
            base_increment=Decimal(
                str(dict(immediate_preflight["product"])["base_increment"])
            ),
        )
        base.set_live_service(runtime, enabled=False)
        _require(
            not base.read_authoritative_spot_nonterminal_orders(
                rest_client,
                expected_portfolio_id=TEST_PORTFOLIO_ID,
            ),
            "v15_active_order_between_root_and_child",
        )

        child_market = base.fresh_exact_market(rest_client)
        child_tuple = build_execution_child_order_tuple(
            plan,
            filled_size=filled_size,
            fresh_market=child_market,
            price_increment=Decimal(
                str(dict(immediate_preflight["product"])["price_increment"])
            ),
        )
        child_reference = Decimal(str(child_tuple["base_size"])) * Decimal(
            str(child_tuple["limit_price"])
        )
        _require(
            child_reference < CHILD_SUBMITTED_CAP
            and root_reference + child_reference < SLICE_REFERENCE_CAP
            and filled_value + child_reference < SLICE_REFERENCE_CAP,
            "v15_actual_aggregate_reference_cap_failed",
        )
        child_body = {
            "reason": "controlled V15 first-child submission",
            "manual_live_acknowledgement": True,
            "expected_root_client_order_id": root_id,
            "controlled_limit_price": child_tuple["limit_price"],
            "controlled_batch_id": plan["batch_id"],
            "controlled_batch_slot": 1,
            "controlled_plan_sha256": confirmed_plan_sha256,
        }
        child_headers = runtime.headers(
            idempotency_key=_deterministic_evidence_id(
                str(plan["batch_id"]), "child-reveal-idempotency"
            ),
            operator_intent=str(plan["child_reveal_operator_intent"]),
            role=base.COMMAND_ROLE,
            correlation_id=_deterministic_evidence_id(
                str(plan["batch_id"]), "child-reveal-correlation"
            ),
        )
        _, blocked_child, _ = runtime.request(
            "POST",
            f"/stealth/orders/{child_id}/reveal",
            headers=child_headers,
            body=child_body,
            expected={501},
        )
        child_context = base.capture_context(blocked_child)
        _require(
            child_context["identity_value"] == child_id,
            "v15_child_route_identity_mismatch",
        )
        child_wallets = base._wallet_balances(
            rest_client,
            expected_portfolio_id=TEST_PORTFOLIO_ID,
        )
        _require(
            child_wallets["BTC"] >= filled_size,
            "v15_child_wallet_insufficient",
        )
        child_proofs = _v15_exact_proofs(
            runtime,
            label="v15-child-reveal",
            context=child_context,
            scope=child,
            wallet_available=child_wallets["BTC"]
            * Decimal(str(child_tuple["limit_price"])),
            max_notional=CHILD_SUBMITTED_CAP,
            command_kind="child_reveal",
        )
        child_attempt = consume_v15_placement_attempt(
            PLACEMENT_LEDGER_PATH,
            plan=plan,
            plan_sha256=confirmed_plan_sha256,
            attempt_kind="child",
            exact_order_tuple=child_tuple,
            consumed_at=datetime.now(timezone.utc).isoformat(),
        )
        _require(
            plan_hash(plan) == confirmed_plan_sha256
            and plan.get("runner_sha256") == runner_sha256(),
            "v15_plan_or_runner_changed_after_child_ledger",
        )
        base.require_plan_unexpired(
            plan,
            blocker="v15_plan_expired_after_child_ledger",
        )
        _require(
            _prove_v15_fresh_ids_absent(
                rest_client,
                plan,
                include_root=False,
            ).get("fresh_read")
            is True
            and not base.read_authoritative_spot_nonterminal_orders(
                rest_client,
                expected_portfolio_id=TEST_PORTFOLIO_ID,
            ),
            "v15_child_immediate_identity_or_active_gate_failed",
        )
        immediate_child_market = base.fresh_exact_market(rest_client)
        base.validate_exact_child_price_against_fresh_bid(
            child_tuple,
            immediate_child_market,
            blocker="v15_child_price_below_immediate_fresh_bid",
        )
        runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={1},
            expected_child_place_limit_order_calls={0},
        )
        _require(
            runtime.live_service_may_be_enabled is False
            and root_exchange_status == "FILLED"
            and fill_reconciliation.get("status") == "clean_reconciled"
            and fill_reconciliation.get("pagination_complete") is True
            and root_attempt.get("attempt_kind") == "root"
            and child_attempt.get("attempt_kind") == "child"
            and child_attempt.get("sequence") == 2
            and plan_hash(plan) == confirmed_plan_sha256,
            "v15_cancel_handoff_pre_child_authority_unproven",
        )
        _require(
            _read_owner_only_jsonl(CANCEL_LEDGER_PATH, "v15_cancel_ledger")
            == []
            and _read_owner_only_jsonl(
                BACKEND_CLAIM_LOG_PATH,
                "v15_backend_claim_log",
            )
            == [],
            "v15_cancel_claim_present_before_handoff",
        )
        cancel_context, cancel_body = build_v15_cancel_admission_context(
            plan,
            plan_sha256=confirmed_plan_sha256,
        )
        cancel_path = f"/orders/{root_id}/fill-follow-up/child-cancel"
        _require(
            cancel_context["identity_value"] == root_id,
            "v15_cancel_route_identity_mismatch",
        )
        cancel_proofs = _v15_exact_proofs(
            runtime,
            label="v15-child-cancel",
            context=cancel_context,
            scope=cancel,
            wallet_available=Decimal("0"),
            max_notional=Decimal("0"),
            command_kind="child_cancel",
        )
        handoff = write_v15_cancel_proof_handoff(
            HANDOFF_PATH,
            plan=plan,
            plan_sha256=confirmed_plan_sha256,
            context=cancel_context,
            proofs=cancel_proofs,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        base.set_live_service(runtime, enabled=True)
        base.preview_admission(runtime, child_context)
        runtime.exchange_safe_to_shutdown = False
        child_status, child_response, child_response_headers = runtime.request(
            "POST",
            f"/stealth/orders/{child_id}/reveal",
            headers=child_headers,
            body=child_body,
            expected=None,
        )
        _require(child_status == 200, f"v15_child_reveal_http:{child_status}")
        _require(
            str(
                child_response_headers.get("X-Idempotency-Replayed") or ""
            ).lower()
            != "true",
            "v15_child_reveal_replayed",
        )
        synthetic_root = {
            "root_client_order_id": root_id,
            "child_client_order_id": child_id,
        }
        child_exchange_order_id, child_exchange = (
            base._validate_controlled_child_reveal_response(
                child_response,
                root_plan=synthetic_root,
                child_tuple=child_tuple,
                portfolio_id=TEST_PORTFOLIO_ID,
            )
        )
        runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={1},
            expected_child_place_limit_order_calls={1},
        )
        raw_child = base.exact_exchange_order(
            rest_client,
            child_exchange_order_id,
        )
        raw_child = base._validate_exact_coinbase_gtc_child_order(
            raw_child,
            expected_exchange_order_id=child_exchange_order_id,
            expected_portfolio_id=TEST_PORTFOLIO_ID,
            expected_child_tuple=child_tuple,
        )
        validate_v15_explicit_zero_fill(raw_child)
        _require(
            str(raw_child.get("status") or "").upper() in {"OPEN", "PENDING"}
            and Decimal(str(raw_child["filled_size"])) == 0,
            "v15_child_not_active_zero_fill_before_cancel",
        )
        base.set_live_service(runtime, enabled=False)

        _, readiness, _ = runtime.request(
            "GET",
            f"{cancel_path}/readiness",
            headers=runtime.headers(role="auditor"),
            params={"controlled_plan_sha256": confirmed_plan_sha256},
            expected={200},
        )
        readiness = _validate_v15_cancel_readiness(
            readiness,
            plan=plan,
            plan_sha256=confirmed_plan_sha256,
        )
        _require(
            _read_owner_only_jsonl(CANCEL_LEDGER_PATH, "v15_cancel_ledger")
            == []
            and _read_owner_only_jsonl(
                BACKEND_CLAIM_LOG_PATH,
                "v15_backend_claim_log",
            )
            == [],
            "v15_cancel_claim_present_before_operator_action",
        )
        sentinel = runtime.sdk_boundary_sentinel(
            expected_root_create_order_calls={1},
            expected_child_place_limit_order_calls={1},
        )
        _, admin_runtime, _ = runtime.request(
            "GET",
            "/admin/runtime",
            headers=runtime.headers(role="viewer"),
            expected={200},
        )
        _require(
            "total_inflight" in admin_runtime
            and admin_runtime["total_inflight"] is not None
            and int(admin_runtime["total_inflight"]) == 0,
            "v15_runtime_not_quiescent",
        )
        runtime.exchange_safe_to_shutdown = False
        summary.update(
            {
                "status": "awaiting_operator_ui_root_scoped_cancel",
                "root_attempt": root_attempt,
                "root_proofs": root_proofs,
                "root_acceptance": root_acceptance,
                "root_exchange_order_id": root_exchange_order_id,
                "root_status": "FILLED",
                "root_filled_size": _canonical_decimal(filled_size),
                "root_filled_value": _canonical_decimal(filled_value),
                "root_fill_reconciliation": fill_reconciliation,
                "root_fill_crosscheck": fill_crosscheck,
                "root_wallet_propagation": root_wallet_propagation,
                "child_attempt": child_attempt,
                "child_proofs": child_proofs,
                "child_exchange_order_id": child_exchange_order_id,
                "child_submitted_status": str(
                    child_exchange.get("status") or ""
                ).upper(),
                "child_cancel_proofs": cancel_proofs,
                "child_cancel_handoff": handoff,
                "child_cancel_readiness": readiness,
                "operator_cancel_request_body": cancel_body,
                "operator_cancel_route": cancel["route"],
                "operator_cancel_idempotency_key": cancel[
                    "idempotency_key"
                ],
                "operator_cancel_correlation_id": cancel["correlation_id"],
                "operator_cancel_intent": cancel["operator_intent"],
                "runner_cancel_post_submitted": False,
                "runner_cancel_claim_acquired": False,
                "child_terminal_status": None,
                "child_filled_size": "0",
                "actual_reference_notional_usdc": _canonical_decimal(
                    filled_value + child_reference
                ),
                "placement_attempt_count": 2,
                "root_placement_count": 1,
                "child_placement_count": 1,
                "cancel_command_count": 0,
                "semantic_cancel_claim_count": 0,
                "active_spot_order_count": 1,
                "live_service_disabled": False,
                "sdk_boundary_sentinel": sentinel,
                "live_coinbase_orders_ran": True,
            }
        )
        base.set_live_service(runtime, enabled=True)
        base.preview_admission(runtime, cancel_context)
        progress_path = runtime.state_dir / "v15-operator-ui-cancel-handoff.json"
        progress = {
            "status": "awaiting_operator_ui_root_scoped_cancel",
            "root_client_order_id": root_id,
            "child_client_order_id": child_id,
            "controlled_plan_sha256": confirmed_plan_sha256,
            "readiness_url": (
                f"{base.BASE_URL}{cancel_path}/readiness?"
                f"controlled_plan_sha256={confirmed_plan_sha256}"
            ),
            "cancel_url": f"{base.BASE_URL}{cancel_path}",
            "idempotency_key": cancel["idempotency_key"],
            "correlation_id": cancel["correlation_id"],
            "operator_intent": cancel["operator_intent"],
            "request_body": cancel_body,
            "runner_cancel_post_submitted": False,
            "runner_cancel_claim_acquired": False,
            "runtime_pid": runtime.process.pid if runtime.process else None,
            "state_dir": str(runtime.state_dir),
            "plan_expires_at": plan["expires_at"],
        }
        base._replace_owner_only_json(progress_path, progress)
        print(json.dumps(progress, sort_keys=True), flush=True)
        last_monitor_status = progress["status"]
        expected_backend_claim_identity = v15_backend_claim_identity(
            plan,
            plan_sha256=confirmed_plan_sha256,
        )
        while True:
            runtime.sdk_boundary_sentinel(
                expected_root_create_order_calls={1},
                expected_child_place_limit_order_calls={1},
            )
            backend_rows = _read_v15_backend_cancel_claim_records(
                BACKEND_CLAIM_LOG_PATH
            )
            placement_rows = _read_owner_only_jsonl(
                PLACEMENT_LEDGER_PATH,
                "v15_placement_ledger",
            )
            local_rows = _read_owner_only_jsonl(
                CANCEL_LEDGER_PATH,
                "v15_cancel_ledger",
            )
            monitor_decision = v15_operator_monitor_decision(
                placement_rows,
                local_rows,
                backend_rows,
                expected_identity=expected_backend_claim_identity,
                now=datetime.now(timezone.utc),
                expires_at=str(plan["expires_at"]),
            )
            if not backend_rows:
                if monitor_decision == (
                    "plan_expired_active_child_reconciliation_only"
                ):
                    summary.update(
                        {
                            "status": monitor_decision,
                            "live_service_disabled": True,
                            "backend_cancel_claim_events": 0,
                        }
                    )
                    break
                _, monitored_readiness, _ = runtime.request(
                    "GET",
                    f"{cancel_path}/readiness",
                    headers=runtime.headers(role="auditor"),
                    params={
                        "controlled_plan_sha256": confirmed_plan_sha256
                    },
                    expected={200},
                )
                _validate_v15_cancel_readiness(
                    monitored_readiness,
                    plan=plan,
                    plan_sha256=confirmed_plan_sha256,
                )
                time.sleep(0.5)
                continue

            latest = dict(backend_rows[-1])
            latest_outcome = str(latest.get("outcome") or "")
            if monitor_decision == "verify_terminal_closeout":
                backend_claim = _validate_v15_backend_cancel_claim_log(
                    BACKEND_CLAIM_LOG_PATH,
                    plan=plan,
                    plan_sha256=confirmed_plan_sha256,
                )
                terminal_child = base.exact_exchange_order(
                    rest_client,
                    child_exchange_order_id,
                )
                terminal_child = base._validate_exact_coinbase_gtc_child_order(
                    terminal_child,
                    expected_exchange_order_id=child_exchange_order_id,
                    expected_portfolio_id=TEST_PORTFOLIO_ID,
                    expected_child_tuple=child_tuple,
                )
                validate_v15_explicit_zero_fill(terminal_child)
                _require(
                    str(terminal_child.get("status") or "").upper()
                    in {"CANCELLED", "CANCELED"},
                    "v15_child_terminal_zero_fill_unproven",
                )
                cancelled_chain = base._validate_cancelled_child_chain(
                    runtime,
                    root_plan=synthetic_root,
                    exchange_order_id=child_exchange_order_id,
                )
                final_active = base.prove_stable_authoritative_active_zero(
                    rest_client,
                    expected_portfolio_id=TEST_PORTFOLIO_ID,
                )
                _require(
                    final_active.get("stable_zero") is True,
                    "v15_final_active_zero_unproven",
                )
                base.set_live_service(runtime, enabled=False)
                sentinel = runtime.sdk_boundary_sentinel(
                    expected_root_create_order_calls={1},
                    expected_child_place_limit_order_calls={1},
                )
                _, final_runtime, _ = runtime.request(
                    "GET",
                    "/admin/runtime",
                    headers=runtime.headers(role="viewer"),
                    expected={200},
                )
                _require(
                    "total_inflight" in final_runtime
                    and final_runtime["total_inflight"] is not None
                    and int(final_runtime["total_inflight"]) == 0,
                    "v15_runtime_not_quiescent_after_operator_cancel",
                )
                runtime.exchange_safe_to_shutdown = True
                terminal_closeout = True
                summary.update(
                    {
                        "status": "passed",
                        "backend_cancel_claim": backend_claim,
                        "backend_cancel_claim_events": 3,
                        "semantic_cancel_claim_count": 1,
                        "cancel_command_count": 1,
                        "child_terminal_status": str(
                            terminal_child.get("status") or ""
                        ).upper(),
                        "cancelled_child_chain": cancelled_chain,
                        "final_active_spot_order_count": 0,
                        "live_service_disabled": True,
                        "sdk_boundary_sentinel": sentinel,
                    }
                )
                break

            _require(
                latest_outcome in {"claimed", "unknown", "rejected"},
                "v15_backend_cancel_claim_outcome_invalid",
            )
            monitor_status = monitor_decision
            if monitor_status != last_monitor_status:
                print(
                    json.dumps(
                        {
                            "status": monitor_status,
                            "root_client_order_id": root_id,
                            "child_client_order_id": child_id,
                            "same_idempotency_key_reconciliation_only": True,
                            "runner_cancel_post_submitted": False,
                            "runtime_preserved": True,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                last_monitor_status = monitor_status
            summary.update(
                {
                    "status": monitor_status,
                    "backend_cancel_claim_events": len(backend_rows),
                    "backend_cancel_latest_outcome": latest_outcome,
                    "same_idempotency_key_reconciliation_only": True,
                }
            )
            if latest_outcome in {"unknown", "rejected"}:
                break
            if monitor_status == (
                "plan_expired_ambiguous_cancel_reconciliation_only"
            ):
                break
            time.sleep(0.5)
    finally:
        if runtime.live_service_may_be_enabled:
            try:
                base.set_live_service(runtime, enabled=False)
            except Exception as exc:
                cleanup["live_service_disable_error"] = (
                    f"{type(exc).__name__}:{exc}"
                )
                runtime.exchange_safe_to_shutdown = False
        cleanup.update(runtime.stop_if_safe())
        summary["runtime_cleanup"] = cleanup
    if terminal_closeout:
        _require(
            cleanup.get("runtime_process_shutdown_proven") is True
            and cleanup.get("runtime_preserved_for_reconciliation") is False,
            "v15_runtime_shutdown_unproven",
        )
        summary["shutdown_quiescent"] = True
    else:
        _require(
            cleanup.get("runtime_process_shutdown_proven") is False
            and cleanup.get("runtime_preserved_for_reconciliation") is True,
            "v15_operator_handoff_runtime_not_preserved",
        )
        summary["shutdown_quiescent"] = False
    base._replace_owner_only_json(
        progress_path,
        {
            **progress,
            "status": summary["status"],
            "runner_cancel_post_submitted": False,
            "runner_cancel_claim_acquired": False,
            "runtime_cleanup": cleanup,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    base._write_owner_only_exclusive_json(
        runtime.state_dir / "controlled-v15-child-cancel-summary.json",
        summary,
        exists_blocker="v15_summary_already_exists",
    )
    return summary


def run_offline_self_test() -> dict[str, Any]:
    preflight = {
        "portfolio_id": TEST_PORTFOLIO_ID,
        "wallets": {"USDC": Decimal("997"), "BTC": Decimal("0")},
        "product": {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
        },
        "best_bid": Decimal("100000.00"),
        "best_ask": Decimal("100000.01"),
        "market": {
            "product_id": PRODUCT_ID,
            "source": "coinbase_rest_get_best_bid_ask_exact_product",
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        "active_spot_order_count": 0,
    }
    plan = build_v15_plan(preflight)
    validate_v15_plan(
        plan,
        expected_hash=str(plan["plan_sha256"]),
        preflight=preflight,
    )
    claim = build_cancel_command_claim(
        plan,
        plan_sha256=str(plan["plan_sha256"]),
        claimed_at=datetime.now(timezone.utc).isoformat(),
    )
    _require(
        cancel_command_claim_decision(
            [claim],
            command=dict(plan["cancel_command"]),
            plan_sha256=str(plan["plan_sha256"]),
        )
        == "same_key_replay",
        "v15_offline_cancel_claim_replay_failed",
    )
    return {
        "status": "offline_self_test_passed",
        "placement_attempt_count": 2,
        "cancel_command_maximum": 1,
        "plan_sha256": plan["plan_sha256"],
        "live_coinbase_orders_ran": False,
        "marker_written": False,
        "placement_ledger_written": False,
        "cancel_ledger_written": False,
        "backend_claim_log_written": False,
        "runtime_started": False,
    }


def _require_prepare_environment() -> None:
    _require(
        _git("rev-list", "--left-right", "--count", "HEAD...origin/main")
        == "0\t0",
        "v15_backend_origin_divergence",
    )
    _require(
        not _git("status", "--porcelain", "--untracked-files=no"),
        "v15_backend_tracked_worktree_not_clean",
    )
    _require(
        _git(
            "rev-list",
            "--left-right",
            "--count",
            "HEAD...origin/main",
            cwd=FRONTEND_ROOT,
        )
        == "0\t0",
        "v15_frontend_origin_divergence",
    )
    _require(
        not _git(
            "status",
            "--porcelain",
            "--untracked-files=no",
            cwd=FRONTEND_ROOT,
        ),
        "v15_frontend_tracked_worktree_not_clean",
    )
    _require(not os.path.lexists(PLAN_PATH), "v15_plan_path_already_exists")


def prepare_v15_plan() -> dict[str, Any]:
    _require_prepare_environment()
    rest_client = base.hydrate_test_credentials()
    preflight = base.coinbase_preflight(rest_client)
    _require(
        preflight.get("portfolio_id") == TEST_PORTFOLIO_ID
        and preflight.get("active_spot_order_count") == 0,
        "v15_prepare_profile_or_active_order_gate_failed",
    )
    active_zero = base.prove_stable_authoritative_active_zero(
        rest_client, expected_portfolio_id=TEST_PORTFOLIO_ID
    )
    _require(active_zero.get("stable_zero") is True, "v15_prepare_active_zero_unproven")
    plan = build_v15_plan(preflight)
    validate_v15_plan(
        plan,
        expected_hash=str(plan["plan_sha256"]),
        preflight=preflight,
    )
    planned_ids = {
        str(dict(plan["root"])["client_order_id"]),
        str(dict(plan["child"])["client_order_id"]),
    }
    local_absence = base.prove_local_scope_with_historical_hidden_child(
        planned_client_order_ids=planned_ids,
        carried_root_plan=base.completed_slot_1_binding_fixture(),
    )
    catalog, pagination = base.read_failed_v6_v7_order_catalog(rest_client)
    matching = [
        row for row in catalog if str(row.get("client_order_id") or "") in planned_ids
    ]
    _require(
        pagination.get("authoritative") is True
        and pagination.get("pagination_complete") is True
        and not matching
        and local_absence.get("planned_ids_absent_from_order_parent") is True
        and local_absence.get("planned_ids_absent_from_stealth_orders") is True
        and local_absence.get("planned_ids_absent_from_fill_ledger") is True
        and local_absence.get("planned_ids_absent_from_order_match_audit") is True,
        "v15_prepare_fresh_identity_absence_unproven",
    )
    write_prepared_v15_plan(PLAN_PATH, plan)
    return {
        "status": "v15_plan_prepared",
        "live_execution_requested": False,
        "plan_file": str(PLAN_PATH),
        "plan_sha256": plan["plan_sha256"],
        "expires_at": plan["expires_at"],
        "placement_attempt_count": 2,
        "root_placement_maximum": 1,
        "child_placement_maximum": 1,
        "cancel_command_maximum": 1,
        "root_reference_notional_usdc": plan["root_reference_notional_usdc"],
        "child_reference_reserve_usdc": plan["child_reference_reserve_usdc"],
        "planned_reference_notional_usdc": plan["planned_reference_notional_usdc"],
        "conservative_reference_notional_usdc": plan[
            "conservative_reference_notional_usdc"
        ],
        "slice_reference_cap_usdc": plan["slice_reference_cap_usdc"],
        "marker_written": False,
        "placement_ledger_written": False,
        "cancel_ledger_written": False,
        "backend_claim_log_written": False,
        "runtime_started": False,
        "live_coinbase_orders_ran": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline-self-test", action="store_true")
    mode.add_argument("--prepare-v15-plan", action="store_true")
    mode.add_argument("--execute-v15-plan", action="store_true")
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--confirm-plan-sha256")
    args = parser.parse_args(argv)
    if args.execute_v15_plan:
        _require(args.plan_file is not None, "v15_execute_plan_file_required")
        _require(
            args.plan_file == PLAN_PATH,
            "v15_execute_plan_file_not_fixed",
        )
        _require(
            args.confirm_plan_sha256 is not None,
            "v15_execute_plan_hash_required",
        )
        confirmed_hash = _validate_lower_sha256(
            args.confirm_plan_sha256,
            "v15_execute_plan_hash_invalid",
        )
        result = execute_v15_plan(
            plan_path=args.plan_file,
            confirmed_plan_sha256=confirmed_hash,
        )
    elif args.offline_self_test:
        _require(
            args.plan_file is None and args.confirm_plan_sha256 is None,
            "v15_non_execute_confirmation_not_allowed",
        )
        result = run_offline_self_test()
    else:
        _require(
            args.plan_file is None and args.confirm_plan_sha256 is None,
            "v15_non_execute_confirmation_not_allowed",
        )
        result = prepare_v15_plan()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
