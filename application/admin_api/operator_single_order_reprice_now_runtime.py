"""Call-free canonical source resolver for one Reprice Now intent."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Mapping


class OperatorSingleOrderRepriceNowSourceResolver:
    """Project exact local exchange-truth evidence without market terms."""

    def __init__(
        self,
        *,
        manager: Any,
        configured_portfolio_id: str,
    ) -> None:
        self.manager = manager
        self.configured_portfolio_id = str(
            configured_portfolio_id or ""
        ).strip()

    def resolve(
        self,
        *,
        definition: Mapping[str, Any],
        stealth_order_id: str,
        source_client_order_id: str,
    ) -> dict[str, Any]:
        base = {
            "stealth_order_id": stealth_order_id,
            "source_client_order_id": source_client_order_id,
            "found": False,
            "eligible": False,
            "diagnostic_code": "operator_reprice_now_source_unavailable",
            "definition_revision": None,
            "definition_sha256": None,
            "root_client_order_id": None,
            "source_status": None,
            "zero_fill_proven": False,
            "system_owned": False,
            "direct_parent": False,
            "source_evidence_sha256": None,
        }
        try:
            definition_id = str(definition["definition_id"])
            definition_revision = int(definition["revision"])
            definition_sha256 = str(definition["definition_sha256"])
        except (KeyError, TypeError, ValueError):
            return {
                **base,
                "diagnostic_code": (
                    "operator_reprice_now_definition_binding_invalid"
                ),
            }
        if definition_id != stealth_order_id:
            return {
                **base,
                "diagnostic_code": (
                    "operator_reprice_now_definition_binding_invalid"
                ),
            }
        state = self.manager._get_stealth_order(stealth_order_id)
        state = state if isinstance(state, Mapping) else {}
        if not state:
            return base
        found = {
            **base,
            "found": True,
            "definition_revision": definition_revision,
            "definition_sha256": definition_sha256,
            "source_status": str(state.get("status") or "").upper() or None,
        }
        anchor = state.get("anchor_repricing_state_json")
        anchor = anchor if isinstance(anchor, Mapping) else {}
        source_reader = getattr(
            self.manager,
            "get_operator_stealth_move_source_placement",
            None,
        )
        if not callable(source_reader):
            return found
        try:
            placement = source_reader(stealth_order_id)
        except Exception:
            return found
        placement = placement if isinstance(placement, Mapping) else {}
        raw_exchange_id = str(
            anchor.get("active_exchange_order_id") or ""
        )
        placement_exchange_id = str(
            placement.get("exchange_order_id") or ""
        )
        if (
            not raw_exchange_id
            or not placement_exchange_id
            or raw_exchange_id != placement_exchange_id
            or str(
                anchor.get("active_placement_client_order_id") or ""
            )
            != source_client_order_id
            or str(placement.get("client_order_id") or "")
            != source_client_order_id
        ):
            return {
                **found,
                "diagnostic_code": (
                    "operator_reprice_now_source_identity_mismatch"
                ),
            }
        if str(state.get("status") or "").upper() != "REVEALED":
            return {
                **found,
                "diagnostic_code": (
                    "operator_reprice_now_source_not_revealed"
                ),
            }
        try:
            executed = Decimal(str(state.get("executed_size") or "0"))
            remaining = Decimal(str(state["remaining_size"]))
            source_size = Decimal(str(placement["size"]))
        except (InvalidOperation, KeyError, TypeError, ValueError):
            return {
                **found,
                "diagnostic_code": (
                    "operator_reprice_now_zero_fill_not_proven"
                ),
            }
        zero_fill = bool(
            executed.is_finite()
            and executed == 0
            and remaining.is_finite()
            and remaining == 0
            and source_size.is_finite()
            and source_size > 0
            and state.get("allow_partial_fills") is False
            and placement.get("allow_partial_fills") is False
            and str(placement.get("status") or "").upper()
            in {"PENDING", "SUBMITTED", "OPEN"}
        )
        if not zero_fill:
            return {
                **found,
                "diagnostic_code": (
                    "operator_reprice_now_zero_fill_not_proven"
                ),
            }
        expected_portfolio_id = str(
            getattr(
                self.manager,
                "expected_retail_portfolio_id",
                "",
            )
            or ""
        )
        if (
            not self.configured_portfolio_id
            or expected_portfolio_id != self.configured_portfolio_id
            or str(placement.get("retail_portfolio_id") or "")
            != self.configured_portfolio_id
        ):
            return {
                **found,
                "zero_fill_proven": True,
                "diagnostic_code": (
                    "operator_reprice_now_source_not_system_owned"
                ),
            }
        root_resolver = getattr(
            self.manager,
            "resolve_operator_stealth_chain_root",
            None,
        )
        try:
            if callable(root_resolver):
                root_client_order_id = str(
                    root_resolver(stealth_order_id)
                )
            else:
                from core.stealth_order_manager import (
                    resolve_stealth_chain_root,
                )

                root_client_order_id = str(
                    resolve_stealth_chain_root(dict(state))
                )
        except Exception:
            return {
                **found,
                "zero_fill_proven": True,
                "system_owned": True,
                "diagnostic_code": (
                    "operator_reprice_now_source_not_direct_parent"
                ),
            }
        if root_client_order_id != stealth_order_id:
            return {
                **found,
                "root_client_order_id": root_client_order_id,
                "zero_fill_proven": True,
                "system_owned": True,
                "diagnostic_code": (
                    "operator_reprice_now_source_not_direct_parent"
                ),
            }
        evidence = {
            "stealth_order_id": stealth_order_id,
            "source_client_order_id": source_client_order_id,
            "definition_revision": definition_revision,
            "definition_sha256": definition_sha256,
            "root_client_order_id": root_client_order_id,
            "source_status": "REVEALED",
            "zero_fill_proven": True,
            "system_owned": True,
            "direct_parent": True,
        }
        source_evidence_sha256 = hashlib.sha256(
            json.dumps(
                evidence,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return {
            **found,
            **evidence,
            "eligible": True,
            "diagnostic_code": "operator_reprice_now_source_eligible",
            "source_evidence_sha256": source_evidence_sha256,
        }


def get_operator_single_order_reprice_now_source_resolver(
) -> OperatorSingleOrderRepriceNowSourceResolver:
    try:
        import os
        import dashboard_server

        bridge = getattr(dashboard_server, "stealth_order_bridge", None)
        manager = getattr(bridge, "stealth_manager", None) if bridge else None
        if manager is None:
            raise RuntimeError
        return OperatorSingleOrderRepriceNowSourceResolver(
            manager=manager,
            configured_portfolio_id=str(
                os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID")
                or ""
            ).strip(),
        )
    except Exception:
        raise RuntimeError(
            "operator_reprice_now_source_resolver_unavailable"
        ) from None


__all__ = [
    "OperatorSingleOrderRepriceNowSourceResolver",
    "get_operator_single_order_reprice_now_source_resolver",
]
