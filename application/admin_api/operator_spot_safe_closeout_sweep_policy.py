"""Pure candidate validation and immutable cancel-only plan construction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid5

from application.admin_api.operator_spot_safe_closeout_sweep_models import (
    GOAL_ID,
    POLICY_REVISION,
)


MAX_ITEMS = 3
_SWEEP_NAMESPACE = UUID("1d7c8f5a-5132-5f2e-a91f-9d9d743b1aa7")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ACTIVE_STATUSES = frozenset({"PENDING", "OPEN", "QUEUED"})
_PROVENANCES = frozenset(
    {"ADMIN_FILL_FOLLOW_UP", "ADMIN_HOTPOINT_CHILD"}
)


class OperatorSpotSafeCloseoutSweepPolicyError(ValueError):
    """Fixed value-blind Goal 16 policy rejection."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OperatorSpotSafeCloseoutSweepPlanItem:
    position: int
    client_order_id: str
    root_client_order_id: str
    product_id: str
    status: str
    ownership_provenance: str
    portfolio_scope_sha256: str
    predecessor_evidence_sha256: str
    candidate_evidence_sha256: str


@dataclass(frozen=True, slots=True)
class OperatorSpotSafeCloseoutSweepPlan:
    goal_id: str
    policy_revision: str
    sweep_id: str
    configured_portfolio_scope_sha256: str
    max_items: int
    zero_creates: bool
    items: tuple[OperatorSpotSafeCloseoutSweepPlanItem, ...]
    private_exchange_bindings: tuple[tuple[str, str], ...]
    plan_sha256: str

    def to_persisted_payload(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "policy_revision": self.policy_revision,
            "sweep_id": self.sweep_id,
            "configured_portfolio_scope_sha256": (
                self.configured_portfolio_scope_sha256
            ),
            "max_items": self.max_items,
            "zero_creates": self.zero_creates,
            "items": [asdict(item) for item in self.items],
        }


def _fail(code: str) -> None:
    raise OperatorSpotSafeCloseoutSweepPolicyError(code)


def _canonical_uuid(value: Any, *, code: str) -> str:
    normalized = str(value or "").strip()
    try:
        parsed = UUID(normalized)
    except (AttributeError, TypeError, ValueError):
        _fail(code)
    if str(parsed) != normalized:
        _fail(code)
    return normalized


def _sha256(value: Any, *, code: str) -> str:
    normalized = str(value or "")
    if _SHA256.fullmatch(normalized) is None:
        _fail(code)
    return normalized


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def build_operator_spot_safe_closeout_sweep_plan(
    *,
    candidates: Sequence[Mapping[str, Any]],
    configured_portfolio_scope_sha256: str,
) -> OperatorSpotSafeCloseoutSweepPlan:
    """Freeze one ordered, max-three, Cancel-only local plan."""

    configured_hash = _sha256(
        configured_portfolio_scope_sha256,
        code="operator_spot_sweep_portfolio_configuration_invalid",
    )
    if not 1 <= len(candidates) <= MAX_ITEMS:
        _fail("operator_spot_sweep_item_count_invalid")
    items: list[OperatorSpotSafeCloseoutSweepPlanItem] = []
    seen: set[str] = set()
    for position, candidate in enumerate(candidates, start=1):
        client_order_id = _canonical_uuid(
            candidate.get("client_order_id"),
            code="operator_spot_sweep_candidate_identity_invalid",
        )
        root_client_order_id = _canonical_uuid(
            candidate.get("root_client_order_id"),
            code="operator_spot_sweep_root_identity_invalid",
        )
        if client_order_id in seen:
            _fail("operator_spot_sweep_duplicate_candidate")
        seen.add(client_order_id)
        if root_client_order_id == client_order_id:
            _fail("operator_spot_sweep_candidate_not_child")
        if str(candidate.get("product_id") or "") != "BTC-USDC":
            _fail("operator_spot_sweep_candidate_product_invalid")
        status = str(candidate.get("status") or "").upper()
        if status not in _ACTIVE_STATUSES:
            _fail("operator_spot_sweep_candidate_not_active")
        provenance = str(
            candidate.get("ownership_provenance") or ""
        )
        if provenance not in _PROVENANCES:
            _fail("operator_spot_sweep_candidate_not_system_child")
        portfolio_hash = _sha256(
            candidate.get("portfolio_scope_sha256"),
            code="operator_spot_sweep_candidate_evidence_invalid",
        )
        if portfolio_hash != configured_hash:
            _fail("operator_spot_sweep_candidate_portfolio_mismatch")
        item = OperatorSpotSafeCloseoutSweepPlanItem(
            position=position,
            client_order_id=client_order_id,
            root_client_order_id=root_client_order_id,
            product_id="BTC-USDC",
            status=status,
            ownership_provenance=provenance,
            portfolio_scope_sha256=portfolio_hash,
            predecessor_evidence_sha256=_sha256(
                candidate.get("predecessor_evidence_sha256"),
                code="operator_spot_sweep_predecessor_evidence_invalid",
            ),
            candidate_evidence_sha256=_sha256(
                candidate.get("candidate_evidence_sha256"),
                code="operator_spot_sweep_candidate_evidence_invalid",
            ),
        )
        items.append(item)
    sweep_id = str(
        uuid5(
            _SWEEP_NAMESPACE,
            ":".join(
                [
                    GOAL_ID,
                    configured_hash,
                    *(
                        item.candidate_evidence_sha256
                        for item in items
                    ),
                ]
            ),
        )
    )
    payload = {
        "goal_id": GOAL_ID,
        "policy_revision": POLICY_REVISION,
        "sweep_id": sweep_id,
        "configured_portfolio_scope_sha256": configured_hash,
        "max_items": MAX_ITEMS,
        "zero_creates": True,
        "items": [asdict(item) for item in items],
    }
    return OperatorSpotSafeCloseoutSweepPlan(
        goal_id=GOAL_ID,
        policy_revision=POLICY_REVISION,
        sweep_id=sweep_id,
        configured_portfolio_scope_sha256=configured_hash,
        max_items=MAX_ITEMS,
        zero_creates=True,
        items=tuple(items),
        private_exchange_bindings=tuple(
            (
                item.client_order_id,
                _sha256(
                    candidate.get("exchange_order_id_sha256"),
                    code=(
                        "operator_spot_sweep_candidate_evidence_invalid"
                    ),
                ),
            )
            for item, candidate in zip(items, candidates, strict=True)
        ),
        plan_sha256=_canonical_hash(payload),
    )


__all__ = [
    "MAX_ITEMS",
    "OperatorSpotSafeCloseoutSweepPlan",
    "OperatorSpotSafeCloseoutSweepPlanItem",
    "OperatorSpotSafeCloseoutSweepPolicyError",
    "build_operator_spot_safe_closeout_sweep_plan",
]
