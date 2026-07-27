"""Pure non-market policy for one operator Reprice Now intent.

The policy deliberately knows nothing about prices, sizes, products,
portfolios, caps, Coinbase clients, or live execution.  It only freezes the
identity and local source-evidence binding that a later, separately authorized
market-binding coordinator would have to consume.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping
from uuid import UUID, uuid5


GOAL_ID = "operator_single_order_reprice_now_v1"
POLICY_REVISION = "SINGLE_ORDER_REPRICE_NOW_INTENT_V1"
_SUCCESSOR_NAMESPACE = UUID("1ebddda7-e04f-4514-a43a-07c8b86f29f6")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OperatorSingleOrderRepriceNowPolicyError(ValueError):
    """A fixed, value-blind local policy rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class OperatorSingleOrderRepriceNowIntent:
    """Immutable non-market intent persisted by the Goal 15 ledger."""

    goal_id: str
    policy_revision: str
    stealth_order_id: str
    source_client_order_id: str
    reserved_successor_client_order_id: str
    root_client_order_id: str
    definition_revision: int
    definition_sha256: str
    source_evidence_sha256: str
    source_status: str
    zero_fill_proven: bool
    system_owned: bool
    direct_parent: bool
    intent_sha256: str

    def to_persisted_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("intent_sha256")
        return payload


def _fail(code: str) -> None:
    raise OperatorSingleOrderRepriceNowPolicyError(code)


def _canonical_uuid(value: Any, *, code: str) -> str:
    try:
        parsed = UUID(str(value or "").strip())
    except (AttributeError, TypeError, ValueError):
        _fail(code)
    canonical = str(parsed)
    if canonical != str(value or "").strip() or parsed.version != 4:
        _fail(code)
    return canonical


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def build_single_order_reprice_now_intent(
    *,
    source: Mapping[str, Any],
) -> OperatorSingleOrderRepriceNowIntent:
    """Freeze one exact canonical REVEALED source without market terms."""

    stealth_order_id = _canonical_uuid(
        source.get("stealth_order_id"),
        code="operator_reprice_now_source_identity_invalid",
    )
    source_client_order_id = _canonical_uuid(
        source.get("source_client_order_id"),
        code="operator_reprice_now_source_identity_invalid",
    )
    root_client_order_id = _canonical_uuid(
        source.get("root_client_order_id"),
        code="operator_reprice_now_source_identity_invalid",
    )
    try:
        definition_revision = int(source.get("definition_revision"))
    except (TypeError, ValueError):
        _fail("operator_reprice_now_definition_binding_invalid")
    definition_sha256 = str(source.get("definition_sha256") or "")
    source_evidence_sha256 = str(
        source.get("source_evidence_sha256") or ""
    )
    if (
        definition_revision < 1
        or _SHA256.fullmatch(definition_sha256) is None
    ):
        _fail("operator_reprice_now_definition_binding_invalid")
    if _SHA256.fullmatch(source_evidence_sha256) is None:
        _fail("operator_reprice_now_source_evidence_invalid")
    if str(source.get("source_status") or "").upper() != "REVEALED":
        _fail("operator_reprice_now_source_not_revealed")
    if source.get("zero_fill_proven") is not True:
        _fail("operator_reprice_now_zero_fill_not_proven")
    if source.get("system_owned") is not True:
        _fail("operator_reprice_now_source_not_system_owned")
    if (
        source.get("direct_parent") is not True
        or root_client_order_id != stealth_order_id
    ):
        _fail("operator_reprice_now_source_not_direct_parent")
    successor = str(
        uuid5(
            _SUCCESSOR_NAMESPACE,
            ":".join(
                (
                    GOAL_ID,
                    stealth_order_id,
                    source_client_order_id,
                    definition_sha256,
                    source_evidence_sha256,
                )
            ),
        )
    )
    payload = {
        "goal_id": GOAL_ID,
        "policy_revision": POLICY_REVISION,
        "stealth_order_id": stealth_order_id,
        "source_client_order_id": source_client_order_id,
        "reserved_successor_client_order_id": successor,
        "root_client_order_id": root_client_order_id,
        "definition_revision": definition_revision,
        "definition_sha256": definition_sha256,
        "source_evidence_sha256": source_evidence_sha256,
        "source_status": "REVEALED",
        "zero_fill_proven": True,
        "system_owned": True,
        "direct_parent": True,
    }
    return OperatorSingleOrderRepriceNowIntent(
        **payload,
        intent_sha256=_hash_payload(payload),
    )


__all__ = [
    "GOAL_ID",
    "POLICY_REVISION",
    "OperatorSingleOrderRepriceNowIntent",
    "OperatorSingleOrderRepriceNowPolicyError",
    "build_single_order_reprice_now_intent",
]
